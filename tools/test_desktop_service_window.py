"""Offscreen interaction contracts for the independent service window."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from installers.desktop.service_window import ServiceWindow
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 GUI environment required")
class ServiceWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window=ServiceWindow(Path.cwd(),"windows-x64",demo=True)
        self.addCleanup(self.window.close)

    def test_default_upgrade_preserves_transport_broker_channels_and_secrets(self):
        self.assertEqual(self.window.settings(), {"credentials":{},"clear_credentials":[]})

    def test_optional_invalid_history_keeps_valid_core_settings_available(self):
        self.assertIsNotNone(self.window.historySettings)
        self.window.historySettings.load({"enabled": True, "channel_id": "missing"}, {}, True)
        self.window.historySettings.applyCheck.setChecked(True)
        self.window.transport.setCurrentIndex(2)
        self.window.tcpHost.setText("host")
        result = self.window.settings()
        self.assertEqual(result["tcp_host"], "host")
        self.assertIn("channel_history", result)
        self.assertIn("Not applied", self.window.historySettings.savedLabel.text())

    def test_history_view_import_failure_does_not_claim_maintenance_task(self):
        self.window.open_history()
        self.assertIsNone(self.window.task)
        self.assertTrue(all(button.isEnabled() for button in self.window.buttons))

    def test_recording_can_be_selected_for_a_matching_repair_artifact(self):
        import tempfile
        import json
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / "MeshCore-EMS-v0.9.8-beta-windows-x64-setup.exe"
            artifact.write_bytes(b"fixture")
            digest = hashlib.sha256(b"fixture").hexdigest()
            (root / "SHA256SUMS.txt").write_text(digest + "  " + artifact.name)
            artifact.with_name(artifact.name + ".provenance.json").write_text(json.dumps({"artifact_sha256": digest, "target": "windows-x64", "capabilities": ["channel-history-v1"]}))
            self.window.demo = False
            self.window.historySettings.load({}, {}, False)
            self.window.folderEdit.setText(str(root))
            self.window.check_history_installer()
            self.assertTrue(self.window.historySettings.applyCheck.isEnabled())
            self.assertIsNone(self.window.task)

    def test_only_selected_transport_fields_are_sent(self):
        self.window.transport.setCurrentIndex(2)
        self.window.tcpHost.setText("192.168.1.2")
        self.assertEqual(self.window.settings()["tcp_host"],"192.168.1.2")
        self.assertNotIn("serial_port",self.window.settings())
        self.assertFalse(self.window.serial.isEnabled())

    def test_loaded_summary_never_populates_passwords(self):
        self.window.completed({"settings":{"credential_names":["MESHCORE_CHANNEL_KEY_FAMILY"],"channels":{}}})
        self.assertEqual(self.window.credentials.rowCount(),4)
        self.assertTrue(all(not self.window.credentials.cellWidget(row,1).text() for row in range(4)))

    def test_demo_operation_cannot_authorize_or_inspect_host(self):
        with patch("installers.desktop.service_window.select_installer", side_effect=AssertionError("demo cannot inspect installers")), patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Yes):
            self.window.execute("install")
            while self.window.task is not None:
                self.app.processEvents()
        self.assertIn("Simulation only", self.window.results.toPlainText())

    def test_status_refresh_preserves_unsaved_explicit_overrides(self):
        self.window.transport.setCurrentIndex(2)
        self.window.tcpHost.setText("new-host")
        self.window.channelsCheck.setChecked(True)
        self.window.channelsEdit.setPlainText("unsaved registry")
        self.window.mqttCheck.setChecked(True)
        self.window.mqttHost.setText("new-broker")
        self.window.credentials.cellWidget(0,1).setText("unsaved-secret")
        self.window.completed({"settings":{"connection":{"host":"old-host"},"channels":{},"mqtt":{"host":"old-broker"}}})
        self.assertEqual(self.window.tcpHost.text(),"new-host")
        self.assertEqual(self.window.channelsEdit.toPlainText(),"unsaved registry")
        self.assertEqual(self.window.mqttHost.text(),"new-broker")
        self.assertEqual(self.window.credentials.cellWidget(0,1).text(),"unsaved-secret")


if __name__=="__main__":
    unittest.main()
