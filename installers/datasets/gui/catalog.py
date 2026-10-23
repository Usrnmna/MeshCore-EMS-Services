"""Presentation metadata; lifecycle identifiers and dependencies remain backend-owned."""

from installers.datasets.manage import DATASETS

LABELS = {
    "ebmud": ("EBMUD", "GIS layers and source manifests"),
    "basin_plans": ("Basin Plans", "Categorized Basin Plan archive and native originals"),
    "flood_impacts": ("Flood Reference", "Russian River static flood-reference pilot"),
    "usgs_water": ("USGS Water", "Water inventory, observations, routing and spatial index"),
    "wildfire": ("Wildfire", "Whole NWS fire-weather zone polygons"),
    "landslide": ("Landslide", "California/Nevada boundaries and reviewed stations"),
    "california_state_parks": ("California State Parks", "Optional GIS reference collection"),
    "satellites": ("Satellites", "Optional sourced satellite catalog and orbital records"),
}


def ordered(names):
    """Return a deterministic dependency-first order for the supplied identifiers."""
    remaining = set(names)
    if remaining - DATASETS.keys():
        raise ValueError("Unknown dataset identifiers")
    result = []
    while remaining:
        ready = sorted(name for name in remaining if not remaining.intersection(DATASETS[name]))
        if not ready:
            raise ValueError("Cyclic dataset dependencies")
        result.extend(ready)
        remaining.difference_update(ready)
    return result
