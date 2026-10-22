"""Validate cached source receipts, routing joins, and exported basin-portion geometry."""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

from shapely.ops import unary_union

if __package__:
    from . import archive, hydro
    from .report import table
else:
    import archive
    import hydro
    from report import table


def validate(root, include_observations=True):
    """Check semantic consistency after checksum verification, without network access.

    These checks establish consistency of the archived/reference products. They
    do not validate hydraulic predictions against an observed flood event.
    Static-only data installations set include_observations=False; all static
    receipt, routing, area, and coverage checks remain enabled.
    """
    static, manifest = archive.open_generation(root)
    observation_manifest = None
    bound_static = None
    directories = {static}
    if include_observations:
        observations, observation_manifest = archive.open_generation(root, "observations")
        bound_static, _ = archive.open_generation(root, pointer=observation_manifest["static_pointer"])
        directories.update((observations, bound_static))
    receipts = 0
    for directory in directories:
        for receipt_path in directory.glob("raw/*.receipt.json"):
            receipt = archive.read_json(receipt_path)
            raw_path = receipt_path.with_name(receipt_path.name.replace(".receipt.json", ".json.gz"))
            raw = gzip.decompress(raw_path.read_bytes())
            if len(raw) != receipt["raw_byte_count"] or hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]:
                raise ValueError(f"Raw response receipt mismatch: {raw_path}")
            receipts += 1
    region = static / "regions" / manifest["config"]["region"]
    network = {hydro.identifier(f["properties"]["comid"]): f["properties"]
               for f in archive.read_json(region / "waterways.geojson.gz")["features"]}
    edges = table(region, "flow_connections")
    for edge in edges:
        source = network[edge["from_reach_id"]]
        if edge["to_reach_id"]:
            target = network[edge["to_reach_id"]]
            if not source.get("tonode") or source["tonode"] != target["fromnode"]:
                raise ValueError("Directed edge lacks matching published nodes")
    for gauge in table(region, "gauge_reach_links"):
        route = archive.read_json(static / f"raw/route_{gauge['gauge_lid']}.json.gz")
        expected = {hydro.identifier(f["properties"]["nhdplus_comid"]) for f in route["features"]}
        if hydro.downstream(gauge["reach_id"], edges) != expected:
            raise ValueError(f"Network/NLDI disagreement: {gauge['gauge_lid']}")
    context = hydro.GeometryContext(manifest["config"]["metric_crs"])
    footprints = {f["properties"]["scenario_id"]: context.project(f["geometry"], "scenario")
                  for f in archive.read_json(region / "inundation_scenarios.geojson.gz")["features"]}
    impacts = {(r["scenario_id"], r["basin_id"]): r for r in table(region, "scenario_basin_impacts")}
    seen, grouped = set(), defaultdict(list)
    for feature in archive.read_json(region / "scenario_basin_portions.geojson.gz")["features"]:
        p = feature["properties"]
        key = p["scenario_id"], p["basin_id"]
        if key in seen:
            raise ValueError("Duplicate scenario/basin portion")
        seen.add(key)
        row = impacts[key]
        geometry = context.project(feature["geometry"], str(key))
        area = float(row["affected_area_m2"])
        tolerance = max(0.1, area * 0.000001)
        if abs(geometry.area - area) > tolerance or not 0 < float(row["basin_fraction"]) <= 1.000001:
            raise ValueError("Exported area or basin fraction mismatch")
        if geometry.difference(footprints[key[0]]).area > tolerance:
            raise ValueError("Basin portion extends outside its source scenario")
        grouped[(key[0], row["calwater_level"])].append(geometry)
    if seen != set(impacts):
        raise ValueError("Missing exported basin portions")
    coverage = [{"scenario_id": key[0], "calwater_level": key[1],
                 "mapped_footprint_fraction": unary_union(parts).area / footprints[key[0]].area}
                for key, parts in sorted(grouped.items())]
    return {"verified_at_utc": archive.utc_now(), "static_generation": manifest["generation"],
            "observation_generation": observation_manifest["generation"] if observation_manifest else None,
            "observations_bound_to_active_static": bound_static == static if include_observations else None,
            "verified_static_files": len(manifest["files"]),
            "verified_observation_files": len(observation_manifest["files"]) if observation_manifest else 0,
            "raw_receipts_verified": receipts, "network_reaches": len(network),
            "connection_rows": len(edges), "scenario_basin_portions_verified": len(seen),
            "scenario_level_coverage": coverage,
            "limits": "Reference-data and geometry consistency only; no observed-event or hydraulic validation."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=archive.ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--static-only", action="store_true", help="Verify the static reference without optional observations")
    args = parser.parse_args()
    result = validate(args.directory, include_observations=not args.static_only)
    if args.output:
        archive.write_json(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k != "scenario_level_coverage"}, indent=2))
