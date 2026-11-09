"""Synthetic W10-D fixtures; no real provider admission or operational coverage."""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import dataset_paths, flood_evidence, flood_geometry
from scripts import flood_hazard as hazard, flood_hazard_data as data, water_settings


def polygon(left=0, bottom=0, right=1, top=1):
    """Return a synthetic closed polygon with no relation to a real hazard zone."""
    return dict(type='Polygon', coordinates=[[[left, bottom], [right, bottom],
                [right, top], [left, top], [left, bottom]]])


class HazardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'flood_hazards'
        self.folder = self.root / 'static/g1'
        self.config = water_settings.validate({'data_directory': str(self.base)})
        self.features = [dict(type='Feature', properties=dict(FLD_AR_ID='0001', FLD_ZONE='AE',
            ZONE_SUBTY='Synthetic study zone', PROB_CLASS='recorded annual-chance class',
            STATIC_BFE=10.125, DEPTH=None, LEN_UNIT='US survey feet', V_DATUM='NAVD88',
            SOURCE_NOTE='Fixture only; no current conditions', STUDY_DATE='2001-01-01',
            EFF_DATE='2003-01-01', REG_STATUS='recorded regulatory status'), geometry=polygon())]
        self.coverage_features = [dict(type='Feature', properties=dict(ID='panel-001',
            mapping='mapped'), geometry=polygon(-1, -1, 3, 3))]
        self.product = dict(source='FEMA', product='NFHL-fixture', version='0001', generation='g1',
            publication_status='effective', regulatory_status='recorded product status',
            regions=['state:CA'], study_date='2001-01-01', effective_date='2003-01-01',
            source_vintage='2003-01-01', retrieved_at='2026-01-01T00:00:00Z',
            source_url='https://example.invalid/synthetic', qualifications=['Synthetic fixture only'],
            review_reference='fixture-review', evidence_files=['evidence.json'],
            zones=dict(path='zones.geojson.gz', id_field='FLD_AR_ID', complete=True, record_count=1, fields=dict(
                zone_code='FLD_ZONE', description='ZONE_SUBTY', probability_class='PROB_CLASS',
                base_flood_elevation='STATIC_BFE', depth='DEPTH', units='LEN_UNIT',
                vertical_reference='V_DATUM', qualification='SOURCE_NOTE', study_date='STUDY_DATE',
                effective_date='EFF_DATE', regulatory_status='REG_STATUS')),
            coverage=dict(path='coverage.geojson.gz', id_field='ID', state_field='mapping',
                          complete=True, record_count=1, reference='Synthetic mapping-coverage evidence'))
        self.manifest = dict(schema_version=1, generation='g1', kind='static_flood_hazard',
            complete=True, created_at_utc='2026-01-01T00:00:00Z', files={}, products=[self.product])
        self.publish()

    def artifact(self, relative, value):
        """Write isolated fixture bytes and the exact expected digest."""
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value).encode()
        if relative.endswith('.gz'):
            raw = gzip.compress(raw, mtime=0)
        path.write_bytes(raw)
        self.manifest['files'][relative] = dict(byte_count=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    def pin(self):
        """Update only the isolated fixture manifest and pointer."""
        raw = json.dumps(self.manifest).encode()
        (self.folder / 'manifest.json').write_bytes(raw)
        (self.root / 'static.json').write_text(json.dumps(dict(manifest_path='static/g1/manifest.json',
            byte_count=len(raw), sha256=hashlib.sha256(raw).hexdigest())), encoding='utf-8')

    def publish(self):
        """Publish source-shaped synthetic polygons and separate coverage evidence."""
        self.product['zones']['record_count'] = len(self.features)
        self.product['coverage']['record_count'] = len(self.coverage_features)
        self.artifact('evidence.json', {'qualification': 'Synthetic; not provider evidence'})
        self.artifact('zones.geojson.gz', dict(type='FeatureCollection', features=self.features))
        self.artifact('coverage.geojson.gz', dict(type='FeatureCollection', features=self.coverage_features))
        self.pin()

    def point(self, lat=.5, lon=.5, **selectors):
        return hazard.at_coordinate(lat, lon, config=self.config, **selectors)

    def row(self, lat=.5, lon=.5, **selectors):
        result = self.point(lat, lon, **selectors)
        self.assertIn(result['status'], ('ok', 'partial'), result)
        return result['records'][0]

    def test_discovery_preserves_dates_status_and_qualification(self):
        result = hazard.discover(config=self.config)
        self.assertEqual(result['status'], 'ok')
        row = result['records'][0]
        self.assertEqual(row['version'], '0001')
        self.assertEqual(row['study_date'], '2001-01-01')
        self.assertEqual(row['effective_date'], '2003-01-01')
        self.assertNotEqual(row['source_vintage'], row['retrieved_at'])
        self.assertEqual(row['geometry_integrity'], 'unchecked')
        self.assertEqual(row['qualifications'], ['Synthetic fixture only'])

    def test_long_source_qualifications_are_preserved_as_complete_text(self):
        qualification = ('Source coverage remains partial.\n' * 30) + '\u6c34'
        self.product['qualifications'] = [qualification]
        self.pin()
        self.assertEqual(self.row()['qualifications'], [qualification])
        self.assertEqual(hazard.discover(config=self.config)['records'][0]['qualifications'], [qualification])

    def test_exact_selectors_and_leading_zeroes(self):
        selectors = dict(source='FEMA', product='NFHL-fixture', version='0001')
        self.assertEqual(self.row(feature_id='0001', **selectors)['matches'][0]['id'], '0001')
        self.assertEqual(self.row(feature_id='1', **selectors)['relation'], 'unknown_feature')
        for changes in ({'source': 'fema'}, {'version': '1'}, {'region': 'state:NV'}):
            self.assertEqual(self.point(**dict(selectors, **changes))['status'], 'no_matching_product')

    def test_invalid_arguments_fail_before_io(self):
        for lat, lon in ((True, 0), (91, 0), (0, 181), (float('nan'), 0), ('0', 0)):
            with self.subTest(lat=lat), patch.object(data, 'Snapshot') as reader:
                with self.assertRaises(ValueError):
                    self.point(lat, lon)
                reader.assert_not_called()
        for args in ({'limit': 0}, {'limit': True}, {'source': 'x'*161},
                     {'uncertainty_degrees': -1}, {'uncertainty_degrees': float('inf')},
                     {'feature_id': '1'}):
            with self.subTest(args=args), patch.object(data, 'Snapshot') as reader:
                with self.assertRaises(ValueError):
                    self.point(**args)
                reader.assert_not_called()

    def test_distinct_static_evidence_class(self):
        self.assertIn('static_flood_hazard', flood_evidence.EVIDENCE_CLASSES)
        result = self.point()
        self.assertEqual(result['evidence_class'], 'static_flood_hazard')
        self.assertNotIn('scenario', result)
        self.assertIn('not current inundation', result['qualification'])

    def test_source_values_units_and_missing_classification(self):
        row = self.row()['matches'][0]
        self.assertEqual(row['properties'], self.features[0]['properties'])
        self.assertEqual(row['recorded_fields']['probability_class'], 'recorded annual-chance class')
        self.assertEqual(row['measurements'][0]['recorded_value'], 10.125)
        self.assertEqual(row['measurements'][0]['units'], 'US survey feet')
        self.features[0]['properties'].update(FLD_ZONE='UNRECOGNIZED-SOURCE-CODE', V_DATUM=None, LEN_UNIT=None)
        del self.features[0]['properties']['PROB_CLASS']
        self.publish()
        row = self.row()['matches'][0]
        self.assertEqual(row['recorded_fields']['zone_code'], 'UNRECOGNIZED-SOURCE-CODE')
        self.assertIn('probability_class', row['missing_fields'])
        self.assertIn('vertical_reference', row['missing_fields'])
        self.assertIsNone(row['measurements'][0]['units'])
        self.assertIsNone(row['measurements'][0]['vertical_reference'])

    def test_depth_remains_recorded_not_current(self):
        self.features[0]['properties'].update(STATIC_BFE=None, DEPTH=2.75, LEN_UNIT='feet', V_DATUM=None)
        self.publish()
        measurement = self.row()['matches'][0]['measurements'][0]
        self.assertEqual(measurement['kind'], 'depth')
        self.assertEqual(measurement['recorded_value'], 2.75)
        self.assertIn('no conversion or current-depth inference', measurement['qualification'])

    def test_measurements_keep_individual_units_and_vertical_references(self):
        self.features[0]['properties'].update(DEPTH=2.5, BFE_UNIT='US survey feet',
            DEPTH_UNIT='meters', BFE_DATUM='NAVD88', DEPTH_DATUM='local ground')
        self.product['zones']['fields'].update(base_flood_elevation_units='BFE_UNIT',
            depth_units='DEPTH_UNIT', base_flood_elevation_vertical_reference='BFE_DATUM',
            depth_vertical_reference='DEPTH_DATUM')
        self.publish()
        measurements = {row['kind']: row for row in self.row()['matches'][0]['measurements']}
        self.assertEqual(measurements['base_flood_elevation']['units'], 'US survey feet')
        self.assertEqual(measurements['depth']['units'], 'meters')
        self.assertEqual(measurements['depth']['vertical_reference'], 'local ground')
        self.features[0]['properties']['DEPTH_UNIT'] = None
        self.publish()
        measurements = {row['kind']: row for row in self.row()['matches'][0]['measurements']}
        self.assertIsNone(measurements['depth']['units'])

    def test_non_numeric_measurements_remain_raw_properties_only(self):
        for value in (True, 'unavailable', {'value': 10}, [10]):
            with self.subTest(value=value):
                self.features[0]['properties']['STATIC_BFE'] = value
                self.publish()
                result = self.point()
                row = result['records'][0]['matches'][0]
                self.assertEqual(row['properties']['STATIC_BFE'], value)
                self.assertEqual(row['measurements'], [])
                self.assertIn('base_flood_elevation', row['invalid_fields'])
                self.assertEqual(result['status'], 'partial')

    def test_invalid_unit_and_datum_values_are_not_attached_to_measurements(self):
        self.features[0]['properties'].update(LEN_UNIT=['feet'], V_DATUM={'name': 'NAVD88'})
        self.publish()
        result = self.point()
        self.assertEqual(result['status'], 'partial')
        row = result['records'][0]['matches'][0]
        self.assertEqual(row['properties']['LEN_UNIT'], ['feet'])
        self.assertEqual(row['invalid_fields'], ['units', 'vertical_reference'])
        self.assertIsNone(row['measurements'][0]['units'])
        self.assertIsNone(row['measurements'][0]['vertical_reference'])

    def test_json_exponent_overflow_is_rejected_even_outside_zones(self):
        raw = json.dumps(dict(type='FeatureCollection', features=self.features)).replace('10.125', '1e999').encode()
        compressed = gzip.compress(raw)
        (self.folder/'zones.geojson.gz').write_bytes(compressed)
        self.manifest['files']['zones.geojson.gz'] = dict(byte_count=len(compressed),
            sha256=hashlib.sha256(compressed).hexdigest())
        self.pin()
        result = self.point(2, 2)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reasons'], ['nonfinite_json_value'])

    def test_source_missing_value_sentinels_are_preserved_but_not_measurements(self):
        self.features[0]['properties']['STATIC_BFE'] = -9999
        self.product['zones']['missing_values'] = {'base_flood_elevation': [-9999]}
        self.publish()
        row = self.row()['matches'][0]
        self.assertEqual(row['properties']['STATIC_BFE'], -9999)
        self.assertIn('base_flood_elevation', row['missing_fields'])
        self.assertEqual(row['measurements'], [])

    def test_dwr_shaped_fields_are_not_translated_to_fema_classes(self):
        self.product.update(source='CA-DWR', product='BAM-fixture', publication_status='unknown',
                            regulatory_status='nonregulatory fixture', effective_date=None)
        self.product['zones']['fields'] = {'probability_class': 'RETURN_PERIOD', 'qualification': 'NOTE'}
        self.features[0]['properties'] = {'FLD_AR_ID': '0001', 'RETURN_PERIOD': '100-year',
                                        'NOTE': 'Composite source coverage; fixture only'}
        self.publish()
        row = self.row()
        self.assertEqual(row['regulatory_status'], 'nonregulatory fixture')
        self.assertEqual(row['matches'][0]['recorded_fields']['probability_class'], '100-year')
        self.assertIn('zone_code', row['matches'][0]['missing_fields'])
        self.assertNotIn('AE', json.dumps(row))

    def test_all_publication_states_and_no_automatic_preference(self):
        for i, state in enumerate(data.PUBLICATION_STATES):
            self.manifest['products'].append(dict(self.product, version=str(i), publication_status=state))
        self.pin()
        result = self.point()
        self.assertEqual(len(result['records']), 6)
        self.assertEqual({r['publication_status'] for r in result['records']}, set(data.PUBLICATION_STATES))
        self.assertEqual(self.point(version='0001')['total'], 1)

    def test_source_and_product_collisions_preserved(self):
        self.manifest['products'].extend([dict(self.product, source='DWR'), dict(self.product, product='regional')])
        self.pin()
        self.assertEqual(self.point()['total'], 3)
        self.assertEqual(self.point(source='DWR')['total'], 1)
        self.assertEqual(self.point(source='FEMA', product='regional')['total'], 1)

    def test_duplicate_product_identity_is_ambiguous(self):
        self.manifest['products'].append(copy.deepcopy(self.product))
        self.pin()
        self.assertEqual(self.point()['status'], 'ambiguous')
        self.assertEqual(hazard.discover(config=self.config)['status'], 'ambiguous')

    def test_duplicate_feature_identity_is_ambiguous(self):
        self.features.append(copy.deepcopy(self.features[0]))
        self.features[1]['properties']['FLD_ZONE'] = 'X'
        self.publish()
        self.assertEqual(self.point()['status'], 'ambiguous')

    def test_string_integer_identity_collision_requires_disambiguation(self):
        self.features[0]['properties']['FLD_AR_ID'] = '1'
        self.features.append(copy.deepcopy(self.features[0]))
        self.features[1]['properties']['FLD_AR_ID'] = 1
        self.publish()
        self.assertEqual(len(self.row()['matches']), 2)
        self.assertEqual(self.point(source='FEMA', product='NFHL-fixture', version='0001', feature_id='1')['status'], 'ambiguous')

    def test_overlaps_are_returned_without_merging(self):
        other = copy.deepcopy(self.features[0])
        other['properties'].update(FLD_AR_ID='0002', FLD_ZONE='X', PROB_CLASS='different class')
        self.features.append(other)
        self.publish()
        result = self.point(limit=1)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['records'][0]['total_matches'], 2)
        self.assertEqual(result['records'][0]['omitted_matches'], 1)
        selected = self.row(source='FEMA', product='NFHL-fixture', version='0001', feature_id='0002', limit=1)
        self.assertEqual(selected['matches'][0]['recorded_fields']['zone_code'], 'X')

    def test_product_filter_precedes_limit(self):
        self.manifest['products'].append(dict(self.product, source='DWR'))
        self.pin()
        self.assertEqual(self.point(limit=1)['omitted'], 1)
        result = self.point(source='FEMA', limit=1)
        self.assertEqual(result['omitted'], 0)
        self.assertEqual(result['records'][0]['source'], 'FEMA')

    def test_negative_requires_complete_mapping_evidence(self):
        self.assertEqual(self.row(2, 2)['relation'], 'outside_selected_zones')
        self.product['coverage']['complete'] = False
        self.pin()
        self.assertEqual(self.row(2, 2)['relation'], 'coverage_partial')
        self.product['coverage'].update(path=None, complete=False)
        self.pin()
        self.assertEqual(self.row(2, 2)['relation'], 'coverage_unknown')

    def test_negative_also_requires_complete_zone_export(self):
        self.product['zones']['complete'] = False
        self.pin()
        self.assertEqual(self.row(2, 2)['relation'], 'coverage_partial')
        self.assertEqual(self.point()['status'], 'partial')
        del self.product['zones']['complete']
        self.pin()
        self.assertEqual(self.point()['status'], 'unavailable')

    def test_truncated_exports_are_not_negative_results(self):
        for name in ('zones', 'coverage'):
            self.product[name]['record_count'] += 1
            self.pin()
            result = self.point(2, 2)
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['records'], [])
            self.product[name]['record_count'] -= 1

    def test_unmapped_unknown_and_outside_mapping_extent(self):
        self.assertEqual(self.row(4, 4)['relation'], 'coverage_unknown')
        for state in ('unmapped', 'unknown'):
            self.coverage_features[0]['properties']['mapping'] = state
            self.publish()
            expected = 'unmapped' if state == 'unmapped' else 'coverage_unknown'
            self.assertEqual(self.row(2, 2)['relation'], expected)

    def test_coverage_conflict_and_zone_unmapped_conflict(self):
        other = copy.deepcopy(self.coverage_features[0])
        other['properties'].update(ID='panel-002', mapping='unmapped')
        self.coverage_features.append(other)
        self.publish()
        self.assertEqual(self.row(2, 2)['relation'], 'coverage_conflicting')
        self.assertEqual(self.point()['status'], 'partial')
        self.coverage_features = [other]
        self.publish()
        row = self.row()
        self.assertEqual(row['relation'], 'inside')
        self.assertIn('zone_coverage_conflict', row['issues'])

    def test_coverage_limit_preserves_aggregate_conflict_and_boundary(self):
        other = copy.deepcopy(self.coverage_features[0])
        other['properties'].update(ID='panel-002', mapping='unmapped')
        other['geometry'] = polygon(.5, .5, 3, 3)
        self.coverage_features.append(other)
        self.publish()
        result = self.point(limit=1)
        row = result['records'][0]
        coverage = row['coverage']
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(coverage['total_matches'], 2)
        self.assertEqual(coverage['omitted_matches'], 1)
        self.assertEqual(len(coverage['matches']), 1)
        self.assertEqual(coverage['state'], 'boundary_uncertain')
        self.assertTrue(coverage['conflicting'])
        self.assertIn('zone_coverage_conflict', row['issues'])

    def test_coverage_limit_does_not_hide_unmapped_state(self):
        other = copy.deepcopy(self.coverage_features[0])
        other['properties'].update(ID='panel-002', mapping='unmapped')
        self.coverage_features.append(other)
        self.publish()
        row = self.row(2, 2, limit=1)
        self.assertEqual(row['relation'], 'coverage_conflicting')
        self.assertEqual(len(row['coverage']['matches']), 1)
        self.assertEqual(row['coverage']['omitted_matches'], 1)

    def test_cross_border_regions_are_recorded_only(self):
        self.product['regions'].append('state:NV')
        self.pin()
        self.assertEqual(self.point(region='state:NV')['total'], 1)
        self.assertEqual(self.row(4, 4, region='state:NV')['relation'], 'coverage_unknown')

    def test_boundary_band_and_coordinate_uncertainty(self):
        self.assertEqual(self.row(.5, 1)['relation'], 'boundary_uncertain')
        self.assertEqual(self.row(.5, 1.0001)['relation'], 'outside_selected_zones')
        result = self.point(.5, 1.0001, uncertainty_degrees=.001)
        self.assertEqual(result['records'][0]['relation'], 'boundary_uncertain')
        self.assertIn('Not established', result['positional_accuracy'])
        self.assertEqual(self.row(3, 2)['relation'], 'coverage_boundary_uncertain')

    def test_holes_and_multipart(self):
        self.features[0]['geometry']['coordinates'].append(polygon(.2, .2, .8, .8)['coordinates'][0])
        self.publish()
        self.assertEqual(self.row()['relation'], 'outside_selected_zones')
        self.features[0]['geometry'] = dict(type='MultiPolygon', coordinates=[polygon()['coordinates'], polygon(1.5, 1.5, 2.5, 2.5)['coordinates']])
        self.publish()
        self.assertEqual(self.row(2, 2)['relation'], 'inside')

    def test_invalid_geometry_is_not_repaired_even_outside_query(self):
        for shape in (dict(type='Point', coordinates=[0, 0]), dict(type='Polygon', coordinates=[]),
                      dict(type='Polygon', coordinates=[[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]])):
            self.features[0]['geometry'] = shape
            self.publish()
            self.assertEqual(self.point(2, 2)['status'], 'unavailable')

    def test_unsupported_crs_and_nested_crs(self):
        self.artifact('zones.geojson.gz', dict(type='FeatureCollection', features=self.features,
            crs={'type':'name', 'properties':{'name':'EPSG:3857'}}))
        self.pin()
        self.assertEqual(self.point()['status'], 'unavailable')
        self.features[0]['geometry']['crs'] = {}
        self.publish()
        self.assertEqual(self.point()['status'], 'unavailable')

    def test_empty_zone_collection_still_requires_supported_crs(self):
        self.features = []
        self.publish()
        self.assertEqual(self.row()['relation'], 'outside_selected_zones')
        self.artifact('zones.geojson.gz', dict(type='FeatureCollection', features=[],
            crs={'type':'name', 'properties':{'name':'EPSG:3857'}}))
        self.pin()
        self.assertEqual(self.point()['status'], 'unavailable')

    def test_malformed_metadata_and_features_fail_explicitly(self):
        for feature in (None, {'type': 'Feature', 'properties': None},
                        {'type': 'Feature', 'properties': {'FLD_AR_ID': True}, 'geometry': polygon()}):
            self.features = [feature]
            self.publish()
            result = self.point()
            self.assertEqual(result['status'], 'unavailable', result)
        self.product['coverage'] = None
        self.pin()
        self.assertEqual(self.point()['status'], 'unavailable')

    def test_duplicate_json_keys_and_nonfinite_values_fail_explicitly(self):
        for raw in (b'{"type":"FeatureCollection","type":"Other","features":[]}',
                    b'{"type":"FeatureCollection","features":[],"value":NaN}'):
            path = self.folder/'zones.geojson.gz'
            compressed = gzip.compress(raw)
            path.write_bytes(compressed)
            self.manifest['files']['zones.geojson.gz'] = dict(byte_count=len(compressed),
                sha256=hashlib.sha256(compressed).hexdigest())
            self.pin()
            self.assertEqual(self.point()['status'], 'unavailable')

    def test_verification_deadline_is_shared(self):
        with patch.object(data.flood_reference_data, 'VERIFY_SECONDS', -1):
            self.assertEqual(self.point()['status'], 'limit')

    def test_geometry_feature_and_expansion_limits(self):
        for target, name, value in ((flood_geometry, 'MAX_VERTICES', 4),
                (flood_geometry, 'MAX_OPERATIONS', 1), (data, 'MAX_FEATURES', 0),
                (data, 'MAX_DOCUMENT_BYTES', 4000), (data, 'MAX_EXPANDED_BYTES', 10)):
            with self.subTest(name=name), patch.object(target, name, value):
                if name == 'MAX_DOCUMENT_BYTES':
                    self.features[0]['properties']['large'] = 'x'*5000
                    self.publish()
                result = self.point(2, 2)
                self.assertEqual(result['status'], 'limit', result)
                self.assertEqual(result['records'], [])

    def test_output_limit_withholds_qualifications_instead_of_truncating(self):
        self.features[0]['properties']['SOURCE_NOTE'] = '\u6c34'*1000
        self.publish()
        with patch.object(hazard, 'MAX_RESULT_BYTES', 1000):
            result = self.point()
        self.assertEqual(result['status'], 'limit')
        self.assertTrue(result['narrow_selection'])
        self.assertEqual(result['records'], [])
        self.assertIn('not current inundation', result['qualification'])

    def test_missing_root_and_missing_artifact_differ(self):
        missing = water_settings.validate({'data_directory': str(self.base/'missing')})
        self.assertEqual(hazard.discover(config=missing)['status'], 'not_installed')
        (self.folder/'zones.geojson.gz').unlink()
        self.assertEqual(self.point()['status'], 'unavailable')

    def test_integrity_failure_in_source_evidence_and_geometry(self):
        for path in ('evidence.json', 'zones.geojson.gz', 'coverage.geojson.gz'):
            with self.subTest(path=path):
                self.publish()
                (self.folder/path).write_bytes(b'corrupt')
                self.assertEqual(self.point()['status'], 'unavailable')
        self.assertEqual(self.point()['records'], [])

    def test_generation_and_product_contract_mismatches(self):
        for key, value in (('schema_version', 2), ('kind', 'static'), ('generation', 'other'), ('complete', False)):
            old = self.manifest[key]
            self.manifest[key] = value
            self.pin()
            self.assertEqual(self.point()['status'], 'incompatible')
            self.manifest[key] = old
        self.product['generation'] = 'other'
        self.pin()
        self.assertEqual(self.point()['status'], 'incompatible')

    def test_managed_removal_and_custom_path_isolation(self):
        registry = dict(schema=1, datasets={'flood_hazards': {'active': None}})
        (self.base/'datasets.json').write_text(json.dumps(registry))
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.base)}):
            self.assertEqual(self.point()['status'], 'removed')
            custom = self.base/'custom'
            config = water_settings.validate({'data_directory': str(custom)})
            self.assertEqual(hazard.discover(config=config)['status'], 'not_installed')

    def test_managed_selection_and_registry_switch(self):
        selected = self.base/'.datasets/flood_hazards/one/content'
        selected.parent.mkdir(parents=True)
        self.root.rename(selected)
        registry = dict(schema=1, datasets={'flood_hazards': {'active': {'path': str(selected.relative_to(self.base))}}})
        path = self.base/'datasets.json'
        path.write_text(json.dumps(registry))
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.base)}):
            self.assertEqual(self.point()['status'], 'ok')
            original = hazard._point_product
            def change(*args):
                result = original(*args)
                registry['datasets']['flood_hazards']['active'] = None
                path.write_text(json.dumps(registry))
                return result
            with patch.object(hazard, '_point_product', side_effect=change):
                result = self.point()
            self.assertEqual(result['reasons'], ['generation_changed'])

    def test_pointer_and_consumed_file_changes_withhold_results(self):
        original = hazard._point_product
        for relative in ('static.json', 'static/g1/zones.geojson.gz'):
            self.publish()
            def change(*args):
                result = original(*args)
                path = self.root/relative
                path.write_bytes(path.read_bytes()+b' ')
                return result
            with patch.object(hazard, '_point_product', side_effect=change):
                result = self.point()
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['reasons'], ['generation_changed'])

    def test_paths_cannot_escape_generation(self):
        self.product['zones']['path'] = '../outside.json'
        self.pin()
        self.assertEqual(self.point()['status'], 'unavailable')

    def test_discovery_without_geometry_dependency(self):
        with patch.object(flood_geometry, 'dependencies', side_effect=data.EvidenceError('geometry_dependency_unavailable')):
            self.assertEqual(hazard.discover(config=self.config)['status'], 'ok')
            self.assertEqual(self.point()['status'], 'unavailable')

    def test_no_matching_product_does_not_require_geometry_dependency(self):
        with patch.object(flood_geometry, 'dependencies', side_effect=data.EvidenceError('geometry_dependency_unavailable')):
            self.assertEqual(self.point(source='absent')['status'], 'no_matching_product')

    def test_no_files_changed_by_success_or_failure(self):
        def digest():
            return {str(p.relative_to(self.base)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.base.rglob('*') if p.is_file()}
        before = digest()
        self.point()
        hazard.discover(config=self.config)
        self.point(source='missing')
        self.assertEqual(digest(), before)

    def test_standalone_and_service_settings_without_repository_tools_or_orbits(self):
        program = '''
import builtins,json,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
    level=args[3] if len(args)>3 else kwargs.get('level',0)
    if name.split('.')[0] in {'skyfield','sgp4','data','tools','installers'} and level == 0:
        raise ImportError('Forbidden runtime dependency: '+name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from scripts import flood_hazard
result=flood_hazard.at_coordinate(.5,.5)
assert result['status']=='ok',result
print(result['evidence_class'])
'''
        env = dict(os.environ, MESHCORE_WATER_SETTINGS=json.dumps({'data_directory':str(self.base)}),
                   PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B', '-c', program], cwd=Path(__file__).resolve().parents[1],
            env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'static_flood_hazard')


if __name__ == '__main__':
    unittest.main()
