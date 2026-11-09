"""Synthetic B10 reference fixtures; no staged or installed datasets are modified."""
import builtins
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from pyproj import CRS, Transformer

from scripts import dataset_paths, flood_readiness_data, reference_catalog as reference
from scripts import reference_policy as policy, satellite_terrain


class ImperviousReferenceTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.gettempdir()) / ('impervious-test-' + uuid.uuid4().hex)
        self.root = self.base / '.reference-only'
        self.root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.base))
        self.path = self.root / 'impervious.tif'
        self.crs = CRS(reference.LAND_COVER_CRS)
        x, y = Transformer.from_crs(4326, self.crs, always_xy=True).transform(-123, 39)
        self.transform = from_origin(x, y, 30, 30)
        values = np.full((64, 64), 75, dtype='uint8')
        values[0, :6] = (0, 100, 250, 101, 255, 37)
        with rasterio.open(self.path, 'w', driver='GTiff', width=64, height=64,
                           count=1, dtype='uint8', crs=self.crs, transform=self.transform, nodata=250) as ds:
            ds.write(values, 1)
            ds.build_overviews([2, 4], Resampling.average)
        self.entry = dict(kind='nlcd_fractional_impervious', allowed_uses=['impervious_reference'],
                          prohibited_uses=['flood_modelling', 'satellite_terrain', 'operational_fallback'],
                          path=self.path.name, source='USGS-Annual-NLCD', version='Collection-1.2-C1V2',
                          source_date='2026-06-30', year=2025, units='percent',
                          horizontal_crs=self.crs.to_wkt(), coverage_note='Synthetic footprint only.')
        self.document = dict(schema_version=1, kind='restricted_reference_catalog',
                             generation='b10-fixture', complete=True, entries={'B10': self.entry})
        self.publish()

    def publish(self):
        """Pin only synthetic bytes; no actual source admission is performed."""
        self.entry.update(bytes=self.path.stat().st_size, sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())
        (self.root / policy.CATALOG).write_text(json.dumps(self.document), encoding='utf-8')

    def point(self, row, col):
        x, y = self.transform * (col + .5, row + .5)
        lon, lat = Transformer.from_crs(self.crs, 4326, always_xy=True).transform(x, y)
        return lat, lon

    def query(self, col=0):
        return reference.Catalog(self.root).impervious_surface(*self.point(0, col))

    def test_zero_hundred_and_intermediate_percent_preserved(self):
        for column, expected in ((0, 0), (1, 100), (5, 37)):
            result = self.query(column)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['percent'], expected)
            self.assertEqual(result['units'], 'percent')
            self.assertEqual(result['year'], 2025)
            self.assertEqual(result['source_date'], '2026-06-30')
            self.assertEqual(result['source'], self.entry['source'])
            self.assertEqual(result['version'], self.entry['version'])
            self.assertEqual(result['coverage_note'], self.entry['coverage_note'])
            self.assertFalse(result['model_eligible'])
            self.assertEqual(result['permitted_use'], 'impervious_reference')
            self.assertIn('not runoff or infiltration', result['qualification'])
            self.assertIn('zero does not imply zero runoff', result['qualification'])

    def test_nodata_is_unavailable_not_zero(self):
        result = self.query(2)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'source_nodata')
        self.assertNotIn('percent', result)
        self.assertEqual(result['year'], 2025)

    def test_internal_mask_cannot_make_declared_nodata_valid(self):
        mask = np.full((64, 64), 255, dtype='uint8')
        mask[0, 0] = 0
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
            with rasterio.open(self.path, 'r+') as ds:
                ds.write_mask(mask)
        self.publish()
        # Internal validity masks supersede GDAL's nodata-derived mask. Both
        # the source sentinel and an explicitly masked zero remain unavailable.
        for column in (0, 2):
            with self.subTest(column=column):
                result = self.query(column)
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['reason'], 'source_nodata')
                self.assertNotIn('percent', result)
        self.assertEqual(self.query(1)['percent'], 100)

    def test_unpinned_external_mask_is_ignored(self):
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
            with rasterio.open(self.path, 'r+') as ds:
                ds.write_mask(np.zeros((64, 64), dtype='uint8'))
        self.assertTrue(Path(str(self.path) + '.msk').is_file())
        self.publish()
        with rasterio.open(self.path) as ds:
            self.assertTrue(ds.read(1, window=rasterio.windows.Window(0, 0, 1, 1), masked=True).mask.all())
        self.assertEqual(self.query()['percent'], 0)

    def test_non_native_dtype_band_count_and_grid_are_rejected(self):
        for dtype, count, transform in (
                ('uint16', 1, self.transform), ('float32', 1, self.transform),
                ('uint8', 2, self.transform),
                ('uint8', 1, self.transform * rasterio.Affine.scale(2)),
                ('uint8', 1, self.transform * rasterio.Affine.rotation(1))):
            with self.subTest(dtype=dtype, count=count, transform=transform):
                with rasterio.open(self.path, 'w', driver='GTiff', width=64, height=64,
                                   count=count, dtype=dtype, crs=self.crs, transform=transform,
                                   nodata=250) as ds:
                    ds.write(np.full((count, 64, 64), 50, dtype=dtype))
                self.publish()
                with self.assertRaisesRegex(ValueError, 'incompatible_impervious_raster'):
                    self.query()

    def test_unexpected_codes_are_not_clamped_or_rescaled(self):
        for col, raw in ((3, 101), (4, 255)):
            result = self.query(col)
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['reason'], 'invalid_source_percentage')
            self.assertEqual(result['raw_code'], raw)
            self.assertNotIn('percent', result)

    def test_native_pixel_ignores_overview_percentage(self):
        with rasterio.open(self.path, overview_level=0) as ds:
            self.assertNotEqual(int(ds.read(1, window=rasterio.windows.Window(0, 0, 1, 1))[0, 0]), 0)
        result = self.query()
        self.assertEqual(result['percent'], 0)
        self.assertEqual(result['resolution_m'], 30)
        self.assertEqual(result['sampling'], 'native_containing_pixel')

    def test_outside_coverage_has_no_percentage(self):
        result = self.query(64)
        self.assertEqual(result['status'], 'outside_coverage')
        self.assertNotIn('percent', result)
        self.assertEqual(result['units'], 'percent')

    def test_coordinates_rejected_before_artifact_io(self):
        reader = reference.Catalog(self.root)
        with patch.object(reader, '_artifact', side_effect=AssertionError('Unexpected artifact IO')):
            for lat, lon in [(True, 0), (float('nan'), 0), (0, float('inf')), (91, 0), (0, -181)]:
                with self.assertRaisesRegex(ValueError, 'invalid_coordinates'):
                    reader.impervious_surface(lat, lon)

    def test_discovery_is_declared_only_without_optional_gis_imports(self):
        original = builtins.__import__
        def without_gis(name, *args, **kwargs):
            if name.split('.')[0] in {'rasterio', 'pyproj', 'shapely', 'numpy'}:
                raise ImportError(name)
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_gis):
            result = reference.Catalog(self.root).discover()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['batch'], 'B10')
        self.assertEqual(result[0]['integrity'], 'not_checked')
        self.assertFalse(result[0]['model_eligible'])

    def test_missing_b10_does_not_fall_back_to_b09(self):
        substitute = dict(self.entry, kind='nlcd_land_cover', allowed_uses=['land_cover_reference'])
        self.document['entries'] = {'B09': substitute}
        (self.root / policy.CATALOG).write_text(json.dumps(self.document))
        with self.assertRaisesRegex(ValueError, 'reference_source_unavailable'):
            self.query()

    def test_catalog_requires_units_vintage_and_restricted_purpose(self):
        for change in ({'units': 'fraction'}, {'units': None}, {'year': 2024}, {'year': True},
                       {'kind': 'nlcd_land_cover'}, {'allowed_uses': ['flood_modelling']},
                       {'prohibited_uses': []}):
            doc = copy.deepcopy(self.document)
            doc['entries']['B10'].update(change)
            (self.root / policy.CATALOG).write_text(json.dumps(doc))
            with self.subTest(change=change), self.assertRaises(ValueError):
                reference.Catalog(self.root)

    def test_unrecognized_membership_remains_unsupported(self):
        self.document['entries']['B12'] = dict(self.entry)
        self.publish()
        with self.assertRaisesRegex(ValueError, 'unsupported_reference_membership'):
            reference.Catalog(self.root)

    def test_corruption_and_removal_fail_without_fallback(self):
        with self.path.open('ab') as f:
            f.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'integrity_failure'):
            self.query()
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.query()

    def test_same_size_corruption_fails_hash_before_decoding(self):
        payload = bytearray(self.path.read_bytes())
        payload[-1] ^= 1
        self.path.write_bytes(payload)
        with patch.object(rasterio, 'open', side_effect=AssertionError('Unverified raster decoded')):
            with self.assertRaisesRegex(ValueError, 'reference_integrity_failure'):
                self.query()

    def test_catalog_change_during_query_is_rejected(self):
        original = reference._project
        def change(*args):
            (self.root / policy.CATALOG).write_text('{}')
            return original(*args)
        with patch.object(reference, '_project', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'changed_during_query'):
                self.query()

    def test_catalog_crs_and_source_projection_must_agree(self):
        self.entry['horizontal_crs'] = 'EPSG:5070'
        self.publish()
        with self.assertRaisesRegex(ValueError, 'incompatible_impervious_raster'):
            self.query()
        with rasterio.open(self.path, 'r+') as ds:
            ds.crs = 'EPSG:5070'
        self.publish()
        with self.assertRaisesRegex(ValueError, 'incompatible_impervious_raster'):
            self.query()

    def test_zero_nodata_and_numeric_scaling_are_incompatible(self):
        for nodata, scale, offset in ((0, 1, 0), (250, .01, 0), (250, 1, 1)):
            with rasterio.open(self.path, 'r+') as ds:
                ds.nodata = nodata
                ds.scales = (scale,)
                ds.offsets = (offset,)
            self.publish()
            with self.assertRaisesRegex(ValueError, 'incompatible_impervious_raster'):
                self.query()

    def test_time_artifact_and_block_limits_remain_enforced(self):
        reader = reference.Catalog(self.root)
        reader.until = 0
        with self.assertRaisesRegex(ValueError, 'time_limit'):
            reader.impervious_surface(*self.point(0, 0))
        with patch.object(reference, 'MAX_ARTIFACT', 1):
            with self.assertRaisesRegex(ValueError, 'invalid_artifact_pin'):
                reference.Catalog(self.root)
        with patch.object(reference, 'MAX_BLOCK', 1):
            with self.assertRaisesRegex(ValueError, 'incompatible_impervious_raster'):
                self.query()

    def test_b10_identity_kind_and_results_rejected_by_operational_consumers(self):
        reader = flood_readiness_data.Snapshot({'data_directory': str(self.base)})
        for metadata in ({'dataset': 'nlcd_impervious_reference'}, {'kind': 'nlcd_fractional_impervious'}, self.query()):
            with self.assertRaises(policy.ReferenceUseError):
                policy.reject_metadata(metadata)
            with self.assertRaises(policy.ReferenceUseError):
                reader.dependency(metadata)
        with self.assertRaises(policy.ReferenceUseError):
            dataset_paths.resolve('nlcd_impervious_reference', self.base / 'ordinary')

    def test_registry_metadata_and_custom_paths_cannot_promote_b10(self):
        registry = {'schema': 1, 'datasets': {'custom': {'active': {
            'path': 'ordinary', 'kind': 'nlcd_fractional_impervious'}}}}
        with patch.object(dataset_paths, 'data_root', return_value=self.base):
            with self.assertRaises(policy.ReferenceUseError):
                dataset_paths.resolve('custom', self.base / 'ordinary', registry_reader=lambda p: registry)
        with self.assertRaises(policy.ReferenceUseError):
            dataset_paths.resolve('custom', self.base / 'ordinary', configured=self.root)

    def test_terrain_direct_calls_and_missing_catalog_cannot_bypass_isolation(self):
        entry = dict(id='b10', path=self.path, units='m', vertical_crs='EPSG:4979',
                     source=self.entry['source'], bytes=self.entry['bytes'], sha256=self.entry['sha256'])
        (self.root / policy.CATALOG).unlink()
        with self.assertRaises(policy.ReferenceUseError):
            satellite_terrain.sources({'pointing': {'terrain_sources': [entry]}}, self.base)
        with self.assertRaises(policy.ReferenceUseError):
            satellite_terrain.sample(entry, 39, -123, {}, float('inf'))
        with self.assertRaises(policy.ReferenceUseError):
            satellite_terrain.fingerprint(self.path, float('inf'))

    def test_queries_leave_files_and_membership_unchanged(self):
        def hashes():
            return {str(p.relative_to(self.base)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.base.rglob('*') if p.is_file()}
        before = hashes()
        reference.Catalog(self.root).discover()
        self.query()
        self.query(2)
        self.assertEqual(before, hashes())


if __name__ == '__main__':
    unittest.main()
