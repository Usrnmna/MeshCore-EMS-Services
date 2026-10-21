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
    result = {"command": command, "target": text, "page": 1, "radius": None, "action": "lookup"}
    if text in {"", "help"}:
        return dict(result, action="help")
    if command in {"smoke", "firedanger"}:
        if re.fullmatch(r"[A-Za-z]{2}Z\d{3}", text) or " page " in text:
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
    match = re.search(r" page ([1-9][0-9]?)$", result["target"])
    if match:
        result["page"] = int(match[1])
        result["target"] = result["target"][:match.start()]
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
        return (f"{p.get('StationName')}: RH {p.get('RelativeHumidity') or 'not reported'}; "
                f"wind {p.get('WindSpeedMPH') or 'not reported'}; gust {p.get('WindSpeedPeak') or 'not reported'}; "
                f"observed {moment(timestamp(p.get('ObservedDate')))}")
    if category == "aqi":
        aqi = number(p.get("PM25_AQI"))
        return f"{p.get('SiteName')}: PM2.5 AQI {aqi if aqi is not None else 'not reported'}; valid {moment(timestamp(p.get('ValidTime')))}."
    if category in {"aqi_today", "aqi_tomorrow"}:
        try:
            aqi = number(float(p.get("MaxAQI", "")))
        except (TypeError, ValueError):
            aqi = None
        value = f"{aqi:g} ({p.get('MaxAQICat') or 'category unknown'})" if aqi is not None else "not reported"
        return f"{p.get('RAName') or 'Reporting area'}: {category.replace('_', ' ')} maximum AQI {value}; source does not provide a valid-time field."
    if category == "potential":
        return (f"{p.get('source_layer')}, PSA {p.get('nat_code')}: "
                f"provider flag {p.get('type') or 'not reported'}; dryness code {p.get('drynesscode')}; "
                f"provider validity flag {p.get('isvalid')}; "
                f"dated {moment(timestamp(p.get('timestampdate')))}.")
    if category == "smoke":
        return f"Smoke forecast: {p.get('smoke_classdesc')}; valid {moment(timestamp(p.get('referencedate')))} to {moment(timestamp(p.get('todate')))}."
    if category in {"viirs", "modis"}:
        return (f"{category.upper()} thermal detection {moment(timestamp(p.get('DetectionDate')))}; "
                f"confidence {p.get('Raw_Confidence', p.get('Confidence'))}; not a mapped fire boundary.")
    if category == "cameras":
        return f"{p.get('cameraName')}: online={p.get('isOnline')}; {p.get('cameraURL', '')}"
    # Supplemental schemas retain all original fields in JSON/GeoJSON output.
    useful = [(k, v) for k, v in p.items() if v is not None and
              re.search(r"name|date|valid|forecast|potential|label|category|treat|year|aqi", k, re.I)]
    label = (str(p["source_layer"]) + ": ") if p.get("source_layer") else ""
    return label + ("; ".join(f"{k}={v}" for k, v in useful[:6]) or f"{category} record {feature['id']}; use --json for attributes.")


def format_report(data, config=None):
    """Format short, paged radio text while keeping full details available as JSON."""
    config = config or settings.load()
    query, command = data["query"], data["query"]["command"]
    if data.get("help"):
        return {
            "fire": "Use !fire INCIDENT-ID or an unambiguous name from !fires.",
            "firealarm": "Use !firealarm on ZONE/LOCATION, status, or off. Monitoring lasts configured hours.",
            "firedata": "Use !firedata CATEGORY ZONE/LOCATION [page N]. Categories: " + ", ".join(sorted(settings.CONTEXT_NAMES)),
            "fires": "Use !fires ZONE/LOCATION [page N], or !fires near LOCATION within MILES.",
        }.get(command, f"Use !{command} ZONE or LAT LON, ZIP, CITY STATE.")
    zone_names = ", ".join(z["id"] for z in data.get("zones", []))
    lines = [zone_names]
    if data.get("resolved_point"):
        lines.append("Resolved point " + ", ".join(f"{v:.4f}" for v in data["resolved_point"]))
    degraded = [s for s in data.get("sources", []) if s["stale"] or s.get("error")]
    if degraded:
        lines.append("Data limited: " + ", ".join(
            s["source"] + (" unavailable" if s.get("fetched") is None else
                           f" age {int(s['age_seconds']//60)}m" + (" refresh failed" if s.get("error") else " stale"))
            for s in degraded))
    else:
        relevant = [s for s in data.get("sources", []) if s["source"] != "zones"] or data.get("sources", [])
        age = max((s["age_seconds"] or 0 for s in relevant), default=0)
        lines.append(f"Cache age up to {int(age//60)}m.")
    if data.get("alerts"):
        # Hazard information precedes long incident/forecast lists on constrained radio replies.
        lines.append("Active: " + ", ".join(sorted({a["properties"]["event"] for a in data["alerts"]})) + ".")
    if command == "firezone":
        lines += [f"{z['id']} {z['properties']['name']}; office {z['properties']['cwa']}; "
                  + ("includes territory outside CA." if z["properties"].get("cross_state") else "California zone.")
                  for z in data["zones"]]
    if "incidents" in data:
        records = data["incidents"]
        start = (query["page"] - 1) * config["max_results"]
        lines.append(f"{len(records)} incident records" + (" (complex/component records may overlap)." if any(r["complex_parent"] for r in records) else "."))
        if not records:
            lines.append("No matches in available cached feeds." if degraded else "No matching incidents reported.")
        for r in records[start:start + config["max_results"]]:
            if r.get("historical"):
                lines.append(f"Last seen {moment(r['last_seen'])}; absent from current feeds; present status unconfirmed.")
            containment = "not reported" if r["containment"] is None else f"{r['containment']:g}%"
            acres = "unknown" if r["acres"] is None else f"{r['acres']:g}"
            polygon_time = max((timestamp(f["properties"].get("poly_PolygonDateTime")) or 0 for f in r["perimeters"]), default=0)
            lines.append(f"{r['name']} [{r['display_id']}]: {acres} ac; contained {containment}; "
                         f"containment source {r['field_sources']['containment']} {moment(r['field_times']['containment'])}; "
                         f"perimeter {moment(polygon_time) if polygon_time else 'not reported'}.")
        if records and start >= len(records):
            lines.append("Page outside available incident results.")
        if start + config["max_results"] < len(records):
            lines.append(f"More: !{command} {query['target']} page {query['page'] + 1}")
    if "alerts" in data:
        lines += [f"{f['properties']['event']}: {f['properties'].get('headline') or f['properties'].get('areaDesc')}; "
                  f"until {moment(timestamp(f['properties'].get('ends') or f['properties'].get('expires')))}."
                  for f in data["alerts"]]
        if not data["alerts"]:
            lines.append("No fire-weather alerts in available cache." if degraded else "No active fire-weather watches/warnings reported.")
    if command == "firewx":
        for f in data["forecasts"]:
            lines.append(f"FWF issued {moment(f['issued'])}.")
            periods = f["periods"]
            index = query["page"] - 1
            if index < len(periods):
                lines.append(compact_period(periods[index]))
                if index + 1 < len(periods):
                    lines.append(f"Next: !firewx {query['target']} page {query['page'] + 1}")
        if not data["forecasts"]:
            lines.append("Zone forecast unavailable.")
    if command == "firedata":
        features = data["features"]
        start = (query["page"] - 1) * config["max_results"]
        lines.append(f"{len(features)} {query['category']} records intersect the zone.")
        lines.extend(context_line(query["category"], f) for f in features[start:start + config["max_results"]])
        if start + config["max_results"] < len(features):
            lines.append(f"More: !firedata {query['category']} {query['target']} page {query['page'] + 1}")
    return " ".join(lines)


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
