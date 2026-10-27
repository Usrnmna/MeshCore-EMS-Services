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
