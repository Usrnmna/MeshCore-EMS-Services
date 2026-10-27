"""Service-owner contracts for unified maintenance, using disposable fixtures only."""
import hashlib
from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from installers.desktop import service_backend as backend
import test_desktop_service as service_tests


class NativeStartupPolicyTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "Native shell policy fixture")
    def test_linux_fresh_staging_and_upgrade_boot_policies(self):
        source = (Path(__file__).resolve().parents[1] / "installers/linux/install.sh").read_text()
        begin = source.index("configure_startup_policy() {")
        function = source[begin:source.index("\n}", begin) + 2]
        for previous, existing, start, expected in (("", 0, 0, "disable"), ("", 0, 1, "enable"),
                                                     ("enabled", 1, 0, "enable"), ("disabled", 1, 0, "disable"),
                                                     ("disabled", 1, 1, "disable"), ("masked", 1, 0, None)):
            script = function + '\nsystemctl() { printf "POLICY:%s\\n" "$1"; }\nconfigure_startup_policy "$1" "$2" "$3"'
            result = subprocess.run(["/bin/bash", "-eu", "-c", script, "policy-fixture", previous, str(existing), str(start)], capture_output=True, text=True, check=True)
            with self.subTest(previous=previous, existing=existing, start=start):
                lines = [line for line in result.stdout.splitlines() if line.startswith("POLICY:")]
                self.assertEqual(lines, ["POLICY:" + expected] if expected else [])

    @unittest.skipUnless(sys.platform == "win32", "Windows PowerShell policy fixture")
    def test_windows_fresh_staging_and_upgrade_boot_policies(self):
        source = (Path(__file__).resolve().parents[1] / "installers/windows/install.ps1").read_text()
        begin = source.index("function Get-RegistrationStartMode {")
        function = source[begin:source.index("\n}", begin) + 2]
        powershell = str(Path(__import__("os").environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        script = function + "\n@((Get-RegistrationStartMode $null $true),(Get-RegistrationStartMode $null $false),(Get-RegistrationStartMode ([pscustomobject]@{Start=2;DelayedAutoStart=1}) $true),(Get-RegistrationStartMode ([pscustomobject]@{Start=3}) $true),(Get-RegistrationStartMode ([pscustomobject]@{Start=4}) $false)) | ConvertTo-Json -Compress"
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), ["demand", "delayed-auto", "delayed-auto", "demand", "disabled"])


class NativeStatePermissionTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "Actual POSIX permission fixture")
    def test_service_can_write_runtime_but_cannot_replace_dataset_sibling(self):
        """Drop to an existing unprivileged identity inside disposable ext4 paths only."""
        status = Path("/proc/self/status").read_text()
        actual_ids = next(line for line in status.splitlines() if line.startswith("Uid:")).split()[1:]
        if int(actual_ids[1]) != 0:
            self.skipTest("Actual root is required for setuid permission proof; PRoot root emulation is insufficient")
        import pwd
        try:
            account = pwd.getpwnam("nobody")
        except KeyError:
            self.skipTest("An existing disposable unprivileged identity is required; no account is created")
        source = (Path(__file__).resolve().parents[1] / "installers/linux/install.sh").read_text()
        begin = source.index("protect_state_parent() {")
        function = source[begin:source.index("\n}", begin) + 2]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); root.chmod(0o755)
            state = root / "state"; state.mkdir(mode=0o750)
            os.chown(state, account.pw_uid, account.pw_gid)
            data = state / "data"; data.mkdir(mode=0o755)
            runtime = state / "runtime"; runtime.mkdir(mode=0o700)
            os.chown(runtime, account.pw_uid, account.pw_gid)
            retained = data / "retained.txt"; retained.write_text("retained dataset bytes")
            before = (data.stat().st_uid, data.stat().st_gid, data.stat().st_mode, retained.read_bytes())
            subprocess.run(["/bin/bash", "-eu", "-c", function + '\nprotect_state_parent "$1" "$2"', "state-permissions", str(state), str(account.pw_gid)], check=True, capture_output=True, text=True)
            self.assertEqual((state.stat().st_uid, state.stat().st_gid, state.stat().st_mode & 0o777), (0, account.pw_gid, 0o750))
            def unprivileged():
                os.setgroups([]); os.setgid(account.pw_gid); os.setuid(account.pw_uid)
            probe = "from pathlib import Path; import sys; state=Path(sys.argv[1]); (state/'runtime/write-check.txt').write_text('runtime writable');\ntry:\n (state/'data').rename(state/'data-replaced')\nexcept PermissionError:\n print('dataset replacement blocked')\nelse:\n raise AssertionError('service account replaced dataset root')\n"
            result = subprocess.run([sys.executable, "-I", "-B", "-c", probe, str(state)], preexec_fn=unprivileged, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "dataset replacement blocked")
            self.assertEqual((runtime / "write-check.txt").read_text(), "runtime writable")
            self.assertEqual((data.stat().st_uid, data.stat().st_gid, data.stat().st_mode, retained.read_bytes()), before)


class UnifiedServiceTests(unittest.TestCase):
    def setUp(self):
        self.staging = tempfile.TemporaryDirectory()
        self.addCleanup(self.staging.cleanup)
        from tools.test_desktop_staging import fixture_staging
        fixture_staging(self, Path(self.staging.name))

    def test_deconfiguration_summary_retains_corrupt_receipt_and_never_exposes_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            (config / "config.json").write_text(json.dumps({"responder": {}, "mqtt": {}}))
            receipt = config / "desktop-integrations.json"
            receipt.write_text(json.dumps({"schema": 1, "changes": [{"path": ["unknown"], "before": None,
                "after": {"present": False}}], "disabled_commands": {}}))
            original = receipt.read_bytes()
            (config / "environment.json").write_text(json.dumps({"AIRNOW_API_KEY": "hidden-current-secret"}))
            summary = backend.configuration_summary(config)
            self.assertTrue(summary["deconfiguration_error"])
            self.assertNotIn("hidden-current-secret", json.dumps(summary))
            self.assertEqual(receipt.read_bytes(), original)

    def test_cancelled_or_unprivileged_mutation_never_acquires_lock(self):
        import threading
        cancelled = threading.Event(); cancelled.set()
        request = {"kind": "service", "action": "stop", "target": "windows-x64"}
        with patch.object(backend, "native_target", return_value="windows-x64"), patch("installers.desktop.locking.operation_lock") as lock:
            with self.assertRaises(RuntimeError):
                backend.perform(request, lambda message: None, cancelled)
            with patch("installers.datasets.gui.execution.privileged", return_value=False), self.assertRaises(PermissionError):
                backend.perform(request, lambda message: None)
            lock.assert_not_called()

    def test_connection_check_constructs_only_read_only_package_command(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = service_tests.ServiceConfigurationTests().fixture(folder)
            program = paths[0] / "meshcore_mqtt_service/channel_setup.py"
            with patch.object(backend, "installed_paths", return_value=paths), patch.object(backend, "trusted_runtime"), patch.object(backend, "trusted_installed", return_value=program), patch("installers.datasets.gui.privileges.require_stopped") as stopped, patch.object(backend, "run_native", return_value="checked") as launch:
                self.assertEqual(backend.check_connection("linux-x86_64", lambda message: None), "checked")
            stopped.assert_called_once_with("linux-x86_64")
            argv = launch.call_args.args[0]
            self.assertEqual(argv[-1], "check")
            self.assertNotIn("provision", argv)

    def test_startup_controls_are_fixed_and_disable_stops_first(self):
        events = []
        with patch.object(backend, "control", side_effect=lambda *args: events.append("stop")), patch.object(backend, "run_native", side_effect=lambda command, emit: events.append(command)), patch.object(backend, "startup_mode", return_value="manual"):
            backend.set_startup("linux-x86_64", "disabled", lambda message: None)
        self.assertEqual(events, ["stop", ["/usr/bin/systemctl", "disable", "meshcore-ems.service"]])
        with self.assertRaises(ValueError):
            backend.set_startup("linux-x86_64", "shell", lambda message: None)

    @unittest.skipUnless(sys.platform.startswith("linux"), "POSIX service traversal permissions")
    def test_service_owned_private_directory_is_traversable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
            with patch("pwd.getpwnam", return_value=account), patch("grp.getgrall", return_value=[]):
                backend.validate_dataset_access(str(root / "datasets"), "linux")

    @unittest.skipUnless(sys.platform.startswith("linux"), "POSIX service traversal permissions")
    def test_direct_start_blocks_untraversable_ancestor_before_service_control(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = service_tests.ServiceConfigurationTests().fixture(folder)
            Path(folder).chmod(0o700)
            account = SimpleNamespace(pw_uid=987654, pw_gid=987654)
            request = {"kind": "service", "action": "start", "target": "linux-x86_64"}
            with patch.object(backend, "native_target", return_value="linux-x86_64"), patch.object(backend, "installed_paths", return_value=paths), patch("installers.datasets.gui.execution.privileged", return_value=True), patch("installers.desktop.locking.operation_lock", side_effect=nullcontext), patch("pwd.getpwnam", return_value=account), patch("grp.getgrall", return_value=[]), patch.object(backend, "control") as control:
                with self.assertRaisesRegex(ValueError, "cannot traverse"):
                    backend.perform(request, lambda message: None)
                control.assert_not_called()

    def test_configuration_runs_access_validation_after_installed_settings_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = service_tests.ServiceConfigurationTests().fixture(folder)
            paths[3].parent.mkdir(parents=True)
            paths[3].write_text("fixture interpreter")
            with patch.object(backend, "installed_paths", return_value=paths), patch.object(backend, "trusted_installed", side_effect=lambda path, root: path), patch.object(backend, "trusted_runtime"), patch.object(backend, "run_native", return_value="settings saved") as launch, patch.object(backend, "validate_dataset_access", side_effect=ValueError("cannot traverse")) as access:
                with self.assertRaisesRegex(ValueError, "cannot traverse"):
                    backend.configure_installed("linux-x86_64", {}, lambda message: None)
                access.assert_called_once_with(str(paths[1] / "data"), "linux")
                self.assertEqual(launch.call_count, 1)
                self.assertIn("--apply-settings", launch.call_args.args[0])

    def test_automatic_startup_does_not_enable_before_failed_validation(self):
        root = Path.cwd()
        paths = (root, root, root, root / "python", "linux")
        request = {"kind": "service", "action": "startup", "target": "linux-x86_64", "mode": "automatic"}
        with patch.object(backend, "native_target", return_value="linux-x86_64"), patch.object(backend, "installed_paths", return_value=paths), patch("installers.datasets.gui.execution.privileged", return_value=True), patch("installers.desktop.locking.operation_lock", side_effect=nullcontext), patch.object(backend, "validate_installed", side_effect=ValueError("cannot traverse")), patch.object(backend, "set_startup") as startup:
            with self.assertRaisesRegex(ValueError, "cannot traverse"):
                backend.perform(request, lambda message: None)
            startup.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith("linux"), "POSIX service traversal permissions")
    def test_private_dataset_ancestor_is_blocked_without_permission_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            with self.assertRaises(ValueError):
                backend.validate_dataset_access(str(root / "datasets"), "linux")
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)

    def test_new_settings_and_fixed_actions_are_bounded(self):
        backend.validate_settings({"dataset_root": str(Path.cwd() / "data elsewhere"), "commands": {"!status": False}})
        backend.validate_request({"kind": "service", "target": "windows-x64", "action": "startup", "mode": "manual"})
        for settings in ({"dataset_root": "relative"}, {"commands": {"!status": "false"}},
                         {"programs": {"register": [{"name": "!x", "source": "relative", "sha256": "0" * 64, "channels": []}], "unregister": []}}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                backend.validate_settings(settings)

    def test_data_root_and_disable_preserve_configuration_and_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = service_tests.ServiceConfigurationTests().fixture(folder)
            _, _, config, _, _ = paths
            before = json.loads((config / "config.json").read_text())
            with patch.object(backend, "installed_paths", return_value=paths):
                backend.apply_settings({"dataset_root": str(Path(folder) / "reference data"), "commands": {"!status": False}}, "linux-x86_64")
            after = json.loads((config / "config.json").read_text())
            self.assertEqual(after["dataset_root"], str(Path(folder) / "reference data"))
            self.assertEqual(after["responder"]["commands"]["!status"]["channels"], [])
            self.assertEqual(after["mqtt"], before["mqtt"])
            self.assertEqual(json.loads((config / "environment.json").read_text()), {})
            with patch.object(backend, "installed_paths", return_value=paths):
                backend.apply_settings({"commands": {"!status": True}}, "linux-x86_64")
            enabled = json.loads((config / "config.json").read_text())
            self.assertEqual(enabled["responder"]["commands"]["!status"]["channels"], before["responder"]["commands"]["!status"]["channels"])

    def test_deconfiguration_reverts_owned_values_but_preserves_external_edits_and_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = service_tests.ServiceConfigurationTests().fixture(folder)
            _, _, config, _, _ = paths
            with patch.object(backend, "installed_paths", return_value=paths):
                backend.apply_settings({"dataset_root": str(Path(folder) / "datasets"), "commands": {"!status": False},
                                        "credentials": {"AIRNOW_API_KEY": "retained-secret"}}, "linux-x86_64")
                current = json.loads((config / "config.json").read_text())
                current["dataset_root"] = str(Path(folder) / "external-edit")
                (config / "config.json").write_text(json.dumps(current))
                result = backend.deconfigure_settings("linux-x86_64")
            restored = json.loads((config / "config.json").read_text())
            self.assertEqual(restored["dataset_root"], str(Path(folder) / "external-edit"))
            self.assertEqual(restored["responder"]["commands"]["!status"]["channels"], ["default"])
            self.assertIn("dataset_root", result["conflicts"])
            self.assertEqual(json.loads((config / "environment.json").read_text())["AIRNOW_API_KEY"], "retained-secret")
            self.assertNotIn("retained-secret", (config / "desktop-integrations.json").read_text())

    def test_custom_program_is_statically_checked_registered_and_retained_on_deregister(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = service_tests.ServiceConfigurationTests().fixture(folder)
            _, _, config, _, _ = paths
            source = Path(folder) / "operator tool.py"
            source.write_text("raise RuntimeError('must never execute during configuration')\n")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            program = {"name": "!operator", "source": str(source), "sha256": digest, "channels": ["default"]}
            with patch.object(backend, "installed_paths", return_value=paths):
                backend.apply_settings({"programs": {"register": [program], "unregister": []}}, "linux-x86_64")
            value = json.loads((config / "config.json").read_text())
            spec = value["responder"]["commands"]["!operator"]
            path = config / spec["script"]
            self.assertEqual(path.read_bytes(), source.read_bytes())
            with patch.object(backend, "installed_paths", return_value=paths):
                backend.apply_settings({"programs": {"register": [], "unregister": ["!operator"]}}, "linux-x86_64")
            self.assertNotIn("!operator", json.loads((config / "config.json").read_text())["responder"]["commands"])
            self.assertTrue(path.exists())

    def test_custom_program_cannot_replace_shipped_entry_point_or_mismatched_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = service_tests.ServiceConfigurationTests().fixture(folder)
            source = Path(folder) / "operator.py"; source.write_text("print('fixture')\n")
            original = (paths[2] / "config.json").read_bytes()
            for name, digest in (("!status", hashlib.sha256(source.read_bytes()).hexdigest()), ("!operator", "0" * 64)):
                with patch.object(backend, "installed_paths", return_value=paths), self.assertRaises(ValueError):
                    backend.apply_settings({"programs": {"register": [{"name": name, "source": str(source), "sha256": digest, "channels": []}], "unregister": []}}, "linux-x86_64")
                self.assertEqual((paths[2] / "config.json").read_bytes(), original)

    def test_unavailable_direct_import_is_rejected_without_executing_custom_source(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = service_tests.ServiceConfigurationTests().fixture(folder)
            source = Path(folder) / "missing_dependency.py"
            source.write_text("import mc_ems_fixture_unavailable_dependency\nraise RuntimeError('never execute')\n")
            program = {"name": "!operator", "source": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "channels": []}
            original = (paths[2] / "config.json").read_bytes()
            with patch.object(backend, "installed_paths", return_value=paths), self.assertRaisesRegex(ValueError, "import is unavailable"):
                backend.apply_settings({"programs": {"register": [program], "unregister": []}}, "linux-x86_64")
            self.assertEqual((paths[2] / "config.json").read_bytes(), original)
            self.assertEqual(list((paths[2] / "programs").iterdir()), [])

    def test_snapshot_fingerprints_secret_changes_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = service_tests.ServiceConfigurationTests().fixture(folder)
            with patch.object(backend, "installed_paths", return_value=paths), patch.object(backend, "service_state", return_value="stopped"), patch.object(backend, "startup_mode", return_value="manual"):
                first = backend.snapshot("linux-x86_64")
                (paths[2] / "environment.json").write_text(json.dumps({"AIRNOW_API_KEY": "changed-secret"}))
                second = backend.snapshot("linux-x86_64")
            self.assertNotEqual(first["revision"], second["revision"])
            self.assertNotIn("changed-secret", json.dumps(second))
            self.assertEqual(second["settings"]["commands"]["!status"]["owner"], "service-package")


if __name__ == "__main__":
    unittest.main()
