"""Isolated contracts for the separate desktop service application."""
import hashlib
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installers.desktop import service_backend as backend


class ServiceDesktopTests(unittest.TestCase):
    def test_request_rejects_arbitrary_commands_and_unknown_actions(self):
        for value in ({"kind":"service", "target":"windows-x64", "action":"shell"},
                      {"kind":"service", "target":"windows-x64", "action":"status", "command":"cmd.exe"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                backend.validate_request(value)

    def test_settings_reject_inline_channel_keys_and_invalid_transport(self):
        for settings in ({"transport":"shell"}, {"credentials":{"PYTHONPATH":"unsafe"}},
                         {"channels":{"channels":{"x":{"key":"unsafe"}},"command_channels":{}}}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                backend.validate_settings(settings)

    def test_blank_credentials_preserve_and_explicit_clear_is_scoped(self):
        current = {"AIRNOW_API_KEY":"kept", "MESHCORE_MQTT_PASSWORD":"old", "MESHCORE_CHANNEL_KEY_FAMILY":"saved"}
        result = backend.merge_credentials(current, {"credentials":{"AIRNOW_API_KEY":"", "MESHCORE_MQTT_PASSWORD":"new"},
                                                    "clear_credentials":["MESHCORE_CHANNEL_KEY_FAMILY"]})
        self.assertEqual(result, {"AIRNOW_API_KEY":"kept", "MESHCORE_MQTT_PASSWORD":"new"})
        self.assertEqual(current["MESHCORE_CHANNEL_KEY_FAMILY"], "saved")

    def test_secrets_are_redacted_from_diagnostics(self):
        self.assertEqual(backend.redact("error token=private and key=abc123", {"A":"private", "B":"abc123"}),
                         "error token=[redacted] and key=[redacted]")

    def test_installer_selection_checks_target_digest_and_ambiguity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / "MeshCore-EMS-v0.9.6-beta-windows-x64-setup.exe"
            artifact.write_bytes(b"fixture")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            (root / "SHA256SUMS.txt").write_text(digest + "  " + artifact.name + "\n")
            self.assertEqual(backend.select_installer(root, "windows-x64", digest), artifact)
            with self.assertRaises(ValueError):
                backend.select_installer(root, "linux-x86_64", digest)
            artifact.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                backend.select_installer(root, "windows-x64", digest)

    def test_status_request_cannot_smuggle_mutation_settings(self):
        with self.assertRaises(ValueError):
            backend.validate_request({"kind":"service", "action":"status", "target":"windows-x64", "settings":{"channel":"changed"}})

    def test_transport_validation_prevents_control_characters_and_invalid_ports(self):
        for settings in ({"tcp_port":0}, {"tcp_host":"host\ncommand"}, {"serial_port":"auto;rm"},
                         {"transport":"serial", "tcp_host":"host"}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                backend.validate_settings(settings)

    def test_auth_cancel_does_not_run_native_actions(self):
        import threading
        cancel = threading.Event(); cancel.set()
        with patch.object(backend, "native_target", return_value="windows-x64"), patch.object(backend, "run_native") as launch:
            with self.assertRaises(RuntimeError):
                backend.perform({"kind":"service", "action":"stop", "target":"windows-x64"}, lambda message: None, cancel)
            launch.assert_not_called()

    def test_zero_exit_uninstall_does_not_claim_success_if_service_remains(self):
        from installers.datasets.gui import execution
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            uninstaller=root/"unins000.exe"; uninstaller.write_bytes(b"fixture")
            paths=(root,root,root,root/"python.exe","windows")
            with patch("installers.desktop.locking.operation_lock", side_effect=nullcontext), patch.object(backend,"native_target",return_value="windows-x64"), patch.object(backend,"installed_paths",return_value=paths), patch.object(execution,"privileged",return_value=True), patch.object(backend,"trusted_installed",return_value=uninstaller), patch.object(backend,"run_native",return_value=""), patch.object(backend,"control",return_value="Stopped"):
                with self.assertRaises(RuntimeError):
                    backend.perform({"kind":"service","action":"uninstall","target":"windows-x64"},lambda message:None)


if __name__ == "__main__":
    unittest.main()

class ServiceConfigurationTests(unittest.TestCase):
    def fixture(self, folder):
        import test_installers
        from installers import configure
        root, state, config = test_installers.InstallerTests().fixture(folder)
        configure.configure(root,state,config,"linux")
        return root,state,config,root/".venv/bin/python","linux"

    def test_graphical_settings_preserve_programs_credentials_and_runtime(self):
        from installers import configure
        with tempfile.TemporaryDirectory() as folder:
            paths=self.fixture(folder); root,state,config,_,_=paths
            current=json.loads((config/"config.json").read_text())
            current["operator_future_setting"]={"keep":True}
            configure.write_json(config/"config.json",current)
            configure.write_json(config/"environment.json",{"AIRNOW_API_KEY":"saved"})
            (state/"runtime/retained.db").write_bytes(b"state")
            with patch.object(backend,"installed_paths",return_value=paths):
                backend.apply_settings({"transport":"tcp","tcp_host":"192.168.1.5","tcp_port":5000,"credentials":{"AIRNOW_API_KEY":""}},"linux-x86_64")
            saved=json.loads((config/"config.json").read_text())
            self.assertEqual(saved["operator_future_setting"],{"keep":True})
            self.assertEqual(saved["responder"]["program_directory"],current["responder"]["program_directory"])
            self.assertEqual(json.loads((config/"environment.json").read_text()),{"AIRNOW_API_KEY":"saved"})
            self.assertEqual((state/"runtime/retained.db").read_bytes(),b"state")
            self.assertTrue(any((state/"backups").glob("*/environment.json")))

    def test_second_publish_failure_restores_both_original_files(self):
        from installers import configure
        with tempfile.TemporaryDirectory() as folder:
            paths=self.fixture(folder); root,state,config,_,_=paths
            original={name:(config/name).read_bytes() for name in ("config.json","environment.json")}
            write=configure.write_json
            def fail_config(path,value):
                if path.name=="config.json":
                    raise OSError("simulated publication failure")
                return write(path,value)
            with patch.object(backend,"installed_paths",return_value=paths),patch.object(configure,"write_json",side_effect=fail_config):
                with self.assertRaises(OSError):
                    backend.apply_settings({"credentials":{"AIRNOW_API_KEY":"new"}},"linux-x86_64")
            for name,value in original.items():
                self.assertEqual((config/name).read_bytes(),value)

    def test_clear_private_secret_does_not_fall_back_to_inherited_environment(self):
        import os
        from installers import configure
        with tempfile.TemporaryDirectory() as folder:
            paths=self.fixture(folder); root,state,config,_,_=paths
            value=json.loads((config/"config.json").read_text())
            value["responder"]["channels"]["default"].update(type="private",secret_env="MESHCORE_CHANNEL_KEY_FAMILY")
            configure.write_json(config/"config.json",value)
            secret="11"*16
            configure.write_json(config/"environment.json",{"MESHCORE_CHANNEL_KEY_FAMILY":secret})
            before=(config/"environment.json").read_bytes()
            with patch.object(backend,"installed_paths",return_value=paths),patch.dict(os.environ,{"MESHCORE_CHANNEL_KEY_FAMILY":secret}):
                with self.assertRaises(ValueError):
                    backend.apply_settings({"clear_credentials":["MESHCORE_CHANNEL_KEY_FAMILY"]},"linux-x86_64")
            self.assertEqual((config/"environment.json").read_bytes(),before)

    def test_summary_omits_inline_mqtt_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=self.fixture(folder); root,state,config,_,_=paths
            value=json.loads((config/"config.json").read_text())
            value["mqtt"].update(password="legacy-secret",username="legacy-name")
            (config/"config.json").write_text(json.dumps(value))
            summary=backend.configuration_summary(config)
            self.assertNotIn("legacy-secret",json.dumps(summary))
            self.assertNotIn("legacy-name",json.dumps(summary))
