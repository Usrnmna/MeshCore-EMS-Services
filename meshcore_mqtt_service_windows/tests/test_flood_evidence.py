"""W10-A independent evidence attributes and read-only generation contracts."""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import flood_evidence as e, flood_reference_data as d, water_settings

NOW = 1794081600
TIME = '2026-11-07T20:00:00+00:00'


def evidence(**changes):
    """Provide explicit supporting identities, not implicit hydraulic validation."""
    attrs = dict(catalog='listed', provider_mapping='mapped', installation='installed', integrity='passed',
                 compatibility='compatible', relationship='published_match', geography='california',
                 parameter='applicable', vertical_reference='compatible', observation='stale')
    attrs.update(changes)
    ref = dict(datum='NAVD88', zero=79.98, units='ft')
    return e.record('HEAC1_scenario', 'published_hypothetical_scenario', source='NOAA-CatFIM',
        generation='static-1', extent=dict(id='pilot',states=['CA']), vintage='2020-01-01T00:00:00Z',
        attributes=attrs, provenance=dict(catalog_reference='catalog-1', relationship_reference='link-1',
        integrity_reference='sha256-check-1', compatibility_reference='basin-pin-1'),
        provider_report=dict(status=attrs['provider_mapping'], reference='catalog-1', reported_at=None,
                             retrieved_at=TIME, reason='Recorded provider qualification'),
        scenario=dict(id='HEAC1_scenario', gauge_id='NOAA-HEAC1', stage=23, units='FT',
                      source_version='6.2',model_version='4.9',gauge_reference=ref,scenario_reference=ref))


def digest(raw):
    return dict(sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw))


def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(value)+'\n').encode()
    path.write_bytes(raw)
    return digest(raw)


def fixture(base):
    """Build source-shaped pinned flood/Basin Plan metadata in a temporary directory."""
    basins=base/'basin_plans'
    bm=dict(schema_version=1,snapshot_id='b1',complete=True,datasets=[])
    fingerprint=write_json(basins/'snapshots/b1/manifest.json',bm)
    report=dict(schema_version=1,snapshot_id='b1',source_manifest_sha256=fingerprint['sha256'],dataset_keys=[],dataset_count=0,files={})
    organized=write_json(basins/'organized/b1/organization.json',report)
    bp=dict(schema_version=1,snapshot_id='b1',manifest_path='snapshots/b1/manifest.json',
            manifest_sha256=fingerprint['sha256'],organization_path='organized/b1',
            organization_manifest_sha256=organized['sha256'])
    write_json(basins/'sources.json',bp)
    root=base/'flood_impacts'
    folder=root/'static/f1'
    artifact=write_json(folder/'inputs/catalog.json',{'records':[{'id':'USGS-001','mapped':'no'}]})
    manifest=dict(schema_version=1,kind='static',complete=True,generation='f1',created_at_utc=TIME,
                  basin_source=bp,files={'inputs/catalog.json':artifact})
    pointer=dict(manifest_path='static/f1/manifest.json',**write_json(folder/'manifest.json',manifest))
    write_json(root/'static.json',pointer)
    return root,folder,manifest


class ContractTests(unittest.TestCase):
    def test_old_static_vintage_is_separate_from_observation_freshness(self):
        for observation in ('stale','unavailable','invalid','fresh'):
            value=evidence(observation=observation)
            self.assertTrue(e.assess(value)['static_reference'])
            self.assertEqual(value['attributes']['predictive_validation'],'not_assessed')
            self.assertEqual(e.assess(value)['current_inundation'],'not_assessed')

    def test_independent_coverage_combinations_preserve_discovery(self):
        for changes,reason in ((dict(installation='not_installed'),'installation:not_installed'),
                               (dict(integrity='unchecked'),'integrity:unchecked'),
                               (dict(integrity='failed'),'integrity:failed'),
                               (dict(compatibility='incompatible'),'compatibility:incompatible'),
                               (dict(relationship='conflicting'),'relationship:conflicting'),
                               (dict(installation='removed'),'installation:removed')):
            with self.subTest(changes=changes):
                value=evidence(**changes);result=e.assess(value)
                self.assertTrue(result['discovery']);self.assertFalse(result['static_reference'])
                self.assertIn(reason,result['reasons'])
                self.assertEqual(value['attributes']['provider_mapping'],'mapped')

    def test_unmapped_and_conflicting_installed_library(self):
        result=e.assess(evidence(provider_mapping='unmapped',installation='not_installed'))
        self.assertTrue(result['discovery']);self.assertFalse(result['static_reference'])
        result=e.assess(evidence(provider_mapping='unmapped'))
        self.assertIn('provider_unmapped_with_installed_library',result['contradictions'])
        self.assertFalse(result['static_reference'])

    def test_acquisition_failure_does_not_rewrite_installed_reference(self):
        value=evidence(acquisition='failed')
        self.assertTrue(e.assess(value)['static_reference'])
        self.assertEqual(value['attributes']['acquisition'],'failed')
        self.assertEqual(value['attributes']['observation'],'stale')

    def test_provider_evidence_date_is_not_retrieval_date(self):
        value=evidence(provider_mapping='unmapped',installation='not_installed')
        self.assertEqual(e.assess(value)['provider_evidence_time'],'unknown')
        self.assertEqual(value['provider_report']['reason'],'Recorded provider qualification')
        value['provider_report']['reported_at']='2020-01-01T00:00:00Z'
        self.assertEqual(e.assess(value)['provider_evidence_time'],'dated')
        value['provider_report']['status']='mapped'
        with self.assertRaisesRegex(ValueError,'conflict'):e.validate(value)
        value['provider_report']=None
        with self.assertRaisesRegex(ValueError,'source evidence'):e.validate(value)

    def test_all_evidence_classes_remain_distinct(self):
        for kind in e.EVIDENCE_CLASSES:
            value=evidence();value['evidence_class']=kind
            if kind=='validated_model_result':
                with self.assertRaises(ValueError):e.validate(value)
                continue
            self.assertEqual(e.assess(value)['static_reference'],kind=='published_hypothetical_scenario')
            self.assertEqual(value['evidence_class'],kind)

    def test_validation_claim_requires_matching_scoped_assessment(self):
        value=evidence()
        value['attributes']['numerical_verification']='passed'
        with self.assertRaises(ValueError):e.validate(value)
        assessment=dict(reference='report-1',method='mass-balance',purpose='pilot numerical verification',
                        source=value['source'],evidence_id=value['id'],
                        generation='static-1',extent_id='pilot',assessed_at=TIME)
        value['validation']['numerical_verification']=assessment
        e.validate(value)
        self.assertEqual(value['attributes']['predictive_validation'],'not_assessed')
        assessment['extent_id']='statewide'
        with self.assertRaisesRegex(ValueError,'scope'):e.validate(value)

    def test_exact_station_and_source_identities(self):
        self.assertEqual(e.station_id('USGS','00123'),'USGS-00123')
        self.assertNotEqual(e.station_id('USGS','00123'),e.station_id('CA','00123'))
        for value in (123, '', ' 001', 'x\n', 'x|y', '\u6e29'*54):
            with self.assertRaises(ValueError):e.identifier(value)
        self.assertEqual(e.identifier('NHD:000123'),'NHD:000123')

    def test_relationship_eligibility_is_not_endpoint_presence(self):
        row=dict(station='USGS-001',reach='00023',network='NHD-v2',status='published_identifier_match',evidence='source-link')
        self.assertEqual(e.relationship([row],'USGS-001','00023','NHD-v2'),'published_match')
        self.assertEqual(e.relationship([],'USGS-001','00023','NHD-v2'),'missing')
        self.assertEqual(e.relationship([row,row],'USGS-001','00023','NHD-v2'),'ambiguous')
        self.assertEqual(e.relationship([row,dict(row,reach='00024')],'USGS-001','00023','NHD-v2'),'conflicting')
        self.assertEqual(e.relationship([row],'USGS-001','00023','NHD-v3'),'incompatible')
        self.assertEqual(e.relationship([dict(row,status='nearest')],'USGS-001','00023','NHD-v2'),'unsupported')

    def test_geography_cross_border_requires_review(self):
        self.assertEqual(e.geography(dict(states=['CA']),'unknown'),'california')
        self.assertEqual(e.geography(dict(states=['CA','NV']),'unknown'),'not_assessed')
        self.assertEqual(e.geography(dict(states=['CA','NV']),'reviewed','drainage-link'),'cross_border_reviewed')
        self.assertEqual(e.geography(dict(states=['NV']),'reviewed','drainage-link'),'not_assessed')
        value=evidence(geography='cross_border_reviewed');value['extent']['states']=['CA','NV']
        self.assertFalse(e.assess(value)['static_reference'])
        value['provenance']['drainage_review']='review-1'
        self.assertTrue(e.assess(value)['static_reference'])

    def test_missing_datum_units_and_scenario_versions_block_reference(self):
        for key in ('model_version','gauge_reference','scenario_reference'):
            value=evidence();value['scenario'].pop(key)
            self.assertFalse(e.assess(value)['static_reference'])
        value=evidence();value['scenario']['scenario_reference']=dict(datum='NGVD29',zero=79.98,units='ft')
        self.assertIn('scenario_vertical_reference:incompatible',e.assess(value)['reasons'])
        value=evidence();value['scenario']['units']='kcfs'
        self.assertFalse(e.assess(value)['static_reference'])
        value=evidence();value['scenario']['units']='m'
        self.assertIn('scenario_stage_units:incompatible',e.assess(value)['reasons'])
        self.assertEqual(e.vertical_reference(dict(datum='X',zero=0,units='bad'),dict(datum='X',zero=0,units='bad')),'incompatible')

    def test_observation_time_is_not_retrieval_time(self):
        self.assertEqual(e.observation_state(TIME,NOW,3600),'fresh')
        self.assertEqual(e.observation_state(TIME,NOW+3601,3600),'stale')
        self.assertEqual(e.observation_state(TIME,NOW-1,3600),'invalid')
        self.assertEqual(e.observation_state(None,NOW,3600),'unavailable')
        self.assertEqual(e.observation_state('2026-11-07T20:00:00',NOW,3600),'invalid')

    def test_placeholder_datums_cannot_establish_compatibility(self):
        for datum in ('UNKNOWN', ' Unknown ', ' ', 'NaN', 'N/A', 'null', 'None'):
            with self.subTest(datum=datum):
                ref = dict(datum=datum, zero=0, units='ft')
                self.assertEqual(e.vertical_reference(ref, ref), 'missing')

    def test_validation_cannot_transfer_between_source_identities(self):
        value = evidence()
        value['attributes']['predictive_validation'] = 'passed'
        assessment = dict(reference='review-1', method='independent event comparison',
                          purpose='pilot inundation', generation='static-1', extent_id='pilot',
                          source=value['source'], evidence_id=value['id'], assessed_at=TIME)
        value['validation']['predictive_validation'] = assessment
        e.validate(value)
        for field in ('source', 'evidence_id'):
            changed = copy.deepcopy(value)
            changed['validation']['predictive_validation'][field] = 'another-source-record'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'scope'):
                e.validate(changed)

    def test_malformed_evidence_is_rejected_consistently(self):
        for value in (None, [], {}, dict(evidence(), attributes=None), dict(evidence(), extent={})):
            with self.subTest(value=type(value)), self.assertRaises(ValueError):
                e.validate(value)

    def test_summary_does_not_hide_validation_qualifications(self):
        value = evidence(predictive_validation='failed')
        with patch.dict(os.environ, MESHCORE_SENDER='A'):
            text = e.summaries([value])
        self.assertTrue('validation failed' in text.lower() or 'withheld' in text.lower())

    def test_partial_source_coverage_remains_distinct_from_integrity(self):
        value = evidence(coverage='partial')
        result = e.assess(value)
        self.assertTrue(result['static_reference'])
        self.assertEqual(value['attributes']['integrity'], 'passed')
        with patch.dict(os.environ, MESHCORE_SENDER='A'):
            text = e.summaries([value])
        self.assertTrue('coverage partial' in text.lower() or 'withheld' in text.lower())

    def test_short_identity_has_a_useful_qualified_radio_summary(self):
        value = evidence()
        value.update(source='F', id='S', generation='G')
        value['scenario']['id'] = 'S'
        with patch.dict(os.environ, MESHCORE_SENDER='A'):
            text = e.summaries([value])
        self.assertIn('F:S@G', text)
        self.assertIn('hypothetical', text)
        self.assertIn('not validated', text)
        self.assertIn('coverage unknown', text)
        self.assertLessEqual(len(('@A '+text).encode()), 150)

    def test_six_calwater_levels_do_not_mean_flow_or_water_board_regions(self):
        values=[e.calwater(level,'BP:layer:001','b1') for level in e.LEVELS]
        self.assertEqual(len(values),6)
        self.assertTrue(all('not hydraulic connectivity' in v['meaning'] for v in values))
        with self.assertRaises(ValueError):e.calwater('Water Board Region','01','b1')

    def test_radio_bounds_and_duplicate_identities(self):
        for sender in ('Alice','x'*80,'\u6e29'*26):
            with patch.dict(os.environ,MESHCORE_SENDER=sender):
                text=e.summaries([evidence()])
            self.assertLessEqual(len(('@'+sender+' '+text).encode()),150)
            self.assertIn('not all-clear',text.lower())
        with self.assertRaises(ValueError):e.summaries([evidence(),evidence()])
        with self.assertRaises(ValueError):e.summaries([evidence()]*21)
        with patch.dict(os.environ,MESHCORE_SENDER='Alice'):
            text=e.summaries([evidence(integrity='failed',relationship='conflicting')])
            self.assertTrue('failed' in text or 'withheld' in text)


class GenerationTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name)
        self.root,self.folder,self.manifest=fixture(self.base)
        self.config=water_settings.validate({'data_directory':str(self.base)})

    def publish_manifest(self):
        pointer=dict(manifest_path='static/f1/manifest.json',**write_json(self.folder/'manifest.json',self.manifest))
        write_json(self.root/'static.json',pointer)

    def test_full_integrity_compatibility_and_no_writes(self):
        before={p.relative_to(self.base):p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        result=d.inspect(self.config)
        self.assertEqual((result['integrity'],result['compatibility']),('passed','compatible'))
        self.assertEqual(result['checked_files'],1)
        self.assertEqual(result['predictive_validation'],'not_assessed')
        self.assertEqual(result['acquisition'],'not_checked')
        self.assertEqual(before,{p.relative_to(self.base):p.read_bytes() for p in self.base.rglob('*') if p.is_file()})

    def test_manifest_check_is_not_full_artifact_verification(self):
        snapshot=d.Snapshot(self.config)
        self.assertEqual(snapshot.verified,set())
        self.assertEqual(snapshot.metadata('inputs/catalog.json')['records'][0]['id'],'USGS-001')
        self.assertEqual(snapshot.verified,{'inputs/catalog.json'})
        snapshot.finish()

    def test_corrupted_or_missing_artifact_is_explicit_failed_integrity(self):
        path=self.folder/'inputs/catalog.json';path.write_bytes(b'changed')
        result=d.inspect(self.config)
        self.assertEqual(result['installation'],'installed');self.assertEqual(result['integrity'],'failed')
        path.unlink()
        self.assertEqual(d.inspect(self.config)['integrity'],'failed')

    def test_incomplete_and_malformed_manifests(self):
        self.manifest['complete']=False;self.publish_manifest()
        result=d.inspect(self.config)
        self.assertIn('incomplete_or_unsupported_generation',result['issues'])
        self.assertNotEqual(result['integrity'],'passed')
        (self.root/'static.json').write_text('invalid',encoding='utf-8')
        self.assertIn('metadata_unavailable_or_invalid',d.inspect(self.config)['issues'])

    def test_incompatible_basin_pin_does_not_erase_flood_integrity(self):
        self.manifest['basin_source']['snapshot_id']='other';self.publish_manifest()
        result=d.inspect(self.config)
        self.assertEqual(result['integrity'],'passed')
        self.assertEqual(result['compatibility'],'incompatible')

    def test_unavailable_basin_does_not_certify_compatibility(self):
        (self.base/'basin_plans/sources.json').unlink()
        result=d.inspect(self.config)
        self.assertEqual(result['integrity'],'passed');self.assertEqual(result['compatibility'],'unknown')
        self.assertIn('basin_dependency_unavailable_or_invalid',result['issues'])

    def test_basin_integrity_failure_is_separate_from_flood_integrity(self):
        (self.base/'basin_plans/snapshots/b1/manifest.json').write_bytes(b'corrupt')
        result=d.inspect(self.config)
        self.assertEqual(result['integrity'],'passed')
        self.assertEqual(result['basin_integrity'],'failed')
        self.assertEqual(result['compatibility'],'unknown')
        self.assertIn('basin_dependency:integrity_failed',result['issues'])

    def test_large_basin_manifest_uses_existing_file_allowance(self):
        basins=self.base/'basin_plans'
        path=basins/'snapshots/b1/manifest.json'
        manifest=json.loads(path.read_bytes())
        manifest['source_metadata']='x'*(d.MAX_METADATA_BYTES+1)
        fingerprint=write_json(path,manifest)
        report_path=basins/'organized/b1/organization.json'
        report=json.loads(report_path.read_bytes())
        report['source_manifest_sha256']=fingerprint['sha256']
        report_fingerprint=write_json(report_path,report)
        pointer=json.loads((basins/'sources.json').read_bytes())
        pointer.update(manifest_sha256=fingerprint['sha256'],organization_manifest_sha256=report_fingerprint['sha256'])
        write_json(basins/'sources.json',pointer)
        self.manifest['basin_source']=pointer;self.publish_manifest()
        result=d.inspect(self.config)
        self.assertEqual((result['integrity'],result['basin_integrity'],result['compatibility']),
                         ('passed','passed','compatible'))

    def test_basin_replacement_invalidates_an_existing_pin(self):
        snapshot=d.Snapshot(self.config);snapshot.check_basins()
        pointer=self.base/'basin_plans/sources.json'
        write_json(pointer,dict(json.loads(pointer.read_bytes()),snapshot_id='other'))
        with self.assertRaisesRegex(d.EvidenceError,'generation_changed'):snapshot.finish()

    def test_repeated_read_cannot_repin_changed_file(self):
        snapshot=d.Snapshot(self.config)
        path=self.folder/'inputs/catalog.json'
        snapshot.read(path,1000)
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(d.EvidenceError,'generation_changed'):snapshot.read(path,1000)

    def test_pointer_and_artifact_replacement_during_read(self):
        snapshot=d.Snapshot(self.config)
        snapshot.metadata('inputs/catalog.json')
        write_json(self.folder/'inputs/catalog.json',{'different':True})
        with self.assertRaisesRegex(d.EvidenceError,'generation_changed'):snapshot.finish()
        snapshot=d.Snapshot(self.config)
        pointer=json.loads((self.root/'static.json').read_bytes());pointer['manifest_path']='static/other/manifest.json'
        write_json(self.root/'static.json',pointer)
        with self.assertRaisesRegex(d.EvidenceError,'generation_changed'):snapshot.finish()

    def test_custom_path_and_managed_removal_are_distinct(self):
        managed=self.base/'managed';managed.mkdir()
        write_json(managed/'datasets.json',dict(schema=1,datasets={'flood_impacts':{'active':None}}))
        with patch.dict(os.environ,MESHCORE_DATA_DIR=str(managed)):
            self.assertEqual(d.inspect(self.config)['integrity'],'passed')
            result=d.inspect(water_settings.validate({}))
            self.assertEqual(result['installation'],'removed')
        (self.root/'static.json').unlink()
        self.assertEqual(d.inspect(self.config)['installation'],'not_installed')

    def test_bounds_and_path_escape(self):
        with patch.object(d,'MAX_BYTES',1):
            self.assertEqual(d.inspect(self.config)['integrity'],'partial')
        snapshot=d.Snapshot(self.config);snapshot.until=0
        with self.assertRaisesRegex(d.EvidenceError,'verification_limit'):snapshot.verify_all()
        self.manifest['files']['../outside']={'sha256':'0'*64,'byte_count':0};self.publish_manifest()
        self.assertNotEqual(d.inspect(self.config)['integrity'],'passed')

    def test_decompression_bound(self):
        raw=gzip.compress(b'x'*(d.MAX_METADATA_BYTES+1))
        (self.folder/'large.gz').write_bytes(raw)
        self.manifest['files']['large.gz']=digest(raw);self.publish_manifest()
        with self.assertRaisesRegex(d.EvidenceError,'metadata_expansion_limit'):
            d.Snapshot(self.config).metadata('large.gz')

    def test_nonobject_manifests_and_pointers_are_reported(self):
        for value in ([], None, 5, 'text'):
            with self.subTest(value=value):
                pointer = dict(manifest_path='static/f1/manifest.json',
                               **write_json(self.folder/'manifest.json', value))
                write_json(self.root/'static.json', pointer)
                result = d.inspect(self.config)
                self.assertNotEqual(result['integrity'], 'passed')
                self.assertTrue(result['issues'])
                write_json(self.root/'static.json', value)
                self.assertTrue(d.inspect(self.config)['issues'])

    def test_basin_pointer_reads_share_the_bounded_reader(self):
        original = Path.read_bytes

        def reject_unbounded_pointer(path):
            if path.name == 'sources.json':
                raise AssertionError('Basin pointer bypassed bounded reader')
            return original(path)

        with patch.object(Path, 'read_bytes', reject_unbounded_pointer):
            self.assertEqual(d.inspect(self.config)['compatibility'], 'compatible')

    def test_basin_managed_removal_is_explicit(self):
        write_json(self.base/'datasets.json', dict(schema=1, datasets={'basin_plans': {'active': None}}))
        with patch.dict(os.environ, MESHCORE_DATA_DIR=str(self.base)):
            result = d.inspect(self.config)
        self.assertEqual(result['installation'], 'installed')
        self.assertEqual(result['integrity'], 'passed')
        self.assertEqual(result['basin_installation'], 'removed')
        self.assertIn('basin_dependency:managed_removal', result['issues'])

    def test_internally_incompatible_basin_generation_is_explicit(self):
        basins = self.base/'basin_plans'
        report_path = basins/'organized/b1/organization.json'
        report = json.loads(report_path.read_bytes())
        report['snapshot_id'] = 'other-generation'
        fingerprint = write_json(report_path, report)
        pointer = json.loads((basins/'sources.json').read_bytes())
        pointer['organization_manifest_sha256'] = fingerprint['sha256']
        write_json(basins/'sources.json', pointer)
        self.manifest['basin_source'] = pointer
        self.publish_manifest()
        result = d.inspect(self.config)
        self.assertEqual(result['integrity'], 'passed')
        self.assertEqual(result['compatibility'], 'incompatible')


if __name__=='__main__':
    unittest.main()
