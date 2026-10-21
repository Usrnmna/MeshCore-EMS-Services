"""Wildfire configuration shared by standalone programs and the service worker."""

import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "enabled": True,
    "incident_interval": 300,
    "perimeter_interval": 900,
    "weather_interval": 900,
    "alert_interval": 300,
    "boundary_interval": 86400,
    "context_interval": 1800,
    "smoke_interval": 1800,
    "danger_interval": 3600,
    "smoke_max_age": 21600,
    "air_quality_max_age": 10800,
    "danger_max_age": 129600,
    "monitor_radius_miles": 50,
    "fems_station_ids": [],
    "stale_after": 3600,
    "history_days": 7,
    "subscription_hours": 4,
    "subscription_interval": 300,
    "containment_change": 10,
    "acreage_change": 100,
    "max_results": 3,
    "maximum_radius_miles": 100,
    "context_sources": ["raws", "aqi", "smoke", "viirs", "modis", "cameras"],
}
CONTEXT_NAMES = {
    "raws", "aqi", "smoke", "aqi_today", "aqi_tomorrow", "viirs", "modis",
    "cameras", "treatments", "history", "spc", "potential",
}


def validate(settings):
    """Merge defaults and reject settings that could cause unbounded work."""
    if not isinstance(settings, dict) or set(settings) - set(DEFAULTS):
        raise ValueError("Unknown wildfire setting or invalid settings object")
    result = dict(DEFAULTS, **settings)
    if type(result["enabled"]) is not bool:
        raise ValueError("wildfire.enabled must be boolean")
    for key, value in result.items():
        if key in {"enabled", "context_sources", "fems_station_ids"}:
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"wildfire.{key} must be a positive finite number")
    for key in ("max_results", "history_days"):
        if type(result[key]) is not int:
            raise ValueError(f"wildfire.{key} must be an integer")
    if result["max_results"] > 20 or result["history_days"] > 30:
        raise ValueError("Wildfire results are limited to 20; history to 30 days")
    if result["maximum_radius_miles"] > 200 or result["subscription_hours"] > 24:
        raise ValueError("Wildfire radius is limited to 200 miles; subscriptions to 24 hours")
    if any(result[k] < 60 for k in DEFAULTS if k.endswith("_interval")):
        raise ValueError("Wildfire polling intervals must be at least 60 seconds")
    if result["monitor_radius_miles"] > 200:
        raise ValueError("Air quality monitor radius is limited to 200 miles")
    ids = result["fems_station_ids"]
    if (not isinstance(ids, list) or len(ids) > 20 or len(set(map(str, ids))) != len(ids)
            or any(not isinstance(s, str) or not s.isascii() or not s.isdigit() or len(s) > 12 for s in ids)):
        raise ValueError("fems_station_ids must contain at most 20 unique numeric station ID strings")
    sources = result["context_sources"]
    if not isinstance(sources, list) or any(s not in CONTEXT_NAMES for s in sources):
        raise ValueError("Unknown wildfire context source")
    return result


def load():
    """Read service-provided settings or the package's standalone configuration."""
    if "MESHCORE_WILDFIRE_SETTINGS" in os.environ:
        return validate(json.loads(os.environ["MESHCORE_WILDFIRE_SETTINGS"]))
    config = json.loads((ROOT / "config.json").read_bytes())
    return validate(config.get("responder", {}).get("wildfire", {}))


def database_path():
    """Resolve installed state independently from the application/source directory."""
    return Path(os.environ.get("MESHCORE_RUNTIME_DIR", ROOT / "runtime")) / "wildfire.sqlite3"
