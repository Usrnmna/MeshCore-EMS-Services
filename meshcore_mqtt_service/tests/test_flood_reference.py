"""W10-B internal discovery and scenario selection; all positive scenarios are fixtures."""
import copy
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import flood_reference as f, flood_catalog as c, flood_reference_data as d, water_settings
from test_flood_evidence import fixture, write_json, digest


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root, self.folder, self.manifest = fixture(self.base)
        self.config = water_settings.validate({'data_directory': str(self.base)})
        self.manifest['network'] = 'NHD-v2'
        self.region = '01_north_coast'
        self.index = f'regions/{self.region}/relationships/inundation_scenarios.csv'
        self.link_path = f'regions/{self.region}/relationships/gauge_reach_links.csv'
        self.footprint = f'regions/{self.region}/inundation_scenarios.geojson.gz'
        self.properties = dict(ahps_lid='heac1', usgs_gage='00123', oid=1, states='CA', name='River',
                               mapped='yes', status='Good', wfo='MTR', rfc='CNRFC', huc8='00000001',
                               fim_version='6.2', model_version='4.9',
                               nrldb_timestamp='NWS source last updated: 2020-01-01 UTC')
        self.catalog = [self.properties, dict(self.properties, ahps_lid='other', usgs_gage='00055',
                        oid=2, mapped='no', status='Datum conversion failed', states='CA,NV')]
        self.link = dict(gauge_lid='HEAC1', usgs_id='00123', reach_id='0001', network='NHD-v2',
                         status='published_identifier_match', source_url='published-station-link')
        self.links = [self.link]
        self.rows = [dict(scenario_id='HEAC1_s'+str(n), gauge_lid='HEAC1', stage=str(n), stage_units='FT',
                          category='action', fim_version='6.2', model_version='4.9', source_layer='2',
                          source_stage_field='interval_stage', source_object_ids=str(n),
                          source_url=c.SOURCE_URL+'2', evidence_class='experimental_static_stage_scenario',
                          event_valid_time='', depth_status='not_available') for n in (21, 23)]
        # These explicit source references exercise qualified behavior. They do
        # not assert that the installed CatFIM snapshot contains datum evidence.
        self.source_rows = [dict(oid=n, ahps_lid='heac1', interval_stage=n, stage_uni='FT',
                                 fim_version='6.2', model_version='4.9',
                                 vertical_reference=dict(datum='NAVD88', zero=79.98, units='ft',
                                                         source_reference='published-scenario-datum')) for n in (21, 23)]
        self.gauge = dict(lid='HEAC1', usgsId='00123', reachId='0001',
                          datums={'vertical': {'value': [dict(abbrev='NAVD88', value=79.98, units='ft')]}})
        self.publish()

    def artifact(self, relative, raw):
        path = self.folder/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.manifest['files'][relative] = digest(raw)

    def json_artifact(self, relative, value):
        raw = json.dumps(value).encode()
        self.artifact(relative, gzip.compress(raw) if relative.endswith('.gz') else raw)

    def features(self, relative, rows):
        self.json_artifact(relative, dict(type='FeatureCollection', features=[dict(type='Feature', properties=r,
            geometry=dict(type='Polygon', coordinates=[[[0, 0], [1, 0], [1, 1], [0, 0]]])) for r in rows]))

    def csv_artifact(self, relative, rows, fields):
        text = io.StringIO(newline='')
        writer = csv.DictWriter(text, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        self.artifact(relative, text.getvalue().encode())

    def publish_manifest(self):
        pointer = dict(manifest_path='static/f1/manifest.json',
                       **write_json(self.folder/'manifest.json', self.manifest))
        write_json(self.root/'static.json', pointer)

    def publish(self):
        self.features(c.CATALOG, self.catalog)
        self.csv_artifact(self.index, self.rows, list(self.rows[0]))
        self.csv_artifact(self.link_path, self.links, list(self.links[0]))
        self.features(self.footprint, self.rows)
        self.features('inputs/catfim_2.geojson.gz', self.source_rows)
        self.json_artifact('raw/gauge_HEAC1.json.gz', self.gauge)
        self.publish_manifest()

    def test_coverage_separates_inventory_mapping_and_local_library(self):
        result = f.coverage(config=self.config)
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['provider_mapping_counts'], {'mapped': 1, 'unmapped': 1})
        first, second = result['records']
        self.assertEqual(first['aliases'], ['CATFIM-heac1', 'USGS-00123', 'NOAA-HEAC1'])
        self.assertEqual(first['attributes']['installation'], 'installed')
        self.assertEqual(first['library_integrity'], 'unchecked')
        self.assertEqual(second['attributes']['installation'], 'not_installed')
        self.assertEqual(second['attributes']['geography'], 'not_assessed')
        self.assertIn('Datum conversion failed', second['provider_report']['reason'])

    def test_region_and_source_selectors_are_explicit(self):
        self.assertEqual(f.coverage(region='state:NV', config=self.config)['total'], 1)
        self.assertEqual(f.coverage(region='huc8:00000001', config=self.config)['total'], 2)
        self.assertEqual(f.coverage(region='wfo:UNKNOWN', config=self.config)['status'], 'unknown_region')
        self.assertEqual(f.coverage(source='other-source', config=self.config)['status'], 'unsupported')
        with self.assertRaises(ValueError):
            f.coverage(region='North Coast', config=self.config)

    def test_exact_identity_preserves_zeroes_and_source_case(self):
        for station in ('CATFIM-heac1', 'USGS-00123', 'NOAA-HEAC1'):
            self.assertEqual(f.site(station, config=self.config)['records'][0]['scenario_eligibility'], 'eligible')
        for station in ('USGS-123', 'CATFIM-HEAC1', 'NOAA-heac1'):
            self.assertEqual(f.site(station, config=self.config)['status'], 'unknown')
        self.assertEqual(f.site('OTHER-00123', config=self.config)['status'], 'unsupported')

    def test_duplicate_catalog_identities_require_explicit_object_selection(self):
        self.catalog.append(dict(self.properties, oid=3, name='Different record'))
        self.publish()
        self.assertEqual(f.site('USGS-00123', config=self.config)['status'], 'ambiguous')
        result = f.site('USGS-00123', catalog_object_id='1', config=self.config)
        self.assertEqual(result['status'], 'ok')
        # A selector does not erase a conflicting gauge-to-catalog association.
        self.assertEqual(result['records'][0]['scenario_eligibility'], 'ineligible')

    def test_source_dates_are_not_retrieval_or_current_observation_dates(self):
        record = f.site('USGS-00123', config=self.config)['records'][0]
        self.assertIsNone(record['provider_report']['reported_at'])
        self.assertIn('2020', record['source_times']['nrldb_timestamp'])
        self.assertEqual(record['attributes']['predictive_validation'], 'not_assessed')

    def test_provider_mapped_does_not_install_a_library(self):
        self.catalog[1]['mapped'] = 'yes'
        self.publish()
        record = f.site('USGS-00055', config=self.config)['records'][0]
        self.assertEqual(record['attributes']['provider_mapping'], 'mapped')
        self.assertEqual(record['attributes']['installation'], 'not_installed')

    def test_exact_scenario_details_preserve_source_and_units(self):
        result = f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)
        self.assertEqual(result['status'], 'ok')
        record = result['records'][0]
        self.assertEqual(record['recorded_stage'], '21')
        self.assertEqual(record['evidence']['scenario']['units'], 'FT')
        self.assertEqual(record['reach_id'], '0001')
        self.assertEqual(record['network'], 'NHD-v2')
        self.assertEqual(record['evidence']['attributes']['coverage'], 'partial')
        self.assertIn('Hypothetical', record['qualifications'][0])
        self.assertEqual(record['footprint']['path'], self.footprint)
        self.assertNotIn('geometry', record)

    def test_exact_and_bracketed_stage_selection(self):
        exact = f.stage_scenarios('USGS-00123', '21.0', 'ft', config=self.config)
        self.assertEqual(exact['selection'], 'exact_stage')
        bracket = f.stage_scenarios('NOAA-HEAC1', 22, 'FT', config=self.config)
        self.assertEqual(bracket['status'], 'ok')
        self.assertFalse(bracket['interpolation'])
        self.assertEqual([r['bracket_role'] for r in bracket['records']], ['lower', 'upper'])
        self.assertEqual([r['recorded_stage'] for r in bracket['records']], ['21', '23'])

    def test_out_of_range_and_unsupported_units(self):
        for value, reason in ((20, 'below_library'), (24, 'above_library')):
            self.assertEqual(f.stage_scenarios('USGS-00123', value, 'FT', config=self.config)['reasons'], [reason])
        self.assertEqual(f.stage_scenarios('USGS-00123', 21, 'm', config=self.config)['status'], 'unsupported')
        with self.assertRaises(ValueError):
            f.stage_scenarios('USGS-00123', 21, 'cfs', config=self.config)

    def test_unknown_scenario_is_not_no_flood_risk(self):
        result = f.scenario(c.SOURCE, 'unknown', config=self.config)
        self.assertEqual(result['status'], 'unknown')
        self.assertIn('not current inundation', result['qualification'])
        self.assertIn('all-clear', result['qualification'])

    def test_duplicate_scenario_and_stage_are_not_arbitrarily_selected(self):
        self.rows.append(dict(self.rows[0]))
        self.publish()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ambiguous')
        self.assertEqual(f.stage_scenarios('USGS-00123', 21, 'FT', config=self.config)['status'], 'ambiguous')
        self.assertEqual(f.stage_scenarios('USGS-00123', 22, 'FT', config=self.config)['status'], 'ambiguous')

    def test_brackets_cannot_mix_model_versions(self):
        self.properties['model_version'] = None
        self.rows[1]['model_version'] = 'other'
        self.source_rows[1]['model_version'] = 'other'
        self.publish()
        result = f.stage_scenarios('USGS-00123', 22, 'FT', config=self.config)
        self.assertEqual(result['status'], 'ineligible')
        self.assertIn('incompatible_bracket_versions_or_references', result['reasons'])

    def test_missing_or_placeholder_scenario_datum_blocks_only_details(self):
        for value in (None, dict(datum='UNKNOWN', zero=79.98, units='ft', source_reference='ref')):
            self.source_rows[0]['vertical_reference'] = value
            self.publish()
            result = f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)
            self.assertEqual(result['status'], 'ineligible')
            self.assertNotIn('evidence', result['records'][0])
            self.assertTrue(result['records'][0]['reasons'])
            self.assertEqual(f.coverage(config=self.config)['total'], 2)

    def test_gauge_units_are_not_inferred(self):
        self.gauge['datums']['vertical']['value'][0].pop('units')
        self.publish()
        result = f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)
        self.assertEqual(result['status'], 'ineligible')
        self.assertIn('vertical_reference:missing', result['records'][0]['reasons'])

    def test_incompatible_datum_and_gauge_identity(self):
        self.gauge['datums']['vertical']['value'][0]['abbrev'] = 'NGVD29'
        self.publish()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')
        self.gauge['usgsId'] = '123'
        self.publish()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')

    def test_missing_versions_and_source_identity_mismatch(self):
        self.rows[0]['model_version'] = ''
        self.publish()
        self.assertNotEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ok')
        self.rows[0]['model_version'] = '4.9'
        self.source_rows[0]['ahps_lid'] = 'another'
        self.publish()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')

    def test_failed_bracket_does_not_return_one_eligible_endpoint(self):
        self.source_rows[1].pop('vertical_reference')
        self.publish()
        result = f.stage_scenarios('USGS-00123', 22, 'FT', config=self.config)
        self.assertEqual(result['status'], 'ineligible')
        self.assertTrue(all('evidence' not in r for r in result['records']))

    def test_unreviewed_or_conflicting_links_do_not_establish_eligibility(self):
        self.link['status'] = 'nearest'
        self.publish()
        result = f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)
        self.assertIn('relationship:unsupported', result['records'][0]['reasons'])
        self.links.append(dict(self.link, reach_id='0002'))
        self.publish()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')

    def test_cross_border_applicability_requires_explicit_drainage_review(self):
        self.properties['states'] = 'CA,NV'
        self.publish()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')
        self.link['drainage_review'] = 'reviewed-CA-drainage'
        self.publish()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ok')

    def test_event_records_are_not_static_references(self):
        self.rows[0]['event_valid_time'] = '2026-11-07T20:00:00Z'
        self.publish()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')

    def test_missing_corrupt_catalog_and_malformed_generation(self):
        (self.folder/c.CATALOG).unlink()
        self.assertEqual(f.coverage(config=self.config)['status'], 'unavailable')
        self.publish()
        (self.folder/c.CATALOG).write_bytes(b'corrupt')
        self.assertEqual(f.coverage(config=self.config)['status'], 'unavailable')
        self.manifest['complete'] = False
        self.publish_manifest()
        self.assertEqual(f.coverage(config=self.config)['status'], 'unavailable')

    def test_corrupt_scenario_preserves_discovery(self):
        (self.folder/self.footprint).write_bytes(b'corrupt')
        self.assertEqual(f.coverage(config=self.config)['total'], 2)
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')

    def test_missing_footprint_is_not_reported_as_installed(self):
        (self.folder/self.footprint).unlink()
        record = f.site('USGS-00123', config=self.config)['records'][0]
        self.assertEqual(record['attributes']['installation'], 'unavailable')
        self.assertEqual(record['scenario_eligibility'], 'ineligible')

    def test_known_unreviewed_noaa_identity_is_not_unknown(self):
        self.link['status'] = 'nearest'
        self.publish()
        result = f.site('NOAA-HEAC1', config=self.config)
        self.assertEqual(result['status'], 'ok')
        self.assertNotIn('NOAA-HEAC1', result['records'][0]['aliases'])
        self.assertEqual(result['records'][0]['attributes']['relationship'], 'unsupported')
        self.assertEqual(f.stage_scenarios('NOAA-HEAC1', 21, 'FT', config=self.config)['status'], 'ineligible')

    def test_invalid_gauge_metadata_retains_site_discovery(self):
        self.gauge['datums'] = None
        self.publish()
        result = f.site('USGS-00123', config=self.config)
        self.assertEqual(result['records'][0]['scenario_eligibility'], 'ineligible')
        self.assertEqual(result['records'][0]['id'], 'CATFIM-heac1')

    def test_corrupt_other_library_requires_explicit_scope(self):
        other = 'regions/other/relationships/inundation_scenarios.csv'
        self.artifact(other, b'invalid schema\n')
        self.publish_manifest()
        result = f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)
        self.assertEqual(result['status'], 'unavailable')
        result = f.scenario(c.SOURCE, 'HEAC1_s21', library_region=self.region, config=self.config)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['records'][0]['eligible'])
        self.assertEqual(f.coverage(config=self.config)['total'], 2)

    def test_library_region_disambiguates_duplicate_scenario_ids(self):
        self.csv_artifact('regions/other/relationships/inundation_scenarios.csv', self.rows, list(self.rows[0]))
        self.csv_artifact('regions/other/relationships/gauge_reach_links.csv', self.links, list(self.links[0]))
        self.features('regions/other/inundation_scenarios.geojson.gz', self.rows)
        self.publish_manifest()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ambiguous')
        result = f.scenario(c.SOURCE, 'HEAC1_s21', library_region='other', config=self.config)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['records'][0]['library_region'], 'other')
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', library_region='missing', config=self.config)['status'], 'unknown_region')

    def test_unmapped_installed_library_is_conflicting(self):
        self.properties['mapped'] = 'no'
        self.publish()
        result = f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)
        self.assertIn('provider_mapping:conflicting', result['records'][0]['reasons'])

    def test_footprint_identity_and_geometry_must_exist(self):
        self.features(self.footprint, [dict(self.rows[0], stage='25'), self.rows[1]])
        self.publish_manifest()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')
        self.json_artifact(self.footprint, dict(type='FeatureCollection', features=[dict(properties=self.rows[0])]))
        self.publish_manifest()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')

    def test_basin_replacement_after_selection_discards_details(self):
        original = c.Catalog.evaluate

        def replace_dependency(reader, row):
            result = original(reader, row)
            write_json(self.base/'basin_plans/sources.json', {})
            return result

        with patch.object(c.Catalog, 'evaluate', replace_dependency):
            result = f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['records'], [])

    def test_malformed_relationships_do_not_hide_catalog(self):
        self.artifact(self.index, b'bad,fields\na,b\n')
        self.publish_manifest()
        result = f.coverage(config=self.config)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['records'][0]['attributes']['installation'], 'unknown')

    def test_missing_link_fields_preserve_discovery_and_block_details(self):
        self.link['reach_id'] = ''
        self.publish()
        result = f.site('USGS-00123', config=self.config)
        self.assertEqual(result['records'][0]['attributes']['relationship'], 'unknown')
        self.assertEqual(result['records'][0]['scenario_eligibility'], 'ineligible')

    def test_catalog_source_version_conflict_is_not_ignored(self):
        self.properties['fim_version'] = 'older'
        self.publish()
        result = f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)
        self.assertIn('catalog_source_versions:conflicting', result['records'][0]['reasons'])

    def test_missing_object_id_cannot_be_selected_as_literal_none(self):
        self.properties.pop('oid')
        self.publish()
        self.assertEqual(f.site('USGS-00123', catalog_object_id='None', config=self.config)['status'], 'unknown')

    def test_unknown_provider_mapping_is_preserved(self):
        self.properties['mapped'] = 'unrecognized'
        self.publish()
        result = f.coverage(config=self.config)
        self.assertEqual(result['provider_mapping_unknown'], 1)
        self.assertEqual(result['records'][0]['provider_report']['recorded_mapping'], 'unrecognized')

    def test_missing_or_incompatible_basin_preserves_catalog(self):
        self.manifest['basin_source']['snapshot_id'] = 'different'
        self.publish_manifest()
        self.assertEqual(f.coverage(config=self.config)['total'], 2)
        result = f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)
        self.assertIn('compatibility:incompatible', result['records'][0]['reasons'])
        (self.base/'basin_plans/sources.json').unlink()
        self.assertEqual(f.coverage(config=self.config)['total'], 2)
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')

    def test_custom_paths_and_explicit_removal(self):
        managed = self.base/'managed'
        write_json(managed/'datasets.json', dict(schema=1, datasets={'flood_impacts': {'active': None}}))
        with patch.dict(os.environ, MESHCORE_DATA_DIR=str(managed)):
            self.assertEqual(f.coverage(config=self.config)['total'], 2)
            result = f.coverage(config=water_settings.validate({}))
            self.assertEqual(result['reasons'], ['managed_removal'])

    def test_pointer_replacement_discards_all_results(self):
        original = c.Catalog.site_record

        def replace_pointer(reader, properties):
            result = original(reader, properties)
            write_json(self.root/'static.json', {})
            return result

        with patch.object(c.Catalog, 'site_record', replace_pointer):
            result = f.coverage(config=self.config)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['records'], [])
        self.assertIn('generation_changed', result['reasons'])

    def test_malformed_and_excessive_arguments(self):
        for value in (float('nan'), float('inf'), True, '21ft', '1e3', '1'*33):
            with self.subTest(value=value), self.assertRaises(ValueError):
                f.stage_scenarios('USGS-00123', value, 'FT', config=self.config)
        for limit in (0, 21, True):
            with self.assertRaises(ValueError):
                f.coverage(limit=limit, config=self.config)
        with self.assertRaises(ValueError):
            f.site('HEAC1', config=self.config)

    def test_record_and_serialized_limits_disclose_omissions(self):
        result = f.coverage(limit=1, config=self.config)
        self.assertEqual((result['status'], result['total'], result['omitted']), ('partial', 2, 1))
        self.properties['name'] = '\u6e29'*1000
        self.publish()
        with patch.object(f, 'MAX_RESULT_BYTES', 1000):
            result = f.coverage(config=self.config)
        self.assertEqual(result['status'], 'limit')
        self.assertEqual(result['records'], [])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 1000)

    def test_execution_and_decompression_limits(self):
        with patch.object(d, 'VERIFY_SECONDS', -1):
            self.assertEqual(f.coverage(config=self.config)['status'], 'limit')
        with patch.object(c, 'MAX_FEATURE_BYTES', 10):
            self.assertEqual(f.coverage(config=self.config)['status'], 'limit')

    def test_truncated_compressed_metadata_is_reported(self):
        self.artifact(c.CATALOG, gzip.compress(b'{"type":"FeatureCollection","features":[]}')[:-5])
        self.publish_manifest()
        self.assertEqual(f.coverage(config=self.config)['status'], 'unavailable')

    def test_internal_calls_are_read_only_and_do_not_require_meshcore_context(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.base.rglob('*') if p.is_file()}
        with patch.dict(os.environ, {}, clear=True), patch('socket.create_connection', side_effect=AssertionError('network')):
            self.assertEqual(f.stage_scenarios('USGS-00123', 22, 'FT', config=self.config)['status'], 'ok')
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.base.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_stdlib_only_import_and_no_registered_entry_point(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-S', '-c',
                                 'from scripts import flood_reference; assert callable(flood_reference.coverage)'],
                                cwd=root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = json.loads((root/'config.json').read_bytes())['responder']['commands']
        self.assertFalse(any('floodref' in name or spec['script'].endswith(('flood_reference.py', 'flood_catalog.py'))
                             for name, spec in commands.items()))

    def add_other_gauge(self):
        """Record a second NOAA identity on the same USGS association without inferring equivalence."""
        self.links.append(dict(self.link, gauge_lid='OTHER1'))
        self.rows.append(dict(self.rows[0], scenario_id='OTHER1_s30', gauge_lid='OTHER1',
                              stage='30', source_object_ids='30'))
        self.source_rows.append(dict(self.source_rows[0], oid=30, interval_stage=30))
        self.publish()
        self.json_artifact('raw/gauge_OTHER1.json.gz', dict(self.gauge, lid='OTHER1'))
        self.publish_manifest()

    def test_explicit_noaa_selection_cannot_substitute_another_gauge(self):
        self.add_other_gauge()
        result = f.stage_scenarios('NOAA-HEAC1', 30, 'FT', config=self.config)
        self.assertEqual(result['status'], 'out_of_range')
        record = f.site('NOAA-HEAC1', config=self.config)['records'][0]
        self.assertEqual(record['scenario_count'], 2)
        self.assertTrue(all(r['id'].startswith('HEAC1_') for r in record['scenario_availability']))

    def test_usgs_selection_requires_disambiguation_before_stage_matching(self):
        self.add_other_gauge()
        result = f.stage_scenarios('USGS-00123', 21, 'FT', config=self.config)
        self.assertEqual(result['status'], 'ambiguous')
        self.assertIn('multiple_gauge_associations', result['reasons'])

    def test_reused_scenario_identity_blocks_stage_access(self):
        self.rows.append(dict(self.rows[1], scenario_id='HEAC1_s21'))
        # The index conflicts even if the selected footprint/source still matches.
        self.csv_artifact(self.index, self.rows, list(self.rows[0]))
        self.publish_manifest()
        result = f.stage_scenarios('USGS-00123', 21, 'FT', config=self.config)
        self.assertEqual(result['status'], 'ineligible')
        self.assertIn('scenario_identity:ambiguous', result['records'][0]['reasons'])

    def test_arbitrary_numeric_source_field_is_not_a_stage(self):
        self.rows[0]['source_stage_field'] = 'oid'
        self.source_rows[0]['interval_stage'] = 99
        self.publish()
        self.assertEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ineligible')

    def test_duplicate_csv_headers_cannot_override_identity(self):
        raw = (self.folder/self.link_path).read_text(encoding='utf-8').splitlines()
        raw[0] += ',usgs_id'
        raw[1] += ',00123'
        self.artifact(self.link_path, ('\n'.join(raw)+'\n').encode())
        self.publish_manifest()
        self.assertEqual(f.coverage(config=self.config)['status'], 'partial')
        self.assertNotEqual(f.scenario(c.SOURCE, 'HEAC1_s21', config=self.config)['status'], 'ok')

    def test_csv_parser_errors_preserve_catalog_discovery(self):
        self.artifact(self.link_path, b','.join(k.encode() for k in c.LINK_FIELDS)+b'\n'+b'x'*200000+b'\n')
        self.publish_manifest()
        self.assertEqual(f.coverage(config=self.config)['total'], 2)

    def test_failed_links_cannot_prove_a_noaa_identity_is_unknown(self):
        (self.folder/self.link_path).write_bytes(b'corrupt')
        result = f.site('NOAA-HEAC1', config=self.config)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(f.site('CATFIM-heac1', config=self.config)['records'][0]['id'], 'CATFIM-heac1')

    def test_undeclared_footprint_is_not_a_managed_installed_library(self):
        self.manifest['files'].pop(self.footprint)
        self.publish_manifest()
        record = f.coverage(config=self.config)['records'][0]
        self.assertEqual(record['attributes']['installation'], 'unavailable')

    def test_discovery_rechecks_library_presence_before_return(self):
        original = c.Catalog.site_record

        def remove_library(reader, properties):
            result = original(reader, properties)
            (self.folder/self.footprint).unlink(missing_ok=True)
            return result

        with patch.object(c.Catalog, 'site_record', remove_library):
            result = f.coverage(config=self.config)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['records'], [])

    def test_incompatible_bracket_preserves_followup_identities(self):
        self.properties['model_version'] = None
        self.rows[1]['model_version'] = 'other'
        self.source_rows[1]['model_version'] = 'other'
        self.publish()
        result = f.stage_scenarios('USGS-00123', 22, 'FT', config=self.config)
        self.assertEqual(result['status'], 'ineligible')
        self.assertEqual([r['id'] for r in result['records']], ['HEAC1_s21', 'HEAC1_s23'])
        self.assertTrue(all('evidence' not in r for r in result['records']))

    def test_library_selection_precedes_noaa_identity_resolution(self):
        other_link = dict(self.link, usgs_id='00055')
        self.csv_artifact('regions/other/relationships/inundation_scenarios.csv', self.rows, list(self.rows[0]))
        self.csv_artifact('regions/other/relationships/gauge_reach_links.csv', [other_link], list(other_link))
        self.publish_manifest()
        self.assertEqual(f.stage_scenarios('NOAA-HEAC1', 21, 'FT', config=self.config)['status'], 'ambiguous')
        scoped = f.stage_scenarios('NOAA-HEAC1', 21, 'FT', library_region=self.region, config=self.config)
        self.assertEqual(scoped['status'], 'ok')
        self.assertEqual(scoped['records'][0]['library_region'], self.region)

    def test_invalid_gauge_link_keeps_installation_unknown(self):
        self.link['gauge_lid'] = ''
        self.publish()
        result = f.site('USGS-00123', config=self.config)
        self.assertEqual(result['records'][0]['attributes']['relationship'], 'unknown')
        self.assertEqual(result['records'][0]['attributes']['installation'], 'unknown')

    def test_invalid_deflate_stream_is_reported(self):
        raw = gzip.compress(b'{"type":"FeatureCollection","features":[]}')
        self.artifact(c.CATALOG, raw[:10]+b'\x07'+raw[11:])
        self.publish_manifest()
        self.assertEqual(f.coverage(config=self.config)['status'], 'unavailable')

    def test_discovery_rechecks_an_initially_missing_library(self):
        raw = (self.folder/self.footprint).read_bytes()
        (self.folder/self.footprint).unlink()
        original = c.Catalog.site_record

        def restore_library(reader, properties):
            result = original(reader, properties)
            (self.folder/self.footprint).write_bytes(raw)
            return result

        with patch.object(c.Catalog, 'site_record', restore_library):
            result = f.coverage(config=self.config)
        self.assertEqual(result['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
