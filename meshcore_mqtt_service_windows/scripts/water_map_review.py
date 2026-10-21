"""Non-authorizing map evidence for the sixteen unresolved NOAA identities.

Map proximity and shared waterbody names never create a station link. Refresh
retains static metadata only and flags changed candidate identities for review.
"""

from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
import math
import re
from urllib.parse import urlencode

from .water_agency_review import TARGET_IDS, SUCCESSOR_ID, fetch_bytes
from .water_operator_records import evidence as operator_record_evidence

REVIEW_IDS = tuple(sid for sid in TARGET_IDS if sid != SUCCESSOR_ID)
USGS_SITES = (
    "https://waterservices.usgs.gov/nwis/site/?format=rdb&sites="
    + ",".join(sid[5:] for sid in REVIEW_IDS)
    + "&siteOutput=expanded&siteStatus=all"
)
MAP_LAYER = "https://mapservices.weather.noaa.gov/eventdriven/rest/services/water/riv_gauges/MapServer/0"
MAP_FIELDS = ("gaugelid", "location", "waterbody", "state", "latitude", "longitude")
MAP_QUERY = (
    MAP_LAYER
    + "/query?"
    + urlencode(
        {
            "f": "json",
            "where": "state='CA'",
            "outFields": ",".join(MAP_FIELDS),
            "returnGeometry": "false",
        }
    )
)
GAUGES = "https://api.water.noaa.gov/nwps/v1/gauges/"
RECORDS = {
    "discontinued": "https://pubs.usgs.gov/wdr/wdr-ca-03-2/WDR.CA.03.vol2.pdf",
    "partial_record": "https://pubs.usgs.gov/circ/1971/0661/report.pdf",
}
# Fixed manual-review provenance; ordinary refresh does not redownload these PDFs.
RECORD_REVIEWS = {
    "discontinued": {
        "reviewed_at": "2026-10-21T03:40:21+00:00",
        "access": "full_pdf_retrieved_and_page_visually_reviewed",
        "sha256": "5aa7e0b01a15ddceb644db71729f19915396f7357e387f3fc640278fd6ec24fa",
        "pdf_page": 18,
        "printed_page": "xvi",
        "official_index": "https://pubs.usgs.gov/pubs-services/publication/wdrCA032",
    },
    "partial_record": {
        "reviewed_at": "2026-10-21T03:40:21+00:00",
        "access": "full_pdf_retrieved_and_page_visually_reviewed",
        "sha256": "0881d55be742e909af69cb650d3311dd9e2dd6f3ac78ce6248c7be906be4dcac",
        "pdf_page": 42,
        "printed_page": "38",
        "official_index": "https://pubs.usgs.gov/pubs-services/publication/cir661",
    },
}
ONERAIN_SITES = "https://sonoma.onerain.com/export/map/geojson/?method=sites&view=1476abfc-52ba-4423-8f6b-f2712d9593ed"
# Operator aliases corroborate candidate metadata only, never legacy USGS identity.
ONERAIN_ALIASES = {
    "DCOC1": ("CDEC", "DAC", "Dry Creek at Cooley Ranch RD"),
    "FVSC1": ("ALERT2", "40210", "Franz Creek at Franz Valley School Rd"),
    "WSDC1": ("CDEC", "WRS", "WARM SPRINGS (USACE)"),
}
PARTIAL_IDS = {"11462125", "11462900", "11463700", "11464880", "11465300"}
# Curated candidates are investigative leads, not approved overlay identifiers.
CANDIDATES = {
    "11463940": ("FVSC1",),
    "11464050": ("DCOC1",),
    "11464400": ("DCOC1",),
    "11464500": ("DCOC1", "WSDC1"),
    "11464860": ("WSSC1", "WSDC1"),
    "11464880": ("WSSC1", "WSDC1"),
}
EXPECTED = {
    "DCOC1": ("Dry Creek at Cooley Ranch Road", 38.7892, -123.155803),
    "FVSC1": ("Franz Creek at Franz Valley School Rd", 38.583716, -122.671742),
    "WSSC1": ("Warm Springs Creek below Strawberry Creek", 38.7025, -123.0909),
    "WSDC1": ("Warm Springs Reservoir (Lake Sonoma)", 38.723055555556, -123.01),
}


def position(latitude, longitude):
    """Reject malformed or nonfinite metadata coordinates before persisting them."""
    lat, lon = float(latitude), float(longitude)
    if not (
        math.isfinite(lat)
        and math.isfinite(lon)
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    ):
        raise ValueError("Invalid map position")
    return lat, lon


def parse_sites(raw):
    """Retain exact USGS site identifiers, names and horizontal-position metadata."""
    lines = [
        line
        for line in raw.decode("utf-8-sig").splitlines()
        if line and not line.startswith("#")
    ]
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter="\t")
    fields = {
        "agency_cd",
        "site_no",
        "station_nm",
        "dec_lat_va",
        "dec_long_va",
        "dec_coord_datum_cd",
        "site_tp_cd",
    }
    if not fields.issubset(reader.fieldnames or []):
        raise ValueError("USGS site metadata schema changed")
    sites = {}
    for row in reader:
        if row["agency_cd"] != "USGS":
            continue
        sid = "USGS-" + row["site_no"]
        if sid not in REVIEW_IDS or sid in sites:
            raise ValueError("Unexpected or duplicate USGS site metadata")
        lat, lon = position(row["dec_lat_va"], row["dec_long_va"])
        sites[sid] = {
            "name": row["station_nm"],
            "latitude": lat,
            "longitude": lon,
            "horizontal_datum": row["dec_coord_datum_cd"],
            "site_type": row["site_tp_cd"],
        }
    return sites


def parse_map(raw):
    """Reject truncated/error maps; allowlist static fields, excluding level values."""
    data = json.loads(raw)
    if (
        data.get("error")
        or data.get("exceededTransferLimit")
        or not isinstance(data.get("features"), list)
    ):
        raise ValueError("Incomplete NOAA map response")
    if len(data["features"]) < 100:
        raise ValueError("Unexpectedly short California NOAA map")
    rows = {}
    for feature in data["features"]:
        attr = feature.get("attributes", {})
        if not set(MAP_FIELDS).issubset(attr):
            raise ValueError("NOAA map metadata schema changed")
        lid = attr["gaugelid"]
        if (
            not isinstance(lid, str)
            or not re.fullmatch(r"[A-Z0-9]{3,8}", lid)
            or lid in rows
            or attr["state"] != "CA"
        ):
            raise ValueError("Invalid or duplicate California map identity")
        position(attr["latitude"], attr["longitude"])
        rows[lid] = {key: attr[key] for key in MAP_FIELDS}
    return rows


def candidate_metadata(lid, map_rows, gauge_fetch):
    """Flag changed static identities without promoting even an exact new USGS ID."""
    result = {"lid": lid, "source": GAUGES + lid, "status": "source_unavailable"}
    try:
        if lid not in map_rows:
            raise ValueError("Reviewed candidate missing from NOAA map")
        raw = gauge_fetch(GAUGES + lid)
        if (
            raw.get("lid") != lid
            or not isinstance(raw.get("usgsId"), str)
            or not isinstance(raw.get("name"), str)
        ):
            raise ValueError("NOAA candidate identity schema changed")
        lat, lon = position(raw.get("latitude"), raw.get("longitude"))
        result.update(
            api_usgs_id=raw["usgsId"],
            name=raw["name"].strip(),
            latitude=lat,
            longitude=lon,
            map_metadata=map_rows[lid],
        )
        name, expected_lat, expected_lon = EXPECTED[lid]
        stable = (
            not raw["usgsId"]
            and raw["name"].strip() == name
            and abs(lat - expected_lat) < 0.00001
            and abs(lon - expected_lon) < 0.00001
            and abs(lat - map_rows[lid]["latitude"]) < 0.00001
            and abs(lon - map_rows[lid]["longitude"]) < 0.00001
        )
        result["status"] = "not_linked" if stable else "needs_review"
        result["reason"] = (
            "No explicit legacy-USGS crosswalk; map proximity and names cannot authorize a link."
            if stable
            else "Candidate identity changed; manual review required. No link authorized."
        )
    except Exception as exc:
        result["reason"] = str(exc)
    return result


def parse_onerain(raw):
    """Read the public sites inventory, excluding telemetry, HTML and measurements."""
    data = json.loads(raw)
    features = data.get("features")
    if (
        data.get("error")
        or data.get("exceededTransferLimit")
        or data.get("type") != "FeatureCollection"
        or not isinstance(features, list)
        or len(features) < 50
    ):
        raise ValueError("Incomplete OneRain site inventory")
    sites, ids = [], set()
    for feature in features:
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        if (
            not {"site", "site_id", "site_alias", "system", "name"}.issubset(properties)
            or geometry.get("type") != "Point"
        ):
            raise ValueError("OneRain site metadata schema changed")
        if not isinstance(properties["site"], str) or properties["site"] in ids:
            raise ValueError("Duplicate or invalid OneRain site identity")
        if not properties["site"] or not all(
            isinstance(properties[k], str) and properties[k] for k in ("system", "name")
        ):
            raise ValueError("Missing OneRain system or name")
        if type(properties["site_id"]) is not int or properties["site_id"] < 1:
            raise ValueError("Invalid OneRain numeric site ID")
        ids.add(properties["site"])
        if not isinstance(properties["site_alias"], (str, int)) or isinstance(
            properties["site_alias"], bool
        ):
            raise ValueError("Invalid OneRain site alias")
        coords = geometry.get("coordinates", [])
        if len(coords) != 2:
            raise ValueError("Invalid OneRain site geometry")
        lat, lon = position(coords[1], coords[0])
        sites.append(
            {
                "site": properties["site"],
                "site_id": properties["site_id"],
                "alias": str(properties["site_alias"]),
                "system": properties["system"],
                "name": properties["name"],
                "latitude": lat,
                "longitude": lon,
            }
        )
    return sites


def onerain_evidence(sid, candidate_lids, sites, available):
    """Keep exact alias leads and reviewed operator aliases separate from accepted links."""
    exact = [s for s in sites if s["system"] == "USGS" and s["alias"] == sid[5:]]
    related, changed = [], False
    for lid in candidate_lids:
        if lid not in ONERAIN_ALIASES:
            continue
        system, alias, name = ONERAIN_ALIASES[lid]
        found = [s for s in sites if (s["system"], s["alias"]) == (system, alias)]
        related.extend(found)
        # The published reservoir position is rounded; this is a drift check,
        # not a distance-based link rule. No alias can authorize a link here.
        _, lat, lon = EXPECTED[lid]
        changed |= len(found) != 1 or any(
            s["name"] != name
            or abs(s["latitude"] - lat) > 0.0001
            or abs(s["longitude"] - lon) > 0.0001
            for s in found
        )
    return {
        "status": (
            "source_unavailable"
            if not available
            else "needs_review" if exact or changed else "no_supported_crosswalk"
        ),
        "exact_usgs_alias_candidates": exact,
        "related_operator_sites": related,
        "link_authorized": False,
    }


def enrich(document, gauge_fetch, download=fetch_bytes):
    """Replace auxiliary map evidence while leaving every operational identity untouched.

    Historical publication pages are manual context, not refreshed proof of
    current closure. NOAA map/API and USGS position metadata are checked live.
    """
    selected = [row for row in document["stations"] if row["station_id"] in REVIEW_IDS]
    if not selected:
        return document
    sources, parsed = {}, {}
    for key, url, parser in (
        ("usgs_sites", USGS_SITES, parse_sites),
        ("noaa_map", MAP_QUERY, parse_map),
        ("onerain_sites", ONERAIN_SITES, parse_onerain),
    ):
        try:
            raw = download(url)
            parsed[key] = parser(raw)
            sources[key] = {
                "url": url,
                "status": "retrieved",
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        except Exception as exc:
            parsed[key] = [] if key == "onerain_sites" else {}
            sources[key] = {
                "url": url,
                "status": "source_unavailable",
                "reason": str(exc),
            }
    document["map_sources"] = sources
    lids = sorted(
        {lid for row in selected for lid in CANDIDATES.get(row["station_id"][5:], ())}
    )
    with ThreadPoolExecutor(max_workers=3) as pool:
        candidates = dict(
            zip(
                lids,
                pool.map(
                    lambda lid: candidate_metadata(
                        lid, parsed["noaa_map"], gauge_fetch
                    ),
                    lids,
                ),
            )
        )
    for row in selected:
        sid = row["station_id"]
        kind = "partial_record" if sid[5:] in PARTIAL_IDS else "discontinued"
        related = [candidates[lid] for lid in CANDIDATES.get(sid[5:], ())]
        operator = onerain_evidence(
            sid,
            CANDIDATES.get(sid[5:], ()),
            parsed["onerain_sites"],
            sources["onerain_sites"]["status"] == "retrieved",
        )
        status = "not_linked"
        if (
            any(s["status"] == "source_unavailable" for s in sources.values())
            or sid not in parsed["usgs_sites"]
            or any(c["status"] == "source_unavailable" for c in related)
        ):
            status = "source_unavailable"
        elif operator["status"] == "needs_review" or any(
            c["status"] == "needs_review" for c in related
        ):
            status = "needs_review"
        row["map_record_review"] = {
            "status": status,
            "link_authorized": False,
            "checked_at": document["retrieved_at"],
            "usgs_site": parsed["usgs_sites"].get(sid),
            "candidates": related,
            "onerain_review": operator,
            "operator_record_review": operator_record_evidence(sid),
            "historical_context": {
                "classification": kind,
                "source": RECORDS[kind],
                **RECORD_REVIEWS[kind],
                "interpretation": "Historical publication context only; not proof of current closure or a NOAA successor.",
            },
            "reason": "No additional crosswalk supported by the reviewed maps and records. This auxiliary review never overrides exact catalog/API evidence.",
        }
    return document
