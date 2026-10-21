"""Check WAC/WAS interpretation metadata without correcting or storing readings.

The fixed manual baseline remains unresolved. Live checks detect source drift;
they cannot authorize a datum conversion, logger correction or NOAA identity.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import hashlib
from html.parser import HTMLParser
import re

from .water_agency_review import MetadataCells, fetch_bytes
from .water_operator_records import SOURCES, WAC_REVIEWED_AT, WAC_STATIONS

SOURCE_URLS = {
    key: SOURCES[key]["url"]
    for key in ("cw3e_wac", "cw3e_wac_logger", "cw3e_wac_sensor", "cdec_was")
}
SOURCE_URLS["cdec_datums"] = (
    "https://cdec.water.ca.gov/reportapp/javareports?name=RivStagesInfo"
)
BASELINE = {
    "cw3e_wac": {
        "cw3e_id": "WAC",
        "cdec_id": "WAS",
        "nws_id": "--",
        "elevation_m": "190",
        "latitude": "38.7025",
        "longitude": "-123.0909",
        "logger_link_present": True,
        "sensor_link_present": True,
    },
    "cw3e_wac_logger": {
        "type": "Data Logger",
        "model": "Sutron SatLink3 Lite",
        "installed_on": "July 15, 2026",
        "offset": "1.42",
        "offset_applied_on": "2026-07-15",
        "offset_note_recognized": True,
    },
    "cw3e_wac_sensor": {
        "type": "Pressure transducer",
        "model": "Ott Hydro PLS500",
        "installed_on": "July 15, 2026",
        "deactivated_on": "--",
        "height_cm": "--",
        "distance_cm": "--",
        "notes_present": False,
        "calibration_entries_present": False,
    },
    "cdec_was": {
        "station_id": "WAS",
        "elevation_ft": "470",
        "stage_sensor_number": "1",
        "stage_description": "RIVER STAGE, FEET",
    },
    "cdec_datums": {"was_entry_present": False},
}
FAILURE_STATUSES = {"source_changed", "source_unavailable", "invalid_metadata"}


class PlainText(HTMLParser):
    """Normalize entity-encoded text without retaining HTML or hidden form values."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(text)

    def handle_data(self, text):
        self.parts.append(text)


def normalized(text):
    return " ".join("".join(PlainText(text).parts).split())


def one_after(cells, label):
    """Require exactly one labeled field, including an explicitly empty value."""
    positions = [
        i for i, value in enumerate(cells) if value.casefold() == label.casefold()
    ]
    if len(positions) != 1 or positions[0] + 1 >= len(cells):
        raise ValueError("Missing or duplicate metadata field: " + label)
    return cells[positions[0] + 1]


def numeric_units(value, units):
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*" + units, value, re.I)
    if not match:
        raise ValueError("Unrecognized elevation units or value")
    return format(Decimal(match[1]).normalize(), "f")


def parse_metadata(key, raw):
    """Allowlist interpretation fields; discard telemetry, raw notes and peak records.

    A newly published datum row or changed offset wording requires review rather
    than automatic interpretation. HTML checksums are provenance, not drift tests.
    """
    try:
        html = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        html = raw.decode("cp1252")
    if not re.search(r"</html\s*>\s*$", html, re.I):
        raise ValueError("Metadata page is incomplete")
    cells = MetadataCells(raw).cells
    if key == "cw3e_wac":

        def field(label):
            matches = re.findall(
                re.escape(label) + r":\s*<b\b[^>]*>(.*?)</b\s*>", html, re.I | re.S
            )
            if len(matches) != 1:
                raise ValueError("Missing or duplicate WAC field: " + label)
            return normalized(matches[0])

        coordinates = re.fullmatch(
            r"([+-]?\d+\.\d+)\s*/\s*([+-]?\d+\.\d+)", field("Lat/Long")
        )
        if not coordinates:
            raise ValueError("WAC coordinates missing or unrecognized")
        return {
            "cw3e_id": field("CW3E id"),
            "cdec_id": field("CDEC id"),
            "nws_id": field("NWS id"),
            "elevation_m": numeric_units(field("Elevation"), "m"),
            "latitude": format(Decimal(coordinates[1]).normalize(), "f"),
            "longitude": format(Decimal(coordinates[2]).normalize(), "f"),
            "logger_link_present": bool(
                re.search(
                    r"href=[\"\']/metadata/sites/WAC/otherequipment/568[\"\']", html
                )
            ),
            "sensor_link_present": bool(
                re.search(r"href=[\"\']/metadata/sites/WAC/sensors/899[\"\']", html)
            ),
        }
    if key in {"cw3e_wac_logger", "cw3e_wac_sensor"}:
        if not re.search(r"href=[\"\']/metadata/sites/WAC/?[\"\']", html):
            raise ValueError("Equipment page lacks WAC station reference")
        # The first Notes cell terminates the equipment table; the second is a
        # calibration column header and must not be mistaken for equipment notes.
        notes_index = cells.index("Notes")
        equipment, calibration = cells[: notes_index + 2], cells[notes_index + 2 :]
        note = one_after(equipment, "Notes")
        result = {
            "type": one_after(equipment, "Type"),
            "model": one_after(equipment, "Model"),
            "installed_on": one_after(equipment, "Installed on"),
        }
        if key == "cw3e_wac_logger":
            if calibration:
                raise ValueError("Unexpected or duplicate logger fields after Notes")
            match = re.fullmatch(
                r"Offset\s+([+-]?\d+(?:\.\d+)?)\s+applied\s+15\s+July\s+2026\.?",
                note,
                re.I,
            )
            result.update(
                offset=format(Decimal(match[1]).normalize(), "f") if match else None,
                offset_applied_on="2026-07-15" if match else None,
                offset_note_recognized=bool(match),
            )
            # Unknown wording is fingerprinted, never stored as unbounded text or
            # treated as a supported correction instruction.
            if not match:
                result["unrecognized_note_sha256"] = hashlib.sha256(
                    note.encode()
                ).hexdigest()
        else:
            if calibration[:2] != ["On", "Notes"]:
                raise ValueError("Pressure-transducer calibration table missing")
            result.update(
                deactivated_on=one_after(equipment, "Deactivated on"),
                height_cm=one_after(equipment, "Height (cm)"),
                distance_cm=one_after(equipment, "Distance (cm)"),
                notes_present=bool(note),
                calibration_entries_present=bool(calibration[2:]),
            )
        return result
    if key == "cdec_was":
        stage = [i for i, value in enumerate(cells) if value.startswith("RIVER STAGE")]
        if len(stage) != 1 or stage[0] + 1 >= len(cells):
            raise ValueError("Missing or ambiguous CDEC stage sensor")
        return {
            "station_id": one_after(cells, "Station ID"),
            "elevation_ft": numeric_units(one_after(cells, "Elevation"), "ft"),
            "stage_sensor_number": cells[stage[0] + 1],
            "stage_description": cells[stage[0]],
        }
    if key == "cdec_datums":
        expected = [
            "STATION",
            "ID",
            "MONITOR STAGE (FEET)",
            "FLOOD STAGE (FEET)",
            "DATUM 0",
            "DATUM",
            "PEAK DATE",
            "PEAK OF RECORD",
            "OPERATING AGENCY",
        ]
        start = cells.index("STATION")
        if cells[start : start + len(expected)] != expected:
            raise ValueError("CDEC datum report schema changed")
        # A header-only/error page must never verify absence. Legacy report HTML
        # omits some row tags, so inspect flat cells with ID and numeric-stage shape.
        ids = [
            value
            for i, value in enumerate(cells[:-1])
            if re.fullmatch(r"[A-Z0-9]{3}", value)
            and re.fullmatch(r"[\d,. +-]+", cells[i + 1])
        ]
        if len(set(ids)) < 50:
            raise ValueError("CDEC datum report incomplete")
        return {"was_entry_present": "WAS" in cells}
    raise ValueError("Unknown vertical-reference source")


def enrich(document, download=fetch_bytes):
    """Replace live checks for both legacy candidates, even on NOAA catalog failure.

    Source failures never fall back to a previous successful check. The manual
    baseline and its date remain fixed; only the separate live timestamp advances.
    """
    targets = [
        row
        for row in document["stations"]
        if row["station_id"].removeprefix("USGS-") in WAC_STATIONS
    ]
    if not targets:
        return document

    def check(item):
        key, url = item
        result = {"url": url, "status": "source_unavailable", "sha256": None}
        try:
            raw = download(url)
        except Exception as exc:
            result["reason"] = "Metadata download failed: " + type(exc).__name__
            return key, result
        result["sha256"] = hashlib.sha256(raw).hexdigest()
        try:
            metadata = parse_metadata(key, raw)
            changes = sorted(
                field
                for field in set(BASELINE[key]) | set(metadata)
                if BASELINE[key].get(field) != metadata.get(field)
            )
            result.update(
                status="source_changed" if changes else "unchanged",
                metadata=metadata,
                changed_fields=changes,
            )
        except (ValueError, IndexError, UnicodeError) as exc:
            result.update(status="invalid_metadata", reason=str(exc))
        return key, result

    with ThreadPoolExecutor(max_workers=3) as pool:
        sources = dict(pool.map(check, SOURCE_URLS.items()))
    # Source preference selects reported station metadata, never a datum or
    # measurement transform. Failure leaves the preferred value unavailable.
    cdec = sources["cdec_was"]
    cdec_metadata = cdec.get("metadata", {})
    cdec_available = cdec_metadata.get("station_id") == "WAS"
    result = {
        "status": (
            "needs_review"
            if any(s["status"] in FAILURE_STATUSES for s in sources.values())
            else "unchanged_uncertainty"
        ),
        "checked_at": document["retrieved_at"],
        "baseline_reviewed_at": WAC_REVIEWED_AT,
        "link_authorized": False,
        "correction_authorized": False,
        "applied_correction": None,
        "preferred_station_elevation": {
            "source": "cdec_was",
            "url": SOURCE_URLS["cdec_was"],
            "value": cdec_metadata.get("elevation_ft") if cdec_available else None,
            "units": "ft",
            "vertical_datum": None,
            "status": cdec["status"] if cdec_available else "unavailable",
            "scope": "Reported station metadata only; changed values still require review. No CW3E fallback or reading correction.",
        },
        "unverified_configuration": {
            key: None
            for key in (
                "vertical_datum",
                "gauge_zero",
                "offset_units",
                "offset_sign",
                "offset_target_quantity",
                "offset_already_in_published_readings",
            )
        },
        "sources": sources,
        "reason": "The manual baseline has conflicting station elevations; gauge-zero datum and logger offset units, sign, target quantity and prior application remain unverified. Changed evidence requires manual review. Source checks do not authorize links or reading corrections.",
    }
    document["wac_was_refresh_check"] = result
    for row in targets:
        row["vertical_reference_check"] = deepcopy(result)
    return document
