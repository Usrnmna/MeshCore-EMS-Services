"""Bounded official point alerts and latest NOAA conditions, with current-only caching."""

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import sqlite3
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import water_agency_review, water_identifiers, water_settings
from .flood_warn import ALERTS, timestamp

NWS = "https://api.weather.gov"
NWPS = "https://api.water.noaa.gov/nwps/v1/gauges/"
FIM = "https://maps.water.noaa.gov/server/rest/services/nwm/ana_inundation_extent/FeatureServer/0"
DOMAIN = "https://maps.water.noaa.gov/server/rest/services/reference/static_public_fim_domain/MapServer/0"
QPE = "https://mapservices.weather.noaa.gov/raster/rest/services/obs/rfc_qpe/MapServer"
MAX_BYTES = 8 * 1024 * 1024


def get_json(url, params=None):
    """Fetch bounded JSON; stale HTTP caches and source errors cannot become valid conditions."""
    url += ("?" + urlencode(params)) if params else ""
    request = Request(
        url,
        headers={
            "User-Agent": "MC-EMS-Services-Water/1.0",
            "Accept": "application/geo+json, application/json",
        },
    )
    with urlopen(request, timeout=12) as response:
        if float(response.headers.get("Age", "0")) > 300:
            raise ValueError("Source HTTP response is stale")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Water response exceeds size limit")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("error"):
        raise ValueError("Source returned an error or invalid JSON")
    return data


def cached(key, config, fetch, now=None, path=None):
    """Replace one current record per product/target; errors never return old data as fresh.

    Fetchers must remove historical levels before returning. No raw gauge payload is
    persisted. Secure deletion and DELETE journals avoid accumulating obsolete levels.
    """
    now = time.time() if now is None else now
    path = path or water_settings.runtime() / "water_current.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    try:
        db.execute("PRAGMA secure_delete=ON")
        db.execute(
            "CREATE TABLE IF NOT EXISTS current(key TEXT PRIMARY KEY, fetched REAL, attempted REAL, body TEXT, error TEXT)"
        )
        row = db.execute(
            "SELECT fetched,attempted,body,error FROM current WHERE key=?", (key,)
        ).fetchone()
        if row and 0 <= now - row[1] < config["cache_seconds"]:
            if row[3]:
                raise ValueError(row[3])
            return json.loads(row[2])
        try:
            data = fetch()
        except Exception as exc:
            db.execute(
                "INSERT OR REPLACE INTO current VALUES(?,?,?,?,?)",
                (key, None, now, None, str(exc)),
            )
            db.commit()
            raise ValueError(str(exc)) from exc
        db.execute(
            "INSERT OR REPLACE INTO current VALUES(?,?,?,?,NULL)",
            (key, now, now, json.dumps(data, allow_nan=False)),
        )
        db.execute("DELETE FROM current WHERE attempted<?", (now - 86400,))
        db.execute(
            "DELETE FROM current WHERE key IN (SELECT key FROM current ORDER BY attempted DESC LIMIT -1 OFFSET 1000)"
        )
        db.commit()
        return data
    finally:
        db.close()


def select_alerts(data, now):
    """Keep actual effective flood CAP records, references and material-content fingerprints."""
    if (
        data.get("type") != "FeatureCollection"
        or not isinstance(data.get("features"), list)
        or data.get("pagination", {}).get("next")
    ):
        raise ValueError("Incomplete or invalid NWS collection")
    alerts, superseded, cancelled, seen = {}, set(), set(), set()
    for feature in data["features"]:
        if not isinstance(feature, dict):
            raise ValueError("Invalid NWS feature")
        p = feature.get("properties")
        if not isinstance(p, dict):
            raise ValueError("Invalid NWS alert")
        if p.get("event") not in ALERTS:
            continue
        if p.get("status") in {"Exercise", "System", "Test", "Draft"}:
            continue
        if p.get("status") != "Actual" or p.get("messageType") not in {
            "Alert",
            "Update",
            "Cancel",
        }:
            raise ValueError("Invalid NWS flood message status")
        key = p.get("id") or feature.get("id")
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("NWS alert ID missing")
        seen.add(key)
        effective = timestamp(p.get("effective")).timestamp()
        expires = min(
            timestamp(p.get("expires")).timestamp(),
            timestamp(p.get("ends") or p["expires"]).timestamp(),
        )
        references = p.get("references") or []
        if not isinstance(references, list) or any(
            not isinstance(r, dict) for r in references
        ):
            raise ValueError("Invalid NWS references")
        refs = [
            r["identifier"] for r in references if isinstance(r.get("identifier"), str)
        ]
        if effective <= now:
            superseded.update(refs)
            if p["messageType"] == "Cancel":
                cancelled.update(refs)
        if p["messageType"] == "Cancel" or not effective <= now < expires:
            continue
        fields = {
            k: p.get(k)
            for k in (
                "event",
                "headline",
                "description",
                "instruction",
                "severity",
                "urgency",
                "certainty",
                "effective",
                "expires",
                "ends",
                "areaDesc",
                "affectedZones",
                "geocode",
            )
        }
        fields["geometry"] = feature.get("geometry")
        fingerprint = hashlib.sha256(
            json.dumps(fields, sort_keys=True).encode()
        ).hexdigest()
        for field in (
            "headline",
            "description",
            "instruction",
            "areaDesc",
            "severity",
            "urgency",
            "certainty",
        ):
            if p.get(field) is not None and not isinstance(p[field], str):
                raise ValueError("Invalid NWS alert text")
        alerts[key] = {
            "id": key,
            "event": p["event"],
            "expires": expires,
            "effective": effective,
            "references": refs,
            "fingerprint": fingerprint,
            "headline": p.get("headline") or p["event"],
            "instruction": p.get("instruction") or "See full NWS alert.",
            "description": p.get("description") or "",
            "area": p.get("areaDesc") or "",
            "severity": p.get("severity") or "",
            "urgency": p.get("urgency") or "",
            "certainty": p.get("certainty") or "",
            "url": NWS + "/alerts/" + key.removeprefix(NWS + "/alerts/"),
        }
    return {
        "alerts": {k: v for k, v in alerts.items() if k not in superseded},
        "cancelled_ids": sorted(cancelled),
    }


def alerts_at(lat, lon, config, now, fetch=get_json):
    """Check NWS coverage before interpreting an empty point-matched alert response."""
    point = f"{lat:.6f},{lon:.6f}"

    def retrieve():
        coverage = fetch(NWS + "/points/" + point)
        if coverage.get("type") != "Feature" or not coverage.get("properties", {}).get(
            "forecastZone"
        ):
            raise ValueError("NWS point coverage could not be verified")
        raw = fetch(NWS + "/alerts/active", {"point": point, "status": "actual"})
        return dict(
            select_alerts(raw, now),
            fetched=now,
            source=NWS + "/alerts/active?point=" + point,
        )

    result = cached("alerts:" + point, config, retrieve, now)
    # A cached alert can expire between checks; its expiry is evaluated on every use.
    result["alerts"] = {
        k: v
        for k, v in result["alerts"].items()
        if v["effective"] <= now < v["expires"]
    }
    return result


def gauge(lid, station_id, config, now, fetch=get_json):
    """Use NOAA's own observation/category; never apply NOAA stage thresholds to USGS datums."""
    if not re.fullmatch(r"[A-Za-z0-9]{3,8}", lid):
        raise ValueError("Invalid NWPS identifier")
    agency_successor = False
    if (
        station_id == water_agency_review.SUCCESSOR_ID
        and lid == water_agency_review.SUCCESSOR_LID
    ):
        review, _ = water_identifiers.load()
        reviewed = review.get(station_id, {})
        agency_successor = reviewed.get("identity_status") == "matched_agency_successor"
        if reviewed.get("lid") != lid or reviewed.get("identity_status") not in {
            "matched",
            "matched_agency_successor",
        }:
            raise ValueError("Agency successor review unavailable; link withheld")

    def retrieve():
        raw = fetch(NWPS + lid)
        if agency_successor:
            if not water_agency_review.api_matches(raw):
                raise ValueError("NWPS agency-successor identity conflict")
        elif (
            str(raw.get("lid", "")).upper() != lid.upper()
            or "USGS-" + str(raw.get("usgsId")) != station_id
        ):
            raise ValueError("NWPS/USGS identity conflict")
        # Deliberate allowlist excludes flood.crests, stageflow history and historical impacts.
        return {
            "lid": lid,
            "station_id": station_id,
            "identity_basis": (
                "agency_successor" if agency_successor else "exact_usgs_id"
            ),
            "observation": raw.get("status", {}).get("observed"),
            "in_service": raw.get("inService", {}).get("enabled"),
            "thresholds": raw.get("flood", {}).get("categories", {}),
            "stage_units": raw.get("flood", {}).get("stageUnits"),
            "datums": raw.get("datums"),
            "fetched": now,
            "source": NWPS + lid,
        }

    result = cached("gauge:" + station_id + ":" + lid, config, retrieve, now)
    expected_basis = "agency_successor" if agency_successor else "exact_usgs_id"
    if result.get("identity_basis", "exact_usgs_id") != expected_basis:
        # Replace a cache entry verified under the previous identity rule. This also
        # permits recovery when NOAA begins publishing the exact legacy USGS ID.
        result = cached(
            "gauge:" + station_id + ":" + lid,
            dict(config, cache_seconds=0),
            retrieve,
            now,
        )
    # The source category alone is insufficient when its thresholds are undefined.
    # A no_flooding category needs a published minor threshold; other categories
    # need their own threshold. No threshold is transferred to a USGS datum.
    categories = water_identifiers.thresholds(result.get("thresholds"))
    obs = result.get("observation")
    state = "unavailable"
    if isinstance(obs, dict):
        try:
            age = now - timestamp(obs.get("validTime")).timestamp()
            primary = obs.get("primary")
            valid = (
                type(primary) in (int, float)
                and math.isfinite(primary)
                and primary > -999
            )
            category = obs.get("floodCategory")
            required = "minor" if category == "no_flooding" else category
            supported_category = any(
                value is not None for value in categories.get(required, {}).values()
            )
            state = (
                "out_of_service"
                if result["in_service"] is not True
                else (
                    "invalid"
                    if not valid
                    else (
                        "future"
                        if age < 0
                        else (
                            "stale"
                            if age > config["reading_max_age"]
                            else (
                                category
                                if supported_category
                                and category
                                in {
                                    "no_flooding",
                                    "action",
                                    "minor",
                                    "moderate",
                                    "major",
                                }
                                else "threshold_unavailable"
                            )
                        )
                    )
                )
            )
        except (ValueError, RuntimeError, TypeError):
            state = "invalid"
    return dict(
        result,
        condition=state,
        threshold_status=water_identifiers.threshold_status(result.get("thresholds")),
    )


def arc_features(url, params, fetch):
    data = fetch(url + "/query", dict(f="json", returnGeometry="false", **params))
    if data.get("exceededTransferLimit") or not isinstance(data.get("features"), list):
        raise ValueError("Incomplete GIS response")
    return [f["attributes"] for f in data["features"]]


def model_at(lat, lon, config, now, fetch=get_json):
    """Point-intersect current modeled footprints; missing features do not mean safe conditions."""
    point = f"{lon:.6f},{lat:.6f}"
    params = {
        "geometry": point,
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
    }

    def retrieve():
        domain = arc_features(DOMAIN, params, fetch)
        if not domain:
            return {
                "condition": "outside_published_domain",
                "fetched": now,
                "source": FIM,
            }
        rows = arc_features(FIM, params, fetch)
        # An empty filtered layer does not establish model freshness or a dry point.
        return {"rows": rows, "fetched": now, "source": FIM}

    result = cached("fim:" + point, config, retrieve, now)
    if "rows" not in result:
        return result
    fresh = []
    for row in result["rows"]:
        try:
            # HydroVIS explicitly labels update_time UTC; reject an unlabelled reference time.
            updated = timestamp(
                row["update_time"].replace(" UTC", "+00:00")
            ).timestamp()
            if 0 <= now - updated <= config["model_max_age"]:
                fresh.append(row)
        except (KeyError, ValueError, RuntimeError, TypeError, AttributeError):
            pass
    state = (
        "modeled_footprint_intersects_point"
        if fresh
        else (
            "stale_or_unverified_time"
            if result["rows"]
            else "no_current_footprint_returned_not_all_clear"
        )
    )
    return dict(result, condition=state)


def rainfall_at(lat, lon, config, now, fetch=get_json):
    """Expose the current 24-hour QPE pixel as point context, never as a basin-average total."""

    def retrieve():
        raw = fetch(
            QPE + "/identify",
            {
                "f": "json",
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "sr": 4326,
                "layers": "all:28",
                "tolerance": 0,
                "mapExtent": f"{lon-.1},{lat-.1},{lon+.1},{lat+.1}",
                "imageDisplay": "1000,1000,96",
                "returnGeometry": "false",
            },
        )
        rows = [r for r in raw.get("results", []) if r.get("layerId") == 28]
        if len(rows) != 1:
            raise ValueError("QPE pixel unavailable or ambiguous")
        attrs = rows[0].get("attributes", {})
        value = float(attrs.get("Service Pixel Value"))
        if not math.isfinite(value) or value < 0:
            raise ValueError("QPE pixel is no-data")
        return {
            "value": value,
            "units": "in",
            "period": "last 24 hours",
            "fetched": now,
            "source": QPE,
            "source_time": None,
            "interpretation": "point grid estimate; source valid time unavailable; not a basin mean or alarm trigger",
        }

    return cached(f"rain:{lat:.6f},{lon:.6f}", config, retrieve, now)
