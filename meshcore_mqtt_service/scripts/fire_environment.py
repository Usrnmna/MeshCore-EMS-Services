"""Point-based smoke and fuel-danger reports with independently qualified evidence."""

import argparse
import math
import sqlite3
import sys
import time

from pyproj import Geod, Transformer
from shapely.geometry import Point, shape
from shapely.ops import nearest_points, transform

from . import wildfire_settings as settings
from .fire_weather import fire_alerts
from .uv_index import parse_location, resolve_location
from .wildfire_lookup import parse_query, moment
from .wildfire_sources import timestamp
from .wildfire_spatial import distance_miles, point_zones
from .wildfire_store import Store, encode


def numeric(value, maximum=None):
    """Normalize measured numeric fields; negative sentinels and nonfinite values are unknown."""
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) and value >= 0 and (maximum is None or value <= maximum) else None


def recent(value, now, limit):
    """Reject stale and materially future observations independently of retrieval age."""
    return value is not None and -300 <= now - value <= limit


def observation_time(value):
    """Treat malformed individual observation dates as unavailable rather than aborting a report."""
    try:
        return timestamp(value)
    except (ValueError, TypeError, OverflowError):
        return None


def available(store, name, now, limit):
    """A failed refresh cannot support a current-condition or absence claim."""
    state = store.status(name)
    return not state.get("error") and recent(state.get("fetched"), now, limit)


def nearest(features, latitude, longitude, radius, eligible):
    """Filter quality and time before ranking eligible full geometries by distance."""
    candidates = []
    for feature in features:
        if feature.get("geometry") is None or not eligible(feature["properties"]):
            continue
        distance = distance_miles(shape(feature["geometry"]), latitude, longitude)
        if distance <= radius:
            candidates.append((distance, str(feature["id"]), feature))
    return min(candidates, default=None, key=lambda x: (x[0], x[1]))


def aqi_category(value):
    """Apply EPA AQI category ranges to published AQI, never to raw concentrations."""
    if value is None:
        return "category unavailable"
    for limit, label in ((50, "Good"), (100, "Moderate"), (150, "Unhealthy for Sensitive Groups"),
                         (200, "Unhealthy"), (300, "Very Unhealthy"), (500, "Hazardous")):
        if value <= limit:
            return label
    return "Beyond AQI scale"


def air_quality(store, latitude, longitude, config, now):
    """Select fresh monitors separately per pollutant; retain provenance in JSON."""
    result = {}
    if not available(store, "aqi", now, config["air_quality_max_age"]):
        return result
    for pollutant in ("PM25", "PM10", "OZONE"):
        def eligible(p):
            return (recent(observation_time(p.get("ValidTime")), now, config["air_quality_max_age"])
                    and (numeric(p.get(pollutant)) is not None or numeric(p.get(pollutant + "_AQI")) is not None))
        match = nearest(store.features("aqi"), latitude, longitude, config["monitor_radius_miles"], eligible)
        if match:
            distance, _, feature = match
            p = feature["properties"]
            aqi = numeric(p.get(pollutant + "_AQI"))
            result[pollutant] = {"concentration": numeric(p.get(pollutant)), "unit": p.get(pollutant + "_Unit"),
                                 "aqi": aqi, "category": aqi_category(aqi), "distance_miles": distance,
                                 "station": p.get("SiteName"), "observed": timestamp(p["ValidTime"]),
                                 "basis": "Nearby monitoring site; source-reported concentration and AQI"}
    return result


def smoke_report(store, latitude, longitude, config, now):
    """Describe recent mapped smoke; absence of mapped smoke does not establish clean air."""
    result = {"coverage": "unknown", "origin": None, "air_quality": air_quality(
        store, latitude, longitude, config, now)}
    if not available(store, "hms", now, config["stale_after"]):
        result["reason"] = "satellite analysis unavailable, stale, or refresh failed"
        return result
    plumes = [f for f in store.features("hms") if f.get("geometry") is not None
              and recent(f["properties"].get("end"), now, config["smoke_max_age"])
              and f["properties"]["start"] <= now]
    if not plumes:
        result["reason"] = "no recent satellite plume observations; detection coverage is incomplete"
        return result
    point = Point(longitude, latitude)
    hits = [f for f in plumes if shape(f["geometry"]).covers(point)]
    if hits:
        ranking = {"light": 1, "medium": 2, "heavy": 3}
        selected = max(hits, key=lambda f: (ranking[f["properties"]["density"]], f["properties"]["end"]))
        result.update(coverage="inside", plume=selected, distance_miles=0)
    else:
        match = nearest(plumes, latitude, longitude, config["maximum_radius_miles"], lambda p: True)
        result.update(coverage="outside", search_radius_miles=config["maximum_radius_miles"])
        if match:
            distance, _, feature = match
            projection = f"+proj=aeqd +lat_0={latitude} +lon_0={longitude} +datum=WGS84 +units=m"
            forward = Transformer.from_crs(4326, projection, always_xy=True)
            inverse = Transformer.from_crs(projection, 4326, always_xy=True)
            edge = nearest_points(Point(0, 0), transform(forward.transform, shape(feature["geometry"])))[1]
            edge_lon, edge_lat = inverse.transform(edge.x, edge.y)
            azimuth = Geod(ellps="WGS84").inv(longitude, latitude, edge_lon, edge_lat)[0] % 360
            direction = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((azimuth + 22.5) // 45) % 8]
            result.update(distance_miles=distance, direction=direction, plume=feature)
    return result


def fuel_assessment(percentile):
    """Describe historical energy potential without inventing an official danger rating."""
    if percentile is None:
        return "Fuel-energy severity unclassified; matching climatology unavailable."
    if percentile >= 97:
        return "Exceptionally high fuel-energy potential relative to local history."
    if percentile >= 90:
        return "Unusually high fuel-energy potential relative to local history."
    if percentile >= 50:
        return "Fuel-energy potential at or above the historical median."
    return "Fuel-energy potential below the historical median; wind-driven fire remains possible."


def danger_report(store, latitude, longitude, config, now):
    """Use public model-Y daily maxima; detailed FEMS values remain separately timestamped."""
    result = {"station": None, "fuel_moisture": None, "alerts": [], "warning_status": "unknown"}
    if available(store, "nfdrs", now, config["danger_max_age"]):
        match = nearest(store.features("nfdrs"), latitude, longitude, config["maximum_radius_miles"],
                        lambda p: p.get("Process") == 1 and numeric(p.get("erc")) is not None
                        and recent(p.get("published"), now, config["danger_max_age"]))
        if match:
            distance, _, feature = match
            result.update(station=feature, distance_miles=distance,
                          assessment=fuel_assessment(numeric(feature["properties"].get("erc_percentile"), 100)))
            station_id = str(feature["properties"]["Station_ID"])
            if available(store, "fems", now, config["danger_max_age"]):
                observations = [f for f in store.features("fems")
                                if str(f["properties"].get("station_id")).lstrip("0") == station_id.lstrip("0")
                                and f["properties"].get("fuel_model") == "Y"
                                and recent(f["properties"].get("observed"), now, config["air_quality_max_age"])]
                if observations:
                    result["fuel_moisture"] = max(observations, key=lambda f: f["properties"]["observed"])
    zones = point_zones(store.features("zones"), latitude, longitude)
    if (zones and available(store, "zones", now, config["boundary_interval"] * 2)
            and available(store, "alerts", now, config["stale_after"])):
        result["alerts"] = fire_alerts(store.features("alerts"), [z["id"] for z in zones], now)
        result["warning_status"] = "active" if result["alerts"] else "none reported"
    # Weather context is independently selected; it must not masquerade as station ERC input.
    if available(store, "raws", now, config["stale_after"]):
        match = nearest(store.features("raws"), latitude, longitude, config["monitor_radius_miles"],
                        lambda p: recent(observation_time(p.get("ObservedDate")), now, config["air_quality_max_age"]))
        if match:
            result["weather"] = {"distance_miles": match[0], "feature": match[2]}
    return result


def report(command, text, store, config=None, now=None):
    """Resolve ZIP/city/GPS to a point, without requiring a California zone match."""
    config = config or settings.load()
    now = time.time() if now is None else now
    query = parse_query(command, text)
    if query["action"] == "help":
        return {"command": command, "help": True}
    latitude, longitude = resolve_location(parse_location(query["target"]))
    result = {"command": command, "resolved_point": [latitude, longitude], "generated_at": now}
    result.update((smoke_report if command == "smoke" else danger_report)(
        store, latitude, longitude, config, now))
    names = ["hms", "aqi"] if command == "smoke" else ["nfdrs", "fems", "raws", "alerts", "zones"]
    result["sources"] = [store.status(name) for name in names]
    return result


def format_report(data):
    """Keep smoke replies free of a location header, Monitor line, and PM10 line."""
    command = data["command"]
    if data.get("help"):
        return f"Use !{command} ZIP, CITY STATE, or LAT LON."
    if command == "smoke":
        coverage, plume = data["coverage"], data.get("plume", {}).get("properties", {})
        if coverage == "inside":
            lines = [f"Smoke: inside {plume['density']}-density satellite-mapped plume; "
                     f"observed {moment(plume['end'])}. Surface exposure may differ."]
        elif coverage == "outside":
            if "plume" in data:
                lines = [f"Smoke: outside recently mapped plumes; nearest edge approximately "
                         f"{data['distance_miles']:.1f} mi {data['direction']}, observed {moment(plume['end'])}."]
            else:
                lines = [f"Smoke: no recent mapped plume within {data['search_radius_miles']:g} mi."]
            lines[0] += " Satellite detection is incomplete."
        else:
            lines = ["Smoke: unknown; " + data["reason"] + "."]
        for pollutant, label in (("PM25", "PM2.5"), ("OZONE", "Ozone")):
            p = data["air_quality"].get(pollutant)
            if not p:
                if pollutant == "PM25":
                    lines.append("PM2.5: fresh nearby measurements unavailable.")
                continue
            concentration = ("concentration unavailable" if p["concentration"] is None else
                             f"{p['concentration']:g} {p['unit'] or '(unit not supplied)'}")
            aqi = "AQI unavailable" if p["aqi"] is None else f"AQI {p['aqi']:g}, {p['category']}"
            lines.append(f"{label}: {concentration}; {aqi}; nearby observation "
                         f"{p['distance_miles']:.1f} mi away, {moment(p['observed'])}.")
        lines.append("Origin: not established.")
        return "\n".join(lines)
    lines = []
    if data["station"]:
        p = data["station"]["properties"]
        percentile = numeric(p.get("erc_percentile"), 100)
        ranking = "percentile unavailable" if percentile is None else f"{percentile:g}th percentile"
        lines += [f"Fire danger: {data['assessment']}",
                  f"ERC {numeric(p['erc']):g}, {ranking}; trend {p.get('erc_trend') or 'unavailable'}.",
                  f"{p['Station_Name']} ({data['distance_miles']:.1f} mi); model Y; "
                  f"daily maximum summary published {moment(p['published'])}."]
        if numeric(p.get("bi")) is not None:
            lines.append(f"Burning Index {numeric(p['bi']):g}; trend {p.get('bi_trend') or 'unavailable'}.")
    else:
        lines = ["Fire danger: unknown; fresh ERC station data unavailable within the configured radius."]
    if data["fuel_moisture"]:
        p = data["fuel_moisture"]["properties"]
        names = [("1h", "one_hr_tl_fuel_moisture"), ("10h", "ten_hr_tl_fuel_moisture"),
                 ("100h", "hun_hr_tl_fuel_moisture"), ("1000h", "thou_hr_tl_fuel_moisture"),
                 ("live herb", "herbaceous_lfi_fuel_moisture"), ("live woody", "woody_lfi_fuel_moisture")]
        values = [f"{label} {numeric(p.get(key)):g}%" for label, key in names if numeric(p.get(key)) is not None]
        lines.append("Modeled fuel moisture (QC unverified): " + (", ".join(values) or "unavailable") +
                     f"; {moment(p['observed'])}; source quality code {p.get('quality_code')}; type {p.get('nfdr_type')}.")
    else:
        lines.append("Detailed fuel moisture: unavailable.")
    weather = data.get("weather")
    if weather:
        p = weather["feature"]["properties"]
        lines.append(f"Nearby RAWS ({weather['distance_miles']:.1f} mi): wind {p.get('WindSpeedMPH') or 'unknown'}, "
                     f"gust {p.get('WindSpeedPeak') or 'unknown'}, RH {p.get('RelativeHumidity') or 'unknown'}; "
                     f"{moment(timestamp(p.get('ObservedDate')))}.")
    lines.append("Fire-weather warnings: " + (", ".join(sorted({f["properties"]["event"] for f in data["alerts"]}))
                                              if data["alerts"] else data["warning_status"]) + ".")
    lines.append("ERC excludes wind; official local danger rating unavailable.")
    return "\n".join(lines)


def main(command, argv=None):
    """Run a read-only command, with optional explicit bounded refresh and full JSON."""
    parser = argparse.ArgumentParser(description=f"!{command} ZIP, CITY STATE, or LAT LON")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--db", default=str(settings.database_path()))
    parser.add_argument("query", nargs="*")
    args = parser.parse_args(argv)
    try:
        config = settings.load()
        text = " ".join(args.query)
        query = parse_query(command, text)
        if query["action"] == "help":
            data = {"command": command, "help": True}
        else:
            if args.refresh:
                from .wildfire_refresh import refresh
                names = ["hms", "aqi"] if command == "smoke" else ["nfdrs", "raws", "alerts"]
                if command == "firedanger" and config["fems_station_ids"]:
                    names.append("fems")
                with Store(args.db, writable=True) as store:
                    refresh(store, config, only=names)
            with Store(args.db) as store:
                data = report(command, text, store, config)
        print(encode(data) if args.json else format_report(data))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, sqlite3.Error) as exc:
        text = ("Smoke: " if command == "smoke" else "Fire danger: ") + "unavailable; " + str(exc)
        print(encode({"error": text}) if args.json else text)
        return 1 if args.json else 0
