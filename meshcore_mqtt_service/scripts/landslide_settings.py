"""Landslide lookup/cache and service subscription settings, in seconds unless named otherwise."""

import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {"enabled": True, "cache_seconds": 300, "subscription_interval": 300,
            "subscription_hours": 4, "max_alerts": 3}


def validate(values):
    """Reject unknown settings and unbounded polling, subscriptions, or radio output."""
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError("Invalid landslide settings")
    result = dict(DEFAULTS, **values)
    if type(result["enabled"]) is not bool:
        raise ValueError("landslide.enabled must be boolean")
    for key in set(DEFAULTS) - {"enabled"}:
        value = result[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"landslide.{key} must be a positive finite number")
    if not 60 <= result["cache_seconds"] <= 900 or not 60 <= result["subscription_interval"] <= 900:
        raise ValueError("Landslide cache and polling intervals must be 60..900 seconds")
    if result["subscription_hours"] > 24:
        raise ValueError("Landslide subscriptions are limited to 24 hours")
    if type(result["max_alerts"]) is not int or result["max_alerts"] > 10:
        raise ValueError("landslide.max_alerts must be an integer from 1 to 10")
    return result


def load():
    """Use installed service settings when exported, otherwise the standalone package config."""
    if "MESHCORE_LANDSLIDE_SETTINGS" in os.environ:
        return validate(json.loads(os.environ["MESHCORE_LANDSLIDE_SETTINGS"]))
    return validate(json.loads((ROOT / "config.json").read_bytes()).get("responder", {}).get("landslide", {}))


def database_path():
    """Keep the point cache under the configured runtime directory, outside installed source."""
    return Path(os.environ.get("MESHCORE_RUNTIME_DIR", ROOT / "runtime")) / "landslide.sqlite3"
