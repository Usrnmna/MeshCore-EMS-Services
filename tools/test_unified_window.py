"""Offscreen checks for the unified review flow; native backends are isolated."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
QT_AVAILABLE = importlib.util.find_spec("PyQt6") is not None
if QT_AVAILABLE:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox


def reviewed(intent, emit, demo=False):
    """Supply a bounded discovery result without reading the working host."""
    return {"intent": intent, "digest": "a" * 64,
            "steps": [{"owner": "service", "action": "configure", "detail": "Save local settings"}],
            "blocked": [], "warnings": [], "text": "Reviewed local settings; secrets are omitted.",
            "snapshot": {"service": {"installed": True, "status": "stopped", "startup": "manual",
                "settings": {"commands": {"!status": {"enabled": True, "channels": ["default"],
                    "script": "scripts/status.py", "owner": "service-package"}},
                    "channels": {"channels": {"default": {"name": "#test", "type": "hashtag", "mqtt_export": True}},
                                 "command_channels": {"!status": ["default"]}}}}, "datasets": {}}}


@unittest.skipUnless(QT_AVAILABLE, "PyQt6 environment required")
class UnifiedWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from installers.desktop.unified_window import UnifiedWindow
        self.prepare_patch = patch("installers.desktop.unified_window.prepare", side_effect=reviewed)
        self.prepare_patch.start()
        self.addCleanup(self.prepare_patch.stop)
        self.window = UnifiedWindow(ROOT / ".build/test-unified-data", ROOT / "dist/test kit", "windows-x64", demo=True)
        self.wait_idle()
        self.addCleanup(self.window.close)

    def wait_idle(self):
        deadline = time.monotonic() + 10
        self.app.processEvents()
        while self.window.task is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertIsNone(self.window.task)

    def test_default_selection_preserves_installed_components_and_startup(self):
        value = self.window.intent()
        self.assertEqual(value["dataset_action"], "keep")
        self.assertEqual(value["service_action"], "keep")
        self.assertEqual(value["startup"], "preserve")
        self.assertFalse(value["start"])
        self.assertEqual(value["settings"], {"credentials": {}, "clear_credentials": []})
        self.assertEqual(self.window.datasetTree.topLevelItemCount(), 8)
        self.assertGreaterEqual(self.window.serviceAction.findData("check_connection"), 0)

    def test_history_pending_registry_uses_unified_channels_and_invalidates_review(self):
        widget = self.window.serviceForm.historySettings
        self.assertIsNotNone(widget)
        widget.load({"enabled": True, "channel_id": "default"}, {"default": {"name": "Public", "type": "public", "mqtt_export": True}}, True)
        widget.applyCheck.setChecked(True)
        self.window.applyChannels.setChecked(True)
        self.window.channelTable.item(0, 0).setText("renamed")
        self.window.plan = {"reviewed": True}
        widget.enabledCheck.setChecked(False)
        self.assertIsNone(self.window.plan)
        widget.enabledCheck.setChecked(True)
        self.window.serviceAction.setCurrentIndex(2)
        settings = self.window.intent()["settings"]
        self.assertEqual(settings["channels"]["channels"].keys(), {"renamed"})
        self.assertEqual(settings["channel_history"], {"invalid": True})

    def test_demo_recovery_history_never_reads_host_journals(self):
        with patch("installers.desktop.unified_backend.recovery_history", create=True,
                   side_effect=AssertionError("demo must not inspect journals")):
            self.window.recovery_history()
            self.wait_idle()
        self.assertIn("Demo only", self.window.resultsText.toPlainText())

    def test_channel_and_command_fields_create_structured_settings(self):
        self.window.applyChannels.setChecked(True)
        self.window.channelTable.item(0, 1).setText("#new-channel")
        self.window.commandTable.item(0, 1).setText("default")
        self.window.applyCommands.setChecked(True)
        settings = self.window.intent()["settings"]
        self.assertEqual(settings["channels"]["channels"]["default"]["name"], "#new-channel")
        self.assertEqual(settings["channels"]["command_channels"]["!status"], ["default"])
        self.assertTrue(settings["commands"]["!status"])

    def test_selection_changes_invalidate_review(self):
        self.window.review()
        self.wait_idle()
        self.assertIsNotNone(self.window.plan)
        self.window.datasetTree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
        self.assertIsNone(self.window.plan)
        self.assertFalse(self.window.executeButton.isEnabled())

    def test_credential_edits_invalidate_without_printing_secret(self):
        self.window.review()
        self.wait_idle()
        self.window.serviceForm.credentials.cellWidget(0, 1).setText("unique-private-value")
        self.assertIsNone(self.window.plan)
        self.assertNotIn("unique-private-value", self.window.resultsText.toPlainText())
        self.assertNotIn("unique-private-value", self.window.planText.toPlainText())

    def test_dynamic_private_credential_edit_invalidates_review(self):
        self.window.serviceForm.privateName.setText("MESHCORE_CHANNEL_KEY_FAMILY")
        self.window.serviceForm.add_private()
        self.window.review()
        self.wait_idle()
        self.assertIsNotNone(self.window.plan)
        self.window.serviceForm.credentials.cellWidget(3, 1).setText("family-key-value")
        self.assertIsNone(self.window.plan)

    def test_backend_error_text_redacts_entered_secret(self):
        self.window.serviceForm.credentials.cellWidget(0, 1).setText("unique-private-value")
        self.window.failed("validation failed: unique-private-value")
        self.assertNotIn("unique-private-value", self.window.resultsText.toPlainText())

    def test_declined_review_never_calls_executor(self):
        self.window.review()
        self.wait_idle()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No), \
             patch("installers.desktop.unified_window.execute_reviewed", side_effect=AssertionError("declined")):
            self.window.execute()
        self.assertIsNone(self.window.task)

    def test_removal_keeps_data_unless_explicitly_selected(self):
        index = self.window.datasetAction.findData("remove_tools")
        self.window.datasetAction.setCurrentIndex(index)
        self.assertEqual(self.window.intent()["dataset_action"], "remove_tools")
        self.assertIn("retain", self.window.datasetAction.currentText().lower())

    def test_installed_custom_root_does_not_replace_explicit_choice(self):
        custom = str(ROOT / ".build/custom data root")
        value = reviewed(self.window.intent(status_only=True), lambda _: None)
        value["snapshot"]["service"]["settings"]["dataset_root"] = custom
        self.window.show_status(value)
        self.assertEqual(self.window.dataRootEdit.text(), custom)
        explicit = str(ROOT / ".build/explicit data root")
        self.window.dataRootEdit.setText(explicit)
        self.window.show_status(value)
        self.assertEqual(self.window.dataRootEdit.text(), explicit)

    def test_single_retained_root_is_adopted_when_no_explicit_or_saved_root(self):
        retained = str(ROOT / ".build/retained data")
        value = reviewed(self.window.intent(status_only=True), lambda _: None)
        value["snapshot"]["service"]["retained_roots"] = [{"root": retained, "datasets": ["ebmud"], "verification": "receipts verified"}]
        self.window.show_status(value)
        self.assertEqual(self.window.dataRootEdit.text(), retained)
        self.assertFalse(self.window.applyDataRoot.isChecked())

    def test_multiple_retained_roots_require_graphical_choice_and_keep_explicit_root(self):
        before = self.window.dataRootEdit.text()
        value = reviewed(self.window.intent(status_only=True), lambda _: None)
        roots = [str(ROOT / ".build/retained first"), str(ROOT / ".build/retained second")]
        value["snapshot"]["service"]["retained_roots"] = [{"root": path, "datasets": ["ebmud"], "verification": "receipts verified"} for path in roots]
        self.window.show_status(value)
        self.assertEqual(self.window.dataRootEdit.text(), before)
        self.assertEqual(self.window.rootChoices.count(), 3)
        self.window.rootChoices.setCurrentIndex(2)
        self.assertEqual(self.window.dataRootEdit.text(), roots[1])
        self.wait_idle()
        self.window.show_status(value)
        self.assertEqual(self.window.dataRootEdit.text(), roots[1])

    def test_program_picker_hashes_source_without_executing_it(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".build", prefix="program picker ") as directory:
            path = Path(directory) / "custom command.py"
            path.write_text("raise RuntimeError('source must not execute during selection')\n", encoding="utf-8")
            self.window.programName.setText("!custom")
            self.window.programChannels.setText("default")
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(path), "Python (*.py)")):
                self.window.choose_program()
            program = self.window.intent()["settings"]["programs"]["register"][0]
            self.assertEqual(program["name"], "!custom")
            self.assertEqual(program["source"], str(path.absolute()))
            self.assertEqual(len(program["sha256"]), 64)
            self.assertEqual(program["input"], "none")

    def test_failure_clears_plan_and_explains_partial_completion(self):
        self.window.review()
        self.wait_idle()
        self.window.failed("native operation exited 1")
        self.assertIsNone(self.window.plan)
        self.assertIn("retained", self.window.resultsText.toPlainText().lower())
        self.assertIn("Refresh", self.window.resultsText.toPlainText())


if __name__ == "__main__":
    unittest.main()
