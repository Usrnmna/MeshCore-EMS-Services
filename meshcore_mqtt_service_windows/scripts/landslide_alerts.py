"""Bounded NWS point queries with a shared, atomic cache and explicit failure states."""

import hashlib
import json
import re
import sqlite3
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .flood_warn import timestamp
from .landslide_data import require_supported_location
from .landslide_settings import database_path

NWS = "https://api.weather.gov"
MAX_BYTES = 4 * 1024 * 1024
HAZARD = re.compile(r"\b(?:land\s*slides?|debris[\s-]*flows?|mud[\s-]*(?:slides?|flows?))\b", re.I)
NEGATED = re.compile(r"\b(?:no|not|unlikely|not expected|not anticipated)\b", re.I)


def get_json(url):
    """Read bounded NWS JSON; reject known stale HTTP responses instead of refreshing their age."""
    request = Request(url, headers={"User-Agent": "MC-EMS-Services-Landslide/1.0",
                                    "Accept": "application/geo+json, application/json"})
    with urlopen(request, timeout=12) as response:
        if float(response.headers.get("Age", "0")) > 300:
            raise ValueError("NWS response is stale")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("NWS response exceeds size limit")
    return json.loads(raw)


def relevance(properties):
    """Identify explicit source wording; precaution-only and negated mentions remain labelled context."""
    matched = []
    for field in ("headline", "description", "instruction"):
        text = properties.get(field) or ""
        if not isinstance(text, str):
            raise ValueError("Invalid NWS alert text")
        if HAZARD.search(text):
            matched.append(field)
    if not matched:
        return None
    # Classification describes where the source mentions the hazard, never a new warning level.
    body = " ".join(properties.get(k) or "" for k in ("headline", "description"))
    sentences = re.split(r"[.!?\n]+", body)
    direct = any(HAZARD.search(s) and not NEGATED.search(s) for s in sentences)
    return "hazard mentioned in headline/description" if direct else "precautionary/qualified mention only"


def select_alerts(data, now):
    """Validate a complete point response and retain effective actual alerts mentioning slide hazards."""
    if (not isinstance(data, dict) or data.get("type") != "FeatureCollection"
            or not isinstance(data.get("features"), list)):
        raise ValueError("Invalid NWS alert collection")
    if data.get("pagination", {}).get("next"):
        raise ValueError("Incomplete NWS alert collection")
    alerts, superseded, cancelled, seen = {}, set(), set(), set()
    for feature in data["features"]:
        if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
            raise ValueError("Invalid NWS alert record")
        p = feature["properties"]
        if p.get("status") in {"Exercise", "System", "Test", "Draft"}:
            continue
        if p.get("status") != "Actual":
            raise ValueError("Invalid NWS alert status")
        key = p.get("id") or feature.get("id")
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("Missing/duplicate NWS alert ID")
        seen.add(key)
        message_type = p.get("messageType")
        if message_type not in {"Alert", "Update", "Cancel"}:
            raise ValueError("Invalid NWS alert message type")
        effective = timestamp(p.get("effective")).timestamp()
        expires = timestamp(p.get("expires")).timestamp()
        ends = timestamp(p["ends"]).timestamp() if p.get("ends") else expires
        references = p.get("references") or []
        if not isinstance(references, list) or any(not isinstance(r, dict) for r in references):
            raise ValueError("Invalid NWS alert references")
        refs = [r.get("identifier") for r in references if isinstance(r.get("identifier"), str)]
        if effective <= now:
            superseded.update(refs)
            if message_type == "Cancel":
                cancelled.update(refs)
        if message_type == "Cancel" or not effective <= now < min(expires, ends):
            continue
        label = relevance(p)
        if label is None:
            continue
        if not isinstance(p.get("event"), str) or not p["event"]:
            raise ValueError("Invalid NWS event name")
        # Preserve the original CAP fields and geometry for --json, without inventing polygons.
        digest_fields = {k: p.get(k) for k in (
            "event", "headline", "description", "instruction", "areaDesc", "severity",
            "urgency", "certainty", "effective", "onset", "expires", "ends", "affectedZones", "geocode")}
        digest_fields["geometry"] = feature.get("geometry")
        digest = hashlib.sha256(json.dumps(digest_fields, sort_keys=True).encode()).hexdigest()
        alerts[key] = {"id": key, "event": p["event"], "mention": label, "references": refs,
                       "expires": min(expires, ends), "fingerprint": digest, "properties": p,
                       "url": NWS + "/alerts/" + key.removeprefix(NWS + "/alerts/"),
                       "geometry": feature.get("geometry")}
    return {"alerts": {k: v for k, v in alerts.items() if k not in superseded},
            "cancelled_ids": sorted(cancelled)}


def fetch_point(latitude, longitude, now=None, fetch=get_json):
    """Verify NWS coverage before querying point-matched alerts, including alerts without geometry."""
    require_supported_location(latitude, longitude)
    point = f"{latitude:.6f},{longitude:.6f}"
    coverage = fetch(NWS + "/points/" + point)
    if (not isinstance(coverage, dict) or coverage.get("type") != "Feature"
            or not isinstance(coverage.get("properties"), dict)
            or not coverage["properties"].get("forecastZone")):
        raise ValueError("Unable to verify NWS coverage")
    url = NWS + "/alerts/active?" + urlencode({"point": point, "status": "actual"})
    raw = fetch(url)
    fetched = time.time() if now is None else now
    result = select_alerts(raw, fetched)
    return dict(result, point=[latitude, longitude], fetched=fetched, source=url,
                coverage=coverage["properties"]["forecastZone"], raw=raw)


def prune_cache(db, current):
    """Bound successful and failed point records within the caller's cache transaction."""
    db.execute("DELETE FROM points WHERE attempted<?", (current - 7 * 86400,))
    db.execute("DELETE FROM points WHERE point IN (SELECT point FROM points ORDER BY attempted DESC LIMIT -1 OFFSET 1000)")


def snapshot(latitude, longitude, config, path=None, now=None, fetcher=fetch_point):
    """Share fresh point snapshots across commands/subscribers; failed refreshes never become clear.

    A short SQLite writer lock prevents duplicate concurrent refreshes. Failed attempts
    retain the last successful payload for diagnosis but it is not returned as current.
    At most 1,000 points and seven days of unused point state are retained.
    """
    latitude, longitude = require_supported_location(latitude, longitude)
    point = f"{latitude:.6f},{longitude:.6f}"
    # Query and cache the same rounded point; reject rounding across the state boundary.
    latitude, longitude = require_supported_location(*map(float, point.split(",")))
    path = database_path() if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=1)
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValueError("Unsupported landslide cache schema")
        db.execute("CREATE TABLE IF NOT EXISTS points(point TEXT PRIMARY KEY, fetched REAL, attempted REAL, body TEXT, error TEXT)")
        db.execute("PRAGMA user_version=1")
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        current = time.time() if now is None else now
        row = db.execute("SELECT fetched,attempted,body,error FROM points WHERE point=?", (point,)).fetchone()
        if row and 0 <= current - row[1] < config["cache_seconds"]:
            if row[3]:
                raise ValueError("NWS lookup unavailable; previous data retained: " + row[3])
            data = json.loads(row[2])
            # Expiry still applies during the cache interval.
            data.update(select_alerts(data["raw"], current))
            return data
        try:
            data = fetcher(latitude, longitude, now=now)
        except Exception as exc:
            db.execute("INSERT INTO points VALUES(?,?,?,?,?) ON CONFLICT(point) DO UPDATE SET attempted=excluded.attempted,error=excluded.error",
                       (point, None, current, None, str(exc)[:300]))
            prune_cache(db, current)
            db.commit()
            raise ValueError("NWS landslide alert lookup unavailable: " + str(exc)) from exc
        db.execute("INSERT OR REPLACE INTO points VALUES(?,?,?,?,NULL)",
                   (point, data["fetched"], current, json.dumps(data, allow_nan=False)))
        prune_cache(db, current)
        db.commit()
        return data
    finally:
        db.close()
