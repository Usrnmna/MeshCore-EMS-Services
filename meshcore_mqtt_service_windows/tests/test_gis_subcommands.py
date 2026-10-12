"""Focused GIS fields, affirmative filters, and closest-only search contracts."""

import json
import unittest
from unittest.mock import Mock, patch

from shapely.geometry import LineString, Point, box, mapping

import responder
import service
from scripts import gis_data as data, gis_lookup as lookup, gis_spatial as spatial


def feature(dataset, name, longitude=-122.2, latitude=37.9, **properties):
    """Construct a source-shaped record with deterministic, valid test geometry."""
    category = data.LAYER_FIELDS[dataset][0]
    geometry = Point(longitude, latitude)
    if category == 'Trail':
        geometry = LineString([(longitude, latitude), (longitude, latitude + .001)])
    elif category in {'Park', 'Recreation area', 'Reservoir', 'Watershed'}:
        geometry = box(longitude - .001, latitude - .001, longitude + .001, latitude + .001)
    return {'name': name, 'named': True, 'dataset': dataset, 'category': category,
            'geometry': mapping(geometry), 'properties': properties}


class GISSubcommandTests(unittest.TestCase):
    def setUp(self):
        self.settings = data.load_settings()
        self.settings['max_reply_bytes'] = 2000
        self.layers = {name: [] for name in data.LAYER_FIELDS}
        self.snapshot = Mock()
        self.snapshot.load_dataset.side_effect = lambda name: self.layers[name]
        self.patch = patch.object(lookup, 'Snapshot', return_value=self.snapshot)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def reply(self, kind, query):
        """Execute a complete lookup over the deterministic source fixtures."""
        result = lookup.lookup(kind, query, self.settings)
        self.assertNotIn('Snapshot ', result)
        return result

    def test_named_field_info_and_default_identification(self):
        self.layers['trails'] = [feature('trails', 'Bear Creek', DOGS='No', HORSES='Yes', LENGTH_MIL=5.41)]
        self.assertEqual(self.reply('trail', 'Bear Creek dogs'), 'Bear Creek: dogs No.')
        brief = self.reply('trail', 'Bear Creek')
        self.assertIn('Subcommands:', brief)
        self.assertNotIn('5.41', brief)
        detailed = self.reply('trail', 'Bear Creek info')
        self.assertIn('5.41 mi', detailed)
        self.assertIn('dogs No', detailed)
        self.snapshot.verify_unchanged.assert_called()

    def test_all_trail_attributes(self):
        self.layers['trails'] = [feature('trails', 'Trail A', DOGS='Yes', HORSES='No', BIKES='Yes',
            LENGTH_MIL=2, DIFFICULTY='Difficult', ELEVATION_GAIN=100, SURFACE='Dirt', SUN_SHADE='Shade',
            HOUR=1, TRAIL_DESC='A short description')]
        self.layers['trail_endpoints'] = [feature('trail_endpoints', 'Trail A', END_POINT='START')]
        self.layers['watershed_boundary'] = [feature('watershed_boundary', 'Test County')]
        expected = {'dogs': 'Yes', 'horses': 'No', 'bikes': 'Yes', 'length': '2 mi',
                    'difficulty': 'Strenuous', 'gain': '100 ft', 'surface': 'Dirt', 'shade': 'Shade',
                    'time': '1 hr', 'start': '37.90000,-122.20000', 'areas': 'Test County',
                    'description': 'A short description', 'info': 'dogs Yes'}
        for attribute, text in expected.items():
            with self.subTest(attribute=attribute):
                self.assertIn(text, self.reply('trail', 'Trail A ' + attribute))

    def test_recreation_peak_and_park_attributes(self):
        self.layers['recreation_points'] = [feature('recreation_points', 'Rec A', TYPE='Staging Area',
            PARKING='Limited', RESTROOM='ADA', DRINKING_WATER='Yes', PICNIC_AREA='Yes', FISHING='No',
            BOAT_LAUNCH='No', BOAT_RENTAL='No', PLAYGROUND='Yes', HORSE_PARKING='phYes')]
        self.layers['peaks'] = [feature('peaks', 'Peak A', ELEVATION=1200)]
        self.layers['ebrpd'] = [feature('ebrpd', 'Park A', STATUS='Landbank', AGENCY_NAM='Agency A')]
        for kind, name in [('rec', 'Rec A'), ('peak', 'Peak A'), ('park', 'Park A')]:
            for attribute in data.SUBCOMMANDS[kind]:
                with self.subTest(kind=kind, attribute=attribute):
                    self.assertIn(name, self.reply(kind, name + ' ' + attribute))
        self.assertEqual(self.reply('rec', 'Rec A parking'), 'Rec A: parking Limited.')
        self.assertEqual(self.reply('rec', 'Rec A restrooms'), 'Rec A: restrooms ADA.')
        self.assertEqual(self.reply('peak', 'Peak A elevation'), 'Peak A: elevation 1200 ft.')
        self.assertEqual(self.reply('park', 'Park A status'), 'Park A: status Landbank.')
        self.assertIn('Rec A', self.reply('park', 'Park A recreation'))

    def test_filter_precedes_nearest_and_preserves_conditions(self):
        self.layers['trails'] = [feature('trails', 'Closer forbidden', DOGS='No')]
        self.layers['additional_trails'] = [feature('additional_trails', 'Farther allowed', -122.1,
                                                   DOG='Limited to Park Hours')]
        result = self.reply('trail', 'dogs near 37.9 -122.2')
        self.assertIn('Farther allowed', result)
        self.assertIn('Limited to Park Hours', result)
        self.assertNotIn('Closer forbidden', result)
        self.assertNotIn('more', result)

    def test_no_radius_returns_one_even_beyond_old_default_and_maximum(self):
        self.settings['default_radius_miles'] = .001
        self.settings['maximum_radius_miles'] = 1
        self.layers['peaks'] = [feature('peaks', 'Far peak', -121.3), feature('peaks', 'Further peak', -121.1)]
        for query in ('near 37.9 -122.2', '37.9 -122.2'):
            result = self.reply('peak', query)
            self.assertIn('Far peak', result)
            self.assertNotIn('Further peak', result)
            self.assertNotIn('more', result)
        self.assertIn('No matching', self.reply('peak', 'near 37.9 -122.2 1'))
        with self.assertRaises(ValueError):
            self.reply('peak', 'near 37.9 -122.2 2')

    def test_explicit_radius_lists_matches_and_omitted_count(self):
        self.layers['peaks'] = [feature('peaks', name, -122.2 + offset)
                               for name, offset in [('A', 0), ('B', .01), ('C', .02), ('Outside', 1)]]
        self.settings['max_results'] = 2
        result = self.reply('peak', 'near 37.9 -122.2 2')
        self.assertIn('Peak: A', result)
        self.assertIn('Peak: B', result)
        self.assertIn('+1 more', result)
        self.assertNotIn('Outside', result)

    def test_equal_distance_returns_one_by_name(self):
        self.layers['peaks'] = [feature('peaks', 'Zulu'), feature('peaks', 'Alpha')]
        result = self.reply('peak', 'near 37.9 -122.2')
        self.assertIn('Alpha', result)
        self.assertNotIn('Zulu', result)
        self.assertNotIn('more', result)

    def test_filters_exclude_unknown_missing_and_conflicting_policy(self):
        for value in (None, 'No', 'Unknown', 'Yes except closed areas'):
            with self.subTest(value=value):
                self.assertFalse(lookup.eligible([feature('trails', 'A', DOGS=value)], 'trail', 'dogs'))
        mixed = [feature('trails', 'A', DOGS='Yes'), feature('trails', 'A', DOGS='No')]
        self.assertFalse(lookup.eligible(mixed, 'trail', 'dogs'))
        self.assertTrue(lookup.eligible([feature('additional_trails', 'A', BICYCLE='Yes L')], 'trail', 'bikes'))
        self.layers['trails'] = [feature('trails', 'Unknown')]
        self.assertIn('No matching', self.reply('trail', 'dogs near 37.9 -122.2'))
        self.assertEqual(self.reply('trail', 'Unknown dogs'), 'Unknown: dogs not recorded.')

    def test_each_amenity_filter_and_qualified_values(self):
        for attribute, allowed in lookup.FILTER_VALUES['rec'].items():
            field = lookup.ATTRIBUTE_FIELDS['rec'][attribute][0]
            for value in allowed:
                with self.subTest(attribute=attribute, value=value):
                    self.layers['recreation_points'] = [feature('recreation_points', 'Rejected', **{field: 'No'}),
                        feature('recreation_points', 'Qualified', -122.19, **{field: value})]
                    result = self.reply('rec', attribute + ' near 37.9 -122.2')
                    self.assertIn('Qualified', result)
                    self.assertNotIn('Rejected', result)

    def test_boundary_category_containment_nearest_and_trail_overlap(self):
        for dataset, name in [('ebrpd', 'Park A'), ('watershed_boundary', 'County A'),
                              ('reservoirs', 'Reservoir A'), ('recreation_areas', 'Rec Area A')]:
            self.layers[dataset] = [feature(dataset, name)]
        self.layers['trails'] = [feature('trails', 'Trail A')]
        for category, expected in [('parks', 'Park A'), ('watersheds', 'County A'),
                                   ('reservoirs', 'Reservoir A'), ('recreation', 'Rec Area A')]:
            for query in (f'{category} 37.9 -122.2', f'{category} near 37.9 -122.2',
                          f'{category} near 37.9 -122.2 2', f'{category} trail Trail A'):
                with self.subTest(query=query):
                    result = self.reply('boundary', query)
                    self.assertIn(expected, result)
                    for other in ('Park A', 'County A', 'Reservoir A', 'Rec Area A'):
                        if other != expected:
                            self.assertNotIn(other, result)

    def test_null_geometry_is_skipped_and_near_attribute_is_focused(self):
        missing = feature('peaks', 'Null peak', ELEVATION=99)
        missing['geometry'] = None
        self.layers['peaks'] = [missing, feature('peaks', 'Mapped peak', ELEVATION=1200)]
        result = self.reply('peak', 'elevation near 37.9 -122.2')
        self.assertIn('elevation 1200 ft', result)
        self.assertNotIn('Null peak', result)
        self.assertNotIn('location', result)

    def test_parser_rejects_malformed_filtered_queries(self):
        for kind, query in [('trail', 'dogs near nan -122.2'), ('rec', 'water near 91 -122'),
                            ('peak', 'elevation near 37 -122 0'), ('trail', 'dogs near 37 -122 -1'),
                            ('rec', 'unknown near 37 -122'), ('boundary', 'parks'),
                            ('boundary', 'watersheds near 37 -122 2 extra')]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                data.parse_command_query(kind, query)
        self.assertEqual(data.parse_command_query('trail', 'Bear Creek dogs'), ('name', 'Bear Creek', 'dogs'))
        self.assertEqual(data.parse_command_query('trail', 'dogs near 37.9,-122.2'),
                         ('near', (37.9, -122.2), 'dogs'))

    def test_bare_command_help_and_responder_argument_passthrough(self):
        commands = json.loads((service.ROOT / 'config.json').read_bytes())['responder']['commands']
        self.settings['max_reply_bytes'] = 200
        for kind in data.SUBCOMMANDS:
            self.assertEqual(responder.match_command('!' + kind, commands)[1], ['help'])
            self.assertIn('!' + kind, self.reply(kind, 'help'))
            self.assertLessEqual(len(self.reply(kind, 'help').encode('utf-8')), 200)
        for query in ('Bear Creek dogs', 'dogs near 37.9 -122.2', 'dogs near 37.9 -122.2 2'):
            self.assertEqual(responder.match_command('!trail ' + query, commands)[1], [query])


if __name__ == '__main__':
    unittest.main()
