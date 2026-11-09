"""Pinned B01 geographic DEM references; no source installation or height conversion.

The supported contract is the staged USGS 1/3 arc-second, 10812-cell tile with
six-cell buffers. XML declarations must agree with the raster; historical
metadata inconsistencies remain errors rather than implicit corrections.
"""
from datetime import datetime
import hashlib
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from . import dataset_paths, reference_catalog as ref
from .reference_elevation_xml import _one, _date

KIND = 'usgs_3dep_13arc_fgdc_v1'
MAX_XML = 64 * 1024
CELL_DEGREES = 1 / 10800
SIZE = 10812
BUFFER = 6
IDENTITY = r'USGS_13_n([0-9]{2})w([0-9]{3})'
NETWORK_PATH = 'distinfo/stdorder/digform/digtopt/onlinopt/computer/networka/networkr'
DOCTYPES = tuple(('<!DOCTYPE metadata SYSTEM "' + url + '">').encode('ascii') for url in (
    'https://www.fgdc.gov/schemas/metadata/fgdc-std-001-1998.dtd',
    'https://thor-f5.er.usgs.gov/ngtoc/metadata/fgdc-std-001-1998.dtd',
    'http://thor-f5.er.usgs.gov/ngtoc/metadata/fgdc-std-001-1998.dtd'))


def validate_tile_identity(tile_id, tile):
    """Require an exact geographic tile and TIFF name even without height evidence."""
    match = re.fullmatch(IDENTITY, tile_id)
    if (match is None or not 1 <= int(match[1]) <= 90
            or not 1 <= int(match[2]) <= 180
            or Path(tile['path']).name != tile_id + '.tif'):
        raise ValueError('elevation_tile_mismatch')
    return int(match[1]), -int(match[2])


def validate_evidence(root, batch, tile_id, tile):
    """Validate exact tile identity and the explicit review, XML and TIFF pins."""
    if batch != 'B01':
        raise ValueError('elevation_xml_tile_mismatch')
    validate_tile_identity(tile_id, tile)
    evidence = tile.get('height_evidence')
    if (not isinstance(evidence, dict) or evidence.get('kind') != KIND
            or evidence.get('reviewed') is not True or evidence.get('units') != 'm'
            or evidence.get('vertical_datum') != 'EPSG:5703'
            or evidence.get('tile_sha256') != tile['sha256']
            or type(evidence.get('bytes')) is not int or not 0 < evidence['bytes'] <= MAX_XML
            or not isinstance(evidence.get('sha256'), str)
            or not re.fullmatch('[a-f0-9]{64}', evidence['sha256'])):
        raise ValueError('invalid_elevation_xml_evidence')
    path = dataset_paths.checked_path(root, evidence.get('path'), allow_reference=True)
    if path.name != tile_id + '.xml':
        raise ValueError('elevation_xml_tile_mismatch')
    return evidence, path


def _number(tree, path):
    """Read one finite numeric declaration, rejecting duplicates and nonnumbers."""
    try:
        number = float(_one(tree, path))
    except ValueError as exc:
        raise ValueError('invalid_baseline_xml_number') from exc
    if not math.isfinite(number):
        raise ValueError('invalid_baseline_xml_number')
    return number


def _publication(tree):
    """Preserve year-only publication evidence without inventing month or day."""
    value = _one(tree, 'idinfo/citation/citeinfo/pubdate')
    if not re.fullmatch(r'\d{4}(?:\d{4})?', value):
        raise ValueError('invalid_elevation_xml_date')
    try:
        date = datetime.strptime(value, '%Y' if len(value) == 4 else '%Y%m%d')
    except ValueError as exc:
        raise ValueError('invalid_elevation_xml_date') from exc
    return (value, 'year') if len(value) == 4 else (date.date().isoformat(), 'day')


def read_evidence(reader, tile_id, tile, raster):
    """Bind source identity, dated declarations and geographic geometry offline."""
    evidence, path = validate_evidence(reader.root, 'B01', tile_id, tile)
    reader._tick()
    reader.paths[evidence['path']] = path
    reader._remember(path)
    if path.stat().st_size != evidence['bytes']:
        raise ValueError('elevation_xml_integrity_failure')
    with path.open('rb') as stream:
        raw = stream.read(MAX_XML + 1)
    if len(raw) != evidence['bytes'] or hashlib.sha256(raw).hexdigest() != evidence['sha256']:
        raise ValueError('elevation_xml_integrity_failure')
    reader._finish()
    if sum(raw.count(declaration) for declaration in DOCTYPES) > 1:
        raise ValueError('unsupported_elevation_xml_declaration')
    for declaration in DOCTYPES:
        raw = raw.replace(declaration, b'')
    # Preserve the declared XML encoding. No external DTD or entities are read.
    if b'<!' in raw or b'\x00' in raw:
        raise ValueError('unsupported_elevation_xml_declaration')
    try:
        tree = ET.fromstring(raw)
    except (ET.ParseError, ValueError, LookupError) as exc:
        raise ValueError('invalid_elevation_xml') from exc
    if tree.tag != 'metadata':
        raise ValueError('unsupported_elevation_xml_schema')
    # Only the audited geographic/altitude structure is supported. Alternative
    # or duplicate reference branches must not be silently ignored.
    for parent, children in (('spref', {'horizsys', 'vertdef'}),
                             ('spref/horizsys', {'geograph', 'geodetic'}),
                             ('spref/vertdef', {'altsys'})):
        nodes = tree.findall(parent)
        if (len(nodes) != 1 or len(nodes[0]) != len(children)
                or {node.tag for node in nodes[0]} != children):
            raise ValueError('conflicting_baseline_xml_reference')
    code = tile_id.removeprefix('USGS_13_')
    title = _one(tree, 'idinfo/citation/citeinfo/title')
    modern = re.fullmatch(r'USGS 1/3 Arc Second ' + re.escape(code) + r' (\d{8})', title)
    legacy = title == 'USGS 1/3 arc-second ' + code + ' 1 x 1 degree'
    if not modern and not legacy:
        raise ValueError('elevation_xml_source_mismatch')
    publication, precision = _publication(tree)
    # The tile revision token and publication date are independent source fields.
    revision = datetime.strptime(modern[1], '%Y%m%d').date().isoformat() if modern else None
    url = _one(tree, NETWORK_PATH)
    prefix = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/'
    urls = {prefix + code + '/' + tile_id + '.tif'}
    if modern:
        urls.add(prefix + 'historical/' + code + '/' + tile_id + '_' + modern[1] + '.tif')
        urls.add('ftp://rockyftp.cr.usgs.gov/vdelivery/Datasets/Staged/Elevation/13/TIFF/'
                 + code + '/' + tile_id + '_' + modern[1] + '.tif')
        urls.add('https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/13/TIFF/historical/'
                 + code + '/' + tile_id + '_' + modern[1] + '.tif')
    if legacy:
        urls.add('ftp://rockyftp.cr.usgs.gov/vdelivery/Datasets/Staged/Elevation/13/TIFF/'
                 + code + '/' + tile_id + '.tif')
    if (url not in urls or _one(tree, 'idinfo/citation/citeinfo/origin') != 'U.S. Geological Survey'
            or _one(tree, 'idinfo/citation/citeinfo/pubinfo/publish') != 'U.S. Geological Survey'):
        raise ValueError('elevation_xml_source_mismatch')
    declarations = {
        'horizsys/geograph/geogunit': 'Decimal degrees',
        'horizsys/geodetic/horizdn': 'North American Datum of 1983',
        'horizsys/geodetic/ellips': 'Geodetic Reference System 80',
        'vertdef/altsys/altdatum': 'North American Vertical Datum of 1988',
        'vertdef/altsys/altunits': 'meters',
        'vertdef/altsys/altenc': 'Implicit coordinate',
    }
    for field, expected in declarations.items():
        if _one(tree, 'spref/' + field) != expected:
            raise ValueError('conflicting_baseline_xml_reference')
    for field, expected, tolerance in (
            ('horizsys/geodetic/semiaxis', 6378137, 1e-6),
            ('horizsys/geodetic/denflat', 298.257222101, 1e-8)):
        if abs(_number(tree, 'spref/' + field) - expected) > tolerance:
            raise ValueError('conflicting_baseline_xml_reference')
    longitude_spacing = _number(tree, 'spref/horizsys/geograph/longres')
    latitude_spacing = _number(tree, 'spref/horizsys/geograph/latres')
    # Older XML uses positive latitude spacing; the north-up raster supplies sign.
    # Longitude spacing must remain eastward, as in every audited B01 record.
    if (abs(longitude_spacing - raster.transform.a) > 1e-12
            or abs(abs(latitude_spacing) - abs(raster.transform.e)) > 1e-12):
        raise ValueError('conflicting_baseline_xml_resolution')
    for field, actual in (('rowcount', raster.height), ('colcount', raster.width), ('vrtcount', 1)):
        if _one(tree, 'spdoinfo/rastinfo/' + field) != str(actual):
            raise ValueError('elevation_xml_raster_mismatch')
    for field, actual in zip(('westbc', 'southbc', 'eastbc', 'northbc'), raster.bounds):
        if abs(_number(tree, 'idinfo/spdom/bounding/' + field) - actual) > 1e-8:
            raise ValueError('elevation_xml_footprint_mismatch')
    start = _date(tree, 'idinfo/timeperd/timeinfo/rngdates/begdate')
    end = _date(tree, 'idinfo/timeperd/timeinfo/rngdates/enddate')
    if ((start is None) != (end is None) or start is not None and start > end
            or tile['collection_date'] is not None and not start == end == tile['collection_date']):
        raise ValueError('conflicting_elevation_xml_dates')
    return dict(height_evidence_basis='reviewed_xml_declaration', xml_evidence=dict(evidence),
                xml_source_title=title, xml_download_url=url, xml_publication_date=publication,
                xml_revision_date=revision,
                xml_publication_date_precision=precision, xml_collection_start=start, xml_collection_end=end,
                source_use_constraints=_one(tree, 'idinfo/useconst', optional=True),
                source_vertical_accuracy=_one(tree, 'dataqual/posacc/vertacc/vertaccr', optional=True),
                height_qualification='Source-declared NAVD88 meters; realization, numerical accuracy and '
                                     'transformation lineage remain unverified. No precision conversion or model admission.')


def elevation(reader, latitude, longitude, tile_id):
    """Read one native geographic pixel; conflicts and missing evidence never fall back."""
    tile, path = reader._artifact('B01', tile_id=tile_id)
    fields = dict(tile_id=tile_id, collection_date=tile['collection_date'],
                  units=tile['units'], vertical_datum=tile['vertical_datum'])
    import rasterio
    from rasterio.windows import Window
    from pyproj import CRS
    north, west = validate_tile_identity(tile_id, tile)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO'):
        with rasterio.open(path, driver='GTiff', GEOREF_SOURCES='INTERNAL') as ds:
            crs = CRS(ds.crs) if ds.crs else None
            if (crs is None or not crs.to_2d().equals(CRS('EPSG:4269'))
                    or not crs.to_2d().equals(CRS(reader.entries['B01']['horizontal_crs']))
                    or (ds.width, ds.height) != (SIZE, SIZE) or ds.count != 1
                    or ds.dtypes != ('float32',) or ds.nodata != -999999
                    or ds.scales != (1.0,) or ds.offsets != (0.0,)
                    or not all(math.isfinite(v) for v in ds.transform)
                    or abs(ds.transform.a - CELL_DEGREES) > 1e-12
                    or abs(ds.transform.e + CELL_DEGREES) > 1e-12
                    or ds.transform.b or ds.transform.d
                    or abs(ds.transform.c - (west - BUFFER * CELL_DEGREES)) > 1e-8
                    or abs(ds.transform.f - (north + BUFFER * CELL_DEGREES)) > 1e-8
                    or list(ds.bounds) != tile['bounds']
                    or any(a * b * 4 > ref.MAX_BLOCK for a, b in ds.block_shapes)):
                raise ValueError('incompatible_baseline_raster')
            x, y = ref._project(crs.to_2d(), latitude, longitude)
            row, col = ds.index(x, y)
            if not (0 <= row < ds.height and 0 <= col < ds.width):
                return reader._result('B01', 'outside_coverage', **fields)
            if 'height_evidence' not in tile:
                return reader._result('B01', 'unavailable', reason='baseline_xml_evidence_required', **fields)
            evidence = read_evidence(reader, tile_id, tile, ds)
            if any(unit is not None and unit not in ('m', 'metre', 'meter')
                   for unit in (ds.units[0], tile['units'])):
                raise ValueError('conflicting_elevation_units')
            vertical = [c for c in crs.sub_crs_list if c.is_vertical]
            if (len(vertical) > 1 or any(not v.equals(CRS('EPSG:5703')) for v in vertical)
                    or tile['vertical_datum'] is not None
                    and not CRS(tile['vertical_datum']).equals(CRS('EPSG:5703'))):
                raise ValueError('conflicting_elevation_vertical_datum')
            fields.update(evidence, units='m', vertical_datum='EPSG:5703')
            value = ds.read(1, window=Window(col, row, 1, 1), masked=True)
            number = float(value.data[0, 0])
            if value.mask.any() or number == ds.nodata or not math.isfinite(number):
                return reader._result('B01', 'unavailable', reason='source_nodata', **fields)
            fields.update(resolution_arcseconds=1 / 3,
                          pixel_size_degrees=[ds.transform.a, -ds.transform.e])
    return reader._result('B01', 'ok', elevation_m=number,
                          sampling='native_containing_pixel', **fields)
