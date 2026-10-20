"""Replay supplemental station decisions from archived source evidence."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import shapely

from data.flood_impacts import archive
from data.usgs_water.link_review import assess_station, effective_links, features, key
from data.usgs_water.relationships import read_csv
from data.usgs_water.refresh import ROOT
from data.usgs_water.validate import verify_receipts


def csv_record(row):
    """Normalize an in-memory decision to the CSV writer's scalar representation."""
    return {k: "" if v is None else str(v) for k, v in row.items()}


def connect(directory):
    """Open a published routing database without permitting writes."""
    return sqlite3.connect((directory / "routing.sqlite").resolve().as_uri() + "?mode=ro", uri=True)


def validate(root):
    """Check source receipts, decision replay, routing overlays and value retention."""
    review, manifest = archive.open_generation(root, "link_review")
    inventory, _ = archive.open_generation(root, "inventory", manifest["inventory_pointer"])
    network, _ = archive.open_generation(root, "network", manifest["network_pointer"])
    baseline, _ = archive.open_generation(root, "routing", manifest["routing_pointer"])
    routing, rm = archive.open_generation(root, "routing")
    observations, om = archive.open_generation(root, "observations")
    if any(archive.read_json(root / (kind + ".json")) != manifest[kind + "_pointer"]
           for kind in ("inventory", "network")):
        raise ValueError("Supplemental review does not use the active source versions")
    if rm.get("link_review_pointer") != archive.read_json(root / "link_review.json"):
        raise ValueError("Routing does not use the active supplemental review")
    if om["inventory_pointer"] != manifest["inventory_pointer"]:
        raise ValueError("Current readings and station review use different inventories")
    receipts = verify_receipts(review)
    decisions = read_csv(review / "relationships/station_link_review.csv")
    ids = [row["station_id"] for row in decisions]
    if len(ids) != len(set(ids)) or sorted(ids) != manifest["station_ids"]:
        raise ValueError("Station review scope has missing or duplicate decisions")
    statuses = dict(Counter(row["status"] for row in decisions))
    if statuses != manifest["status_counts"] or manifest["observations_retained"] is not False:
        raise ValueError("Review manifest does not describe the decision tables")
    stations = {f["id"]: f for f in archive.read_json(inventory / "stations.geojson.gz")["features"]}
    state = defaultdict(list)
    state_path = review / "raw/waterboards_stations.gz"
    state_features = archive.read_json(state_path)["features"] if state_path.exists() else []
    source_ids = archive.read_json(review / "raw/waterboards_ids.gz")["objectIds"]
    after_ids = archive.read_json(review / "raw/waterboards_ids_after.gz")["objectIds"]
    returned_ids = [f["properties"]["objectid"] for f in state_features]
    if (len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != set(source_ids)
            or set(after_ids) != set(source_ids)):
        raise ValueError("Water Board station enumeration is incomplete")
    for feature in state_features:
        state["USGS-" + feature["properties"]["siteid"]].append(feature)
    replayed_candidates = []
    with closing(connect(baseline)) as db:
        def lookup(rid):
            """Resolve only the pinned network or preserved nonnetwork response."""
            row = db.execute(
                "SELECT reachcode,feature_type,enabled,flow_direction,geometry_wkb FROM reaches WHERE reach_id=?",
                (rid,)).fetchone()
            if row:
                result = dict(zip(("reachcode", "feature_type", "enabled", "flow_direction"), row[:4]))
                result.update(collection="network",
                              geometry=json.loads(shapely.to_geojson(shapely.from_wkb(row[4]))))
                return result
            fs = features(archive.read_json(review / "raw/nonnetwork" / (rid + ".gz")))
            if not fs:
                return None
            p = fs[0]["properties"]
            if len(fs) != 1 or key(p["comid"]) != rid:
                raise ValueError("Nonnetwork feature identity mismatch")
            return {"reachcode": p["reachcode"], "feature_type": p["ftype"], "enabled": None,
                    "flow_direction": p["flowdir"], "geometry": fs[0]["geometry"], "collection": "nonnetwork"}

        for saved in decisions:
            sid = saved["station_id"]
            primary = features(archive.read_json(review / "raw/nldi_recheck" / (sid + ".gz")))
            refs = archive.read_json(review / "raw/reference_gages" / (sid + ".gz"))
            if refs["numberMatched"] != len(refs["features"]):
                raise ValueError("Reference results are incomplete")
            sb_path = review / "raw/sb19_identity" / (sid + ".gz")
            sb = features(archive.read_json(sb_path)) if sb_path.exists() else []
            decision, candidates = assess_station(stations[sid], primary, refs["features"], state[sid], sb, lookup)
            if csv_record(decision) != saved:
                raise ValueError(f"Station decision cannot be reproduced: {sid}")
            for row in candidates:
                record = lookup(row["reach_id"]) if row["reach_id"] else None
                row.update(hydrography_collection=record["collection"] if record else "",
                           hydrography_reachcode=record["reachcode"] if record else "",
                           key_check=("consistent" if record and record["reachcode"] == row["reachcode"]
                                      else "reachcode_conflict" if record else "no_checked_feature"))
                replayed_candidates.append(csv_record(row))
    if replayed_candidates != read_csv(review / "relationships/published_address_candidates.csv"):
        raise ValueError("Published candidates or conflict labels cannot be reproduced")
    for name, status in (("supplemental_routing_links", "supported_supplemental_routing"),
                         ("supported_nonnetwork_addresses", "supported_nonnetwork_address_no_downstream")):
        if read_csv(review / "relationships" / (name + ".csv")) != [r for r in decisions if r["status"] == status]:
            raise ValueError("A supported-link export differs from its review decisions")
    effective, _ = effective_links(root, network, manifest["inventory_pointer"], manifest["network_pointer"])
    if effective != read_csv(routing / "relationships/effective_station_reach_links.csv"):
        raise ValueError("Routing exported a different effective station-link table")
    current_rows = read_csv(observations / "latest_measurements.csv")
    if len({r["time_series_id"] for r in current_rows}) != len(current_rows):
        raise ValueError("Multiple current values were retained for a series")
    observation_dirs = [p for p in (root / "observations").iterdir() if p.is_dir()]
    if {p.resolve() for p in observation_dirs} != {observations.resolve()}:
        raise ValueError("An additional observation generation or pending value download remains")
    if list(review.rglob("*.parquet")) or (review / "latest_measurements.csv").exists():
        raise ValueError("Measurements were copied into the metadata review")
    current_ids = {r["monitoring_location_id"] for r in current_rows}
    accepted = {r["station_id"] for r in decisions if r["status"] == "supported_supplemental_routing"}
    with closing(connect(baseline)) as before, closing(connect(routing)) as after:
        old_routes = {r[0] for r in before.execute("SELECT station_id FROM station_routing_coverage WHERE reachable_reaches>0")}
        new_routes = {r[0] for r in after.execute("SELECT station_id FROM station_routing_coverage WHERE reachable_reaches>0")}
        if not old_routes.issubset(new_routes) or not accepted.issubset(new_routes):
            raise ValueError("An existing or accepted station lost routing")
        if new_routes - old_routes != accepted - old_routes:
            raise ValueError("Routing promoted an unsupported station")
        for row in decisions:
            if row["status"] != "supported_supplemental_routing" and row["station_id"] not in old_routes:
                if row["station_id"] in new_routes:
                    raise ValueError("An unresolved or nonnetwork address acquired downstream routes")
    return {"validated_at_utc": archive.utc_now(), "review_generation": manifest["generation"],
            "routing_generation": rm["generation"], "observation_generation": om["generation"],
            "stations_reviewed": len(ids), "status_counts": statuses, "raw_receipts_verified": receipts,
            "published_candidate_rows": len(replayed_candidates),
            "archived_nonnetwork_features": len(archive.read_json(review / "nonnetwork_features.geojson.gz")["features"]),
            "current_readings": len(current_rows), "current_stations": len(current_ids),
            "current_stations_routed_before": len(current_ids & old_routes),
            "current_stations_routed_after": len(current_ids & new_routes),
            "current_stations_without_routing": len(current_ids - new_routes),
            "added_routing_station_ids": sorted(new_routes - old_routes),
            "level_history_retained": False,
            "validation_limit": "Archived-source consistency and routing integration, not hydraulic validation"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.directory)
    if args.output:
        archive.write_json(args.output, result)
    print(json.dumps(result, indent=2))
