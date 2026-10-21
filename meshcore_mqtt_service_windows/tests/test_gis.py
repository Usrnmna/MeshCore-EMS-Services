"""Local GIS contracts: matching, geometry, refresh consistency, and radio integration."""

import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from shapely.geometry import Point, Polygon, mapping

import responder
import service
from scripts import gis_data as data, gis_lookup as lookup, gis_spatial as spatial


@contextmanager
def fixture_directory():
    """Create isolated snapshots with inherited Windows permissions and remove them afterward."""
    directory = service.ROOT / 'runtime' / ('gis-test-' + uuid4().hex)
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def record(name, geometry, category='Park', properties=None):
    """Build a normalized in-memory record for geometry and formatting tests."""
    return {'name': name, 'geometry': geometry, 'category': category, 'dataset': 'ebrpd',
            'named': True, 'properties': properties or {}}


class GISUnitTests(unittest.TestCase):
    def test_command_programs_use_positional_queries_and_external_settings(self):
        """Exercise each executable with a custom data path and output limit."""
        with fixture_directory() as directory:
            settings = json.loads(data.SETTINGS_FILE.read_bytes())
            settings['data_directory'] = str(data.load_settings()['data_directory'])
            settings['max_reply_bytes'] = 300
            settings_path = directory / 'gis_settings.json'
            settings_path.write_text(json.dumps(settings), encoding='utf-8')
            loaded = data.load_settings(settings_path)
            environment = dict(os.environ, PYTHONIOENCODING='utf-8')
            cases = [('trail', 'Bear Creek dogs'), ('rec', 'water near 37.9 -122.2'),
                     ('peak', 'Wildcat Peak elevation'), ('park', 'Pleasanton Ridge status'),
                     ('boundary', 'trail Bear Creek')]
            for kind, query in cases:
                with self.subTest(kind=kind):
                    result = subprocess.run(
                        [sys.executable, str(service.ROOT / 'scripts' / f'{kind}.py'),
                         '--settings', str(settings_path), *query.split()],
                        cwd=directory, env=environment, capture_output=True,
                        text=True, encoding='utf-8', timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), lookup.lookup(kind, query, loaded))
                    self.assertLessEqual(len(result.stdout.strip().encode('utf-8')), 300)
            result = subprocess.run(
                [sys.executable, str(service.ROOT / 'scripts/peak.py'),
                 '--kind', 'trail', 'Bear Creek'], capture_output=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)

    def test_generic_cli_remains_compatible(self):
        """Retain the earlier generic interface for existing command registrations."""
        from contextlib import redirect_stdout
        from io import StringIO
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(lookup.main(['--kind', 'peak', '--query', 'Wildcat Peak']), 0)
        self.assertEqual(output.getvalue().strip(), lookup.lookup('peak', 'Wildcat Peak'))

    def test_query_syntax_and_coordinate_validation(self):
        self.assertEqual(data.parse_query('near 37.9,-122.2 2'), ('near', (37.9, -122.2, 2.0)))
        self.assertEqual(data.parse_query('37.9 -122.2')[0], 'coordinates')
        self.assertEqual(data.parse_query('trail Bear Creek'), ('trail', 'Bear Creek'))
        for text in ['', 'near nan -122', 'near 91 -122', 'near 38 -181',
                     'near 38 -122 -1', 'near 38 -122 1 2', '--settings evil',
                     'name\nother', 'x' * 151]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                data.parse_query(text)

    def test_exact_names_win_and_partial_names_remain_ambiguous(self):
        groups = [[record("Eagle's Nest", None)], [record('Eagles Nest Loop', None)]]
        self.assertEqual(data.find_by_name(groups, 'Eagles Nest Trail'), [groups[0]])
        self.assertEqual(len(data.find_by_name(groups, 'Eagles')), 2)

    def test_grouped_park_status_and_conditional_access_are_preserved(self):
        records = [record('Park', None, properties={'STATUS': 'Landbank', 'DOG': 'Limited to Park Hours'}),
                   record('Park', None, properties={'STATUS': 'Parkland', 'BICYCLE': 'Yes L'})]
        group = data.group_features(records)[0]
        self.assertEqual(len(group), 2)
        self.assertIn('Landbank/Parkland', lookup.summary(group))
        self.assertEqual(lookup.field_values(group, 'DOG'), 'Limited to Park Hours')
        self.assertEqual(lookup.field_values(group, 'BICYCLE'), 'Yes L')
        self.assertEqual(lookup.field_values(group, 'ABSENT'), 'not recorded')

    def test_snapshot_integrity_null_geometry_and_refresh_overlap(self):
        with fixture_directory() as directory:
            raw = json.dumps({'type': 'FeatureCollection', 'features': [
                {'type': 'Feature', 'id': 1, 'properties': {'PEAK_NAME': 'Peak'}, 'geometry': None}
            ]}).encode()
            manifest = {'datasets': {'peaks': {'path': 'peaks.geojson', 'feature_count': 1,
                'byte_count': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                'retrieved_at_utc': '2026-09-24T00:00:00+00:00'}}}
            (directory / 'peaks.geojson').write_bytes(raw)
            (directory / 'sources.json').write_text(json.dumps(manifest))
            snapshot = data.Snapshot(directory)
            self.assertIsNone(snapshot.load_dataset('peaks')[0]['geometry'])
            self.assertEqual(snapshot.date_label(), '2026-09-24')
            (directory / '.refresh.lock').touch()
            with self.assertRaises(data.GISUnavailable):
                snapshot.verify_unchanged()
            (directory / '.refresh.lock').unlink()
            (directory / 'sources.json').write_text(json.dumps(manifest) + ' ')
            with self.assertRaises(data.GISUnavailable):
                snapshot.verify_unchanged()
            (directory / 'peaks.geojson').write_bytes(raw + b' ')
            with self.assertRaises(data.GISUnavailable):
                data.Snapshot(directory).load_dataset('peaks')

    def test_polygon_holes_edges_multipart_and_nulls(self):
        engine = spatial.Spatial(data.load_settings())
        # Meter-space fixture isolates containment semantics from coordinate transforms.
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)],
                          holes=[[(3, 3), (7, 3), (7, 7), (3, 7)]])
        groups = [[record('Park', None)]]
        with patch.object(engine, 'geometry', return_value=polygon):
            self.assertEqual(engine.containing(groups, Point(1, 1))[0][1], 'inside')
            self.assertEqual(engine.containing(groups, Point(0, 1))[0][1], 'on boundary')
            self.assertEqual(engine.containing(groups, Point(5, 5)), [])
        self.assertIsNone(engine.geometry([record('Null', None)]))
        group = [record('Park', mapping(Point(-122.2, 37.9))),
                 record('Park', mapping(Point(-122.1, 37.9)))]
        self.assertEqual(engine.geometry(group).geom_type, 'MultiPoint')

    def test_nearest_line_uses_segments_and_latitude_longitude_order(self):
        engine = spatial.Spatial(data.load_settings())
        line = [record('Trail', {'type': 'LineString', 'coordinates': [[-122.21, 37.9], [-122.19, 37.9]]})]
        point = engine.point(37.9, -122.2)
        self.assertLess(engine.nearby([line], point, 1)[0][1], 0.001)
        with self.assertRaises(ValueError):
            engine.point(-122.2, 37.9)

    def test_invalid_polygon_is_repaired_only_in_memory(self):
        engine = spatial.Spatial(data.load_settings())
        raw = {'type': 'Polygon', 'coordinates': [[[-122.2, 37.9], [-122.1, 38],
               [-122.2, 38], [-122.1, 37.9], [-122.2, 37.9]]]}
        original = json.dumps(raw)
        geometry = engine.geometry([record('Crossed', raw)])
        self.assertTrue(geometry.is_valid)
        self.assertTrue(engine.repaired)
        self.assertEqual(json.dumps(raw), original)

    def test_reply_limit_keeps_repair_note_without_snapshot_footer(self):
        settings = data.load_settings()
        engine = unittest.mock.Mock(repaired=True)
        text = lookup.bounded_reply('long ' * 300, engine, settings)
        self.assertLessEqual(len(text.encode()), settings['max_reply_bytes'])
        self.assertNotIn('omitted', text)
        self.assertNotIn('Snapshot ', text)
        self.assertNotIn('not live conditions/access', text)
        self.assertIn('Geometry repaired', text)
        engine.repaired = False
        self.assertEqual(lookup.bounded_reply('Peak: Example.', engine, settings), 'Peak: Example.')

    def test_real_local_datasets_all_commands_without_network(self):
        settings = data.load_settings()
        if not (settings['data_directory'] / 'sources.json').exists():
            self.skipTest('Shared GIS snapshots are not installed')
        with patch('socket.socket.connect', side_effect=AssertionError('Unexpected network')):
            cases = [('trail', 'Bear Creek'), ('rec', 'near 37.9 -122.2'),
                     ('peak', 'Wildcat Peak'), ('park', 'Pleasanton Ridge'),
                     ('boundary', '37.9 -122.2'), ('boundary', 'trail Bear Creek'),
                     ('trail', 'near 37.9 -122.2 2'), ('peak', 'near 37.9 -122.2'),
                     ('park', 'near 37.9 -122.2')]
            for kind, query in cases:
                with self.subTest(kind=kind, query=query):
                    result = lookup.lookup(kind, query, settings)
                    self.assertNotIn('Snapshot ', result)
                    self.assertNotIn('download date', result)
                    self.assertNotIn('not live conditions/access', result)
                    self.assertNotIn('data unavailable', result)
                    self.assertLessEqual(len(result.encode()), settings['max_reply_bytes'])

    def test_unnamed_peaks_are_excluded_and_radius_is_bounded(self):
        settings = data.load_settings()
        with self.assertRaises(ValueError):
            lookup.lookup('peak', 'near 37.9 -122.2 1000', settings)
        result = lookup.lookup('peak', 'Unnamed', settings)
        self.assertIn('No matching', result)


class GISResponderTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_commands_validate_and_run_in_same_channel(self):
        config = json.loads((service.ROOT / 'config.json').read_bytes())['responder']
        responder.validate_config(config, service.ROOT)
        for kind in ['trail', 'rec', 'peak', 'park', 'boundary']:
            self.assertEqual(config['commands']['!' + kind]['script'], f'scripts/{kind}.py')
            self.assertEqual(config['commands']['!' + kind]['args'], [])
            command, arguments, error = responder.match_command(f'!{kind} near 37.9 -122.2', config['commands'])
            self.assertEqual(command, '!' + kind)
            self.assertEqual(arguments, ['near 37.9 -122.2'])
            self.assertIsNone(error)
        self.assertIsNotNone(responder.match_command('!peak --settings evil', config['commands'])[2])
        send = AsyncMock()
        database = sqlite3.connect(':memory:')
        try:
            bot = responder.Responder(service.ROOT, database, config, 3, 'Bot', send)
            packet = {'channel_idx': 3, 'txt_type': 0, 'text': 'Alice: !peak Wildcat Peak elevation',
                      'sender_timestamp': int(time.time())}
            self.assertTrue(bot.accept(packet))
            with patch.object(asyncio, 'sleep', new=AsyncMock()):
                self.assertTrue(await bot.process_one())
            messages = [call.args for call in send.await_args_list]
            self.assertTrue(messages)
            self.assertTrue(all(channel == 3 and text.startswith('@Alice ') for channel, text in messages))
            self.assertTrue(all(len(text.encode()) <= 150 for _, text in messages))
            self.assertIn('Wildcat Peak', ' '.join(text for _, text in messages))
            self.assertIn('elevation 1200 ft', ' '.join(text for _, text in messages))
            self.assertNotIn('Subcommands:', ' '.join(text for _, text in messages))
            self.assertNotIn('Snapshot', ' '.join(text for _, text in messages))
        finally:
            database.close()


if __name__ == '__main__':
    unittest.main()
