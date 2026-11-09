"""Pinned, reviewed USGS B03/B04 height declarations for reference-only reads.

Optional tile height_evidence records contain kind, reviewed, path, bytes,
sha256, tile_sha256, units and vertical_datum. They never enroll a source.
Only the audited FGDC declaration is supported; changed wording needs review.
"""
from datetime import datetime
import hashlib
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from . import dataset_paths

MAX_XML = 64 * 1024
PROJECTS = {'B03': 'CA_NorthernCA_B22', 'B04': 'CA_NorthCoastRanges_B23'}
KIND = 'usgs_3dep_fgdc_v1'
# Whitespace-normalized abstract shared by all 126 audited sidecars.
ABSTRACT_SHA256 = '239210c54c653ec734f22ffcf0c01fc16367d1afc0ec78450f9ef176ab8ba745'
DOCTYPE = '<!DOCTYPE metadata SYSTEM "https://www.fgdc.gov/schemas/metadata/fgdc-std-001-1998.dtd">'
NETWORK_PATH = 'distinfo/stdorder/digform/digtopt/onlinopt/computer/networka/networkr'
# Explicit optional declarations must agree with the audited NAD83/UTM 10N
# metadata. Their absence does not establish a datum realization or accuracy.
HORIZONTAL_TEXT = {
    'geodetic/horizdn': {'North_American_Datum_1983'},
    'geodetic/ellips': {'GRS 1980'},
    'planar/planci/plandu': {'m', 'meter', 'meters', 'metre', 'metres'},
}
HORIZONTAL_NUMBERS = {
    'geodetic/semiaxis': 6378137.0,
    'geodetic/denflat': 298.257222101,
    'planar/gridsys/utm/transmer/sfctrmer': 0.9996,
    'planar/gridsys/utm/transmer/longcm': -123.0,
    'planar/gridsys/utm/transmer/latprjo': 0.0,
    'planar/gridsys/utm/transmer/feast': 500000.0,
    'planar/gridsys/utm/transmer/fnorth': 0.0,
}


def validate_evidence(root, batch, tile_id, tile):
    """Validate explicit review and TIFF/XML pins without reading a sidecar."""
    evidence = tile.get('height_evidence')
    if (not isinstance(evidence, dict) or evidence.get('kind') != KIND
            or evidence.get('reviewed') is not True or evidence.get('units') != 'm'
            or evidence.get('vertical_datum') != 'EPSG:5703'
            or evidence.get('tile_sha256') != tile['sha256']
            or type(evidence.get('bytes')) is not int or not 0 < evidence['bytes'] <= MAX_XML
            or not isinstance(evidence.get('sha256'), str)
            or not re.fullmatch('[a-f0-9]{64}', evidence['sha256'])):
        raise ValueError('invalid_elevation_xml_evidence')
    project = PROJECTS[batch]
    if (not re.fullmatch(r'USGS_1M_10_x\d+y\d+_' + re.escape(project), tile_id)
            or Path(tile['path']).stem != tile_id):
        raise ValueError('elevation_xml_tile_mismatch')
    path = dataset_paths.checked_path(root, evidence.get('path'), allow_reference=True)
    if path.name != tile_id + '.xml':
        raise ValueError('elevation_xml_tile_mismatch')
    return evidence, path


def _one(tree, path, *, optional=False):
    """Read one bounded leaf; duplicate fields never silently select a value."""
    nodes = tree.findall(path)
    if optional and not nodes:
        return None
    if len(nodes) != 1 or len(nodes[0]) or not nodes[0].text:
        raise ValueError('ambiguous_or_missing_elevation_xml_field')
    value = ' '.join(nodes[0].text.split())
    if not value or len(value) > 4096:
        raise ValueError('invalid_elevation_xml_field')
    return value


def _date(tree, path):
    """Keep absent source dates unknown; reject malformed recorded dates."""
    value = _one(tree, path, optional=True)
    if value is None:
        return None
    if not re.fullmatch(r'\d{8}', value):
        raise ValueError('invalid_elevation_xml_date')
    try:
        return datetime.strptime(value, '%Y%m%d').date().isoformat()
    except ValueError as exc:
        raise ValueError('invalid_elevation_xml_date') from exc


def _footprint(tree, raster):
    """Check the XML nominal footprint while retaining native raster buffers."""
    from pyproj import Transformer, network
    network.set_network_enabled(False)
    inset = 6 if (raster.width, raster.height) == (10012, 10012) else 0
    corners = [raster.transform * (col, row)
               for col in (inset, raster.width - inset)
               for row in (inset, raster.height - inset)]
    operation = Transformer.from_crs('EPSG:26910', 'EPSG:4326', always_xy=True,
                                     allow_ballpark=False)
    geographic = [operation.transform(x, y, errcheck=True) for x, y in corners]
    expected = (min(p[0] for p in geographic), min(p[1] for p in geographic),
                max(p[0] for p in geographic), max(p[1] for p in geographic))
    try:
        declared = [float(_one(tree, 'idinfo/spdom/bounding/' + field))
                    for field in ('westbc', 'southbc', 'eastbc', 'northbc')]
    except ValueError as exc:
        raise ValueError('invalid_elevation_xml_bounds') from exc
    # Audited XML coordinates are rounded; this is about a millimeter locally.
    if any(not math.isfinite(value) or abs(value - target) > 1e-8
           for value, target in zip(declared, expected)):
        raise ValueError('elevation_xml_footprint_mismatch')


def _horizontal_details(tree):
    """Reject explicit details that conflict with the source's grid-system label."""
    for field, supported in HORIZONTAL_TEXT.items():
        value = _one(tree, 'spref/horizsys/' + field, optional=True)
        if value is not None and value not in supported:
            raise ValueError('conflicting_elevation_xml_horizontal_reference')
    for field, expected in HORIZONTAL_NUMBERS.items():
        value = _one(tree, 'spref/horizsys/' + field, optional=True)
        if value is None:
            continue
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError('conflicting_elevation_xml_horizontal_reference') from exc
        if not math.isfinite(number) or number != expected:
            raise ValueError('conflicting_elevation_xml_horizontal_reference')


def read_evidence(reader, batch, tile_id, tile, raster):
    """Verify pinned XML identity and declarations without fetching external DTDs.

Raster geometry remains authoritative. XML nominal footprints do not crop the
six-pixel buffers present in many audited tiles. No height transform is applied.
"""
    evidence, path = validate_evidence(reader.root, batch, tile_id, tile)
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
    try:
        text = raw.decode('utf-8-sig')
        if text.count(DOCTYPE) > 1:
            raise ValueError('unsupported_elevation_xml_declaration')
        # Strip only the audited inert DTD reference. Reject entities, internal
        # subsets and other declarations before invoking the standard parser.
        text = text.replace(DOCTYPE, '')
        if '<!' in text:
            raise ValueError('unsupported_elevation_xml_declaration')
        tree = ET.fromstring(text)
    except (UnicodeError, ET.ParseError) as exc:
        raise ValueError('invalid_elevation_xml') from exc
    if tree.tag != 'metadata':
        raise ValueError('unsupported_elevation_xml_schema')
    project = PROJECTS[batch]
    tile_code = tile_id.removeprefix('USGS_1M_10_').removesuffix('_' + project)
    title = _one(tree, 'idinfo/citation/citeinfo/title')
    url = _one(tree, NETWORK_PATH)
    expected_url = ('https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/'
                    + project + '/TIFF/' + tile_id + '.tif')
    if (title != 'USGS 1 Meter 10 ' + tile_code + ' ' + project or url != expected_url
            or _one(tree, 'idinfo/citation/citeinfo/origin') != 'U.S. Geological Survey'
            or _one(tree, 'idinfo/citation/citeinfo/pubinfo/publish') != 'U.S. Geological Survey'):
        raise ValueError('elevation_xml_source_mismatch')
    abstract = _one(tree, 'idinfo/descript/abstract')
    if (hashlib.sha256(abstract.encode()).hexdigest() != ABSTRACT_SHA256
            or tree.findall('.//vertdef')):
        raise ValueError('unsupported_elevation_xml_declaration')
    if (_one(tree, 'spref/horizsys/planar/gridsys/gridsysn') != 'NAD83 / UTM zone 10N'
            or _one(tree, 'spref/horizsys/planar/gridsys/utm/utmzone') != '10'
            or _one(tree, 'spdoinfo/rastinfo/rowcount') != str(raster.height)
            or _one(tree, 'spdoinfo/rastinfo/colcount') != str(raster.width)
            or _one(tree, 'spdoinfo/rastinfo/vrtcount') != '1'):
        raise ValueError('elevation_xml_raster_mismatch')
    _horizontal_details(tree)
    _footprint(tree, raster)
    publication = _date(tree, 'idinfo/citation/citeinfo/pubdate')
    start = _date(tree, 'idinfo/timeperd/timeinfo/rngdates/begdate')
    end = _date(tree, 'idinfo/timeperd/timeinfo/rngdates/enddate')
    if ((start is None) != (end is None) or start is not None and start > end
            or tile['collection_date'] is not None and not start == end == tile['collection_date']):
        raise ValueError('conflicting_elevation_xml_dates')
    return dict(height_evidence_basis='reviewed_xml_declaration',
                xml_evidence=dict(evidence), xml_source_title=title, xml_download_url=url,
                xml_publication_date=publication, xml_collection_start=start, xml_collection_end=end,
                source_use_constraints=_one(tree, 'idinfo/useconst', optional=True),
                source_vertical_accuracy=_one(tree, 'dataqual/posacc/vertacc/vertaccr', optional=True),
                height_qualification='Source-declared NAVD88 meters; realization, numerical accuracy and '
                                     'transformation lineage remain unverified. No precision conversion or model admission.')
