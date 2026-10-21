"""Shared landslide parsing and presentation; dedicated programs select their own behavior."""

from datetime import datetime, timezone
import json
import re
import sqlite3
import sys
import time

from . import landslide_alerts, landslide_settings
from .flood_warn import resolve_location
from .landslide_data import nearest_station, require_supported_location
from .time_settings import format_timestamp
from .uv_index import parse_location
from .response_text import compact_fields, short_label, counted

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
    if text.lower().startswith("details ") or text.lower() == "details" or re.search(r"\s+page\s+\d+\s*$", text, re.I):
        raise ValueError(f"Use !{command} LOCATION; details and paging are not supported.")
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
    """Preserve official event and qualified relevance; do not invent landslide warnings."""
    until = format_timestamp(datetime.fromtimestamp(alert["expires"], timezone.utc))
    mention = ("landslide mention" if alert["mention"] == "hazard mentioned in headline/description"
               else "qualified mention only")
    return compact_fields(f"NWS {alert['event']}; {mention}.", ["Until " + until])


def format_alerts(data, target, config):
    """Select highest severity, retaining explicit uncertainty for empty coverage."""
    alerts = list(data["alerts"].values())
    order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4}
    alerts.sort(key=lambda a: (order.get(a["properties"].get("severity"), 4), a["expires"], a["id"]))
    if not alerts:
        return compact_fields("No NWS landslide mentions; not an all-clear.", [short_label(target, 25)])
    return compact_fields(alert_summary(alerts[0]),
                          (["+" + counted(len(alerts)-1, "alert")] if len(alerts) > 1 else []) + [short_label(target, 25)])


def format_station(station, target):
    """Report catalog identity and distance without claiming live local measurements."""
    essential = f"{short_label(station['id'], 15)}: telemetry unverified; not local coverage."
    # Catalog names can contain quoted titles and parenthetical fire context.
    # Admit the complete name only; excerpts can leave either construct unfinished.
    return compact_fields(essential, [f"{station['distance_miles']:.1f}mi", station['name']])


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
