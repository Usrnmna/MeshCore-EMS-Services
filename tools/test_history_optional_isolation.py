"""Optional recording failures cannot invalidate unrelated installer intentions."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from installers.desktop import service_backend as service, unified_backend as unified
from installers.desktop import service_integrations as integrations
from installers.datasets.gui.discovery import demo_snapshot


class OptionalIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.package = Path(__file__).resolve().parents[1] / 'meshcore_mqtt_service'
        self.config = {'responder': {'channels': {'public': {'name': 'Public', 'type': 'public', 'mqtt_export': True}}}}
        self.installed = dict(registered=True, state='running', startup='manual', revision='a' * 64,
            capabilities=['operation-lock-v1', 'settings-v2', 'channel-history-v1'],
            settings={'channels': {'channels': self.config['responder']['channels']}})
        self.intent = dict(target='windows-x64', root=str(self.root / 'data'), folder=str(self.root),
            datasets=[], dataset_action='keep', service_action='configure', settings={}, startup='preserve', start=False)
        self.datasets = demo_snapshot(self.root / 'data', 'windows-x64')

    def test_explicit_null_accepts_core_target_and_disabled(self):
        for section in ({'enabled': False, 'channel': None}, {'enabled': True, 'channel_id': 'public', 'channel': None}):
            with self.subTest(section=section):
                value = service.prepare_history(self.config, self.config, {}, {'channel_history': section}, self.package)
                self.assertEqual(value[3]['status'], 'applied')

    def test_malformed_optional_description_does_not_block_core_review(self):
        for value in ([], {}, 4):
            with self.subTest(value=value):
                intent = dict(self.intent, settings={'credentials': {'AIRNOW_API_KEY': 'new'},
                    'channel_history': {'enabled': True, 'channel_id': value}})
                plan, _ = unified.build_plan(intent, self.datasets, self.installed, demo=True)
                self.assertFalse(plan['blocked'])
                self.assertEqual(plan['history_outcome']['status'], 'not_applied')
                self.assertIn('configure', [step['action'] for step in plan['steps']])

    def test_optional_availability_is_not_a_core_revision(self):
        intent = dict(self.intent, settings={'channel_history': {'enabled': False}})
        with patch.object(service, 'review_history', return_value={'status': 'applied', 'reason': '', 'available': True}):
            before, _ = unified.build_plan(intent, self.datasets, self.installed, demo=True)
        with patch.object(service, 'review_history', return_value={'status': 'not_applied', 'reason': 'unavailable', 'available': False}):
            after, _ = unified.build_plan(intent, self.datasets, self.installed, demo=True)
        self.assertEqual(before['digest'], after['digest'])
        self.assertTrue(before['steps'])
        self.assertEqual(after['steps'], [])
        changed = copy.deepcopy(self.installed); changed['revision'] = 'b' * 64
        other, _ = unified.build_plan(intent, self.datasets, changed, demo=True)
        self.assertNotEqual(before['digest'], other['digest'])

    def test_fresh_and_legacy_install_use_bundled_schema(self):
        for registered in (False, True):
            with self.subTest(registered=registered), patch.object(service, 'installed_paths',
                    return_value=(self.root, self.root, self.root, self.root / 'python', 'linux')):
                result = service.review_history({'channel_history': {'enabled': False, 'channel': None}},
                    dict(self.installed, registered=registered), 'linux-x86_64', supported=True, incoming=True)
                self.assertEqual(result['status'], 'applied')

    def test_malformed_history_receipt_survives_unrelated_core_save(self):
        entry = {'path': ['channel_history', []], 'before': {'present': False}, 'after': {'present': False}}
        receipt = {'schema': 1, 'changes': [entry], 'disabled_commands': {}}
        before = {'mqtt': {'host': 'old'}}; after = {'mqtt': {'host': 'new'}}
        result = service.record_settings_changes(before, after, receipt)
        self.assertIn(entry, result['changes'])
        candidate, retained, conflicts = service.revert_settings_changes(after, result)
        self.assertEqual(candidate, before)
        self.assertEqual(retained['changes'], [entry])
        self.assertIn('channel_history', conflicts)
        receipt['changes'] = [dict(entry, path=['mqtt', []])]
        with self.assertRaises((TypeError, ValueError)):
            service.record_settings_changes(before, after, receipt)

    def test_incoming_preview_requires_matching_schema_sources(self):
        import hashlib
        record = {'capabilities': ['channel-history-v1'], 'source_sha256': {
            self.package.name + '/' + name: hashlib.sha256((self.package / name).read_bytes()).hexdigest()
            for name in ('config.json', 'channels.py', 'channel_history.py')}}
        self.assertTrue(service.incoming_history_supported(record, 'linux-x86_64'))
        record['source_sha256']['meshcore_mqtt_service/channel_history.py'] = '0' * 64
        self.assertFalse(service.incoming_history_supported(record, 'linux-x86_64'))

    def test_rejected_optional_noop_reports_completed_operation_and_reason(self):
        import threading
        from unittest.mock import MagicMock
        outcome = {'status': 'not_applied', 'reason': 'optional validator unavailable', 'available': False}
        intent = dict(self.intent, settings={'channel_history': {'enabled': False}})
        with patch.object(service, 'review_history', return_value=outcome):
            plan, _ = unified.build_plan(intent, self.datasets, self.installed, demo=True)
        journal = MagicMock(); journal.value = {'recovery': 'none'}
        with patch.object(unified, 'Journal', return_value=journal), patch.object(service, 'snapshot', return_value=self.installed), patch('installers.desktop.locking.maintenance_directory', return_value=self.root):
            result = unified.run_plan(plan, None, lambda _: None, threading.Event())
        self.assertTrue(result['complete'])
        self.assertEqual(result['history_outcome'], outcome)
        self.assertEqual(result['results'], [])
        journal.finish.assert_called_once_with(True)
