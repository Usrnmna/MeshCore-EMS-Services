"""Checksummed California/Nevada boundaries and reviewed USGS monitoring stations."""

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

from pyproj import Geod
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from . import dataset_paths

DATA = Path(__file__).resolve().parents[1] / "data" / "landslide"


def reference_bytes(path):
    """Bound reference reads before JSON decoding, including concurrently growing files."""
    limit = 1024 * 1024 if path.name in {'manifest.json', 'stations.json'} else 32 * 1024 * 1024
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Landslide reference size limit exceeded')
    return raw


def reference():
    """Pin the current installed generation before consulting the immutable cache."""
    return _reference(dataset_paths.resolve("landslide", DATA))


@lru_cache(maxsize=2)
def _reference(directory):
    """Load curated reference files only after verifying their published package checksums."""
    manifest = json.loads(reference_bytes(directory / "manifest.json"))
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or
            manifest['schema_version'] != 1 or type(manifest.get('station_count')) is not int):
        raise ValueError('Incompatible landslide station catalog')
    contents = {}
    for name in ("california.geojson", "nevada.geojson", "stations.json"):
        raw = reference_bytes(directory / name)
        if hashlib.sha256(raw).hexdigest() != manifest["sha256"][name]:
            raise ValueError("Landslide reference checksum mismatch: " + name)
        contents[name] = json.loads(raw)
    stations = contents['stations.json']
    if (not isinstance(stations, list) or len(stations) > 5000 or len(stations) != manifest['station_count'] or
            any(not isinstance(s, dict) or not isinstance(s.get('id'), str) or not s['id'] for s in stations)):
        raise ValueError('Invalid landslide station catalog')
    boundaries = []
    for name in ('california.geojson', 'nevada.geojson'):
        collection = contents[name]
        features = collection.get('features') if isinstance(collection, dict) else None
        if (not isinstance(features, list) or len(features) != 1 or not isinstance(features[0], dict) or
                not isinstance(features[0].get('geometry'), dict) or
                features[0]['geometry'].get('type') not in {'Polygon', 'MultiPolygon'}):
            raise ValueError('Invalid California/Nevada boundary collection')
        boundaries.append(shape(features[0]['geometry']))
    if any(boundary.is_empty or not boundary.is_valid for boundary in boundaries):
        raise ValueError("Invalid California/Nevada boundary")
    boundary = unary_union(boundaries)
    if boundary.is_empty or not boundary.is_valid:
        raise ValueError("Invalid California/Nevada boundary")
    return boundary, contents["stations.json"], manifest


def require_supported_location(latitude, longitude, boundary=None):
    """Accept California and Nevada; reject other out-of-state and invalid coordinates."""
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (latitude, longitude))
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError("Invalid latitude/longitude")
    if boundary is None:
        boundary = reference()[0]
    if not boundary.covers(Point(longitude, latitude)):
        raise ValueError("Landslide commands support California and Nevada locations only.")
    return latitude, longitude


def nearest_station(latitude, longitude):
    """Rank verified, non-discontinued station points by geodesic distance; no coverage radius is implied."""
    boundary, stations, manifest = reference()
    require_supported_location(latitude, longitude, boundary)
    candidates = []
    geod = Geod(ellps="WGS84")
    for station in stations:
        coordinates = station.get("coordinates")
        if not coordinates or station["status"] == "discontinued":
            continue
        lon, lat = coordinates
        require_supported_location(lat, lon, boundary)
        distance = geod.inv(longitude, latitude, lon, lat)[2] / 1609.344
        candidates.append((distance, station["id"], station))
    if not candidates:
        raise ValueError("No eligible California monitoring station in reference catalog")
    distance, _, station = min(candidates)
    return dict(station, distance_miles=distance, catalog_checked=manifest["checked_on"],
                catalog_notes=manifest["notes"])
