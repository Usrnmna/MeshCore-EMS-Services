"""Bounded, read-only geometry checks for explicitly selected hypothetical scenarios."""
import math

from .flood_reference_data import EvidenceError

MAX_VERTICES = 20000
MAX_PARTS = 128
MAX_OPERATIONS = 256
BOUNDARY_TOLERANCE_DEGREES = 0.00001


def dependencies():
    """Load geometry only when needed; catalog discovery remains dependency-light."""
    try:
        from shapely.geometry import shape, Point
        from shapely.ops import unary_union
        from shapely.errors import GEOSException
    except ImportError:
        raise EvidenceError('geometry_dependency_unavailable') from None
    return shape, Point, unary_union, GEOSException


def coordinates(latitude, longitude):
    """Accept finite numeric WGS84 latitude/longitude without wrapping or axis guessing."""
    if (type(latitude) not in (int, float) or type(longitude) not in (int, float)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError('Finite WGS84 latitude and longitude required')
    return float(latitude), float(longitude)


class Budget:
    """Bound geometry inputs and operation counts, sharing the caller's deadline."""

    def __init__(self, tick=lambda: None):
        self.tick = tick
        self.vertices = MAX_VERTICES
        self.operations = MAX_OPERATIONS

    def operation(self):
        self.tick()
        self.operations -= 1
        if self.operations < 0:
            raise EvidenceError('geometry_operation_limit')


def polygon(document, feature, budget):
    """Validate GeoJSON polygon coordinates and topology; never repair source geometry.

    Absent CRS uses RFC 7946 longitude/latitude. Explicit CRS84 and EPSG:4326
    exports are accepted in that order. Antimeridian ambiguity is unsupported.
    """
    shape, _, _, geos_error = dependencies()
    budget.operation()
    crs = document.get('crs')
    if crs is not None and crs not in (
        {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'}},
        {'type': 'name', 'properties': {'name': 'EPSG:4326'}},
    ):
        raise EvidenceError('geometry_crs_unsupported')
    geometry = feature.get('geometry')
    if not isinstance(geometry, dict) or geometry.get('type') not in ('Polygon', 'MultiPolygon'):
        raise EvidenceError('geometry_polygon_required')
    if 'crs' in feature or 'crs' in geometry:
        raise EvidenceError('geometry_nested_crs_unsupported')
    parts = geometry.get('coordinates')
    if geometry['type'] == 'Polygon':
        parts = [parts]
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS:
        raise EvidenceError('geometry_part_limit_or_empty')
    for part in parts:
        if not isinstance(part, list) or not 1 <= len(part) <= MAX_PARTS:
            raise EvidenceError('geometry_ring_limit_or_empty')
        for ring in part:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise EvidenceError('geometry_ring_invalid')
            budget.vertices -= len(ring)
            if budget.vertices < 0:
                raise EvidenceError('geometry_vertex_limit')
            for point in ring:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise EvidenceError('geometry_axis_unsupported')
                coordinates(point[1], point[0])
            if any(abs(a[0]-b[0]) > 180 for a, b in zip(ring, ring[1:])):
                raise EvidenceError('geometry_antimeridian_unsupported')
    try:
        result = shape(geometry)
        if result.is_empty or not result.is_valid or result.area <= 0:
            raise EvidenceError('geometry_invalid_or_empty')
    except geos_error:
        raise EvidenceError('geometry_invalid') from None
    budget.tick()
    return result


def selected_geometry(reader, row, budget=None):
    """Match a normalized footprint to all exact original source objects, without repair.

    Topological equality is deliberately strict. Altered/repaired derivatives need
    separate reviewed support; numerical similarity alone cannot admit them.
    """
    from .flood_catalog import source_path
    budget = budget or Budget(reader.snapshot.tick)
    _, _, union, geos_error = dependencies()
    path = f"regions/{row['library_region']}/inundation_scenarios.geojson.gz"
    document = reader.json(path)
    matches = [f for f in document['features'] if f['properties'].get('scenario_id') == row['scenario_id']]
    if len(matches) != 1:
        raise EvidenceError('geometry_identity_ambiguous_or_missing')
    footprint = polygon(document, matches[0], budget)
    originals = reader.json(source_path(row, 'inputs/catfim_'+row['source_layer']+'.geojson.gz'))
    fragments = []
    for object_id in row['source_object_ids'].split(';'):
        found = [f for f in originals['features'] if str(f['properties'].get('oid')) == object_id]
        if len(found) != 1:
            raise EvidenceError('geometry_original_ambiguous_or_missing')
        fragments.append(polygon(originals, found[0], budget))
    budget.operation()
    try:
        if not footprint.equals(union(fragments)):
            raise EvidenceError('geometry_derivation_unreviewed')
    except geos_error:
        raise EvidenceError('geometry_operation_failed') from None
    budget.tick()
    return footprint


def point_result(footprint, latitude, longitude, budget):
    """Report boundary uncertainty in angular units, never infer safety or positional accuracy."""
    _, point_class, _, geos_error = dependencies()
    budget.operation()
    point = point_class(longitude, latitude)
    try:
        distance = footprint.boundary.distance(point)
        relation = ('boundary_uncertain' if distance <= BOUNDARY_TOLERANCE_DEGREES else
                    'inside' if footprint.contains(point) else 'outside')
    except geos_error:
        raise EvidenceError('geometry_operation_failed') from None
    budget.tick()
    return dict(relation=relation, latitude=latitude, longitude=longitude, crs='OGC:CRS84',
                boundary_tolerance_degrees=BOUNDARY_TOLERANCE_DEGREES,
                positional_accuracy='not established; tolerance is a computational boundary band',
                interpretation='Selected hypothetical footprint only; outside does not mean safe.')
