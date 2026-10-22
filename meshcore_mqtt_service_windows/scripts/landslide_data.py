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


def reference():
    """Pin the current installed generation before consulting the immutable cache."""
    return _reference(dataset_paths.resolve("landslide", DATA))


@lru_cache(maxsize=2)
def _reference(directory):
    """Load curated reference files only after verifying their published package checksums."""
    manifest = json.loads((directory / "manifest.json").read_bytes())
    contents = {}
    for name in ("california.geojson", "nevada.geojson", "stations.json"):
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["sha256"][name]:
            raise ValueError("Landslide reference checksum mismatch: " + name)
        contents[name] = json.loads(raw)
    boundaries = [shape(contents[name]["features"][0]["geometry"])
                  for name in ("california.geojson", "nevada.geojson")]
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
