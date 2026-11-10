"""Synthetic B11 contracts; staged and installed datasets remain untouched."""
import builtins
import copy
import hashlib
import io
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


class ConfidenceReferenceTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.gettempdir()) / ('confidence-test-' + uuid.uuid4().hex)
        self.root = self.base / policy.DIRECTORY
        self.root.mkdir(parents=True)
        # Keep an equivalent noncanonical spelling to exercise read interception.
        self.root = self.root / ".." / self.root.name
        self.addCleanup(lambda: shutil.rmtree(self.base))
        self.path = self.root / 'confidence.tif'
        self.crs = CRS(reference.LAND_COVER_CRS)
        x, y = Transformer.from_crs(4326, self.crs, always_xy=True).transform(-123, 39)
        self.transform = from_origin(x, y, 30, 30)
        values = np.full((64, 64), 75, dtype='uint8')
        values[0, :10] = (0, 1, 37, 100, 101, 200, 249, 250, 251, 255)
        with rasterio.open(self.path, 'w', driver='GTiff', width=64, height=64,
                           count=1, dtype='uint8', crs=self.crs, transform=self.transform, nodata=250) as ds:
            ds.write(values, 1)
            ds.build_overviews([2, 4], Resampling.average)
        self.entry = dict(kind='nlcd_land_cover_confidence', allowed_uses=['land_cover_confidence_reference'],
                          prohibited_uses=['flood_modelling', 'satellite_terrain', 'operational_fallback'],
                          path=self.path.name, source='USGS-Annual-NLCD', version='Collection-1.2-C1V2',
                          source_date='2026-06-30', year=2025, units='unitless',
                          horizontal_crs=self.crs.to_wkt(), coverage_note='Synthetic footprint only.')
        self.document = dict(schema_version=1, kind='restricted_reference_catalog',
                             generation='b11-fixture', complete=True, entries={'B11': self.entry})
        self.publish()

    def publish(self):
        """Pin a small synthetic TIFF and its explicit reference policy."""
        self.entry.update(bytes=self.path.stat().st_size, sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.write_catalog(self.document)

    def write_catalog(self, document):
        (self.root / policy.CATALOG).write_text(json.dumps(document), encoding='utf-8')

    def point(self, col):
        x, y = self.transform * (col + .5, .5)
        lon, lat = Transformer.from_crs(self.crs, 4326, always_xy=True).transform(x, y)
        return lat, lon

    def query(self, col=0):
        return reference.Catalog(self.root).land_cover_confidence(*self.point(col))

    def test_unitless_scores_identity_and_qualifications(self):
        for col, score in ((1, 1), (2, 37), (3, 100)):
            result = self.query(col)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['confidence_score'], score)
            self.assertEqual(result['raw_code'], score)
            for field in ('year', 'units', 'source', 'version', 'source_date', 'coverage_note'):
                self.assertEqual(result[field], self.entry[field])
            self.assertFalse(result['model_eligible'])
            self.assertEqual(result['permitted_use'], 'land_cover_confidence_reference')
            self.assertIn('not calibrated probability', result['qualification'])
            self.assertIn('impervious-surface confidence', result['qualification'])
            self.assertNotIn('percent', result)

    def test_zero_is_unresolved_not_score_or_nodata(self):
        result = self.query()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'unresolved_zero_code')
        self.assertEqual(result['raw_code'], 0)
        self.assertNotIn('confidence_score', result)

    def test_special_codes_preserved_without_numeric_scores(self):
        for col, code in ((4, 101), (5, 200), (6, 249), (8, 251), (9, 255)):
            result = self.query(col)
            self.assertEqual(result['status'], 'qualified')
            self.assertEqual(result['reason'], 'additional_interpretation')
            self.assertEqual(result['raw_code'], code)
            self.assertIn('code-specific meaning is not established', result['interpretation'])
            self.assertNotIn('confidence_score', result)
            self.assertNotIn('percent', result)
            self.assertFalse(result['model_eligible'])

    def test_nodata_remains_missing_with_internal_mask(self):
        for add_mask in (False, True):
            if add_mask:
                with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
                    with rasterio.open(self.path, 'r+') as ds:
                        ds.write_mask(np.full((64, 64), 255, dtype='uint8'))
                self.publish()
            result = self.query(7)
            self.assertEqual(result['reason'], 'source_nodata')
            self.assertEqual(result['status'], 'unavailable')
            self.assertNotIn('confidence_score', result)
            self.assertNotIn('interpretation', result)

    def test_native_zero_not_replaced_by_overview(self):
        with rasterio.open(self.path, overview_level=0) as ds:
            self.assertNotEqual(int(ds.read(1, window=rasterio.windows.Window(0, 0, 1, 1))[0, 0]), 0)
        result = self.query()
        self.assertEqual(result['raw_code'], 0)
        self.assertEqual(result['sampling'], 'native_containing_pixel')
        self.assertEqual(result['resolution_m'], 30)

    def test_internal_mask_hides_scores_zero_and_special_codes(self):
        mask = np.full((64, 64), 255, dtype='uint8')
        mask[0, [0, 1, 4]] = 0
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
            with rasterio.open(self.path, 'r+') as ds:
                ds.write_mask(mask)
        self.publish()
        for col in (0, 1, 4):
            with self.subTest(column=col):
                result = self.query(col)
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['reason'], 'source_nodata')
                self.assertNotIn('confidence_score', result)
                self.assertNotIn('raw_code', result)
                self.assertNotIn('interpretation', result)
        self.assertEqual(self.query(2)['confidence_score'], 37)

    def test_external_mask_does_not_change_reference(self):
        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
            with rasterio.open(self.path, 'r+') as ds:
                ds.write_mask(np.zeros((64, 64), dtype='uint8'))
        self.assertTrue(Path(str(self.path) + '.msk').exists())
        self.publish()
        self.assertEqual(self.query(1)['confidence_score'], 1)

    def test_outside_coverage_not_zero_or_missing_score(self):
        result = self.query(64)
        self.assertEqual(result['status'], 'outside_coverage')
        self.assertNotIn('raw_code', result)
        self.assertNotIn('confidence_score', result)

    def test_bad_coordinates_rejected_before_payload_access(self):
        reader = reference.Catalog(self.root)
        with patch.object(reader, '_artifact', side_effect=AssertionError('Unexpected IO')):
            for lat, lon in ((True, 0), (float('nan'), 0), (0, float('inf')), (91, 0), (0, -181)):
                with self.assertRaisesRegex(ValueError, 'invalid_coordinates'):
                    reader.land_cover_confidence(lat, lon)

    def test_declared_discovery_without_optional_gis_or_payload_reads(self):
        original = builtins.__import__
        original_open = Path.open
        def without_gis(name, *args, **kwargs):
            if name.split('.')[0] in {'rasterio', 'pyproj', 'numpy', 'shapely'}:
                raise ImportError(name)
            return original(name, *args, **kwargs)
        def without_payload(path, *args, **kwargs):
            self.assertNotEqual(path, self.path, 'Discovery opened the raster payload')
            return original_open(path, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_gis), patch.object(Path, 'open', without_payload):
            result = reference.Catalog(self.root).discover()[0]
        self.assertEqual(result['integrity'], 'not_checked')
        self.assertEqual(result['batch'], 'B11')
        self.assertFalse(result['model_eligible'])

    def test_missing_b11_does_not_substitute_land_cover_or_impervious(self):
        for batch, kind, use in (('B09', 'nlcd_land_cover', 'land_cover_reference'),
                                 ('B10', 'nlcd_fractional_impervious', 'impervious_reference')):
            entry = dict(self.entry, kind=kind, allowed_uses=[use], units='percent')
            self.write_catalog(dict(self.document, entries={batch: entry}))
            with self.assertRaisesRegex(ValueError, 'reference_source_unavailable'):
                self.query()

    def test_invalid_units_vintage_and_purpose_are_rejected(self):
        for change in ({'units': 'percent'}, {'units': None}, {'year': 2024}, {'year': True},
                       {'kind': 'nlcd_fractional_impervious'}, {'allowed_uses': ['flood_modelling']},
                       {'prohibited_uses': []}):
            doc = copy.deepcopy(self.document)
            doc['entries']['B11'].update(change)
            self.write_catalog(doc)
            with self.subTest(change=change), self.assertRaises(ValueError):
                reference.Catalog(self.root)

    def test_large_file_allowance_is_b11_only_and_still_bounded(self):
        # Admission of declared metadata never verifies or decodes a large file.
        self.assertEqual(reference.MAX_CONFIDENCE_ARTIFACT, 8 * 1024 ** 3)
        for size in (7729797852, reference.MAX_CONFIDENCE_ARTIFACT):
            self.entry['bytes'] = size
            self.write_catalog(self.document)
            self.assertEqual(reference.Catalog(self.root).discover()[0]['integrity'], 'not_checked')
            with self.assertRaisesRegex(ValueError, 'reference_integrity_failure'):
                self.query()
        for size in (reference.MAX_CONFIDENCE_ARTIFACT + 1, 0, True):
            self.entry['bytes'] = size
            self.write_catalog(self.document)
            with self.assertRaisesRegex(ValueError, 'invalid_artifact_pin'):
                reference.Catalog(self.root)
        for batch in ('B08', 'B09', 'B10'):
            kind, use, suffix = reference.USES[batch]
            entry = dict(self.entry, kind=kind, allowed_uses=[use], path='source' + suffix,
                         units='percent', bytes=reference.MAX_ARTIFACT + 1)
            self.write_catalog(dict(self.document, entries={batch: entry}))
            with self.assertRaisesRegex(ValueError, 'invalid_artifact_pin'):
                reference.Catalog(self.root)

    def test_hashing_respects_deadline_before_any_raster_decode(self):
        now = [0.0]
        original = Path.open
        payload = self.path.read_bytes()
        class SlowStream(io.BytesIO):
            def read(stream, size=-1):
                self.assertGreater(size, 0)
                self.assertLessEqual(size, 1024 * 1024)
                now[0] = reference.SECONDS + 1
                return super().read(size)
        def opened(path, *args, **kwargs):
            return SlowStream(payload) if path.resolve() == self.path.resolve() else original(path, *args, **kwargs)
        with patch.object(reference.time, 'monotonic', side_effect=lambda: now[0]):
            reader = reference.Catalog(self.root)
            with patch.object(Path, 'open', opened), patch.object(rasterio, 'open', side_effect=AssertionError('Late decode')):
                with self.assertRaisesRegex(ValueError, 'reference_query_time_limit'):
                    reader.land_cover_confidence(*self.point(1))

    def test_same_size_corruption_and_removal_fail_closed(self):
        payload = bytearray(self.path.read_bytes())
        payload[-1] ^= 1
        self.path.write_bytes(payload)
        with patch.object(rasterio, 'open', side_effect=AssertionError('Unverified decode')):
            with self.assertRaisesRegex(ValueError, 'reference_integrity_failure'):
                self.query(1)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.query(1)

    def test_deadline_after_hashing_blocks_every_result_category(self):
        now = [0.0]
        original = reference._project
        def delayed(*args):
            coordinates = original(*args)
            now[0] = reference.SECONDS + 1
            return coordinates
        for col in (0, 1, 4, 7, 64):
            with self.subTest(column=col):
                now[0] = 0.0
                with patch.object(reference.time, 'monotonic', side_effect=lambda: now[0]):
                    reader = reference.Catalog(self.root)
                    with patch.object(reference, '_project', side_effect=delayed):
                        with self.assertRaisesRegex(ValueError, 'reference_query_time_limit'):
                            reader.land_cover_confidence(*self.point(col))

    def test_catalog_change_during_query_is_rejected(self):
        original = reference._project
        def changed(*args):
            self.write_catalog({})
            return original(*args)
        with patch.object(reference, '_project', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'reference_changed_during_query'):
                self.query(1)

    def test_matching_wrong_crs_is_not_accepted(self):
        self.entry['horizontal_crs'] = 'EPSG:5070'
        self.publish()
        with self.assertRaisesRegex(ValueError, 'incompatible_confidence_raster'):
            self.query(1)
        with rasterio.open(self.path, 'r+') as ds:
            ds.crs = 'EPSG:5070'
        self.publish()
        with self.assertRaisesRegex(ValueError, 'incompatible_confidence_raster'):
            self.query(1)

    def test_scaling_sentinels_grid_and_dtype_are_not_inferred(self):
        for dtype, count, transform, nodata, scale, offset in (
                ('uint16', 1, self.transform, 250, 1, 0),
                ('uint8', 2, self.transform, 250, 1, 0),
                ('uint8', 1, self.transform * rasterio.Affine.scale(2), 250, 1, 0),
                ('uint8', 1, self.transform, 0, 1, 0),
                ('uint8', 1, self.transform, 250, .01, 0),
                ('uint8', 1, self.transform, 250, 1, 1)):
            with rasterio.open(self.path, 'w', driver='GTiff', width=64, height=64,
                               count=count, dtype=dtype, crs=self.crs, transform=transform, nodata=nodata) as ds:
                ds.write(np.full((count, 64, 64), 50, dtype=dtype))
                ds.scales = (scale,) * count
                ds.offsets = (offset,) * count
            self.publish()
            with self.assertRaisesRegex(ValueError, 'incompatible_confidence_raster'):
                self.query(1)

    def test_block_size_is_bounded(self):
        with patch.object(reference, 'MAX_BLOCK', 1):
            with self.assertRaisesRegex(ValueError, 'incompatible_confidence_raster'):
                self.query(1)

    def test_kind_dataset_and_results_cannot_be_operational_inputs(self):
        reader = flood_readiness_data.Snapshot({'data_directory': str(self.base)})
        for metadata in ({'kind': 'nlcd_land_cover_confidence'},
                         {'dataset': 'nlcd_land_cover_confidence_reference'}, self.query(1), self.query(4)):
            with self.assertRaises(policy.ReferenceUseError):
                policy.reject_metadata(metadata)
            with self.assertRaises(policy.ReferenceUseError):
                reader.dependency(metadata)
        with self.assertRaises(policy.ReferenceUseError):
            dataset_paths.resolve('nlcd_land_cover_confidence_reference', self.base / 'ordinary')

    def test_registry_metadata_and_custom_paths_cannot_promote_b11(self):
        registry = {'schema': 1, 'datasets': {'custom': {'active': {
            'path': 'ordinary', 'kind': 'nlcd_land_cover_confidence'}}}}
        with patch.object(dataset_paths, 'data_root', return_value=self.base):
            with self.assertRaises(policy.ReferenceUseError):
                dataset_paths.resolve('custom', self.base / 'ordinary', registry_reader=lambda p: registry)
        with self.assertRaises(policy.ReferenceUseError):
            dataset_paths.resolve('custom', self.base / 'ordinary', configured=self.root)

    def test_terrain_calls_and_missing_catalog_cannot_bypass_policy(self):
        entry = dict(path=self.path, units='m', vertical_crs='EPSG:4979')
        (self.root / policy.CATALOG).unlink()
        with self.assertRaises(policy.ReferenceUseError):
            satellite_terrain.sample(entry, 39, -123, {}, float('inf'))
        with self.assertRaises(policy.ReferenceUseError):
            satellite_terrain.fingerprint(self.path, float('inf'))

    def test_terrain_configuration_rejects_b11_metadata_outside_reserved_root(self):
        ordinary = self.base / 'ordinary.tif'
        shutil.copyfile(self.path, ordinary)
        for marker in ({'kind': 'nlcd_land_cover_confidence'},
                       {'dataset': 'nlcd_land_cover_confidence_reference'}):
            with self.subTest(marker=marker):
                entry = dict(id='b11', path=ordinary.name, units='m', vertical_crs='EPSG:4979',
                             source=self.entry['source'], bytes=self.entry['bytes'],
                             sha256=self.entry['sha256'], **marker)
                with self.assertRaises(policy.ReferenceUseError):
                    satellite_terrain.sources({'pointing': {'terrain_sources': [entry]}}, self.base)
                with self.assertRaises(policy.ReferenceUseError):
                    satellite_terrain.sample(dict(entry, path=ordinary), 39, -123, {}, float('inf'))

    def test_queries_do_not_write_files_or_change_membership(self):
        def hashes():
            return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.base.rglob('*') if p.is_file()}
        before = hashes()
        reference.Catalog(self.root).discover()
        for col in (0, 1, 4, 7):
            self.query(col)
        self.assertEqual(before, hashes())


if __name__ == '__main__':
    unittest.main()
