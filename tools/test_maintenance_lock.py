"""Exercise protected lease semantics with disposable files; never touch host locks."""

import os
from pathlib import Path
import subprocess
import shlex
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installers.desktop import locking


@unittest.skipUnless(os.name == "nt" or getattr(os, "geteuid", lambda: -1)() == 0,
                     "Protected POSIX lease fixtures run in the separate root-only CI step")
class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch.object(locking, "lock_directory", return_value=self.directory).start()
        patch.object(locking, "_secure_directory").start()
        patch.object(locking, "_private_owner").start()
        def fixture_private(path, content):
            with Path(path).open("xb") as stream:
                stream.write(content)
            if os.name != "nt":
                Path(path).chmod(0o600)
        patch.object(locking, "create_private_file", side_effect=fixture_private).start()
        patch.object(locking, "create_private_directory", side_effect=lambda path: Path(path).mkdir(mode=0o700)).start()
        patch.dict(os.environ).start()
        os.environ.pop(locking.VARIABLE, None)

    def test_nested_delegate_requires_matching_token_and_owner_creation_identity(self):
        with locking.operation_lock():
            token = os.environ[locking.VARIABLE]
            with locking.operation_lock():
                self.assertEqual(os.environ[locking.VARIABLE], token)
            self.assertTrue((self.directory / "lease").exists())
        self.assertFalse((self.directory / "lease").exists())
        self.assertNotIn(locking.VARIABLE, os.environ)

    def test_competitor_without_token_cannot_join_live_lease(self):
        with locking.operation_lock():
            token = os.environ.pop(locking.VARIABLE)
            with self.assertRaisesRegex(RuntimeError, "Another maintenance"):
                with locking.operation_lock():
                    self.fail("Joined another owner's operation")
            os.environ[locking.VARIABLE] = token

    def test_supplied_token_does_not_override_process_identity(self):
        token = "b" * 32
        path = self.directory / "lease"
        path.write_text(f"{os.getpid()}\n0\n{token}\n")
        if os.name != "nt":
            path.chmod(0o600)
        os.environ[locking.VARIABLE] = token
        with self.assertRaisesRegex(RuntimeError, "Another maintenance"):
            with locking.operation_lock():
                self.fail("Accepted stale process identity")
        self.assertTrue(path.exists())

    def test_failure_releases_own_lease(self):
        with self.assertRaisesRegex(ValueError, "fixture"):
            with locking.operation_lock():
                raise ValueError("fixture")
        self.assertFalse((self.directory / "lease").exists())

    def test_invalid_record_is_never_stolen(self):
        path = self.directory / "lease"
        path.write_text("not a lease")
        if os.name != "nt":
            path.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "Invalid maintenance"):
            with locking.operation_lock():
                self.fail("Invalid record replaced")
        self.assertEqual(path.read_text(), "not a lease")

    @unittest.skipIf(os.name == "nt", "POSIX O_NOFOLLOW contract")
    def test_lease_symlink_is_rejected_without_touching_target(self):
        target = self.directory / "retained"
        target.write_text("retained")
        (self.directory / "lease").symlink_to(target)
        with self.assertRaises(OSError):
            with locking.operation_lock():
                self.fail("Followed lease symlink")
        self.assertEqual(target.read_text(), "retained")

    def test_running_consumers_block_independent_removal(self):
        response = subprocess.CompletedProcess([], 0, "STATE : 4 RUNNING\nActiveState=active\nLoadState=loaded\n", "")
        with patch.object(locking.subprocess, "run", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "Stop MeshCore EMS"):
                locking.require_consumers_stopped()

    def orphan(self, *, child=False, protocol=True):
        token = "a" * 32
        path = self.directory / "lease"
        path.write_text("999991\n1\n" + token + "\n")
        if os.name != "nt":
            path.chmod(0o600)
        if protocol:
            group = self.directory / ("participants-" + token)
            group.mkdir()
            (group / "PROTOCOL").write_text("2\n")
            if child:
                item = group / "999992-2.participant"
                item.write_text("999992\n2\n" + token + "\n")
                if os.name != "nt":
                    item.chmod(0o600)
        return path

    def test_reviewed_orphan_recovery_preserves_dataset_lock_and_archives_evidence(self):
        path = self.orphan(child=True)
        dataset_lock = self.directory / ".datasets.lock"
        dataset_lock.write_text("retained recovery material")
        with patch.object(locking, "_process_state", return_value="dead"), patch.object(locking, "_native_process_gate", return_value=[]):
            state = locking.inspect_recovery()
            self.assertTrue(state["recoverable"])
            result = locking.recover_interrupted(state["revision"])
        self.assertTrue(result["released"])
        self.assertFalse(path.exists())
        self.assertTrue(list(self.directory.glob("orphan-*")))
        self.assertEqual(dataset_lock.read_text(), "retained recovery material")

    def test_live_delegated_participant_blocks_recovery_even_after_owner_exits(self):
        self.orphan(child=True)
        def process_state(pid, identity):
            return "live" if str(pid) == "999992" else "dead"
        with patch.object(locking, "_process_state", side_effect=process_state):
            state = locking.inspect_recovery()
            self.assertFalse(state["recoverable"])
            with self.assertRaisesRegex(RuntimeError, "participant"):
                locking.recover_interrupted(state["revision"])

    def test_orphan_native_subcommand_blocks_recovery_after_wrappers_exit(self):
        self.orphan()
        native = [{"pid": 999993, "state": "unknown", "role": "potential native maintenance"}]
        with patch.object(locking, "_process_state", return_value="dead"), patch.object(locking, "_native_process_gate", return_value=native):
            self.assertFalse(locking.inspect_recovery()["recoverable"])

    def test_legacy_lease_without_participant_evidence_cannot_be_recovered(self):
        self.orphan(protocol=False)
        with patch.object(locking, "_process_state", return_value="dead"):
            state = locking.inspect_recovery()
        self.assertFalse(state["recoverable"])
        self.assertIn("legacy", state["detail"].lower())

    def test_changed_recovery_evidence_invalidates_approval(self):
        path = self.orphan()
        with patch.object(locking, "_process_state", return_value="dead"), patch.object(locking, "_native_process_gate", return_value=[]):
            state = locking.inspect_recovery()
            (path.parent / ("participants-" + "a" * 32) / "unknown").write_text("unknown")
            with self.assertRaisesRegex(RuntimeError, "changed"):
                locking.recover_interrupted(state["revision"])

    def test_guard_left_after_lease_archive_has_reviewed_recovery(self):
        guard = self.directory / "recovery-guard"
        guard.write_text("999991\n1\n" + "b" * 32 + "\n")
        if os.name != "nt":
            guard.chmod(0o600)
        with patch.object(locking, "_process_state", return_value="dead"), patch.object(locking, "_native_process_gate", return_value=[]):
            state = locking.inspect_recovery()
            self.assertTrue(state["recoverable"])
            locking.recover_interrupted(state["revision"])
        self.assertFalse(guard.exists())

    @unittest.skipUnless(os.name == "nt", "Windows conservative CIM process gate")
    def test_windows_process_gate_blocks_other_python_but_excludes_own_query(self):
        import json
        rows = [{"ProcessId": os.getpid(), "Name": "python.exe"},
                {"ProcessId": 7777, "Name": "powershell.exe"},
                {"ProcessId": 8888, "Name": "python.exe"},
                {"ProcessId": 9999, "Name": "unins000.exe"},
                {"ProcessId": 2001, "Name": "sc.exe"},
                {"ProcessId": 2002, "Name": "icacls.exe"},
                {"ProcessId": 2003, "Name": "taskkill.exe"},
                {"ProcessId": 2004, "Name": "Dataset.exe"},
                {"ProcessId": 2005, "Name": "unins000.tmp"},
                {"ProcessId": 4444, "Name": "explorer.exe"}]
        process = SimpleNamespace(pid=7777, returncode=0, communicate=lambda timeout: (json.dumps(rows), ""))
        with patch.object(locking.subprocess, "Popen", return_value=process):
            found = locking._native_process_gate("a" * 32)
        self.assertEqual([item["pid"] for item in found], [2001, 2002, 2003, 2004, 2005, 8888, 9999])
        self.assertTrue(all(item["state"] == "unknown" for item in found))

    @unittest.skipUnless(os.name == "nt", "Windows current recovery delegation gate")
    def test_windows_gate_excludes_only_verified_participants_of_different_current_lease(self):
        import json
        token = "b" * 32
        locking.create_private_file(self.directory / "lease", f"{os.getpid()}\n1\n{token}\n".encode())
        group = self.directory / ("participants-" + token)
        group.mkdir()
        (group / "PROTOCOL").write_text("2\n")
        locking.create_private_file(group / "2004-44.participant", f"2004\n44\n{token}\n".encode())
        os.environ[locking.VARIABLE] = token
        rows = [{"ProcessId": 2004, "Name": "Dataset.exe"}, {"ProcessId": 2001, "Name": "sc.exe"}]
        process = SimpleNamespace(pid=7777, returncode=0, communicate=lambda timeout: (json.dumps(rows), ""))
        with patch.object(locking.subprocess, "Popen", return_value=process), patch.object(locking, "_process_state", return_value="live"):
            self.assertEqual([item["pid"] for item in locking._native_process_gate("a" * 32)], [2001])
            self.assertEqual([item["pid"] for item in locking._native_process_gate(token)], [2001, 2004])

    @unittest.skipIf(os.name == "nt", "POSIX exact inherited-token process gate")
    def test_posix_process_gate_matches_only_complete_environment_value(self):
        token = "a" * 32
        for pid, value in (("999991", token), ("999992", token + "bad")):
            path = self.directory / pid
            path.mkdir()
            (path / "environ").write_bytes((locking.VARIABLE + "=" + value + "\0OTHER=fixture\0").encode())
        original = Path
        with patch.object(locking, "Path", side_effect=lambda value: self.directory if value == "/proc" else original(value)):
            found = locking._native_process_gate(token)
        self.assertEqual([item["pid"] for item in found], [999991])

    @unittest.skipIf(os.name == "nt", "Native Bash lease helper requires Linux")
    def test_native_shell_children_delegate_without_releasing_parent_lease(self):
        helper = self.directory / "fixture-lock.sh"
        source = (Path(__file__).resolve().parents[1] / "installers/desktop/maintenance_lock.sh").read_text()
        location = self.directory / "native-lease"
        source = source.replace("meshcore_lock_directory=/run/meshcore-ems-maintenance", "meshcore_lock_directory=" + shlex.quote(str(location)))
        helper.write_text(source)
        script = '''set -euo pipefail
source "$1"
meshcore_lock_acquire
test -f "$meshcore_lock_file"
bash -c 'source "$1"; meshcore_lock_acquire; meshcore_lock_release' child "$1"
test -f "$meshcore_lock_file"
if env -u MESHCORE_MAINTENANCE_LEASE bash -c 'source "$1"; meshcore_lock_acquire' competitor "$1"; then exit 27; fi
meshcore_lock_release
test ! -e "$meshcore_lock_file"
'''
        result = subprocess.run(["/bin/bash", "-c", script, "fixture", str(helper)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
