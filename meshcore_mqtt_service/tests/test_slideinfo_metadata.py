"""W14B station identity, source qualifications and command checks."""
from datetime import datetime, timezone, timedelta
import asyncio
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import landslide_data, landslide_lookup as lookup
import responder


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(landslide_data.DATA, self.root/'reference')
        self.reference = self.root/'reference'
        self.real_resolve = lookup.dataset_paths.resolve
        self.patcher = patch.object(lookup.dataset_paths, 'resolve', return_value=self.reference)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(landslide_data._reference.cache_clear)

    def query(self, text, now=None):
        return lookup.station_metadata(lookup.parse_query('slideinfo', text), now=now)

    def alter(self, change):
        path = self.reference/'stations.json'
        stations = json.loads(path.read_bytes())
        change(stations)
        raw = json.dumps(stations).encode()
        path.write_bytes(raw)
        mpath = self.reference/'manifest.json'
        manifest = json.loads(mpath.read_bytes())
        manifest['station_count'] = len(stations)
        manifest['sha256']['stations.json'] = hashlib.sha256(raw).hexdigest()
        mpath.write_text(json.dumps(manifest), encoding='utf-8')

    def test_exact_ids_selectors_and_no_telemetry_inference(self):
        result = self.query('station BALT1 instruments 1', datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(result['station']['id'], 'BALT1')
        self.assertEqual(result['catalog_age_days'], 73)
        self.assertIn('no policy', result['catalog_freshness'])
        self.assertIn('telemetry unverified', lookup.format_station_metadata(result))
        for query in ('station balt1', 'station NOT-FOUND', 'station BALT1 instruments 99',
                      'station BALT1 bad', 'station BALT1 status 1', 'station ../x'):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.query(query)

    def test_duplicates_missing_and_unbounded_metadata(self):
        self.alter(lambda stations: stations.append(dict(stations[0])))
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            self.query('station CHAMBERS')
        self.alter(lambda stations: stations.pop())
        self.alter(lambda stations: stations[0].update(measurements=None, status=None, url=None))
        result = self.query('station CHAMBERS instruments')
        self.assertIn('not recorded', lookup.format_station_metadata(result))
        self.alter(lambda stations: stations[0].update(measurements=['x']*101))
        with self.assertRaisesRegex(ValueError, 'metadata'):
            self.query('station CHAMBERS')

    def test_checksum_generation_and_explicit_removal(self):
        self.query('station BALT1')
        (self.reference/'stations.json').write_text('[]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.query('station BALT1')
        with patch.object(lookup.dataset_paths, 'resolve', side_effect=FileNotFoundError('removed')):
            with self.assertRaisesRegex(FileNotFoundError, 'removed'):
                self.query('station BALT1')

    def test_generation_switch_and_unsupported_schema(self):
        with patch.object(lookup.dataset_paths, 'resolve', side_effect=[self.reference, self.root/'other']):
            with self.assertRaisesRegex(ValueError, 'generation changed'):
                self.query('station BALT1')
        path = self.reference/'manifest.json'
        value = json.loads(path.read_bytes())
        value['schema_version'] = 99
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Incompatible'):
            self.query('station BALT1')

    def test_radio_budget_and_complete_values(self):
        for query in ('station BALT1 instruments', 'station BALT1 instruments 1', 'station BALT1 source', 'station BALT1 status'):
            result = self.query(query)
            for sender in ('Reader', '\u00e9'*40):
                with patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                    text = lookup.format_station_metadata(result)
                    self.assertLessEqual(len(('@'+sender+' '+text).encode()), 150)
                    self.assertTrue('telemetry unverified' in text or 'too long' in text)

    def test_nevada_location_retains_coverage_warning(self):
        station = landslide_data.nearest_station(39.5296, -119.8138)
        self.assertIn('not local coverage', lookup.format_station(station, 'Reno'))

    def test_direct_entry_and_service_json_block(self):
        root = Path(__file__).resolve().parents[1]
        cmd = [sys.executable, str(root/'scripts/slideinfo.py'), '--json', 'station', 'BALT1']
        result = subprocess.run(cmd, text=True, capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(json.loads(result.stdout)['station']['id'], 'BALT1')
        result = subprocess.run(cmd, env=dict(os.environ, MESHCORE_REQUEST_ID='service'),
                                text=True, capture_output=True, encoding='utf-8', timeout=20)
        self.assertIn('local-only', result.stdout)

    def test_service_context_and_registration(self):
        from scripts.command_dependencies import is_bundled
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root/'config.json').read_bytes())['responder']
        spec = config['commands']['!slideinfo']
        self.assertTrue(is_bundled('!slideinfo', spec))
        request = dict(sender='Alice', channel_name='Test', channel_id='default', channel_index=3,
                       id='w14b', phrase='!slideinfo station BALT1 status', command='!slideinfo',
                       arguments=['station BALT1 status'])
        output, diagnostic = asyncio.run(responder.run_script(root, spec, request, config))
        self.assertFalse(diagnostic)
        self.assertTrue('telemetry unverified' in output or 'too long' in output)
        self.assertLessEqual(len(responder.reply_parts('Alice', output, max_parts=1)[0].encode()), 150)

    def test_catalog_dates_are_explicit_and_use_utc(self):
        now = datetime(2026, 10, 19, 23, 30, tzinfo=timezone(timedelta(hours=-7)))
        self.assertEqual(self.query('station BALT1', now)['catalog_age_days'], 0)
        path = self.reference/'manifest.json'
        manifest = json.loads(path.read_bytes())
        for checked, state in ((None, 'undated'), ('garbage', 'invalid date'),
                               ('2026-10-20T12:00:00', 'invalid date'), ('2027-01-01', 'future')):
            manifest['checked_on'] = checked
            path.write_text(json.dumps(manifest), encoding='utf-8')
            result = self.query('station BALT1', now)
            self.assertEqual(result['catalog_date_state'], state)
            self.assertIn('no policy', result['catalog_freshness'])
        with self.assertRaisesRegex(ValueError, 'UTC offset'):
            self.query('station BALT1', datetime(2026, 10, 20))

    def test_bounded_reads_and_discovery_schema_validation(self):
        from scripts.command_dependencies import dependency_status
        path = self.reference/'manifest.json'
        manifest = json.loads(path.read_bytes())
        manifest['schema_version'] = True
        path.write_text(json.dumps(manifest), encoding='utf-8')
        self.assertTrue(dependency_status('!slideinfo').startswith('Unavailable:'))
        path.write_bytes(b' '*(1024*1024+1))
        with self.assertRaisesRegex(ValueError, 'size limit'):
            self.query('station BALT1')

    def test_empty_boundary_collection_is_explicitly_unavailable(self):
        path = self.reference/'california.geojson'
        raw = json.dumps({'type': 'FeatureCollection', 'features': []}).encode()
        path.write_bytes(raw)
        mpath = self.reference/'manifest.json'
        manifest = json.loads(mpath.read_bytes())
        manifest['sha256']['california.geojson'] = hashlib.sha256(raw).hexdigest()
        mpath.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'boundary collection'):
            self.query('station BALT1')

    def test_actual_custom_registry_and_removal(self):
        registry = self.root/'datasets.json'
        value = dict(schema=1, datasets={'landslide': {'active': {'path': 'reference'}}})
        registry.write_text(json.dumps(value), encoding='utf-8')
        with patch.object(lookup.dataset_paths, 'resolve', self.real_resolve), \
                patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.root)}):
            self.assertEqual(self.query('station BALT1')['station']['id'], 'BALT1')
            value['datasets']['landslide']['active'] = None
            registry.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaisesRegex(FileNotFoundError, 'not installed'):
                self.query('station BALT1')

    def test_long_failure_stays_within_radio_budget(self):
        sender = '\u00e9'*40
        output = io.StringIO()
        with patch.dict(os.environ, {'MESHCORE_SENDER': sender}), redirect_stdout(output), \
                patch.object(lookup, 'station_metadata', side_effect=OSError('long path '*100)):
            lookup.main('slideinfo', ['station', 'BALT1'])
        self.assertIn('unavailable', output.getvalue())
        self.assertLessEqual(len(('@'+sender+' '+output.getvalue().strip()).encode()), 150)
