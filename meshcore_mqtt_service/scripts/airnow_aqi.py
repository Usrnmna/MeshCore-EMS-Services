"""Find the nearest AirNow monitoring site and report its PM2.5 AQI.

Set AIRNOW_API_KEY in the environment, then pass latitude and longitude:
    python airnow_aqi.py 37.7749 -122.4194

Request a free AirNow API key at https://docs.airnowapi.org/account/request/.
AirNow observations are preliminary and subject to change.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# ----------------------------- User settings -----------------------------
API_KEY = os.environ.get("AIRNOW_API_KEY", "").strip()
SEARCH_RADII_KM = (10, 25, 50, 100, 250, 500)
# -------------------------------------------------------------------------

API_URL = "https://www.airnowapi.org/aq/data/"
EARTH_RADIUS_KM = 6371.0088

@dataclass(frozen=True)
class Observation:
    site_name: str
    site_id: str
    latitude: float
    longitude: float
    aqi: int
    pm25: float | None
    unit: str
    category_number: int | None
    observed_at_utc: str
    distance_km: float


def validate_coordinates(latitude: float, longitude: float) -> None:
    if not -90 <= latitude <= 90:
        raise ValueError("LATITUDE must be between -90 and 90.")
    if not -180 <= longitude <= 180:
        raise ValueError("LONGITUDE must be between -180 and 180.")


def parse_arguments() -> tuple[float, float]:
    parser = argparse.ArgumentParser(
        description="Return PM2.5 and AQI from the nearest AirNow monitoring site."
    )
    parser.add_argument("latitude", type=float, help="latitude from -90 to 90")
    parser.add_argument("longitude", type=float, help="longitude from -180 to 180")
    args = parser.parse_args()
    try:
        validate_coordinates(args.latitude, args.longitude)
    except ValueError as exc:
        parser.error(str(exc))
    return args.latitude, args.longitude


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bounding_boxes(latitude: float, longitude: float, radius_km: float) -> list[str]:
    """Return west,south,east,north boxes, splitting at the date line."""
    lat_delta = radius_km / 110.574
    cos_lat = max(abs(math.cos(math.radians(latitude))), 0.01)
    lon_delta = min(radius_km / (111.320 * cos_lat), 180.0)
    north, south = min(90.0, latitude + lat_delta), max(-90.0, latitude - lat_delta)
    west, east = longitude - lon_delta, longitude + lon_delta
    if west < -180:
        ranges = [(-180.0, east), (west + 360.0, 180.0)]
    elif east > 180:
        ranges = [(west, 180.0), (-180.0, east - 360.0)]
    else:
        ranges = [(west, east)]
    return [f"{w:.6f},{south:.6f},{e:.6f},{north:.6f}" for w, e in ranges]


def api_get(bbox: str) -> list[dict[str, Any]]:
    params = {
        "parameters": "PM25", "BBOX": bbox, "dataType": "B",
        "format": "application/json", "verbose": 1, "monitorType": 0,
        "includerawconcentrations": 1, "API_KEY": API_KEY,
    }
    request = Request(f"{API_URL}?{urlencode(params)}", headers={
        "Accept": "application/json", "User-Agent": "airnow-nearest-aqi/1.0"
    })
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"AirNow API error {exc.code}.") from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Could not reach the AirNow API.") from None
    except json.JSONDecodeError as exc:
        raise RuntimeError("AirNow returned an invalid response.") from exc
    if isinstance(payload, dict) and payload.get("Error"):
        raise RuntimeError("AirNow returned an API error.")
    if not isinstance(payload, list):
        raise RuntimeError("AirNow returned an unexpected response format.")
    return payload


def _number(item: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return None


def parse_observation(item: dict[str, Any], latitude: float, longitude: float) -> Observation | None:
    parameter = str(item.get("Parameter", "")).upper().replace(".", "")
    if parameter not in {"PM25", "PM2_5"}:
        return None
    site_lat, site_lon = _number(item, "Latitude"), _number(item, "Longitude")
    aqi_value = _number(item, "AQI")
    if site_lat is None or site_lon is None or aqi_value is None or aqi_value < 0:
        return None
    concentration = _number(item, "RawConcentration", "Value")
    category_value = _number(item, "Category")
    return Observation(
        site_name=str(item.get("SiteName") or "Unnamed AirNow site"),
        site_id=str(item.get("FullAQSCode") or item.get("AQSID") or "Unknown"),
        latitude=site_lat, longitude=site_lon, aqi=round(aqi_value), pm25=concentration,
        unit=str(item.get("Unit") or "µg/m³"),
        category_number=round(category_value) if category_value is not None else None,
        observed_at_utc=str(item.get("UTC") or "Unknown"),
        distance_km=haversine_km(latitude, longitude, site_lat, site_lon),
    )


def find_nearest_observation(latitude: float, longitude: float) -> Observation:
    for radius_km in SEARCH_RADII_KM:
        candidates: list[Observation] = []
        seen: set[tuple[str, str]] = set()
        for bbox in bounding_boxes(latitude, longitude, radius_km):
            for item in api_get(bbox):
                observation = parse_observation(item, latitude, longitude)
                if observation is None:
                    continue
                key = (observation.site_id, observation.observed_at_utc)
                if key not in seen:
                    seen.add(key)
                    candidates.append(observation)
        if candidates:
            return min(candidates, key=lambda obs: obs.distance_km)
    raise RuntimeError(f"No current PM2.5 observation was found within {SEARCH_RADII_KM[-1]} km.")


def one_word_rating(aqi: int, category_number: int | None = None) -> str:
    if category_number == 1 or (category_number is None and aqi <= 50): return "Good"
    if category_number == 2 or (category_number is None and aqi <= 100): return "Moderate"
    if category_number == 3 or (category_number is None and aqi <= 150): return "Sensitive"
    if category_number == 4 or (category_number is None and aqi <= 200): return "Unhealthy"
    if category_number == 5 or (category_number is None and aqi <= 300): return "Very Unhealthy"
    return "Hazardous"


def main() -> int:
    try:
        latitude, longitude = parse_arguments()
        if not API_KEY or API_KEY == "PASTE_YOUR_API_KEY_HERE":
            raise ValueError("Set the AIRNOW_API_KEY environment variable before starting the service.")
        observation = find_nearest_observation(latitude, longitude)
        print(f"AQI: {observation.aqi}")
        if observation.pm25 is None:
            print("PM2.5: N/A")
        else:
            print(f"PM2.5: {observation.pm25:.1f} {observation.unit.replace('UG/M3', 'µg/m³')}")
        print(f"Rating: {one_word_rating(observation.aqi, observation.category_number)}")
        print(f"Station: {observation.site_name}")
        
        print(f"Distance: {observation.distance_km:.2f} km")
        print(f"Observed (UTC): {observation.observed_at_utc}")
        print("Data status: Preliminary")
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
