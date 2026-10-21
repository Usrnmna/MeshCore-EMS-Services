"""Shared wildfire queries; dedicated programs select their own command behavior."""

import argparse
from datetime import datetime
import hashlib
import json
import re
import sqlite3
import sys
import time
import uuid
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from . import wildfire_settings as settings
from .response_text import compact_fields, short_label, counted
from .fire_weather import compact_period, fire_alerts
from .time_settings import display_timezone
from .uv_index import parse_location, resolve_location
from .wildfire_sources import timestamp
from .wildfire_spatial import distance_miles, point_zones
from .wildfire_store import Store, encode

COMMANDS = {"firezone", "fires", "fire", "firewx", "firewarn", "firedata", "firealarm", "smoke", "firedanger"}


def parse_query(command, text):
    """Validate radio syntax without HTTP, filesystem mutations, or shell interpretation."""
    command = command.lstrip("!")
    text = " ".join(text.split())
    if command not in COMMANDS or len(text) > 220:
        raise ValueError("Invalid wildfire command")
    result = {"command": command, "target": text, "radius": None, "action": "lookup"}
    if text in {"", "help"}:
        return dict(result, action="help")
    if command in {"smoke", "firedanger"}:
        if re.fullmatch(r"[A-Za-z]{2}Z\d{3}", text) or re.search(r"\s+page\s+\d+\s*$", text, re.I):
            raise ValueError(f"Use !{command} LAT LON, ZIP, or CITY STATE.")
        try:
            parse_location(text)
        except ValueError as exc:
            raise ValueError(str(exc).replace("!uv", "!" + command)) from exc
        return result
    if command == "firealarm":
        if text in {"off", "status"}:
            return dict(result, action=text, target="")
        if not text.startswith("on "):
            raise ValueError("Use !firealarm on ZONE/LOCATION, status, or off.")
        result.update(action="on", target=text[3:])
    if command == "firedata":
        category, _, target = text.partition(" ")
        if category not in settings.CONTEXT_NAMES:
            raise ValueError("Use !firedata CATEGORY ZONE/LOCATION; categories: " + ", ".join(sorted(settings.CONTEXT_NAMES)))
        result.update(category=category, target=target)
    if re.search(r"\s+page\s+\d+\s*$", result["target"], re.I) or result["target"].lower().startswith("details "):
        raise ValueError(f"Use !{command} with its normal query; details and paging are not supported.")
    if command == "fires" and result["target"].startswith("near "):
        match = re.fullmatch(r"near (.+) within (\d+(?:\.\d+)?)", result["target"])
        if not match or not 0 < float(match[2]) <= 200:
            raise ValueError("Use !fires near LOCATION within MILES (1-200).")
        result.update(target=match[1], radius=float(match[2]))
    target = result["target"]
    if target.startswith("--"):
        raise ValueError("Terminal options are not accepted in radio queries.")
    if command == "fire":
        if not target or not re.fullmatch(r"[A-Za-z0-9{} .,'_-]+", target):
            raise ValueError("Use !fire INCIDENT-ID or an unambiguous incident name.")
    elif re.fullmatch(r"[A-Za-z]{2}Z\d{3}", target):
        result["target"] = target.upper()
        if result["radius"] is not None:
            raise ValueError("A distance search requires a location, not a zone.")
    else:
        parse_location(target)
    return result


def resolve_target(store, query):
    """Resolve full zone polygons; place names represent the geocoder's selected point."""
    zones = store.features("zones")
    if not zones:
        raise ValueError("Wildfire zone data not initialized")
    target = query["target"]
    point = None
    if re.fullmatch(r"[A-Z]{2}Z\d{3}", target):
        selected = [f for f in zones if f["id"] == target]
    else:
        latitude, longitude = resolve_location(parse_location(target))
        point = (latitude, longitude)
        selected = point_zones(zones, latitude, longitude)
    if not selected:
        raise ValueError("Location/zone is outside the configured California-associated fire zones")
    return selected, point


def identifier(value):
    """Normalize IRWIN GUIDs; names and service-specific object IDs are never join keys."""
    return str(uuid.UUID(str(value).strip("{}")))


def number(value, maximum=None):
    """Keep missing/invalid source measurements unknown, including invalid percentages."""
    if type(value) not in (int, float) or not 0 <= value < float("inf"):
        return None
    return value if maximum is None or value <= maximum else None


def incidents(store, source_features=None):
    """Merge by IRWIN ID with explicit EGP-summary precedence and retained observations."""
    result = {}
    for source in ("incidents", "egp"):
        for feature in (source_features[source] if source_features is not None else store.features(source)):
            p = feature["properties"]
            if p.get("EgpFireClassification") == "RX" or p.get("IncidentTypeCategory") == "RX":
                continue
            key = identifier(p["IrwinID"])
            old = result.get(key, {})
            observation = {
                "source": source, "name": p.get("Name") if source == "egp" else p.get("IncidentName"),
                "acres": number(p.get("DailyAcres") if source == "egp" else p.get("IncidentSize")),
                "containment": number(p.get("PercentContained"), 100),
                "updated": timestamp(p.get("Last_Time_Information_Modified") if source == "egp" else p.get("ModifiedOnDateTime_dt")),
                "geometry": feature.get("geometry"), "raw": p,
            }
            observations = old.get("observations", []) + [observation]
            # A null EGP field may fall back to WFIGS, but its provenance stays explicit.
            chosen = {field: next((o for o in reversed(observations) if o.get(field) is not None), observation)
                      for field in ("name", "acres", "containment", "updated", "geometry")}
            result[key] = dict(old, id=key, display_id=p.get("UniqueFireIdentifier") or old.get("display_id") or key,
                               observations=observations, source=source,
                               classification=p.get("EgpFireClassification") or p.get("IncidentTypeCategory"),
                               complex_parent=p.get("CpxID"), complex_child=bool(p.get("IsCpxChild")),
                               **{field: o.get(field) for field, o in chosen.items()},
                               field_sources={field: o["source"] for field, o in chosen.items()},
                               field_times={field: o["updated"] for field, o in chosen.items()})
    polygons = {}
    for feature in store.features("perimeters"):
        p = feature["properties"]
        if not (p.get("attr_IrwinID") or p.get("poly_IRWINID")):
            continue
        if not feature.get("geometry") or shape(feature["geometry"]).area <= 0:
            continue
        key = identifier(p.get("attr_IrwinID") or p.get("poly_IRWINID"))
        polygons.setdefault(key, []).append(feature)
    for key, incident in result.items():
        available = polygons.get(key, [])
        # One incident can have multiple historical uploads in a year-to-date layer.
        # Retain only the most recent timestamp, including multipart records at that time.
        def observed(feature):
            p = feature["properties"]
            return timestamp(p.get("poly_PolygonDateTime") or p.get("poly_DateCurrent")) or 0
        latest = max(map(observed, available), default=0)
        incident["perimeters"] = [f for f in available if observed(f) == latest]
    return result


def historical_incidents(store):
    """Return last-seen local observations for explicit detail lookup, never the current list."""
    observations = {"incidents": {}, "egp": {}}
    captured = {}
    for source in observations:
        rows = store.db.execute("SELECT captured,body FROM history WHERE source=? ORDER BY captured DESC", (source,))
        for seen, body in rows:
            for feature in json.loads(body):
                key = identifier(feature["properties"]["IrwinID"])
                if key not in observations[source]:
                    observations[source][key] = feature
                    captured[key] = max(captured.get(key, 0), seen)
    result = incidents(store, {s: list(v.values()) for s, v in observations.items()})
    for key, incident in result.items():
        incident.update(last_seen=captured[key], historical=True)
    return result


def matches(incident, geometry, point=None, radius=None):
    """Match full perimeters independently of origin, with a separate proximity mode."""
    geometries = [shape(f["geometry"]) for f in incident["perimeters"] if f.get("geometry")]
    if incident.get("geometry"):
        geometries.append(shape(incident["geometry"]))
    if radius is not None:
        distances = [distance_miles(g, *point) for g in geometries]
        return min(distances) if distances and min(distances) <= radius else None
    if any(g.intersects(geometry) for g in geometries):
        return 0
    return None


def health(store, names, config, now):
    """Describe acquisition freshness separately from source observation timestamps."""
    statuses = []
    for name in sorted(set(names)):
        status = store.status(name)
        fetched = status.get("fetched")
        limit = config["boundary_interval"] * 2 if name == "zones" else config["stale_after"]
        statuses.append(dict(status, stale=fetched is None or now - fetched > limit,
                             age_seconds=None if fetched is None else max(0, now - fetched)))
    return statuses


def report(command, text, store, config=None, now=None):
    """Return structured results and source health; never enroll a subscription."""
    config, now = config or settings.load(), time.time() if now is None else now
    query = parse_query(command, text)
    if query["action"] == "help":
        return {"query": query, "help": True}
    if command == "firealarm" and query["action"] in {"off", "status"}:
        raise ValueError("Subscription status/cancellation requires the running service")
    source_names = ["zones"]
    output = {"query": query, "generated_at": now}
    if command == "fire":
        all_incidents = incidents(store)
        target = query["target"].strip("{}").casefold()
        found = [r for r in all_incidents.values() if target in
                 {r["id"].casefold(), r["display_id"].casefold(), str(r["name"]).casefold()}]
        if not found:
            found = [r for r in historical_incidents(store).values() if target in
                     {r["id"].casefold(), r["display_id"].casefold(), str(r["name"]).casefold()}]
        if len(found) != 1:
            raise ValueError("Incident not listed or name ambiguous; use an incident ID from !fires.")
        output["incidents"] = found
        output["zones"] = [z for z in store.features("zones") if matches(found[0], shape(z["geometry"])) is not None]
        source_names += ["egp", "incidents", "perimeters"]
    else:
        zones, point = resolve_target(store, query)
        output["zones"] = zones
        output["resolved_point"] = point
        geometry = unary_union([shape(z["geometry"]) for z in zones])
        codes = {z["id"] for z in zones}
        if command in {"fires", "firealarm"}:
            if query["radius"] and query["radius"] > config["maximum_radius_miles"]:
                raise ValueError("Distance exceeds configured wildfire search radius")
            found = []
            for incident in incidents(store).values():
                distance = matches(incident, geometry, point, query["radius"])
                if distance is not None:
                    found.append(dict(incident, distance_miles=distance))
            found.sort(key=lambda r: (r["distance_miles"], str(r["name"]).casefold(), r["id"]))
            output["incidents"] = found
            source_names += ["egp", "incidents", "perimeters"]
        if command in {"firezone", "firewx", "firewarn", "firealarm"}:
            output["alerts"] = fire_alerts(store.features("alerts"), codes, now)
            source_names += ["alerts"]
        if command == "firewx":
            forecasts = []
            for zone in zones:
                office = zone["properties"]["cwa"].split(",")[0].strip()
                source = "fwf:" + office
                source_names.append(source)
                products = store.features(source)
                if products:
                    p = products[0]["properties"]
                    section = p["sections"].get(zone["id"])
                    if section:
                        forecasts.append(dict(section, zone=zone["id"], issued=p["issued"],
                                              discussion=p["discussion"], url=p["url"]))
            output["forecasts"] = forecasts
        if command == "firedata":
            name = query["category"]
            source_names.append(name)
            output["features"] = [f for f in store.features(name, geometry.bounds)
                                  if f.get("geometry") and shape(f["geometry"]).intersects(geometry)]
    output["sources"] = health(store, source_names, config, now)
    return output


def moment(value):
    """Render UTC observations in the shared configured reply timezone."""
    return "unknown" if value is None else datetime.fromtimestamp(value, display_timezone()).strftime("%b %d %H:%M %Z")


def context_line(category, feature):
    """Provide source-specific, unit-labelled context without inventing a composite risk score."""
    p = feature["properties"]
    if category == "raws":
        readings = []
        for field, label, unit in (("RelativeHumidity", "RH", "%"),
                                   ("WindSpeedMPH", "wind", " mph"),
                                   ("WindSpeedPeak", "gust", " mph")):
            value = number(p.get(field))
            readings.append(label + " " + (f"{value:g}{unit}" if value is not None else "not reported"))
        return (f"{p.get('StationName') or 'Station unknown'}: " + "; ".join(readings) +
                f"; observed {moment(timestamp(p.get('ObservedDate')))}")
    if category == "aqi":
        aqi = number(p.get("PM25_AQI"))
        value = f"{aqi:g}" if aqi is not None else "not reported"
        return f"{p.get('SiteName') or 'Site unknown'}: PM2.5 AQI {value}; valid {moment(timestamp(p.get('ValidTime')))}."
    if category in {"aqi_today", "aqi_tomorrow"}:
        try:
            aqi = number(float(p.get("MaxAQI", "")))
        except (TypeError, ValueError):
            aqi = None
        value = f"{aqi:g} ({p.get('MaxAQICat') or 'category unknown'})" if aqi is not None else "not reported"
        return f"{p.get('RAName') or 'Reporting area'}: max AQI {value}; valid time unavailable."
    if category == "potential":
        return (f"{p.get('source_layer')}, PSA {p.get('nat_code')}: "
                f"provider flag {p.get('type') or 'not reported'}; dryness code {p.get('drynesscode')}; "
                f"provider validity flag {p.get('isvalid')}; "
                f"dated {moment(timestamp(p.get('timestampdate')))}.")
    if category == "smoke":
        return f"{p.get('smoke_classdesc') or 'Smoke class unknown'}; valid {moment(timestamp(p.get('referencedate')))} to {moment(timestamp(p.get('todate')))}."
    if category in {"viirs", "modis"}:
        return (f"Detected {moment(timestamp(p.get('DetectionDate')))}; "
                f"confidence {p.get('Raw_Confidence', p.get('Confidence'))}; not a mapped fire boundary.")
    if category == "cameras":
        online = p.get('isOnline')
        status = "online" if online is True else "offline" if online is False else "status unknown"
        return f"{p.get('cameraName') or 'Camera'}: {status}; {p.get('cameraURL', '')}".rstrip('; ')
    # Supplemental schemas retain all original fields in JSON/GeoJSON output.
    useful = [(k, v) for k, v in p.items() if v is not None and
              re.search(r"name|date|valid|forecast|potential|label|category|treat|year|aqi", k, re.I)]
    fields = [str(p["source_layer"])] if p.get("source_layer") else []
    for key, value in useful[:6]:
        label = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', key).replace('_', ' ').lower()
        fields.append(str(value) if label in {"name", "category"} else f"{label}: {value}")
    return "; ".join(fields) or "Attributes unavailable."


def format_report(data, config=None):
    """Return one focused result, prioritizing alerts and degraded-source status."""
    query, command = data["query"], data["query"]["command"]
    if data.get("help"):
        return {"fire": "Use !fire INCIDENT-ID or NAME from !fires.",
                "firealarm": "Use !firealarm on ZONE/LOCATION, status, or off.",
                "firedata": "Use !firedata CATEGORY ZONE/LOCATION. Categories are listed in the command guide."}.get(
                    command, f"Use !{command} ZONE, ZIP, CITY STATE, or LAT LON.")
    degraded = any(s["stale"] or s.get("error") for s in data.get("sources", []))
    caveat = " Data limited." if degraded else ""
    zones = ",".join(z["id"] for z in data.get("zones", []))
    alerts = data.get("alerts", [])
    hazards = sorted({a["properties"]["event"] for a in alerts}, key=lambda x: ("Warning" not in x, x))
    hazard = hazards[0] if hazards else ""
    if command in {"firewarn", "firewx", "firezone"} and hazard:
        essential = "NWS " + hazard + "." + caveat
    elif command == "firewarn":
        essential = ("Fire-weather alert status unknown; data limited." if degraded else "No active NWS fire-weather alerts.")
    elif command == "firezone":
        essential = (zones or "Zone unknown") + (": alert status unknown; data limited." if degraded else ": no active NWS fire-weather alerts.")
    else:
        essential = ""
    fields = []
    if command in {"fires", "fire"}:
        records = data.get("incidents", [])
        if not records:
            return compact_fields("No matches in available cache." + caveat, [zones])
        r = records[0]
        contained = "unknown" if r["containment"] is None else f"{r['containment']:g}%"
        if r.get("historical"):
            essential = short_label(r["name"], 18) + ": absent from current feeds; status unconfirmed."
        else:
            essential = f"{short_label(r['name'], 18)}: contained {contained}." + caveat
        fields = [f"{r['acres']:g} ac" if r["acres"] is not None else "acres unknown",
                  counted(len(records), "incident record")]
        if command == "fires" and query.get("radius") is not None:
            # Proximity is more useful on radio than a raw incident identifier.
            # The structured record and exact-ID lookup retain the full identifier.
            distance = r.get("distance_miles")
            fields.insert(0, f"{distance:.2f} mi map distance" if distance is not None else "Map distance unknown")
        else:
            fields.append(r["display_id"])
        fields.append(zones)
    elif command == "firedata":
        features = data.get("features", [])
        labels = {"aqi": "AQI observation", "aqi_today": "AQI forecast",
                  "aqi_tomorrow": "AQI forecast", "raws": "RAWS observation",
                  "cameras": "camera", "history": "historical fire",
                  "treatments": "fuel treatment", "spc": "SPC outlook",
                  "viirs": "VIIRS detection", "modis": "MODIS detection",
                  "potential": "fire potential record", "smoke": "smoke forecast"}
        category = query["category"]
        period = " for " + category.split('_')[1] if category in {"aqi_today", "aqi_tomorrow"} else ""
        essential = counted(len(features), labels[category]) + period + "." + caveat
        fields = [context_line(query["category"], f) for f in features[:1]] + [zones]
    elif command == "firewx":
        forecasts = data.get("forecasts", [])
        essential = essential or ("Fire weather: data limited." if degraded else "Fire weather forecast.")
        fields = []
        for forecast in forecasts:
            if not forecast["periods"]:
                continue
            period = forecast["periods"][0]
            fields.append(period["name"])
            group = []
            for line in period["text"].splitlines():
                text = line.strip().lstrip("*").strip()
                label = re.split(r"\.{2,}", text)[0]
                terrain = re.search(r"Valley|Valleys|Slope|Ridge|Above|Below", label, re.I)
                if re.search(r"\.{2,}", text) and not terrain:
                    if group:
                        fields.append(" ".join(group))
                    group = [re.sub(r"\.{2,}", ": ", text)] if re.search(r"Humidity|Winds|Thunder|Wetting|LAL", label, re.I) else []
                elif group and text:
                    group.append(re.sub(r"\.{2,}", ": ", text))
            if group:
                fields.append(" ".join(group))
        fields.append(zones)
        if not forecasts:
            fields.insert(0, "Zone forecast unavailable")
    elif command == "firezone":
        fields = [short_label(z["properties"]["name"], 40) +
                  ("; crosses CA boundary" if z["properties"].get("cross_state") else "") for z in data.get("zones", [])]
    elif alerts:
        fields = ["Until " + moment(timestamp(alerts[0]["properties"].get("ends") or alerts[0]["properties"].get("expires"))), zones]
    return compact_fields(essential, fields)


def monitor_snapshot(data):
    """Exclude retrieval timestamps from comparisons; require complete fresh core feeds."""
    bad = [s["source"] for s in data["sources"] if s["stale"] or s.get("error")]
    if bad:
        raise ValueError("Wildfire monitoring data unavailable/stale: " + ", ".join(bad))
    return {
        "zones": [z["id"] for z in data["zones"]],
        "incidents": {r["id"]: {"name": r["name"], "acres": r["acres"], "containment": r["containment"],
                              "perimeter": bool(r["perimeters"])} for r in data["incidents"]},
        "alerts": {encode([f["properties"].get("event"), f["properties"].get("sender"),
                          f["properties"].get("onset"), sorted(f["properties"].get("geocode", {}).get("UGC", []))]):
                   {"event": f["properties"]["event"],
                    "digest": hashlib.sha256(encode({k: f["properties"].get(k) for k in
                        ("headline", "description", "instruction", "severity", "onset", "ends", "expires")}).encode()).hexdigest()}
                   for f in data["alerts"]},
    }


def main(command, argv=None):
    """Run one dedicated command, optionally emitting JSON or explicitly refreshing local data."""
    parser = argparse.ArgumentParser(description=f"Standalone !{command} lookup; no persistent enrollment.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--monitor", action="store_true", help="Emit a compact, freshness-checked firealarm snapshot")
    parser.add_argument("--refresh", action="store_true", help="Perform a bounded local refresh first")
    parser.add_argument("--db", type=str, default=str(settings.database_path()))
    parser.add_argument("query", nargs="*")
    args = parser.parse_args(argv)
    if args.monitor:
        if command != "firealarm":
            parser.error("--monitor is only supported by firealarm.py")
        args.json = True
    try:
        config = settings.load()
        if args.refresh:
            from .wildfire_refresh import refresh
            with Store(args.db, writable=True) as store:
                refresh(store, config)
        query = " ".join(args.query)
        if parse_query(command, query)["action"] == "help":
            data = {"query": parse_query(command, query), "help": True}
        else:
            with Store(args.db) as store:
                data = report(command, query, store, config)
        if args.json:
            print(encode(monitor_snapshot(data) if args.monitor else data))
        else:
            text = format_report(data, config)
            if command == "firealarm":
                text = "Standalone snapshot only; no subscription created. " + text
            print(text)
        return 0
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        text = "Wildfire data unavailable or query invalid: " + str(exc)
        if args.json:
            print(encode({"error": text}))
        else:
            print(text + ". Use wildfire_refresh.py to initialize the cache if needed.")
        return 0 if not args.json else 1
