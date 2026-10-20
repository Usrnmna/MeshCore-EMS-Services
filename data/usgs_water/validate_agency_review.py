"""Verify original-agency address evidence without downloading observations."""

import argparse
from collections import Counter
from contextlib import closing
import gzip
import io
import json
from pathlib import Path
import zipfile

from data.flood_impacts import archive
from data.usgs_water.agency_review import check_swim_archive, dbf_rows, derive, sevenzip_member
from data.usgs_water.relationships import read_csv
from data.usgs_water.refresh import ROOT
from data.usgs_water.validate import verify_receipts
from data.usgs_water.validate_link_review import connect, csv_record


def validate(root):
    """Replay all decisions, verify complete source selections and current retention."""
    directory, manifest = archive.open_generation(root, "agency_review")
    for kind in ("inventory", "network", "link_review"):
        if archive.read_json(root / (kind + ".json")) != manifest[kind + "_pointer"]:
            raise ValueError("Original-agency review has stale source versions")
    ids = set(manifest["station_ids"])
    receipts = verify_receipts(directory)
    item = archive.read_json(directory / "raw/swim_metadata.gz")
    original = gzip.decompress((directory / "raw/swim_archive.gz").read_bytes())
    with zipfile.ZipFile(io.BytesIO(original)) as bundle:
        source_checks = check_swim_archive(bundle, item)
        all_swim = list(dbf_rows(bundle.read("SWIM_gage_loc/SWIM_gage_loc.dbf")))
    selected_swim = [r for r in all_swim if "USGS-" + r["Gage_no"] in ids]
    if selected_swim != archive.read_json(directory / "swim_selected.json"):
        raise ValueError("An original USGS review record was omitted or changed")
    original = gzip.decompress((directory / "raw/gageloc_archive.gz").read_bytes())
    original_dbf = sevenzip_member(original, directory, "gageloc.dbf")
    if original_dbf != (directory / "gageloc.dbf").read_bytes():
        raise ValueError("Extracted GageLoc differs from original archive")
    all_gages = list(dbf_rows(original_dbf))
    selected_gages = [r for r in all_gages if "USGS-" + r["SOURCE_FEA"] in ids]
    if selected_gages != archive.read_json(directory / "gageloc_selected.json"):
        raise ValueError("An original GageLoc address was omitted or changed")
    current = archive.read_json(directory / "current_station_metadata.json")
    if set(current) != ids:
        raise ValueError("A station lacks a fresh agency identity check")
    for sid, feature in current.items():
        if feature != archive.read_json(directory / "raw/usgs_station" / (sid + ".gz")):
            raise ValueError("Agency station metadata differs from the preserved response")
    decisions, candidates, geometries = derive(directory, manifest, root, offline=True)
    saved = read_csv(directory / "relationships/station_agency_review.csv")
    if [csv_record(r) for r in decisions] != saved:
        raise ValueError("Agency decisions cannot be reproduced")
    if [csv_record(r) for r in candidates] != read_csv(directory / "relationships/agency_address_candidates.csv"):
        raise ValueError("Agency candidate evidence cannot be reproduced")
    supported = [r for r in decisions if r["status"] == "supported_static_nonnetwork_address"]
    if [csv_record(r) for r in supported] != read_csv(directory / "relationships/supported_static_station_features.csv"):
        raise ValueError("Static link export differs from decisions")
    if geometries != archive.read_json(directory / "nonnetwork_features.geojson.gz")["features"]:
        raise ValueError("Static feature geometries differ from original responses")
    statuses = dict(Counter(r["status"] for r in decisions))
    if statuses != manifest["status_counts"] or any(r["routing_supported"] for r in decisions):
        raise ValueError("Agency review acquired an unsupported routing claim")
    observations, om = archive.open_generation(root, "observations")
    rows = read_csv(observations / "latest_measurements.csv")
    if len(rows) != len({r["time_series_id"] for r in rows}):
        raise ValueError("Multiple readings retained for a time series")
    if {p.resolve() for p in (root / "observations").iterdir() if p.is_dir()} != {observations.resolve()}:
        raise ValueError("Additional current-value or historical observation generations exist")
    if manifest["observations_retained"] is not False or list(directory.rglob("*.parquet")):
        raise ValueError("Measurement files entered the agency metadata archive")
    routing, rm = archive.open_generation(root, "routing")
    current_ids = {r["monitoring_location_id"] for r in rows}
    with closing(connect(routing)) as db:
        routed = {r[0] for r in db.execute("SELECT station_id FROM station_routing_coverage WHERE reachable_reaches>0")}
        review_routed = sorted(ids & routed)
    resolved_conflicts = sum(r["previous_status"] == "conflicting_published_addresses" for r in supported)
    return {"validated_at_utc": archive.utc_now(), "agency_review_generation": manifest["generation"],
            "routing_generation": rm["generation"], "observation_generation": om["generation"],
            "reviewed_stations": len(ids), "status_counts": statuses,
            "supported_static_feature_links": len(supported), "resolved_conflicting_static_addresses": resolved_conflicts,
            "new_static_addresses_from_previously_uncorroborated": len(supported) - resolved_conflicts,
            "unresolved_addresses": len(ids) - len(supported),
            "raw_receipts_verified": receipts, "agency_gageloc_total_records": len(all_gages),
            "agency_gageloc_matching_records": len(selected_gages), "swim_total_records": len(all_swim),
            "swim_matching_records": len(selected_swim),
            "swim_publisher_checksum_checks": source_checks,
            "reviewed_station_ids_with_routing": review_routed, "routing_links_added_by_agency_review": 0,
            "current_stations_with_routing": len(current_ids & routed),
            "current_stations_without_routing": len(current_ids - routed),
            "current_readings": len(rows), "level_history_retained": False,
            "limits": "Historical agency address evidence and present source consistency; no hydraulic or inundation validation"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.directory)
    if args.output:
        archive.write_json(args.output, result)
    print(json.dumps(result, indent=2))
