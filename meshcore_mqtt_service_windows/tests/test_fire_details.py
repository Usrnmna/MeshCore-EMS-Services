"""Offline W14A identity, provenance and bounded radio detail checks."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import wildfire_lookup as fire
from scripts import wildfire_settings
from scripts.wildfire_store import Store
import test_wildfire as fixtures
import responder


class FireDetailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'wildfire.sqlite3'
        self.store = Store(self.path, writable=True)
        self.addCleanup(self.store.close)
        self.now = 1800000000
        self.config = wildfire_settings.validate({})
        stamp = self.now * 1000
        self.store.replace('zones', [fixtures.zone()], 'zones', now=self.now)
        self.store.replace('incidents', [fixtures.feature('1', dict(IrwinID=fixtures.GUID,
                           IncidentName='Field acreage id North', IncidentSize=20, PercentContained=10,
                           ModifiedOnDateTime_dt=stamp))], 'wfigs', now=self.now)
        self.store.replace('egp', [fixtures.feature('2', dict(IrwinID=fixtures.GUID,
                           Name='Field acreage id North', DailyAcres=25, PercentContained=None,
                           Last_Time_Information_Modified=stamp))], 'egp', now=self.now)
        self.store.replace('perimeters', [], 'perimeter', now=self.now)

    def query(self, suffix):
        return fire.report('fire', suffix, self.store, self.config, now=self.now)

    def test_explicit_selector_source_and_conflicts(self):
        data = self.query('field acreage id '+fixtures.GUID)
        detail = data['detail']
        self.assertEqual((detail['value'], detail['source']), (25, 'egp'))
        self.assertTrue(detail['conflict'])
        self.assertEqual(detail['observed'], self.now)
        self.assertIn('cached', fire.format_report(data))
        self.assertIn('conflict', fire.format_report(data))
        containment = self.query('field containment id '+fixtures.GUID)['detail']
        self.assertEqual((containment['value'], containment['source']), (10, 'incidents'))

    def test_exact_identity_selector_words_and_ambiguity(self):
        self.assertEqual(self.query('name Field acreage id North')['incidents'][0]['id'], fixtures.GUID)
        self.assertEqual(self.query('field acreage name Field acreage id North')['detail']['value'], 25)
        with self.assertRaisesRegex(ValueError, 'Selector matches an incident name'):
            self.query('field acreage id North')
        other = '22222222-2222-4222-8222-222222222222'
        self.store.replace('incidents', [fixtures.feature('1', dict(IrwinID=fixtures.GUID, IncidentName='Same')),
                                        fixtures.feature('2', dict(IrwinID=other, IncidentName='Same'))], 'test', now=self.now)
        self.store.replace('egp', [], 'test', now=self.now)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.query('field acreage name Same')
        self.assertEqual(self.query('field acreage id '+other)['incidents'][0]['id'], other)
        with self.assertRaisesRegex(ValueError, 'not listed'):
            self.query('field acreage id 33333333-3333-4333-8333-333333333333')

    def test_perimeter_missing_and_observation_time_separate(self):
        self.assertIn('no mapped perimeter', fire.format_report(self.query('field perimeter id '+fixtures.GUID)))
        observed = self.now-120
        self.store.replace('perimeters', [fixtures.feature('p', dict(attr_IrwinID=fixtures.GUID,
                           poly_PolygonDateTime=observed*1000), fixtures.zone()['geometry'])], 'test', now=self.now)
        d = self.query('field perimeter id '+fixtures.GUID)['detail']
        self.assertEqual((d['value'], d['observed'], d['acquisition']), (observed, observed, self.now))
        self.store.replace('perimeters', [fixtures.feature('p', dict(attr_IrwinID=fixtures.GUID,
                           poly_IRWINID='22222222-2222-4222-8222-222222222222',
                           poly_PolygonDateTime=observed*1000), fixtures.zone()['geometry'])], 'test', now=self.now)
        d = self.query('field perimeter id '+fixtures.GUID)['detail']
        self.assertTrue(d['conflict'])
        self.assertIsNone(d['value'])

    def test_out_of_range_source_timestamp_is_not_a_crash(self):
        data = self.query('field updated id '+fixtures.GUID)
        data['detail'].update(value=1e100, observed=1e100, freshness='future')
        self.assertIn('invalid', fire.format_report(data))

    def test_source_update_is_not_perimeter_observation(self):
        self.store.replace('perimeters', [fixtures.feature('p', dict(attr_IrwinID=fixtures.GUID,
                           poly_DateCurrent=self.now*1000), fixtures.zone()['geometry'])], 'test', now=self.now)
        data = self.query('field perimeter id '+fixtures.GUID)
        self.assertIsNone(data['detail']['observed'])
        self.assertIsNone(data['detail']['value'])
        self.assertEqual(data['detail']['source_updated'], self.now)
        text = fire.format_report(data)
        self.assertTrue('obs=?' in text or 'too long' in text)

    def test_equal_numeric_values_are_not_conflicting(self):
        self.store.replace('egp', [fixtures.feature('e', dict(IrwinID=fixtures.GUID, Name='X',
                           DailyAcres=20.0, PercentContained=10.0,
                           Last_Time_Information_Modified=self.now*1000))], 'test', now=self.now)
        for field in ('acreage', 'containment'):
            self.assertFalse(self.query('field '+field+' id '+fixtures.GUID)['detail']['conflict'])

    def test_current_and_retained_same_name_require_identity(self):
        other = '22222222-2222-4222-8222-222222222222'
        self.store.replace('egp', [], 'test', now=self.now+10)
        self.store.replace('incidents', [fixtures.feature('new', dict(IrwinID=other,
                           IncidentName='Field acreage id North'))], 'test', now=self.now+10)
        self.now += 10
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.query('field acreage name Field acreage id North')
        data = self.query('field acreage id '+fixtures.GUID)
        self.assertTrue(data['detail']['historical'])
        text = fire.format_report(data)
        self.assertTrue('retained;status unknown' in text or 'too long' in text)
        self.assertFalse(self.query('field acreage id '+other)['detail']['historical'])

    def test_perimeter_link_conflict_is_visible_from_either_id(self):
        other = '22222222-2222-4222-8222-222222222222'
        records = self.store.features('incidents') + [fixtures.feature('other', dict(IrwinID=other, IncidentName='Other'))]
        self.store.replace('incidents', records, 'test', now=self.now)
        self.store.replace('perimeters', [fixtures.feature('p', dict(attr_IrwinID=fixtures.GUID,
                           poly_IRWINID=other, poly_PolygonDateTime=self.now*1000),
                           fixtures.zone()['geometry'])], 'test', now=self.now)
        for key in (fixtures.GUID, other):
            data = self.query('field perimeter id '+key)
            self.assertTrue(data['detail']['conflict'])
            self.assertIsNone(data['detail']['value'])
            self.assertNotIn('no mapped perimeter', fire.format_report(data))

    def test_stale_failed_future_and_null(self):
        self.store.fail('egp', 'offline', now=self.now+1)
        d = self.query('field acreage id '+fixtures.GUID)['detail']
        self.assertTrue(d['source_failed'])
        self.assertTrue(d['partial'])
        self.assertIn('source failed', fire.format_report(self.query('field acreage id '+fixtures.GUID)))
        self.now += 7200
        self.assertEqual(self.query('field acreage id '+fixtures.GUID)['detail']['freshness'], 'stale')
        self.store.replace('egp', [fixtures.feature('2', dict(IrwinID=fixtures.GUID, Name='X',
                           DailyAcres=None, Last_Time_Information_Modified=(self.now+1)*1000))], 'test', now=self.now+1)
        self.store.replace('incidents', [], 'test', now=self.now)
        d = self.query('field acreage id '+fixtures.GUID)['detail']
        self.assertIsNone(d['value'])
        self.assertTrue(d['cache_future'])

    def test_historical_acquisition_is_last_seen(self):
        self.store.replace('incidents', [], 'test', now=self.now+20)
        self.store.replace('egp', [], 'test', now=self.now+20)
        self.now += 20
        d = self.query('field acreage id '+fixtures.GUID)['detail']
        self.assertTrue(d['historical'])
        self.assertEqual(d['acquisition'], self.now-20)
        self.assertTrue(d['conflict'])

    def test_historical_source_uses_its_own_acquisition(self):
        self.store.replace('egp', [fixtures.feature('2', dict(IrwinID=fixtures.GUID, Name='X', DailyAcres=25))], 'test', now=self.now+1)
        self.store.replace('incidents', [fixtures.feature('1', dict(IrwinID=fixtures.GUID, IncidentName='X', IncidentSize=20))], 'test', now=self.now+10)
        self.store.replace('egp', [], 'test', now=self.now+20)
        self.store.replace('incidents', [], 'test', now=self.now+20)
        self.now += 20
        data = self.query('field acreage id '+fixtures.GUID)
        self.assertEqual(data['detail']['acquisition'], self.now-19)
        self.assertEqual(data['detail']['last_seen'], self.now-10)

    def test_radio_budget_and_validation(self):
        data = self.query('field acreage id '+fixtures.GUID)
        for sender in ('Reader', '\u00e9'*40):
            with patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                text = fire.format_report(data)
                self.assertLessEqual(len(('@'+sender+' '+text).encode()), 150)
                self.assertTrue('conflict' in text or 'too long' in text)
        for text in ('x'*221, 'field acreage id x\n', 'field acreage id --bad'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                fire.parse_query('fire', text)

    def test_direct_program_and_local_json_restriction(self):
        root = Path(__file__).resolve().parents[1]
        command = [sys.executable, str(root/'scripts/fire.py'), '--db', str(self.path), '--json',
                   'field', 'acreage', 'id', fixtures.GUID]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['detail']['value'], 25)
        env = dict(os.environ, MESHCORE_REQUEST_ID='w14a')
        result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertIn('local-only', result.stdout)

    def test_incompatible_cache_schema_is_explicitly_unavailable(self):
        self.store.db.execute('PRAGMA user_version=99')
        self.store.db.commit()
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root/'scripts/fire.py'), '--db', str(self.path), '--json',
                                 'field', 'acreage', 'id', fixtures.GUID],
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('schema', json.loads(result.stdout)['error'])

    def test_corrupt_cache_is_unavailable(self):
        corrupt = self.path.parent/'corrupt.sqlite3'
        corrupt.write_bytes(b'not a sqlite database')
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root/'scripts/fire.py'), '--db', str(corrupt), '--json',
                                 'field', 'acreage', 'id', fixtures.GUID],
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unavailable', json.loads(result.stdout)['error'])

    def test_service_invocation_and_discovery(self):
        from scripts.command_dependencies import dependency_status, is_bundled
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root/'config.json').read_bytes())['responder']
        config['_runtime_directory'] = str(self.path.parent)
        spec = config['commands']['!fire']
        self.assertTrue(is_bundled('!fire', spec))
        query = 'field acreage id '+fixtures.GUID
        request = dict(sender='Alice', channel_name='Test', channel_id='default', channel_index=3,
                       id='w14a', phrase='!fire '+query, command='!fire', arguments=[query])
        with patch.dict(os.environ, {'MESHCORE_RUNTIME_DIR': str(self.path.parent)}):
            output, diagnostic = asyncio.run(responder.run_script(root, spec, request, config))
            self.assertFalse(diagnostic)
            self.assertTrue('cached' in output or 'too long' in output)
            self.assertLessEqual(len(responder.reply_parts('Alice', output, max_parts=1)[0].encode()), 150)
            self.assertIn('Cache readable', dependency_status('!fire', True))
            self.store.db.execute("DELETE FROM snapshots WHERE source IN ('egp','incidents')")
            self.store.db.commit()
            self.assertTrue(dependency_status('!fire', True).startswith('Unavailable:'))


if __name__ == '__main__':
    unittest.main()
