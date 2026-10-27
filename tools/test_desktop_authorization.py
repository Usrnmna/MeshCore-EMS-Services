"""Offline contracts for graphical privilege requests and dataset safety."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class DesktopAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.staging = tempfile.TemporaryDirectory()
        self.addCleanup(self.staging.cleanup)
        from tools.test_desktop_staging import fixture_staging
        fixture_staging(self, Path(self.staging.name))

    def test_worker_command_is_fixed_and_source_imports_are_isolated(self):
        from installers.desktop import authorization
        with patch.object(authorization.sys, "frozen", False, create=True):
            command = authorization.worker_command(Path("/tmp/reviewed request.json"))
        self.assertEqual(command[1], "-I")
        self.assertEqual(command[-2:], ["--desktop-worker", str(Path("/tmp/reviewed request.json"))])
        self.assertNotIn("-c", command)

    def test_unknown_operation_kind_is_rejected_before_dispatch(self):
        from installers.desktop import authorization
        with self.assertRaises(ValueError):
            authorization.validate_envelope({"kind": "shell", "command": "anything"})

    def test_dataset_request_never_accepts_command_arguments(self):
        from installers.datasets.gui import privileges
        request = {"kind": "dataset", "action": "install_selected", "selected": ["ebmud"],
                   "root": str(ROOT / "data"), "folder": str(ROOT / "dist"),
                   "target": "windows-x64", "plan_digest": "a" * 64, "command": ["shell"]}
        with self.assertRaises(ValueError):
            privileges.validate_request(request)

    def test_dataset_request_rejects_relative_path_and_unknown_selection(self):
        from installers.datasets.gui import privileges
        request = {"kind": "dataset", "action": "install_selected", "selected": ["ebmud"],
                   "root": str(ROOT / "data"), "folder": str(ROOT / "dist"),
                   "target": "windows-x64", "plan_digest": "a" * 64}
        self.assertEqual(privileges.validate_request(request), request)
        for field, value in (("root", "relative"), ("selected", ["../../other"]),
                             ("action", "purge"), ("plan_digest", "changed")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                privileges.validate_request(dict(request, **{field: value}))

    def test_consumer_removal_is_blocked_when_active_or_unknown(self):
        from installers.datasets.gui import privileges
        for state in ("running", "unknown", "start_pending"):
            with self.subTest(state=state), self.assertRaises(RuntimeError):
                privileges.require_stopped("windows-x64", query=lambda target: state)
        for state in ("stopped", "missing"):
            privileges.require_stopped("windows-x64", query=lambda target: state)

    def test_windows_state_query_uses_fixed_service_and_numeric_state(self):
        from installers.datasets.gui import privileges
        import subprocess
        result = subprocess.CompletedProcess([], 0, "STATE : 4 RUNNING", "")
        with patch.object(privileges.subprocess, "run", return_value=result) as run:
            self.assertEqual(privileges.service_state("windows-x64"), "running")
        self.assertEqual(run.call_args.args[0][-2:], ["query", "MeshCoreEMS"])

    def test_changed_reviewed_plan_fails_before_native_operation(self):
        from installers.datasets.gui import privileges, discovery, planning
        snapshot = discovery.demo_snapshot(ROOT / "data", "windows-x64")
        plan = planning.make_plan(snapshot, "install_selected", ["ebmud"], ROOT / "dist", demo=True)
        request = dict(kind="dataset", action="install_selected", selected=["ebmud"],
                       root=str(ROOT / "data"), folder=str(ROOT / "dist"),
                       target="windows-x64", plan_digest="a" * 64)
        with patch.object(privileges, "native_target", return_value="windows-x64"), \
             patch.object(privileges, "inspect", return_value=snapshot), \
             patch.object(privileges, "make_plan", return_value=plan), \
             patch.object(privileges, "run_batch") as run:
            with self.assertRaises(RuntimeError):
                privileges.perform(request, lambda text: None, threading.Event())
        run.assert_not_called()

    def test_cancel_before_authorization_starts_no_process(self):
        from installers.desktop import authorization
        cancel = threading.Event()
        cancel.set()
        with patch.object(authorization, "launch_worker") as launch:
            with self.assertRaises(RuntimeError):
                authorization.run_authorized({"kind": "dataset"}, lambda text: None, cancel)
        launch.assert_not_called()

    def test_authorized_snapshot_round_trip_preserves_native_paths_and_commands(self):
        from installers.datasets.gui import privileges, discovery
        original = discovery.demo_snapshot(ROOT / "data", "windows-x64")
        with patch.object(privileges, "inspect", side_effect=PermissionError("protected data")), \
             patch.object(privileges, "run_authorized", return_value=privileges.snapshot_payload(original)) as authorize:
            actual = privileges.inspect_with_authorization(ROOT / "data", "windows-x64", lambda message: None)
        self.assertEqual(actual, original)
        self.assertEqual(authorize.call_args.args[0]["action"], "inspect")

    def test_authorization_refusal_is_not_reported_as_success(self):
        from installers.desktop import authorization
        from types import SimpleNamespace
        process = SimpleNamespace(poll=lambda: 126)
        with patch.object(authorization, "launch_worker", return_value=process), self.assertRaises(RuntimeError):
            authorization.run_authorized({"kind": "dataset"}, lambda message: None)

    def test_linux_authorization_disables_text_fallback_and_uses_no_shell(self):
        from installers.desktop import authorization
        with patch.object(authorization.os, "name", "posix"), \
             patch.object(authorization.shutil, "which", return_value="/usr/bin/pkexec"), \
             patch.object(authorization.subprocess, "Popen") as launch:
            authorization.launch_worker(["/kit/manager", "--desktop-worker", "/tmp/session/request.json"])
        self.assertEqual(launch.call_args.args[0][:2], ["/usr/bin/pkexec", "--disable-internal-agent"])
        self.assertNotIn("shell", launch.call_args.kwargs)

    def test_setup_hash_change_blocks_before_execution(self):
        from installers.datasets.gui import privileges, planning
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "setup.exe"
            source.write_bytes(b"changed bytes")
            operation = planning.Operation("ebmud", "setup", (str(source), "/VERYSILENT"),
                                           "reviewed", Path(folder), "0" * 64)
            with patch("installers.desktop.windows_trust.validate_paths"), patch.object(privileges, "run_process") as launch, self.assertRaises(ValueError):
                privileges._launch_checked(operation, lambda message: None, "windows-x64")
            launch.assert_not_called()

    def test_setup_executes_private_checked_copy_instead_of_mutable_original(self):
        from installers.datasets.gui import privileges, planning
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "setup with spaces.exe"
            source.write_bytes(b"reviewed installer")
            operation = planning.Operation("ebmud", "setup", (str(source), "/VERYSILENT"),
                                           "reviewed", Path(folder), hashlib.sha256(source.read_bytes()).hexdigest())
            staged_paths = []
            def launch(staged, emit):
                staged_path = Path(staged.command[0])
                staged_paths.append(staged_path)
                self.assertNotEqual(staged_path, source)
                source.write_bytes(b"replaced original")
                self.assertEqual(staged_path.read_bytes(), b"reviewed installer")
                return 0
            with patch("installers.desktop.windows_trust.validate_paths"), patch.object(privileges, "run_process", side_effect=launch):
                self.assertEqual(privileges._launch_checked(operation, lambda message: None, "windows-x64"), 0)
            self.assertFalse(staged_paths[0].exists())

    def test_authorized_backend_failure_is_reported(self):
        from installers.desktop import authorization
        from types import SimpleNamespace
        def launch(command):
            directory = Path(command[-1]).parent
            (directory / "result.json").write_text(json.dumps({"ok": False, "error": "safe failure"}))
            return SimpleNamespace(poll=lambda: 1)
        with patch.object(authorization, "launch_worker", side_effect=launch), self.assertRaisesRegex(RuntimeError, "safe failure"):
            authorization.run_authorized({"kind": "dataset"}, lambda message: None)

    def test_symlink_request_location_is_rejected(self):
        from installers.desktop import authorization
        with patch.object(authorization.Path, "is_absolute", return_value=True), \
             patch.object(authorization.Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
            authorization._worker_request(Path("/tmp/request.json"))

    def test_worker_session_blocks_parent_redirection(self):
        """Directory replacement cannot redirect an authorized worker's output."""
        from installers.desktop import authorization
        import os
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            original = base / "session"
            original.mkdir(mode=0o700)
            request = original / "request.json"
            request.write_text(json.dumps({"kind": "dataset"}), encoding="utf-8")
            if os.name != "nt":
                request.chmod(0o600)
            victim = base / "unrelated"
            victim.mkdir()
            with authorization.worker_session(request) as session:
                if os.name == "nt":
                    with self.assertRaises(PermissionError):
                        original.rename(base / "moved-session")
                else:
                    original.rename(base / "moved-session")
                    original.symlink_to(victim, target_is_directory=True)
                descriptor = session.open_output("result.json")
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write("reviewed result")
                self.assertEqual(list(victim.iterdir()), [])
                self.assertFalse(session.cancelled())
            if os.name != "nt":
                self.assertEqual((base / "moved-session/result.json").read_text(), "reviewed result")
                original.unlink()

    def test_worker_session_holds_request_immutable_until_dispatch_finishes(self):
        """The Windows request file cannot be swapped or edited under the worker."""
        import os
        if os.name != "nt":
            self.skipTest("Windows sharing contract; POSIX reads via its anchored descriptor")
        from installers.desktop import authorization
        with tempfile.TemporaryDirectory() as temporary:
            request = Path(temporary) / "request.json"
            request.write_text(json.dumps({"kind": "dataset"}))
            with authorization.worker_session(request):
                with self.assertRaises(PermissionError):
                    request.write_text(json.dumps({"kind": "service"}))
                with self.assertRaises(PermissionError):
                    request.rename(request.with_name("replaced.json"))

    def test_unprivileged_worker_does_not_open_a_session(self):
        from installers.desktop import authorization
        with patch.object(authorization, "worker_privileged", return_value=False), \
             patch.object(authorization, "worker_session") as session:
            with self.assertRaises(PermissionError):
                authorization.worker_main("untrusted/request.json")
        session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
