"""Explicit, offline B01/B03-B11 references; no installation or operational discovery.

Catalog schema 1 resides at .reference-only/reference-catalog.json, declares
kind restricted_reference_catalog, generation, complete=true and entries keyed
by batch. Each entry pins path, bytes, sha256, source, version, source_date,
horizontal_crs, coverage_note and allowed_uses. B08 declares kind wbd_boundary
and use boundary_reference; B09 declares kind nlcd_land_cover, year 2025 and use
land_cover_reference. B10 declares kind nlcd_fractional_impervious, year 2025,
units percent and use impervious_reference. B11 declares kind nlcd_land_cover_confidence,
year 2025, units unitless and use land_cover_confidence_reference.
Files must remain inside the reserved root. No default
root, current-generation pointer, acquisition, writer or MeshCore command exists.
B01/B03/B04 use bounded tile inventories instead of a single artifact. Their tile
units, vertical datum and collection date may be explicitly unknown. B05-B07
use single pinned artifacts; the environmental readers never join operational data.
"""
import hashlib
from datetime import date
import json
import math
from pathlib import Path
import re
import sqlite3
import struct
import time

from . import dataset_paths, reference_policy as policy

# Bound total catalog bytes independently of per-collection tile and XML limits.
MAX_CATALOG = 256 * 1024
MAX_ARTIFACT = 2 * 1024 ** 3
# The staged B11 TIFF exceeds 7 GiB; other collections retain the smaller limit.
MAX_CONFIDENCE_ARTIFACT = 8 * 1024 ** 3
ENVIRONMENT_LIMITS = {'B05': 64 * 1024 ** 2, 'B06': 6 * 1024 ** 3, 'B07': 3 * 1024 ** 3}
MAX_TILES = 128
MAX_GEOMETRY = 16 * 1024 ** 2
MAX_GEOMETRY_TOTAL = 64 * 1024 ** 2
MAX_CANDIDATES = 128
MAX_BLOCK = 16 * 1024 ** 2
SECONDS = 30
# Recorded B09-B11 projection; NAD83 Albers (EPSG:5070) is a different datum.
LAND_COVER_CRS = '+proj=aea +lat_1=29.5 +lat_2=45.5 +lat_0=23 +lon_0=-96 +datum=WGS84 +units=m'
USES = {'B01': ('usgs_elevation_reference', 'elevation_reference', '.tif'),
        'B03': ('usgs_elevation_reference', 'elevation_reference', '.tif'),
        'B04': ('usgs_elevation_reference', 'elevation_reference', '.tif'),
        'B05': ('geoid18_reference', 'geoid_reference', '.bin'),
        'B06': ('ssurgo_reference', 'soil_reference', '.gpkg'),
        'B07': ('nhdplus_reference', 'hydrography_reference', '.gpkg'),
        'B08': ('wbd_boundary', 'boundary_reference', '.gpkg'),
        'B09': ('nlcd_land_cover', 'land_cover_reference', '.tif'),
        'B10': ('nlcd_fractional_impervious', 'impervious_reference', '.tif'),
        'B11': ('nlcd_land_cover_confidence', 'land_cover_confidence_reference', '.tif')}
CLASSES = {11: 'Open Water', 12: 'Perennial Ice/Snow', 21: 'Developed, Open Space',
           22: 'Developed, Low Intensity', 23: 'Developed, Medium Intensity',
           24: 'Developed, High Intensity', 31: 'Barren Land', 41: 'Deciduous Forest',
           42: 'Evergreen Forest', 43: 'Mixed Forest', 52: 'Shrub/Scrub',
           71: 'Grassland/Herbaceous', 81: 'Pasture/Hay', 82: 'Cultivated Crops',
           90: 'Woody Wetlands', 95: 'Emergent Herbaceous Wetlands'}
QUALIFICATION = ('Recorded geographic reference only; not flood-model input, '
                 'hydrologic connectivity, current conditions or precision terrain.')


def _unique(pairs):
    """Reject duplicate JSON keys rather than silently replacing a policy or pin."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_catalog_key')
        result[key] = value
    return result


def _invalid_number(value):
    """Reject nonfinite JSON literals in catalog metadata."""
    raise ValueError('invalid_catalog_number')


def _text(value, maximum=500):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('invalid_reference_metadata')
    return value


def _coordinates(latitude, longitude):
    """Reject booleans, nonfinite values and coordinates outside geographic bounds."""
    if (type(latitude) not in (int, float) or type(longitude) not in (int, float)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError('invalid_coordinates')


def _level(level):
    if type(level) is not int or level not in (2, 4, 6, 8, 10, 12, 14, 16):
        raise ValueError('explicit_huc_level_required')
    return level


def _project(crs, latitude, longitude):
    """Use available offline horizontal operations only; never convert heights."""
    from pyproj import Transformer, network
    network.set_network_enabled(False)
    operation = Transformer.from_crs('EPSG:4326', crs, always_xy=True, allow_ballpark=False)
    x, y = operation.transform(longitude, latitude, errcheck=True)
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError('coordinate_transform_unavailable')
    return x, y


def _sql_text(column, maximum):
    """Bound source text in SQLite before allocating result fields in Python.

    Column expressions come only from fixed or validated identifiers.
    """
    return f'CASE WHEN typeof({column})=\'text\' AND length({column})<={maximum} THEN {column} END'


class Catalog:
    """Pin catalog and consumed artifacts for one bounded read transaction.

Construct a new instance for each query. Hashes are verified before GIS decoding;
path and stat pins are rechecked before returning. Failure never falls back to
another source. Large raster dimensions are allowed, but only one bounded native
block is sampled. Catalog discovery reads no GIS artifacts or optional libraries.
"""

    def __init__(self, root):
        self.requested_root = Path(root).absolute()
        self.root = self.requested_root.resolve()
        if self.root.name.casefold() != policy.DIRECTORY:
            raise ValueError('reserved_reference_root_required')
        self.until = time.monotonic() + SECONDS
        self.pins = {}
        self.paths = {}
        path = dataset_paths.checked_path(self.root, policy.CATALOG, allow_reference=True)
        self.paths[policy.CATALOG] = path
        if path.stat().st_size > MAX_CATALOG:
            raise ValueError('catalog_size_limit')
        self._remember(path)
        with path.open('rb') as stream:
            raw = stream.read(MAX_CATALOG + 1)
        if len(raw) > MAX_CATALOG:
            raise ValueError('catalog_size_limit')
        self.document = json.loads(raw, object_pairs_hook=_unique,
                                   parse_constant=_invalid_number)
        doc = self.document
        if (not isinstance(doc, dict) or type(doc.get('schema_version')) is not int
                or doc['schema_version'] != 1 or doc.get('kind') != 'restricted_reference_catalog'
                or doc.get('complete') is not True):
            raise ValueError('incompatible_reference_catalog')
        _text(doc.get('generation'), 80)
        entries = doc.get('entries')
        if not isinstance(entries, dict) or not entries or set(entries) - USES.keys():
            raise ValueError('unsupported_reference_membership')
        self.entries = entries
        for batch, entry in entries.items():
            kind, use, suffix = USES[batch]
            if (not isinstance(entry, dict) or entry.get('kind') != kind
                    or entry.get('allowed_uses') != [use]
                    or entry.get('prohibited_uses') != ['flood_modelling', 'satellite_terrain', 'operational_fallback']):
                raise ValueError('invalid_reference_purpose_policy')
            for field in ('source', 'version', 'source_date', 'coverage_note'):
                _text(entry.get(field))
            _text(entry.get('horizontal_crs'), 4096)
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', entry['source_date']):
                raise ValueError('invalid_source_date')
            date.fromisoformat(entry['source_date'])
            if batch in ('B01', 'B03', 'B04'):
                tiles = entry.get('tiles')
                if not isinstance(tiles, dict) or not 0 < len(tiles) <= MAX_TILES:
                    raise ValueError('invalid_tile_inventory')
                paths = set()
                for identifier, tile in tiles.items():
                    if not isinstance(identifier, str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', identifier):
                        raise ValueError('invalid_tile_identity')
                    artifact = self._validate_pin(batch, tile)
                    if batch == 'B01':
                        from .reference_elevation_baseline import validate_tile_identity
                        validate_tile_identity(identifier, tile)
                    if artifact in paths:
                        raise ValueError('duplicate_tile_artifact')
                    paths.add(artifact)
                    bounds = tile.get('bounds')
                    if (not isinstance(bounds, list) or len(bounds) != 4
                            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
                            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
                        raise ValueError('invalid_tile_bounds')
                    for field in ('units', 'vertical_datum', 'collection_date'):
                        if field not in tile:
                            raise ValueError('missing_tile_metadata')
                        if tile[field] is not None:
                            _text(tile[field], 100)
                    if tile['collection_date'] is not None:
                        date.fromisoformat(tile['collection_date'])
                    if 'height_evidence' in tile:
                        if batch == 'B01':
                            from .reference_elevation_baseline import validate_evidence
                        else:
                            from .reference_elevation_xml import validate_evidence
                        validate_evidence(self.root, batch, identifier, tile)
            else:
                self._validate_pin(batch, entry)
            if batch == 'B09' and (type(entry.get('year')) is not int or entry['year'] != 2025):
                raise ValueError('unsupported_land_cover_vintage')
            if batch == 'B10':
                if type(entry.get('year')) is not int or entry['year'] != 2025:
                    raise ValueError('unsupported_impervious_vintage')
                if entry.get('units') != 'percent':
                    raise ValueError('incompatible_impervious_units')
            if batch == 'B11':
                if type(entry.get('year')) is not int or entry['year'] != 2025:
                    raise ValueError('unsupported_confidence_vintage')
                if entry.get('units') != 'unitless':
                    raise ValueError('incompatible_confidence_units')
        self._finish()

    def _validate_pin(self, batch, entry):
        """Validate one bounded artifact declaration without reading its payload."""
        maximum = MAX_CONFIDENCE_ARTIFACT if batch == 'B11' else ENVIRONMENT_LIMITS.get(batch, MAX_ARTIFACT)
        if (not isinstance(entry, dict) or type(entry.get('bytes')) is not int
                or not 0 < entry['bytes'] <= maximum or not isinstance(entry.get('sha256'), str)
                or not re.fullmatch('[a-f0-9]{64}', entry['sha256'])):
            raise ValueError('invalid_artifact_pin')
        artifact = dataset_paths.checked_path(self.root, entry.get('path'), allow_reference=True)
        if artifact.suffix.lower() != USES[batch][2] or artifact == self.paths[policy.CATALOG]:
            raise ValueError('unsupported_reference_artifact')
        return artifact

    def _tick(self):
        if time.monotonic() > self.until:
            raise ValueError('reference_query_time_limit')

    @staticmethod
    def _signature(path):
        s = path.stat()
        return (path.resolve(), s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino)

    def _remember(self, path):
        signature = self._signature(path)
        if path in self.pins and self.pins[path] != signature:
            raise ValueError('reference_changed_during_query')
        self.pins[path] = signature

    def _finish(self):
        self._tick()
        if self.requested_root.resolve() != self.root:
            raise ValueError('reference_root_changed')
        for relative, selected in self.paths.items():
            if dataset_paths.checked_path(self.root, relative, allow_reference=True) != selected:
                raise ValueError('reference_path_changed')
        for path, signature in self.pins.items():
            if self._signature(path) != signature:
                raise ValueError('reference_changed_during_query')

    def _artifact(self, batch, *, tile_id=None):
        self._tick()
        if batch not in self.entries:
            raise ValueError('reference_source_unavailable')
        entry = self.entries[batch]
        if batch in ('B01', 'B03', 'B04'):
            if tile_id not in entry['tiles']:
                raise ValueError('exact_tile_identity_required')
            entry = entry['tiles'][tile_id]
        path = dataset_paths.checked_path(self.root, entry['path'], allow_reference=True)
        self.paths[entry['path']] = path
        self._remember(path)
        if path.stat().st_size != entry['bytes']:
            raise ValueError('reference_integrity_failure')
        digest = hashlib.sha256()
        consumed = 0
        with path.open('rb') as stream:
            while True:
                self._tick()
                block = stream.read(min(1024 * 1024, entry['bytes'] + 1 - consumed))
                if not block:
                    break
                consumed += len(block)
                if consumed > entry['bytes']:
                    raise ValueError('reference_integrity_failure')
                digest.update(block)
        if consumed != entry['bytes'] or digest.hexdigest() != entry['sha256']:
            raise ValueError('reference_integrity_failure')
        self._finish()
        return entry, path

    def _result(self, batch, status, **fields):
        self._finish()
        entry = self.entries[batch]
        qualification = QUALIFICATION
        if batch in ('B01', 'B03', 'B04'):
            qualification += ' Recorded source terrain only; no height conversion or gap filling.'
        if batch == 'B05':
            qualification += ' GEOID18 grid reference only; not terrain or an applied height conversion.'
        if batch == 'B06':
            qualification += ' Survey soil properties; not current saturation, infiltration or runoff rates.'
        if batch == 'B07':
            qualification += ' Recorded hydrography only; no routing, station association or live flow inference.'
        if batch == 'B10':
            qualification += (' Impervious percentage is not runoff or infiltration; '
                              'zero does not imply zero runoff.')
        if batch == 'B11':
            qualification += (' Unitless confidence in the primary land-cover class; '
                              'not calibrated probability, percentage accuracy or '
                              'impervious-surface confidence.')
        return dict(status=status, batch=batch, generation=self.document['generation'],
                    source=entry['source'], version=entry['version'], source_date=entry['source_date'],
                    horizontal_crs=entry['horizontal_crs'], coverage_note=entry['coverage_note'],
                    qualification=qualification, permitted_use=USES[batch][1], model_eligible=False, **fields)

    def discover(self):
        """Return declared membership, never an integrity or modelling approval."""
        self._finish()
        return [self._result(batch, 'declared', integrity='not_checked') for batch in sorted(self.entries)]

    def _nlcd_pixel(self, batch, latitude, longitude):
        """Read one native B09-B11 pixel, without overviews, resampling or sidecars.

        The caller interprets the raw code and finishes the pinned transaction.
        NoData and outside coverage remain distinct from numerical zero.
        """
        _coordinates(latitude, longitude)
        entry, path = self._artifact(batch)
        import rasterio
        from rasterio.windows import Window
        from pyproj import CRS
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO'):
            with rasterio.open(path, driver='GTiff', GEOREF_SOURCES='INTERNAL') as raster:
                if (raster.count != 1 or raster.dtypes != ('uint8',) or raster.crs is None
                        or not CRS(raster.crs).equals(CRS(entry['horizontal_crs']))
                        or not CRS(raster.crs).equals(CRS(LAND_COVER_CRS))
                        or raster.nodata != 250 or raster.scales != (1.0,) or raster.offsets != (0.0,)
                        or not all(math.isfinite(v) for v in raster.transform)
                        or raster.transform.b != 0 or raster.transform.d != 0
                        or raster.transform.a != 30 or raster.transform.e != -30
                        or any(rows * cols > MAX_BLOCK for rows, cols in raster.block_shapes)):
                    reason = {'B09': 'incompatible_land_cover_raster',
                              'B10': 'incompatible_impervious_raster',
                              'B11': 'incompatible_confidence_raster'}[batch]
                    raise ValueError(reason)
                x, y = _project(raster.crs, latitude, longitude)
                row, col = raster.index(x, y)
                if not 0 <= row < raster.height or not 0 <= col < raster.width:
                    return 'outside_coverage', None
                value = raster.read(1, window=Window(col, row, 1, 1), masked=True)
                # Internal masks can override GDAL's nodata-derived mask;
                # the recorded sentinel remains unavailable in either case.
                if value.mask.any() or value.data[0, 0] == raster.nodata:
                    return 'source_nodata', None
                return 'ok', int(value[0, 0])

    def land_cover(self, latitude, longitude):
        """Return one B09 native class without overview selection or interpolation."""
        status, code = self._nlcd_pixel('B09', latitude, longitude)
        year = self.entries['B09']['year']
        if status == 'outside_coverage':
            return self._result('B09', status, year=year)
        if status == 'source_nodata':
            return self._result('B09', 'unavailable', reason=status, year=year)
        if code not in CLASSES:
            return self._result('B09', 'unavailable', reason='unrecognized_source_class', raw_code=code, year=year)
        return self._result('B09', 'ok', year=year, code=code, description=CLASSES[code],
                            resolution_m=30, sampling='native_containing_pixel')

    def impervious_surface(self, latitude, longitude):
        """Return a recorded B10 percentage only; never derive hydrologic parameters."""
        status, value = self._nlcd_pixel('B10', latitude, longitude)
        fields = dict(year=self.entries['B10']['year'], units='percent')
        if status == 'outside_coverage':
            return self._result('B10', status, **fields)
        if status == 'source_nodata':
            return self._result('B10', 'unavailable', reason=status, **fields)
        if not 0 <= value <= 100:
            return self._result('B10', 'unavailable', reason='invalid_source_percentage', raw_code=value, **fields)
        return self._result('B10', 'ok', percent=value, resolution_m=30,
                            sampling='native_containing_pixel', **fields)

    def land_cover_confidence(self, latitude, longitude):
        """Return B11 scores or qualified source codes, without joining other products.

        The source defines scores 1-100 and additional interpretation above 100,
        except the NoData sentinel. Zero has no established interpretation.
        A special code never becomes a numerical score or a probability.
        """
        status, value = self._nlcd_pixel('B11', latitude, longitude)
        fields = dict(year=self.entries['B11']['year'], units='unitless')
        if status == 'outside_coverage':
            return self._result('B11', status, **fields)
        if status == 'source_nodata':
            return self._result('B11', 'unavailable', reason=status, **fields)
        fields.update(raw_code=value, resolution_m=30, sampling='native_containing_pixel')
        if value == 0:
            return self._result('B11', 'unavailable', reason='unresolved_zero_code', **fields)
        if value > 100:
            return self._result('B11', 'qualified', reason='additional_interpretation',
                                interpretation='Additional interpretation procedures used for the '
                                'primary land-cover label; code-specific meaning is not established.',
                                **fields)
        return self._result('B11', 'ok', confidence_score=value, **fields)

    def elevation_tiles(self, latitude, longitude):
        """Discover declared B03/B04 footprints without opening every source tile."""
        from . import reference_environment as environment
        return environment.elevation_tiles(self, latitude, longitude)

    def elevation(self, latitude, longitude, *, batch=None, tile_id=None):
        """Read one unambiguous tile only when native height evidence is sufficient."""
        from . import reference_environment as environment
        return environment.elevation(self, latitude, longitude, batch=batch, tile_id=tile_id)

    def geoid(self, latitude, longitude, *, coordinate_crs):
        """Read a nearest GEOID18 grid node in explicitly asserted NAD83(2011)."""
        from . import reference_environment as environment
        return environment.geoid(self, latitude, longitude, coordinate_crs=coordinate_crs)

    def soil_map_unit(self, mukey):
        """Read an exact recorded SSURGO map-unit identity."""
        from . import reference_environment as environment
        return environment.soil_map_unit(self, mukey)

    def soil_at(self, latitude, longitude):
        """Return bounded containing soil polygons, preserving boundary ambiguity."""
        from . import reference_environment as environment
        return environment.spatial(self, 'B06', 'mupolygon', latitude, longitude)

    def soil_components(self, mukey):
        """List recorded components and percentages without selecting a dominant soil."""
        from . import reference_environment as environment
        return environment.soil_components(self, mukey)

    def soil_horizons(self, mukey, cokey):
        """List bounded horizon identities and source depth ranges for one component."""
        from . import reference_environment as environment
        return environment.soil_horizons(self, mukey, cokey)

    def soil_horizon(self, mukey, cokey, chkey, *, property):
        """Read an explicitly selected horizon property, with recorded units and ranges."""
        from . import reference_environment as environment
        return environment.soil_horizon(self, mukey, cokey, chkey, property=property)

    def hydro_feature(self, layer, identifier, *, key):
        """Read exact source-specific NHD identities without routing or association."""
        from . import reference_environment as environment
        return environment.hydro_feature(self, layer, identifier, key=key)

    def hydro_at(self, latitude, longitude, *, layer):
        """Read containing recorded catchments or waterbodies at an explicit layer."""
        from . import reference_environment as environment
        return environment.spatial(self, 'B07', layer, latitude, longitude)

    def _database(self, path, entry, level):
        """Open only the pinned local SQLite file, with extensions and writes disabled."""
        from pyproj import CRS
        if not CRS(entry['horizontal_crs']).equals(CRS('EPSG:4269')):
            raise ValueError('incompatible_wbd_crs')
        connection = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
        connection.execute('PRAGMA query_only=ON')
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_GEOMETRY + 4096)
        connection.set_progress_handler(lambda: int(time.monotonic() > self.until), 1000)
        try:
            table = 'WBDHU' + str(level)
            srs = connection.execute('SELECT ' + _sql_text('organization', 16) +
                                     ', organization_coordsys_id FROM gpkg_spatial_ref_sys '
                                     'WHERE srs_id=4269 LIMIT 2').fetchall()
            if srs != [('EPSG', 4269)]:
                raise ValueError('incompatible_wbd_crs')
            metadata = connection.execute('SELECT ' + _sql_text('column_name', 128) + ', ' +
                                          _sql_text('geometry_type_name', 32) + ', srs_id FROM gpkg_geometry_columns '
                                          'WHERE lower(table_name)=lower(?) LIMIT 2', (table,)).fetchall()
            if (len(metadata) != 1 or not isinstance(metadata[0][1], str)
                    or metadata[0][1].upper() not in ('POLYGON', 'MULTIPOLYGON')
                    or metadata[0][2] != 4269):
                raise ValueError('unsupported_wbd_layer')
            geometry = metadata[0][0]
            columns = connection.execute('SELECT ' + _sql_text('name', 128) +
                                         ', pk FROM pragma_table_info(?) LIMIT 65', (table,)).fetchall()
            if not columns or len(columns) > 64 or any(not isinstance(r[0], str) for r in columns):
                raise ValueError('unsupported_wbd_schema')
            names = {r[0].lower(): r[0] for r in columns}
            primary = [r[0] for r in columns if r[1] > 0]
            required = [geometry, names.get('huc' + str(level)), names.get('name')]
            if (len(primary) != 1 or geometry not in names.values()
                    or any(not isinstance(n, str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', n)
                           for n in required + primary)):
                raise ValueError('unsupported_wbd_schema')
            return connection, table, required, primary[0]
        except BaseException:
            connection.close()
            raise

    @staticmethod
    def _record(huc, name, level):
        """Preserve HUC strings including leading zeroes; do not infer parent links."""
        if not isinstance(huc, str) or not re.fullmatch('[0-9]{' + str(level) + '}', huc):
            raise ValueError('invalid_recorded_huc')
        return dict(id='WBD:' + huc, huc=huc, level=level, name=_text(name))

    def basin(self, huc):
        """Lookup an exact recorded HUC; duplicate identities remain ambiguous."""
        if not isinstance(huc, str) or not huc.isascii() or not huc.isdigit():
            raise ValueError('exact_huc_string_required')
        level = _level(len(huc))
        entry, path = self._artifact('B08')
        db, table, (_, key, name), _ = self._database(path, entry, level)
        try:
            fields = _sql_text(f'"{key}"', level) + ',' + _sql_text(f'"{name}"', 500)
            rows = db.execute(f'SELECT {fields} FROM "{table}" WHERE "{key}"=? LIMIT 3', (huc,)).fetchall()
            records = [self._record(*row, level) for row in rows]
        finally:
            db.close()
        return self._result('B08', 'unknown' if not records else 'ok' if len(records) == 1 else 'ambiguous',
                            records=records, partial=len(records) == 3)

    def boundaries(self, latitude, longitude, *, level):
        """Return all containing records at an explicit HUC level, including edges.

An R-tree is required for bounded candidate discovery. No nearest-feature,
upstream, parent, connectivity or geometry repair inference is performed.
"""
        _coordinates(latitude, longitude)
        level = _level(level)
        entry, path = self._artifact('B08')
        x, y = _project('EPSG:4269', latitude, longitude)
        db, table, (geom, key, name), pk = self._database(path, entry, level)
        records, consumed = [], 0
        try:
            index = f'rtree_{table}_{geom}'
            if not db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (index,)).fetchone():
                raise ValueError('wbd_spatial_index_unavailable')
            fields = _sql_text(f'f."{key}"', level) + ',' + _sql_text(f'f."{name}"', 500)
            query = (f'SELECT {fields},'
                     f'CASE WHEN length(f."{geom}")<={MAX_GEOMETRY} THEN f."{geom}" END FROM "{table}" f '
                     f'JOIN "{index}" r ON f."{pk}"=r.id WHERE r.minx<=? AND r.maxx>=? '
                     f'AND r.miny<=? AND r.maxy>=? LIMIT {MAX_CANDIDATES + 1}')
            from shapely import from_wkb
            from shapely.geometry import Point
            point = Point(x, y)
            for count, (huc, label, blob) in enumerate(db.execute(query, (x, x, y, y)), 1):
                self._tick()
                if count > MAX_CANDIDATES:
                    raise ValueError('wbd_candidate_limit')
                if not isinstance(blob, bytes) or len(blob) > MAX_GEOMETRY:
                    raise ValueError('wbd_geometry_limit')
                consumed += len(blob)
                if consumed > MAX_GEOMETRY_TOTAL:
                    raise ValueError('wbd_geometry_limit')
                if len(blob) < 9 or blob[:3] != b'GP\x00' or blob[3] & 0xf0:
                    raise ValueError('invalid_geopackage_geometry')
                endian = '<' if blob[3] & 1 else '>'
                if struct.unpack(endian + 'i', blob[4:8])[0] != 4269:
                    raise ValueError('incompatible_geometry_crs')
                envelope = (blob[3] >> 1) & 7
                lengths = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
                if envelope not in lengths or len(blob) <= 8 + lengths[envelope]:
                    raise ValueError('invalid_geopackage_geometry')
                geometry = from_wkb(blob[8 + lengths[envelope]:])
                if geometry.geom_type not in ('Polygon', 'MultiPolygon') or geometry.is_empty or not geometry.is_valid:
                    raise ValueError('invalid_source_polygon')
                if geometry.covers(point):
                    records.append(self._record(huc, label, level))
        finally:
            db.close()
        records.sort(key=lambda r: (r['huc'], r['name']))
        return self._result('B08', 'ok' if len(records) == 1 else 'ambiguous' if records else 'outside_coverage',
                            records=records, partial=False)
