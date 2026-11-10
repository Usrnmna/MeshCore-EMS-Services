"""Synthetic reference-only contracts; no installed source admission or activation."""
import copy
import builtins
from contextlib import closing
import hashlib
import io
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
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from pyproj import CRS, Transformer
from shapely.geometry import box

from scripts import reference_catalog as reference, reference_policy as policy
from scripts import dataset_paths, flood_readiness_data, satellite_terrain

LAND_COVER_CRS = CRS.from_proj4('+proj=aea +lat_1=29.5 +lat_2=45.5 +lat_0=23 +lon_0=-96 +datum=WGS84 +units=m')


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.gettempdir()) / ('reference-test-' + uuid.uuid4().hex)
        self.base.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.base))
        self.root = self.base / policy.DIRECTORY
        self.root.mkdir()
        # Keep an equivalent noncanonical spelling to exercise read interception.
        self.root = self.root / ".." / self.root.name
        self.gpkg = self.root / 'boundaries.gpkg'
        with closing(sqlite3.connect(self.gpkg)) as db, db:
            db.executescript('''
                CREATE TABLE gpkg_geometry_columns(table_name TEXT,column_name TEXT,geometry_type_name TEXT,srs_id INTEGER);
                CREATE TABLE gpkg_spatial_ref_sys(srs_id INTEGER,organization TEXT,organization_coordsys_id INTEGER);
                INSERT INTO gpkg_spatial_ref_sys VALUES(4269,'EPSG',4269);
                INSERT INTO gpkg_geometry_columns VALUES('WBDHU8','geom','POLYGON',4269);
                CREATE TABLE WBDHU8(fid INTEGER PRIMARY KEY,huc8 TEXT,name TEXT,geom BLOB);
                CREATE VIRTUAL TABLE rtree_WBDHU8_geom USING rtree(id,minx,maxx,miny,maxy);
            ''')
        self.add_basin(1, '00123456', 'Recorded basin', box(-124, 38, -122, 40))
        self.tif = self.root / 'landcover.tif'
        x, y = Transformer.from_crs(4326, LAND_COVER_CRS, always_xy=True).transform(-123, 39)
        self.transform = from_origin(x, y, 30, 30)
        values = np.full((64, 64), 41, dtype='uint8')
        values[0, :3] = (11, 250, 99)
        with rasterio.open(self.tif, 'w', driver='GTiff', width=64, height=64, count=1,
                           dtype='uint8', crs=LAND_COVER_CRS, transform=self.transform, nodata=250) as ds:
            ds.write(values, 1)
            ds.build_overviews([2, 4], Resampling.mode)
        forbidden = ['flood_modelling', 'satellite_terrain', 'operational_fallback']
        self.document = dict(schema_version=1, kind='restricted_reference_catalog', generation='fixture-01',
                             complete=True, entries={
            'B08': dict(kind='wbd_boundary', allowed_uses=['boundary_reference'], prohibited_uses=forbidden,
                        path=self.gpkg.name, source='USGS-WBD-HU2-18', version='fixture', source_date='2025-01-08',
                        horizontal_crs='EPSG:4269', coverage_note='Fixture only; not complete California coverage.'),
            'B09': dict(kind='nlcd_land_cover', allowed_uses=['land_cover_reference'], prohibited_uses=forbidden,
                        path=self.tif.name, source='USGS-Annual-NLCD', version='C1V2', source_date='2026-06-30',
                        year=2025, horizontal_crs=LAND_COVER_CRS.to_wkt(), coverage_note='Synthetic footprint only.')})
        self.publish()

    def add_basin(self, fid, huc, name, geometry):
        blob = b'GP\x00\x01' + struct.pack('<i', 4269) + geometry.wkb
        with closing(sqlite3.connect(self.gpkg)) as db, db:
            db.execute('INSERT INTO WBDHU8 VALUES(?,?,?,?)', (fid, huc, name, blob))
            left, bottom, right, top = geometry.bounds
            db.execute('INSERT INTO rtree_WBDHU8_geom VALUES(?,?,?,?,?)', (fid, left, right, bottom, top))

    def publish(self):
        for entry in self.document['entries'].values():
            p = self.root / entry['path']
            entry.update(bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        (self.root / policy.CATALOG).write_text(json.dumps(self.document), encoding='utf-8')

    def point(self, row, col):
        x, y = self.transform * (col + .5, row + .5)
        lon, lat = Transformer.from_crs(LAND_COVER_CRS, 4326, always_xy=True).transform(x, y)
        return lat, lon

    def test_discovery_does_not_verify_or_admit_data(self):
        records = reference.Catalog(self.root).discover()
        self.assertEqual([r['batch'] for r in records], ['B08', 'B09'])
        self.assertTrue(all(not r['model_eligible'] and r['integrity'] == 'not_checked' for r in records))

    def test_internal_mask_does_not_override_land_cover_nodata(self):
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
            with rasterio.open(self.tif, 'r+') as ds:
                ds.write_mask(np.full((64, 64), 255, dtype='uint8'))
        self.publish()
        result = reference.Catalog(self.root).land_cover(*self.point(0, 1))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'source_nodata')
        self.assertNotIn('code', result)

    def test_discovery_requires_no_optional_gis_libraries(self):
        original = builtins.__import__
        def without_gis(name, *args, **kwargs):
            if name.split('.')[0] in {'pyproj', 'rasterio', 'shapely', 'numpy'}:
                raise ImportError(name)
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_gis):
            self.assertEqual(len(reference.Catalog(self.root).discover()), 2)

    def test_source_projection_is_not_relabelled_as_nad83_albers(self):
        self.document['entries']['B09']['horizontal_crs'] = 'EPSG:5070'
        self.publish()
        with self.assertRaisesRegex(ValueError, 'incompatible_land_cover'):
            reference.Catalog(self.root).land_cover(*self.point(0, 0))

    def test_matching_catalog_does_not_make_wrong_source_crs_eligible(self):
        for crs in (CRS('EPSG:4326'), CRS('EPSG:5070'), CRS('EPSG:2226')):
            with self.subTest(crs=crs):
                with rasterio.open(self.tif, 'r+') as ds:
                    ds.crs = crs
                self.document['entries']['B09']['horizontal_crs'] = crs.to_wkt()
                self.publish()
                with self.assertRaisesRegex(ValueError, 'incompatible_land_cover'):
                    reference.Catalog(self.root).land_cover(39, -123)

    def test_wrong_grid_orientation_is_not_native_source(self):
        with rasterio.open(self.tif, 'r+') as ds:
            ds.transform = rasterio.Affine(-30, 0, self.transform.c, 0, 30, self.transform.f)
        self.publish()
        with self.assertRaisesRegex(ValueError, 'incompatible_land_cover'):
            reference.Catalog(self.root).land_cover(39, -123)

    def test_catalog_read_is_bounded_even_if_stat_is_outdated(self):
        payload = b' ' * (reference.MAX_CATALOG + 1) + json.dumps(self.document).encode()
        original = Path.open
        class BoundedStream(io.BytesIO):
            def read(stream, size=-1):
                self.assertGreater(size, 0, 'Catalog read must specify a byte bound')
                self.assertLessEqual(size, reference.MAX_CATALOG + 1)
                return super().read(size)
        def replaced(path, *args, **kwargs):
            if path.resolve() == (self.root / policy.CATALOG).resolve():
                return BoundedStream(payload)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', replaced):
            with self.assertRaisesRegex(ValueError, 'catalog_size_limit'):
                reference.Catalog(self.root)

    def test_growing_artifact_stops_at_declared_byte_bound(self):
        reader = reference.Catalog(self.root)
        expected = self.document['entries']['B08']['bytes']
        original = Path.open
        class GrowingStream(io.BytesIO):
            def read(stream, size=-1):
                self.assertLessEqual(size, expected + 1 - stream.tell(),
                                     'Read exceeded the declared artifact boundary')
                return super().read(size)
        def replaced(path, *args, **kwargs):
            if path.resolve() == self.gpkg.resolve():
                return GrowingStream(b'x' * (expected + 100))
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', replaced):
            with self.assertRaisesRegex(ValueError, 'integrity_failure'):
                reader.basin('00123456')

    def test_exact_huc_preserves_zeroes_and_namespace(self):
        result = reference.Catalog(self.root).basin('00123456')
        self.assertEqual(result['records'][0]['id'], 'WBD:00123456')
        self.assertEqual(result['status'], 'ok')
        self.assertFalse(result['model_eligible'])

    def test_unknown_and_malformed_huc(self):
        self.assertEqual(reference.Catalog(self.root).basin('00123457')['status'], 'unknown')
        for value in (123456, True, '１２３４５６７８', '00123456 OR 1=1', '123'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reference.Catalog(self.root).basin(value)

    def test_duplicate_huc_is_ambiguous(self):
        self.add_basin(2, '00123456', 'Conflicting record', box(-124, 38, -122, 40))
        self.publish()
        self.assertEqual(reference.Catalog(self.root).basin('00123456')['status'], 'ambiguous')

    def test_containment_edges_and_overlapping_records(self):
        self.assertEqual(reference.Catalog(self.root).boundaries(39, -123, level=8)['status'], 'ok')
        self.assertEqual(reference.Catalog(self.root).boundaries(39, -121, level=8)['status'], 'outside_coverage')
        self.add_basin(2, '00999999', 'Second basin', box(-123, 38, -121, 40))
        self.publish()
        with patch.object(reference, '_project', return_value=(-123, 39)):
            result = reference.Catalog(self.root).boundaries(39, -123, level=8)
        self.assertEqual(result['status'], 'ambiguous')
        self.assertEqual(len(result['records']), 2)

    def test_candidate_limit_never_returns_incomplete_match_set(self):
        with patch.object(reference, 'MAX_CANDIDATES', 0):
            with self.assertRaisesRegex(ValueError, 'candidate_limit'):
                reference.Catalog(self.root).boundaries(39, -123, level=8)

    def test_missing_index_and_geometry_limit(self):
        with patch.object(reference, 'MAX_GEOMETRY', 5):
            with self.assertRaisesRegex(ValueError, 'geometry_limit'):
                reference.Catalog(self.root).boundaries(39, -123, level=8)
        with closing(sqlite3.connect(self.gpkg)) as db, db:
            db.execute('DROP TABLE rtree_WBDHU8_geom')
        self.publish()
        with self.assertRaisesRegex(ValueError, 'spatial_index_unavailable'):
            reference.Catalog(self.root).boundaries(39, -123, level=8)

    def test_invalid_geometry_srs_is_not_repaired(self):
        with closing(sqlite3.connect(self.gpkg)) as db, db:
            blob = b'GP\x00\x01' + struct.pack('<i', 4326) + box(-124, 38, -122, 40).wkb
            db.execute('UPDATE WBDHU8 SET geom=?', (blob,))
        self.publish()
        with self.assertRaisesRegex(ValueError, 'geometry_crs'):
            reference.Catalog(self.root).boundaries(39, -123, level=8)

    def test_missing_huc_column_is_explicit_schema_failure(self):
        with closing(sqlite3.connect(self.gpkg)) as db, db:
            db.execute('ALTER TABLE WBDHU8 RENAME COLUMN huc8 TO unsupported')
        self.publish()
        with self.assertRaisesRegex(ValueError, 'unsupported_wbd_schema'):
            reference.Catalog(self.root).basin('00123456')

    def test_long_wbd_field_is_rejected_before_materializing_it(self):
        with closing(sqlite3.connect(self.gpkg)) as db, db:
            db.execute('UPDATE WBDHU8 SET name=?', ('x' * 600,))
        self.publish()
        original = reference._text
        def bounded(value, maximum=500):
            if isinstance(value, str) and value == 'x' * 600:
                self.fail('Oversized SQLite field reached Python')
            return original(value, maximum)
        with patch.object(reference, '_text', side_effect=bounded):
            for query in (lambda c: c.basin('00123456'), lambda c: c.boundaries(39, -123, level=8)):
                with self.assertRaisesRegex(ValueError, 'invalid_reference_metadata'):
                    query(reference.Catalog(self.root))

    def test_native_land_class_overview_is_not_selected(self):
        with rasterio.open(self.tif, overview_level=0) as ds:
            self.assertNotEqual(int(ds.read(1)[0, 0]), 11)
        result = reference.Catalog(self.root).land_cover(*self.point(0, 0))
        self.assertEqual(result['code'], 11)
        self.assertEqual(result['sampling'], 'native_containing_pixel')
        self.assertEqual(result['year'], 2025)
        self.assertFalse(result['model_eligible'])

    def test_nodata_unknown_class_and_outside_no_fallback(self):
        self.assertEqual(reference.Catalog(self.root).land_cover(*self.point(0, 1))['reason'], 'source_nodata')
        result = reference.Catalog(self.root).land_cover(*self.point(0, 2))
        self.assertEqual(result['reason'], 'unrecognized_source_class')
        self.assertEqual(result['raw_code'], 99)
        self.assertEqual(reference.Catalog(self.root).land_cover(*self.point(0, 64))['status'], 'outside_coverage')

    def test_input_validation_and_time_bound(self):
        for coords in ((True, 0), (0, float('nan')), (91, 0), (0, 181)):
            with self.assertRaises(ValueError):
                reference.Catalog(self.root).land_cover(*coords)
        with self.assertRaises(ValueError):
            reference.Catalog(self.root).boundaries(39, -123, level=True)
        reader = reference.Catalog(self.root)
        reader.until = 0
        with self.assertRaisesRegex(ValueError, 'time_limit'):
            reader.basin('00123456')

    def test_missing_policy_and_unknown_membership_fail_closed(self):
        for edit in (lambda d: d['entries']['B08'].pop('allowed_uses'),
                     lambda d: d['entries']['B08'].update(allowed_uses=['flood_modelling']),
                     lambda d: d.update(schema_version=True),
                     lambda d: d['entries'].update(B12=d['entries']['B09'])):
            doc = copy.deepcopy(self.document)
            edit(doc)
            (self.root / policy.CATALOG).write_text(json.dumps(doc))
            with self.assertRaises(ValueError):
                reference.Catalog(self.root)

    def test_duplicate_catalog_key_and_path_escape(self):
        (self.root / policy.CATALOG).write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            reference.Catalog(self.root)
        self.document['entries']['B08']['path'] = '../outside.gpkg'
        (self.root / policy.CATALOG).write_text(json.dumps(self.document))
        with self.assertRaisesRegex(ValueError, 'escapes'):
            reference.Catalog(self.root)

    def test_integrity_and_missing_artifact_fail_without_other_source(self):
        reader = reference.Catalog(self.root)
        with self.tif.open('ab') as f:
            f.write(b'x')
        with self.assertRaisesRegex(ValueError, 'integrity_failure'):
            reader.land_cover(*self.point(0, 0))
        self.gpkg.unlink()
        with self.assertRaises(FileNotFoundError):
            reference.Catalog(self.root).basin('00123456')

    def test_catalog_mutation_detected(self):
        reader = reference.Catalog(self.root)
        original = reference._project
        def change(*args):
            (self.root / policy.CATALOG).write_text('{}')
            return original(*args)
        with patch.object(reference, '_project', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'changed_during_query'):
                reader.land_cover(*self.point(0, 0))

    def test_crs_mismatch_blocks_both_readers(self):
        for batch, call in (('B08', lambda c: c.basin('00123456')),
                            ('B09', lambda c: c.land_cover(*self.point(0, 0)))):
            self.document['entries'][batch]['horizontal_crs'] = 'EPSG:4326'
            self.publish()
            with self.assertRaises(ValueError):
                call(reference.Catalog(self.root))

    def test_reserved_path_blocked_before_custom_registry_bypass(self):
        with patch.object(dataset_paths, 'data_root', return_value=self.base/'managed'):
            with self.assertRaisesRegex(ValueError, 'reference_only'):
                dataset_paths.resolve('anything', self.base/'fallback', configured=self.root,
                                      registry_reader=lambda p: self.fail('Registry must not be consulted'))

    def test_missing_catalog_still_blocks_operational_paths(self):
        (self.root / policy.CATALOG).unlink()
        with self.assertRaises(FileNotFoundError):
            reference.Catalog(self.root)
        with self.assertRaisesRegex(ValueError, 'reference_only'):
            policy.reject_path(self.tif)

    def test_nested_reference_path_rejected_by_default_path_helper(self):
        with self.assertRaisesRegex(ValueError, 'reference_only'):
            dataset_paths.checked_path(self.base, '.reference-only/landcover.tif')

    def test_registry_metadata_cannot_promote_reference(self):
        (self.base/'ordinary').mkdir()
        registry = {'schema': 1, 'datasets': {'anything': {'active': {
            'path': 'ordinary', 'kind': 'restricted_reference'}}}}
        with patch.object(dataset_paths, 'data_root', return_value=self.base):
            with self.assertRaisesRegex(ValueError, 'reference_only'):
                dataset_paths.resolve('anything', self.base/'fallback', registry_reader=lambda p: registry)

    def test_catalog_external_symlink_rejected(self):
        original = self.root / policy.CATALOG
        outside = self.base / 'outside.json'
        original.rename(outside)
        try:
            original.symlink_to(outside)
        except OSError:
            self.skipTest('Host cannot create file symlinks')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            reference.Catalog(self.root)

    def test_renamed_root_with_marker_and_symlink_alias(self):
        renamed = self.base/'elsewhere'
        self.root.rename(renamed)
        with self.assertRaisesRegex(ValueError, 'reference_only'):
            policy.reject_path(renamed/'landcover.tif')
        alias = self.base/'alias'
        try:
            alias.symlink_to(renamed, target_is_directory=True)
        except OSError:
            self.skipTest('Host cannot create directory symlinks')
        self.addCleanup(alias.unlink)
        with self.assertRaisesRegex(ValueError, 'reference_only'):
            policy.reject_path(alias/'landcover.tif')

    def test_satellite_custom_entry_cannot_consume_reference(self):
        entry = dict(id='ref', path=str(self.tif), bytes=self.tif.stat().st_size,
                     sha256=hashlib.sha256(self.tif.read_bytes()).hexdigest(), units='m',
                     vertical_crs='EPSG:4979', source='incorrect terrain relabelling')
        with self.assertRaisesRegex(ValueError, 'reference_only'):
            satellite_terrain.sources({'pointing': {'terrain_sources': [entry]}}, self.base)
        entry['path'] = self.tif
        with self.assertRaisesRegex(ValueError, 'reference_only'):
            satellite_terrain.sample(entry, 39, -123, {}, float('inf'))
        with self.assertRaisesRegex(ValueError, 'reference_only'):
            satellite_terrain.fingerprint(self.tif, float('inf'))

    def test_readiness_reference_dependency_blocked(self):
        reader = flood_readiness_data.Snapshot({'data_directory': str(self.base)})
        for entry in ({'dataset': 'wbd_reference'}, {'kind': 'restricted_reference'},
                      {'allowed_uses': ['reference_lookup']}, {'purpose_policy': None}):
            with self.subTest(entry=entry), self.assertRaisesRegex(ValueError, 'reference_only'):
                reader.dependency(entry)

    def test_reference_result_and_kind_cannot_be_promoted(self):
        records = reference.Catalog(self.root).discover()
        for metadata in [*records, {'kind': 'wbd_boundary'}, {'kind': 'nlcd_land_cover'}]:
            with self.subTest(metadata=metadata), self.assertRaises(policy.ReferenceUseError):
                policy.reject_metadata(metadata)

    def test_broken_marker_still_denies_operational_access(self):
        renamed = self.base / 'renamed'
        self.root.rename(renamed)
        marker = renamed / policy.CATALOG
        marker.unlink()
        try:
            marker.symlink_to(renamed / 'missing.json')
        except OSError:
            self.skipTest('Host cannot create symlinks')
        with self.assertRaises(policy.ReferenceUseError):
            policy.reject_path(renamed / 'landcover.tif')

    def test_readiness_manifest_policy_cannot_be_overridden_by_review(self):
        reader = flood_readiness_data.Snapshot({'data_directory': str(self.base)})
        manifest = self.base/'manifest.json'
        manifest.write_text('{}')
        entry = {'dataset': 'custom_inputs', 'pointer': 'current.json', 'pin': {}}
        with patch.object(reader, 'resolve', return_value=self.base), patch.object(reader, 'document',
                side_effect=[{'manifest_path': 'manifest.json'}, {'kind': 'restricted_reference'}]):
            with self.assertRaisesRegex(ValueError, 'reference_only'):
                reader.dependency(entry)

    def test_reads_leave_files_and_membership_unchanged(self):
        def hashes():
            return {str(p.relative_to(self.base)):hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.base.rglob('*') if p.is_file()}
        before = hashes()
        reference.Catalog(self.root).basin('00123456')
        reference.Catalog(self.root).boundaries(39, -123, level=8)
        reference.Catalog(self.root).land_cover(*self.point(0, 0))
        self.assertEqual(before, hashes())


if __name__ == '__main__':
    unittest.main()
