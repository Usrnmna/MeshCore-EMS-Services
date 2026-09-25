#!/usr/bin/env python3
"""Find CDEC river-stage stations near a latitude/longitude.

The public CDEC RR8 report supplies the fixed-width river-stage rows. NOAA's
NWPS API supplies coordinates for the same five-character station identifiers.
Only the Python standard library is required.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any


# USER SETTINGS AND SOURCES: distances are miles; timeouts are seconds.
# CLI flags override these defaults. Mesh requests always supply their own GPS.
USER_LATITUDE = 37.5816
USER_LONGITUDE = -121.4944

DEFAULT_RADIUS_MILES = 15.0
HTTP_TIMEOUT_SECONDS = 30.0  # Per request; the shipped mesh command overrides this to 15.
CDEC_REPORT_URL = (
    "https://cdec.water.ca.gov/reportapp/javareports?name=RNORR8RSA"
)
NOAA_GAUGES_URL = "https://api.water.noaa.gov/nwps/v1/gauges"
USER_AGENT = "nearby-river-stations/1.0 (public hydrology data client)"


class _PreExtractor(HTMLParser):
    """Collect the text inside the first HTML <pre> element."""

    def __init__(self) -> None:
        """Initialize the first-PRE-block parser and its text buffer."""
        super().__init__(convert_charrefs=True)
        self._inside_pre = False
        self._finished = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Start collecting the first preformatted report block when its opening tag appears."""
        if tag.lower() == "pre" and not self._finished:
            self._inside_pre = True

    def handle_endtag(self, tag: str) -> None:
        """Stop collection after the first closing pre tag."""
        if tag.lower() == "pre" and self._inside_pre:
            self._inside_pre = False
            self._finished = True

    def handle_data(self, data: str) -> None:
        """Append text only while inside the selected report block."""
        if self._inside_pre:
            self._parts.append(data)

    @property
    def text(self) -> str:
        """Return the collected report text without fetching or changing external state."""
        return "".join(self._parts)


def _get_text(url: str, timeout: float) -> str:
    """Download and decode one source response; raise RuntimeError on a network timeout or failure."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not retrieve {url}: {exc}") from exc


def _get_json(url: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    """URL-encode parameters, fetch text, and return decoded JSON; raise on malformed JSON."""
    query_url = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        return json.loads(_get_text(query_url, timeout))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"The service returned invalid JSON: {query_url}") from exc


def _extract_report_text(html: str) -> str:
    """Extract and normalize the CDEC PRE block; reject pages that lack the expected report."""
    parser = _PreExtractor()
    parser.feed(html)
    if not parser.text.strip():
        raise RuntimeError("CDEC response did not contain the expected <pre> report.")
    return parser.text.replace("\r\n", "\n").replace("\r", "\n")


def _reading(value: str) -> float | None:
    """Parse one river-stage field in feet; blank, plus-marker, or invalid data becomes None."""
    value = value.strip()
    if not value or value == "+":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_cdec_report(report_text: str) -> dict[str, Any]:
    """Parse the CDEC fixed-width report into station records."""
    lines = report_text.splitlines()
    station_pattern = re.compile(r"^([A-Z0-9]{5})\s*:\s*(.*?)\s*:\s*(.*?)\s*$")
    thresholds_pattern = re.compile(
        r"(?:(?P<action>\d+(?:\.\d+)?)\s*)?/\s*"
        r"(?P<flood>\d+(?:\.\d+)?)?\s*$"
    )

    time_labels: list[str] = []
    report_issued = None
    for line in lines:
        if not time_labels:
            candidates = re.findall(r"\b\d{2}(?:AM|PM)\b", line)
            if len(candidates) >= 2:
                time_labels = candidates
        if report_issued is None:
            issued_match = re.search(
                r":\s*(\d{1,4}\s+[AP]M\s+P[DS]T\s+\w{3}\s+\w{3}\s+\d{2}\s+\d{4})",
                line,
            )
            if issued_match:
                report_issued = issued_match.group(1)

    stations: dict[str, dict[str, Any]] = {}
    for line in lines:
        match = station_pattern.match(line)
        if not match:
            continue

        station_id, name_and_thresholds, reading_text = match.groups()
        threshold_match = thresholds_pattern.search(name_and_thresholds)
        if threshold_match and (threshold_match.group("action") or threshold_match.group("flood")):
            action_stage = (
                float(threshold_match.group("action"))
                if threshold_match.group("action")
                else None
            )
            flood_stage = (
                float(threshold_match.group("flood"))
                if threshold_match.group("flood")
                else None
            )
            name = name_and_thresholds[: threshold_match.start()].strip()
        else:
            action_stage = None
            flood_stage = None
            name = name_and_thresholds.strip()

        values = [_reading(value) for value in reading_text.split("/")]
        history = [
            {"time": time_labels[index] if index < len(time_labels) else None, "stage_feet": value}
            for index, value in enumerate(values)
        ]
        stations[station_id] = {
            "station_id": station_id,
            "station_name": name,
            "action_stage_feet": action_stage,
            "minor_flood_stage_feet": flood_stage,
            "river_stage_feet": values[-1] if values else None,
            "river_stage_history": history,
            "raw_report_line": line,
        }

    if not stations:
        raise RuntimeError("No station rows were found in the CDEC report.")
    return {"report_issued": report_issued, "stations": stations}


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance using mean Earth radius 3,958.761 miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    return 3958.761 * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _bounding_box(latitude: float, longitude: float, radius_miles: float) -> dict[str, Any]:
    """Build NOAA's bounding-box query in decimal degrees from a search radius in miles."""
    latitude_delta = radius_miles / 69.0
    cosine = max(abs(math.cos(math.radians(latitude))), 0.01)
    longitude_delta = radius_miles / (69.172 * cosine)
    return {
        "bbox.xmin": max(-180.0, longitude - longitude_delta),
        "bbox.ymin": max(-90.0, latitude - latitude_delta),
        "bbox.xmax": min(180.0, longitude + longitude_delta),
        "bbox.ymax": min(90.0, latitude + latitude_delta),
        "srid": "EPSG_4326",
    }


def find_nearby_river_stations(
    latitude: float,
    longitude: float,
    radius_miles: float = DEFAULT_RADIUS_MILES,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Return RR8 river stations within radius_miles of latitude/longitude."""
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("latitude must be between -90 and 90")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("longitude must be between -180 and 180")
    if radius_miles <= 0:
        raise ValueError("radius_miles must be greater than zero")

    report_html = _get_text(CDEC_REPORT_URL, timeout)
    parsed_report = parse_cdec_report(_extract_report_text(report_html))
    report_stations = parsed_report["stations"]

    gauge_response = _get_json(
        NOAA_GAUGES_URL, _bounding_box(latitude, longitude, radius_miles), timeout
    )

    nearby: list[dict[str, Any]] = []
    for gauge in gauge_response.get("gauges", []):
        station_id = str(gauge.get("lid", "")).upper()
        if station_id not in report_stations:
            continue
        gauge_lat = gauge.get("latitude")
        gauge_lon = gauge.get("longitude")
        if not isinstance(gauge_lat, (int, float)) or not isinstance(gauge_lon, (int, float)):
            continue
        distance = haversine_miles(latitude, longitude, gauge_lat, gauge_lon)
        if distance > radius_miles:
            continue

        result = dict(report_stations[station_id])
        result.update(
            {
                "distance_miles": round(distance, 2),
                "station_latitude": gauge_lat,
                "station_longitude": gauge_lon,
                "report_issued": parsed_report["report_issued"],
            }
        )
        nearby.append(result)

    nearby.sort(key=lambda station: station["distance_miles"])
    return nearby


def _parse_args() -> argparse.Namespace:
    """Read coordinates, radius in miles, HTTP timeout in seconds, and optional compact output mode."""
    parser = argparse.ArgumentParser(
        description="Find stations in the CDEC river-stage report within a radius."
    )
    parser.add_argument("--latitude", type=float, default=USER_LATITUDE)
    parser.add_argument("--longitude", type=float, default=USER_LONGITUDE)
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS_MILES)
    parser.add_argument("--timeout", type=float, default=HTTP_TIMEOUT_SECONDS)
    parser.add_argument("--mesh-text", action="store_true", help="Compact readable output for a mesh reply instead of JSON")
    return parser.parse_args()


def format_mesh_report(stations: list[dict[str, Any]], radius: float) -> str:
    """Summarize nearest-first station readings without inventing missing values."""
    if not stations:
        return f"No matching river stations found within {radius:g} mi."
    def stage(value):
        """Format a stage as feet or N/A without converting missing readings to zero."""
        return "N/A" if value is None else f"{value:g} ft"
    issued = stations[0].get("report_issued") or "unknown report time"
    lines = [f"CDEC report: {issued}. Within {radius:g} mi:"]
    for station in stations:
        latest_time = next((entry.get("time") for entry in reversed(station.get("river_stage_history", []))), None)
        when = f" at {latest_time}" if latest_time else ""
        lines.append(
            f"{station['station_id']} {station['station_name']} ({station['distance_miles']:g} mi): "
            f"stage {stage(station.get('river_stage_feet'))}{when}; "
            f"AS {stage(station.get('action_stage_feet'))}, FS {stage(station.get('minor_flood_stage_feet'))}."
        )
    return " ".join(lines)


def main() -> int:
    """Fetch nearby stations and print JSON or mesh text; return 1 with JSON error text on expected failures."""
    args = _parse_args()
    try:
        stations = find_nearby_river_stations(
            args.latitude, args.longitude, args.radius, args.timeout
        )
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1

    print(format_mesh_report(stations, args.radius) if args.mesh_text else json.dumps(stations, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
