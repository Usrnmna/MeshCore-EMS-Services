"""Shared landslide parsing and presentation; dedicated programs select their own behavior."""

from datetime import date, datetime, timezone
import hashlib
import json
import os
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
from . import landslide_data, dataset_paths

COMMANDS = {"slidewarn", "slidealarm", "slideinfo"}


def parse_query(command, text):
    """Validate the existing ZIP/city/GPS grammar before child execution; alarm controls are explicit."""
    command = command.lstrip("!")
    if command not in COMMANDS:
        raise ValueError("Unknown landslide command")
    if len(text.encode('utf-8')) > 150 or any(not c.isprintable() for c in text):
        raise ValueError('Invalid or oversized landslide query')
    text = " ".join(text.split())
    if text.lower() in {"", "help", "--help"}:
        return {"action": "help", "target": ""}
    action = "lookup"
    if command == 'slideinfo' and text.lower().startswith('station '):
        words = text.split()
        if not 2 <= len(words) <= 4 or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', words[1]):
            raise ValueError('Use !slideinfo station ID [instruments [INDEX]|status|source]')
        selector = words[2].lower() if len(words) > 2 else 'status'
        if selector not in {'instruments', 'status', 'source'} or (len(words) == 4 and
                (selector != 'instruments' or not re.fullmatch(r'[1-9][0-9]{0,2}', words[3]))):
            raise ValueError('Invalid station metadata selector')
        return dict(action='station', target=words[1], selector=selector,
                    index=int(words[3]) if len(words) == 4 else None)
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


def station_metadata(query, now=None):
    """Resolve exact identity from a freshly checked, pinned reference generation."""
    directory = dataset_paths.resolve('landslide', landslide_data.DATA)
    paths = [directory / name for name in ('manifest.json', 'stations.json', 'california.geojson', 'nevada.geojson')]
    before = [hashlib.sha256(landslide_data.reference_bytes(path)).digest() for path in paths]
    # Do not reuse an earlier checksum result when files at a custom path change.
    landslide_data._reference.cache_clear()
    _, stations, manifest = landslide_data._reference(directory)
    if manifest.get('schema_version') != 1 or manifest.get('station_count') != len(stations):
        raise ValueError('Incompatible landslide station catalog')
    matches = [s for s in stations if isinstance(s, dict) and s.get('id') == query['target']]
    if len(matches) != 1:
        raise ValueError('Unknown station ID' if not matches else 'Ambiguous station ID')
    station = matches[0]
    for key in ('status', 'url'):
        value = station.get(key)
        if value is not None and (not isinstance(value, str) or len(value.encode('utf-8')) > 2048 or not value.isprintable()):
            raise ValueError('Invalid station metadata')
    checked = manifest.get('checked_on')
    date_state = 'undated' if checked is None or checked == '' else 'invalid date'
    checked_date = None
    try:
        if isinstance(checked, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', checked):
            checked_date = date.fromisoformat(checked)
    except ValueError:
        pass
    instant = now or datetime.now(timezone.utc)
    if instant.utcoffset() is None:
        raise ValueError('Catalog query time requires a UTC offset')
    today = instant.astimezone(timezone.utc).date()
    age = (today-checked_date).days if checked_date else None
    if age is not None:
        date_state = 'future' if age < 0 else 'dated'
    measurements = station.get('measurements')
    if measurements is not None and (not isinstance(measurements, list) or len(measurements) > 100 or
            any(not isinstance(v, str) or len(v.encode('utf-8')) > 512 or not v.isprintable() for v in measurements)):
        raise ValueError('Invalid station measurement metadata')
    index = query['index']
    if index is not None and (not measurements or index > len(measurements)):
        raise ValueError('Unknown measurement index')
    result = dict(station=station, selector=query['selector'], index=index, catalog_checked=checked,
                  catalog_age_days=age, catalog_freshness='unknown; no policy',
                  catalog_date_state=date_state,
                  qualification='Catalog only; telemetry unverified; not local coverage')
    if (dataset_paths.resolve('landslide', landslide_data.DATA) != directory or
            before != [hashlib.sha256(landslide_data.reference_bytes(path)).digest() for path in paths]):
        raise ValueError('Landslide dataset generation changed; retry')
    return result


def format_station_metadata(data):
    """Emit complete metadata and qualifications or withhold an oversized reply."""
    station, selector, index = data['station'], data['selector'], data['index']
    age = data['catalog_age_days']
    date = data['catalog_checked'] if age is not None else 'unknown'
    freshness = data['catalog_date_state'] if data['catalog_date_state'] != 'dated' else 'freshness unknown'
    if selector == 'status':
        value = 'status=' + str(station.get('status') or 'not recorded')
    elif selector == 'source':
        value = 'source=' + str(station.get('url') or 'not recorded')
    else:
        entries = station.get('measurements')
        if index:
            value = f'measurement {index}/{len(entries)}=' + entries[index-1]
        else:
            value = 'measurements=' + (', '.join(entries) if entries else 'not recorded')
    text = (f"{station['id']};{value};checked={date};{freshness};"
            'telemetry unverified; not local coverage')
    budget = 150-len(('@'+os.environ.get('MESHCORE_SENDER', 'Reader')+' ').encode('utf-8'))
    if len(text.encode('utf-8')) > budget:
        return 'Station detail too long; use instruments INDEX or local --json.'
    return text


def main(command, argv=None):
    """Run one bounded lookup; standalone alarm invocation never enrolls a subscription."""
    args = list(sys.argv[1:] if argv is None else argv)
    structured = "--json" in args or "--snapshot" in args
    args = [a for a in args if a not in {"--json", "--snapshot"}]
    if command == 'slideinfo' and structured and os.environ.get('MESHCORE_REQUEST_ID'):
        print('JSON is local-only.')
        return 0
    try:
        query = parse_query(command, " ".join(args))
        if query["action"] == "help":
            output = ("Use !slidealarm on LOCATION, status, or off." if command == "slidealarm" else
                      f"Use !{command} LOCATION.") + " LOCATION: ZIP, CITY [CA/NV], or LATITUDE LONGITUDE (comma optional); California and Nevada. Bare cities default to CA."
            if command == 'slideinfo':
                output = compact_fields('!slideinfo station ID or LOCATION.', ['instruments INDEX; status; source', 'CA/NV; telemetry unverified'])
            print(json.dumps({"help": output}) if structured else output)
            return 0
        if command == "slidealarm" and query["action"] in {"off", "status"}:
            output = "Subscription control requires the running MeshCore service; no subscription was changed."
            print(json.dumps({"error": output}) if structured else output)
            return 0
        config = landslide_settings.load()
        if not config["enabled"]:
            raise ValueError("Landslide commands are disabled in configuration.")
        if command == 'slideinfo' and query['action'] == 'station':
            data = station_metadata(query)
            text = format_station_metadata(data)
        elif command == "slideinfo":
            latitude, longitude = resolve(query["target"])
            data = nearest_station(latitude, longitude)
            text = format_station(data, query["target"])
        else:
            latitude, longitude = resolve(query["target"])
            data = landslide_alerts.snapshot(latitude, longitude, config)
            text = format_alerts(data, query["target"], config)
            if command == "slidealarm":
                text = "Standalone lookup only; no subscription created.\n" + text
        print(json.dumps(data, ensure_ascii=False, allow_nan=False) if structured else text)
    except (ValueError, RuntimeError, OSError, sqlite3.Error, KeyError, TypeError, AttributeError) as exc:
        message = "Landslide lookup unavailable: " + str(exc)
        if command == 'slideinfo' and not structured:
            budget = 150-len(('@'+os.environ.get('MESHCORE_SENDER', 'Reader')+' ').encode('utf-8'))
            if len(message.encode('utf-8')) > budget:
                message = 'Station lookup unavailable; check query or local data.'
        print(json.dumps({"error": message}) if structured else message)
    return 0
