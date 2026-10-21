"""Location-only water status and structured subscription snapshots."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import re
import math
import sys
import time

from . import water_local, water_settings, water_sources
from .response_text import compact_fields, short_label, counted
from .flood_warn import GEOCODING_URL
from .time_settings import display_timezone, format_timestamp
from .uv_index import parse_location

COMMANDS = {"waterway", "basin", "floodstatus", "floodwarn", "floodalarm"}
CATEGORICAL_FIELDS = (
    "state",
    "label",
    "evidence",
    "reading_status",
    "routing_status",
    "routing_caveats",
    "noaa_identity_status",
    "threshold_status",
)


def parse_query(command, text):
    """Validate bounded location syntax before any child/network work; controls never enroll."""
    command = command.lstrip("!")
    if command not in COMMANDS:
        raise ValueError("Unknown water command")
    if (
        not isinstance(text, str)
        or len(text) > 150
        or any(not c.isprintable() for c in text)
    ):
        raise ValueError("Use a printable location of at most 150 characters")
    text = " ".join(text.split())
    if text.lower() in {"", "help", "--help"}:
        return {"action": "help", "target": "", "mode": "alerts"}
    action, mode = "lookup", "alerts"
    if text.split()[0].lower() == "details" or re.search(r"\s+page\s+\d+\s*$", text, re.I):
        raise ValueError(f"Use !{command} LOCATION; details and paging are not supported.")
    if command == "floodalarm":
        if text.lower() in {"stop", "status"}:
            return {"action": text.lower(), "target": "", "mode": "alerts"}
        action = "subscribe"
        if text.lower().startswith("conditions "):
            mode, text = "conditions", text[len("conditions ") :]
        elif text.lower() == "conditions":
            raise ValueError("Use !floodalarm conditions LOCATION")
    try:
        parse_location(text)
    except ValueError as exc:
        raise ValueError(str(exc).replace("!uv", "!" + command)) from exc
    return {"action": action, "target": text, "mode": mode}


def resolve(target, fetch=water_sources.get_json):
    """Resolve exactly one US place; city/ZIP results represent a point, not the whole area."""
    kind, value, state = parse_location(target)
    if kind == "coordinates":
        return list(value)
    data = fetch(
        GEOCODING_URL,
        {
            "name": f"{value}, {state}" if state else value,
            "count": 100,
            "language": "en",
            "format": "json",
            "countryCode": "US",
        },
    )
    results = data.get("results", [])
    if not isinstance(results, list) or any(not isinstance(r, dict) for r in results):
        raise ValueError("Invalid geocoder response")
    candidates = {}
    for r in results:
        if r.get("country_code") != "US" or (
            state and r.get("admin1", "").casefold() != state.casefold()
        ):
            continue
        if kind == "city" and r.get("name", "").casefold() != value.casefold():
            continue
        if kind == "zip" and value not in r.get("postcodes", []):
            continue
        lat, lon = r.get("latitude"), r.get("longitude")
        if (
            any(type(n) not in (int, float) or not math.isfinite(n) for n in (lat, lon))
            or not -90 <= lat <= 90
            or not -180 <= lon <= 180
        ):
            raise ValueError("Invalid geocoder coordinates")
        candidates[(lat, lon)] = ", ".join(
            filter(None, [r.get("name"), r.get("admin2"), r.get("admin1")])
        )
    if not candidates:
        raise ValueError(
            "Location not found; use coordinates or a US ZIP/city and state"
        )
    if len(candidates) > 1:
        choices = [
            f"{name} ({lat:.5f}, {lon:.5f})"
            for (lat, lon), name in list(candidates.items())[:3]
        ]
        raise ValueError(
            "Ambiguous location: "
            + "; ".join(choices)
            + ". Resend with coordinates; monitoring not started."
        )
    return list(next(iter(candidates)))


def attempt(function, *args):
    """Preserve partial source failures explicitly without suppressing other known conditions."""
    try:
        return {"status": "available", "data": function(*args)}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def snapshot(target, mode="conditions", config=None, now=None):
    """Collect a bounded point snapshot; all observed values remain current-only."""
    config = water_settings.load() if config is None else config
    if not config["enabled"]:
        raise ValueError("Location water commands are disabled")
    now = time.time() if now is None else now
    lat, lon = resolve(target)
    point = [round(lat, 6), round(lon, 6)]
    lat, lon = point
    result = {
        "point": point,
        "fetched": now,
        "mode": mode,
        "target": target,
        "conditions": {},
    }
    with ThreadPoolExecutor(max_workers=5) as pool:
        nws = pool.submit(attempt, water_sources.alerts_at, lat, lon, config, now)
        if mode == "conditions":
            local = pool.submit(attempt, water_local.context, lat, lon, config, now)
            if config["noaa_enabled"]:
                model = pool.submit(
                    attempt, water_sources.model_at, lat, lon, config, now
                )
                rain = pool.submit(
                    attempt, water_sources.rainfall_at, lat, lon, config, now
                )
            result["local"] = local.result()
            if result["local"]["status"] == "available":
                context = result["local"]["data"]
                stations = context["stations"]
                upstream = context.pop("upstream_stations")
                # Evaluate every supported path, independent of the bounded display list.
                # Shared gauge keys deduplicate monitoring and displayed nearby lookups.
                targets = {s["id"]: s for s in upstream}
                targets.update({s["id"]: s for s in stations if s["id"] not in targets})
                jobs = {
                    sid: pool.submit(
                        attempt, water_sources.gauge, s["lid"], sid, config, now
                    )
                    for sid, s in targets.items()
                    if s.get("lid") and config["noaa_enabled"]
                }
                observations = {sid: job.result() for sid, job in jobs.items()}
                for station in stations:
                    if station["id"] in observations:
                        station["noaa"] = observations[station["id"]]
                for station in upstream:
                    noaa = observations.get(station["id"], {})
                    state = (
                        noaa["data"]["condition"]
                        if noaa.get("status") == "available"
                        else (
                            "threshold_unavailable"
                            if not station.get("lid")
                            else "unavailable"
                        )
                    )
                    result["conditions"]["gauge:" + station["id"]] = {
                        "state": state,
                        "label": station["name"],
                        "evidence": "derived_graph_plus_basin_overlap",
                        "reading_status": station["reading_status"],
                        "routing_status": station["routing_status"],
                        "routing_caveats": station["routing_caveats"],
                        "noaa_identity_status": station.get(
                            "noaa_identity_status", "not_reviewed"
                        ),
                        "threshold_status": noaa.get("data", {}).get(
                            "threshold_status", "unverified"
                        ),
                    }
                context["upstream_total"] = len(upstream)
            result["conditions"]["routing"] = {
                "state": (
                    "available_with_exclusions"
                    if result["local"].get("data", {}).get("routing_exclusions")
                    else result["local"]["status"]
                ),
                "label": "Local water/routing data",
                "evidence": "data_availability",
            }
            if config["noaa_enabled"]:
                result["model"], result["rain"] = model.result(), rain.result()
                state = (
                    result["model"]["data"]["condition"]
                    if result["model"]["status"] == "available"
                    else "unavailable"
                )
                result["conditions"]["model"] = {
                    "state": state,
                    "label": "NOAA current modeled footprint at saved point",
                    "evidence": "modeled_point_intersection",
                }
            else:
                result["model"] = {
                    "status": "unavailable",
                    "error": "NOAA context disabled",
                }
        result["official"] = nws.result()
    return result


def checked_snapshot(data, config, now=None):
    """Reject malformed/stale subprocess output before activating persistent monitoring."""
    now = time.time() if now is None else now
    if not isinstance(data, dict) or data.get("error"):
        raise ValueError(
            data.get("error", "Invalid water snapshot")
            if isinstance(data, dict)
            else "Invalid water snapshot"
        )
    p = data.get("point")
    if (
        not isinstance(p, list)
        or len(p) != 2
        or any(type(n) not in (int, float) or not math.isfinite(n) for n in p)
        or not -90 <= p[0] <= 90
        or not -180 <= p[1] <= 180
    ):
        raise ValueError("Invalid water snapshot point")
    if (
        type(data.get("fetched")) not in (int, float)
        or not 0 <= now - data["fetched"] <= config["cache_seconds"]
    ):
        raise ValueError("Water snapshot stale or invalid")
    official = data.get("official")
    if not isinstance(official, dict) or official.get("status") not in {
        "available",
        "unavailable",
    }:
        raise ValueError("Invalid official-alert status")
    if official["status"] == "available":
        contents = official.get("data", {})
        if (
            not isinstance(contents, dict)
            or not isinstance(contents.get("alerts"), dict)
            or not isinstance(contents.get("cancelled_ids"), list)
        ):
            raise ValueError("Invalid alert snapshot")
        if any(not isinstance(key, str) for key in contents["cancelled_ids"]):
            raise ValueError("Invalid cancelled alert IDs")
        fetched = contents.get("fetched", data["fetched"])
        if (
            type(fetched) not in (int, float)
            or not 0 <= now - fetched <= config["cache_seconds"]
        ):
            raise ValueError("NWS snapshot source time stale or invalid")
        for key, alert in contents["alerts"].items():
            if (
                not isinstance(key, str)
                or not isinstance(alert, dict)
                or alert.get("id") != key
                or alert.get("event") not in water_sources.ALERTS
                or not isinstance(alert.get("fingerprint"), str)
                or type(alert.get("expires")) not in (int, float)
                or not math.isfinite(alert["expires"])
                or type(alert.get("effective")) not in (int, float)
                or not math.isfinite(alert["effective"])
                or alert["effective"] > now
                or alert["expires"] <= now
                or not isinstance(alert.get("references"), list)
                or any(not isinstance(ref, str) for ref in alert["references"])
                or any(
                    not isinstance(alert.get(field), str)
                    for field in ("headline", "instruction", "url")
                )
                or any(
                    alert.get(field) is not None and not isinstance(alert[field], str)
                    for field in ("urgency", "severity", "certainty")
                )
            ):
                raise ValueError("Invalid alert fingerprint")
    if not isinstance(data.get("conditions"), dict) or any(
        not isinstance(v, dict)
        or any(not isinstance(v.get(k), str) for k in ("state", "label", "evidence"))
        or any(not isinstance(v[k], str) for k in CATEGORICAL_FIELDS if k in v)
        for v in data["conditions"].values()
    ):
        raise ValueError("Invalid derived conditions")
    return data


def compact(data):
    """Keep only current alert fingerprints and categorical state for change detection, no levels."""
    official = data["official"]
    alerts = official.get("data", {}).get("alerts", {})
    return {
        "official_status": official["status"],
        "alerts": {
            k: {f: a[f] for f in ("event", "expires", "fingerprint", "references")}
            for k, a in alerts.items()
        },
        "conditions": {
            key: {field: value[field] for field in CATEGORICAL_FIELDS if field in value}
            for key, value in data["conditions"].items()
        },
    }


def brief(text, limit=180):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def condition_summary(conditions):
    """Count all linked gauge states without expanding the radio reply per station."""
    gauges = [value for key, value in conditions.items() if key.startswith("gauge:")]
    if not gauges:
        return "Upstream gauges: 0 supported links evaluated; coverage unknown."
    categories = Counter(g["state"] for g in gauges)
    readings = Counter(g.get("reading_status", "unavailable") for g in gauges)
    caveats = sum(
        g.get("routing_caveats", "none_reported") != "none_reported" for g in gauges
    )
    successors = sum(
        g.get("noaa_identity_status") == "matched_agency_successor" for g in gauges
    )
    counts = lambda values: ", ".join(
        f"{state}={count}" for state, count in sorted(values.items())
    )
    return (
        f"Upstream gauges: all {len(gauges)} evaluated. NOAA: {counts(categories)}. "
        f"USGS: {counts(readings)}. Routing caveats={caveats}. "
        + (f"Agency-successor links={successors}. " if successors else "")
        + "Derived basin context, point flooding unknown."
    )


def format_alerts(data):
    official = data["official"]
    if official["status"] != "available":
        return ["OFFICIAL NWS alerts unavailable; conditions unknown."]
    alerts = list(official["data"]["alerts"].values())
    if not alerts:
        return [
            "OFFICIAL NWS: no active flood alerts returned for this point; not an all-clear."
        ]
    lines = []
    for alert in sorted(
        alerts, key=lambda a: list(water_sources.ALERTS).index(a["event"])
    )[:3]:
        until = format_timestamp(datetime.fromtimestamp(alert["expires"], timezone.utc))
        lines.append(
            f"OFFICIAL NWS {alert['event']} until {until}: {brief(alert['headline'])} Instructions: {brief(alert['instruction'])} {alert['url']}"
        )
    if len(alerts) > 3:
        lines.append(f"{len(alerts)-3} additional alerts; see NWS.")
    return lines


def floodwarn_expiry(expires, fetched):
    """Use the shared timezone; include a date when expiry is not on the lookup day."""
    zone = display_timezone()
    until = datetime.fromtimestamp(expires, timezone.utc).astimezone(zone)
    checked = datetime.fromtimestamp(fetched, timezone.utc).astimezone(zone)
    clock = until.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")
    day = "" if until.date() == checked.date() else until.strftime("%a %b %d ")
    return day + clock + " " + until.strftime("%Z")


def format_floodwarn(data):
    """Put the highest-priority official warning and action ahead of optional context."""
    official = data["official"]
    target = short_label(data["target"], 30)
    if official["status"] != "available":
        return compact_fields("NWS alerts unavailable; status unknown.", [target])
    alerts = sorted(official["data"]["alerts"].values(), key=lambda a: (
        list(water_sources.ALERTS).index(a["event"]), a["expires"], a["id"]))
    if not alerts:
        return compact_fields("No active NWS flood alerts.", [target])
    messages = {
        "Flash Flood Warning": "NWS FLASH FLOOD WARNING. Move to higher ground now.",
        "Flood Warning": "NWS FLOOD WARNING. Flooding imminent/occurring.",
        "Flood Advisory": "NWS Flood Advisory. Minor flooding expected.",
        "Flood Watch": "NWS Flood Watch. Flooding possible; stay alert.",
    }
    first = alerts[0]
    fields = ["+" + counted(len(alerts)-1, "active alert") ] if len(alerts) > 1 else []
    fields += ["Until " + floodwarn_expiry(first["expires"], data["fetched"]), target]
    return compact_fields(messages[first["event"]], fields)


def format_status(command, data):
    """Return one focused result; point flooding is never inferred from a nearby gauge."""
    target = short_label(data["target"], 25)
    local = data.get("local", {})
    context = local.get("data", {}) if local.get("status") == "available" else {}
    if command in {"floodwarn", "floodalarm"}:
        return format_floodwarn(data)
    if command == "floodstatus":
        official = data["official"]
        if official["status"] != "available" or official["data"]["alerts"]:
            return format_floodwarn(data)
        model = data.get("model", {})
        state = model.get("data", {}).get("condition") if model.get("status") == "available" else None
        essential = {
            "modeled_footprint_intersects_point": "Modeled inundation at point; not field-confirmed.",
            "no_current_footprint_returned_not_all_clear": "No current modeled footprint; not an all-clear.",
            "outside_published_domain": "Outside model domain; inundation unknown.",
        }.get(state, "Modeled inundation unknown; not an all-clear.")
        gauges = [v for k, v in data.get("conditions", {}).items() if k.startswith("gauge:")]
        counts = Counter(g["state"] for g in gauges)
        gauge_text = "; ".join(f"{name.replace('_', ' ')}={count}" for name, count in sorted(counts.items()))
        return compact_fields(essential, ["NWS: no flood alerts", "Upstream gauges: " + (gauge_text or "coverage unknown"), target])
    if not context:
        return compact_fields("Local water data unavailable; conditions unknown.", [target])
    if command == "waterway":
        reaches = context["waterways"]
        if not reaches:
            return compact_fields("No nearby waterways in local data; coverage limited.", [target])
        r = reaches[0]
        essential = f"{short_label(r['name'] or 'Unnamed reach', 24)} {r['distance_miles']:.1f}mi; nearby only."
        return compact_fields(essential, [counted(context["waterways_total"], "reach", "reaches") + " found", target])
    basins = context["basins"]
    if not basins:
        return compact_fields("No containing CalWater basin found; coverage limited.", [target])
    basin = sorted(basins, key=lambda b: b["level"], reverse=True)[0]
    essential = f"CalWater {basin['level'][:2]}: {short_label(basin['name'] or basin['code'] or 'Unnamed', 30)}."
    return compact_fields(essential, ["Basin boundary, not current flooding", counted(len(basins), "basin level"), target])


def main(command, argv=None):
    """Dedicated entry points call this once; direct alarm calls never create subscriptions."""
    args = list(sys.argv[1:] if argv is None else argv)
    structured = "--snapshot" in args or "--json" in args
    args = [a for a in args if a not in {"--snapshot", "--json"}]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    query = None
    try:
        query = parse_query(command, " ".join(args))
        if query["action"] == "help":
            text = f"Use !{command} LOCATION. LOCATION: coordinates, ZIP, or city [state]; bare cities default CA."
            if command == "floodwarn":
                text = "!floodwarn CITY [STATE], ZIP, or LAT LON. Default state: CA."
            if command == "floodalarm":
                text += " Also: conditions LOCATION, status, stop. Enrollment requires the running service."
            print(json.dumps({"help": text}) if structured else text)
            return 0
        if command == "floodalarm" and query["action"] in {"status", "stop"}:
            raise ValueError(
                "Subscription control requires the running service; nothing changed"
            )
        mode = (
            query["mode"]
            if command == "floodalarm"
            else "alerts" if command == "floodwarn" else "conditions"
        )
        data = snapshot(query["target"], mode)
        text = (
            format_floodwarn(data)
            if command == "floodwarn"
            else format_status(
                (
                    "floodwarn"
                    if command == "floodalarm" and mode == "alerts"
                    else command
                ),
                data,
            )
        )
        if command == "floodalarm":
            text = "Standalone snapshot only; no subscription created.\n" + text
        print(json.dumps(data, ensure_ascii=False) if structured else text)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        message = str(exc)
        if command == "floodwarn":
            if query and message.startswith("Ambiguous location:"):
                message = f"Multiple matches for {query['target']}. Specify state or coordinates."
            elif message.startswith("Location not found"):
                message = "Location not found. Use ZIP or coordinates."
        print(json.dumps({"error": message}) if structured else message)
    return 0
