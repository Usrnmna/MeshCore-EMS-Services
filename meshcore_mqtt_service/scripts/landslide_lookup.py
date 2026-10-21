"""Shared landslide parsing and presentation; dedicated programs select their own behavior."""

from datetime import datetime, timezone
import json
import sqlite3
import sys
import time

from . import landslide_alerts, landslide_settings
from .flood_warn import resolve_location
from .landslide_data import nearest_station, require_supported_location
from .time_settings import format_timestamp
from .uv_index import parse_location

COMMANDS = {"slidewarn", "slidealarm", "slideinfo"}


def parse_query(command, text):
    """Validate the existing ZIP/city/GPS grammar before child execution; alarm controls are explicit."""
    command = command.lstrip("!")
    if command not in COMMANDS:
        raise ValueError("Unknown landslide command")
    text = " ".join(text.split())
    if text.lower() in {"", "help", "--help"}:
        return {"action": "help", "target": ""}
    action = "lookup"
    if command == "slidealarm":
        if text.lower() in {"status", "off"}:
            return {"action": text.lower(), "target": ""}
        action, _, text = text.partition(" ")
        if action.lower() != "on" or not text:
            raise ValueError("Use !slidealarm on LOCATION, status, or off.")
        action = "on"
    if command == "slideinfo" and text.lower().startswith("near "):
        text = text[5:]
    try:
        parsed = parse_location(text)
    except ValueError as exc:
        raise ValueError(str(exc).replace("!uv", "!" + command)) from exc
    if parsed[0] == "city" and parsed[2] not in {"California", "Nevada"}:
        raise ValueError("Landslide commands support California and Nevada locations only.")
    return {"action": action, "target": text}


def resolve(target):
    """Use the flood/UV location contract, then check the California/Nevada boundary."""
    return require_supported_location(*resolve_location(parse_location(target)))


def checked_snapshot(data, config, now=None):
    """Validate child/cache snapshots before enabling or changing a persistent subscription."""
    now = time.time() if now is None else now
    if not isinstance(data, dict) or data.get("error"):
        raise ValueError(data.get("error", "Invalid landslide snapshot") if isinstance(data, dict) else "Invalid landslide snapshot")
    if not isinstance(data.get("point"), list) or len(data["point"]) != 2:
        raise ValueError("Invalid landslide snapshot point")
    require_supported_location(*data["point"])
    fetched = data.get("fetched")
    if type(fetched) not in (int, float) or not 0 <= now - fetched <= config["cache_seconds"]:
        raise ValueError("Landslide snapshot unavailable or stale")
    # Recompute classification/expiry/fingerprints instead of trusting presentation or stale child fields.
    data.update(landslide_alerts.select_alerts(data.get("raw"), now))
    return data


def shorten(text, limit):
    """Collapse CAP whitespace and explicitly mark excerpts that exceed the radio budget."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def alert_summary(alert):
    """Keep official event/issuer and validity ahead of a bounded source-text excerpt."""
    p = alert["properties"]
    until = format_timestamp(datetime.fromtimestamp(alert["expires"], timezone.utc))
    issue = p.get("sent") or p.get("effective")
    issued = format_timestamp(landslide_alerts.timestamp(issue))
    excerpt = p.get("headline") or p.get("description") or p.get("instruction")
    return (f"{alert['event']} ({p.get('senderName') or 'NWS'}), issued {issued}, until {until}; "
            f"{alert['mention']}. {shorten(excerpt, 150)} "
            f"Instructions (excerpt): {shorten(p.get('instruction') or 'See full NWS alert.', 180)} "
            f"{alert['url']}")


def format_alerts(data, target, config):
    """Report fresh point matches with source age; an empty response is never an all-clear."""
    checked = format_timestamp(datetime.fromtimestamp(data["fetched"], timezone.utc))
    lat, lon = data["point"]
    lines = [f"{target} ({lat:.5f}, {lon:.5f}); NWS checked {checked}."]
    alerts = list(data["alerts"].values())
    order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4}
    alerts.sort(key=lambda a: (order.get(a["properties"].get("severity"), 4), a["expires"], a["id"]))
    if not alerts:
        lines.append("No active NWS alerts mentioning landslide/debris-flow hazards found for this location. This is not an all-clear.")
    else:
        lines.append(f"{len(alerts)} matching alert(s); official product names retained.")
        lines.extend(alert_summary(a) for a in alerts[:config["max_alerts"]])
        if len(alerts) > config["max_alerts"]:
            lines.append(f"{len(alerts) - config['max_alerts']} more; full list: {data['source']}")
    return "\n".join(lines)


def format_station(station, target):
    """Describe catalog metadata, never imply a live sensor reading or coverage at the query point."""
    return (f"{target}: nearest eligible USGS station in the California catalog: {station['name']} ({station['id']}), "
            f"{station['distance_miles']:.1f} mi. Catalog checked {station['catalog_checked']}. "
            f"Monitors: {', '.join(station['measurements'])}. Published graph interval: "
            f"{station['graph_minutes']} min; current telemetry status unverified. "
            "Preliminary site observations; distance does not establish local conditions or warning coverage. "
            f"Graphs/info: {station['url']}")


def main(command, argv=None):
    """Run one bounded lookup; standalone alarm invocation never enrolls a subscription."""
    args = list(sys.argv[1:] if argv is None else argv)
    structured = "--json" in args or "--snapshot" in args
    args = [a for a in args if a not in {"--json", "--snapshot"}]
    try:
        query = parse_query(command, " ".join(args))
        if query["action"] == "help":
            output = ("Use !slidealarm on LOCATION, status, or off." if command == "slidealarm" else
                      f"Use !{command} LOCATION.") + " LOCATION: ZIP, CITY [CA/NV], or LATITUDE LONGITUDE (comma optional); California and Nevada. Bare cities default to CA."
            print(json.dumps({"help": output}) if structured else output)
            return 0
        if command == "slidealarm" and query["action"] in {"off", "status"}:
            output = "Subscription control requires the running MeshCore service; no subscription was changed."
            print(json.dumps({"error": output}) if structured else output)
            return 0
        config = landslide_settings.load()
        if not config["enabled"]:
            raise ValueError("Landslide commands are disabled in configuration.")
        latitude, longitude = resolve(query["target"])
        if command == "slideinfo":
            data = nearest_station(latitude, longitude)
            text = format_station(data, query["target"])
        else:
            data = landslide_alerts.snapshot(latitude, longitude, config)
            text = format_alerts(data, query["target"], config)
            if command == "slidealarm":
                text = "Standalone lookup only; no subscription created.\n" + text
        print(json.dumps(data, ensure_ascii=False, allow_nan=False) if structured else text)
    except (ValueError, RuntimeError, OSError, sqlite3.Error, KeyError, TypeError, AttributeError) as exc:
        message = "Landslide lookup unavailable: " + str(exc)
        print(json.dumps({"error": message}) if structured else message)
    return 0
