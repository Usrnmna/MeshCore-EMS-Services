"""Synthetic requirement/review fixtures; no real-basin suitability is established."""
import copy
import gzip
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import flood_readiness as readiness, flood_readiness_data as data, water_settings


def digest(raw):
    """Describe exact fixture bytes without timestamps or inferred source identity."""
    return dict(sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw))


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.config = water_settings.validate({'data_directory': str(self.base)})
        self.root = self.base / 'flood_readiness'
        self.directory = self.root / 'readiness/g1'
        self.directory.mkdir(parents=True)
        self.scope = dict(kind='basin', source='CalWater', id='0001', generation='s1', level='PW')
        self.header = dict(id='fixture-use-01', scope=self.scope, intended_use='synthetic-input-review', path='profile.json')
        self.manifest = dict(schema_version=1, kind='environmental_input_readiness', generation='g1',
                             complete=True, files={}, profiles=[self.header])
        self.source = self.base / 'synthetic_inputs'
        self.source.mkdir()
        source_dir = self.source / 's1'
        source_dir.mkdir()
        raw = b'{"fixture_only":true,"numeric_samples":[1,2,3]}'
        (source_dir / 'values.json').write_bytes(raw)
        source_manifest = dict(schema_version=1, generation='s1', complete=True,
                               files={'values.json': digest(raw)})
        manifest_raw = json.dumps(source_manifest).encode()
        (source_dir / 'manifest.json').write_bytes(manifest_raw)
        pointer_raw = json.dumps(dict(manifest_path='s1/manifest.json', **digest(manifest_raw))).encode()
        (self.source / 'current.json').write_bytes(pointer_raw)
        self.dependency = dict(dataset='synthetic_inputs', pointer='current.json', pin=digest(pointer_raw),
                               generation='s1', artifacts=[dict(path='s1/values.json', **digest(raw))])
        self.body = dict(self.header, review='profile-review.json', engine=None, assumptions=[],
                         requirements=[], inputs=[], outstanding=['Model-engine review remains separate.'])
        association = dict(id='scope-to-domain', relation='reviewed_scope_membership',
                           **{'from': self.scope}, to=dict(kind='model_domain', source='fixture', id='D001', generation='s1'),
                           review='association-review.json')
        self.body['domain'] = dict(id='D001', review='domain-review.json', associations=[association],
                                   identity=association['to'],
                                   dependencies=[self.dependency],
                                   **{key: dict(state='reviewed', justification='Synthetic complete review only.')
                                      for key in readiness.DOMAIN_CHECKS})
        for category, fields in readiness.CATEGORIES.items():
            facts = {key: 'fixture-qualified' for key in readiness.COMMON + fields}
            facts.update(variable=category + '_fixture_variable', units='fixture_unit',
                         horizontal_crs='EPSG:4326', spatial_coverage=['D001', 'cross-border-001'],
                         quality_flags=['provisional'], uncertainty=dict(value=1.0, unit='fixture_unit'),
                         source_vintage='2020-01-01')
            if 'vertical_datum' in fields:
                facts['vertical_datum'] = 'NAVD88'
            if 'gauge_zero' in fields:
                facts['gauge_zero'] = dict(station='USGS-0001', value=100, unit='m', datum='NAVD88')
            if category == 'validation':
                facts['independence'] = True
            criteria = {key: dict(op='eq', value=value) for key, value in facts.items()}
            criteria['uncertainty'] = dict(op='max', value=2, unit='fixture_unit')
            item = dict(id='0001-' + category, source='fixture', generation='s1', kind=readiness.INPUT_KINDS[category][0],
                        facts=facts, qualifications=['Synthetic only; not real-world evidence.'],
                        source_date='2020-01-01', acquired_at='2026-01-01T00:00:00Z',
                        review=category + '-input-review.json', preparation='verified', dependencies=[self.dependency])
            req = dict(id=category, category=category, critical=True, criteria=criteria, time_mode='static',
                       input={key: item[key] for key in ('source', 'id', 'generation')}, review=category + '-review.json')
            if category in ('soil_moisture', 'forcing', 'boundaries', 'validation'):
                req['time_mode'] = 'event'
                period = dict(start='2020-01-01T00:00:00Z', end='2020-01-02T00:00:00Z')
                facts['time_coverage'] = period
                criteria['time_coverage'] = dict(op='covers', value=period)
            self.body['inputs'].append(item)
            self.body['requirements'].append(req)
        self.publish()

    def artifact(self, name, value):
        """Write only isolated synthetic evidence and checksum declarations."""
        raw = json.dumps(value).encode()
        if name.endswith('.gz'):
            raw = gzip.compress(raw, mtime=0)
        (self.directory / name).write_bytes(raw)
        self.manifest['files'][name] = digest(raw)

    def review(self, path, subject, record=None):
        self.artifact(path, dict(status='reviewed', subject=subject, justification='Synthetic fixture review.',
                                record_sha256=data.review_digest(record) if record is not None else None))

    def pin(self):
        raw = json.dumps(self.manifest).encode()
        (self.directory / 'manifest.json').write_bytes(raw)
        (self.root / 'readiness.json').write_text(json.dumps(dict(manifest_path='readiness/g1/manifest.json', **digest(raw))), encoding='utf-8')

    def publish(self):
        """Create explicit review fixtures; no actual reviewer or source approval is implied."""
        self.review('profile-review.json', readiness._subject(self.header), self.body)
        domain = self.body['domain']
        self.review('domain-review.json', readiness._subject(self.header, domain=domain['id']), domain)
        for association in domain['associations']:
            self.review(association['review'], readiness._subject(self.header, association=association))
        for req in self.body['requirements']:
            if req.get('review'):
                self.review(req['review'], readiness._subject(self.header, requirement=req['id']), req)
            for item in self.body['inputs']:
                if req.get('input') == {key: item[key] for key in ('source', 'id', 'generation')} and item.get('review'):
                    self.review(item['review'], readiness._subject(self.header, requirement=req['id'], input=req['input']), item)
        self.artifact('profile.json', self.body)
        self.pin()

    def assess(self, **kwargs):
        return readiness.assess(self.scope, self.header['intended_use'], config=self.config, now=1767225600, **kwargs)

    def row(self, category='terrain'):
        result = self.assess()
        self.assertIn(result['status'], ('blocked', 'ready_for_stated_requirements'), result)
        return next(r for r in result['records'] if r['category'] == category)

    def item(self, category):
        return next(i for i in self.body['inputs'] if i['id'] == '0001-' + category)

    def req(self, category):
        return next(r for r in self.body['requirements'] if r['category'] == category)

    def test_complete_synthetic_requirements_are_not_model_approval(self):
        result = self.assess()
        self.assertEqual(result['status'], 'ready_for_stated_requirements', result)
        self.assertTrue(result['input_ready'])
        self.assertFalse(result['engine_ready'])
        self.assertEqual(result['predictive_validation'], 'not_assessed')
        self.assertEqual(set(r['category'] for r in result['records']), set(readiness.CATEGORIES))

    def test_bad_arguments_before_io(self):
        with patch.object(data, 'Snapshot', side_effect=AssertionError('IO')):
            for scope in ({}, dict(self.scope, id=1), dict(self.scope, level='Water Board Region'), dict(self.scope, id=' 001')):
                with self.assertRaises(ValueError):
                    readiness.assess(scope, 'use')
            for value in (0, True, 21, 1.5):
                with self.assertRaises(ValueError):
                    readiness.discover(limit=value)
            with self.assertRaises(ValueError):
                readiness.assess(self.scope, '')
            with self.assertRaises(ValueError):
                readiness.assess(self.scope, 'use', now=float('nan'))

    def test_review_cannot_override_reference_only_source_policy(self):
        manifest_path = self.source / 's1/manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        manifest['allowed_uses'] = ['boundary_reference']
        raw = json.dumps(manifest).encode()
        manifest_path.write_bytes(raw)
        pointer = json.dumps(dict(manifest_path='s1/manifest.json', **digest(raw))).encode()
        (self.source / 'current.json').write_bytes(pointer)
        self.dependency['pin'] = digest(pointer)
        self.publish()
        result = self.assess()
        self.assertFalse(result['input_ready'], result)
        self.assertFalse(result['engine_ready'], result)
        self.assertIn('reference_only_source_forbidden', json.dumps(result))

    def test_review_cannot_override_reference_directory(self):
        restricted = self.base / '.reference-only' / 'synthetic_inputs'
        restricted.parent.mkdir()
        shutil.move(str(self.source), str(restricted))
        registry = {'schema': 1, 'datasets': {'synthetic_inputs': {
            'active': {'path': '.reference-only/synthetic_inputs'}}}}
        (self.base / 'datasets.json').write_text(json.dumps(registry), encoding='utf-8')
        with patch.object(readiness.dataset_paths, 'data_root', return_value=self.base):
            result = self.assess()
        self.assertFalse(result['input_ready'], result)
        self.assertFalse(result['engine_ready'], result)
        self.assertIn('reference_only_source_forbidden', json.dumps(result))

    def test_review_cannot_override_reference_kinds(self):
        for kind in ('nlcd_fractional_impervious', 'nlcd_land_cover_confidence',
                     'usgs_elevation_reference', 'geoid18_reference', 'ssurgo_reference', 'nhdplus_reference'):
            with self.subTest(kind=kind):
                manifest_path = self.source / 's1/manifest.json'
                manifest = json.loads(manifest_path.read_bytes())
                manifest['kind'] = kind
                raw = json.dumps(manifest).encode()
                manifest_path.write_bytes(raw)
                pointer = json.dumps(dict(manifest_path='s1/manifest.json', **digest(raw))).encode()
                (self.source / 'current.json').write_bytes(pointer)
                self.dependency['pin'] = digest(pointer)
                self.publish()
                result = self.assess()
                self.assertFalse(result['input_ready'], result)
                self.assertFalse(result['engine_ready'], result)
                self.assertIn('reference_only_source_forbidden', json.dumps(result))

    def test_exact_scope_zeroes_source_generation_level(self):
        for key, value in (('id', '1'), ('source', 'Other'), ('generation', 's2'), ('level', 'SPW')):
            with self.subTest(key=key):
                result = readiness.assess(dict(self.scope, **{key: value}), self.header['intended_use'], config=self.config)
                self.assertEqual(result['status'], 'unknown')

    def test_ambiguous_profiles_require_explicit_selection(self):
        self.manifest['profiles'].append(dict(self.header, id='other'))
        self.pin()
        self.assertEqual(self.assess()['status'], 'ambiguous')
        self.assertTrue(self.assess(profile=self.header['id'])['input_ready'])

    def test_duplicate_exact_profile_is_ambiguous(self):
        self.manifest['profiles'].append(self.header)
        self.pin()
        self.assertEqual(self.assess(profile=self.header['id'])['status'], 'ambiguous')

    def test_input_source_collisions_are_not_merged(self):
        self.body['inputs'].append(dict(self.item('terrain'), source='another'))
        self.publish()
        self.assertEqual(self.row()['state'], 'suitable')
        self.body['inputs'].append(self.item('terrain'))
        self.publish()
        self.assertEqual(self.row()['state'], 'incompatible')

    def test_missing_category_and_input_block_readiness(self):
        self.body['requirements'].pop()
        self.body['inputs'].pop(0)
        self.publish()
        result = self.assess()
        self.assertFalse(result['input_ready'])
        self.assertIn('category_unresolved:validation', result['blockers'])
        self.assertEqual(self.row()['state'], 'not_installed')

    def test_not_applicable_requires_recorded_justification_and_review(self):
        req = self.req('soil_moisture')
        req.update(not_applicable=True)
        self.publish()
        self.assertEqual(self.row('soil_moisture')['state'], 'unknown')
        req['justification'] = 'Synthetic intended use excludes this input.'
        self.publish()
        self.assertEqual(self.row('soil_moisture')['state'], 'not_applicable')
        req['review'] = None
        self.publish()
        self.assertEqual(self.row('soil_moisture')['state'], 'unreviewed')

    def test_unknown_and_missing_thresholds_cannot_be_ready(self):
        self.req('terrain')['criteria'].pop('resolution')
        self.publish()
        self.assertEqual(self.row()['state'], 'unknown')
        self.req('terrain')['criteria']['resolution'] = dict(op='max', value=None, unit='m')
        self.publish()
        self.assertNotEqual(self.row()['state'], 'suitable')

    def test_compatibility_fields_are_independent(self):
        for field in ('horizontal_crs', 'vertical_datum', 'units', 'resolution', 'spatial_coverage', 'accuracy'):
            with self.subTest(field=field):
                item = self.item('terrain')
                old = item['facts'][field]
                item['facts'][field] = 'different'
                self.publish()
                self.assertEqual(self.row()['state'], 'incompatible')
                item['facts'][field] = old

    def test_units_no_conversion_and_numeric_precision_preserved(self):
        item = self.item('terrain')
        item['facts']['resolution'] = dict(value=0.123456789, unit='ft')
        self.req('terrain')['criteria']['resolution'] = dict(op='max', value=1, unit='m')
        self.publish()
        row = self.row()
        self.assertEqual(row['state'], 'incompatible')
        self.assertEqual(row['facts']['resolution']['value'], 0.123456789)

    def test_gauge_zero_cannot_be_replaced_by_dem_elevation(self):
        self.item('boundaries')['facts']['gauge_zero'] = None
        self.publish()
        self.assertEqual(self.row('boundaries')['state'], 'incomplete')

    def test_unknown_uncertainty_remains_unknown(self):
        self.item('terrain')['facts']['uncertainty'] = 'unknown'
        self.publish()
        row = self.row()
        self.assertEqual(row['state'], 'incomplete')
        self.assertEqual(row['facts']['uncertainty'], 'unknown')

    def test_stale_undated_future_current_observations(self):
        req, item = self.req('soil_moisture'), self.item('soil_moisture')
        req.update(time_mode='current', max_age_seconds=3600)
        period = dict(start='2025-12-31T00:00:00Z', end='2026-01-01T00:00:00Z')
        req['criteria']['time_coverage'] = dict(op='covers', value=period)
        item['facts']['time_coverage'] = period
        for value, expected in ((None, 'unavailable'), ('2025-12-01T00:00:00Z', 'stale'),
                                ('2027-01-01T00:00:00Z', 'invalid'), ('2025-12-31T23:59:00Z', 'fresh')):
            item['observed_at'] = value
            self.publish()
            row = self.row('soil_moisture')
            self.assertEqual(row['freshness'], expected)
            self.assertEqual(row['state'] == 'suitable', expected == 'fresh')

    def test_freshness_is_recomputed_and_assessment_reproducible(self):
        self.test_stale_undated_future_current_observations()
        first = self.assess()
        self.assertEqual(first, self.assess())
        later = readiness.assess(self.scope, self.header['intended_use'], config=self.config, now=1767312000)
        row = next(r for r in later['records'] if r['category'] == 'soil_moisture')
        self.assertEqual(row['freshness'], 'stale')

    def test_static_vintage_not_live_freshness(self):
        self.assertEqual(self.row()['freshness'], 'not_applicable_static')
        self.assertEqual(self.row()['source_date'], '2020-01-01')

    def test_event_inputs_cannot_use_static_vintage_instead_of_time_coverage(self):
        for category in ('soil_moisture', 'forcing', 'boundaries', 'validation'):
            with self.subTest(category=category):
                self.req(category)['time_mode'] = 'static'
                self.publish()
                self.assertEqual(self.row(category)['state'], 'unknown')
                self.req(category)['time_mode'] = 'event'
        self.req('boundaries')['criteria']['time_coverage'] = dict(op='not_applicable', justification='Cannot omit event coverage.')
        self.publish()
        self.assertEqual(self.row('boundaries')['state'], 'incomplete')

    def test_event_hydrograph_time_coverage_and_alignment(self):
        req, item = self.req('boundaries'), self.item('boundaries')
        req['time_mode'] = 'event'
        req['criteria']['time_coverage'] = dict(op='covers', value=dict(start='2020-01-01T00:00:00Z', end='2020-01-02T00:00:00Z'))
        item['facts']['time_coverage'] = dict(start='2020-01-01T01:00:00Z', end='2020-01-02T00:00:00Z')
        self.publish()
        self.assertEqual(self.row('boundaries')['state'], 'incompatible')

    def test_quality_flags_preserved_and_reviewed(self):
        self.item('soil_moisture')['facts']['quality_flags'] = ['provisional', 'estimated']
        self.publish()
        row = self.row('soil_moisture')
        self.assertEqual(row['state'], 'incompatible')
        self.assertEqual(row['facts']['quality_flags'], ['provisional', 'estimated'])

    def test_every_unsupported_substitution(self):
        for kind in readiness.UNSUPPORTED:
            with self.subTest(kind=kind):
                self.item('terrain')['kind'] = kind
                self.publish()
                self.assertEqual(self.row()['reasons'], ['unsupported_substitution'])

    def test_soil_moisture_cannot_supply_hydraulic_properties(self):
        self.item('soil_properties')['kind'] = 'soil_moisture_observations'
        self.publish()
        self.assertEqual(self.row('soil_properties')['state'], 'incompatible')

    def test_required_process_evidence_missing(self):
        for category, field in (('soil_moisture', 'soil_depth'), ('soil_moisture', 'representativeness'),
                ('soil_properties', 'conductivity'), ('soil_properties', 'layering'), ('soil_properties', 'storage'),
                ('boundaries', 'hydrograph_completeness'), ('boundaries', 'downstream_conditions'),
                ('boundaries', 'tidal_backwater'), ('structures', 'operations'),
                ('structures', 'effective_period'), ('validation', 'independence')):
            with self.subTest(category=category, field=field):
                item = self.item(category)
                original = item['facts'].pop(field)
                self.publish()
                self.assertEqual(self.row(category)['state'], 'incomplete')
                item['facts'][field] = original

    def test_domain_checks_include_cross_border_and_double_counting(self):
        for check in readiness.DOMAIN_CHECKS:
            with self.subTest(check=check):
                original = self.body['domain'].pop(check)
                self.publish()
                self.assertIn('domain_unresolved:' + check, self.assess()['blockers'])
                self.body['domain'][check] = original

    def test_unreviewed_assumptions_and_associations_block(self):
        self.body['assumptions'] = [dict(id='operation-assumption', value='fixture only', review=None)]
        self.body['domain']['associations'][0]['to']['id'] = 'D-other'
        self.publish()
        self.review('association-review.json', dict(subject='wrong'))
        self.pin()
        result = self.assess()
        self.assertIn('assumption_unreviewed:operation-assumption', result['blockers'])
        self.assertIn('domain_association_unreviewed:scope-to-domain', result['blockers'])

    def test_preparation_is_outstanding_not_automatically_performed(self):
        self.item('terrain')['preparation'] = 'requires_datum_transform'
        self.publish()
        self.assertEqual(self.row()['reasons'], ['preparation_outstanding'])

    def test_missing_profile_collection_returns_each_unknown_category(self):
        (self.root / 'readiness.json').unlink()
        result = self.assess()
        self.assertEqual(result['status'], 'not_installed')
        self.assertEqual(len(result['records']), 8)

    def test_managed_removal_disallows_fallback(self):
        (self.base / 'datasets.json').write_text(json.dumps(dict(schema=1, datasets={'flood_readiness': dict(active=None)})))
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.base)}):
            self.assertEqual(self.assess()['status'], 'removed')

    def test_removed_input_source_does_not_become_missing_profile(self):
        (self.base / 'datasets.json').write_text(json.dumps(dict(schema=1, datasets={'synthetic_inputs': dict(active=None)})))
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.base)}):
            self.assertEqual(self.assess()['status'], 'removed')

    def test_integrity_failure_never_ready(self):
        (self.source / 's1/values.json').write_bytes(b'corrupt')
        result = self.assess()
        self.assertFalse(result['input_ready'])
        self.assertEqual(result['reasons'], ['integrity_failed'])

    def test_incompatible_generation(self):
        self.dependency['generation'] = 's2'
        self.publish()
        self.assertEqual(self.assess()['status'], 'incompatible')

    def test_custom_path_and_service_environment(self):
        direct = self.assess()
        with patch.dict(os.environ, {'MESHCORE_WATER_SETTINGS': json.dumps(self.config)}):
            service = readiness.assess(self.scope, self.header['intended_use'], now=1767225600)
        self.assertEqual(direct, service)

    def test_mutating_consumed_file_or_pointer_invalidates_result(self):
        original = data.Snapshot.finish
        for path in (self.root / 'readiness.json', self.source / 'current.json', self.source / 's1/values.json'):
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                def mutate(reader):
                    path.write_bytes(raw + b' ')
                    original(reader)
                with patch.object(data.Snapshot, 'finish', mutate):
                    result = self.assess()
                self.assertEqual(result['reasons'], ['generation_changed'])
                path.write_bytes(raw)

    def test_discovery_is_bounded_and_not_a_readiness_claim(self):
        result = readiness.discover(limit=1, config=self.config)
        self.assertTrue(result['partial'])
        self.assertFalse(result['input_ready'])
        self.assertEqual(result['profiles'][0]['scope'], self.scope)

    def test_read_only(self):
        def files():
            return {str(p): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        before = files()
        self.assess()
        readiness.discover(config=self.config)
        self.assertEqual(before, files())

    def test_limits_discard_complete_looking_answers(self):
        for name, value in (('MAX_BYTES', 20), ('MAX_FILES', 1), ('SECONDS', -1), ('MAX_EXPANDED', 30)):
            with self.subTest(name=name), patch.object(data, name, value):
                result = self.assess()
                self.assertEqual(result['status'], 'limit', result)
                self.assertFalse(result['input_ready'])
                self.assertFalse(result['records'])
        with patch.object(readiness, 'MAX_RESULT_BYTES', 10):
            self.assertEqual(self.assess()['status'], 'limit')

    def test_gzip_expansion_limit(self):
        self.header['path'] = 'big.json.gz'
        self.artifact('big.json.gz', {'padding': 'x' * (data.MAX_DOCUMENT + 1)})
        self.pin()
        self.assertEqual(self.assess()['status'], 'limit')

    def test_duplicate_json_and_nonfinite_rejected(self):
        for raw in (b'{"id":1,"id":2}', b'{"number":1e999}'):
            (self.directory / 'profile.json').write_bytes(raw)
            self.manifest['files']['profile.json'] = digest(raw)
            self.pin()
            self.assertFalse(self.assess()['input_ready'])

    def test_direct_internal_import_has_no_optional_solver_gis_or_orbit_dependency(self):
        code = """import sys
class Block:
 def find_spec(self, name, *args):
  if name.split('.')[0] in ('skyfield','sgp4','numpy','rasterio','pyproj','shapely','data'):
   raise ImportError('Optional dependency blocked: '+name)
sys.meta_path.insert(0,Block())
from scripts import flood_readiness
print(len(flood_readiness.CATEGORIES))
"""
        done = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, timeout=15)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), '8')

    def test_metadata_changes_require_new_scoped_review(self):
        self.body['requirements'][0]['criteria']['accuracy']['value'] = 'unreviewed new threshold'
        self.artifact('profile.json', self.body)
        self.pin()
        result = self.assess()
        self.assertIn('profile_unreviewed', result['blockers'])
        self.assertEqual(self.row()['state'], 'unreviewed')

    def test_manifest_only_cannot_supply_numerical_evidence(self):
        pointer = json.loads((self.source / 'current.json').read_bytes())
        dep = copy.deepcopy(self.dependency)
        dep['artifacts'] = [dict(path='s1/manifest.json', **{k: pointer[k] for k in ('sha256', 'byte_count')})]
        self.item('terrain')['dependencies'] = [dep]
        self.publish()
        self.assertEqual(self.row()['reasons'], ['numerical_artifact_evidence_missing'])

    def test_input_generation_must_be_pinned(self):
        self.item('terrain')['generation'] = 'unrelated'
        self.req('terrain')['input']['generation'] = 'unrelated'
        self.publish()
        self.assertEqual(self.row()['reasons'], ['input_generation_not_pinned'])

    def test_per_input_removal_and_unavailable_states(self):
        shutil.copytree(self.source, self.base / 'terrain_inputs')
        dep = copy.deepcopy(self.dependency)
        dep['dataset'] = 'terrain_inputs'
        self.item('terrain')['dependencies'] = [dep]
        self.publish()
        (self.base / 'datasets.json').write_text(json.dumps(dict(schema=1, datasets={'terrain_inputs': dict(active=None)})))
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.base)}):
            self.assertEqual(self.row()['state'], 'removed')
        (self.base / 'datasets.json').unlink()
        (self.base / 'terrain_inputs/s1/values.json').unlink()
        self.assertEqual(self.row()['state'], 'unavailable')

    def test_missing_source_appearing_during_query_invalidates_discovery(self):
        original = data.Snapshot.finish
        def install(reader):
            directory = self.base / 'flood_hazards'
            directory.mkdir()
            (directory / 'static.json').write_text('{}')
            original(reader)
        with patch.object(data.Snapshot, 'finish', install):
            result = readiness.discover(config=self.config)
        self.assertEqual(result['reasons'], ['generation_changed'])

    def test_registry_mutation_invalidates_assessment(self):
        registry = self.base / 'datasets.json'
        registry.write_text(json.dumps(dict(schema=1, datasets={})))
        original = data.Snapshot.finish
        def mutate(reader):
            registry.write_text(json.dumps(dict(schema=1, datasets={'flood_readiness': dict(active=None)})))
            original(reader)
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.base)}), patch.object(data.Snapshot, 'finish', mutate):
            self.assertEqual(self.assess()['reasons'], ['generation_changed'])

    def test_path_escape_rejected(self):
        self.item('terrain')['dependencies'] = [dict(self.dependency, pointer='../escape.json')]
        self.publish()
        self.assertEqual(self.row()['state'], 'unavailable')

    def test_required_selector_keeps_input_leading_zeroes(self):
        self.req('terrain')['input']['id'] = '1-terrain'
        self.publish()
        self.assertEqual(self.row()['state'], 'not_installed')

    def test_model_domain_identity_and_reviewed_association(self):
        self.scope = dict(self.body['domain']['identity'])
        self.header['scope'] = self.body['scope'] = self.scope
        self.publish()
        self.assertTrue(self.assess()['input_ready'])
        self.scope = dict(self.scope, source='different')
        self.assertEqual(self.assess()['status'], 'unknown')

    def test_scope_to_domain_cannot_be_an_unrelated_reviewed_link(self):
        self.body['domain']['associations'][0]['from'] = dict(self.scope, id='elsewhere')
        self.publish()
        self.assertIn('scope_to_domain_association_missing', self.assess()['blockers'])

    def test_malformed_collections_fail_closed(self):
        for value in ([], None, 'invalid', dict(self.body, inputs=[None])):
            self.artifact('profile.json', value)
            self.pin()
            result = self.assess()
            self.assertFalse(result['input_ready'])
            self.assertEqual(result['records'], [])

    def test_bounded_set_criteria_and_nested_boolean_types(self):
        self.assertEqual(readiness._criterion({'value': True}, dict(op='eq', value={'value': 1}))[0], 'incompatible')
        self.item('terrain')['facts']['spatial_coverage'] = ['D001'] * 129
        self.req('terrain')['criteria']['spatial_coverage'] = dict(op='contains', value=['D001'])
        self.publish()
        self.assertEqual(self.assess()['status'], 'limit')

    def test_context_manifest_does_not_promote_latest_values(self):
        root = self.base / 'usgs_water'
        root.mkdir()
        raw = json.dumps(dict(generation='o1', kind='observations', complete=True,
                             retention='latest_values_only', counts={'stage': 2})).encode()
        (root / 'manifest.json').write_bytes(raw)
        (root / 'observations.json').write_text(json.dumps(dict(manifest_path='manifest.json', **digest(raw))))
        result = readiness.discover(source='usgs_water', config=self.config)
        row = next(r for r in result['records'] if r.get('artifact') == 'observations.json')
        self.assertEqual(row['metadata']['retention'], 'latest_values_only')
        self.assertEqual(row['suitability'], 'unreviewed')
        self.assertEqual(row['integrity'], 'manifest_only')
        self.assertFalse(result['input_ready'])

    def test_basin_manifest_discovery_handles_large_schema_without_claiming_semantics(self):
        root = self.base / 'basin_plans'
        root.mkdir()
        raw = b'{"large_source_schema":"' + b'x' * (data.MAX_DOCUMENT + 1) + b'"}'
        (root / 'manifest.json').write_bytes(raw)
        (root / 'sources.json').write_text(json.dumps(dict(manifest_path='manifest.json',
            manifest_sha256=hashlib.sha256(raw).hexdigest(), snapshot_id='basin-001', dataset_count=70)))
        result = readiness.discover(source='basin_plans', config=self.config)
        self.assertEqual(result['records'][0]['integrity'], 'manifest_only')
        self.assertEqual(result['records'][0]['generation'], 'basin-001')
        self.assertFalse(result['input_ready'])

    def rewrite_source_manifest(self, change):
        """Repin a deliberately malformed source fixture without changing real data."""
        path = self.source / 's1/manifest.json'
        manifest = json.loads(path.read_bytes())
        change(manifest)
        raw = json.dumps(manifest).encode()
        path.write_bytes(raw)
        pointer = json.dumps(dict(manifest_path='s1/manifest.json', **digest(raw))).encode()
        (self.source / 'current.json').write_bytes(pointer)
        self.dependency['pin'] = digest(pointer)
        self.publish()

    def test_blank_and_nested_unknown_values_cannot_satisfy_requirements(self):
        for value in ('', '  ', 'UNKNOWN', {}, {'value': None, 'unit': 'm'},
                      {'value': 2, 'accuracy': 'unknown', 'unit': 'm'}):
            with self.subTest(value=value):
                self.item('terrain')['facts']['accuracy'] = value
                self.req('terrain')['criteria']['accuracy'] = dict(op='eq', value=value)
                self.publish()
                self.assertFalse(self.assess()['input_ready'])

    def test_empty_contains_does_not_establish_spatial_coverage(self):
        self.item('terrain')['facts']['spatial_coverage'] = []
        self.req('terrain')['criteria']['spatial_coverage'] = dict(op='contains', value=[])
        self.publish()
        self.assertFalse(self.assess()['input_ready'])

    def test_time_coverage_requires_valid_intervals_not_literal_equality(self):
        period = dict(start='not a timestamp', end='not a timestamp')
        self.item('boundaries')['facts']['time_coverage'] = period
        self.req('boundaries')['criteria']['time_coverage'] = dict(op='eq', value=period)
        self.publish()
        self.assertFalse(self.assess()['input_ready'])

    def test_current_observation_must_belong_to_reported_time_coverage(self):
        self.req('soil_moisture').update(time_mode='current', max_age_seconds=3600)
        self.item('soil_moisture')['observed_at'] = '2025-12-31T23:59:00Z'
        self.publish()
        self.assertFalse(self.assess()['input_ready'])

    def test_unsupported_dependency_schema_is_not_compatible(self):
        self.rewrite_source_manifest(lambda manifest: manifest.update(schema_version=2))
        self.assertFalse(self.assess()['input_ready'])

    def test_malformed_dependency_inventory_returns_structured_failure(self):
        self.rewrite_source_manifest(lambda manifest: manifest.update(files=[]))
        result = self.assess()
        self.assertFalse(result['input_ready'])
        self.assertEqual(result['records'], [])

    def test_archived_pointer_cannot_substitute_for_active_source(self):
        archive = self.source / 'archive'
        archive.mkdir()
        (archive / 'current.json').write_bytes((self.source / 'current.json').read_bytes())
        self.dependency['pointer'] = 'archive/current.json'
        (self.source / 'current.json').write_text('{}')
        self.publish()
        self.assertFalse(self.assess()['input_ready'])

    def test_latest_values_cannot_be_relabelled_as_hydrographs(self):
        self.rewrite_source_manifest(lambda manifest: manifest.update(kind='observations', retention='latest_values_only'))
        self.assertFalse(self.assess()['input_ready'])

    def test_empty_quality_flag_list_is_valid_recorded_evidence(self):
        self.item('terrain')['facts']['quality_flags'] = []
        self.req('terrain')['criteria']['quality_flags'] = dict(op='allowed', value=[])
        self.publish()
        self.assertEqual(self.row()['state'], 'suitable')

    def test_validation_independence_cannot_be_waived_by_equality(self):
        self.item('validation')['facts']['independence'] = False
        self.req('validation')['criteria']['independence'] = dict(op='eq', value=False)
        self.publish()
        self.assertFalse(self.assess()['input_ready'])

    def test_units_and_coordinate_references_require_definitions(self):
        for name in ('units', 'horizontal_crs', 'vertical_datum'):
            with self.subTest(name=name):
                self.item('terrain')['facts'][name] = []
                self.req('terrain')['criteria'][name] = dict(op='eq', value=[])
                self.publish()
                self.assertFalse(self.assess()['input_ready'])

    def test_registry_reads_share_the_budget_and_custom_roots_bypass_it(self):
        registry_root = self.base / 'unrelated_registry'
        registry_root.mkdir()
        (registry_root / 'datasets.json').write_bytes(b'x' * (data.MAX_DOCUMENT + 1))
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(registry_root)}):
            self.assertTrue(self.assess()['input_ready'])
        (self.base / 'datasets.json').write_bytes(b'x' * (data.MAX_DOCUMENT + 1))
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.base)}):
            result = self.assess()
        self.assertEqual(result['status'], 'limit')

    def test_unbounded_registry_read_is_not_used_by_readiness(self):
        registry = self.base / 'datasets.json'
        registry.write_text(json.dumps(dict(schema=1, datasets={})))
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.base)}), patch.object(Path, 'read_text', side_effect=AssertionError('unbounded read')):
            self.assertTrue(self.assess()['input_ready'])

    def test_registry_malformed_types_are_reported(self):
        for value in (None, [], dict(schema=True, datasets={})):
            (self.base / 'datasets.json').write_text(json.dumps(value))
            with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.base)}):
                self.assertFalse(self.assess()['input_ready'])

    def test_assessment_time_range_validated_before_io(self):
        with patch.object(data, 'Snapshot', side_effect=AssertionError('IO')):
            for now in (1e300, -1e300):
                with self.assertRaises(ValueError):
                    readiness.assess(self.scope, self.header['intended_use'], now=now)


if __name__ == '__main__':
    unittest.main()
