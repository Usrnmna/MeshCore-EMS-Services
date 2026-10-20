"""Verify statewide current snapshots, source receipts and Russian River joins."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data.basin_plans.organize import REGIONS
from data.flood_impacts import archive
from data.flood_impacts.validate import validate as validate_flood
from data.usgs_water.analysis import numeric
from data.usgs_water.relationships import read_csv
from data.usgs_water.refresh import ROOT


def verify_receipts(directory):
    """Verify decompressed original bytes against receipts, independently of manifests."""
    count = 0
    for path in directory.glob("raw/**/*.receipt.json"):
        receipt = archive.read_json(path)
        raw_path = path.with_name(path.name.replace(".receipt.json", ".gz"))
        raw = gzip.decompress(raw_path.read_bytes())
        if (len(raw) != receipt["raw_byte_count"] or hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]
                or archive.digest(raw_path) != receipt["stored_file"]):
            raise ValueError(f"Source receipt mismatch: {path}")
        count += 1
    return count


def validate(root, flood_root):
    """Validate coverage and identity joins without claiming flood prediction accuracy."""
    observations, om = archive.open_generation(root, "observations")
    inventory, im = archive.open_generation(root, "inventory", om["inventory_pointer"])
    network, nm = archive.open_generation(root, "network")
    if nm["inventory_pointer"] != om["inventory_pointer"]:
        raise ValueError("Network and observations use different inventory versions; refresh dependent products")
    receipts = sum(verify_receipts(p) for p in (inventory, observations, network))
    if list(observations.glob("raw/continuous_*")) or list(observations.glob("measurements/continuous_*")):
        raise ValueError("Historical level files are forbidden in the current snapshot")
    if len([p for p in (root / "observations").iterdir() if p.is_dir() and not p.name.startswith(".pending-")]) != 1:
        raise ValueError("Obsolete measurement generations were retained")
    stations = {str(f["id"]): f for f in archive.read_json(inventory / "stations.geojson.gz")["features"]}
    metadata = {str(f["id"]): f["properties"] for f in archive.read_json(inventory / "time_series.geojson.gz")["features"]}
    if any(str(f["properties"]["state_code"]) != "06" for f in stations.values()):
        raise ValueError("Inventory contains an out-of-scope state")
    counts, seen, rows = Counter(), set(), []
    for path in sorted((observations / "measurements").glob("*.parquet")):
        records = pq.read_table(path).to_pylist()
        if len(records) != om["counts"][path.stem]:
            raise ValueError("Parquet/source row counts differ")
        for row in records:
            sid = row["time_series_id"]
            if sid in seen:
                raise ValueError("Multiple stored levels for a single current series")
            seen.add(sid)
            if sid in metadata and (metadata[sid]["monitoring_location_id"] != row["monitoring_location_id"]
                                    or metadata[sid]["parameter_code"] != row["parameter_code"]):
                raise ValueError("Measurement and metadata identity disagreement")
            counts[(row["monitoring_location_id"], row["parameter_code"])] += 1
        rows.extend(records)
    memberships = read_csv(inventory / "relationships/station_calwater_membership.csv")
    if any(r["station_id"] not in stations for r in memberships):
        raise ValueError("Unknown station in CalWater relationships")
    region_rows = read_csv(inventory / "region_coverage.csv")
    if not set(REGIONS).issubset({r["region"] for r in region_rows}):
        raise ValueError("Missing statewide regional catalog")
    for slug in REGIONS:
        for name in ("README.md", "catalog.csv", "stations.csv"):
            if not (inventory / "regions" / slug / name).is_file():
                raise ValueError("Missing regional review file")
    links = {r["station_id"]: r for r in read_csv(network / "relationships/station_reach_links.csv")}
    queried = {p["monitoring_location_id"] for p in metadata.values()}
    if nm["counts"]["california_stations_queried"] != len(queried):
        raise ValueError("Network lookup is not statewide for stage/discharge stations")
    if set(links) != set(stations):
        raise ValueError("Unresolved stations disappeared from network table")
    # The organization index binds published relationship artifacts, including
    # compressed member tables. Verify references against that original index.
    bp = im["basin_pointer"]
    basin_root = flood_root.parent / "basin_plans"
    organization = basin_root / bp["organization_path"]
    organization_path = organization / "organization.json"
    if archive.digest(organization_path)["sha256"] != bp["organization_manifest_sha256"]:
        raise ValueError("Basin relationship organization index changed")
    organization_manifest = archive.read_json(organization_path)
    refs = archive.read_json(inventory / "basin_relationship_references.json")
    for item in refs["relationships"]:
        relative = item["path"].replace("\\", "/")
        if archive.digest(archive.safe_path(organization, relative)) != organization_manifest["files"][relative]:
            raise ValueError("A referenced Basin Plan relationship changed")
    # Verify the original flood reference independently; this retains the directed
    # tributary table and its node/topology and source-navigation checks.
    flood_result = validate_flood(flood_root)
    flood, fm = archive.open_generation(flood_root, "static", im["flood_pointer"])
    source = flood / "regions" / fm["config"]["region"] / "relationships"
    if archive.digest(source / "flow_connections.csv") != archive.digest(network / "relationships/flow_connections.csv"):
        raise ValueError("Tributary relationship table changed during integration")
    pilot_rows = []
    for gauge in read_csv(source / "gauge_reach_links.csv"):
        station = "USGS-" + gauge["usgs_id"]
        link = links[station]
        if link["reach_id"] != gauge["reach_id"] or link["reachcode"] != gauge["reachcode"]:
            raise ValueError("Russian River published reach identifiers disagree")
        basin_rows = [r for r in memberships if r["station_id"] == station]
        current = [r for r in rows if r["monitoring_location_id"] == station]
        stage_rows = [r for r in current if r["parameter_code"] == "00065" and numeric(r["value"]) is not None]
        if not stage_rows or not basin_rows:
            raise ValueError("Russian River pilot lacks current stage or CalWater membership")
        pilot_rows.append({"station_id": station, "nwps_lid": gauge["gauge_lid"],
                           "station_name": stations[station]["properties"]["monitoring_location_name"],
                           "reach_id": link["reach_id"], "reachcode": link["reachcode"],
                           "stage_series_count": len(stage_rows), "discharge_series_count": counts[(station, "00060")],
                           "discharge_status": "available" if counts[(station, "00060")] else "no_latest_discharge_returned",
                           "calwater_memberships": len(basin_rows),
                           "status": "station_series_reach_and_basin_joins_verified",
                           "flood_extent_status": "not_inferred_from_USGS_values_datum_and_hydraulics_require_verification"})
    return {"validated_at_utc": archive.utc_now(), "scope": "Statewide inventory, current observations and network links; Russian River integration checks",
            "inventory_generation": im["generation"], "observation_generation": om["generation"], "network_generation": nm["generation"],
            "station_count": len(stations), "series_metadata_count": len(metadata), "current_reading_count": len(rows),
            "stations_with_current_readings": len({r["monitoring_location_id"] for r in rows}),
            "verified_raw_receipts": receipts, "calwater_memberships": len(memberships),
            "network_counts": nm["counts"], "regions": region_rows, "russian_river_pilot": pilot_rows,
            "existing_flood_reference_validation": flood_result,
            "validation_limit": "Consistency and coverage checks only; no independent flood-event or prediction-skill validation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--flood-directory", type=Path, default=ROOT.parent / "flood_impacts")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.directory, args.flood_directory)
    if args.output:
        archive.write_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
