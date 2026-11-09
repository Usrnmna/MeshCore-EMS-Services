"""Read-only command dependency checks; no downloads, repairs, or readiness guarantees."""
import os
from pathlib import Path
import sqlite3
import sys

# Package imports are needed by existing readers during direct script invocation.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ENTRY_POINTS = {
    "!brief": "scripts/brief.py",
    "!weather": "scripts/weather.py",
    "!where": "scripts/where.py",
    "!satpass": "scripts/satpass.py",
    "!satpoint": "scripts/satpoint.py",
    "!sat": "scripts/sat.py", "!satfreq": "scripts/satfreq.py",
    "!wateruse": "scripts/wateruse.py",
    "!downstream": "scripts/downstream.py", "!tributaries": "scripts/tributaries.py",
    "!gauge": "scripts/gauge.py", "!gauges": "scripts/gauges.py",
    "!facility": "scripts/facility.py",
    "!camp": "scripts/camp.py",
    "!parking": "scripts/parking.py",
    "!statepark": "scripts/statepark.py",
    "!entrance": "scripts/entrance.py",
    "!help": "scripts/command_help.py",
    "!data": "scripts/data_status.py",
    "!status": "scripts/status.py",
    "!time": "scripts/time_now.py",
    "!aqi": "scripts/airnow_aqi.py",
    "!traffic": "scripts/highway_info.py",
    "!rivers": "scripts/nearby_river_stations.py",
    "!uv": "scripts/uv_index.py",
    "!heatadv": "scripts/heat_adv.py",
    "!floodwarn": "scripts/flood_warn.py",
    "!snowpack": "scripts/snowpack.py",
    "!floodalarm": "scripts/floodalarm.py",
    "!lightning": "scripts/lightning.py",
    "!trail": "scripts/trail.py",
    "!rec": "scripts/rec.py",
    "!peak": "scripts/peak.py",
    "!park": "scripts/park.py",
    "!boundary": "scripts/boundary.py",
    "!firezone": "scripts/firezone.py",
    "!fires": "scripts/fires.py",
    "!fire": "scripts/fire.py",
    "!firewx": "scripts/firewx.py",
    "!firewarn": "scripts/firewarn.py",
    "!firedata": "scripts/firedata.py",
    "!firealarm": "scripts/firealarm.py",
    "!smoke": "scripts/smoke.py",
    "!firedanger": "scripts/firedanger.py",
    "!slidewarn": "scripts/slidewarn.py",
    "!slidealarm": "scripts/slidealarm.py",
    "!slideinfo": "scripts/slideinfo.py",
    "!waterway": "scripts/waterway.py",
    "!basin": "scripts/basin.py",
    "!floodstatus": "scripts/floodstatus.py"
}

GIS_LAYERS = {
    "!trail": ("trails", "additional_trails", "trail_endpoints"),
    "!rec": ("recreation_points",), "!peak": ("peaks",),
    "!park": ("ebrpd", "ebrpd_display_2_jan_14", "adjacent_local_parks_jan_14", "recreation_areas"),
    "!boundary": ("ebrpd", "ebrpd_display_2_jan_14", "adjacent_local_parks_jan_14", "recreation_areas", "reservoirs", "watershed_boundary"),
}
FIRE = {"!firezone", "!fires", "!fire", "!firewx", "!firewarn", "!firedata", "!firealarm", "!smoke", "!firedanger"}
WATER = {"!waterway", "!basin", "!floodstatus", "!floodwarn", "!floodalarm"}
SLIDE = {"!slidewarn", "!slidealarm", "!slideinfo"}


INPUTS = {
    "none": {"!status", "!time"}, "text_query": {"!brief", "!weather", "!where", "!satpass", "!satpoint", "!sat", "!satfreq", "!wateruse", "!downstream", "!tributaries","!gauge", "!gauges","!help", "!data", "!statepark", "!entrance", "!camp", "!parking", "!facility"},
    "coordinates": {"!aqi", "!rivers"}, "route_number": {"!traffic"},
    "location": {"!uv", "!heatadv", "!lightning", "!snowpack"},
    "gis_query": set(GIS_LAYERS), "water_query": WATER,
    "fire_query": FIRE, "slide_query": SLIDE,
}


def is_bundled(command, spec):
    """Recognize shipped registration contracts without trusting custom metadata."""
    mode = next((mode for mode, names in INPUTS.items() if command in names), None)
    args = ["--mesh-text", "--timeout", "15"] if command == "!rivers" else []
    style = "options" if command == "!rivers" else "positional"
    return (command in ENTRY_POINTS and spec.get("script") == ENTRY_POINTS[command]
            and spec.get("input", "none") == mode and spec.get("args", []) == args
            and spec.get("coordinate_style", "positional") == style)


def dependency_status(command, bundled=True):
    """Return a safe public status for known prerequisites; provider health stays unverified.

    Only bundled entry points have known contracts. Existing readers enforce
    managed removal, custom roots and reference integrity. Failures never expose
    paths or exception text. A successful local check is not a live-source test.
    """
    if not bundled:
        return "Dependencies unverified"
    try:
        if command == "!brief":
            from scripts import brief_lookup
            return "Partial: NWS unverified; fire cache/water datasets checked per query"
        if command == "!weather":
            import urllib.request
            from zoneinfo import ZoneInfo
            from scripts import weather_lookup
            ZoneInfo("America/Los_Angeles")
            return "NWS/geocoder unverified; runtime cache checked per query"
        if command == "!where":
            from scripts.where_data import availability
            return ("Partial: local geographic references; checked per query" if availability()
                    else "Unavailable: geographic collections missing or invalid")
        if command in {"!satpoint", "!satpass"}:
            from scripts import satellite_pointing, satellite_terrain
            from scripts.satellite_lookup import catalog
            values, base, _ = satellite_pointing.settings()
            try:
                entries = satellite_terrain.source_entries(values)
                available = False
                for entry in entries:
                    try:
                        satellite_terrain.sources(values, base, entry['id'])
                    except (ValueError, OSError, KeyError, TypeError):
                        continue
                    available = True
                    break
                if not available:
                    return "Unavailable: GIS terrain missing or invalid"
            except (ValueError, OSError, KeyError, TypeError):
                return "Unavailable: GIS terrain missing or invalid"
            import skyfield.api, rasterio, pyproj
            with catalog() as (db, _):
                if not db.execute('SELECT 1 FROM orbits LIMIT 1').fetchone():
                    return "Unavailable: orbital records missing"
            return "Partial: orbit age, terrain coverage and datum checked per query"
        if command in {"!sat", "!satfreq"}:
            from scripts.satellite_lookup import catalog
            with catalog():
                pass
            return "Partial: catalog only; RF unverified"
        if command == "!wateruse":
            from scripts import basin_plan_data, water_settings
            settings = water_settings.load()
            if not settings["enabled"]:
                return "Unavailable: water feature disabled"
            with basin_plan_data.Collection(settings) as collection:
                collection.review_bytes('relationships/beneficial_uses.csv')
                if not any(entry['name'] in basin_plan_data.USE_LAYERS for entry in collection.entries.values()):
                    return "Unavailable: designation source missing"
            return "Partial: installed designation coverage only"
        if command in {"!downstream", "!tributaries"}:
            from scripts import connectivity_lookup, water_settings
            settings = water_settings.load()
            if not settings["enabled"]:
                return "Unavailable: water feature disabled"
            with connectivity_lookup.routing(settings):
                pass
            return "Routing checked; local coverage only"
        if command in {"!gauge", "!gauges"}:
            from scripts import gauge_data, water_settings
            settings = water_settings.load()
            if not settings["enabled"]:
                return "Unavailable: water feature disabled"
            gauge_data.load_inventory(settings)
            return "Inventory checked; readings unverified"
        if command == "!facility":
            from scripts.facility_lookup import load_source, SOURCE_FAILURES
            from scripts.parks_sites import radius_limit
            from pyproj import Geod
            Geod(ellps="WGS84")
            radius_limit()
            checked = 0
            for source, category in (("ebmud", "restrooms"), ("parks", "restrooms"), ("parks", "picnic")):
                try:
                    load_source(source, category)
                    checked += 1
                except SOURCE_FAILURES:
                    pass
            if not checked:
                return "Unavailable: facility sources missing or invalid"
            return "Partial: facility category coverage varies"
        if command in {"!camp", "!parking"}:
            from scripts.parks_sites import LAYERS, load_snapshot, radius_limit
            load_snapshot(("park_boundaries", LAYERS[command[1:]][0]))
            try:
                from pyproj import Geod
                Geod(ellps="WGS84")
                radius_limit()
            except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError):
                return "Partial: proximity dependency unavailable"
            return "Local data checked; query coverage varies"
        if command in {"!statepark", "!entrance"}:
            from scripts.stateparks_lookup import load_snapshot
            load_snapshot()
            if command == "!statepark":
                try:
                    import shapely.geometry
                    import pyproj
                except ImportError:
                    return "Partial: proximity dependency unavailable"
            return "Local data checked; query coverage varies"
        if command in {"!help", "!data", "!status", "!time"}:
            return "Local command"
        if command == "!aqi" and not os.environ.get("AIRNOW_API_KEY", "").strip():
            return "Unavailable: AirNow key missing"
        if command in GIS_LAYERS:
            from scripts.gis_data import Snapshot, load_settings
            from scripts.gis_spatial import Spatial
            settings = load_settings()
            Spatial(settings)
            snapshot = Snapshot(settings["data_directory"])
            for layer in GIS_LAYERS[command]:
                snapshot.load_dataset(layer)
            snapshot.verify_unchanged()
            return "Local data checked; query coverage varies"
        if command in SLIDE:
            from scripts.landslide_settings import load
            from scripts.landslide_data import reference, _reference
            if not load()["enabled"]:
                return "Unavailable: landslide feature disabled"
            if command == '!slideinfo':
                _reference.cache_clear()
            reference()
            return "Local data checked; telemetry unverified" if command == "!slideinfo" else "Provider unverified"
        if command in FIRE:
            from scripts.wildfire_settings import database_path, load
            from scripts.wildfire_store import Store
            if not load()["enabled"]:
                return "Unavailable: wildfire feature disabled"
            with Store(database_path()) as store:
                if not any(row.get("fetched") is not None for row in store.statuses()):
                    return "Unavailable: wildfire cache uninitialized"
                if command == '!fire':
                    incident_sources = [store.status(name) for name in ('egp', 'incidents')]
                    if not any(row.get('fetched') is not None for row in incident_sources):
                        return 'Unavailable: wildfire incident cache uninitialized'
                    if any(row.get('fetched') is None or row.get('error') for row in incident_sources):
                        return 'Partial: wildfire incident sources incomplete'
            return "Cache readable; source freshness unverified"
        if command in WATER:
            from scripts.water_settings import load, collection, runtime
            settings = load()
            if not settings["enabled"]:
                return "Unavailable: water feature disabled"
            if command in {"!waterway", "!basin", "!floodstatus"}:
                try:
                    directory = collection(settings)
                    if not ((directory / "water_index.sqlite3").is_file() or
                            (runtime() / "water_index.sqlite3").is_file()):
                        return "Partial: local water data unavailable"
                except (OSError, ValueError, KeyError, TypeError):
                    return "Partial: local water data unavailable"
            return "Provider unverified"
        return "Provider unverified" if command in ENTRY_POINTS else "Dependencies unverified"
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError, IndexError, AttributeError, sqlite3.Error):
        return "Unavailable: local dependency missing or invalid"
