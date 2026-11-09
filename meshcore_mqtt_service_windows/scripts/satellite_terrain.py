"""Read local, explicitly qualified GeoTIFF terrain without network or fallback heights."""
from contextlib import contextmanager
import hashlib
import math
from pathlib import Path
import re
import time
import warnings

from . import reference_policy

MAX_BYTES = 128 * 1024 * 1024
MAX_RASTER_PIXELS = 100_000_000
MAX_BLOCK_BYTES = 16 * 1024 * 1024
UNITS = {'m': 1.0, 'ft': 0.3048, 'us_survey_ft': 1200 / 3937}


def fingerprint(path, deadline):
    """Bound and hash a local input; returned evidence also detects replacement."""
    reference_policy.reject_path(path)
    before = path.stat()
    if not path.is_file() or before.st_size > MAX_BYTES:
        raise ValueError('Terrain input exceeds limit')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            if time.monotonic() > deadline:
                raise ValueError('Terrain verification time limit')
            digest.update(block)
    after = path.stat()
    if (after.st_size, after.st_mtime_ns, after.st_ino) != (before.st_size, before.st_mtime_ns, before.st_ino):
        raise ValueError('Terrain changed; retry')
    return before.st_size, before.st_mtime_ns, digest.hexdigest()


def source_entries(settings):
    """Validate the bounded source identity list before selecting any files."""
    configuration = settings.get('pointing', {})
    if not isinstance(configuration, dict):
        raise ValueError('Invalid terrain configuration')
    entries = configuration.get('terrain_sources', [])
    if not isinstance(entries, list) or not 0 < len(entries) <= 4:
        raise ValueError('GIS terrain unavailable')
    ids = set()
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or
                not re.fullmatch(r'[A-Za-z0-9_-]{1,12}', entry['id'])):
            raise ValueError('Invalid terrain source identity')
        if entry['id'] in ids:
            raise ValueError('Conflicting terrain source IDs')
        ids.add(entry['id'])
    return entries


def sources(settings, base, selector=None):
    """Validate operator-configured local sources; no source is enabled by default.

    Each pointing.terrain_sources entry requires id, path, sha256, bytes,
    vertical_crs, units and source (provenance). Raster georeferencing supplies
    the horizontal CRS. EPSG:4979 denotes WGS84 ellipsoidal terrain heights;
    an orthometric source requires an explicit vertical CRS and local PROJ grids.
    """
    entries = source_entries(settings)
    if selector is not None:
        entries = [entry for entry in entries if entry['id'] == selector]
        if not entries:
            raise ValueError('Unknown terrain source ID')
    result = []
    for entry in entries:
        reference_policy.reject_metadata(entry)
        reference_policy.reject_path(base / entry['path'])
        path = (base / entry['path']).resolve()
        if '.datasets' in path.parts:
            raise ValueError('Managed terrain generation unsupported; no receipt contract')
        if path.suffix.lower() not in {'.tif', '.tiff'} or not path.is_file():
            raise ValueError('Local GeoTIFF terrain unavailable')
        if (entry.get('units') not in UNITS or not entry.get('vertical_crs') or
                not isinstance(entry.get('source'), str) or not entry['source'].strip() or
                type(entry.get('bytes')) is not int or not 0 < entry['bytes'] <= MAX_BYTES or
                not re.fullmatch('[0-9a-f]{64}', str(entry.get('sha256', '')))):
            raise ValueError('Terrain units, datum, provenance or integrity metadata unavailable')
        result.append(dict(entry, path=path))
    return result


def raster_metadata(raster, vertical):
    """Reject oversized decoding work and incompatible embedded vertical metadata."""
    import numpy as np
    from pyproj import CRS
    if raster.driver != 'GTiff' or raster.count != 1 or raster.crs is None:
        raise ValueError('Unsupported terrain schema or horizontal CRS')
    dtype = np.dtype(raster.dtypes[0])
    if dtype.kind not in {'i', 'u', 'f'}:
        raise ValueError('Unsupported terrain numeric type')
    if not 0 < raster.width * raster.height <= MAX_RASTER_PIXELS:
        raise ValueError('Terrain raster dimensions exceed limit')
    if any(not 0 < rows * cols * dtype.itemsize <= MAX_BLOCK_BYTES for rows, cols in raster.block_shapes):
        raise ValueError('Terrain raster block exceeds decoding limit')
    if (not all(math.isfinite(value) for value in raster.transform) or raster.transform.determinant == 0):
        raise ValueError('Invalid terrain georeferencing')
    embedded = CRS(raster.crs)
    if embedded.is_compound:
        axes = [part for part in embedded.sub_crs_list if part.is_vertical]
        if len(axes) != 1 or not axes[0].equals(vertical):
            raise ValueError('Conflicting embedded vertical datum')
    elif len(embedded.axis_info) == 3:
        if not embedded.equals(CRS('EPSG:4979')) or vertical != CRS('EPSG:4979'):
            raise ValueError('Conflicting embedded vertical datum')
    if vertical != CRS('EPSG:4979') and (not vertical.is_vertical or len(vertical.axis_info) != 1 or
            vertical.axis_info[0].direction != 'up' or vertical.axis_info[0].unit_conversion_factor != 1):
        raise ValueError('Unsupported vertical CRS; require upward metres')
    horizontal = embedded.to_2d()
    if not (horizontal.is_geographic or horizontal.is_projected):
        raise ValueError('Unsupported terrain horizontal CRS')
    return horizontal


def band_units(value):
    """Normalize GDAL unit spellings without conflating international and survey feet."""
    aliases = {'metre': 'm', 'meter': 'm', 'metres': 'm', 'meters': 'm',
               'foot': 'ft', 'feet': 'ft', 'us survey foot': 'us_survey_ft', 'us survey feet': 'us_survey_ft'}
    key = value.strip().casefold()
    return aliases.get(key, key)


def transformer(source, target, latitude, longitude):
    """Require an available non-ballpark local transformation at this location."""
    from pyproj import network
    from pyproj.aoi import AreaOfInterest
    from pyproj.transformer import TransformerGroup
    network.set_network_enabled(False)
    area = AreaOfInterest(max(-180, longitude - .00001), max(-90, latitude - .00001),
                          min(180, longitude + .00001), min(90, latitude + .00001))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        group = TransformerGroup(source, target, always_xy=True, area_of_interest=area, allow_ballpark=False)
    if not group.best_available or not group.transformers:
        raise ValueError('Required local datum transformation unavailable')
    return group.transformers[0]


def pin_grids(operation, pins, deadline):
    """Pin any installed grids used by either horizontal or vertical conversion."""
    for step in operation.operations:
        for grid in step.grids:
            path = Path(grid.full_name)
            if not grid.available or not path.is_file():
                raise ValueError('Required local datum grid unavailable')
            evidence = fingerprint(path, deadline)
            if path in pins and pins[path] != evidence:
                raise ValueError('Datum grid changed; retry')
            pins[path] = evidence


def sample(entry, latitude, longitude, pins, deadline):
    """Sample the containing pixel, without interpolation or nearest-valid substitution.

    East/south outer edges are excluded by the raster's half-open pixel bounds.
    Internal masks and NoData are honored; external sidecars are disabled.
    """
    reference_policy.reject_metadata(entry)
    reference_policy.reject_path(entry['path'])
    import rasterio
    from rasterio.windows import Window
    from pyproj import CRS
    from pyproj.crs import CompoundCRS
    path = entry['path']
    evidence = fingerprint(path, deadline)
    if evidence[0] != entry['bytes'] or evidence[2] != entry['sha256']:
        raise ValueError('Terrain integrity failure')
    pins[path] = evidence
    with path.open('rb') as stream:
        if stream.read(4) not in (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+'):
            raise ValueError('Unsupported terrain file')
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO',
                      GTIFF_POINT_GEO_IGNORE='FALSE'):
        with rasterio.open(path, driver='GTiff', GEOREF_SOURCES='INTERNAL') as raster:
            vertical = CRS(entry['vertical_crs'])
            horizontal = raster_metadata(raster, vertical)
            projected = transformer('EPSG:4326', horizontal, latitude, longitude)
            pin_grids(projected, pins, deadline)
            x, y = projected.transform(longitude, latitude, errcheck=True)
            row, col = raster.index(x, y)
            if not 0 <= row < raster.height or not 0 <= col < raster.width:
                return None
            value = raster.read(1, window=Window(col, row, 1, 1), masked=True)
            if value.mask.any():
                raise ValueError('Terrain NoData at observer location')
            scale, offset = raster.scales[0], raster.offsets[0]
            height = (float(value[0, 0]) * scale + offset) * UNITS[entry['units']]
            band_unit = raster.units[0]
            if band_unit and band_units(band_unit) != entry['units']:
                raise ValueError('Conflicting terrain units')
            if not math.isfinite(height) or not -12000 <= height <= 10000:
                raise ValueError('Invalid terrain height')
            if vertical == CRS('EPSG:4979'):
                if not horizontal.geodetic_crs.equals(CRS('EPSG:4326'), ignore_axis_order=True):
                    raise ValueError('Ellipsoidal terrain requires a WGS84 horizontal datum')
                ellipsoid = height
                conversion = 'WGS84 ellipsoid; no vertical shift'
            else:
                compound = CompoundCRS('Terrain', [horizontal, vertical])
                conversion_op = transformer(compound, 'EPSG:4979', latitude, longitude)
                # Grid files are immutable query inputs too; no download or repair.
                pin_grids(conversion_op, pins, deadline)
                lon, lat, ellipsoid = conversion_op.transform(x, y, height, errcheck=True)
                if abs(lat - latitude) > .001 or abs(lon - longitude) > .001:
                    raise ValueError('Incompatible vertical transformation location')
                conversion = conversion_op.description
            if not math.isfinite(ellipsoid) or not -13000 <= ellipsoid <= 11000:
                raise ValueError('Invalid transformed terrain height')
            return dict(source_id=entry['id'], source=entry['source'], horizontal_crs=horizontal.to_string(),
                        vertical_crs=entry['vertical_crs'], source_units=entry['units'],
                        terrain_height_m=height, ellipsoid_height_m=ellipsoid,
                        resolution=list(raster.res), resolution_units=horizontal.axis_info[0].unit_name,
                        sampling='containing pixel; no interpolation', transformation=conversion)


@contextmanager
def terrain(settings, base, latitude, longitude, selector=None):
    """Pin one unambiguous terrain source and its local transformation inputs."""
    entries = sources(settings, base, selector)
    deadline = time.monotonic() + 12
    pins = {}
    matches = []
    for entry in entries:
        value = sample(entry, latitude, longitude, pins, deadline)
        if value is not None:
            matches.append(value)
    if not matches:
        raise ValueError('GIS terrain outside source coverage')
    if len(matches) != 1:
        raise ValueError('Select terrain ' + ','.join(value['source_id'] for value in matches))
    yield matches[0]
    deadline = time.monotonic() + 12
    for path, before in pins.items():
        if fingerprint(path, deadline) != before:
            raise ValueError('Terrain or datum grid changed; retry')
