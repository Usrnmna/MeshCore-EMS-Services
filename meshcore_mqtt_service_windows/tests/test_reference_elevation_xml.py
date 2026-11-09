"""Synthetic XML-qualified height references; no installed catalog enrollment."""
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

from scripts import reference_catalog as ref, reference_elevation_xml as xml
from scripts import reference_policy as policy, dataset_paths, flood_readiness_data, satellite_terrain

ABSTRACT = "This is a tile of the standard one-meter resolution digital elevation model (DEM) produced through the 3D Elevation Program (3DEP) . The elevations in this DEM represent the topographic bare-earth surface. USGS standard one-meter DEMs are produced exclusively from high resolution light detection and ranging (lidar) source data of one-meter or higher resolution. One-meter DEM surfaces are seamless within collection projects, but, not necessarily seamless across projects. The spatial reference used for tiles of the one-meter DEM within the conterminous United States (CONUS) is Universal Transverse Mercator (UTM) in units of meters, and in conformance with the North American Datum of 1983 (NAD83). All bare earth elevation values are in meters and are referenced to the North American Vertical Datum of 1988 (NAVD88). Each tile is distributed in the UTM Zone in which it lies. If a tile crosses two UTM zones, it is delivered in both zones. The one-meter DEM is the highest resolution standard DEM offered in the 3DEP product suite. Other 3DEP products are nationally seamless DEMs in resolutions of 1/3, 1, and 2 arc seconds. These seamless DEMs were referred to as the National Elevation Dataset (NED) from about 2000 through 2015 at which time they became the seamless DEM layers under the 3DEP program and lost the NED branding. Other 3DEP products include five-meter DEMs in Alaska as well as various source datasets including the lidar point cloud and interferometric synthetic aperture radar (Ifsar) digital surface models and intensity images. All 3DEP products are public domain."


class ElevationXmlTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.gettempdir()) / ('elevation-xml-' + uuid.uuid4().hex)
        self.root = self.base / '.reference-only'
        self.root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.base))
        self.document = dict(schema_version=1, kind='restricted_reference_catalog',
                             generation='synthetic-xml-01', complete=True, entries={})
        self.x, self.y = 460000.0, 4280000.0
        self.transform = from_origin(self.x, self.y, 1, 1)
        self.make_tile('B03')
        self.make_tile('B04', units='metre')

    def make_tile(self, batch, *, units=None, vertical=None, value=12.25, size=4):
        """Create a small or sparse buffered TIFF and its independently pinned XML."""
        project = xml.PROJECTS[batch]
        identifier = 'USGS_1M_10_x46y428_' + project
        path = self.root / (identifier + '.tif')
        with rasterio.open(path, 'w', driver='GTiff', width=size, height=size, count=1,
                           dtype='float32', nodata=-999999,
                           crs='EPSG:26910' + ('+' + vertical if vertical else ''),
                           transform=self.transform, tiled=True, blockxsize=16, blockysize=16,
                           SPARSE_OK=True) as ds:
            ds.write(np.array([[value]], dtype='float32'), 1, window=Window(0, 0, 1, 1))
            if units:
                ds.set_band_unit(1, units)
            bounds = list(ds.bounds)
        tile = dict(path=path.name, bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bounds=bounds,
                    units=None, vertical_datum=None, collection_date=None)
        self.document['entries'][batch] = dict(
            kind='usgs_elevation_reference', allowed_uses=['elevation_reference'],
            prohibited_uses=['flood_modelling', 'satellite_terrain', 'operational_fallback'],
            source='USGS-3DEP-' + project, version=project, source_date='2026-03-24',
            horizontal_crs='EPSG:26910', coverage_note='Synthetic reference fixture only.',
            tiles={identifier: tile})
        tree = ET.Element('metadata')
        def leaf(path, text):
            node = tree
            for name in path.split('/'):
                child = node.find(name)
                if child is None:
                    child = ET.SubElement(node, name)
                node = child
            node.text = text
        fields = {
            'idinfo/citation/citeinfo/title': 'USGS 1 Meter 10 x46y428 ' + project,
            'idinfo/citation/citeinfo/origin': 'U.S. Geological Survey',
            'idinfo/citation/citeinfo/pubinfo/publish': 'U.S. Geological Survey',
            'idinfo/citation/citeinfo/pubdate': '20260324',
            'idinfo/descript/abstract': ABSTRACT,
            'idinfo/useconst': 'No accuracy warranty; temporal changes may have occurred.',
            'dataqual/posacc/vertacc/vertaccr': 'Refer to original project metadata.',
            'idinfo/timeperd/timeinfo/rngdates/begdate': '20220826',
            'idinfo/timeperd/timeinfo/rngdates/enddate': '20240704',
            'spref/horizsys/planar/gridsys/gridsysn': 'NAD83 / UTM zone 10N',
            'spref/horizsys/planar/gridsys/utm/utmzone': '10',
            'spdoinfo/rastinfo/rowcount': str(size),
            'spdoinfo/rastinfo/colcount': str(size),
            'spdoinfo/rastinfo/vrtcount': '1',
            xml.NETWORK_PATH: 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/'
                              + project + '/TIFF/' + identifier + '.tif'}
        inset = 6 if size == 10012 else 0
        operation = Transformer.from_crs(26910, 4326, always_xy=True)
        corners = [operation.transform(*(self.transform * (col, row)))
                   for col in (inset, size-inset) for row in (inset, size-inset)]
        for key, value in zip(('westbc', 'southbc', 'eastbc', 'northbc'),
                              (min(p[0] for p in corners), min(p[1] for p in corners),
                               max(p[0] for p in corners), max(p[1] for p in corners))):
            fields['idinfo/spdom/bounding/' + key] = str(value)
        for key, value in fields.items():
            leaf(key, value)
        self.write_xml(batch, xml.DOCTYPE.encode() + ET.tostring(tree))

    def tile(self, batch='B03'):
        return next(iter(self.document['entries'][batch]['tiles'].items()))

    def write_xml(self, batch, raw):
        """Repin intentional fixture edits; corruption tests bypass this method."""
        identifier, tile = self.tile(batch)
        path = self.root / (identifier + '.xml')
        path.write_bytes(raw)
        tile['height_evidence'] = dict(kind=xml.KIND, reviewed=True, path=path.name,
                                      bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                                      tile_sha256=tile['sha256'], units='m', vertical_datum='EPSG:5703')
        self.publish()

    def publish(self):
        (self.root / 'reference-catalog.json').write_text(json.dumps(self.document), encoding='utf-8')

    def query(self, batch='B03', *, x_offset=.5, y_offset=.5):
        lon, lat = Transformer.from_crs(26910, 4326, always_xy=True).transform(
            self.x+x_offset, self.y-y_offset)
        return ref.Catalog(self.root).elevation(lat, lon, batch=batch, tile_id=self.tile(batch)[0])

    def test_qualified_reads_preserve_dates_identity_and_restrictions(self):
        for batch in ('B03', 'B04'):
            with self.subTest(batch=batch):
                result = self.query(batch)
                self.assertEqual(result['status'], 'ok')
                self.assertEqual(result['elevation_m'], 12.25)
                self.assertEqual(result['tile_id'], self.tile(batch)[0])
                self.assertEqual(result['units'], 'm')
                self.assertEqual(result['vertical_datum'], 'EPSG:5703')
                self.assertEqual(result['height_evidence_basis'], 'reviewed_xml_declaration')
                self.assertEqual(result['xml_publication_date'], '2026-03-24')
                self.assertEqual(result['xml_collection_start'], '2022-08-26')
                self.assertEqual(result['xml_collection_end'], '2024-07-04')
                self.assertIn('No accuracy warranty', result['source_use_constraints'])
                self.assertIn('unverified', result['height_qualification'])
                self.assertEqual(result['sampling'], 'native_containing_pixel')
                self.assertIsNone(result['collection_date'])
                self.assertFalse(result['model_eligible'])
                self.assertEqual(result['permitted_use'], 'elevation_reference')

    def test_embedded_metadata_agreement_and_conflicts(self):
        for units, vertical, error in [('metre', '5703', None), ('ft', None, 'conflicting_elevation_units'),
                                       ('metre', '5773', 'conflicting_elevation_vertical_datum')]:
            self.make_tile('B03', units=units, vertical=vertical)
            with self.subTest(units=units, vertical=vertical):
                if error:
                    with self.assertRaisesRegex(ValueError, error):
                        self.query()
                else:
                    self.assertEqual(self.query()['elevation_m'], 12.25)
        for field, value in [('units', 'ft'), ('vertical_datum', 'EPSG:5773')]:
            self.make_tile('B03')
            self.tile()[1][field] = value
            self.publish()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'conflicting_elevation'):
                self.query()

    def test_no_evidence_never_infers_height_and_overlap_stays_ambiguous(self):
        reader = ref.Catalog(self.root)
        lon, lat = Transformer.from_crs(26910, 4326, always_xy=True).transform(self.x+.5, self.y-.5)
        self.assertEqual(reader.elevation(lat, lon)['status'], 'ambiguous')
        for batch in ('B03', 'B04'):
            del self.tile(batch)[1]['height_evidence']
        self.publish()
        for batch in ('B03', 'B04'):
            self.assertEqual(self.query(batch)['status'], 'unavailable')

    def test_missing_changed_xml_and_tiff_fail_closed(self):
        identifier, tile = self.tile()
        path = self.root / tile['height_evidence']['path']
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.query()
        path.write_bytes(raw + b' ')
        with self.assertRaisesRegex(ValueError, 'elevation_xml_integrity_failure'):
            self.query()
        path.write_bytes(raw.replace(b'NAVD88', b'NGVD29'))
        with self.assertRaisesRegex(ValueError, 'elevation_xml_integrity_failure'):
            self.query()
        path.write_bytes(raw)
        with (self.root / tile['path']).open('ab') as stream:
            stream.write(b'x')
        with self.assertRaisesRegex(ValueError, 'reference_integrity_failure'):
            self.query()

    def test_invalid_review_and_pin_associations(self):
        original = copy.deepcopy(self.document)
        for field, value in [('reviewed', False), ('tile_sha256', '0'*64), ('bytes', xml.MAX_XML+1),
                             ('units', 'ft'), ('vertical_datum', 'EPSG:5773'),
                             ('path', '../escape.xml'), ('path', self.tile('B04')[0]+'.xml')]:
            self.document = copy.deepcopy(original)
            self.tile()[1]['height_evidence'][field] = value
            self.publish()
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                ref.Catalog(self.root)
        self.document = copy.deepcopy(original)
        self.tile()[1]['height_evidence'] = None
        self.publish()
        with self.assertRaisesRegex(ValueError, 'invalid_elevation_xml_evidence'):
            ref.Catalog(self.root)

    def test_pinned_but_wrong_source_declarations_and_geometry_are_rejected(self):
        identifier, tile = self.tile()
        raw = (self.root/tile['height_evidence']['path']).read_bytes()
        replacements = [
            (b'USGS 1 Meter 10 x46y428', b'USGS 1 Meter 10 x47y428'),
            (b'/TIFF/'+identifier.encode()+b'.tif', b'/TIFF/other.tif'),
            (b'U.S. Geological Survey', b'Other publisher'),
            (b'elevation values are in meters', b'elevation values are in feet'),
            (b'(NAVD88)', b'(NGVD29)'),
            (b'<rowcount>4</rowcount>', b'<rowcount>5</rowcount>'),
            (b'<utmzone>10</utmzone>', b'<utmzone>11</utmzone>'),
            (b'</spref>', b'<vertdef><altsys><altdatum>NGVD29</altdatum></altsys></vertdef></spref>')]
        for old, new in replacements:
            self.write_xml('B03', raw.replace(old, new))
            with self.subTest(replacement=new), self.assertRaises(ValueError):
                self.query()
        tree = ET.fromstring(raw)
        tree.find('idinfo/spdom/bounding/westbc').text = '-120'
        self.write_xml('B03', ET.tostring(tree))
        with self.assertRaisesRegex(ValueError, 'elevation_xml_footprint_mismatch'):
            self.query()

    def test_duplicate_and_unsafe_xml_is_rejected_without_network(self):
        raw = (self.root/self.tile()[1]['height_evidence']['path']).read_bytes()
        duplicate = raw.replace(b'</citeinfo>', b'<title>Other</title></citeinfo>')
        unsafe = b'<!DOCTYPE metadata [<!ENTITY x SYSTEM "file:///private">]><metadata>&x;</metadata>'
        for content in (duplicate, unsafe, b'<metadata>', raw.replace(xml.DOCTYPE.encode(),
                         b'<!DOCTYPE metadata SYSTEM "https://example.invalid/evil.dtd">')):
            self.write_xml('B03', content)
            with self.subTest(content=content[:70]), patch('socket.socket', side_effect=AssertionError('network access')):
                with self.assertRaises(ValueError):
                    self.query()
        self.write_xml('B03', raw)
        with patch('socket.socket', side_effect=AssertionError('network access')):
            self.assertEqual(self.query()['status'], 'ok')

    def test_explicit_horizontal_details_cannot_contradict_grid_label(self):
        raw = (self.root/self.tile()[1]['height_evidence']['path']).read_bytes()
        fields = [
            ('geodetic/horizdn', 'North_American_Datum_1983', 'WGS_1984'),
            ('geodetic/ellips', 'GRS 1980', 'Clarke 1866'),
            ('geodetic/semiaxis', '6378137.0', '6378206.4'),
            ('geodetic/denflat', '298.257222101', '294.9786982'),
            ('planar/planci/plandu', 'meters', 'feet'),
            ('planar/gridsys/utm/transmer/sfctrmer', '0.9996', '1.0'),
            ('planar/gridsys/utm/transmer/longcm', '-123.0', '-117.0'),
            ('planar/gridsys/utm/transmer/latprjo', '0.0', '1.0'),
            ('planar/gridsys/utm/transmer/feast', '500000.0', '400000.0'),
            ('planar/gridsys/utm/transmer/fnorth', '0.0', '10000000.0')]
        tree = ET.fromstring(raw)
        for path, expected, conflict in fields:
            node = tree.find('spref/horizsys')
            for name in path.split('/'):
                child = node.find(name)
                if child is None:
                    child = ET.SubElement(node, name)
                node = child
            node.text = expected
        valid = ET.tostring(tree)
        self.write_xml('B03', valid)
        self.assertEqual(self.query()['status'], 'ok')
        for path, expected, conflict in fields:
            for invalid in (conflict, 'NaN'):
                changed = ET.fromstring(valid)
                changed.find('spref/horizsys/' + path).text = invalid
                self.write_xml('B03', ET.tostring(changed))
                with self.subTest(field=path, value=invalid):
                    with self.assertRaisesRegex(ValueError, 'conflicting_elevation_xml_horizontal_reference'):
                        self.query()
        tree = ET.fromstring(valid)
        ET.SubElement(tree.find('spref/horizsys/geodetic'), 'horizdn').text = 'WGS_1984'
        self.write_xml('B03', ET.tostring(tree))
        with self.assertRaisesRegex(ValueError, 'ambiguous_or_missing_elevation_xml_field'):
            self.query()

    def test_nodata_nonfinite_and_outside_preserve_qualifications(self):
        for value in (-999999, float('nan')):
            self.make_tile('B03', value=value)
            result = self.query()
            self.assertEqual(result['reason'], 'source_nodata')
            self.assertNotIn('elevation_m', result)
            self.assertIn('height_evidence_basis', result)
        result = self.query(x_offset=20)
        self.assertEqual(result['status'], 'outside_coverage')
        self.assertNotIn('elevation_m', result)

    def test_buffered_and_unbuffered_tiles_keep_their_native_footprints(self):
        for size in (10000, 10012):
            with self.subTest(size=size):
                self.make_tile('B03', size=size)
                # The first buffered pixel lies outside the XML nominal footprint.
                result = self.query()
                self.assertEqual(result['elevation_m'], 12.25)
                self.assertEqual(result['sampling'], 'native_containing_pixel')
                self.assertEqual(self.query(x_offset=size+.5)['status'], 'outside_coverage')

    def test_full_inventory_with_evidence_fits_bounded_catalog(self):
        template = copy.deepcopy(self.tile()[1])
        tiles = self.document['entries']['B03']['tiles'] = {}
        for index in range(126):
            identifier = 'USGS_1M_10_x' + str(index) + 'y428_CA_NorthernCA_B22'
            tile = copy.deepcopy(template)
            tile['path'] = identifier + '.tif'
            tile['height_evidence']['path'] = identifier + '.xml'
            tiles[identifier] = tile
        self.publish()
        self.assertGreater((self.root/'reference-catalog.json').stat().st_size, 64*1024)
        self.assertEqual(len(ref.Catalog(self.root).entries['B03']['tiles']), 126)
        self.document['padding'] = 'x' * ref.MAX_CATALOG
        self.publish()
        with self.assertRaisesRegex(ValueError, 'catalog_size_limit'):
            ref.Catalog(self.root)

    def test_dates_preserve_unknown_and_reject_conflicts(self):
        raw = (self.root/self.tile()[1]['height_evidence']['path']).read_bytes()
        tree = ET.fromstring(raw)
        tree.find('idinfo/citation/citeinfo').remove(tree.find('idinfo/citation/citeinfo/pubdate'))
        tree.find('idinfo/timeperd/timeinfo').remove(tree.find('idinfo/timeperd/timeinfo/rngdates'))
        self.write_xml('B03', ET.tostring(tree))
        result = self.query()
        self.assertIsNone(result['xml_publication_date'])
        self.assertIsNone(result['xml_collection_start'])
        for old, new in [(b'20240704', b'20200101'), (b'20260324', b'20260230')]:
            self.write_xml('B03', raw.replace(old, new))
            with self.assertRaisesRegex(ValueError, 'elevation_xml_date'):
                self.query()

    def test_output_and_paths_remain_isolated_and_reads_are_immutable(self):
        before = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.iterdir()}
        result = self.query()
        with self.assertRaises(policy.ReferenceUseError):
            policy.reject_metadata(result)
        with self.assertRaises(policy.ReferenceUseError):
            flood_readiness_data.Snapshot({'data_directory':str(self.base)}).dependency(result)
        tile_path = '.reference-only/' + self.tile()[1]['path']
        with self.assertRaises(policy.ReferenceUseError):
            dataset_paths.checked_path(self.base, tile_path)
        with self.assertRaises(policy.ReferenceUseError):
            satellite_terrain.sources({'pointing':{'terrain_sources':[{'id':'tile','path':tile_path}]}},self.base)
        self.assertEqual(before, {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.iterdir()})

    def test_xml_change_during_read_is_detected(self):
        original = xml.read_evidence
        def changed(*args):
            result = original(*args)
            path = self.root / self.tile()[1]['height_evidence']['path']
            with path.open('ab') as stream:
                stream.write(b' ')
            return result
        with patch.object(xml, 'read_evidence', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'reference_changed_during_query'):
                self.query()


if __name__ == '__main__':
    unittest.main()

