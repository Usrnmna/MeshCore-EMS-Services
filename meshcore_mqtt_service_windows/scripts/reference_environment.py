"""Bounded B01/B03-B07 references; no acquisition, conversion or model admission."""
from contextlib import contextmanager
import math
import re
import sqlite3
import struct
import time

from . import reference_catalog as ref

MAX_ROWS = 32
MAX_SQL_STEPS = 2_000_000
MAX_COLUMNS = 256
# Decimal spacing in the GEOID18 CONUS header accumulates about 4.2e-9
# columns of error at the nominal eastern edge. This tolerance is in cells.
GEOID_NODE_ROUNDOFF = 1e-8
HYDRO_FIELDS = {
    'NHDFlowline': ('OBJECTID', 'Permanent_Identifier', 'NHDPlusID', 'GNIS_ID', 'GNIS_Name',
                    'ReachCode', 'FDate', 'LengthKM', 'FlowDir', 'FlowDir_description',
                    'FType', 'FCode', 'fcode_description', 'VPUID'),
    'NHDWaterbody': ('OBJECTID', 'Permanent_Identifier', 'NHDPlusID', 'GNIS_ID', 'GNIS_Name',
                     'ReachCode', 'FDate', 'AreaSqKm', 'FType', 'FCode', 'fcode_description', 'VPUID'),
    'NHDPlusCatchment': ('OBJECTID', 'NHDPlusID', 'SourceFC', 'GridCode', 'AreaSqKm', 'VPUID'),
}
SOIL_POLYGON_FIELDS = ('objectid', 'areasymbol', 'musym', 'mukey')
DEPTH_FIELDS = tuple(prefix + suffix for prefix in ('hzdept', 'hzdepb') for suffix in ('_l', '_r', '_h'))


def _tiles(reader, latitude, longitude, batch=None):
    """Filter pinned inventory bounds before reading any potentially large raster."""
    ref._coordinates(latitude, longitude)
    if batch is not None and batch not in ('B01', 'B03', 'B04'):
        raise ValueError('unsupported_elevation_batch')
    batches = [batch] if batch else ['B01', 'B03', 'B04']
    available = [b for b in batches if b in reader.entries]
    if not available:
        raise ValueError('reference_source_unavailable')
    records = []
    from pyproj import CRS
    for selected in available:
        entry = reader.entries[selected]
        expected_crs = 'EPSG:4269' if selected == 'B01' else 'EPSG:26910'
        if not CRS(entry['horizontal_crs']).equals(CRS(expected_crs)):
            raise ValueError('incompatible_elevation_crs')
        x, y = ref._project(entry['horizontal_crs'], latitude, longitude)
        for identifier, tile in sorted(entry['tiles'].items()):
            reader._tick()
            west, south, east, north = tile['bounds']
            if west <= x < east and south < y <= north:
                records.append(reader._result(selected, 'declared', tile_id=identifier,
                               integrity='not_checked', bounds=tile['bounds'], units=tile['units'],
                               vertical_datum=tile['vertical_datum'], collection_date=tile['collection_date']))
    reader._finish()
    return records


def elevation_tiles(reader, latitude, longitude):
    """Report candidate tile identities without claiming verified payload coverage."""
    records = _tiles(reader, latitude, longitude)
    return dict(status='declared' if records else 'outside_declared_coverage', records=records,
                model_eligible=False, permitted_use='elevation_reference',
                qualification='Catalog footprint discovery only; payload integrity and elevation evidence not checked.')


def elevation(reader, latitude, longitude, *, batch, tile_id):
    """Select a native tile; require embedded or explicitly reviewed XML evidence."""
    ref._coordinates(latitude, longitude)
    if tile_id is not None:
        if (batch not in ('B01', 'B03', 'B04') or not isinstance(tile_id, str)
                or not re.fullmatch('[A-Za-z0-9_-]{1,100}', tile_id)):
            raise ValueError('exact_tile_identity_required')
        if batch not in reader.entries:
            raise ValueError('reference_source_unavailable')
        if tile_id not in reader.entries[batch]['tiles']:
            return reader._result(batch, 'unknown', tile_id=tile_id)
        selected = batch
    else:
        candidates = _tiles(reader, latitude, longitude, batch)
        if len(candidates) != 1:
            return dict(status='ambiguous' if candidates else 'outside_declared_coverage', records=candidates,
                        model_eligible=False, permitted_use='elevation_reference',
                        qualification='Select an exact batch and tile; no source blending or gap filling.')
        selected, tile_id = candidates[0]['batch'], candidates[0]['tile_id']
    if selected == 'B01':
        from .reference_elevation_baseline import elevation as baseline_elevation
        return baseline_elevation(reader, latitude, longitude, tile_id)
    tile, path = reader._artifact(selected, tile_id=tile_id)
    fields = dict(tile_id=tile_id, collection_date=tile['collection_date'],
                  units=tile['units'], vertical_datum=tile['vertical_datum'])
    import rasterio
    from rasterio.windows import Window
    from pyproj import CRS
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO'):
        with rasterio.open(path, driver='GTiff', GEOREF_SOURCES='INTERNAL') as ds:
            crs = CRS(ds.crs) if ds.crs else None
            if (crs is None or not crs.to_2d().equals(CRS('EPSG:26910'))
                    or not crs.to_2d().equals(CRS(reader.entries[selected]['horizontal_crs']))
                    or ds.count != 1 or ds.dtypes != ('float32',) or ds.nodata != -999999
                    or ds.scales != (1.0,) or ds.offsets != (0.0,)
                    or not all(math.isfinite(v) for v in ds.transform)
                    or ds.transform.a != 1 or ds.transform.e != -1 or ds.transform.b or ds.transform.d
                    or any(a * b * 4 > ref.MAX_BLOCK for a, b in ds.block_shapes)
                    or list(ds.bounds) != tile['bounds']):
                raise ValueError('incompatible_elevation_raster')
            x, y = ref._project(crs.to_2d(), latitude, longitude)
            row, col = ds.index(x, y)
            if not (0 <= row < ds.height and 0 <= col < ds.width):
                return reader._result(selected, 'outside_coverage', **fields)
            vertical = [c for c in crs.sub_crs_list if c.is_vertical]
            if 'height_evidence' in tile:
                from .reference_elevation_xml import read_evidence
                evidence = read_evidence(reader, selected, tile_id, tile, ds)
                if any(unit is not None and unit not in ('m', 'metre', 'meter')
                       for unit in (ds.units[0], tile['units'])):
                    raise ValueError('conflicting_elevation_units')
                if (len(vertical) > 1 or any(not v.equals(CRS('EPSG:5703'))
                                             or v.axis_info[0].unit_conversion_factor != 1 for v in vertical)
                        or tile['vertical_datum'] is not None
                        and not CRS(tile['vertical_datum']).equals(CRS('EPSG:5703'))):
                    raise ValueError('conflicting_elevation_vertical_datum')
                fields.update(evidence, units='m', vertical_datum='EPSG:5703')
            else:
                if ds.units[0] not in ('m', 'metre', 'meter') or tile['units'] not in ('m', 'metre', 'meter'):
                    return reader._result(selected, 'unavailable', reason='elevation_units_unresolved', **fields)
                if not vertical or tile['vertical_datum'] is None:
                    return reader._result(selected, 'unavailable', reason='vertical_datum_unresolved', **fields)
                if (len(vertical) != 1 or not vertical[0].equals(CRS(tile['vertical_datum']))
                        or vertical[0].axis_info[0].unit_conversion_factor != 1):
                    raise ValueError('incompatible_vertical_datum')
            value = ds.read(1, window=Window(col, row, 1, 1), masked=True)
            number = float(value.data[0, 0])
            if value.mask.any() or number == ds.nodata or not math.isfinite(number):
                return reader._result(selected, 'unavailable', reason='source_nodata', **fields)
    return reader._result(selected, 'ok', elevation_m=number, resolution_m=1,
                          sampling='native_containing_pixel', **fields)


def geoid(reader, latitude, longitude, *, coordinate_crs):
    """Read a recorded nearest grid node, not the NGS INTG interpolation algorithm."""
    ref._coordinates(latitude, longitude)
    if coordinate_crs != 'EPSG:6318':
        raise ValueError('explicit_nad83_2011_coordinates_required')
    entry, path = reader._artifact('B05')
    if entry['horizontal_crs'] != 'EPSG:6318' or entry.get('units') != 'm' or entry.get('version') != 'GEOID18':
        raise ValueError('incompatible_geoid_metadata')
    with path.open('rb') as stream:
        header = stream.read(44)
        if len(header) != 44:
            raise ValueError('invalid_geoid_header')
        headers = [(order, struct.unpack(order + '4d3i', header)) for order in ('<', '>')]
        headers = [(order, values) for order, values in headers if values[-1] == 1]
        if len(headers) != 1:
            raise ValueError('invalid_geoid_byte_order')
        order, (south, west, dy, dx, rows, cols, _) = headers[0]
        if (not all(math.isfinite(v) for v in (south, west, dy, dx))
                or not 0 < dy <= 1 or not 0 < dx <= 1 or rows < 2 or cols < 2
                or 44 + rows * cols * 4 != entry['bytes']
                or not 0 <= west < 360 or west + (cols - 1) * dx >= 360
                or not -90 <= south < south + (rows - 1) * dy <= 90):
            raise ValueError('invalid_geoid_grid')
        east_longitude = longitude % 360
        row_float, col_float = (latitude - south) / dy, (east_longitude - west) / dx
        # Admit only header-rounding discrepancies, not a half-cell footprint.
        if (not -GEOID_NODE_ROUNDOFF <= row_float <= rows - 1 + GEOID_NODE_ROUNDOFF
                or not -GEOID_NODE_ROUNDOFF <= col_float <= cols - 1 + GEOID_NODE_ROUNDOFF):
            return reader._result('B05', 'outside_coverage', coordinate_crs=coordinate_crs)
        row_float = min(rows - 1, max(0, row_float))
        col_float = min(cols - 1, max(0, col_float))
        row, col = math.floor(row_float + .5), math.floor(col_float + .5)
        stream.seek(44 + (row * cols + col) * 4)
        raw = stream.read(4)
        if len(raw) != 4:
            raise ValueError('incomplete_geoid_grid')
        value = struct.unpack(order + 'f', raw)[0]
    if not math.isfinite(value):
        return reader._result('B05', 'unavailable', reason='nonfinite_source_value')
    return reader._result('B05', 'ok', geoid_undulation_m=value, units='m', coordinate_crs=coordinate_crs,
                          node_latitude=south + row * dy, node_longitude=(west + col * dx + 180) % 360 - 180,
                          sampling='nearest_recorded_node', interpolated=False,
                          interpretation='Recorded grid node, not an interpolated point height; no datum or height conversion applied.')


@contextmanager
def _database(reader, batch):
    """Open a pinned immutable database with total VM-work, value and time bounds."""
    entry, path = reader._artifact(batch)
    from pyproj import CRS
    epsg = 4326 if batch == 'B06' else 4269
    if not CRS(entry['horizontal_crs']).equals(CRS.from_epsg(epsg)):
        raise ValueError('incompatible_reference_crs')
    db = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    steps = [0]
    def stop():
        steps[0] += 1000
        return int(steps[0] > MAX_SQL_STEPS or time.monotonic() > reader.until)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, ref.MAX_GEOMETRY + 4096)
        db.set_progress_handler(stop, 1000)
        yield db
    except sqlite3.DatabaseError as exc:
        raise ValueError('reference_database_invalid_or_work_limit') from exc
    finally:
        db.close()


def _schema(db, table, fields):
    """Allow fixed tables and complete requested columns, never views or arbitrary SQL."""
    if db.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchall() != [('table',)]:
        raise ValueError('reference_table_unavailable')
    columns = db.execute('SELECT name FROM pragma_table_info(?) LIMIT ?', (table, MAX_COLUMNS + 1)).fetchall()
    if len(columns) > MAX_COLUMNS or not set(fields) <= {c[0] for c in columns}:
        raise ValueError('incompatible_reference_schema')


def _expressions(fields, alias=''):
    """Bound text in SQLite before allocating it; a blob sentinel rejects unsupported values."""
    result = []
    for field in fields:
        c = alias + '"' + field + '"'
        result.append(f'CASE WHEN typeof({c}) IN (\'integer\',\'real\',\'null\') '
                      f'OR (typeof({c})=\'text\' AND length(CAST({c} AS BLOB))<=512) '
                      f'THEN {c} ELSE zeroblob(0) END')
    return ','.join(result)


def _rows(db, table, fields, where, parameters):
    """Return bounded source rows with stable ordering for component/horizon lists."""
    _schema(db, table, fields)
    order = {'component': 'cokey', 'chorizon': 'chkey'}.get(table)
    ordering = f' ORDER BY "{order}"' if order else ''
    data = db.execute(f'SELECT {_expressions(fields)} FROM "{table}" WHERE {where}{ordering} LIMIT {MAX_ROWS + 1}', parameters)
    records = [_record(fields, row) for row in data]
    identity = {'mapunit': 'mukey', 'component': 'cokey', 'chorizon': 'chkey'}.get(table)
    if identity and len({record[identity] for record in records}) != len(records):
        raise ValueError('ambiguous_source_identity')
    return records


def _record(fields, values):
    record = dict(zip(fields, values))
    for key, value in record.items():
        if isinstance(value, bytes) or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError('unsupported_reference_value')
        if key.lower() in ('mukey', 'cokey', 'chkey', 'objectid') and value is None:
            raise ValueError('missing_source_identity')
        if key.lower() in ('mukey', 'cokey', 'chkey', 'nhdplusid', 'objectid') and value is not None:
            if (type(value) not in (int, float) or value < 0 or int(value) != value
                    or isinstance(value, float) and value > 2 ** 53 - 1):
                raise ValueError('inexact_source_identity')
            record[key] = str(int(value))
    return record


def _decimal(value, *, real=False):
    """Reject aliases such as leading zeroes for recorded numeric database keys."""
    if (not isinstance(value, str) or not re.fullmatch('0|[1-9][0-9]{0,18}', value)
            or int(value) > (2 ** 53 - 1 if real else 2 ** 63 - 1)):
        raise ValueError('exact_decimal_identity_required')
    return int(value)


def _result(reader, batch, records, **fields):
    partial = len(records) > MAX_ROWS
    return reader._result(batch, 'partial' if partial else 'unknown' if not records else 'ok',
                          records=records[:MAX_ROWS], partial=partial, **fields)


def _unique(records):
    if len(records) > 1:
        raise ValueError('ambiguous_source_identity')
    return records[0] if records else None


def _mapunit(db, mukey):
    return _unique(_rows(db, 'mapunit', ('mukey', 'musym', 'muname', 'mukind', 'mustatus'),
                        'mukey=?', (_decimal(mukey),)))


def _component(db, mukey, cokey):
    if not _mapunit(db, mukey):
        return None
    record = _unique(_rows(db, 'component', ('mukey', 'cokey', 'compname'),
                           'cokey=?', (_decimal(cokey),)))
    return record if record and record['mukey'] == mukey else None


def _units(db, table, fields):
    """Read units for each source column; missing or contradictory definitions stay unavailable."""
    _schema(db, 'mdstattabcols', ('tabphyname', 'colphyname', 'uom'))
    units = {}
    for field in fields:
        records = _rows(db, 'mdstattabcols', ('uom',), 'tabphyname=? AND colphyname=?', (table, field))
        if len(records) != 1:
            raise ValueError('source_units_unavailable_or_conflicting')
        units[field] = records[0]['uom']
        if not isinstance(units[field], str) or not units[field].strip():
            raise ValueError('source_units_unavailable_or_conflicting')
    return units


def _ranges(records, units, prefixes):
    """Reject malformed or contradictory numeric ranges without filling null values."""
    for prefix in prefixes:
        fields = tuple(prefix + suffix for suffix in ('_l', '_r', '_h'))
        if len({units[field] for field in fields}) != 1:
            raise ValueError('source_range_units_conflicting')
        for record in records:
            values = [record[field] for field in fields if record[field] is not None]
            if (any(type(value) not in (int, float) or value < 0 for value in values)
                    or values != sorted(values)):
                raise ValueError('invalid_source_range')


def _depths(records, units):
    """Validate matching source depth units and top/bottom ordering; retain nulls."""
    _ranges(records, units, ('hzdept', 'hzdepb'))
    if len({units[field] for field in DEPTH_FIELDS}) != 1:
        raise ValueError('source_depth_units_conflicting')
    for record in records:
        for suffix in ('_l', '_r', '_h'):
            top, bottom = record['hzdept' + suffix], record['hzdepb' + suffix]
            if top is not None and bottom is not None and top > bottom:
                raise ValueError('invalid_source_depths')


def soil_map_unit(reader, mukey):
    """Resolve an exact numeric map-unit key without interpreting its classification."""
    _decimal(mukey)
    with _database(reader, 'B06') as db:
        result = _mapunit(db, mukey)
    return _result(reader, 'B06', [result] if result else [], mukey=mukey)


def soil_components(reader, mukey):
    """List recorded components with source percentages and no dominant selection."""
    _decimal(mukey)
    fields = ('mukey', 'cokey', 'compname', 'compkind', 'majcompflag', 'hydgrp', 'drainagecl',
              'comppct_l', 'comppct_r', 'comppct_h')
    with _database(reader, 'B06') as db:
        if not _mapunit(db, mukey):
            return _result(reader, 'B06', [], mukey=mukey)
        units = _units(db, 'component', fields[-3:])
        records = _rows(db, 'component', fields, 'mukey=?', (int(mukey),))
        _ranges(records, units, ('comppct',))
        if any(unit != 'percent' for unit in units.values()):
            raise ValueError('source_percentage_units_conflicting')
        if any(record[field] is not None and record[field] > 100 for record in records for field in units):
            raise ValueError('invalid_source_percentage')
    return _result(reader, 'B06', records, mukey=mukey, field_units=units,
                   interpretation='Recorded component percentages and classifications; no dominant-component selection.')


def soil_horizons(reader, mukey, cokey):
    """List horizons only after validating their recorded map-unit/component parent."""
    _decimal(mukey)
    _decimal(cokey)
    with _database(reader, 'B06') as db:
        if not _component(db, mukey, cokey):
            return _result(reader, 'B06', [], mukey=mukey, cokey=cokey)
        units = _units(db, 'chorizon', DEPTH_FIELDS)
        records = _rows(db, 'chorizon', ('cokey', 'chkey', 'hzname') + DEPTH_FIELDS, 'cokey=?', (int(cokey),))
        _depths(records, units)
    return _result(reader, 'B06', records, mukey=mukey, cokey=cokey, field_units=units)


def soil_horizon(reader, mukey, cokey, chkey, *, property):
    """Return one recorded property range and depths without modelling interpretation."""
    for key in (mukey, cokey, chkey):
        _decimal(key)
    if property not in ('ksat', 'awc'):
        raise ValueError('explicit_supported_soil_property_required')
    values = tuple(property + suffix for suffix in ('_l', '_r', '_h'))
    with _database(reader, 'B06') as db:
        if not _component(db, mukey, cokey):
            return _result(reader, 'B06', [], mukey=mukey, cokey=cokey, chkey=chkey)
        units = _units(db, 'chorizon', DEPTH_FIELDS + values)
        record = _unique(_rows(db, 'chorizon', ('cokey', 'chkey', 'hzname') + DEPTH_FIELDS + values,
                               'chkey=?', (int(chkey),)))
        if record and record['cokey'] != cokey:
            record = None
        if record:
            _depths([record], units)
            _ranges([record], units, (property,))
    return _result(reader, 'B06', [record] if record else [], mukey=mukey, cokey=cokey,
                   chkey=chkey, property=property, field_units=units,
                   interpretation='Recorded lower, representative and upper values; nulls remain missing. No live saturation or rate inference.')


def hydro_feature(reader, layer, identifier, *, key):
    """Resolve a source-qualified identifier; duplicate identities remain ambiguous."""
    if not isinstance(layer, str) or layer not in HYDRO_FIELDS or key not in ('Permanent_Identifier', 'NHDPlusID', 'OBJECTID', 'ReachCode'):
        raise ValueError('explicit_supported_hydro_identity_required')
    fields = HYDRO_FIELDS[layer]
    if key not in fields:
        raise ValueError('unsupported_hydro_identity_for_layer')
    if key in ('NHDPlusID', 'OBJECTID'):
        selected = _decimal(identifier, real=key == 'NHDPlusID')
    else:
        selected = ref._text(identifier, 80)
        if key == 'ReachCode' and not re.fullmatch('[0-9]{14}', selected):
            raise ValueError('exact_reach_code_required')
    with _database(reader, 'B07') as db:
        records = _rows(db, layer, fields, f'"{key}"=? COLLATE BINARY', (selected,))
    result = _result(reader, 'B07', records, layer=layer, identity_key=key, identifier=identifier,
                     field_units={'LengthKM': 'km'} if layer == 'NHDFlowline' else {'AreaSqKm': 'km2'})
    if len(records) > 1:
        result['status'] = 'ambiguous'
    return result


def _geometry(blob, epsg):
    """Decode bounded GeoPackage polygons without repairing or changing geometry."""
    if not isinstance(blob, bytes) or len(blob) < 9 or len(blob) > ref.MAX_GEOMETRY:
        raise ValueError('reference_geometry_limit')
    if blob[:3] != b'GP\x00' or blob[3] & 0xf0:
        raise ValueError('invalid_geopackage_geometry')
    order = '<' if blob[3] & 1 else '>'
    if struct.unpack(order + 'i', blob[4:8])[0] != epsg:
        raise ValueError('incompatible_geometry_crs')
    size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get((blob[3] >> 1) & 7)
    if size is None or len(blob) <= 8 + size:
        raise ValueError('invalid_geopackage_geometry')
    from shapely import from_wkb
    geometry = from_wkb(blob[8 + size:])
    if geometry.geom_type not in ('Polygon', 'MultiPolygon') or geometry.is_empty or not geometry.is_valid:
        raise ValueError('invalid_source_polygon')
    return geometry


def spatial(reader, batch, layer, latitude, longitude):
    """Use required source R-trees for containing polygons; never infer connectivity."""
    ref._coordinates(latitude, longitude)
    if (batch == 'B06' and layer != 'mupolygon') or (batch == 'B07' and layer not in ('NHDPlusCatchment', 'NHDWaterbody')):
        raise ValueError('explicit_supported_polygon_layer_required')
    epsg = 4326 if batch == 'B06' else 4269
    fields = SOIL_POLYGON_FIELDS if batch == 'B06' else HYDRO_FIELDS[layer]
    x, y = ref._project('EPSG:' + str(epsg), latitude, longitude)
    from shapely.geometry import Point
    records = []
    with _database(reader, batch) as db:
        metadata = db.execute('SELECT column_name,geometry_type_name,srs_id FROM gpkg_geometry_columns WHERE table_name=? LIMIT 2', (layer,)).fetchall()
        if (len(metadata) != 1 or metadata[0][1] not in ('POLYGON', 'MULTIPOLYGON')
                or metadata[0][2] != epsg or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', metadata[0][0])):
            raise ValueError('incompatible_reference_geometry_schema')
        geom = metadata[0][0]
        _schema(db, layer, fields + (geom,))
        pk = db.execute('SELECT name FROM pragma_table_info(?) WHERE pk>0', (layer,)).fetchall()
        if pk != [(fields[0],)]:
            raise ValueError('unsupported_reference_primary_key')
        srs = db.execute('SELECT organization,organization_coordsys_id FROM gpkg_spatial_ref_sys WHERE srs_id=? LIMIT 2', (epsg,)).fetchall()
        if srs != [('EPSG', epsg)]:
            raise ValueError('incompatible_reference_crs')
        index = f'rtree_{layer}_{geom}'
        sql = db.execute('SELECT sql FROM sqlite_master WHERE name=? AND type=\'table\'', (index,)).fetchone()
        if not sql or not re.search(r'USING\s+rtree\s*\(', sql[0], re.I):
            raise ValueError('reference_spatial_index_unavailable')
        query = (f'SELECT {_expressions(fields, "f.")},CASE WHEN length(f."{geom}")<={ref.MAX_GEOMETRY} '
                 f'THEN f."{geom}" END FROM "{layer}" f JOIN "{index}" r ON f."{fields[0]}"=r.id '
                 f'WHERE r.minx<=? AND r.maxx>=? AND r.miny<=? AND r.maxy>=? LIMIT {ref.MAX_CANDIDATES + 1}')
        total = 0
        for count, row in enumerate(db.execute(query, (x, x, y, y)), 1):
            reader._tick()
            if count > ref.MAX_CANDIDATES:
                raise ValueError('reference_candidate_limit')
            blob = row[-1]
            if not isinstance(blob, bytes):
                raise ValueError('reference_geometry_limit')
            total += len(blob)
            if total > ref.MAX_GEOMETRY_TOTAL:
                raise ValueError('reference_geometry_limit')
            if _geometry(blob, epsg).covers(Point(x, y)):
                records.append(_record(fields, row[:-1]))
    records.sort(key=lambda r: r[fields[0]])
    measurements = {'field_units': {'AreaSqKm': 'km2'}} if batch == 'B07' else {}
    return reader._result(batch, 'outside_coverage' if not records else 'ok' if len(records) == 1 else 'ambiguous',
                          layer=layer, records=records, partial=False, **measurements)
