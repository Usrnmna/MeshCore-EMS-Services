"""Additional official metadata review for the 17 unresolved NOAA identities.

Only one explicitly documented agency-successor chain is eligible. Historical
USGS series dates describe coverage; no historical measurement values are read
or retained. Names, coordinates and historical periods cannot create a link.
"""

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date
import hashlib
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import io
import re
from urllib.request import HTTPCookieProcessor, Request, build_opener

TARGET_IDS = tuple(
    "USGS-" + number
    for number in (
        "11460940",
        "11461400",
        "11462000",
        "11462125",
        "11462700",
        "11462900",
        "11463160",
        "11463700",
        "11463940",
        "11464050",
        "11464400",
        "11464500",
        "11464860",
        "11464880",
        "11465050",
        "11465150",
        "11465300",
    )
)
SUCCESSOR_ID = "USGS-11462000"
SUCCESSOR_LID = "YDMC1"
SUCCESSOR_NAME = "East Fork Russian River below Coyote Dam"
SUCCESSOR_POINT = (39.1975, -123.1864)
HADS = "https://hads.ncep.noaa.gov/USGS/CA_USGS-HADS_SITES.txt"
USGS = (
    "https://waterservices.usgs.gov/nwis/site/?format=rdb&sites="
    + ",".join(s.removeprefix("USGS-") for s in TARGET_IDS)
    + "&seriesCatalogOutput=true&siteStatus=all"
)
REPORT = "https://www.rrfc.net/files/32a1f7e23/Telemetered%2BWater%2BMonitoring%2BProject%2BReport%2BPt%2B2%2BApril%2B2025.pdf"
REPORT_SHA256 = "8a55b40b4249a01279bda8311dad92ff53de096f854fb4d994e1862a1e676072"
CDEC = "https://cdec.water.ca.gov/dynamicapp/staMeta?station_id=CDM"
HADS_EKA = "https://hads.ncep.noaa.gov/hsas/EKA_dcps.shtml"
SOURCE_URLS = {
    "usgs_catalog": USGS,
    "hads_crosswalk": HADS,
    "agency_report": REPORT,
    "cdec_metadata": CDEC,
    "hads_metadata": HADS_EKA,
}


def fetch_bytes(url):
    """Bound downloads with in-memory redirect cookies; never persist cookies or payloads."""
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with opener.open(
        Request(url, headers={"User-Agent": "MC-EMS-Services-Water/1.0"}), timeout=20
    ) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Agency metadata exceeds size limit")
    return raw


class MetadataCells(HTMLParser):
    """Extract flat table cells even when legacy agency HTML omits row start tags."""

    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.cells, self.current = [], None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag in {"td", "th"}:
            self.current = []
        elif self.current is not None:
            self.current.append(" ")

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.current is not None:
            self.cells.append(" ".join("".join(self.current).split()))
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)


def parse_usgs(raw):
    """Allowlist series coverage metadata, not daily/instantaneous/peak values."""
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
        "data_type_cd",
        "parm_cd",
        "begin_date",
        "end_date",
    }
    if not fields.issubset(reader.fieldnames or []):
        raise ValueError("USGS series-catalog schema changed")
    result = {}
    for row in reader:
        if row["agency_cd"] != "USGS":
            continue
        sid = "USGS-" + row["site_no"]
        if sid not in TARGET_IDS:
            raise ValueError("Unexpected USGS station in requested metadata")
        record = result.setdefault(sid, {"name": row["station_nm"], "periods": []})
        if row["data_type_cd"] == "pk" or (
            row["data_type_cd"] in {"dv", "uv", "iv"}
            and row["parm_cd"] in {"00060", "00065"}
        ):
            period = {
                k: row[k] for k in ("data_type_cd", "parm_cd", "begin_date", "end_date")
            }
            if any(
                not re.fullmatch(r"\d{4}(?:-\d{2})?(?:-\d{2})?", period[k] or "")
                for k in ("begin_date", "end_date")
            ):
                raise ValueError("Unverified USGS series period")
            if period not in record["periods"]:
                record["periods"].append(period)
    return result


def parse_hads(raw):
    """Read the published USGS/NWSLI crosswalk, preserving non-unique candidates."""
    text = raw.decode("utf-8-sig")
    if "STATION" not in text[:300] or "IDENTIFR" not in text[:300]:
        raise ValueError("HADS crosswalk schema changed")
    result, count = {}, 0
    for line in text.splitlines()[4:]:
        cells = [c.strip() for c in line.split("|")]
        if not line.strip():
            continue
        if (
            len(cells) != 7
            or not re.fullmatch(r"\d{8,15}", cells[1])
            or not re.fullmatch(r"[A-Z0-9]{5}", cells[0])
        ):
            raise ValueError("Invalid HADS crosswalk row")
        count += 1
        result.setdefault("USGS-" + cells[1], []).append(cells[0])
    if count < 100:
        raise ValueError("Incomplete California HADS crosswalk")
    return result


def verify_successor_metadata(report, cdec, hads):
    """Verify the reviewed explicit crosswalk plus current CDM/HADS station metadata.

    The reviewed PDF table 2-2 (PDF page 26, printed page 13) explicitly pairs
    11462000 and CDM. Its exact byte hash guards that manual interpretation.
    Coordinates corroborate this documented chain; they never discover a link.
    """
    if hashlib.sha256(report).hexdigest() != REPORT_SHA256:
        raise ValueError("Agency report changed; manual crosswalk review required")
    cells = MetadataCells(cdec).cells

    def field(label):
        found = [cells[i + 1] for i, value in enumerate(cells[:-1]) if value == label]
        if len(found) != 1:
            raise ValueError("Ambiguous CDEC metadata field: " + label)
        return found[0]

    if (
        field("Station ID") != "CDM"
        or field("Operator") != "US Army Corps of Engineers"
    ):
        raise ValueError("CDEC successor identity changed")
    for label, expected in zip(("Latitude", "Longitude"), SUCCESSOR_POINT):
        # Degree symbols vary in the source encoding; the full numeric token must match.
        number = re.fullmatch(r"(-?\d+\.\d+)[^\d\s]*", field(label))
        if not number or abs(float(number[1]) - expected) > 0.000001:
            raise ValueError("CDEC successor position changed")
    cells = MetadataCells(hads).cells
    found = [i for i, value in enumerate(cells) if value == SUCCESSOR_LID]
    if len(found) != 1:
        raise ValueError("HADS successor missing or ambiguous")
    i = found[0]
    if (
        i < 1
        or len(cells) <= i + 5
        or cells[i - 1]
        != "EAST FORK RUSSIAN RIVER BELOW COYOTE DAM NEAR UKIAH 3NNE (CDM)"
        or cells[i + 1] != "CE902418"
        or cells[i + 5] != "CESPD1"
    ):
        raise ValueError("HADS CDM/GOES/operator identity changed")


def api_matches(raw):
    """Permit only the reviewed successor with a blank legacy USGS field, never a conflicting ID."""
    return (
        raw.get("lid") == SUCCESSOR_LID
        and raw.get("usgsId") == ""
        and raw.get("name") == SUCCESSOR_NAME
        and all(
            type(raw.get(key)) in (int, float) and abs(raw[key] - expected) < 0.000001
            for key, expected in zip(("latitude", "longitude"), SUCCESSOR_POINT)
        )
    )


def enrich(document, gauge_fetch, download=fetch_bytes):
    """Attach review evidence and the sole supported successor; failures withhold that link."""
    from .water_identifiers import GAUGES, thresholds, threshold_status

    selected = [r for r in document["stations"] if r["station_id"] in TARGET_IDS]
    if not selected:
        return document
    raw_sources, sources = {}, {}

    def acquire(item):
        key, url = item
        try:
            raw = download(url)
            return (
                key,
                raw,
                {
                    "url": url,
                    "status": "retrieved",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                },
            )
        except Exception as exc:
            return (
                key,
                None,
                {"url": url, "status": "source_unavailable", "reason": str(exc)},
            )

    with ThreadPoolExecutor(max_workers=3) as pool:
        for key, raw, evidence in pool.map(acquire, SOURCE_URLS.items()):
            raw_sources[key], sources[key] = raw, evidence
    parsed = {}
    for key, parser in (("usgs_catalog", parse_usgs), ("hads_crosswalk", parse_hads)):
        try:
            parsed[key] = (
                parser(raw_sources[key]) if raw_sources[key] is not None else {}
            )
        except Exception as exc:
            sources[key].update(status="source_unavailable", reason=str(exc))
            parsed[key] = {}
    document["agency_sources"] = sources
    for row in selected:
        sid = row["station_id"]
        record = parsed["usgs_catalog"].get(sid, {})
        periods = record.get("periods", [])
        metadata_ok = all(
            sources[k]["status"] == "retrieved"
            for k in ("usgs_catalog", "hads_crosswalk")
        ) and bool(record)
        evidence = {
            "status": (
                "no_supported_agency_link" if metadata_ok else "source_unavailable"
            ),
            "hads_candidates": parsed["hads_crosswalk"].get(sid, []),
            "usgs_periods": periods,
            "usgs_record_status": (
                "historical_periods_only"
                if periods
                and all(p["end_date"][:4] < str(date.today().year - 1) for p in periods)
                else "unverified_or_recent_periods"
            ),
        }
        row["agency_review"] = evidence
        if sid != SUCCESSOR_ID or row["identity_status"] != "no_exact_catalog_match":
            continue
        try:
            if not metadata_ok or evidence["hads_candidates"]:
                raise ValueError(
                    "USGS/HADS metadata unavailable or changed; successor review required"
                )
            if any(
                raw_sources[k] is None
                for k in ("agency_report", "cdec_metadata", "hads_metadata")
            ):
                raise ValueError("Successor evidence source unavailable")
            verify_successor_metadata(
                *(
                    raw_sources[k]
                    for k in ("agency_report", "cdec_metadata", "hads_metadata")
                )
            )
            raw = gauge_fetch(GAUGES + SUCCESSOR_LID)
            if not api_matches(raw):
                raise ValueError("NOAA successor API identity conflict")
            flood = raw.get("flood", {})
            if not isinstance(flood.get("categories"), dict) or any(
                not isinstance(flood["categories"].get(name), dict)
                for name in ("action", "minor", "moderate", "major")
            ):
                raise ValueError("NOAA successor threshold schema changed")
            values = thresholds(flood.get("categories"))
            evidence["status"] = "supported_agency_successor"
            row.update(
                lid=SUCCESSOR_LID,
                identity_status="matched_agency_successor",
                threshold_status=threshold_status(values),
                thresholds=values,
                stage_units=flood.get("stageUnits"),
                flow_units=flood.get("flowUnits"),
                gauge_source=GAUGES + SUCCESSOR_LID,
                api_usgs_id="",
                api_lid=SUCCESSOR_LID,
                noaa_name=raw["name"],
                latitude=raw["latitude"],
                longitude=raw["longitude"],
                reason="Published agency crosswalk: legacy USGS-11462000 to CDEC CDM to NOAA YDMC1. Agency successor, not a current USGS observation or datum-equivalence claim.",
            )
        except Exception as exc:
            evidence.update(status="source_unavailable", reason=str(exc))
    return document
