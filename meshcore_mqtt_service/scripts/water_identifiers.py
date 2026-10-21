"""Review exact NOAA/USGS identifiers without modifying the original inventory.

The bundled table records the investigated stations. An explicit refresh replaces
the runtime review, including failures; unsuccessful checks cannot revive an old
match. Only static identity/threshold metadata is persisted, never observations.
"""

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
import re
from urllib.request import Request, urlopen

from . import water_settings

CATALOG = (
    "https://water.noaa.gov/resources/downloads/reports/nwps_all_gauges_report.csv"
)
GAUGES = "https://api.water.noaa.gov/nwps/v1/gauges/"
REVIEW_FILE = "WATER_STATION_REVIEW.json"
CATEGORIES = ("action", "minor", "moderate", "major")
STATUSES = {
    "matched",
    "no_exact_catalog_match",
    "ambiguous_catalog_match",
    "identity_conflict",
    "source_unavailable",
    "matched_agency_successor",
}


def threshold_value(value):
    """Normalize missing/sentinel thresholds; zero is a valid published threshold."""
    return (
        value
        if type(value) in (int, float) and math.isfinite(value) and value > -999
        else None
    )


def thresholds(categories):
    """Keep only static stage/flow thresholds from known NOAA categories."""
    categories = categories if isinstance(categories, dict) else {}
    return {
        category: {
            kind: threshold_value((categories.get(category) or {}).get(kind))
            for kind in ("stage", "flow")
        }
        for category in CATEGORIES
        if isinstance(categories.get(category, {}), dict)
    }


def threshold_status(categories):
    """Distinguish published values, explicit missing values and absent source schema."""
    if any(
        v is not None for row in thresholds(categories).values() for v in row.values()
    ):
        return "published"
    if not isinstance(categories, dict) or any(
        not isinstance(categories.get(category), dict)
        or not {"stage", "flow"}.issubset(categories[category])
        for category in CATEGORIES
    ):
        return "unverified"
    return "none_published"


def download_catalog():
    """Download a bounded national static report, with no historical level products."""
    request = Request(CATALOG, headers={"User-Agent": "MC-EMS-Services-Water/1.0"})
    with urlopen(request, timeout=30) as response:
        if float(response.headers.get("Age", "0")) > 86400:
            raise ValueError("NOAA catalog HTTP cache exceeds one day")
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("NOAA catalog exceeds size limit")
    return raw


def parse_catalog(raw):
    """Reject schema changes, short national reports and conflicting identifier rows."""
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    required = {"usgs id", "nws shef id", "location name", "state"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("NOAA catalog schema changed")
    rows = list(reader)
    if len(rows) < 1000 or any(
        None in row or any(row[k] is None for k in required) for row in rows
    ):
        raise ValueError("NOAA national catalog is incomplete")
    by_station, lid_owners = {}, {}
    for row in rows:
        sid, lid = row["usgs id"].strip(), row["nws shef id"].strip().upper()
        if sid:
            by_station.setdefault("USGS-" + sid, []).append(row)
        lid_owners.setdefault(lid, set()).add(sid)
    return rows, by_station, lid_owners


def review(targets, catalog_fetch=download_catalog, gauge_fetch=None):
    """Corroborate each unique exact catalog ID with the independent gauge response.

    Names and proximity never authorize a match. Duplicate catalog entries,
    conflicting API identities and source failures retain explicit withheld rows.
    """
    from .water_sources import get_json

    gauge_fetch = gauge_fetch or get_json
    result = {
        "schema": 1,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "catalog_source": CATALOG,
        "catalog_sha256": None,
        "catalog_rows": 0,
        "stations": [],
    }
    try:
        raw = catalog_fetch()
        rows, by_station, lid_owners = parse_catalog(raw)
        result.update(
            catalog_sha256=hashlib.sha256(raw).hexdigest(), catalog_rows=len(rows)
        )
    except Exception as exc:
        result["stations"] = [
            dict(
                t,
                lid="",
                identity_status="source_unavailable",
                threshold_status="unverified",
                reason="Catalog unavailable: " + str(exc),
            )
            for t in targets
        ]
        return result

    def check(target):
        row = dict(
            target,
            lid="",
            identity_status="no_exact_catalog_match",
            threshold_status="unverified",
        )
        matches = by_station.get(target["station_id"], [])
        row["catalog_candidates"] = sorted(
            {m["nws shef id"].strip().upper() for m in matches}
        )
        if not matches:
            row["reason"] = (
                "No exact USGS identifier in the retrieved national report; not proof that no other agency gauge exists."
            )
            return row
        lid = matches[0]["nws shef id"].strip().upper()
        if (
            len(matches) != 1
            or len(lid_owners.get(lid, ())) != 1
            or not re.fullmatch(r"[A-Z0-9]{3,8}", lid)
        ):
            row.update(
                identity_status="ambiguous_catalog_match",
                reason="Non-unique or invalid catalog identity; link withheld.",
            )
            return row
        row["gauge_source"] = GAUGES + lid
        try:
            data = gauge_fetch(row["gauge_source"])
            if (
                str(data.get("lid", "")).upper() != lid
                or "USGS-" + str(data.get("usgsId", "")) != target["station_id"]
            ):
                row.update(
                    identity_status="identity_conflict",
                    reason="Gauge API and catalog identities disagree; link withheld.",
                )
                return row
            flood = data.get("flood") or {}
            if not isinstance(flood.get("categories"), dict) or any(
                not isinstance(flood["categories"].get(category), dict)
                for category in CATEGORIES
            ):
                raise ValueError("NOAA threshold schema changed")
            category_values = thresholds(flood.get("categories"))
            row.update(
                lid=lid,
                identity_status="matched",
                threshold_status=threshold_status(category_values),
                noaa_name=data.get("name"),
                thresholds=category_values,
                stage_units=flood.get("stageUnits"),
                flow_units=flood.get("flowUnits"),
                api_usgs_id=data["usgsId"],
                api_lid=data["lid"],
                reason="Exact unique USGS ID in NOAA catalog, corroborated by NOAA gauge API; current responses must revalidate identity.",
            )
        except Exception as exc:
            row.update(
                identity_status="source_unavailable",
                reason="Gauge API unavailable: " + str(exc),
            )
        return row

    with ThreadPoolExecutor(max_workers=3) as pool:
        result["stations"] = list(pool.map(check, targets))
    from . import water_agency_review, water_map_review

    water_agency_review.enrich(result, gauge_fetch)
    water_map_review.enrich(result, gauge_fetch)
    return result


def validate(document):
    """Validate local review records before permitting supplemental identifier use."""
    if document.get("schema") != 1 or document.get("catalog_source") != CATALOG:
        raise ValueError("Unsupported NOAA identifier review")
    instant = datetime.fromisoformat(document["retrieved_at"])
    if instant.tzinfo is None:
        raise ValueError("NOAA review timestamp must include timezone")
    rows = {}
    for row in document["stations"]:
        sid, lid = row["station_id"], row.get("lid", "")
        if (
            sid in rows
            or not re.fullmatch(r"USGS-\d{8,15}", sid)
            or row["identity_status"] not in STATUSES
        ):
            raise ValueError("Invalid or duplicate NOAA review station")
        if row["identity_status"] == "matched":
            if (
                not re.fullmatch(r"[A-Z0-9]{3,8}", lid)
                or row.get("catalog_candidates") != [lid]
                or row.get("gauge_source") != GAUGES + lid
                or "USGS-" + str(row.get("api_usgs_id")) != sid
                or str(row.get("api_lid", "")).upper() != lid
                or row.get("threshold_status")
                != threshold_status(row.get("thresholds"))
            ):
                raise ValueError("Unsupported NOAA review match")
        elif row["identity_status"] == "matched_agency_successor":
            from . import water_agency_review as agency

            if (
                sid != agency.SUCCESSOR_ID
                or lid != agency.SUCCESSOR_LID
                or row.get("gauge_source") != GAUGES + lid
                or row.get("agency_review", {}).get("status")
                != "supported_agency_successor"
                or not agency.api_matches(
                    {
                        "lid": row.get("api_lid"),
                        "usgsId": row.get("api_usgs_id"),
                        "name": row.get("noaa_name"),
                        "latitude": row.get("latitude"),
                        "longitude": row.get("longitude"),
                    }
                )
                or row.get("threshold_status")
                != threshold_status(row.get("thresholds"))
                or any(
                    document.get("agency_sources", {}).get(key, {}).get("url") != url
                    or document.get("agency_sources", {}).get(key, {}).get("status")
                    != "retrieved"
                    for key, url in agency.SOURCE_URLS.items()
                )
                or document.get("agency_sources", {})
                .get("agency_report", {})
                .get("sha256")
                != agency.REPORT_SHA256
            ):
                raise ValueError("Unsupported NOAA agency-successor match")
        elif lid or row.get("threshold_status") != "unverified":
            raise ValueError("Unresolved NOAA review cannot supply a link")
        rows[sid] = row
    if not rows:
        raise ValueError("Empty NOAA identifier review")
    return rows


def load():
    """Prefer the latest explicit runtime review, including its unresolved outcomes."""
    bundled = json.loads(
        (water_settings.ROOT / REVIEW_FILE).read_text(encoding="utf-8")
    )
    seed = validate(bundled)
    path = water_settings.runtime() / "water_station_review.json"
    document = (
        json.loads(path.read_text(encoding="utf-8")) if path.exists() else bundled
    )
    rows = validate(document)
    if set(rows) != set(seed):
        raise ValueError("NOAA review target set changed; rerun --noaa-identifiers")
    return rows, document["retrieved_at"]


def apply(station, rows):
    """Overlay supported identities; never overwrite a conflicting original source ID."""
    row = rows.get(station["id"])
    station["noaa_identity_status"] = (
        "inventory_identifier" if station.get("lid") else "not_reviewed"
    )
    if not row:
        return
    status = row["identity_status"]
    if (
        status in {"matched", "matched_agency_successor"}
        and station.get("lid")
        and station["lid"].upper() != row["lid"]
    ):
        status = "inventory_identity_conflict"
    station.update(
        lid=row["lid"] if status in {"matched", "matched_agency_successor"} else "",
        noaa_identity_status=status,
    )


def refresh():
    """Replace the small runtime relationship table atomically; preserve original datasets."""
    bundled = json.loads(
        (water_settings.ROOT / REVIEW_FILE).read_text(encoding="utf-8")
    )
    targets = [
        {"station_id": sid, "name": row["name"]}
        for sid, row in validate(bundled).items()
    ]
    document = review(targets)
    from . import water_vertical_review

    water_vertical_review.enrich(document)
    validate(document)
    path = water_settings.runtime() / "water_station_review.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".building")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, allow_nan=False)
        stream.write("\n")
    os.replace(temporary, path)
    return path, document
