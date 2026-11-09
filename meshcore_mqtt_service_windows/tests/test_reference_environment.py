"""Synthetic B03-B07 reference contracts; no staged source installation or admission."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import unittest
import uuid
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from pyproj import CRS, Transformer
from shapely.geometry import box

from scripts import reference_catalog as ref, reference_environment as env, reference_policy as policy
from scripts import dataset_paths, flood_readiness_data, satellite_terrain


class EnvironmentReferences(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.gettempdir()) / ('environment-reference-' + uuid.uuid4().hex)
        self.root = self.base / policy.DIRECTORY
        self.root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.base))
        self.document = dict(schema_version=1, kind='restricted_reference_catalog',
                             generation='synthetic-01', complete=True, entries={})
        self.x, self.y = Transformer.from_crs(4326, 26910, always_xy=True).transform(-123, 39)
        self.transform = from_origin(self.x, self.y, 1, 1)
        self.terrain('B03', units=None, vertical=None)
        self.terrain('B04', units='metre', vertical=None)
        self.grid()
        self.soils()
        self.hydro()
        self.publish()

    def entry(self, batch, path, crs, **fields):
        kind, use, _ = ref.USES[batch]
        entry = dict(kind=kind, allowed_uses=[use],
                     prohibited_uses=['flood_modelling', 'satellite_terrain', 'operational_fallback'],
                     source='synthetic-' + batch, version='fixture', source_date='2025-01-08',
                     horizontal_crs=crs, coverage_note='Fixture footprint only; incomplete statewide coverage.', **fields)
        if path:
            entry['path'] = path
        self.document['entries'][batch] = entry
        return entry

    def terrain(self, batch, *, units, vertical, value=12.25):
        path = self.root / (batch + '.tif')
        crs = 'EPSG:26910' + ('+5703' if vertical else '')
        with rasterio.open(path, 'w', driver='GTiff', width=4, height=4, count=1,
                           dtype='float32', crs=crs, transform=self.transform, nodata=-999999) as ds:
            ds.write(np.full((4, 4), value, dtype='float32'), 1)
            if units:
                ds.set_band_unit(1, units)
            bounds = list(ds.bounds)
        self.entry(batch, None, 'EPSG:26910', tiles={'tile_01': dict(path=path.name, bounds=bounds,
                   units=units, vertical_datum=vertical, collection_date=None)})

    def grid(self, order='<', values=(1, 2, 3, 4)):
        (self.root / 'geoid.bin').write_bytes(struct.pack(order + '4d3i', 38, 236, 1, 1, 2, 2, 1)
                                            + struct.pack(order + '4f', *values))
        entry = self.entry('B05', 'geoid.bin', 'EPSG:6318', units='m')
        entry['version'] = 'GEOID18'

    def soils(self):
        path = self.root / 'soil.gpkg'
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript('''
                CREATE TABLE mapunit(mukey INTEGER,musym TEXT,muname TEXT,mukind TEXT,mustatus TEXT);
                INSERT INTO mapunit VALUES(12,'001','Recorded soil','Consociation','Recorded');
                INSERT INTO mapunit VALUES(13,'002','Other soil',NULL,NULL);
                CREATE TABLE component(mukey INTEGER,cokey INTEGER,compname TEXT,compkind TEXT,
                    majcompflag TEXT,hydgrp TEXT,drainagecl TEXT,comppct_l INTEGER,comppct_r INTEGER,comppct_h INTEGER);
                INSERT INTO component VALUES(12,21,'Alpha','Series','Yes','B','Well drained',30,50,70);
                INSERT INTO component VALUES(12,22,'Beta','Series','No',NULL,NULL,NULL,20,NULL);
                INSERT INTO component VALUES(13,23,'Gamma','Series','Yes','C',NULL,100,100,100);
                CREATE INDEX component_parent ON component(mukey);
                CREATE TABLE mdstattabcols(tabphyname TEXT,colphyname TEXT,uom TEXT);
                CREATE TABLE mupolygon(objectid INTEGER PRIMARY KEY,shape BLOB,areasymbol TEXT,musym TEXT,mukey INTEGER);
                CREATE VIRTUAL TABLE rtree_mupolygon_shape USING rtree(id,minx,maxx,miny,maxy);
                CREATE TABLE gpkg_geometry_columns(table_name TEXT,column_name TEXT,geometry_type_name TEXT,srs_id INTEGER);
                INSERT INTO gpkg_geometry_columns VALUES('mupolygon','shape','MULTIPOLYGON',4326);
                CREATE TABLE gpkg_spatial_ref_sys(srs_id INTEGER,organization TEXT,organization_coordsys_id INTEGER);
                INSERT INTO gpkg_spatial_ref_sys VALUES(4326,'EPSG',4326);
            ''')
            columns = env.DEPTH_FIELDS + tuple(p + s for p in ('ksat', 'awc') for s in ('_l', '_r', '_h'))
            db.execute('CREATE TABLE chorizon(cokey INTEGER,chkey INTEGER,hzname TEXT,' +
                       ','.join(c + ' REAL' for c in columns) + ')')
            db.execute('INSERT INTO chorizon VALUES(' + ','.join('?' for _ in range(15)) + ')',
                       (21, 31, 'A', 0, 1, 2, 10, 20, 30, .1, .5, 1, None, .2, .3))
            db.execute('CREATE INDEX horizon_parent ON chorizon(cokey)')
            for field in columns:
                unit = ('centimeters' if field.startswith('hz') else
                        'micrometers per second' if field.startswith('ksat') else 'centimeters per centimeter')
                db.execute('INSERT INTO mdstattabcols VALUES(?,?,?)', ('chorizon', field, unit))
            for field in ('comppct_l', 'comppct_r', 'comppct_h'):
                db.execute('INSERT INTO mdstattabcols VALUES(?,?,?)', ('component', field, 'percent'))
            self.polygon(db, 'mupolygon', 'shape', 1, 4326, box(-124, 38, -122, 40),
                         ('areasymbol', 'musym', 'mukey'), ('CA001', '001', 12))
        self.entry('B06', path.name, 'EPSG:4326')

    def hydro(self):
        path = self.root / 'hydro.gpkg'
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript('''
                CREATE TABLE gpkg_geometry_columns(table_name TEXT,column_name TEXT,geometry_type_name TEXT,srs_id INTEGER);
                CREATE TABLE gpkg_spatial_ref_sys(srs_id INTEGER,organization TEXT,organization_coordsys_id INTEGER);
                INSERT INTO gpkg_spatial_ref_sys VALUES(4269,'EPSG',4269);
            ''')
            for layer, fields in env.HYDRO_FIELDS.items():
                columns = []
                for field in fields:
                    kind = ('INTEGER PRIMARY KEY' if field == 'OBJECTID' else 'REAL'
                            if field in ('NHDPlusID', 'LengthKM', 'AreaSqKm') else 'TEXT')
                    columns.append('"' + field + '" ' + kind)
                db.execute(f'CREATE TABLE {layer}(' + ','.join(columns) + ',SHAPE BLOB)')
                if layer != 'NHDFlowline':
                    db.execute(f'CREATE VIRTUAL TABLE rtree_{layer}_SHAPE USING rtree(id,minx,maxx,miny,maxy)')
                    db.execute('INSERT INTO gpkg_geometry_columns VALUES(?,?,?,?)', (layer, 'SHAPE', 'MULTIPOLYGON', 4269))
            values = (1, '001-permanent', 50000400000045, '0000000123', 'Same name', '00123456789012',
                      '2020-01-02', 1.25, '1', 'With digitized', '460', '46006', 'Perennial', '1801')
            db.execute('INSERT INTO NHDFlowline VALUES(' + ','.join('?' for _ in range(15)) + ')', values + (None,))
            self.polygon(db, 'NHDPlusCatchment', 'SHAPE', 1, 4269, box(-124, 38, -122, 40),
                         ('NHDPlusID', 'SourceFC', 'GridCode', 'AreaSqKm', 'VPUID'),
                         (50000400000045, 'NHDPlusBurnLineEvent', '1', 2.5, '1801'))
        self.entry('B07', path.name, 'EPSG:4269')

    @staticmethod
    def polygon(db, layer, geom, identity, epsg, geometry, fields, values):
        blob = b'GP\x00\x01' + struct.pack('<i', epsg) + geometry.wkb
        db.execute(f'INSERT INTO {layer}(objectid,{geom},' + ','.join(fields) + ') VALUES(' +
                   ','.join('?' for _ in range(len(values) + 2)) + ')', (identity, blob, *values))
        west, south, east, north = geometry.bounds
        db.execute(f'INSERT INTO rtree_{layer}_{geom} VALUES(?,?,?,?,?)', (identity, west, east, south, north))

    def edit_db(self, batch, sql, params=()):
        with closing(sqlite3.connect(self.root / self.document['entries'][batch]['path'])) as db, db:
            db.execute(sql, params)
        self.publish()

    def publish(self):
        for batch, entry in self.document['entries'].items():
            pins = entry['tiles'].values() if batch in ('B03', 'B04') else [entry]
            for pin in pins:
                path = self.root / pin['path']
                pin.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.write_catalog()

    def write_catalog(self):
        (self.root / policy.CATALOG).write_text(json.dumps(self.document), encoding='utf-8')

    def reader(self):
        return ref.Catalog(self.root)

    def terrain_point(self):
        lon, lat = Transformer.from_crs(26910, 4326, always_xy=True).transform(self.x + .5, self.y - .5)
        return lat, lon

    def test_discovery_and_overlap_preserve_both_identities(self):
        result = self.reader().elevation_tiles(*self.terrain_point())
        self.assertEqual([r['batch'] for r in result['records']], ['B03', 'B04'])
        self.assertTrue(all(r['integrity'] == 'not_checked' for r in result['records']))
        self.assertEqual(self.reader().elevation(*self.terrain_point())['status'], 'ambiguous')
        self.assertEqual(self.reader().elevation_tiles(0, 0)['status'], 'outside_declared_coverage')

    def test_terrain_units_and_datum_gaps_never_return_height(self):
        for batch, reason in [('B03', 'elevation_units_unresolved'), ('B04', 'vertical_datum_unresolved')]:
            with self.subTest(batch=batch):
                r = self.reader().elevation(*self.terrain_point(), batch=batch, tile_id='tile_01')
                self.assertEqual(r['reason'], reason)
                self.assertNotIn('elevation_m', r)
                self.assertIsNone(r['collection_date'])

    def test_qualified_native_elevation_and_nodata(self):
        for value, status in [(12.25, 'ok'), (-999999, 'unavailable'), (float('nan'), 'unavailable')]:
            with self.subTest(value=value):
                self.terrain('B04', units='metre', vertical='EPSG:5703', value=value)
                self.publish()
                r = self.reader().elevation(*self.terrain_point(), batch='B04')
                self.assertEqual(r['status'], status)
                if status == 'ok':
                    self.assertEqual(r['elevation_m'], 12.25)
                    self.assertFalse(r['model_eligible'])
                    self.assertIn('no height conversion', r['qualification'])

    def test_terrain_exact_selection_and_outside(self):
        self.assertEqual(self.reader().elevation(0, 0, batch='B03', tile_id='tile_01')['status'], 'outside_coverage')
        self.assertEqual(self.reader().elevation(39, -123, batch='B03', tile_id='missing')['status'], 'unknown')
        for kwargs in ({'tile_id': 'tile_01'}, {'batch': 'B02'}, {'batch': 'B03', 'tile_id': 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.reader().elevation(39, -123, **kwargs)

    def test_terrain_pin_bounds_and_crs_must_match_payload(self):
        tile = self.document['entries']['B03']['tiles']['tile_01']
        tile['bounds'][0] -= 1
        self.write_catalog()
        with self.assertRaisesRegex(ValueError, 'incompatible_elevation_raster'):
            self.reader().elevation(*self.terrain_point(), batch='B03', tile_id='tile_01')
        self.document['entries']['B03']['horizontal_crs'] = 'EPSG:4326'
        self.write_catalog()
        with self.assertRaisesRegex(ValueError, 'incompatible_elevation_crs'):
            self.reader().elevation_tiles(39, -123)

    def test_tile_inventory_validation_and_limits(self):
        original = copy.deepcopy(self.document)
        for kind in ('duplicates', 'count', 'bounds', 'metadata', 'path'):
            self.document = copy.deepcopy(original)
            tiles = self.document['entries']['B03']['tiles']
            if kind == 'duplicates':
                tiles['alias'] = copy.deepcopy(tiles['tile_01'])
            elif kind == 'count':
                tiles.update({f'other{i}': tiles['tile_01'] for i in range(ref.MAX_TILES)})
            elif kind == 'bounds':
                tiles['tile_01']['bounds'] = [0, 0, 0, 1]
            elif kind == 'metadata':
                del tiles['tile_01']['units']
            else:
                tiles['tile_01']['path'] = '../escape.tif'
            self.write_catalog()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.reader()

    def test_collection_specific_size_limits(self):
        for batch, limit in ref.ENVIRONMENT_LIMITS.items():
            entry = self.document['entries'][batch]
            original = entry['bytes']
            entry['bytes'] = limit
            self.write_catalog()
            self.reader().discover()
            entry['bytes'] += 1
            self.write_catalog()
            with self.subTest(batch=batch), self.assertRaisesRegex(ValueError, 'invalid_artifact_pin'):
                self.reader()
            entry['bytes'] = original

    def test_geoid_byte_order_orientation_and_nearest_node(self):
        for order in ('<', '>'):
            self.grid(order)
            self.publish()
            for point, expected in [((38, -124), 1), ((38, -123), 2), ((39, -124), 3), ((39, -123), 4), ((38.6, -123.6), 3)]:
                with self.subTest(order=order, point=point):
                    r = self.reader().geoid(*point, coordinate_crs='EPSG:6318')
                    self.assertEqual(r['geoid_undulation_m'], expected)
                    self.assertFalse(r['interpolated'])
                    self.assertIn('no datum or height conversion', r['interpretation'])

    def test_geoid_requires_explicit_reference_and_valid_coordinates(self):
        for crs in ('EPSG:4326', None, 'NAD83'):
            with self.subTest(crs=crs), self.assertRaisesRegex(ValueError, 'explicit_nad83'):
                self.reader().geoid(38, -124, coordinate_crs=crs)
        for coords in ((True, -124), (float('nan'), 0), (91, 0), (0, 181)):
            with self.subTest(coords=coords), self.assertRaisesRegex(ValueError, 'invalid_coordinates'):
                self.reader().geoid(*coords, coordinate_crs='EPSG:6318')
        self.assertEqual(self.reader().geoid(40, -124, coordinate_crs='EPSG:6318')['status'], 'outside_coverage')

    def test_geoid_nonfinite_invalid_header_and_metadata(self):
        self.grid(values=(float('nan'), 2, 3, 4))
        self.publish()
        self.assertEqual(self.reader().geoid(38, -124, coordinate_crs='EPSG:6318')['status'], 'unavailable')
        path = self.root / 'geoid.bin'
        raw = bytearray(path.read_bytes())
        raw[40:44] = struct.pack('<i', 2)
        path.write_bytes(raw)
        self.publish()
        with self.assertRaisesRegex(ValueError, 'invalid_geoid_byte_order'):
            self.reader().geoid(38, -124, coordinate_crs='EPSG:6318')
        self.grid()
        self.document['entries']['B05']['units'] = 'feet'
        self.publish()
        with self.assertRaisesRegex(ValueError, 'incompatible_geoid_metadata'):
            self.reader().geoid(38, -124, coordinate_crs='EPSG:6318')

    def test_soil_exact_identity_unknown_and_ambiguity(self):
        self.assertEqual(self.reader().soil_map_unit('12')['records'][0]['musym'], '001')
        self.assertEqual(self.reader().soil_map_unit('99')['status'], 'unknown')
        for key in ('012', 12, '-1', ' 12', '1e1', '12 OR 1=1'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'exact_decimal'):
                self.reader().soil_map_unit(key)
        self.edit_db('B06', 'INSERT INTO mapunit SELECT * FROM mapunit WHERE mukey=12')
        with self.assertRaisesRegex(ValueError, 'ambiguous_source_identity'):
            self.reader().soil_map_unit('12')

    def test_soil_components_horizons_and_source_units(self):
        r = self.reader().soil_components('12')
        self.assertEqual([v['cokey'] for v in r['records']], ['21', '22'])
        self.assertEqual(r['field_units']['comppct_r'], 'percent')
        self.assertIsNone(r['records'][1]['hydgrp'])
        self.assertEqual(self.reader().soil_horizons('12', '21')['records'][0]['chkey'], '31')
        for property, unit in [('ksat', 'micrometers per second'), ('awc', 'centimeters per centimeter')]:
            r = self.reader().soil_horizon('12', '21', '31', property=property)
            self.assertEqual(r['field_units'][property + '_r'], unit)
            self.assertEqual(r['field_units']['hzdepb_r'], 'centimeters')
            self.assertIn('not current saturation', r['qualification'])
            self.assertFalse(r['model_eligible'])
        self.assertIsNone(r['records'][0]['awc_l'])

    def test_soil_parent_mismatch_and_unknown_selectors(self):
        for method, args in [('soil_horizons', ('13', '21')), ('soil_horizon', ('13', '21', '31')),
                             ('soil_horizon', ('12', '22', '31'))]:
            kwargs = {'property': 'ksat'} if method == 'soil_horizon' else {}
            with self.subTest(method=method, args=args):
                self.assertEqual(getattr(self.reader(), method)(*args, **kwargs)['status'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'explicit_supported_soil_property'):
            self.reader().soil_horizon('12', '21', '31', property='saturation')

    def test_soil_missing_conflicting_units_and_long_fields(self):
        self.edit_db('B06', "DELETE FROM mdstattabcols WHERE colphyname='ksat_r'")
        with self.assertRaisesRegex(ValueError, 'source_units_unavailable'):
            self.reader().soil_horizon('12', '21', '31', property='ksat')
        self.edit_db('B06', "INSERT INTO mdstattabcols SELECT * FROM mdstattabcols WHERE colphyname='comppct_r'")
        with self.assertRaisesRegex(ValueError, 'source_units_unavailable_or_conflicting'):
            self.reader().soil_components('12')
        self.edit_db('B06', 'UPDATE mapunit SET muname=? WHERE mukey=12', ('x' * 513,))
        with self.assertRaisesRegex(ValueError, 'unsupported_reference_value'):
            self.reader().soil_map_unit('12')

    def test_soil_partial_results_are_stable_and_disclosed(self):
        with closing(sqlite3.connect(self.root / 'soil.gpkg')) as db, db:
            for key in range(100, 140):
                db.execute('INSERT INTO component SELECT mukey,?,compname,compkind,majcompflag,hydgrp,drainagecl,comppct_l,comppct_r,comppct_h FROM component WHERE cokey=21', (key,))
        self.publish()
        r = self.reader().soil_components('12')
        self.assertEqual(r['status'], 'partial')
        self.assertTrue(r['partial'])
        self.assertEqual(len(r['records']), env.MAX_ROWS)
        self.assertEqual(r['records'][0]['cokey'], '21')

    def test_conflicting_component_and_horizon_parents_are_not_selected(self):
        self.edit_db('B06', "INSERT INTO component SELECT 13,cokey,compname,compkind,majcompflag,hydgrp,drainagecl,comppct_l,comppct_r,comppct_h FROM component WHERE cokey=21")
        with self.assertRaisesRegex(ValueError, 'ambiguous_source_identity'):
            self.reader().soil_horizons('12', '21')
        self.edit_db('B06', 'DELETE FROM component WHERE mukey=13 AND cokey=21')
        fields = env.DEPTH_FIELDS + tuple(p + s for p in ('ksat', 'awc') for s in ('_l', '_r', '_h'))
        self.edit_db('B06', 'INSERT INTO chorizon SELECT 22,chkey,hzname,' + ','.join(fields) + ' FROM chorizon')
        with self.assertRaisesRegex(ValueError, 'ambiguous_source_identity'):
            self.reader().soil_horizon('12', '21', '31', property='ksat')

    def test_contradictory_ranges_and_units_are_not_accepted(self):
        for value in ('invalid', -1, 99):
            self.edit_db('B06', 'UPDATE chorizon SET ksat_l=?', (value,))
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'invalid_source_range'):
                self.reader().soil_horizon('12', '21', '31', property='ksat')
        self.edit_db('B06', 'UPDATE chorizon SET ksat_l=.1')
        self.edit_db('B06', "UPDATE mdstattabcols SET uom='different units' WHERE colphyname='ksat_r'")
        with self.assertRaisesRegex(ValueError, 'source_range_units_conflicting'):
            self.reader().soil_horizon('12', '21', '31', property='ksat')

    def test_soil_lists_reject_missing_and_duplicate_followup_keys(self):
        for table, key, query in [('component', 'cokey', lambda: self.reader().soil_components('12')),
                                  ('chorizon', 'chkey', lambda: self.reader().soil_horizons('12', '21'))]:
            for fault in ('missing', 'duplicate'):
                with self.subTest(table=table, fault=fault):
                    path = self.root / 'soil.gpkg'
                    original = path.read_bytes()
                    try:
                        if fault == 'missing':
                            self.edit_db('B06', f'UPDATE {table} SET {key}=NULL')
                        else:
                            self.edit_db('B06', f'INSERT INTO {table} SELECT * FROM {table} LIMIT 1')
                        with self.assertRaisesRegex(ValueError, 'missing_source_identity|ambiguous_source_identity'):
                            query()
                    finally:
                        path.write_bytes(original)
                        self.publish()

    def test_soil_depths_must_not_be_inverted_or_have_incompatible_units(self):
        self.edit_db('B06', 'UPDATE chorizon SET hzdept_l=40,hzdept_r=50,hzdept_h=60')
        for method, args, kwargs in [('soil_horizons', ('12', '21'), {}),
                                     ('soil_horizon', ('12', '21', '31'), {'property': 'ksat'})]:
            with self.subTest(method=method), self.assertRaisesRegex(ValueError, 'invalid_source_depths'):
                getattr(self.reader(), method)(*args, **kwargs)
        self.edit_db('B06', 'UPDATE chorizon SET hzdept_l=0,hzdept_r=1,hzdept_h=2')
        self.edit_db('B06', "UPDATE mdstattabcols SET uom='meters' WHERE colphyname LIKE 'hzdepb_%'")
        with self.assertRaisesRegex(ValueError, 'source_depth_units_conflicting'):
            self.reader().soil_horizons('12', '21')

    def test_component_percentages_require_percent_units_and_valid_bounds(self):
        self.edit_db('B06', 'UPDATE component SET comppct_h=101 WHERE cokey=21')
        with self.assertRaisesRegex(ValueError, 'invalid_source_percentage'):
            self.reader().soil_components('12')
        self.edit_db('B06', 'UPDATE component SET comppct_h=70 WHERE cokey=21')
        self.edit_db('B06', "UPDATE mdstattabcols SET uom='acres' WHERE tabphyname='component'")
        with self.assertRaisesRegex(ValueError, 'source_percentage_units_conflicting'):
            self.reader().soil_components('12')

    def test_spatial_hydrography_preserves_measurement_units(self):
        result = self.reader().hydro_at(39, -123, layer='NHDPlusCatchment')
        self.assertEqual(result['field_units'], {'AreaSqKm': 'km2'})
        self.assertEqual(result['records'][0]['AreaSqKm'], 2.5)

    def test_waterbody_identity_and_containment_preserve_source_fields(self):
        fields = env.HYDRO_FIELDS['NHDWaterbody'][1:]
        with closing(sqlite3.connect(self.root / 'hydro.gpkg')) as db, db:
            self.polygon(db, 'NHDWaterbody', 'SHAPE', 7, 4269, box(-124, 38, -122, 40), fields,
                         ('007-waterbody', 50000400000047, '0000000127', 'Recorded waterbody',
                          '00123456789017', '2020-01-02', 3.5, '390', '39004', 'Lake/Pond', '1801'))
        self.publish()
        exact = self.reader().hydro_feature('NHDWaterbody', '007-waterbody', key='Permanent_Identifier')
        spatial = self.reader().hydro_at(39, -123, layer='NHDWaterbody')
        self.assertEqual(exact['records'], spatial['records'])
        self.assertEqual(exact['field_units'], spatial['field_units'])
        self.assertEqual(exact['records'][0]['ReachCode'], '00123456789017')
        self.assertFalse(spatial['model_eligible'])
        with self.assertRaises(policy.ReferenceUseError):
            policy.reject_metadata(spatial)

    def test_valid_overlapping_depth_ranges_and_nulls_remain_recorded(self):
        # Uncertainty intervals may overlap; only corresponding top/bottom values
        # are comparable, and a missing depth must not be filled from another field.
        self.edit_db('B06', 'UPDATE chorizon SET hzdept_l=0,hzdept_r=10,hzdept_h=20,hzdepb_l=5,hzdepb_r=15,hzdepb_h=25')
        r = self.reader().soil_horizon('12', '21', '31', property='awc')
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['records'][0]['hzdept_h'], 20)
        self.edit_db('B06', 'UPDATE chorizon SET hzdept_l=NULL,hzdepb_r=NULL')
        r = self.reader().soil_horizons('12', '21')
        self.assertIsNone(r['records'][0]['hzdept_l'])
        self.assertIsNone(r['records'][0]['hzdepb_r'])

    def test_geoid_header_roundoff_at_outer_node(self):
        (self.root / 'geoid.bin').write_bytes(struct.pack('<4d3i', 38, 236, .1 - 1e-14, .1 - 1e-14, 2, 2, 1)
                                            + struct.pack('<4f', 1, 2, 3, 4))
        self.publish()
        self.assertEqual(self.reader().geoid(38.1, -123.9, coordinate_crs='EPSG:6318')['geoid_undulation_m'], 4)
        self.assertEqual(self.reader().geoid(38.1001, -123.9, coordinate_crs='EPSG:6318')['status'], 'outside_coverage')

    def conus_grid(self, order):
        """Create synthetic corner values with the staged GEOID18 CONUS header."""
        rows, cols = 2041, 4201
        with (self.root / 'geoid.bin').open('wb') as stream:
            stream.write(struct.pack(order + '4d3i', 24, 230,
                                     .01666666666667, .01666666666665, rows, cols, 1))
            stream.truncate(44 + rows * cols * 4)
            for row, col, value in ((0, 0, 1), (0, cols - 1, 2),
                                    (rows - 1, 0, 3), (rows - 1, cols - 1, 4)):
                stream.seek(44 + (row * cols + col) * 4)
                stream.write(struct.pack(order + 'f', value))
        self.publish()

    def test_geoid_conus_nominal_corners_and_inside_edges(self):
        for order in ('<', '>'):
            self.conus_grid(order)
            for lat, lon, expected in ((24, -130, 1), (24, -60, 2),
                                       (58, -130, 3), (58, -60, 4),
                                       (24 + 1e-8, -130 + 1e-8, 1),
                                       (58 - 1e-8, -60 - 1e-8, 4)):
                with self.subTest(order=order, latitude=lat, longitude=lon):
                    result = self.reader().geoid(lat, lon, coordinate_crs='EPSG:6318')
                    self.assertEqual(result['status'], 'ok')
                    self.assertEqual(result['geoid_undulation_m'], expected)
                    self.assertEqual(result['units'], 'm')
                    # Preserve coordinates from the rounded header, including
                    # its eastern edge, rather than substituting the query.
                    node_latitude = 24 if expected in (1, 2) else 58.0000000000068
                    node_longitude = -130 if expected in (1, 3) else -60.00000000007003
                    self.assertAlmostEqual(result['node_latitude'], node_latitude, places=12)
                    self.assertAlmostEqual(result['node_longitude'], node_longitude, places=12)
                    self.assertEqual(result['sampling'], 'nearest_recorded_node')
                    self.assertFalse(result['interpolated'])
                    self.assertFalse(result['model_eligible'])
                    self.assertIn('no datum or height conversion', result['interpretation'])

    def test_geoid_conus_outside_edges_are_not_clamped(self):
        for order in ('<', '>'):
            self.conus_grid(order)
            # 2e-10 degrees is just beyond the 1e-8-cell roundoff allowance.
            # Also reject larger offsets, including a quarter-cell footprint.
            for delta in (2e-10, 1e-8, 1 / 240):
                for lat, lon in ((24 - delta, -100), (58 + delta, -100),
                                 (40, -130 - delta), (40, -60 + delta)):
                    with self.subTest(order=order, latitude=lat, longitude=lon):
                        result = self.reader().geoid(lat, lon, coordinate_crs='EPSG:6318')
                        self.assertEqual(result['status'], 'outside_coverage')
                        self.assertNotIn('geoid_undulation_m', result)
                        self.assertNotIn('node_latitude', result)
                        self.assertNotIn('node_longitude', result)

    def test_hydro_exact_ids_preserve_zeroes_and_flow_qualification(self):
        for key, identity in [('Permanent_Identifier', '001-permanent'), ('NHDPlusID', '50000400000045'),
                              ('ReachCode', '00123456789012'), ('OBJECTID', '1')]:
            with self.subTest(key=key):
                r = self.reader().hydro_feature('NHDFlowline', identity, key=key)
                self.assertEqual(r['records'][0]['ReachCode'], '00123456789012')
                self.assertEqual(r['records'][0]['NHDPlusID'], '50000400000045')
                self.assertEqual(r['records'][0]['GNIS_ID'], '0000000123')
                self.assertIn('no routing', r['qualification'])
                self.assertEqual(r['field_units']['LengthKM'], 'km')
        self.assertEqual(self.reader().hydro_feature('NHDFlowline', '1-permanent', key='Permanent_Identifier')['status'], 'unknown')

    def test_hydro_requires_layer_key_and_exact_numeric_representation(self):
        for layer, key, identity in [('NHDPlusFlow', 'OBJECTID', '1'), ('NHDFlowline', 'GNIS_Name', 'Same name'),
                                     ('NHDPlusCatchment', 'ReachCode', '00123456789012'),
                                     ('NHDFlowline', 'NHDPlusID', '9007199254740992'),
                                     ('NHDFlowline', 'NHDPlusID', '050000400000045'),
                                     ('NHDFlowline', 'ReachCode', '123456789012')]:
            with self.subTest(layer=layer, key=key, identity=identity), self.assertRaises(ValueError):
                self.reader().hydro_feature(layer, identity, key=key)
        self.edit_db('B07', 'UPDATE NHDFlowline SET NHDPlusID=1.5')
        with self.assertRaisesRegex(ValueError, 'inexact_source_identity'):
            self.reader().hydro_feature('NHDFlowline', '1', key='OBJECTID')

    def test_hydro_duplicate_ids_are_ambiguous_and_separate(self):
        fields = env.HYDRO_FIELDS['NHDFlowline']
        self.edit_db('B07', 'INSERT INTO NHDFlowline(' + ','.join(fields) + ') SELECT 2,' +
                     ','.join(fields[1:]) + ' FROM NHDFlowline')
        r = self.reader().hydro_feature('NHDFlowline', '001-permanent', key='Permanent_Identifier')
        self.assertEqual(r['status'], 'ambiguous')
        self.assertEqual(len(r['records']), 2)

    def test_polygon_containment_and_no_cross_source_relationships(self):
        soil = self.reader().soil_at(39, -123)
        self.assertEqual(soil['records'][0]['mukey'], '12')
        catchment = self.reader().hydro_at(39, -123, layer='NHDPlusCatchment')
        self.assertEqual(catchment['records'][0]['SourceFC'], 'NHDPlusBurnLineEvent')
        self.assertNotIn('downstream', catchment)
        self.assertEqual(self.reader().soil_at(0, 0)['status'], 'outside_coverage')
        with self.assertRaisesRegex(ValueError, 'explicit_supported_polygon_layer'):
            self.reader().hydro_at(39, -123, layer='NHDFlowline')

    def test_boundary_overlap_stays_ambiguous(self):
        with closing(sqlite3.connect(self.root / 'soil.gpkg')) as db, db:
            self.polygon(db, 'mupolygon', 'shape', 2, 4326, box(-122, 38, -121, 40),
                         ('areasymbol', 'musym', 'mukey'), ('CA002', '002', 13))
        self.publish()
        self.assertEqual(self.reader().soil_at(39, -122)['status'], 'ambiguous')

    def test_spatial_index_geometry_and_candidate_limits(self):
        with patch.object(ref, 'MAX_CANDIDATES', 0):
            with self.assertRaisesRegex(ValueError, 'reference_candidate_limit'):
                self.reader().soil_at(39, -123)
        with patch.object(ref, 'MAX_GEOMETRY', 5):
            with self.assertRaisesRegex(ValueError, 'reference_geometry_limit'):
                self.reader().soil_at(39, -123)
        self.edit_db('B06', 'DROP TABLE rtree_mupolygon_shape')
        with self.assertRaisesRegex(ValueError, 'reference_spatial_index_unavailable'):
            self.reader().soil_at(39, -123)

    def test_spatial_crs_mismatch_rejected(self):
        self.edit_db('B07', 'UPDATE gpkg_geometry_columns SET srs_id=4326')
        with self.assertRaisesRegex(ValueError, 'incompatible_reference_geometry_schema'):
            self.reader().hydro_at(39, -123, layer='NHDPlusCatchment')

    def test_sql_work_limit_is_explicit_and_no_partial_success(self):
        with closing(sqlite3.connect(self.root / 'hydro.gpkg')) as db, db:
            for key in range(2, 2001):
                db.execute('INSERT INTO NHDFlowline(OBJECTID,Permanent_Identifier) VALUES(?,?)', (key, 'other'))
        self.publish()
        with patch.object(env, 'MAX_SQL_STEPS', 1000):
            with self.assertRaisesRegex(ValueError, 'reference_database_invalid_or_work_limit'):
                self.reader().hydro_feature('NHDFlowline', 'not-present', key='Permanent_Identifier')

    def test_integrity_missing_payload_and_time_limit(self):
        (self.root / 'geoid.bin').write_bytes(b'x' * 60)
        with self.assertRaisesRegex(ValueError, 'reference_integrity_failure'):
            self.reader().geoid(38, -124, coordinate_crs='EPSG:6318')
        reader = self.reader()
        reader.until = 0
        with self.assertRaisesRegex(ValueError, 'reference_query_time_limit'):
            reader.soil_map_unit('12')
        (self.root / 'soil.gpkg').unlink()
        self.assertEqual(len(self.reader().discover()), 5)
        with self.assertRaises(FileNotFoundError):
            self.reader().soil_map_unit('12')

    def test_all_new_metadata_and_results_block_operational_consumers(self):
        reader = flood_readiness_data.Snapshot({'data_directory': str(self.base)})
        for batch in ('B03', 'B04', 'B05', 'B06', 'B07'):
            kind = ref.USES[batch][0]
            dataset = ('usgs_elevation_' + batch.lower() + '_reference' if batch in ('B03', 'B04') else kind)
            for metadata in ({'kind': kind}, {'dataset': dataset}):
                with self.subTest(metadata=metadata), self.assertRaises(policy.ReferenceUseError):
                    reader.dependency(metadata)
        for record in self.reader().discover():
            with self.assertRaises(policy.ReferenceUseError):
                policy.reject_metadata(record)
        with self.assertRaises(policy.ReferenceUseError):
            dataset_paths.checked_path(self.base, '.reference-only/B03.tif')
        entry = dict(id='ref', path='.reference-only/B03.tif', horizontal_crs='EPSG:26910', vertical_crs='EPSG:5703', source='fixture')
        with self.assertRaises(policy.ReferenceUseError):
            satellite_terrain.sources({'pointing': {'terrain_sources': [entry]}}, self.base)

    def test_reads_do_not_change_files_or_membership(self):
        def fingerprints():
            return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.iterdir()}
        before = fingerprints()
        self.reader().elevation_tiles(*self.terrain_point())
        self.reader().elevation(*self.terrain_point(), batch='B04')
        self.reader().geoid(38, -124, coordinate_crs='EPSG:6318')
        self.reader().soil_map_unit('12')
        self.reader().soil_at(39, -123)
        self.reader().soil_horizon('12', '21', '31', property='ksat')
        self.reader().hydro_feature('NHDFlowline', '1', key='OBJECTID')
        self.reader().hydro_at(39, -123, layer='NHDPlusCatchment')
        self.assertEqual(fingerprints(), before)


if __name__ == '__main__':
    unittest.main()
