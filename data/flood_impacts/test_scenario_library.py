"""Deterministic W10-C maintenance budgets, provenance and detached-generation tests."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from data.flood_impacts import archive, scenario_library as library

# Reuse source-shaped runtime fixtures without requiring a running service.
PACKAGE = Path(__file__).resolve().parents[2]/'meshcore_mqtt_service'
sys.path.insert(0,str(PACKAGE))
sys.path.insert(0,str(PACKAGE/'tests'))
import test_flood_reference as fixtures
from test_flood_evidence import write_json


class Response(io.BytesIO):
    headers = {'Content-Type':'application/json'}


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fetch(self, raw=b'{"value":1}', **limits):
        with patch.object(archive,'urlopen',return_value=Response(raw)):
            return archive.fetch(self.root,'fixture','https://example.test/source',budget=archive.AcquisitionBudget(**limits))

    def test_original_response_and_receipt_are_exact_and_cannot_be_overwritten(self):
        raw=b'{ "value": 1 }\n'
        self.fetch(raw)
        self.assertEqual(gzip.decompress((self.root/'raw/fixture.json.gz').read_bytes()),raw)
        receipt=archive.read_json(self.root/'raw/fixture.receipt.json')
        self.assertEqual(receipt['raw_sha256'],hashlib.sha256(raw).hexdigest())
        with self.assertRaisesRegex(ValueError,'already exist'):
            self.fetch()

    def test_response_and_aggregate_byte_limits(self):
        with self.assertRaisesRegex(ValueError,'byte limit'):
            self.fetch(b'123456',response_bytes=5)
        budget=archive.AcquisitionBudget(total_bytes=7)
        with patch.object(archive,'urlopen',side_effect=[Response(b'{}  '),Response(b'{}  ')]):
            archive.fetch(self.root,'one','https://example.test',budget=budget)
            with self.assertRaisesRegex(ValueError,'byte limit'):
                archive.fetch(self.root,'two','https://example.test',budget=budget)

    def test_failed_requests_consume_budget_and_bound_retries(self):
        with patch.object(archive,'urlopen',side_effect=URLError('offline')) as request, patch.object(archive.time,'sleep'):
            with self.assertRaises(URLError):
                archive.fetch(self.root,'fixture','https://example.test',budget=archive.AcquisitionBudget())
            self.assertEqual(request.call_count,3)
        with patch.object(archive,'urlopen',side_effect=URLError('offline')) as request, patch.object(archive.time,'sleep'):
            with self.assertRaisesRegex(ValueError,'request limit'):
                archive.fetch(self.root,'fixture','https://example.test',budget=archive.AcquisitionBudget(requests=1))
            self.assertEqual(request.call_count,1)

    def test_expired_batch_performs_no_request(self):
        budget=archive.AcquisitionBudget()
        budget.until=0
        with patch.object(archive,'urlopen') as request:
            with self.assertRaisesRegex(ValueError,'duration limit'):
                archive.fetch(self.root,'fixture','https://example.test',budget=budget)
            request.assert_not_called()

    def test_invalid_json_and_provider_error_retain_original_evidence(self):
        for i,raw in enumerate((b'not-json',b'{"error":"provider failure"}',b'{"exceededTransferLimit":true}')):
            with patch.object(archive,'urlopen',return_value=Response(raw)):
                with self.assertRaises(ValueError):
                    archive.fetch(self.root,'failure'+str(i),'https://example.test')
            self.assertEqual(gzip.decompress((self.root/f'raw/failure{i}.json.gz').read_bytes()),raw)

    def test_missing_duplicate_or_excessive_id_inventories(self):
        for ids in (None,[1,1],[1,2,3]):
            with patch.object(archive,'fetch',side_effect=[{'objectIdField':'oid'},{'objectIds':ids}]):
                with self.assertRaises(ValueError):
                    archive.arcgis(self.root,'test','https://example.test','oid=1',budget=archive.AcquisitionBudget(features=2))

    def test_truncated_feature_response_is_rejected(self):
        replies=[{'objectIdField':'oid'},{'objectIds':[1,2]},{'features':[{'properties':{'oid':1}}]}]
        with patch.object(archive,'fetch',side_effect=replies):
            with self.assertRaisesRegex(ValueError,'Incomplete'):
                archive.arcgis(self.root,'test','https://example.test','oid=1')

    def test_arcgis_does_not_erase_an_unsupported_response_crs(self):
        replies = [{'objectIdField': 'oid'}, {'objectIds': [1]},
                   {'crs': {'type': 'name', 'properties': {'name': 'EPSG:3857'}},
                    'features': [{'properties': {'oid': 1}}]}]
        with patch.object(archive, 'fetch', side_effect=replies):
            with self.assertRaisesRegex(ValueError, 'CRS'):
                archive.arcgis(self.root, 'test', 'https://example.test', 'oid=1')

    def test_arcgis_rejects_boolean_source_object_ids(self):
        replies = [{'objectIdField': 'oid'}, {'objectIds': [1]},
                   {'features': [{'properties': {'oid': True}}]}]
        with patch.object(archive, 'fetch', side_effect=replies):
            with self.assertRaises(ValueError):
                archive.arcgis(self.root, 'test', 'https://example.test', 'oid=1')

    def test_batch_identity_and_changed_layer_scope_fail_before_payload(self):
        with patch.object(archive,'fetch',return_value={'layers':[]}),patch.object(archive,'arcgis') as acquire:
            with self.assertRaisesRegex(ValueError,'layer inventory changed'):
                library.acquire_review_batch(self.root,catalog_id=4415,catalog_lid='hopc1',gauge_lid='HOPC1',
                    usgs_id='11462500',budget=archive.AcquisitionBudget(),fim_version='6.2',model_version='4.9')
            acquire.assert_not_called()

    def test_batch_preserves_independent_ids_and_does_not_activate(self):
        service={'layers':[{'id':i,'geometryType':'esriGeometryPolygon'} for i in library.SCENARIO_LAYERS]}
        site={'features':[{'properties':dict(oid=4415,ahps_lid='hopc1',usgs_gage='01462500',fim_version='6.2',model_version='4.9')} ]}
        gauge=dict(lid='HOPC1',usgsId='01462500')
        nldi={'features':[{'properties':{'identifier':'USGS-01462500'}}]}
        with patch.object(archive,'fetch',side_effect=[service,gauge,nldi]) as fetch,patch.object(archive,'arcgis',return_value=site) as arcgis:
            result=library.acquire_review_batch(self.root,catalog_id=4415,catalog_lid='hopc1',gauge_lid='HOPC1',
                usgs_id='01462500',budget=archive.AcquisitionBudget(),fim_version='6.2',model_version='4.9')
            self.assertEqual(result['status'],'unreviewed')
            self.assertFalse(result['activation'])
            self.assertEqual(arcgis.call_count,10)
            self.assertTrue(fetch.call_args_list[-1].args[2].endswith('USGS-01462500'))
            self.assertEqual(list(self.root.iterdir()),[])


class LibraryTests(unittest.TestCase):
    setUp=fixtures.ReferenceTests.setUp
    artifact=fixtures.ReferenceTests.artifact
    json_artifact=fixtures.ReferenceTests.json_artifact
    features=fixtures.ReferenceTests.features
    csv_artifact=fixtures.ReferenceTests.csv_artifact
    publish=fixtures.ReferenceTests.publish
    publish_manifest=fixtures.ReferenceTests.publish_manifest

    def basins(self):
        """Supply six pinned source datasets and independent nested California polygons."""
        geometry={'type':'Polygon','coordinates':[[[-123,38],[-122.99,38],[-122.99,38.01],[-123,38.01],[-123,38]]]}
        for path in (self.footprint,'inputs/catfim_2.geojson.gz'):
            doc=json.loads(gzip.decompress((self.folder/path).read_bytes()))
            for f in doc['features']:
                f['geometry']=copy.deepcopy(geometry)
            self.json_artifact(path,doc)
        datasets=[]
        entries=[]
        root=self.base/'basin_plans'
        for name in library.CALWATER_LEVELS:
            path='inputs/'+name+'.geojson.gz'
            doc={'type':'FeatureCollection','features':[{'type':'Feature','geometry':geometry,'properties':{'objectid':'001'}}]}
            self.json_artifact(path,doc)
            original = root/'snapshots/b1'/path
            archive.write_json(original, doc)
            fingerprint = archive.digest(original)
            source=dict(name=name,path=path,dataset_key=name,object_id_field='objectid',snapshot_id='b1',
                source_sha256=fingerprint['sha256'],source_url='fixture-source',source_record_count=1,selected_count=1)
            datasets.append(source)
            entries.append(dict(key=name,name=name,path=path,kind='spatial',**fingerprint,source_url='fixture-source',
                                object_id_field='objectid',record_count=1))
        manifest={'schema_version':1,'snapshot_id':'b1','complete':True,'datasets':entries}
        digest=write_json(root/'snapshots/b1/manifest.json',manifest)
        report={'schema_version':1,'snapshot_id':'b1','source_manifest_sha256':digest['sha256'],
            'dataset_keys':sorted(e['key'] for e in entries),'dataset_count':6,'files':{}}
        organization=write_json(root/'organized/b1/organization.json',report)
        pointer=copy.deepcopy(self.manifest['basin_source'])
        pointer.update(manifest_sha256=digest['sha256'],organization_manifest_sha256=organization['sha256'])
        write_json(root/'sources.json',pointer)
        self.manifest['basin_source']=pointer
        self.json_artifact('inputs/basin_provenance.json',dict(source_pointer=pointer,datasets=datasets))
        self.publish_manifest()

    def test_partial_admission_retains_eligible_scenario_and_failed_reason(self):
        self.source_rows[1].pop('vertical_reference')
        self.publish()
        result=library.admission(self.config)
        self.assertEqual(result['libraries'][0]['status'],'partial')
        self.assertTrue(result['libraries'][0]['scenarios'][0]['eligible'])
        self.assertFalse(result['libraries'][0]['scenarios'][1]['eligible'])
        self.assertFalse(result['activation'])

    def test_admission_checks_unconsumed_artifact_integrity(self):
        (self.folder/'inputs/catalog.json').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            library.admission(self.config)

    def test_six_levels_reproducible_no_nested_area_sum_or_original_change(self):
        self.basins()
        before={str(p):p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        first=library.derive_intersections(self.config,'HEAC1_s21',self.region)
        self.assertEqual(first,library.derive_intersections(self.config,'HEAC1_s21',self.region))
        self.assertEqual(len(first['rows']),6)
        self.assertEqual(len({r['calwater_level'] for r in first['rows']}),6)
        self.assertTrue(all(abs(r['basin_fraction']-1)<1e-8 for r in first['rows']))
        self.assertNotIn('total_area',first)
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.base.rglob('*') if p.is_file()})

    def test_missing_level_and_changed_provenance_rejected(self):
        self.basins()
        path='inputs/basin_provenance.json'
        doc=archive.read_json(self.folder/path)
        doc['datasets'].pop()
        self.json_artifact(path,doc)
        self.publish_manifest()
        with self.assertRaisesRegex(ValueError,'level_missing'):
            library.derive_intersections(self.config,'HEAC1_s21',self.region)

    def test_invalid_basin_geometry_never_repaired(self):
        self.basins()
        name=next(iter(library.CALWATER_LEVELS))
        path='inputs/'+name+'.geojson.gz'
        doc=archive.read_json(self.folder/path)
        doc['features'][0]['geometry']['coordinates']=[]
        self.json_artifact(path,doc)
        self.publish_manifest()
        with self.assertRaises(ValueError):
            library.derive_intersections(self.config,'HEAC1_s21',self.region)

    def test_valid_but_changed_basin_geometry_is_not_original_source_evidence(self):
        self.basins()
        name = next(iter(library.CALWATER_LEVELS))
        path = 'inputs/'+name+'.geojson.gz'
        document = archive.read_json(self.folder/path)
        for point in document['features'][0]['geometry']['coordinates'][0]:
            point[0] += 0.001
        self.json_artifact(path, document)
        self.publish_manifest()
        with self.assertRaisesRegex(ValueError, 'source_feature'):
            library.derive_intersections(self.config, 'HEAC1_s21', self.region)

    def test_empty_basin_identity_is_rejected(self):
        self.basins()
        name = next(iter(library.CALWATER_LEVELS))
        path = 'inputs/'+name+'.geojson.gz'
        document = archive.read_json(self.folder/path)
        document['features'][0]['properties']['objectid'] = ''
        self.json_artifact(path, document)
        self.publish_manifest()
        with self.assertRaises(ValueError):
            library.derive_intersections(self.config, 'HEAC1_s21', self.region)

    def test_validator_cannot_rewrite_the_expected_manifest_to_hide_changes(self):
        stage, identifier = self.candidate()
        before = (self.root/'static.json').read_bytes()
        def change(directory, manifest):
            path = directory/'inputs/catalog.json'
            path.write_bytes(b'changed')
            manifest['files']['inputs/catalog.json'] = archive.digest(path)
            archive.write_json(directory/'manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, 'changed during validation'):
            archive.publish(self.root, stage, identifier, 'static', {}, validator=change)
        self.assertEqual((self.root/'static.json').read_bytes(), before)

    def test_no_intersection_when_scenario_is_ineligible(self):
        self.source_rows[0].pop('vertical_reference')
        self.publish()
        with self.assertRaisesRegex(ValueError,'ineligible'):
            library.derive_intersections(self.config,'HEAC1_s21',self.region)

    def candidate(self):
        stage,identifier=archive.begin(self.root,'static')
        for path in self.folder.rglob('*'):
            if path.is_file() and path.name!='manifest.json':
                target=stage/path.relative_to(self.folder)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,target)
        return stage,identifier

    def test_detached_candidate_preserves_active_and_originals(self):
        stage,identifier=self.candidate()
        before=(self.root/'static.json').read_bytes()
        archive.write_json(stage/'reviewed_candidate.json',{'status':'fixture'})
        with archive.build_lock(self.root):
            target,manifest=library.retain_candidate(self.root,stage,identifier,
                {'basin_source':self.manifest['basin_source']},json.loads(before),lambda *args:None)
        self.assertEqual((self.root/'static.json').read_bytes(),before)
        self.assertTrue(target.exists())
        self.assertTrue(set(self.manifest['files']) <= set(manifest['files']))
        self.assertEqual(manifest['network'], self.manifest['network'])
        archive.open_generation(self.root)

    def test_candidate_cannot_change_network_meaning_of_retained_links(self):
        stage, identifier = self.candidate()
        pointer = archive.read_json(self.root/'static.json')
        with self.assertRaisesRegex(ValueError, 'retained generation metadata'):
            library.retain_candidate(self.root, stage, identifier,
                {'basin_source': self.manifest['basin_source'], 'network': 'different-network'},
                pointer, lambda *args: None)
        self.assertEqual(archive.read_json(self.root/'static.json'), pointer)

    def test_linked_artifacts_are_rejected_before_validation(self):
        stage, identifier = self.candidate()
        original = self.folder/'inputs/catalog.json'
        target = stage/'inputs/catalog.json'
        target.unlink()
        target.hardlink_to(original)
        before = original.read_bytes()
        validator = unittest.mock.Mock()
        with self.assertRaisesRegex(ValueError, 'linked artifacts'):
            archive.publish(self.root, stage, identifier, 'static', {}, validator=validator)
        validator.assert_not_called()
        self.assertEqual(original.read_bytes(), before)

    def test_pinned_basin_original_tampering_is_rejected(self):
        self.basins()
        name = next(iter(library.CALWATER_LEVELS))
        original = self.base/'basin_plans/snapshots/b1/inputs'/f'{name}.geojson.gz'
        original.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            library.derive_intersections(self.config, 'HEAC1_s21', self.region)

    def test_source_basin_decompression_uses_shared_limit(self):
        self.basins()
        original = library.verify_basin_subset
        def exhausted(reader, entry, subset):
            reader.expanded_remaining = 1
            return original(reader, entry, subset)
        with patch.object(library, 'verify_basin_subset', side_effect=exhausted):
            with self.assertRaisesRegex(ValueError, 'basin_source_expansion_limit'):
                library.derive_intersections(self.config, 'HEAC1_s21', self.region)

    def test_failed_validation_keeps_previous_active(self):
        stage,identifier=self.candidate()
        before=(self.root/'static.json').read_bytes()
        def fail(*args):
            raise ValueError('fixture rejection')
        with self.assertRaisesRegex(ValueError,'fixture rejection'):
            library.retain_candidate(self.root,stage,identifier,{'basin_source':self.manifest['basin_source']},json.loads(before),fail)
        self.assertEqual((self.root/'static.json').read_bytes(),before)
        self.assertTrue(stage.exists())

    def test_coverage_loss_and_dependency_changes_block_candidate(self):
        for change in ('coverage','dependency'):
            stage,identifier=self.candidate()
            before=(self.root/'static.json').read_bytes()
            details={'basin_source':copy.deepcopy(self.manifest['basin_source'])}
            if change=='coverage':
                (stage/'inputs/catalog.json').write_bytes(b'changed')
            else:
                details['basin_source']['snapshot_id']='other'
            with self.assertRaises(ValueError):
                library.retain_candidate(self.root,stage,identifier,details,json.loads(before),lambda *args:None)
            self.assertEqual((self.root/'static.json').read_bytes(),before)

    def test_failed_pointer_replacement_preserves_previous_active(self):
        stage,identifier=self.candidate()
        before=(self.root/'static.json').read_bytes()
        with patch.object(archive.os,'replace',side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                archive.publish(self.root,stage,identifier,'static',{})
        self.assertEqual((self.root/'static.json').read_bytes(),before)

    def test_validator_cannot_modify_artifacts_after_hashing(self):
        stage,identifier=self.candidate()
        before=(self.root/'static.json').read_bytes()
        def change(directory,manifest):
            (directory/'inputs/catalog.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed during validation'):
            archive.publish(self.root,stage,identifier,'static',{},validator=change)
        self.assertEqual((self.root/'static.json').read_bytes(),before)

    def test_existing_active_generation_cannot_be_published_in_place(self):
        before=(self.folder/'manifest.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'isolated pending'):
            archive.publish(self.root,self.folder,'f1','static',{})
        self.assertEqual((self.folder/'manifest.json').read_bytes(),before)

    def test_retry_after_failed_validation_does_not_hash_its_own_manifest(self):
        stage,identifier=self.candidate()
        with self.assertRaises(ValueError):
            archive.publish(self.root,stage,identifier,'static',{},activate=False,
                validator=lambda *args: (_ for _ in ()).throw(ValueError('fixture')))
        target,manifest=archive.publish(self.root,stage,identifier,'static',{},activate=False)
        self.assertNotIn('manifest.json',manifest['files'])
        self.assertTrue(target.is_dir())

    def test_detached_candidate_rejects_concurrent_pointer_change(self):
        stage,identifier=self.candidate()
        before=(self.root/'static.json').read_bytes()
        def change(directory,manifest):
            archive.write_json(self.root/'static.json',{'changed':'fixture'})
        with self.assertRaisesRegex(ValueError,'Active generation changed'):
            library.retain_candidate(self.root,stage,identifier,{'basin_source':self.manifest['basin_source']},
                                     json.loads(before),change)
        self.assertTrue(stage.exists())

    def test_intersection_geometry_budget_and_subset_count(self):
        self.basins()
        with patch.object(library.flood_geometry,'MAX_OPERATIONS',0):
            with self.assertRaises(ValueError):
                library.derive_intersections(self.config,'HEAC1_s21',self.region)
        path='inputs/basin_provenance.json'
        doc=archive.read_json(self.folder/path)
        doc['datasets'][0]['selected_count']=2
        self.json_artifact(path,doc)
        self.publish_manifest()
        with self.assertRaisesRegex(ValueError,'incomplete_subset'):
            library.derive_intersections(self.config,'HEAC1_s21',self.region)


if __name__=='__main__':
    unittest.main()
