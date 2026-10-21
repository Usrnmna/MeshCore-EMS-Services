"""Whole-zone geographic operations for California and interstate fire coverage."""

import math
from pyproj import CRS, Transformer
from shapely import make_valid
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform, unary_union

METERS_PER_MILE = 1609.344


def checked_geometry(feature):
    """Validate source coordinates; preserve repair provenance when repair is necessary."""
    geometry = shape(feature["geometry"])
    if geometry.is_empty or not all(math.isfinite(v) for v in geometry.bounds):
        raise ValueError("Empty/non-finite source geometry")
    west, south, east, north = geometry.bounds
    if west < -180 or east > 180 or south < -90 or north > 90:
        raise ValueError("Source geometry is not longitude/latitude")
    if not geometry.is_valid:
        geometry = make_valid(geometry)
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("Unrepairable source geometry")
        feature["properties"] = dict(feature["properties"], geometry_repaired=True)
        feature["geometry"] = mapping(geometry)
    return geometry


def prepare_zones(features, california):
    """Select area overlaps, retaining each complete official zone including neighboring states."""
    project = Transformer.from_crs(4326, 5070, always_xy=True).transform
    selected = []
    for feature in features:
        geometry = checked_geometry(feature)
        overlap = geometry.intersection(california)
        # One hectare rejects numerical boundary slivers without clipping the retained zone.
        if overlap.is_empty or transform(project, overlap).area < 10000:
            continue
        props = feature["properties"]
        code = props["state"] + "Z" + props["zone"].zfill(3)
        selected.append({
            "type": "Feature", "id": code, "geometry": mapping(geometry),
            "properties": dict(props, id=code, type="fire",
                               cross_state=transform(project, geometry.difference(california)).area >= 10000),
        })
    if not selected or not any(f["id"] == "CAZ272" for f in selected):
        raise ValueError("California zone selection is incomplete")
    return selected


def scope(zones, radius_miles=100):
    """Cover every supported proximity search, including centers at the outer zone edge."""
    geometry = unary_union([shape(f["geometry"]) for f in zones])
    west, south, east, north = geometry.bounds
    latitude_margin = radius_miles / 68.7
    longitude_margin = radius_miles / (68.7 * math.cos(math.radians(max(abs(south), abs(north)) + latitude_margin)))
    return geometry, (west - longitude_margin, south - latitude_margin,
                      east + longitude_margin, north + latitude_margin)


def point_zones(zones, latitude, longitude):
    """Include exact-boundary matches; callers must not arbitrarily pick one of several zones."""
    point = Point(longitude, latitude)
    return [f for f in zones if shape(f["geometry"]).covers(point)]


def distance_miles(geometry, latitude, longitude):
    """Measure from the query location using a local azimuthal-equidistant projection."""
    crs = CRS.from_proj4(f"+proj=aeqd +lat_0={latitude} +lon_0={longitude} +datum=WGS84 +units=m")
    project = Transformer.from_crs(4326, crs, always_xy=True).transform
    return transform(project, geometry).distance(Point(0, 0)) / METERS_PER_MILE
