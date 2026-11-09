"""W10-C fixture-only geometry, internal point selection and read-only boundaries."""
import copy
import gzip
import json
import unittest
from unittest.mock import patch

import test_flood_reference as fixtures
from scripts import flood_catalog as c, flood_geometry as g, flood_reference as f
from scripts import flood_reference_data as d


class GeometryTests(unittest.TestCase):
    setUp = fixtures.ReferenceTests.setUp
    artifact = fixtures.ReferenceTests.artifact
    json_artifact = fixtures.ReferenceTests.json_artifact
    features = fixtures.ReferenceTests.features
    csv_artifact = fixtures.ReferenceTests.csv_artifact
    publish = fixtures.ReferenceTests.publish
    publish_manifest = fixtures.ReferenceTests.publish_manifest

    def point(self, lat=0.2, lon=0.8, **kwargs):
        return f.scenario_at_coordinate(c.SOURCE, 'HEAC1_s21', lat, lon, config=self.config, **kwargs)

    def change_geometry(self, geometry, *, originals=True, **extra):
        """Replace selected test geometries and refresh fixture checksums only."""
        paths = [self.footprint, 'inputs/catfim_2.geojson.gz'] if originals else [self.footprint]
        for path in paths:
            doc = json.loads(gzip.decompress((self.folder/path).read_bytes()))
            doc.update(extra)
            for feature in doc['features']:
                feature['geometry'] = copy.deepcopy(geometry)
            self.json_artifact(path, doc)
        self.publish_manifest()

    def test_inside_outside_boundary_and_near_boundary(self):
        for lat,lon,expected in ((.2,.8,'inside'), (.8,.2,'outside'),(.5,.5,'boundary_uncertain'),
                                 (.500001,.5,'boundary_uncertain')):
            result = self.point(lat,lon)
            self.assertEqual(result['status'], 'ok', result)
            record = result['records'][0]
            self.assertEqual(record['point']['relation'], expected)
            self.assertIn('outside does not mean safe', record['point']['interpretation'])
            self.assertEqual(record['evidence']['scenario']['gauge_id'], 'NOAA-HEAC1')

    def test_invalid_coordinates_rejected_before_dataset_access(self):
        with patch.object(c, 'Catalog', side_effect=AssertionError('dataset read')):
            for lat,lon in ((True,1),('0',1),(91,1),(0,181),(float('nan'),0),(0,float('inf'))):
                with self.assertRaises(ValueError):
                    self.point(lat,lon)

    def test_unknown_and_ambiguous_scenarios_no_point(self):
        self.assertEqual(f.scenario_at_coordinate(c.SOURCE,'missing',0,0,config=self.config)['status'],'unknown')
        self.rows.append(dict(self.rows[0]))
        self.publish()
        self.assertEqual(self.point()['status'],'ambiguous')

    def test_datum_gap_prevents_geometry_claim(self):
        self.source_rows[0].pop('vertical_reference')
        self.publish()
        result = self.point()
        self.assertEqual(result['status'],'ineligible')
        self.assertNotIn('point',result['records'][0])

    def test_invalid_empty_unclosed_and_three_dimensional_geometry(self):
        examples = [dict(type='Polygon',coordinates=[]),
            dict(type='Polygon',coordinates=[[[0,0],[1,1],[0,1],[1,0],[0,0]]]),
            dict(type='Polygon',coordinates=[[[0,0],[1,0],[1,1],[0,1]]]),
            dict(type='Polygon',coordinates=[[[0,0,0],[1,0,0],[1,1,0],[0,0,0]]])]
        for geometry in examples:
            self.change_geometry(geometry)
            self.assertEqual(self.point()['status'],'ineligible')

    def test_crs_and_antimeridian_are_explicitly_rejected(self):
        polygon = dict(type='Polygon', coordinates=[[[0,0],[1,0],[1,1],[0,0]]])
        self.change_geometry(polygon, crs={'type':'name','properties':{'name':'EPSG:3857'}})
        self.assertIn('geometry:geometry_crs_unsupported', self.point()['records'][0]['reasons'])
        self.publish()
        polygon['coordinates'] = [[[179,0],[-179,0],[-179,1],[179,0]]]
        self.change_geometry(polygon)
        self.assertIn('geometry:geometry_antimeridian_unsupported',self.point()['records'][0]['reasons'])

    def test_nested_crs_cannot_override_the_collection_coordinate_system(self):
        for location in ('feature', 'geometry'):
            self.publish()
            path = self.footprint
            document = json.loads(gzip.decompress((self.folder/path).read_bytes()))
            feature = document['features'][0]
            target = feature if location == 'feature' else feature['geometry']
            target['crs'] = {'type': 'name', 'properties': {'name': 'EPSG:3857'}}
            self.json_artifact(path, document)
            self.publish_manifest()
            self.assertEqual(self.point()['status'], 'ineligible')

    def test_missing_indexes_are_unavailable_not_unknown(self):
        self.manifest['files'].pop(self.index)
        self.publish_manifest()
        self.assertEqual(self.point()['status'], 'unavailable')

    def test_changed_or_repaired_footprint_not_silently_admitted(self):
        self.change_geometry(dict(type='Polygon', coordinates=[[[0,0],[2,0],[2,2],[0,0]]]), originals=False)
        self.assertIn('geometry:geometry_derivation_unreviewed', self.point()['records'][0]['reasons'])

    def test_geometry_dependency_failure_leaves_catalog_discovery(self):
        with patch.object(g, 'dependencies', side_effect=d.EvidenceError('geometry_dependency_unavailable')):
            self.assertEqual(f.coverage(config=self.config)['total'],2)
            self.assertIn('geometry:geometry_dependency_unavailable', self.point()['records'][0]['reasons'])

    def test_vertex_operation_and_time_limits(self):
        for name,value in (('MAX_VERTICES',4),('MAX_OPERATIONS',0)):
            with patch.object(g,name,value):
                self.assertEqual(self.point()['status'],'ineligible')
        with patch.object(d,'VERIFY_SECONDS',-1):
            self.assertEqual(self.point()['status'],'limit')

    def test_originals_and_active_pointer_unchanged_by_queries(self):
        before = {str(p):p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        with patch('socket.create_connection',side_effect=AssertionError('network')):
            self.assertEqual(self.point()['status'],'ok')
            self.assertEqual(f.stage_scenarios('NOAA-HEAC1','22','FT',config=self.config)['status'],'ok')
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.base.rglob('*') if p.is_file()})

    def test_source_replacement_during_point_operation_is_rejected(self):
        original = g.point_result
        def replace(*args,**kwargs):
            result = original(*args,**kwargs)
            (self.folder/'inputs/catfim_2.geojson.gz').write_bytes(b'changed')
            return result
        with patch.object(g,'point_result',side_effect=replace):
            self.assertEqual(self.point()['status'],'unavailable')

    def test_missing_library_and_dependency_pin_are_unavailable(self):
        (self.folder/self.footprint).unlink()
        self.assertEqual(self.point()['status'],'ineligible')
        self.publish()
        self.manifest['basin_source']['snapshot_id']='other'
        self.publish_manifest()
        self.assertEqual(self.point()['status'],'ineligible')

    def test_isolated_library_originals_preserve_legacy_queries(self):
        prefix = 'libraries/reviewed_001/'
        for path in ('inputs/catfim_2.geojson.gz','raw/gauge_HEAC1.json.gz'):
            self.artifact(prefix+path,(self.folder/path).read_bytes())
        self.rows[0]['source_prefix']=prefix
        self.rows[1]['source_prefix']=''
        self.csv_artifact(self.index,self.rows,list(self.rows[0]))
        self.features(self.footprint,self.rows)
        self.publish_manifest()
        self.assertEqual(self.point()['status'],'ok')
        self.assertEqual(f.scenario(c.SOURCE,'HEAC1_s23',config=self.config)['status'],'ok')
        bracket=f.stage_scenarios('NOAA-HEAC1','22','FT',config=self.config)
        self.assertEqual(bracket['status'],'ineligible')
        self.assertEqual([r['id'] for r in bracket['records']], ['HEAC1_s21','HEAC1_s23'])

    def test_source_prefix_traversal_and_mismatched_properties_rejected(self):
        self.rows[0]['source_prefix']='../outside/'
        self.rows[1]['source_prefix']=''
        self.csv_artifact(self.index,self.rows,list(self.rows[0]))
        self.publish_manifest()
        self.assertEqual(self.point()['status'],'ineligible')

    def test_output_limits_withhold_complete_point_result(self):
        with patch.object(f,'MAX_RESULT_BYTES',100):
            result=self.point()
            self.assertEqual(result['status'],'limit')
            self.assertEqual(result['records'],[])


if __name__ == '__main__':
    unittest.main()
