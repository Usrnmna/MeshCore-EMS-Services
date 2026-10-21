"""Location water-status settings shared by direct programs and the service."""

import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "enabled": True,
    "data_directory": "../data",
    "cache_seconds": 300,
    "subscription_interval": 300,
    "subscription_hours": 4,
    "reading_max_age": 21600,
    "model_max_age": 10800,
    "nearby_radius_miles": 15,
    "max_results": 3,
    "noaa_enabled": True,
}


def validate(values):
    """Validate local settings; radio requests cannot change paths, limits or source URLs."""
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError("Invalid water settings")
    result = dict(DEFAULTS, **values)
    for key in ("enabled", "noaa_enabled"):
        if type(result[key]) is not bool:
            raise ValueError(f"water.{key} must be boolean")
    if (
        not isinstance(result["data_directory"], str)
        or not result["data_directory"].strip()
    ):
        raise ValueError("water.data_directory must name the downloaded data directory")
    for key, lo, hi in (
        ("cache_seconds", 60, 900),
        ("subscription_interval", 60, 3600),
        ("subscription_hours", 1, 24),
        ("reading_max_age", 60, 86400),
        ("model_max_age", 60, 86400),
        ("nearby_radius_miles", 1, 50),
        ("max_results", 1, 5),
    ):
        value = result[key]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not lo <= value <= hi
        ):
            raise ValueError(f"water.{key} must be {lo}..{hi}")
    if type(result["max_results"]) is not int:
        raise ValueError("water.max_results must be an integer")
    return result


def load():
    """Read the active service environment or the standalone package configuration."""
    if "MESHCORE_WATER_SETTINGS" in os.environ:
        return validate(json.loads(os.environ["MESHCORE_WATER_SETTINGS"]))
    return validate(
        json.loads((ROOT / "config.json").read_bytes())["responder"].get("water", {})
    )


def data_root(config):
    return (ROOT / config["data_directory"]).resolve()


def runtime():
    return Path(os.environ.get("MESHCORE_RUNTIME_DIR", ROOT / "runtime"))
