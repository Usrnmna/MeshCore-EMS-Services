"""Focused GIS fields, affirmative filters, and closest-only search contracts."""

import json
import os
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
        self.assertEqual(brief, 'Trail: Bear Creek.')
        self.assertNotIn('5.41', brief)
        detailed = self.reply('trail', 'Bear Creek info')
        self.assertIn('5.41 mi', detailed)
        self.assertIn('dogs No', detailed)
        self.snapshot.verify_unchanged.assert_called()

    def test_info_and_time_never_split_parenthetical_qualifiers(self):
        self.layers['trails'] = [feature('trails', 'Oak Loop', LENGTH_MIL=2, HOUR=.5,
            DIFFICULTY='Easy', ELEVATION_GAIN=100, SURFACE='Dirt', SUN_SHADE='Shade',
            DOGS='Yes', HORSES='Yes', BIKES='Yes')]
        for query in ('Oak Loop info', 'Oak Loop time', 'info near 37.9 -122.2',
                      'time near 37.9 -122.2', 'time near 37.9,-122.2 2'):
            for sender in ('Alice', 'a' * 80, '温' * 26):
                with self.subTest(query=query, sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                    text = responder.reply_parts(sender, self.reply('trail', query), max_parts=1)[0]
                    self.assertEqual(text.count('('), text.count(')'))
                    self.assertLessEqual(len(text.encode()), 150)
                    if '3 mph' in text:
                        self.assertIn('(3 mph; terrain excluded)', text)
                    self.assertNotIn('bikes Yes. Estimated', text)
                    if query == 'Oak Loop time' and sender == 'Alice':
                        self.assertIn('0.5 hr (3 mph; terrain excluded)', text)

    def test_info_omits_start_and_polygon_counts_but_preserves_focused_start(self):
        trail = feature('trails', 'Oak Loop', LENGTH_MIL=2, HOUR=.5, DIFFICULTY='Easy',
                        ELEVATION_GAIN=100, SURFACE='Dirt', SUN_SHADE='Shade',
                        DOGS='Yes', HORSES='Yes', BIKES='Yes')
        park = feature('ebrpd', 'Oak Park', STATUS='Landbank', AGENCY_NAM='Oak District')
        self.layers['trails'] = [trail]
        self.layers['ebrpd'] = [park]
        self.layers['trail_endpoints'] = [feature('trail_endpoints', 'Oak Loop', END_POINT='START')]
        geometry = spatial.Spatial(self.settings)
        self.assertNotIn('mapped start', lookup.format_trail_reply([trail], self.snapshot, geometry, self.settings))
        self.assertNotIn('source polygon', lookup.format_park_reply([park], self.snapshot, geometry, self.settings))
        for kind, name in (('trail', 'Oak Loop'), ('park', 'Oak Park')):
            for query in (name + ' info', 'info near 37.9 -122.2', 'info near 37.9,-122.2 2'):
                for sender in ('Alice', 'a' * 80, '温' * 26):
                    with self.subTest(kind=kind, query=query, sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                        text = responder.reply_parts(sender, self.reply(kind, query), max_parts=1)[0]
                        self.assertNotIn('mapped start', text)
                        self.assertNotIn('source polygon', text)
                        self.assertIn(name, text)
                        if kind == 'park':
                            self.assertIn('[Landbank]', text)
                        self.assertLessEqual(len(text.encode()), 150)
        for query in ('Oak Loop start', 'start near 37.9 -122.2'):
            self.assertIn('mapped start 37.90000,-122.20000', self.reply('trail', query))

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
        self.assertIn('Peaks within 2 mi: A', result)
        self.assertIn('B (', result)
        self.assertNotIn('more', result)
        self.assertLessEqual(len(('@Reader ' + result).encode()), 150)
        self.assertNotIn('Outside', result)

    def test_equal_distance_returns_one_by_name(self):
        self.layers['peaks'] = [feature('peaks', 'Zulu'), feature('peaks', 'Alpha')]
        result = self.reply('peak', 'near 37.9 -122.2')
        self.assertIn('Alpha', result)
        self.assertNotIn('Zulu', result)
        self.assertNotIn('more', result)

    def test_near_families_fit_one_tagged_message(self):
        for dataset in ('trails', 'recreation_points', 'peaks', 'ebrpd'):
            self.layers[dataset] = [feature(dataset, 'A')]
        for kind in ('trail', 'rec', 'peak', 'park', 'boundary'):
            for radius in ('', ' 2'):
                query = ('parks ' if kind == 'boundary' else '') + 'near 37.9 -122.2' + radius
                for sender in ('Alice', 'a' * 80, '温' * 26):
                    with self.subTest(kind=kind, radius=radius, sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                        result = responder.reply_parts(sender, self.reply(kind, query), max_parts=1)
                        self.assertEqual(len(result), 1)
                        self.assertLessEqual(len(result[0].encode()), 150)
                        self.assertIn('map distance', result[0])
                        self.assertIn('A [Park]' if kind == 'boundary' and radius else ': A ', result[0])
                        self.assertIn('(0.00 mi map distance)', result[0])
                        self.assertNotIn('Unable to return', result[0])
                        self.assertNotIn('page', result[0])

    def test_near_headings_avoid_stacked_labels(self):
        self.layers['trails'] = [feature('trails', 'Bear Creek')]
        self.assertEqual(self.reply('trail', 'near 37.9 -122.2'),
                         'Nearest trail: Bear Creek (0.00 mi map distance).')
        self.assertEqual(self.reply('trail', 'near 37.9 -122.2 2'),
                         'Trails within 2 mi: Bear Creek (0.00 mi map distance).')
        self.layers['ebrpd'] = [feature('ebrpd', 'Park A')]
        self.assertEqual(self.reply('boundary', 'parks near 37.9 -122.2'),
                         'Nearest park: Park A (0.00 mi map distance).')
        self.assertEqual(self.reply('boundary', 'parks near 37.9 -122.2 2'),
                         'Areas within 2 mi: Park A [Park] (0.00 mi map distance).')

    def test_near_info_keeps_identity_once_and_park_status(self):
        self.layers['peaks'] = [feature('peaks', 'Peak A', ELEVATION=1200)]
        self.layers['ebrpd'] = [feature('ebrpd', 'Park A', STATUS='Landbank')]
        for kind, name, detail in (('peak', 'Peak A', 'elevation 1200 ft'),
                                   ('park', 'Park A', '[Landbank]')):
            for radius in ('', ' 2'):
                text = self.reply(kind, 'info near 37.9 -122.2' + radius)
                self.assertEqual(text.count(name), 1)
                self.assertIn(detail, text)
                self.assertIn('0.00 mi map distance', text)
                self.assertNotIn('Closest,', text)

    def test_filtered_near_keeps_policy_qualification_on_radio(self):
        self.layers['trails'] = [feature('trails', 'Closed', DOGS='No')]
        self.layers['additional_trails'] = [feature('additional_trails', 'A', -122.19,
                                                   DOG='Limited to Park Hours')]
        for radius in ('', ' 2'):
            result = responder.reply_parts('Alice', self.reply('trail', 'dogs near 37.9 -122.2' + radius), max_parts=1)
            self.assertEqual(len(result), 1)
            self.assertLessEqual(len(result[0].encode()), 150)
            self.assertIn('Limited to Park Hours', result[0])
            self.assertNotIn('Closed', result[0])

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

    def test_boundary_containment_labels_preserve_relation_and_status(self):
        park = feature('ebrpd', 'Example Park', STATUS='Landbank')
        self.layers['ebrpd'] = [park]
        lon, lat = park['geometry']['coordinates'][0][0]
        for query, expected in (
            ('37.9 -122.2', 'Inside mapped park: Example Park [Landbank].'),
            (f'{lat} {lon}', 'On mapped park boundary: Example Park [Landbank].'),
            ('37.95 -122.2', 'No containing areas in local map data.'),
        ):
            for sender in ('Alice', 'a' * 80, '温' * 26):
                with self.subTest(query=query, sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                    text = self.reply('boundary', query)
                    self.assertEqual(text, expected)
                    parts = responder.reply_parts(sender, text, max_parts=1)
                    self.assertEqual(len(parts), 1)
                    self.assertLessEqual(len(parts[0].encode()), 150)

    def test_boundary_multiple_categories_keep_each_relation(self):
        self.layers['ebrpd'] = [feature('ebrpd', 'Park A', STATUS='Closed')]
        self.layers['reservoirs'] = [feature('reservoirs', 'Reservoir A')]
        result = self.reply('boundary', '37.9 -122.2')
        self.assertIn('Inside mapped park: Park A [Closed]', result)
        self.assertIn('Inside mapped reservoir: Reservoir A', result)
        self.assertNotIn('Mapped areas: inside', result)

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
