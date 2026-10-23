"""Offscreen interaction checks against the actual editable Qt Designer form."""

import importlib.util
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
QT_AVAILABLE = importlib.util.find_spec("PyQt6") is not None
if QT_AVAILABLE:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtCore import Qt
    from installers.datasets.gui.window import DatasetWindow


@unittest.skipUnless(QT_AVAILABLE, "Install GUI requirements to run widget checks")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        # The offscreen Windows plugin does not enumerate desktop system fonts.
        # Load a local font only for a readable automated preview.
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
        if font_path.is_file():
            from PyQt6.QtGui import QFontDatabase, QFont
            identity = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(identity)
            if families:
                cls.application.setFont(QFont(families[0], 10))

    def setUp(self):
        self.window = DatasetWindow(ROOT / ".build/demo-data", ROOT / "dist/v0.9.6-beta/datasets", "windows-x64", demo=True)
        self.window.show()
        self.wait_idle()

    def tearDown(self):
        self.wait_idle()
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()

    def wait_idle(self):
        """Pump the real event loop while waiting for worker completion."""
        deadline = time.monotonic() + 10
        self.application.processEvents()
        while self.window.task is not None and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.005)
        self.application.processEvents()
        self.assertIsNone(self.window.task, "Worker did not finish")

    def test_form_loads_all_collections_and_selection_controls(self):
        self.assertEqual(self.window.datasetTree.topLevelItemCount(), 8)
        self.window.selectAllButton.click()
        self.assertEqual(len(self.window.selected()), 8)
        self.window.clearSelectionButton.click()
        self.assertEqual(self.window.selected(), [])

    def test_selected_plan_demo_execution_and_results(self):
        self.window.selectAllButton.click()
        self.window.installSelectedButton.click()
        self.wait_idle()
        self.assertTrue(self.window.executeButton.isEnabled())
        self.assertIn("DEMO", self.window.planText.toPlainText())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.executeButton.click()
        self.wait_idle()
        self.assertIn("simulated", self.window.resultsText.toPlainText())
        self.assertFalse(self.window.executeButton.isEnabled())

    def test_all_actions_have_working_plan_connections(self):
        for button in (self.window.missingPackagesButton, self.window.missingDataButton, self.window.uninstallAllButton):
            button.click()
            self.wait_idle()
            self.assertIsNotNone(self.window.plan)
            self.assertTrue(self.window.plan.operations)

    def test_selection_or_path_change_invalidates_reviewed_plan(self):
        self.window.missingPackagesButton.click()
        self.wait_idle()
        self.assertTrue(self.window.executeButton.isEnabled())
        self.window.datasetTree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
        self.assertFalse(self.window.executeButton.isEnabled())
        self.window.missingPackagesButton.click()
        self.wait_idle()
        self.window.dataRootEdit.setText(str(ROOT / "different-root"))
        self.assertIsNone(self.window.plan)
        self.assertFalse(self.window.executeButton.isEnabled())

    def test_declined_confirmation_does_not_start_batch(self):
        self.window.missingPackagesButton.click()
        self.wait_idle()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.window.executeButton.click()
        self.assertIsNone(self.window.task)
        self.assertEqual(self.window.resultsText.toPlainText(), "")

    def test_demo_render(self):
        self.window.missingPackagesButton.click()
        self.wait_idle()
        destination = ROOT / ".build/dataset-gui-preview.png"
        destination.parent.mkdir(exist_ok=True)
        self.assertTrue(self.window.grab().save(str(destination)))


if __name__ == "__main__":
    unittest.main()
