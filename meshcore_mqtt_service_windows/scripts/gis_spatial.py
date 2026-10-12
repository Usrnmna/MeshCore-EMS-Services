"""Offline geometry operations in a configured metric projection."""

import math
from pyproj import CRS, Transformer, network
from shapely.geometry import Point, shape
from shapely import make_valid
from shapely.ops import transform, unary_union

try:
    from .gis_data import GISUnavailable
except ImportError:
    from gis_data import GISUnavailable

METERS_PER_MILE = 1609.344


class Spatial:
    """Project GeoJSON longitude/latitude and cache geometries for one lookup."""

    def __init__(self, settings):
        """Disable projection downloads and require a projected CRS in meters."""
        network.set_network_enabled(False)
        crs = CRS.from_user_input(settings['projected_crs'])
        if not crs.is_projected or any(axis.unit_conversion_factor != 1 for axis in crs.axis_info):
            raise ValueError('projected_crs must use meters')
        self.transformer = Transformer.from_crs('EPSG:4326', crs, always_xy=True)
        self.bounds = settings['search_bounds']
        self.cache = {}
        self.repaired = False

    def point(self, latitude, longitude):
        """Validate the configured search area and project an input location."""
        west, south, east, north = self.bounds
        if not west <= longitude <= east or not south <= latitude <= north:
            raise ValueError('Location is outside the configured GIS search area.')
        x, y = self.transformer.transform(longitude, latitude, errcheck=True)
        return Point(x, y)

    def geometry(self, group):
        """Combine a named feature's parts; null geometry is omitted, never fabricated."""
        key = tuple(id(record) for record in group)
        if key not in self.cache:
            parts = []
            for record in group:
                if record['geometry'] is None:
                    continue
                geometry = transform(self.transformer.transform, shape(record['geometry']))
                if not geometry.is_valid:
                    geometry = make_valid(geometry)
                    self.repaired = True
                if geometry.is_empty or not geometry.is_valid or not all(math.isfinite(v) for v in geometry.bounds):
                    raise GISUnavailable(f'Invalid spatial geometry for {record["name"]}.')
                parts.append(geometry)
            self.cache[key] = unary_union(parts) if parts else None
        return self.cache[key]

    def nearby(self, groups, point, radius_miles=None):
        """Rank full geometries; absent radius returns only the nearest feature.

        Equal distances are ordered by name and category. An explicit radius
        returns all qualifying geometries for the caller's result limit.
        """
        found = []
        for group in groups:
            geometry = self.geometry(group)
            if geometry is not None:
                miles = geometry.distance(point) / METERS_PER_MILE
                if radius_miles is None or miles <= radius_miles:
                    found.append((group, miles))
        found.sort(key=lambda item: (item[1], item[0][0]['name'].casefold(), item[0][0]['category']))
        return found[:1] if radius_miles is None else found

    def containing(self, groups, point):
        """Report interior and exact-boundary matches; polygon holes remain excluded."""
        matches = []
        for group in groups:
            geometry = self.geometry(group)
            if geometry is not None and geometry.covers(point):
                relation = 'inside' if geometry.contains(point) else 'on boundary'
                matches.append((group, relation))
        return matches

    def intersections(self, target, groups):
        """Find mapped overlap, which does not establish public access or connectivity."""
        geometry = self.geometry(target)
        if geometry is None:
            return []
        return [group for group in groups if self.geometry(group) is not None
                and geometry.intersects(self.geometry(group))]
