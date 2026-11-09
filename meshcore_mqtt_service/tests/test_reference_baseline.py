"""Synthetic B01 geographic DEM fixtures; no installed catalog changes."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window
from pyproj import Transformer

from scripts import reference_catalog as ref, reference_elevation_baseline as baseline
from scripts import dataset_paths, reference_policy, flood_readiness_data, satellite_terrain


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.gettempdir()) / ('reference-baseline-' + uuid.uuid4().hex)
        self.root = self.base / '.reference-only'
        self.root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.base))
        self.document = dict(schema_version=1, kind='restricted_reference_catalog',
                             complete=True, generation='synthetic-b01', entries={})
        self.make_tile()

    def make_tile(self, identifier='USGS_13_n39w123', *, units=None, vertical=None):
        """Write a sparse native-size geographic tile with bounded sample pixels."""
        north, west = int(identifier[9:11]), -int(identifier[12:15])
        cell = baseline.CELL_DEGREES
        transform = from_origin(west - 6 * cell, north + 6 * cell, cell, cell)
        path = self.root / (identifier + '.tif')
        with rasterio.open(path, 'w', driver='GTiff', width=baseline.SIZE, height=baseline.SIZE,
                           count=1, dtype='float32', nodata=-999999, transform=transform,
                           crs='EPSG:4269' + ('+' + vertical if vertical else ''),
                           tiled=True, blockxsize=16, blockysize=16, SPARSE_OK=True) as ds:
            for row, col in ((0, 0), (6, 6), (baseline.SIZE - 1, baseline.SIZE - 1)):
                ds.write(np.array([[14.25]], dtype='float32'), 1, window=Window(col, row, 1, 1))
            if units:
                ds.set_band_unit(1, units)
            bounds = list(ds.bounds)
        tile = dict(path=path.name, bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bounds=bounds,
                    units=None, vertical_datum=None, collection_date=None)
        entry = self.document['entries'].setdefault('B01', dict(
            kind='usgs_elevation_reference', allowed_uses=['elevation_reference'],
            prohibited_uses=['flood_modelling', 'satellite_terrain', 'operational_fallback'],
            source='USGS-3DEP-13arc', version='fixture', source_date='2026-01-01',
            horizontal_crs='EPSG:4269', coverage_note='Synthetic reference fixture.', tiles={}))
        entry['tiles'][identifier] = tile
        tree = ET.Element('metadata')
        fields = {
            'idinfo/citation/citeinfo/title': 'USGS 1/3 Arc Second ' + identifier[8:] + ' 20260101',
            'idinfo/citation/citeinfo/pubdate': '20260101',
            'idinfo/citation/citeinfo/origin': 'U.S. Geological Survey',
            'idinfo/citation/citeinfo/pubinfo/publish': 'U.S. Geological Survey',
            'idinfo/timeperd/timeinfo/rngdates/begdate': '19480101',
            'idinfo/timeperd/timeinfo/rngdates/enddate': '20230903',
            'idinfo/useconst': 'Temporal changes and source limitations apply.',
            'dataqual/posacc/vertacc/vertaccr': 'Original source accuracy remains unverified.',
            'spref/horizsys/geograph/geogunit': 'Decimal degrees',
            'spref/horizsys/geograph/longres': str(cell),
            'spref/horizsys/geograph/latres': str(-cell),
            'spref/horizsys/geodetic/horizdn': 'North American Datum of 1983',
            'spref/horizsys/geodetic/ellips': 'Geodetic Reference System 80',
            'spref/horizsys/geodetic/semiaxis': '6378137.0',
            'spref/horizsys/geodetic/denflat': '298.2572221',
            'spref/vertdef/altsys/altdatum': 'North American Vertical Datum of 1988',
            'spref/vertdef/altsys/altunits': 'meters',
            'spref/vertdef/altsys/altenc': 'Implicit coordinate',
            'spdoinfo/rastinfo/rowcount': str(baseline.SIZE),
            'spdoinfo/rastinfo/colcount': str(baseline.SIZE),
            'spdoinfo/rastinfo/vrtcount': '1',
            baseline.NETWORK_PATH: 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/'
                + 'historical/' + identifier[8:] + '/' + identifier + '_20260101.tif',
        }
        fields.update({'idinfo/spdom/bounding/' + k: str(v)
                       for k, v in zip(('westbc', 'southbc', 'eastbc', 'northbc'), bounds)})
        for name, value in fields.items():
            node = tree
            for part in name.split('/'):
                child = node.find(part)
                if child is None:
                    child = ET.SubElement(node, part)
                node = child
            node.text = value
        self.write_xml(identifier, baseline.DOCTYPES[0] + ET.tostring(tree))
        return identifier

    def tile(self, identifier='USGS_13_n39w123'):
        return self.document['entries']['B01']['tiles'][identifier]

    def publish(self):
        (self.root / 'reference-catalog.json').write_text(json.dumps(self.document), encoding='utf-8')

    def write_xml(self, identifier, raw):
        """Pin intentional fixture metadata changes independently of TIFF bytes."""
        path = self.root / (identifier + '.xml')
        path.write_bytes(raw)
        tile = self.tile(identifier)
        tile['height_evidence'] = dict(kind=baseline.KIND, reviewed=True, path=path.name,
                                      bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                                      tile_sha256=tile['sha256'], units='m', vertical_datum='EPSG:5703')
        self.publish()

    def mutate_xml(self, field, value, *, duplicate=False):
        identifier = 'USGS_13_n39w123'
        tree = ET.fromstring((self.root / (identifier + '.xml')).read_bytes())
        node = tree.find(field)
        if duplicate:
            tree.find(field.rsplit('/', 1)[0]).append(copy.deepcopy(node))
        elif value is None:
            tree.find(field.rsplit('/', 1)[0]).remove(node)
        else:
            node.text = value
        self.write_xml(identifier, ET.tostring(tree))

    def query(self, row=6, col=6, identifier='USGS_13_n39w123', **options):
        """Use explicit longitude/latitude order across the offline horizontal transform."""
        with rasterio.open(self.root / self.tile(identifier)['path']) as ds:
            x, y = ds.xy(row, col)
        lon, lat = Transformer.from_crs(4269, 4326, always_xy=True, allow_ballpark=False).transform(x, y)
        return ref.Catalog(self.root).elevation(lat, lon, batch='B01', tile_id=identifier, **options)

    def test_native_pixel_identity_dates_units_and_qualifications(self):
        r = self.query()
        self.assertEqual(r['elevation_m'], 14.25)
        self.assertEqual(r['tile_id'], 'USGS_13_n39w123')
        self.assertEqual(r['xml_publication_date'], '2026-01-01')
        self.assertEqual(r['xml_collection_start'], '1948-01-01')
        self.assertEqual(r['xml_collection_end'], '2023-09-03')
        self.assertEqual(r['vertical_datum'], 'EPSG:5703')
        self.assertEqual(r['units'], 'm')
        self.assertEqual(r['resolution_arcseconds'], 1 / 3)
        self.assertNotIn('resolution_m', r)
        self.assertEqual(r['sampling'], 'native_containing_pixel')
        self.assertIn('unverified', r['height_qualification'])
        self.assertFalse(r['model_eligible'])
        self.assertEqual(r['permitted_use'], 'elevation_reference')

    def test_buffers_half_open_edges_nodata_and_outside(self):
        for row, col in ((0, 0), (baseline.SIZE-1, baseline.SIZE-1)):
            self.assertEqual(self.query(row, col)['elevation_m'], 14.25)
        for row, col in ((-1, 0), (0, -1), (baseline.SIZE, 0), (0, baseline.SIZE)):
            self.assertEqual(self.query(row, col)['status'], 'outside_coverage')
        r = self.query(500, 500)
        self.assertEqual(r['reason'], 'source_nodata')
        self.assertNotIn('elevation_m', r)

    def test_overlap_requires_selection_without_blending(self):
        self.make_tile('USGS_13_n39w122')
        reader = ref.Catalog(self.root)
        r = reader.elevation(38.5, -122.0001)
        self.assertEqual(r['status'], 'ambiguous')
        self.assertEqual(len(r['records']), 2)
        self.assertEqual(ref.Catalog(self.root).elevation_tiles(38.5, -122.0001)['status'], 'declared')

    def test_no_xml_evidence_is_unavailable(self):
        del self.tile()['height_evidence']
        self.publish()
        self.assertEqual(self.query()['reason'], 'baseline_xml_evidence_required')

    def test_inventory_identity_is_checked_without_xml_evidence(self):
        original = copy.deepcopy(self.document)
        for identifier in ('unrelated_identity', 'USGS_13_n00w123', 'USGS_13_n91w123',
                           'USGS_13_n39w000', 'USGS_13_n39w181', 'USGS_13_n38w123'):
            self.document = copy.deepcopy(original)
            tiles = self.document['entries']['B01']['tiles']
            tile = tiles.pop('USGS_13_n39w123')
            tile.pop('height_evidence')
            if identifier != 'USGS_13_n38w123':
                tile['path'] = identifier + '.tif'
            tiles[identifier] = tile
            self.publish()
            with self.subTest(identifier=identifier), self.assertRaisesRegex(ValueError, 'tile_mismatch'):
                ref.Catalog(self.root)

    def test_conflicting_reference_branches_are_rejected(self):
        for parent, tag in (('spref/horizsys', 'planar'), ('spref/horizsys', 'local'),
                            ('spref/vertdef', 'depthsys'), ('spref', 'vertdef'),
                            ('spref/horizsys', 'geograph'), ('spref/vertdef', 'altsys')):
            self.make_tile()
            tree = ET.fromstring((self.root / self.tile()['height_evidence']['path']).read_bytes())
            ET.SubElement(tree.find(parent), tag).text = 'Unreviewed reference'
            self.write_xml('USGS_13_n39w123', ET.tostring(tree))
            with self.subTest(parent=parent, tag=tag):
                with self.assertRaisesRegex(ValueError, 'conflicting_baseline_xml_reference'):
                    self.query()

    def test_longitude_spacing_must_follow_eastward_grid(self):
        self.mutate_xml('spref/horizsys/geograph/longres', str(-baseline.CELL_DEGREES))
        with self.assertRaisesRegex(ValueError, 'conflicting_baseline_xml_resolution'):
            self.query()

    def test_b01_b03_overlap_requires_explicit_batch_without_fallback(self):
        entry = copy.deepcopy(self.document['entries']['B01'])
        entry['horizontal_crs'] = 'EPSG:26910'
        tile = next(iter(entry['tiles'].values()))
        tile.pop('height_evidence')
        x, y = Transformer.from_crs(4326, 26910, always_xy=True).transform(-122.99995, 38.99995)
        tile['bounds'] = [x - 100, y - 100, x + 100, y + 100]
        self.document['entries']['B03'] = entry
        self.publish()
        result = ref.Catalog(self.root).elevation(38.99995, -122.99995)
        self.assertEqual(result['status'], 'ambiguous')
        self.assertEqual({r['batch'] for r in result['records']}, {'B01', 'B03'})
        self.assertEqual(self.query()['elevation_m'], 14.25)
        self.tile()['height_evidence']['reviewed'] = False
        self.publish()
        with self.assertRaisesRegex(ValueError, 'invalid_elevation_xml_evidence'):
            ref.Catalog(self.root).elevation(38.99995, -122.99995)

    def test_exact_identity_unknown_and_bounded_coordinates(self):
        self.assertEqual(ref.Catalog(self.root).elevation(38.5, -122.5, batch='B01',
                         tile_id='USGS_13_n38w123')['status'], 'unknown')
        for lat, lon in ((True, 0), (91, 0), (0, float('nan')), (0, 181)):
            with self.assertRaises(ValueError):
                ref.Catalog(self.root).elevation(lat, lon, batch='B01')
        with self.assertRaisesRegex(ValueError, 'exact_tile_identity_required'):
            ref.Catalog(self.root).elevation(38, -122, tile_id='USGS_13_n39w123')

    def test_xml_tiff_integrity_and_missing_artifacts(self):
        for suffix in ('.xml', '.tif'):
            path = self.root / ('USGS_13_n39w123' + suffix)
            original = path.read_bytes()
            try:
                path.write_bytes(original + b'corruption')
                with self.assertRaisesRegex(ValueError, 'integrity_failure'):
                    self.query()
            finally:
                path.write_bytes(original)
        path = self.root / self.tile()['height_evidence']['path']
        path.unlink()
        with self.assertRaises(OSError):
            self.query()

    def test_conflicting_and_duplicate_source_fields_fail_closed(self):
        edits = [('spref/vertdef/altsys/altunits', 'feet'),
                 ('spref/vertdef/altsys/altdatum', 'NGVD29'),
                 ('spref/horizsys/geodetic/horizdn', 'WGS84'),
                 ('spref/horizsys/geograph/latres', '0.00001'),
                 ('spref/horizsys/geograph/longres', 'NaN'),
                 ('idinfo/spdom/bounding/westbc', '-100'),
                 ('spdoinfo/rastinfo/rowcount', '10800'),
                 ('idinfo/citation/citeinfo/pubdate', '20250230'),
                 ('idinfo/citation/citeinfo/title', 'USGS 1/3 Arc Second n39w123 20250101'),
                 (baseline.NETWORK_PATH, 'https://example.org/USGS_13_n39w123.tif'),
                 ('idinfo/timeperd/timeinfo/rngdates/enddate', '19000101')]
        for field, value in edits:
            with self.subTest(field=field):
                self.make_tile()
                self.mutate_xml(field, value)
                with self.assertRaises(ValueError):
                    self.query()
        self.make_tile()
        self.mutate_xml('spref/vertdef/altsys/altunits', 'meters', duplicate=True)
        with self.assertRaisesRegex(ValueError, 'ambiguous_or_missing'):
            self.query()

    def test_revision_and_publication_dates_remain_distinct(self):
        self.mutate_xml('idinfo/citation/citeinfo/pubdate', '20260102')
        r = self.query()
        self.assertEqual(r['xml_revision_date'], '2026-01-01')
        self.assertEqual(r['xml_publication_date'], '2026-01-02')
        self.mutate_xml(baseline.NETWORK_PATH,
                        'ftp://rockyftp.cr.usgs.gov/vdelivery/Datasets/Staged/Elevation/13/TIFF/'
                        'n39w123/USGS_13_n39w123_20260101.tif')
        self.assertEqual(self.query()['xml_revision_date'], '2026-01-01')
        self.mutate_xml(baseline.NETWORK_PATH,
                        'https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/13/TIFF/historical/'
                        'n39w123/USGS_13_n39w123_20260101.tif')
        self.assertEqual(self.query()['xml_revision_date'], '2026-01-01')

    def test_legacy_identity_and_year_precision_preserved(self):
        self.mutate_xml('idinfo/citation/citeinfo/title', 'USGS 1/3 arc-second n39w123 1 x 1 degree')
        self.mutate_xml('idinfo/citation/citeinfo/pubdate', '2013')
        self.mutate_xml(baseline.NETWORK_PATH,
                        'ftp://rockyftp.cr.usgs.gov/vdelivery/Datasets/Staged/Elevation/13/TIFF/'
                        'n39w123/USGS_13_n39w123.tif')
        self.mutate_xml('spref/horizsys/geograph/latres', str(baseline.CELL_DEGREES))
        r = self.query()
        self.assertEqual(r['xml_publication_date'], '2013')
        self.assertEqual(r['xml_publication_date_precision'], 'year')
        self.mutate_xml('spref/horizsys/geograph/latres', '0.00001')
        with self.assertRaisesRegex(ValueError, 'conflicting_baseline_xml_resolution'):
            self.query()

    def test_review_and_identity_pins_and_path_escape(self):
        for key, value in [('reviewed', False), ('tile_sha256', '0'*64), ('kind', 'unknown'),
                           ('path', '../escaped.xml'), ('path', 'wrong.xml')]:
            self.make_tile()
            self.tile()['height_evidence'][key] = value
            self.publish()
            with self.subTest(key=key), self.assertRaises(ValueError):
                ref.Catalog(self.root)

    def test_unsafe_xml_is_never_expanded(self):
        raw = (self.root / self.tile()['height_evidence']['path']).read_bytes()
        for declaration in (b'<!DOCTYPE metadata SYSTEM "https://example.org/evil.dtd">',
                            b'<!DOCTYPE metadata [<!ENTITY leak SYSTEM "file:///secret">]>'):
            self.write_xml('USGS_13_n39w123', declaration + raw)
            with self.assertRaisesRegex(ValueError, 'unsupported_elevation_xml_declaration'):
                self.query()
        self.write_xml('USGS_13_n39w123',
                       ('<!DOCTYPE metadata [<!ENTITY leak SYSTEM "file:///secret">]>'
                        '<metadata>&leak;</metadata>').encode('utf-16'))
        with self.assertRaisesRegex(ValueError, 'unsupported_elevation_xml_declaration'):
            self.query()

    def test_invalid_encoding_is_controlled(self):
        self.write_xml('USGS_13_n39w123', b'<?xml version="1.0" encoding="unknown-encoding"?><metadata/>')
        with self.assertRaisesRegex(ValueError, 'invalid_elevation_xml'):
            self.query()

    def test_nonfinite_pixels_and_incompatible_rasters(self):
        path = self.root / self.tile()['path']
        for value in (float('nan'), float('inf'), -999999):
            with rasterio.open(path, 'r+') as ds:
                ds.write(np.array([[value]], dtype='float32'), 1, window=Window(6, 6, 1, 1))
            self.tile()['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.tile()['bytes'] = path.stat().st_size
            self.write_xml('USGS_13_n39w123', (self.root / self.tile()['height_evidence']['path']).read_bytes())
            result = self.query()
            self.assertEqual(result['reason'], 'source_nodata')
            self.assertNotIn('elevation_m', result)
        for field, value in (('crs', 'EPSG:4326'), ('scales', (2.0,)), ('offsets', (10.0,))):
            self.make_tile()
            with rasterio.open(path, 'r+') as ds:
                setattr(ds, field, value)
            self.tile()['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.tile()['bytes'] = path.stat().st_size
            self.write_xml('USGS_13_n39w123', (self.root / self.tile()['height_evidence']['path']).read_bytes())
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'incompatible_baseline_raster'):
                self.query()

    def test_removal_and_query_deadline_do_not_fall_back(self):
        reader = ref.Catalog(self.root)
        reader.until = 0
        with self.assertRaisesRegex(ValueError, 'reference_query_time_limit'):
            reader.elevation(38.5, -122.5, batch='B01', tile_id='USGS_13_n39w123')
        (self.root / 'reference-catalog.json').unlink()
        with self.assertRaises(OSError):
            ref.Catalog(self.root)
        with self.assertRaises(reference_policy.ReferenceUseError):
            dataset_paths.checked_path(self.root, self.tile()['path'])

    def test_embedded_unit_and_vertical_conflicts(self):
        for units, vertical in [('ft', None), ('m', '5773')]:
            self.make_tile(units=units, vertical=vertical)
            with self.assertRaisesRegex(ValueError, 'conflicting_elevation'):
                self.query()
        self.make_tile(units='m', vertical='5703')
        self.assertEqual(self.query()['elevation_m'], 14.25)

    def test_no_horizontal_operation_never_falls_back(self):
        with patch.object(ref, '_project', side_effect=ValueError('coordinate_transform_unavailable')):
            with self.assertRaisesRegex(ValueError, 'coordinate_transform_unavailable'):
                self.query()

    def test_custom_path_and_reference_isolation(self):
        self.assertEqual(ref.Catalog(self.root).discover()[0]['batch'], 'B01')
        result = self.query()
        calls = [lambda: dataset_paths.checked_path(self.root, self.tile()['path']),
                 lambda: dataset_paths.resolve('usgs_elevation_b01_reference', self.root),
                 lambda: reference_policy.reject_metadata(result),
                 lambda: flood_readiness_data.Snapshot({}).dependency({'dataset': 'usgs_elevation_b01_reference'}),
                 lambda: flood_readiness_data.Snapshot({}).dependency({'kind': 'usgs_elevation_reference'}),
                 lambda: satellite_terrain.sources({'pointing': {'terrain_sources': [
                     {'id': 'b01', 'path': self.tile()['path']}]}}, self.root)]
        for call in calls:
            with self.assertRaises(reference_policy.ReferenceUseError):
                call()


if __name__ == '__main__':
    unittest.main()
