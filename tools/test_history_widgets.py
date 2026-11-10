"""Optional recording settings and independent desktop control contracts."""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installers.desktop import service_backend as backend


class HistorySettingsTests(unittest.TestCase):
    def setUp(self):
        self.current = {"responder": {"channels": {"core": {"name": "Public", "type": "public", "mqtt_export": True}}},
                        "channel_history": {"enabled": False}}
        self.package = ROOT / "meshcore_mqtt_service"

    def evaluate(self, settings, secrets=None, candidate=None, supported=True):
        candidate = copy.deepcopy(candidate or self.current)
        return backend.prepare_history(self.current, candidate, secrets or {}, settings, self.package, supported=supported)

    def test_absent_override_preserves_saved_history(self):
        candidate, secrets, accepted, outcome = self.evaluate({})
        self.assertEqual(candidate, self.current)
        self.assertEqual(outcome["status"], "preserved")
        self.assertEqual(accepted, {})

    def test_existing_public_selection_applies_without_changing_core_registry(self):
        candidate, _, accepted, outcome = self.evaluate({"channel_history": {"enabled": True, "channel_id": "core"}})
        self.assertEqual(candidate["channel_history"], {"enabled": True, "channel_id": "core"})
        self.assertEqual(candidate["responder"], self.current["responder"])
        self.assertEqual(outcome["status"], "applied")

    def test_invalid_optional_bundle_preserves_all_saved_values(self):
        override = {"enabled": True, "channel_id": "private", "channel": {"name": "Private", "type": "private", "secret_env": "MESHCORE_CHANNEL_KEY_ONLY", "mqtt_export": False}}
        for value in (123, "x\nunsafe", "x" * 4097, "bad encoding"):
            with self.subTest(value=str(value)[:20]):
                candidate, secrets, accepted, outcome = self.evaluate({"channel_history": override, "history_credentials": {"MESHCORE_CHANNEL_KEY_ONLY": value}}, {"MESHCORE_CHANNEL_KEY_ONLY": "00" * 16})
                self.assertEqual(candidate, self.current)
                self.assertEqual(secrets, {"MESHCORE_CHANNEL_KEY_ONLY": "00" * 16})
                self.assertEqual(accepted, {})
                self.assertEqual(outcome["status"], "not_applied")

    def test_private_recording_key_accepted_only_for_selected_unused_reference(self):
        override = {"enabled": True, "channel_id": "private", "channel": {"name": "Private", "type": "private", "secret_env": "MESHCORE_CHANNEL_KEY_ONLY", "mqtt_export": False}}
        candidate, secrets, accepted, outcome = self.evaluate({"channel_history": override, "history_credentials": {"MESHCORE_CHANNEL_KEY_ONLY": "00" * 16}})
        self.assertEqual(secrets, {"MESHCORE_CHANNEL_KEY_ONLY": "00" * 16})
        self.assertEqual(outcome["status"], "applied")
        proposed = copy.deepcopy(self.current)
        proposed["responder"]["channels"]["shared"] = override["channel"]
        _, secrets, _, outcome = self.evaluate({"channel_history": override, "history_credentials": {"MESHCORE_CHANNEL_KEY_ONLY": "00" * 16}}, candidate=proposed)
        self.assertEqual(secrets, {})
        self.assertEqual(outcome["status"], "not_applied")

    def test_core_removal_preserved_history_reports_unavailable(self):
        self.current["channel_history"] = {"enabled": True, "channel_id": "core"}
        proposed = {"responder": {"channels": {}}, "channel_history": self.current["channel_history"]}
        candidate, _, _, outcome = self.evaluate({}, candidate=proposed)
        self.assertEqual(candidate["responder"]["channels"], {})
        self.assertEqual(outcome["status"], "preserved")
        self.assertFalse(outcome["available"])

    def test_missing_capability_skips_override_and_malformed_values_never_enter_core(self):
        settings = {"tcp_host": "host", "channel_history": {"enabled": True, "channel_id": "core"}, "history_credentials": {"bad": object()}}
        self.assertEqual(backend.validate_settings(settings), settings)
        _, _, accepted, outcome = self.evaluate(settings, supported=False)
        self.assertEqual(accepted, {})
        self.assertEqual(outcome["status"], "not_applied")

    def test_optional_schema_is_rechecked_after_review(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder)
            module = package / "channel_history.py"
            module.write_text("def validate_history_config(config):\n    return None\n")
            settings = {"channel_history": {"enabled": True, "channel_id": "core"}}
            first = backend.prepare_history(self.current, self.current, {}, settings, package)[3]
            module.write_text("raise ImportError('optional module unavailable')\n")
            second = backend.prepare_history(self.current, self.current, {}, settings, package)[3]
            self.assertEqual(first["status"], "applied")
            self.assertEqual(second["status"], "not_applied")

    def test_service_request_partitions_optional_bundle_before_core_validator(self):
        payload = {"transport": "serial", "serial_port": "auto", "channel_history": {"enabled": True}, "history_credentials": {"BAD": "unsafe\nvalue"}}
        real = backend.validate_settings
        def core_only(settings):
            self.assertFalse(backend.HISTORY_FIELDS & settings.keys())
            return real(settings)
        with patch.object(backend, "validate_settings", side_effect=core_only):
            backend.validate_request({"kind": "service", "action": "configure", "target": "windows-x64", "settings": payload})


class HistoryWidgetTests(unittest.TestCase):
    def test_malformed_saved_history_cannot_break_settings_refresh(self):
        from installers.desktop.history_widgets import HistorySettingsWidget
        widget = HistorySettingsWidget()
        for malformed in ({'enabled': True, 'channel_id': [], 'channel': {'name': [], 'type': {}, 'secret_env': []}},
                          {'enabled': False, 'channel_id': {'invalid': True}}):
            widget.load(malformed, {}, True)
            self.assertFalse(widget.applyCheck.isChecked())
        widget.deleteLater()

    def test_history_observations_and_path_do_not_change_pending_settings(self):
        from installers.desktop.history_widgets import HistorySettingsWidget
        widget = HistorySettingsWidget()
        widget.load({'enabled': False}, {}, True)
        widget.applyCheck.setChecked(True)
        before = widget.override()
        widget.observe({'database_path': 'example.sqlite3', 'service_state': 'running',
            'availability': 'not_created', 'observed_at': '2026-10-28T12:00:00+00:00'})
        self.assertEqual(widget.override(), before)
        self.assertTrue(widget.databasePath.isReadOnly())
        self.assertTrue(widget.copyPath.isEnabled())
        self.assertIn('not_created', widget.observationLabel.text())
        widget.deleteLater()

    def test_unused_private_key_input_does_not_reject_another_source_or_disable(self):
        from installers.desktop.history_widgets import HistorySettingsWidget
        widget = HistorySettingsWidget()
        widget.load({'enabled': True, 'channel_id': 'public'}, {'public': {'name': 'Public', 'type': 'public'}}, True)
        widget.applyCheck.setChecked(True)
        widget.secretEnv.setText('MESHCORE_CHANNEL_KEY_PREVIOUS')
        widget.secretValue.setText('previous edit')
        widget.clearSecret.setChecked(True)
        self.assertEqual(widget.credential_overrides(), {})
        widget.sourceCombo.setCurrentIndex(1); widget.channelType.setCurrentText('private')
        self.assertTrue(widget.credential_overrides())
        widget.enabledCheck.setChecked(False)
        self.assertEqual(widget.credential_overrides(), {})
        widget.deleteLater()
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from installers.desktop.history_widgets import HistorySettingsWidget
        self.widget = HistorySettingsWidget()
        self.addCleanup(self.widget.close)
        self.registry = {"core": {"name": "Public", "type": "public", "mqtt_export": True}}
        self.widget.load({"enabled": True, "channel_id": "core"}, self.registry, True)

    def test_default_preserves_but_disabled_is_explicit_override(self):
        self.assertIsNone(self.widget.override())
        self.widget.applyCheck.setChecked(True)
        self.widget.enabledCheck.setChecked(False)
        self.assertEqual(self.widget.override(), {"enabled": False})

    def test_missing_selection_is_not_replaced(self):
        from installers.desktop.history_widgets import HistorySettingsError
        self.widget.applyCheck.setChecked(True)
        self.widget.set_registry({"replacement": self.registry["core"]})
        with self.assertRaises(HistorySettingsError):
            self.widget.override()

    def test_refresh_preserves_pending_fields_and_source_is_explicit(self):
        self.widget.applyCheck.setChecked(True)
        self.widget.sourceCombo.setCurrentIndex(1)
        self.widget.channelId.setText("archive")
        self.widget.channelName.setText("Public")
        self.widget.channelType.setCurrentText("public")
        self.widget.load({"enabled": False}, self.registry, True)
        self.assertEqual(self.widget.override(), {"enabled": True, "channel_id": "archive", "channel": {"name": "Public", "type": "public", "mqtt_export": False}})


if __name__ == "__main__":
    unittest.main()
