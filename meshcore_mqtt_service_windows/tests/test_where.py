"""W15 containment, pinned references, bounded replies and command integration."""
import asyncio
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from shapely.geometry import Point
import responder
from scripts import where_data as d, where_lookup as q
from scripts.command_dependencies import dependency_status, is_bundled
from test_stateparks import write_snapshot

ROOT = Path(__file__).resolve().parents[1]
POLYGON = {'type': 'Polygon', 'coordinates': [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


def feature(identifier=1, geometry=None, **properties):
    return dict(type='Feature', id=identifier, geometry=copy.deepcopy(geometry or POLYGON),
                properties=dict(FID=identifier, OBJECTID=identifier, objectid=identifier,
                                UNITNBR='007', UNITNAME='Same name', **properties))


def put(root, path, value, compressed=False):
    """Publish exact fixture bytes and return the installed checksum schema."""
    raw = json.dumps(value).encode()
    if compressed:
        raw = gzip.compress(raw)
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return dict(path=path, byte_count=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class WhereTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.park = self.root / 'parks'
        write_snapshot(self.park, {'park_boundaries': [feature()], 'park_entry_points': []}, [1])
        self.gis = self.root / 'gis'
        manifest = dict(coordinate_reference_system='WGS 84 (EPSG:4326)', datasets={})
        for name in d.gis_data.PARK_LAYERS:
            row = put(self.gis, name + '.json', dict(type='FeatureCollection', features=[feature(NAME='Same name', SITE_NAME='Same name')]))
            manifest['datasets'][name] = dict(row, feature_count=1, retrieved_at_utc='2020-01-01T00:00:00+00:00', source_url='https://example.test/' + name)
        put(self.gis, 'sources.json', manifest)
        settings = json.loads((ROOT/'gis_settings.json').read_bytes())
        settings['data_directory'] = str(self.gis)
        self.gis_settings = self.root / 'gis_settings.json'
        put(self.root, 'gis_settings.json', settings)
        original = d.gis_data.load_settings
        setting_patch = patch.object(d.gis_data, 'load_settings', lambda: original(self.gis_settings))
        setting_patch.start(); self.addCleanup(setting_patch.stop)
        self.basin = self.root / 'basin_plans'
        self.make_basins()
        self.zones = self.root / 'zones'
        f = feature('CAZ001', state='CA', zone='001', type='fire', name='Fire reference')
        f['properties']['id'] = 'CAZ001'
        evidence = put(self.zones, 'zones.geojson', dict(type='FeatureCollection', features=[f]))
        put(self.zones, 'manifest.json', dict(schema_version=1, sha256=evidence['sha256'],
            feature_count=1, zone_ids=['CAZ001'], source='https://example.test/zones',
            selection='Installed fire polygons intersecting California', retrieved_at=1))
        self.registry = {'schema': 1, 'datasets': {
            'california_state_parks': {'active': {'path': 'parks'}},
            'wildfire': {'active': {'path': 'zones'}},
            'ebmud': {'active': {'path': 'gis'}},
            'basin_plans': {'active': {'path': 'basin_plans'}}}}
        self.save_registry()
        env = patch.dict(os.environ, MESHCORE_DATA_DIR=str(self.root), MESHCORE_SENDER='Alice',
                         MESHCORE_WATER_SETTINGS=json.dumps({'data_directory': str(self.root)}))
        env.start(); self.addCleanup(env.stop)

    def save_registry(self):
        put(self.root, 'datasets.json', self.registry)

    def make_basins(self):
        entries, files = [], {}
        for i, level in enumerate(d.basin.LEVELS):
            key = 'svc/' + str(i)
            row = put(self.basin, f'snapshot/{i}.gz', dict(type='FeatureCollection', features=[feature('001')]), True)
            ids = put(self.basin, f'snapshot/{i}-ids.json', {'objectIds': ['001']})
            files[f'{i}-ids.json'] = ids
            entries.append(dict(row, path=f'{i}.gz', key=key, name='CalWater_Hydrologic_' + level,
                category='hydrologic_boundaries/calwater_2_2_1', object_id_field='objectid',
                record_count=1, id_evidence_path=f'{i}-ids.json', source_url='https://example.test/' + key,
                completed_at_utc='2020-01-01T00:00:00Z'))
        manifest = dict(schema_version=1, complete=True, snapshot_id='one', datasets=entries, files=files)
        evidence = put(self.basin, 'snapshot/manifest.json', manifest)
        report = put(self.basin, 'review/organization.json', dict(schema_version=1, snapshot_id='one',
            source_manifest_sha256=evidence['sha256'], dataset_keys=sorted(e['key'] for e in entries), dataset_count=6, files={}))
        put(self.basin, 'sources.json', dict(schema_version=1, snapshot_id='one', manifest_path=evidence['path'],
            manifest_sha256=evidence['sha256'], organization_path='review', organization_manifest_sha256=report['sha256']))

    def source(self, result, name):
        return next(e for e in result['sources'] if e['source'] == name)

    def test_default_sources_are_independent_and_resolved_once(self):
        sources = {k: tuple((n, unittest.mock.Mock(wraps=r)) for n, r in rows) for k, rows in d.SOURCES.items()}
        with patch.object(d, 'SOURCES', sources):
            result = q.lookup('1 1')
        self.assertFalse(result['partial'])
        self.assertEqual(len(result['sources']), 4)
        for rows in sources.values():
            for _, reader in rows:
                reader.assert_called_once()
        self.assertEqual(len(self.source(result, 'calwater')['matches']), 6)
        self.assertIn('no legal access', result['qualification'])

    def test_coordinate_and_selector_validation(self):
        for text in ('1 2', '-90 -180', '90 180', '0 0 park', '0 0 basin PW', '0 0 firezone'):
            self.assertIsNotNone(q.parse(text))
        for text in ('x 2', 'nan 0', '0 inf', '91 0', '0 -181', '0', '0 0 park park',
                     'park 0 0', '0 0 nearby', '0 0 basin PW x', '0 0 --json', '0 0\n',
                     '0 0 basin WaterBoard', '1_0 0', 'x'*151, '\u00e9'*76):
            with self.subTest(text=text), self.assertRaises(ValueError):
                q.parse(text)

    def test_overlaps_duplicate_names_and_boundaries(self):
        write_snapshot(self.park, {'park_boundaries': [feature(1), feature(2)], 'park_entry_points': []})
        for query, relation in [('1 1 park', 'contains'), ('0 1 park', 'boundary')]:
            rows = self.source(q.lookup(query), 'stateparks')['matches']
            self.assertEqual([r['id'] for r in rows], ['StateParks:FID:1', 'StateParks:FID:2'])
            self.assertEqual({r['relation'] for r in rows}, {relation})
            self.assertEqual(rows[0]['followup'], '!statepark id 007')

    def test_holes_multipolygons_and_no_proximity_substitution(self):
        hole = copy.deepcopy(POLYGON)
        hole['coordinates'].append([[.5,.5],[.5,1.5],[1.5,1.5],[1.5,.5],[.5,.5]])
        multi = dict(type='MultiPolygon', coordinates=[hole['coordinates']])
        rows = d.containing([feature(1,multi)], Point(1,1), lambda f: {'id':str(f['id'])}, time.monotonic()+5)
        self.assertEqual(rows, [])
        rows = d.containing([feature(1,multi)], Point(.5,1), lambda f: {'id':str(f['id'])}, time.monotonic()+5)
        self.assertEqual(rows[0]['relation'], 'boundary')
        result = q.lookup('3 3')
        self.assertEqual(self.source(result, 'stateparks')['status'], 'no_match')
        self.assertEqual(self.source(result, 'nws')['status'], 'outside_coverage')
        self.assertFalse(any(e['matches'] for e in result['sources']))

    def test_recorded_and_runtime_geometry_repairs(self):
        self.assertTrue(self.source(q.lookup('1 1 park'), 'stateparks')['matches'][0]['repaired'])
        bow = {'type':'Polygon','coordinates':[[[0,0],[2,2],[0,2],[2,0],[0,0]]]}
        rows = d.containing([feature(1,bow)], Point(1,.25), lambda f: {'id':str(f['id'])}, time.monotonic()+5)
        self.assertTrue(rows[0]['repaired'])

    def test_duplicate_ids_and_non_area_geometry_are_rejected(self):
        for rows in ([feature(),feature()], [feature(1, {'type':'LineString','coordinates':[[0,0],[1,1]]})]):
            with self.assertRaises(ValueError):
                d.containing(rows, Point(1,1), lambda f:{'id':str(f['id'])}, time.monotonic()+5)

    def test_calwater_levels_leading_zeroes_and_source_identity(self):
        rows = self.source(q.lookup('1 1 basin'), 'calwater')['matches']
        self.assertEqual({r['level'] for r in rows}, set(d.basin.LEVELS))
        self.assertEqual({r['id'] for r in rows}, {'BP:svc/'+str(i)+':001' for i in range(6)})
        result = q.lookup('1 1 basin PW')
        self.assertEqual(self.source(result,'calwater')['matches'][0]['level'], 'PW')
        self.assertIn('not Water Board', self.source(result,'calwater')['coverage'])
        self.assertIn('BP:svc/5:001', q.render(result))

    def test_firezone_qualifications_and_reference_dates(self):
        result = q.lookup('1 1 firezone')
        self.assertEqual(self.source(result,'nws')['evidence'],1)
        text = q.render(result)
        self.assertIn('CAZ001(contains)',text)
        self.assertIn('Not evacuation zones',text)
        self.assertNotIn('current',text)

    def test_partial_failure_retains_independent_matches(self):
        (self.park/'park_boundaries.json').write_bytes(b'corrupt')
        result = q.lookup('1 1')
        self.assertTrue(result['partial'])
        self.assertEqual(self.source(result,'stateparks')['status'],'unavailable')
        self.assertEqual(self.source(result,'nws')['matches'][0]['id'],'CAZ001')
        self.assertEqual(self.source(result,'ebmud')['match_count'],4)

    def test_custom_paths_and_managed_removal(self):
        self.assertEqual(self.source(q.lookup('1 1 firezone'),'nws')['matches'][0]['id'],'CAZ001')
        self.registry['datasets']['wildfire']['active']=None
        self.save_registry()
        self.assertEqual(self.source(q.lookup('1 1 firezone'),'nws')['status'],'unavailable')

    def test_basin_incompatible_generation(self):
        p=self.basin/'sources.json'; value=json.loads(p.read_bytes());value['snapshot_id']='two';put(self.basin,'sources.json',value)
        self.assertEqual(self.source(q.lookup('1 1 basin'),'calwater')['status'],'unavailable')

    def test_generation_or_removal_after_read_is_rejected(self):
        reader=d.fire_zones
        def changing(*args):
            result=reader(*args)
            self.registry['datasets']['wildfire']['active']=None;self.save_registry()
            return result
        with patch.dict(d.SOURCES, firezone=(('nws',changing),)):
            result=q.lookup('1 1')
        self.assertEqual(self.source(result,'nws')['matches'],[])
        self.assertIn('removed',self.source(result,'nws')['reason'])
        self.assertTrue(self.source(result,'calwater')['matches'])

    def test_file_change_after_read_is_rejected(self):
        rows,verify,_=d.state_parks(Point(1,1),time.monotonic()+5)
        self.assertTrue(rows)
        (self.park/'park_boundaries.json').write_bytes(b'changed')
        with self.assertRaises(ValueError):verify()

    def test_integrity_failures_for_each_independent_source(self):
        for path, query, source in ((self.park/'park_boundaries.json', '1 1 park', 'stateparks'),
                                    (self.gis/'ebrpd.json', '1 1 park', 'ebmud'),
                                    (self.basin/'snapshot/0.gz', '1 1 basin', 'calwater'),
                                    (self.zones/'zones.geojson', '1 1 firezone', 'nws')):
            with self.subTest(source=source):
                original=path.read_bytes()
                path.write_bytes(b'corrupt')
                result=self.source(q.lookup(query), source)
                self.assertEqual(result['status'],'unavailable')
                self.assertEqual(result['reason'],'Integrity failure')
                path.write_bytes(original)

    def test_removed_all_collections_discovery_is_unavailable(self):
        for entry in self.registry['datasets'].values():
            entry['active']=None
        self.save_registry()
        # Explicit external GIS paths remain authoritative under the existing policy.
        self.gis_settings.unlink()
        self.assertEqual(d.availability(),0)
        self.assertTrue(dependency_status('!where').startswith('Unavailable:'))

    def test_basin_pointer_swap_after_geometry_scan(self):
        rows,verify,_=d.calwater(Point(1,1),time.monotonic()+5,'PW')
        self.assertTrue(rows)
        pointer=json.loads((self.basin/'sources.json').read_bytes())
        pointer['snapshot_id']='replaced'
        put(self.basin,'sources.json',pointer)
        with self.assertRaises(ValueError):verify()

    def test_ebmud_manifest_swap_and_individual_file_change(self):
        for relative in ('sources.json','ebrpd.json'):
            path=self.gis/relative
            original=path.read_bytes()
            rows,verify,_=d.ebmud(Point(1,1),time.monotonic()+5)
            self.assertEqual(len(rows),4)
            path.write_bytes(b'changed')
            with self.assertRaises((ValueError, d.gis_data.GISUnavailable)):verify()
            path.write_bytes(original)

    def test_source_selection_does_not_read_other_categories(self):
        with patch.dict(d.SOURCES, park=(('stateparks', unittest.mock.Mock(side_effect=AssertionError('not selected'))),)):
            self.assertEqual(len(q.lookup('1 1 firezone')['sources']),1)

    def test_malformed_manifest_preserves_independent_sources(self):
        put(self.park, 'sources.json', [])
        result = q.lookup('1 1')
        self.assertTrue(result['partial'])
        self.assertEqual(self.source(result, 'stateparks')['status'], 'unavailable')
        self.assertEqual(self.source(result, 'nws')['matches'][0]['id'], 'CAZ001')
        self.assertEqual(d.availability(), 3)

    def publish_zones(self, document):
        """Update fixture checksums so tests reach source schema validation."""
        evidence = put(self.zones, 'zones.geojson', document)
        manifest = json.loads((self.zones / 'manifest.json').read_bytes())
        manifest['sha256'] = evidence['sha256']
        put(self.zones, 'manifest.json', manifest)

    def test_malformed_zone_identity_preserves_other_categories(self):
        document = json.loads((self.zones / 'zones.geojson').read_bytes())
        document['features'][0]['properties']['zone'] = 1
        self.publish_zones(document)
        result = q.lookup('1 1')
        self.assertEqual(self.source(result, 'nws')['status'], 'unavailable')
        self.assertEqual(self.source(result, 'calwater')['match_count'], 6)

    def test_non_geographic_firezone_crs_cannot_establish_containment(self):
        document = json.loads((self.zones / 'zones.geojson').read_bytes())
        document['crs'] = {'type': 'name', 'properties': {'name': 'EPSG:3857'}}
        self.publish_zones(document)
        self.assertEqual(self.source(q.lookup('1 1 firezone'), 'nws')['status'], 'unavailable')

    def test_explicit_geographic_crs_and_leading_zero_zone_remain_supported(self):
        document = json.loads((self.zones / 'zones.geojson').read_bytes())
        for name in ('EPSG:4326', 'urn:ogc:def:crs:OGC:1.3:CRS84'):
            with self.subTest(crs=name):
                document['crs'] = {'type': 'name', 'properties': {'name': name}}
                self.publish_zones(document)
                entry = self.source(q.lookup('1 1 firezone'), 'nws')
                self.assertEqual(entry['matches'][0]['id'], 'CAZ001')

    def test_invalid_zone_codes_and_duplicate_membership_are_unavailable(self):
        original = json.loads((self.zones / 'zones.geojson').read_bytes())
        for state, zone in (('CA', '0001'), ('ca', '001'), ('CA', '-01'), ('CA', True)):
            with self.subTest(state=state, zone=zone):
                document = copy.deepcopy(original)
                document['features'][0]['properties'].update(state=state, zone=zone)
                self.publish_zones(document)
                self.assertEqual(self.source(q.lookup('1 1 firezone'), 'nws')['status'], 'unavailable')
        self.publish_zones(original)
        manifest = json.loads((self.zones / 'manifest.json').read_bytes())
        manifest['zone_ids'].append('CAZ001')
        put(self.zones, 'manifest.json', manifest)
        self.assertEqual(self.source(q.lookup('1 1 firezone'), 'nws')['status'], 'unavailable')

    def test_malformed_feature_collections_are_local_failures(self):
        for document in ([], None, {'type': 'FeatureCollection', 'features': {}},
                         {'type': 'FeatureCollection', 'features': [None]}):
            with self.subTest(document=document):
                self.publish_zones(document)
                result = q.lookup('1 1')
                self.assertEqual(self.source(result, 'nws')['status'], 'unavailable')
                self.assertEqual(self.source(result, 'calwater')['match_count'], 6)

    def test_invalid_gzip_preserves_other_categories(self):
        # The bytes have a gzip header but an invalid deflate block. A valid
        # manifest digest must not make the compressed source readable.
        raw = b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff\x07'
        (self.basin / 'snapshot/0.gz').write_bytes(raw)
        manifest = json.loads((self.basin / 'snapshot/manifest.json').read_bytes())
        manifest['datasets'][0].update(byte_count=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        evidence = put(self.basin, 'snapshot/manifest.json', manifest)
        report = json.loads((self.basin / 'review/organization.json').read_bytes())
        report['source_manifest_sha256'] = evidence['sha256']
        review = put(self.basin, 'review/organization.json', report)
        pointer = json.loads((self.basin / 'sources.json').read_bytes())
        pointer.update(manifest_sha256=evidence['sha256'], organization_manifest_sha256=review['sha256'])
        put(self.basin, 'sources.json', pointer)
        result = q.lookup('1 1')
        self.assertEqual(self.source(result, 'calwater')['status'], 'unavailable')
        self.assertEqual(self.source(result, 'nws')['matches'][0]['id'], 'CAZ001')

    def test_expired_budget_does_not_start_another_source_read(self):
        reader = unittest.mock.Mock(side_effect=AssertionError('Read after deadline'))
        with patch.object(d, 'QUERY_SECONDS', -1), patch.dict(d.SOURCES, firezone=(('nws', reader),)):
            result = q.lookup('1 1 firezone')
        reader.assert_not_called()
        self.assertIn('limit', self.source(result, 'nws')['reason'])

    def test_final_verification_reports_timeout_without_claiming_generation_changed(self):
        reader = d.fire_zones
        def expiring(*args):
            rows, _, metadata = reader(*args)
            verify = unittest.mock.Mock(side_effect=ValueError('Query time limit'))
            return rows, verify, metadata
        with patch.dict(d.SOURCES, firezone=(('nws', expiring),)):
            result = q.lookup('1 1 firezone')
        entry = self.source(result, 'nws')
        self.assertEqual(entry['matches'], [])
        self.assertNotIn('match_count', entry)
        self.assertIn('limit', entry['reason'])
        self.assertNotIn('changed', entry['reason'])

    def test_watched_relative_path_cannot_retarget_during_query(self):
        guard = d.Guard(lambda: self.zones)
        guard.watch('zones.geojson')
        # Model a retargeted link without requiring Windows symlink privileges.
        with patch.object(d.dataset_paths, 'checked_path', return_value=self.zones / 'manifest.json'):
            with self.assertRaises(ValueError):
                guard.verify()

    def test_source_geometry_null_and_invalid_coordinates_are_unavailable(self):
        for geometry in (None, {'type':'Polygon','coordinates':[]},
                         {'type':'Polygon','coordinates':[[[200,0],[201,0],[201,1],[200,0]]]}):
            f=feature();f['geometry']=geometry
            write_snapshot(self.park, {'park_boundaries':[f],'park_entry_points':[]})
            self.assertEqual(self.source(q.lookup('1 1 park'),'stateparks')['status'],'unavailable')

    def test_declared_crs_and_membership_are_verified(self):
        manifest=json.loads((self.gis/'sources.json').read_bytes())
        manifest['coordinate_reference_system']='EPSG:3310'
        put(self.gis,'sources.json',manifest)
        self.assertEqual(self.source(q.lookup('1 1 park'),'ebmud')['status'],'unavailable')
        manifest=json.loads((self.zones/'manifest.json').read_bytes())
        manifest['zone_ids']=['CAZ002']
        put(self.zones,'manifest.json',manifest)
        self.assertEqual(self.source(q.lookup('1 1 firezone'),'nws')['status'],'unavailable')

    def test_reference_file_bound_and_missing_runtime_dependency(self):
        with patch.object(d,'MAX_EXPANDED',1):
            self.assertEqual(self.source(q.lookup('1 1 basin'),'calwater')['status'],'unavailable')
        with patch.dict(d.SOURCES, firezone=(('nws',unittest.mock.Mock(side_effect=ImportError('missing'))),)):
            self.assertEqual(self.source(q.lookup('1 1 firezone'),'nws')['reason'],'Runtime dependency unavailable')

    def test_limits_and_partial_results(self):
        with patch.object(d,'MAX_MATCHES',2):
            result=q.lookup('1 1 basin')
        row=self.source(result,'calwater')
        self.assertTrue(result['partial']);self.assertEqual(len(row['matches']),2);self.assertEqual(row['match_count'],6)
        with patch.object(d,'MAX_FEATURES',0):
            self.assertEqual(self.source(q.lookup('1 1 firezone'),'nws')['status'],'unavailable')
        with patch.object(d,'QUERY_SECONDS',-1):
            self.assertTrue(q.lookup('1 1')['partial'])

    def test_partial_qualification_survives_compact_fallback(self):
        result=q.lookup('1 1')
        result['partial']=True
        with patch.dict(os.environ,MESHCORE_SENDER='x'*80):
            text=q.render(result)
        self.assertIn('Partial',text)
        self.assertIn('withheld',text)

    def test_lookup_does_not_mutate_references_or_create_indexes(self):
        before={p.relative_to(self.root):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}
        self.assertFalse(q.lookup('1 1')['partial'])
        after={p.relative_to(self.root):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_empty_zone_collection_cannot_establish_outside_coverage(self):
        evidence=put(self.zones,'zones.geojson',dict(type='FeatureCollection',features=[]))
        manifest=json.loads((self.zones/'manifest.json').read_bytes())
        manifest.update(sha256=evidence['sha256'],feature_count=0,zone_ids=[])
        put(self.zones,'manifest.json',manifest)
        self.assertEqual(self.source(q.lookup('1 1 firezone'),'nws')['status'],'unavailable')

    def test_utf8_budgets_and_oversized_identity_withholding(self):
        result=q.lookup('1 1 firezone')
        for sender in ('Alice','a'*80,'\u6e29'*26):
            with patch.dict(os.environ,MESHCORE_SENDER=sender):
                text=q.render(result)
                self.assertLessEqual(len(('@'+sender+' '+text).encode()),150)
                if 'CAZ001' in text:self.assertIn('Not evacuation zones',text)
        result['sources'][0]['matches'][0]['id']='\u00e9'*200
        text=q.render(result)
        self.assertNotIn('\u00e9',text);self.assertIn('withheld',text)

    def test_discovery_and_dedicated_registration(self):
        spec=json.loads((ROOT/'config.json').read_bytes())['responder']['commands']['!where']
        self.assertEqual(spec['script'],'scripts/where.py');self.assertEqual(spec['args'],[])
        self.assertTrue(is_bundled('!where',spec))
        self.assertTrue(dependency_status('!where').startswith('Partial:'))
        with patch.object(d,'availability',return_value=0):
            self.assertTrue(dependency_status('!where').startswith('Unavailable:'))
        self.assertEqual(dependency_status('!where',False),'Dependencies unverified')

    def test_direct_structured_and_service_invocations(self):
        env=dict(os.environ);env.pop('MESHCORE_SENDER',None);env.pop('MESHCORE_REQUEST_ID',None)
        cmd=[sys.executable,str(ROOT/'scripts/where.py'),'--json','1','1','firezone']
        run=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=20,check=True)
        self.assertEqual(json.loads(run.stdout)['sources'][0]['matches'][0]['id'],'CAZ001')
        run=subprocess.run(cmd,env=dict(env,MESHCORE_REQUEST_ID='service'),capture_output=True,text=True,timeout=20,check=True)
        self.assertNotIn('"matches"',run.stdout)
        config=json.loads((ROOT/'config.json').read_bytes())['responder']
        config['_runtime_directory']=str(self.root/'runtime')
        request=dict(sender='Alice',channel_name='Test',channel_id='default',channel_index=3,id='w15',
                     phrase='!where 1 1 firezone',command='!where',arguments=['1 1 firezone'])
        text,error=asyncio.run(responder.run_script(ROOT,config['commands']['!where'],request,config))
        self.assertFalse(error);self.assertIn('CAZ001',text);self.assertIn('Not evacuation zones',text)


if __name__ == '__main__':
    unittest.main()
