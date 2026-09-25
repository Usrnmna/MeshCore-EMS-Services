"""Build, inspect and export a sourced satellite radio reference database.

Python 3.11+ standard library. Optional Skyfield is only used by 'position'.
See settings.json for sources/tuning and operator_overrides.json for corrections.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from catalog import classify, frequency_band, normalize_operation, tle_epoch
from reports import match_operation, parse_amsat_reports
from sources import SourceReader, parse_time, utc_now

HERE = Path(__file__).resolve().parent
STATUS_URL = "https://www.amsat.org/status/"
STATUSES = ("active", "inactive", "scheduled_off", "unknown")


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def settings_from(path):
    path = Path(path).resolve()
    settings = read_json(path)
    for key in ("database", "cache_directory", "export_directory"):
        settings[key] = (path.parent / settings[key]).resolve()
    for key in ("status_max_age_days", "orbit_max_age_days", "cache_hours", "timeout_seconds", "max_response_bytes", "max_pages"):
        value = settings[key]
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(key + " must be positive")
    return settings


def connect(settings, create=False):
    path = settings["database"]
    if not create and not path.exists():
        raise ValueError("Database not found. Run the refresh command first.")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    if create:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            db.close()
            raise ValueError("Unsupported database schema version")
        db.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
        db.execute("PRAGMA user_version=1")
    return db


def receipt_time(reader, url):
    return next(r["fetched_at"] for r in reversed(reader.receipts) if r["url"] == url)


def as_norad(value):
    try:
        result = int(value)
        return result if result > 0 else None
    except (ValueError, TypeError):
        return None


def build_catalog(satellite_rows, transmitters, amsat_rows, settings, fetched_at):
    """Join by stable SatNOGS ID, then NORAD ID. Never join different craft by name."""
    amsat_by_id, amsat_by_norad = {}, {}
    for row in amsat_rows:
        if row.get("satnogs_id"):
            amsat_by_id.setdefault(row["satnogs_id"], []).append(row)
        if as_norad(row.get("norad_id")):
            amsat_by_norad.setdefault(as_norad(row["norad_id"]), []).append(row)
    satellites = {}
    for row in satellite_rows:
        norad = as_norad(row.get("norad_cat_id"))
        amsat = amsat_by_id.get(row["sat_id"], amsat_by_norad.get(norad, []))
        aliases = [s.strip() for s in (row.get("names") or "").split(",") if s.strip()]
        aliases.extend(r["name"] for r in amsat)
        satellites[row["sat_id"]] = {
            "satellite_id": row["sat_id"], "norad_id": norad, "name": row["name"],
            "aliases": sorted(set(aliases)), "lifecycle": row.get("status"),
            "operator": row.get("operator"), "website": row.get("website"),
            "launched": row.get("launched"), "decayed": row.get("decayed"),
            "source_url": "https://db.satnogs.org/satellite/" + row["sat_id"] + "/",
            "amsat_records": amsat, "raw": row,
        }
    operations, excluded = {}, Counter()
    for tx in transmitters:
        satellite = satellites.get(tx.get("sat_id"))
        if not satellite:
            excluded["missing satellite identity"] += 1
            continue
        scopes, reason = classify(tx, bool(satellite["amsat_records"]), settings)
        if not scopes:
            excluded[reason] += 1
            continue
        op = normalize_operation(tx, satellite["satellite_id"], scopes, reason,
                                 settings["sources"]["transmitters"], fetched_at)
        if op["operation_id"] in operations:
            raise ValueError("Duplicate transmitter identity: " + op["operation_id"])
        operations[op["operation_id"]] = op
    selected_ids = {op["satellite_id"] for op in operations.values()}
    satellites = {key: row for key, row in satellites.items() if key in selected_ids}
    return satellites, operations, dict(excluded)


def apply_overrides(satellites, operations, overrides, settings):
    """Explicit additions require identity, capabilities and sources; no fake modes."""
    for sat in overrides.get("additional_satellites", []):
        for field in ("satellite_id", "name", "source_url", "lifecycle"):
            if not sat.get(field):
                raise ValueError("Additional satellite missing " + field)
        satellites[sat["satellite_id"]] = sat
    for op in overrides.get("additional_operations", []):
        for field in ("operation_id", "satellite_id", "name", "source_url", "capability_evidence", "scopes"):
            if not op.get(field):
                raise ValueError("Additional operation missing " + field)
        if op["satellite_id"] not in satellites:
            raise ValueError("Additional operation has no documented satellite")
        if op["operation_id"] in operations:
            raise ValueError("Use corrections to amend an existing operation")
        defaults = {"source_reported_status": None, "source_mode": None, "protocols": [],
                    "present_in_latest_source": True, "uplink_availability": "unknown", "raw": {}}
        operations[op["operation_id"]] = dict(defaults, **op)
    for correction in overrides.get("corrections", []):
        if not correction.get("source_url") or not parse_time(correction.get("reviewed_at")):
            raise ValueError("Corrections require a source and review date")
        for op_id in correction["operation_ids"]:
            if op_id not in operations:
                continue
            fields = correction["fields"]
            if any(k in fields for k in ("operation_id", "satellite_id", "raw", "current_status")):
                raise ValueError("Corrections cannot replace identity, raw evidence, or current status")
            operations[op_id].update(fields)
            operations[op_id]["operator_correction"] = correction
            operations[op_id]["downlink_band"] = frequency_band(operations[op_id].get("downlink_low_hz"))
    for op_id, details in overrides.get("superseded_operations", {}).items():
        if op_id in operations and details["superseded_by"] in operations:
            operations[op_id].update(details)
    for op in operations.values():
        if not set(op["scopes"]).issubset(settings["scopes"]):
            raise ValueError("Unknown scope in " + op["operation_id"])
    return overrides.get("observations", [])


def retirement_reason(satellite, settings, overrides):
    """Retirement is a spacecraft fact, never inferred from one failed radio."""
    lifecycle = str(satellite.get("lifecycle") or satellite.get("status") or "").casefold()
    if lifecycle in settings["excluded_lifecycle_states"]:
        return lifecycle
    # Normalize punctuation to match NOAA 15, NOAA-15 and NOAA_15 consistently.
    import re
    canonical = lambda name: re.sub(r"[^a-z0-9]", "", str(name).casefold())
    names = {canonical(satellite["name"])}
    names.update(canonical(name) for name in satellite.get("aliases", []))
    names.update(canonical(name.strip()) for name in (satellite.get("names") or "").split(","))
    for rule in overrides.get("retired_satellites", []):
        if not rule.get("source_url") or not rule.get("reason"):
            raise ValueError("Retirement rules require an evidence source and reason")
        if names.intersection(canonical(name) for name in rule["names"]):
            return "operator-documented retirement"
    return None


def prune_satellite(db, sat_id):
    """Remove retired spacecraft and dependent reference entries in one transaction."""
    operation_query = "SELECT operation_id FROM operations WHERE satellite_id=?"
    for table in ("observations", "operation_versions", "operation_scopes", "reception_reports"):
        db.execute("DELETE FROM " + table + " WHERE operation_id IN (" + operation_query + ")", (sat_id,))
    db.execute("DELETE FROM operations WHERE satellite_id=?", (sat_id,))
    db.execute("DELETE FROM orbits WHERE satellite_id=?", (sat_id,))
    db.execute("DELETE FROM satellites WHERE satellite_id=?", (sat_id,))


def validate_observation(observation, operation_ids):
    """A failure label requires a real capability, a date, source and explanation."""
    for field in ("operation_id", "status", "observed_at", "source_url", "note", "evidence_kind"):
        if not observation.get(field):
            raise ValueError("Observation missing " + field)
    if observation["operation_id"] not in operation_ids:
        raise ValueError("Observation targets a capability that does not exist: " + observation["operation_id"])
    if observation["status"] not in STATUSES:
        raise ValueError("Invalid observation status")
    timestamp = parse_time(observation["observed_at"])
    if timestamp is None or timestamp > datetime.now(timezone.utc):
        raise ValueError("Observation needs a valid, nonfuture time")
    if observation["status"] == "inactive" and observation["evidence_kind"] != "confirmed_failure":
        raise ValueError("Inactive requires evidence_kind=confirmed_failure; not-heard is insufficient")
    if observation["status"] == "scheduled_off" and observation["evidence_kind"] != "operator_schedule":
        raise ValueError("Scheduled-off requires evidence_kind=operator_schedule")


def save_observation(db, observation):
    observation = dict(observation)
    observation["observed_at"] = parse_time(observation["observed_at"]).astimezone(timezone.utc).isoformat()
    key = hashlib.sha256(dumps(observation).encode()).hexdigest()
    db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?)",
               (key, observation["operation_id"], observation["status"], observation["observed_at"],
                observation["source_url"], observation["note"], observation["evidence_kind"], utc_now()))


def fetch_orbits(reader, satellites, settings, warnings, use_celestrak):
    """Store elements, not a misleading permanently saved 'current position'."""
    orbits = []
    try:
        url = settings["sources"]["tle"]
        for row in reader.records(url, "tle1"):
            if row.get("sat_id") in satellites and row.get("tle2"):
                orbits.append((row["sat_id"], url, "TLE", tle_epoch(row["tle1"]), receipt_time(reader, url), dumps(row)))
    except Exception as exc:
        warnings.append("SatNOGS orbital data unavailable: " + str(exc))
    if use_celestrak:
        by_norad = {s["norad_id"]: s["satellite_id"] for s in satellites.values() if s.get("norad_id")}
        for group in settings["orbit_groups"]:
            url = settings["celestrak_url"].format(group=group)
            try:
                # CelesTrak: cache at least two hours, no retry/redirect after errors.
                body, meta = reader.read(url, max(2, settings["cache_hours"]))
                rows = json.loads(body)
                if not isinstance(rows, list) or not rows:
                    raise ValueError("Expected nonempty GP JSON list")
                for row in rows:
                    sat_id = by_norad.get(as_norad(row.get("NORAD_CAT_ID")))
                    if sat_id and parse_time(row.get("EPOCH")):
                        orbits.append((sat_id, url, "OMM_JSON", parse_time(row["EPOCH"]).isoformat(), meta["fetched_at"], dumps(row)))
            except Exception as exc:
                warnings.append("CelesTrak stopped after error; retained existing elements: " + str(exc))
                break
    return orbits


def refresh(settings, args):
    reader = SourceReader(settings["cache_directory"], settings, args.offline)
    feeds = settings["sources"]
    print("Reading satellite identities, radio capabilities and AMSAT references...", file=sys.stderr)
    satellite_rows = reader.records(feeds["satellites"], "sat_id")
    transmitters = reader.records(feeds["transmitters"], "uuid")
    amsat_rows = reader.records(feeds["amsat"], "name")
    satellites, operations, excluded = build_catalog(satellite_rows, transmitters, amsat_rows, settings, receipt_time(reader, feeds["transmitters"]))
    overrides = read_json(args.overrides)
    manual_observations = apply_overrides(satellites, operations, overrides, settings)
    excluded_satellites = {key: retirement_reason(sat, settings, overrides) for key, sat in satellites.items()}
    excluded_satellites = {key: reason for key, reason in excluded_satellites.items() if reason}
    excluded_labels = {alias.casefold() for key in excluded_satellites for alias in [satellites[key]["name"]] + satellites[key].get("aliases", [])}
    satellites = {key: sat for key, sat in satellites.items() if key not in excluded_satellites}
    operations = {key: op for key, op in operations.items() if op["satellite_id"] in satellites and not op.get("superseded_by")}
    selected_ids = {op["satellite_id"] for op in operations.values()}
    satellites = {key: sat for key, sat in satellites.items() if key in selected_ids}
    for observation in manual_observations:
        validate_observation(observation, operations)
    warnings, reports, mapped = [], [], []
    try:
        body, _ = reader.read(STATUS_URL)
        reports = parse_amsat_reports(body.decode("utf-8", errors="replace"))
        reports = [r for r in reports if r["satellite_label"].casefold() not in excluded_labels]
        for report in reports:
            op_id = match_operation(report, satellites, operations, overrides.get("status_label_mappings", {}))
            report["operation_id"] = op_id
            if op_id:
                status = "active" if report["reported_status"] == "Heard" else "unknown"
                observation = {"operation_id": op_id, "status": status, "observed_at": report["observed_at"],
                               "source_url": STATUS_URL, "evidence_kind": "reception_report",
                               "note": report["reported_status"] + "; " + report["satellite_label"] + " [" + report["mode_label"] + "]; " + report["callsign"] + "; 15-minute interval"}
                # Ambiguous beacon-only reports do not identify which beacon was heard.
                validate_observation(observation, operations)
                mapped.append(observation)
    except Exception as exc:
        warnings.append("AMSAT reception reports unavailable/unusable: " + str(exc))
        reports, mapped = [], []
    print("Reading orbital elements and preserving source evidence...", file=sys.stderr)
    orbits = fetch_orbits(reader, satellites, settings, warnings, not args.no_celestrak)
    report = {"completed_at": utc_now(), "offline": args.offline,
              "source_satellites": len(satellite_rows), "source_transmitters": len(transmitters),
              "selected_satellites": len(satellites), "selected_operations": len(operations),
              "excluded_satellites_by_reason": dict(Counter(excluded_satellites.values())),
              "excluded_transmitters": excluded, "reception_reports": len(reports),
              "matched_reports": len(mapped), "unmatched_reports": sum(r["operation_id"] is None for r in reports),
              "orbital_records_loaded": len(orbits), "warnings": warnings,
              "coverage": "All records returned by configured feeds were processed. Public catalogs do not guarantee worldwide completeness or current RF activity.",
              "source_receipts": reader.receipts}
    # Required feeds and manual evidence have all passed validation before any catalog mutation.
    db = connect(settings, create=True)
    try:
        with db:
            # Apply the user's exclusion policy to databases created by earlier runs too.
            latest_source = {row["sat_id"]: row for row in satellite_rows}
            for row in db.execute("SELECT satellite_id,data_json FROM satellites").fetchall():
                old = json.loads(row["data_json"])
                current = latest_source.get(row["satellite_id"], old)
                if retirement_reason(current, settings, overrides) or retirement_reason(old, settings, overrides):
                    prune_satellite(db, row["satellite_id"])
            for op_id in overrides.get("superseded_operations", {}):
                for table in ("observations", "operation_versions", "operation_scopes", "reception_reports"):
                    db.execute("DELETE FROM " + table + " WHERE operation_id=?", (op_id,))
                db.execute("DELETE FROM operations WHERE operation_id=?", (op_id,))
            for label in excluded_labels:
                db.execute("DELETE FROM reception_reports WHERE lower(satellite_label)=?", (label,))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('status_max_age_days',?)", (str(settings["status_max_age_days"]),))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('scopes',?)", (dumps(settings["scopes"]),))
            # Disappearing records are retained. Disappearance is NOT a failure observation.
            for row in db.execute("SELECT operation_id,data_json FROM operations").fetchall():
                if row["operation_id"] not in operations:
                    old = json.loads(row["data_json"])
                    old["present_in_latest_source"] = False
                    db.execute("UPDATE operations SET data_json=? WHERE operation_id=?", (dumps(old), row["operation_id"]))
            for sat in satellites.values():
                db.execute("INSERT INTO satellites VALUES (?,?,?,?,?) ON CONFLICT(satellite_id) DO UPDATE SET norad_id=excluded.norad_id,name=excluded.name,lifecycle=excluded.lifecycle,data_json=excluded.data_json",
                           (sat["satellite_id"], sat.get("norad_id"), sat["name"], sat.get("lifecycle"), dumps(sat)))
            for op in operations.values():
                data = dumps(op)
                db.execute("INSERT INTO operations VALUES (?,?,?,?) ON CONFLICT(operation_id) DO UPDATE SET name=excluded.name,data_json=excluded.data_json",
                           (op["operation_id"], op["satellite_id"], op["name"], data))
                # A changed source/correction creates a version, while repeated refreshes do not.
                version = dict(op)
                version.pop("fetched_at", None)
                version_id = hashlib.sha256(dumps(version).encode()).hexdigest()
                db.execute("INSERT OR IGNORE INTO operation_versions VALUES (?,?,?,?)", (version_id, op["operation_id"], utc_now(), data))
                db.execute("DELETE FROM operation_scopes WHERE operation_id=?", (op["operation_id"],))
                db.executemany("INSERT INTO operation_scopes VALUES (?,?)", [(op["operation_id"], scope) for scope in op["scopes"]])
            for observation in mapped + manual_observations:
                save_observation(db, observation)
            for item in reports:
                db.execute("INSERT INTO reception_reports VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(report_id) DO UPDATE SET operation_id=excluded.operation_id",
                           (item["report_id"], item["operation_id"], item["satellite_label"], item["mode_label"], item["reported_status"], item["observed_at"], STATUS_URL, dumps(item)))
            db.executemany("INSERT OR REPLACE INTO orbits VALUES (?,?,?,?,?,?)", orbits)
            db.executemany("INSERT OR IGNORE INTO source_fetches VALUES (?,?,?)", [(r["url"], r["fetched_at"], r["sha256"]) for r in reader.receipts])
            db.execute("INSERT INTO refresh_runs(completed_at,report_json) VALUES (?,?)", (report["completed_at"], dumps(report)))
        export_database(db, settings)
        print(json.dumps(dict(report, database=str(settings["database"])), indent=2))
    finally:
        db.close()
    return 2 if warnings else 0


def operation_rows(db, settings, satellite=None, scope=None, status=None):
    """Freshness is calculated in SQL each time; JSON/CSV exports are snapshots."""
    where, values = [], []
    if satellite:
        ids = find_satellites(db, satellite)
        where.append("satellite_id IN (%s)" % ",".join("?" for _ in ids))
        values.extend(ids)
    if scope:
        where.append("operation_id IN (SELECT operation_id FROM operation_scopes WHERE scope=?)")
        values.append(scope)
    if status:
        where.append("current_status=?")
        values.append(status)
    where.append("json_extract(data_json,'$.superseded_by') IS NULL")
    query = "SELECT * FROM operation_reference" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY satellite_name,operation_name,operation_id"
    result = []
    for row in db.execute(query, values):
        item = json.loads(row["data_json"])
        item.update({k: row[k] for k in row.keys() if k != "data_json"})
        updated = parse_time(item.get("source_updated_at"))
        item["catalog_age_days"] = round((datetime.now(timezone.utc) - updated).total_seconds() / 86400, 2) if updated else None
        item["status_evaluated_at"] = utc_now()
        result.append(item)
    return result


def find_satellites(db, query):
    exact, partial = [], []
    for row in db.execute("SELECT * FROM satellites"):
        sat = json.loads(row["data_json"])
        names = [sat["name"], sat["satellite_id"], str(sat.get("norad_id"))] + sat.get("aliases", [])
        if any(query.casefold() == name.casefold() for name in names):
            exact.append(sat["satellite_id"])
        elif any(query.casefold() in name.casefold() for name in names):
            partial.append(sat["satellite_id"])
    result = exact or partial
    if not result:
        raise ValueError("No matching satellite: " + query)
    return result


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def export_database(db, settings):
    directory = settings["export_directory"]
    directory.mkdir(parents=True, exist_ok=True)
    satellites = [json.loads(row[0]) for row in db.execute("SELECT data_json FROM satellites ORDER BY name")]
    operations = operation_rows(db, settings)
    snapshot = {"schema_version": 1, "exported_at": utc_now(), "status_max_age_days": settings["status_max_age_days"],
                "scopes": settings["scopes"], "satellites": satellites, "operations": operations,
                "orbits": [dict(r) for r in db.execute("SELECT * FROM orbits ORDER BY satellite_id,epoch")],
                "observations": [dict(r) for r in db.execute("SELECT * FROM observations ORDER BY operation_id,observed_at")],
                "source_attribution": "SatNOGS DB (CC BY-SA 4.0), AMSAT / JE9PEL / KF0IA, CelesTrak, NOAA, ARISS; source URLs and raw records retained."}
    atomic_json(directory / "satellites.json", snapshot)
    fields = ["satellite_name", "norad_id", "satellite_id", "operation_id", "operation_name", "scopes", "current_status", "catalog_status", "evidence_at", "status_source", "modulation", "protocols", "uplink_availability", "uplink_low_hz", "uplink_high_hz", "downlink_low_hz", "downlink_high_hz", "downlink_band", "occupied_bandwidth_hz", "necessary_bandwidth_hz", "passband_width_hz", "symbol_rate_baud", "data_rate_bps", "review_required", "source_url", "source_updated_at", "superseded_by"]
    temp = directory / "operations.csv.tmp"
    with temp.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for op in operations:
            row = {key: "; ".join(op[key]) if isinstance(op.get(key), list) else op.get(key) for key in fields}
            # Prevent spreadsheet formula interpretation of remotely supplied text.
            row = {key: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for key, value in row.items()}
            writer.writerow(row)
    temp.replace(directory / "operations.csv")
    last = db.execute("SELECT report_json FROM refresh_runs ORDER BY run_id DESC LIMIT 1").fetchone()
    report = json.loads(last[0]) if last else {}
    report["current_status_counts"] = dict(Counter(op["current_status"] for op in operations))
    report["scope_counts"] = dict(Counter(scope for op in operations if not op.get("superseded_by") for scope in op["scopes"]))
    report["satellites_with_orbits"] = db.execute("SELECT COUNT(DISTINCT satellite_id) FROM orbits").fetchone()[0]
    report["review_required_operations"] = sum(bool(op.get("review_required")) for op in operations)
    report["lifecycle_counts"] = dict(Counter(s.get("lifecycle", "unknown") for s in satellites))
    report["missing_orbits"] = len(satellites) - report["satellites_with_orbits"]
    report["current_status_evaluated_at"] = utc_now()
    report["in_orbit_scope_counts"] = dict(Counter(scope for op in operations if op.get("lifecycle") == "in orbit" and not op.get("superseded_by") for scope in op["scopes"]))
    report["unmatched_report_labels"] = [dict(r) for r in db.execute("SELECT satellite_label,mode_label,COUNT(*) AS report_count FROM reception_reports WHERE operation_id IS NULL GROUP BY satellite_label,mode_label")]
    atomic_json(directory / "coverage.json", report)


def position(db, settings, args):
    if not (-90 <= args.latitude <= 90 and -180 <= args.longitude <= 180):
        raise ValueError("Latitude/longitude out of range")
    if not (-500 <= args.altitude <= 100000):
        raise ValueError("Altitude must be -500 to 100000 metres")
    try:
        from skyfield.api import EarthSatellite, load, wgs84
    except ImportError as exc:
        raise ValueError("Position needs the optional package: python -m pip install -r satellite_database/requirements-tracking.txt") from exc
    ids = find_satellites(db, args.satellite)
    if len(ids) != 1:
        raise ValueError("Several satellites match; use a NORAD ID")
    now = parse_time(args.at) if args.at else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("Invalid --at ISO timestamp")
    candidates = db.execute("SELECT * FROM orbits WHERE satellite_id=? AND epoch IS NOT NULL", (ids[0],)).fetchall()
    if not candidates:
        raise ValueError("No orbital elements stored for this satellite")
    orbit = min(candidates, key=lambda r: abs((now - parse_time(r["epoch"])).total_seconds()))
    age = abs((now - parse_time(orbit["epoch"])).total_seconds()) / 86400
    if age > settings["orbit_max_age_days"]:
        raise ValueError("Orbital elements are %.1f days from requested time; refresh before calculating" % age)
    ts = load.timescale(builtin=True)
    elements = json.loads(orbit["data_json"])
    if orbit["format"] == "OMM_JSON":
        # SGP4 expects UTC without a suffix, even when the source uses ISO +00:00/Z.
        epoch = parse_time(elements["EPOCH"])
        if epoch is None:
            raise ValueError("Invalid OMM epoch")
        elements["EPOCH"] = epoch.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
        sat = EarthSatellite.from_omm(ts, elements)
    else:
        sat = EarthSatellite(elements["tle1"], elements["tle2"], elements.get("tle0", ""), ts)
    time = ts.from_datetime(now)
    geocentric = sat.at(time)
    if geocentric.message:
        raise ValueError("Orbit propagation failed: " + str(geocentric.message))
    subpoint = wgs84.subpoint(geocentric)
    observer = wgs84.latlon(args.latitude, args.longitude, elevation_m=args.altitude)
    elevation, azimuth, distance = (sat - observer).at(time).altaz()
    result = {"satellite_id": ids[0], "calculated_at": now.isoformat(), "satellite_latitude_deg": subpoint.latitude.degrees,
              "satellite_longitude_deg": subpoint.longitude.degrees, "satellite_altitude_km": subpoint.elevation.km,
              "azimuth_true_deg": azimuth.degrees, "elevation_deg": elevation.degrees, "range_km": distance.km,
              "above_geometric_horizon": bool(elevation.degrees > 0), "orbit_epoch": orbit["epoch"], "orbit_source": orbit["source_url"],
              "note": "Calculated orbital prediction, not measured position or proof of reception. Azimuth is clockwise from true north."}
    print(json.dumps(result, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", default=str(HERE / "settings.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    update = sub.add_parser("refresh", help="Fetch, merge, save and export the catalog")
    update.add_argument("--offline", action="store_true", help="Rebuild from cached responses without network")
    update.add_argument("--no-celestrak", action="store_true", help="Use SatNOGS orbital elements only")
    update.add_argument("--overrides", default=str(HERE / "operator_overrides.json"))
    listing = sub.add_parser("list", help="Query operations with current evidence status")
    listing.add_argument("--satellite")
    listing.add_argument("--scope")
    listing.add_argument("--status", choices=STATUSES)
    listing.add_argument("--json", action="store_true")
    show = sub.add_parser("show", help="All recorded capabilities and evidence for a satellite")
    show.add_argument("satellite")
    sub.add_parser("summary", help="Coverage, freshness and source errors")
    sub.add_parser("export", help="Update JSON and CSV snapshots without network")
    observe = sub.add_parser("import-observations", help="Record dated evidence for existing capabilities")
    observe.add_argument("file")
    pointing = sub.add_parser("position", help="Calculate pointing locally from stored elements")
    pointing.add_argument("satellite")
    pointing.add_argument("latitude", type=float)
    pointing.add_argument("longitude", type=float)
    pointing.add_argument("--altitude", type=float, default=0, help="Metres above sea level")
    pointing.add_argument("--at", help="ISO UTC timestamp; defaults to now")
    args = parser.parse_args(argv)
    try:
        settings = settings_from(args.settings)
        if args.command == "refresh":
            return refresh(settings, args)
        db = connect(settings)
        try:
            if args.command == "list":
                if args.scope and args.scope not in settings["scopes"]:
                    raise ValueError("Unknown scope. Choose: " + ", ".join(settings["scopes"]))
                rows = operation_rows(db, settings, args.satellite, args.scope, args.status)
                if args.json:
                    print(json.dumps(rows, ensure_ascii=False, indent=2))
                else:
                    for row in rows:
                        hz = row.get("downlink_low_hz")
                        print("%s | %s | %s | %s | %s MHz | %s" % (row["satellite_name"], row["norad_id"], row["current_status"], row["operation_name"], "?" if hz is None else "%g" % (hz / 1e6), row["operation_id"]))
                    print("%d operations. Status is recent evidence, not a guarantee of transmission now." % len(rows), file=sys.stderr)
            elif args.command == "show":
                ids = find_satellites(db, args.satellite)
                result = []
                for sat_id in ids:
                    sat = json.loads(db.execute("SELECT data_json FROM satellites WHERE satellite_id=?", (sat_id,)).fetchone()[0])
                    sat["operations"] = operation_rows(db, settings, sat_id)
                    sat["observations"] = [dict(r) for r in db.execute("SELECT * FROM observations WHERE operation_id IN (SELECT operation_id FROM operations WHERE satellite_id=?) ORDER BY observed_at DESC", (sat_id,))]
                    sat["orbits"] = [dict(r) for r in db.execute("SELECT * FROM orbits WHERE satellite_id=?", (sat_id,))]
                    result.append(sat)
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif args.command in ("summary", "export"):
                export_database(db, settings)
                print((settings["export_directory"] / "coverage.json").read_text(encoding="utf-8"))
            elif args.command == "import-observations":
                observations = read_json(args.file)
                if not isinstance(observations, list):
                    raise ValueError("Observation file must be a JSON list")
                ids = {r[0] for r in db.execute("SELECT operation_id FROM operations")}
                for item in observations:
                    validate_observation(item, ids)
                with db:
                    for item in observations:
                        save_observation(db, item)
                export_database(db, settings)
                print("Imported %d observations." % len(observations))
            elif args.command == "position":
                position(db, settings, args)
        finally:
            db.close()
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
