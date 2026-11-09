"""Recorded EBMUD endpoints and conjunction filters, including radio execution."""
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from shapely.geometry import LineString, Point, mapping

import responder
import service
from scripts import gis_data as data, gis_lookup as lookup


def feature(dataset, name='Oak Loop', longitude=-122.2, **properties):
    """Build deterministic source-shaped records with geometry separate from roles."""
    geometry = Point(longitude, 37.9) if dataset == 'trail_endpoints' else LineString(
        [(longitude, 37.9), (longitude, 37.901)])
    return {'name': name, 'named': True, 'dataset': dataset,
            'category': data.LAYER_FIELDS[dataset][0], 'geometry': mapping(geometry),
            'properties': dict(TRAIL_NAME=name, **properties)}


class TrailQueryTests(unittest.TestCase):
    def setUp(self):
        self.settings = data.load_settings()
        self.layers = {name: [] for name in data.LAYER_FIELDS}
        self.layers['trails'] = [feature('trails', OBJECTID=7, OBJECTID_1=1,
                                        DOGS='Yes', SUN_SHADE='Mostly Shade')]
        self.snapshot = Mock()
        self.snapshot.load_dataset.side_effect = lambda name: self.layers[name]
        patcher = patch.object(lookup, 'Snapshot', return_value=self.snapshot)
        patcher.start()
        self.addCleanup(patcher.stop)

    def reply(self, query):
        """Run the public lookup against the fixture generation."""
        return lookup.lookup('trail', query, self.settings)

    def endpoint(self, role, ident, longitude=-122.2, **properties):
        """Append an endpoint whose source ID differs from its trail association."""
        record = feature('trail_endpoints', longitude=longitude, END_POINT=role,
                         OBJECTID_1=ident, OBJECTID=7, **properties)
        self.layers['trail_endpoints'].append(record)
        return record

    def test_parser_endpoint_and_combined_forms(self):
        self.assertEqual(data.parse_command_query('trail', 'Oak Loop end'), ('name', 'Oak Loop', 'end'))
        self.assertEqual(data.parse_command_query('trail', 'Oak Loop END id 42'),
                         ('name', 'Oak Loop', ('endpoint', 'end', '42')))
        self.assertEqual(data.parse_command_query('trail', 'find DOGS shade near 37.9,-122.2 2'),
                         ('find', (37.9, -122.2, 2.0), ('dogs', 'shade')))
        for query in ('find near 37.9 -122.2', 'find dogs dogs near 37.9 -122.2',
                      'find dogs water near 37.9 -122.2', 'find dogs shade',
                      'find shade near nan -122.2', 'find shade near 91 -122.2',
                      'find shade near 37.9 -122.2 0', 'find shade near 37.9 -122.2 extra',
                      'Oak Loop end id', 'Oak Loop end id -1', 'Oak Loop end id １',
                      'end id 42', 'Oak Loop end\n', 'x' * 151):
            with self.subTest(query=query), self.assertRaises(ValueError):
                data.parse_command_query('trail', query)

    def test_help_exposes_new_forms_without_loading_data(self):
        for topic, expected in [('endpoints', 'start/end'), ('find', 'FILTERS near'),
                                ('filters', 'dogs horses bikes shade'), ('shade', 'Equal Parts Shade and Sun')]:
            with self.subTest(topic=topic):
                self.assertIn(expected, self.reply('help ' + topic))
        self.snapshot.load_dataset.assert_not_called()

    def test_recorded_roles_override_line_vertex_and_record_order(self):
        self.endpoint('END', 42, -122.1)
        self.endpoint('START', 41, -122.3)
        for query, expected in [('Oak Loop end', '-122.10000'), ('Oak Loop start', '-122.30000'),
                                ('end near 37.9 -122.2', '-122.10000')]:
            result = self.reply(query)
            self.assertIn(expected, result)
            self.assertIn('access unknown', result)
            self.assertNotIn('-122.20000', result)
        self.snapshot.verify_unchanged.assert_called()

    def test_multiple_endpoints_require_unique_source_selector(self):
        self.endpoint('END', 42, -122.1)
        self.endpoint('END', 43, -122.3)
        self.endpoint('START', 41)
        for query in ('Oak Loop end', 'end near 37.9 -122.2'):
            result = self.reply(query)
            self.assertIn('Multiple mapped ends', result)
            self.assertIn('42', result)
            self.assertIn('43', result)
            self.assertNotIn('37.90000', result)
        self.assertIn('-122.30000', self.reply('Oak Loop end id 43'))
        for ident in (7, 41, 99):
            self.assertIn('not recorded for that ID', self.reply(f'Oak Loop end id {ident}'))

    def test_missing_or_duplicate_endpoint_ids_do_not_choose_arbitrarily(self):
        self.endpoint('END', 42)
        extra = self.endpoint('END', 42, -122.3)
        self.assertIn('ambiguous', self.reply('Oak Loop end id 42'))
        extra['properties'].pop('OBJECTID_1')
        self.assertIn('source IDs missing', self.reply('Oak Loop end'))

    def test_nearby_endpoint_choices_identify_trail_and_ids_on_radio(self):
        for role in ('START', 'END'):
            self.endpoint(role, 42)
            self.endpoint(role, 43, -122.3)
            for sender in ('Alice', 'a' * 80, '温' * 26):
                with self.subTest(role=role, sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                    text = responder.reply_parts(sender, self.reply(f'{role.lower()} near 37.9 -122.2'), max_parts=1)[0]
                    for expected in ('Multiple mapped', 'Oak Loop', '42', '43'):
                        self.assertIn(expected, text)
                    self.assertLessEqual(len(text.encode()), 150)
                    self.assertNotIn('37.90000', text)
            self.layers['trail_endpoints'] = []

    def test_incomplete_trail_associations_cannot_disable_conflict_checks(self):
        record = self.endpoint('END', 42)
        record['properties']['OBJECTID'] = 8
        self.layers['trails'].append(feature('trails'))
        for query in ('Oak Loop end', 'Oak Loop end id 42'):
            with self.subTest(query=query):
                result = self.reply(query)
                self.assertIn('association incomplete', result)
                self.assertNotIn('37.90000', result)

    def test_explicit_endpoint_id_requires_integer_source_id(self):
        self.endpoint('END', '42')
        result = self.reply('Oak Loop end id 42')
        self.assertIn('source ID invalid', result)
        self.assertNotIn('37.90000', result)

    def test_numeric_endpoint_selector_accepts_leading_zeroes(self):
        self.endpoint('END', 42)
        self.assertIn('mapped end 37.90000,-122.20000', self.reply('Oak Loop end id 0042'))

    def test_endpoint_choices_never_drop_their_name_or_ids_to_fit(self):
        name = 'Long named trail ' * 5
        self.layers['trails'][0]['name'] = name
        for ident in (42, 43):
            self.endpoint('END', ident)['name'] = name
        with patch.dict(os.environ, {'MESHCORE_SENDER': 'a' * 80}):
            result = self.reply('end near 37.9 -122.2')
            self.assertEqual(result, 'Endpoint choices exceed reply limit.')
            self.assertLessEqual(len(('@' + 'a' * 80 + ' ' + result).encode()), 150)

    def test_missing_or_malformed_association_is_not_a_coordinate_result(self):
        record = self.endpoint('END', 42)
        for association in (None, True, '7', -1, [], {}):
            record['properties']['OBJECTID'] = association
            with self.subTest(association=association):
                result = self.reply('Oak Loop end')
                self.assertIn('association', result)
                self.assertIn('ambiguous', result)
                self.assertNotIn('37.90000', result)

    def test_missing_role_or_geometry_never_infers_a_line_endpoint(self):
        record = self.endpoint('START', 41)
        self.assertIn('mapped end not recorded', self.reply('Oak Loop end'))
        record['properties']['END_POINT'] = None
        self.assertIn('mapped start not recorded', self.reply('Oak Loop start'))
        record['properties']['END_POINT'] = 'END'
        record['geometry'] = None
        self.assertIn('coordinates unavailable', self.reply('Oak Loop end'))
        for coordinates in ([float('nan'), 38], [-122, float('inf')], [True, 38], [-181, 38], [1]):
            record['geometry'] = {'type': 'Point', 'coordinates': coordinates}
            with self.subTest(coordinates=coordinates):
                result = self.reply('Oak Loop end')
                self.assertTrue('invalid' in result or 'unavailable' in result)

    def test_conflicting_association_and_ambiguous_trail_names(self):
        record = self.endpoint('END', 42)
        record['properties']['OBJECTID'] = 8
        self.assertIn('association conflicts', self.reply('Oak Loop end'))
        self.layers['trails'].append(feature('trails', 'Oak Ridge', OBJECTID=8))
        for query in ('Oak end', 'Oak end id 42', 'end near 37.9 -122.2'):
            self.assertIn('Multiple trails', self.reply(query))

    def test_supplementary_descriptions_are_not_endpoint_points_or_total_lengths(self):
        self.layers['trails'] = []
        self.layers['additional_trails'] = [feature('additional_trails', TRAIL_START='Gate',
            TRAIL_END='Road', LENGTH_MILES=1.2), feature('additional_trails', LENGTH_MILES=2.3)]
        self.endpoint('END', 42)
        self.assertIn('supplementary segments', self.reply('Oak Loop end'))
        self.assertIn('total not inferred', self.reply('Oak Loop length'))
        self.assertNotIn('3.5', self.reply('Oak Loop length'))

    def test_every_filter_precedes_geometry_ranking_and_keeps_conditions(self):
        # Excluded records cannot influence nearest selection or geometry errors.
        self.layers['trails'][0]['properties']['DOGS'] = 'No'
        self.layers['trails'][0]['geometry'] = None
        self.layers['additional_trails'] = [feature('additional_trails', 'Conditional', -122.1,
            DOG='Limited to Park Hours', HORSE='Yes', BICYCLE='Yes L', SUNEXPO='Full shade')]
        result = self.reply('find dogs horses bikes shade near 37.9 -122.2')
        for expected in ('Conditional', 'segment ref', 'Limited to Park Hours', 'Yes L', 'Full shade'):
            self.assertIn(expected, result)
        self.assertNotIn('Oak Loop', result)

    def test_shade_requires_recorded_eligible_values_on_every_segment(self):
        for value in (None, '', 'Unknown', 'Shade', 'Full Sun', 'Mostly Sun', 'No shade'):
            self.layers['trails'][0]['properties']['SUN_SHADE'] = value
            with self.subTest(value=value):
                self.assertIn('No matching', self.reply('find dogs shade near 37.9 -122.2'))
        for value in ('Equal Parts Shade and Sun', 'Mostly Shade', 'Full Shade'):
            self.layers['trails'][0]['properties']['SUN_SHADE'] = value
            self.assertIn(value, self.reply('find dogs shade near 37.9 -122.2'))
        self.layers['trails'].append(feature('trails', DOGS='Yes', SUN_SHADE='Full Sun'))
        self.assertIn('No matching', self.reply('find dogs shade near 37.9 -122.2'))

    def test_conflicting_aliases_and_policy_on_grouped_segments_exclude_group(self):
        for properties in ({'DOG': 'No'}, {'SUNEXPO': 'Full Sun'}):
            record = self.layers['trails'][0]
            record['properties'].update(properties)
            self.assertIn('No matching', self.reply('find dogs shade near 37.9 -122.2'))
            for key in properties:
                record['properties'].pop(key)
        self.layers['trails'].append(feature('trails', DOGS='Unknown', SUN_SHADE='Full Shade'))
        self.assertIn('No matching', self.reply('find dogs shade near 37.9 -122.2'))

    def test_each_combined_filter_rejects_a_closer_record_before_ranking(self):
        """Each conjunction member independently prevents a nearer false match."""
        for field in ('DOGS', 'HORSES', 'BIKES', 'SUN_SHADE'):
            properties = dict(DOGS='Yes', HORSES='Yes', BIKES='Yes', SUN_SHADE='Mostly Shade')
            rejected = feature('trails', 'Closer', **dict(properties, **{field: None}))
            rejected['geometry'] = None
            self.layers['trails'] = [rejected, feature('trails', 'Farther', -122.1, **properties)]
            with self.subTest(field=field):
                result = self.reply('find dogs horses bikes shade near 37.9 -122.2')
                self.assertIn('Farther', result)
                self.assertNotIn('Closer', result)

    def test_supplementary_group_requires_every_segment_and_preserves_all_values(self):
        self.layers['trails'] = []
        self.layers['additional_trails'] = [
            feature('additional_trails', 'Loop', DOG='Yes', SUNEXPO='Full Shade'),
            feature('additional_trails', 'Loop', DOG='Limited to Park Hours', SUNEXPO='Mostly Shade')]
        result = self.reply('find dogs shade near 37.9 -122.2')
        for value in ('segment ref', 'Yes/Limited to Park Hours', 'Full Shade/Mostly Shade'):
            self.assertIn(value, result)
        self.layers['additional_trails'][1]['properties'].pop('SUNEXPO')
        self.assertIn('No matching', self.reply('find dogs shade near 37.9 -122.2'))

    def test_primary_record_precedence_does_not_borrow_supplementary_permission(self):
        self.layers['trails'][0]['properties']['DOGS'] = 'No'
        self.layers['additional_trails'] = [feature('additional_trails', DOG='Yes', SUNEXPO='Full Shade')]
        self.assertIn('No matching', self.reply('find dogs shade near 37.9 -122.2'))
        self.assertIn('dogs No', self.reply('Oak Loop dogs'))

    def test_tied_nearest_groups_require_an_explicit_name(self):
        self.layers['trails'].append(feature('trails', 'Other', DOGS='Yes', SUN_SHADE='Full Shade'))
        result = self.reply('find dogs shade near 37.9 -122.2')
        self.assertIn('Multiple trails', result)
        self.assertIn('Oak Loop', result)
        self.assertIn('Other', result)

    def test_explicit_radius_retains_all_matches_for_identity_resolution(self):
        self.layers['trails'].append(feature('trails', 'Other', -122.19, DOGS='Yes', SUN_SHADE='Full Shade'))
        for query in ('find dogs shade near 37.9 -122.2 2', 'start near 37.9 -122.2 2'):
            result = self.reply(query)
            self.assertIn('Multiple trails', result)
            self.assertIn('Other', result)
        self.assertNotIn('Other', self.reply('find dogs shade near 37.9 -122.2'))

    def test_legacy_shade_proximity_reports_values_without_filtering(self):
        self.layers['trails'][0]['properties']['SUN_SHADE'] = 'Full Sun'
        self.assertIn('shade Full Sun', self.reply('shade near 37.9 -122.2'))
        self.assertIn('No matching', self.reply('find shade near 37.9 -122.2'))

    def test_missing_eligible_geometry_does_not_silently_claim_nearest(self):
        self.layers['trails'][0]['geometry'] = None
        with self.assertRaisesRegex(ValueError, 'nearest unknown'):
            self.reply('find dogs shade near 37.9 -122.2')

    def test_explicit_radius_and_projection_bounds_and_no_implicit_radius(self):
        self.layers['trails'][0]['geometry'] = feature('trails', longitude=-121.3)['geometry']
        self.settings['maximum_radius_miles'] = 1
        self.assertIn('Oak Loop', self.reply('find dogs shade near 37.9 -122.2'))
        self.assertIn('No matching', self.reply('find dogs shade near 37.9 -122.2 1'))
        for query in ('find dogs shade near 37.9 -122.2 2', 'end near 37.9 -122.2 2',
                      'find shade near 37.9 -110'):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.reply(query)

    def test_radio_budgets_preserve_whole_qualifications_or_decline_result(self):
        self.layers['trails'] = []
        self.layers['additional_trails'] = [feature('additional_trails', 'Oak | Loop',
            DOG='Limited to Park Hours', HORSE='Yes', BICYCLE='Yes L', SUNEXPO='Equal Parts Shade and Sun')]
        for sender in ('Alice', 'a' * 80, '温' * 26):
            with self.subTest(sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                text = responder.reply_parts(sender, self.reply('find dogs horses bikes shade near 37.9 -122.2'), max_parts=1)[0]
                self.assertLessEqual(len(text.encode()), 150)
                if 'conditions exceed' not in text:
                    for value in ('Limited to Park Hours', 'Yes L', 'Equal Parts Shade and Sun', 'segment ref'):
                        self.assertIn(value, text)
                self.assertNotIn('Unable to return', text)

    def test_endpoint_coordinates_and_access_qualification_fit_long_sender(self):
        self.endpoint('END', 42)
        for sender in ('Alice', 'a' * 80, '温' * 26):
            with self.subTest(sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                result = responder.reply_parts(sender, self.reply('Oak Loop end'), max_parts=1)[0]
                self.assertLessEqual(len(result.encode()), 150)
                self.assertIn('mapped end 37.90000,-122.20000', result)
                self.assertIn('access unknown', result)

    def test_generation_change_rejects_new_results(self):
        self.endpoint('END', 42)
        self.snapshot.verify_unchanged.side_effect = data.GISUnavailable('Changed generation')
        for query in ('Oak Loop end', 'find dogs shade near 37.9 -122.2'):
            with self.subTest(query=query), self.assertRaises(data.GISUnavailable):
                self.reply(query)

    def test_dedicated_cli_custom_snapshot_and_endpoint_integrity(self):
        """Exercise actual executable imports, parsing, settings and checksum checks."""
        self.endpoint('END', 42, -122.1)
        directory = service.ROOT / 'runtime' / ('w06-test-' + uuid4().hex)
        directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, directory)
        manifest = {'datasets': {}}
        for name in ('trails', 'additional_trails', 'trail_endpoints'):
            records = self.layers[name]
            raw = json.dumps({'type': 'FeatureCollection', 'features': [
                {'type': 'Feature', 'properties': record['properties'], 'geometry': record['geometry']}
                for record in records]}).encode()
            (directory / (name + '.geojson')).write_bytes(raw)
            manifest['datasets'][name] = {'path': name + '.geojson', 'feature_count': len(records),
                'byte_count': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        (directory / 'sources.json').write_text(json.dumps(manifest))
        settings = dict(self.settings, data_directory=str(directory))
        settings_path = directory / 'settings.json'
        settings_path.write_text(json.dumps(settings))
        environment = dict(os.environ, PYTHONIOENCODING='utf-8', MESHCORE_SENDER='Alice')
        def execute(query):
            """Invoke the registered standalone trail entry point from an unrelated cwd."""
            return subprocess.run([sys.executable, str(service.ROOT / 'scripts/trail.py'),
                '--settings', str(settings_path), *query.split()], cwd=directory, env=environment,
                capture_output=True, text=True, encoding='utf-8', timeout=30)
        for query, expected in [('Oak Loop end id 0042', '-122.10000'),
                                ('find dogs shade near 37.9 -122.2', 'Mostly Shade')]:
            result = execute(query)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)
        path = directory / 'trail_endpoints.geojson'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(data.GISUnavailable, 'integrity'):
            data.Snapshot(directory).load_dataset('trail_endpoints')
        result = execute('Oak Loop end')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Local GIS data unavailable', result.stdout)
        self.assertNotIn('mapped end 37.', result.stdout)


class TrailResponderTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_program_runs_new_forms_on_requesting_channel(self):
        """Verify actual subprocess routing through the existing trail registration."""
        config = json.loads((service.ROOT / 'config.json').read_bytes())['responder']
        self.assertEqual(config['commands']['!trail']['script'], 'scripts/trail.py')
        self.assertEqual(config['commands']['!trail']['args'], [])
        responder.validate_config(config, service.ROOT)
        for query, expected in [('Recreation Loop end', 'mapped end'),
                                ('find dogs shade near 37.9 -122.2', 'shade')]:
            with self.subTest(query=query):
                database = sqlite3.connect(':memory:')
                self.addCleanup(database.close)
                self.assertEqual(responder.match_command('!trail ' + query, config['commands']),
                                 ('!trail', [query], None))
                send = AsyncMock()
                bot = responder.Responder(service.ROOT, database, config, 3, 'Bot', send)
                packet = {'channel_idx': 3, 'txt_type': 0, 'text': 'Alice: !trail ' + query,
                          'sender_timestamp': int(time.time())}
                self.assertTrue(bot.accept(packet))
                with patch.object(asyncio, 'sleep', new=AsyncMock()):
                    self.assertTrue(await bot.process_one())
                messages = [call.args for call in send.await_args_list]
                self.assertTrue(messages)
                self.assertTrue(all(channel == 3 and text.startswith('@Alice ') for channel, text in messages))
                self.assertTrue(all(len(text.encode()) <= 150 for _, text in messages))
                self.assertIn(expected, ' '.join(text for _, text in messages))


if __name__ == '__main__':
    unittest.main()
