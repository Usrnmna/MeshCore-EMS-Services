"""Find California stations by name and interpret their latest values offline."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data.flood_impacts import archive
from data.usgs_water.analysis import condition
from data.usgs_water.relationships import read_csv
from data.usgs_water.refresh import ROOT


def report(root, station_id, now=None):
    """Resolve one exact agency-qualified ID; recompute freshness on every read."""
    now = now or datetime.now(timezone.utc)
    observations, om = archive.open_generation(root, "observations")
    inventory, im = archive.open_generation(root, "inventory", om["inventory_pointer"])
    stations = archive.read_json(inventory / "stations.geojson.gz")["features"]
    station = next((f for f in stations if f["id"] == station_id), None)
    if station is None:
        raise ValueError("Station not found in the pinned California inventory")
    series = {str(f["id"]): f["properties"] for f in archive.read_json(inventory / "time_series.geojson.gz")["features"]
              if f["properties"]["monitoring_location_id"] == station_id}
    readings = [r for r in read_csv(observations / "latest_measurements.csv") if r["monitoring_location_id"] == station_id]
    conditions = [condition(r, series.get(r["time_series_id"], {}), now) for r in readings]
    relationships = {}
    for name in ("station_region_plan", "station_calwater_membership", "station_identifiers", "station_contributing_areas"):
        relationships[name] = [r for r in read_csv(inventory / "relationships" / (name + ".csv")) if r["station_id"] == station_id]
    if (root / "network.json").exists():
        network, nm = archive.open_generation(root, "network")
        relationships["network_inventory_matches_observations"] = nm["inventory_pointer"] == om["inventory_pointer"]
        for name in ("station_reach_links", "station_basin_plan_candidates"):
            relationships[name] = [r for r in read_csv(network / "relationships" / (name + ".csv")) if r["station_id"] == station_id]
    aliases = relationships["station_identifiers"]
    lids = {r["nwps_lid"] for r in aliases if r["nwps_lid"]}
    for name in ("gauge_downstream_basins", "inundation_scenarios"):
        relationships[name] = [r for r in read_csv(inventory / "relationships/flood_reference" / (name + ".csv")) if r["gauge_lid"] in lids]
    from data.usgs_water.routing import station_context
    relationships["statewide_downstream_context"] = station_context(root, station_id, om["inventory_pointer"])
    if (root / "link_review.json").exists():
        review, rm = archive.open_generation(root, "link_review")
        compatible = rm["inventory_pointer"] == om["inventory_pointer"] and rm["network_pointer"] == archive.read_json(root / "network.json")
        relationships["supplemental_link_review"] = {
            "status": "available" if compatible else "source_version_mismatch_refresh_link_review",
            "generation": rm["generation"],
            "station_decision": [r for r in read_csv(review / "relationships/station_link_review.csv") if r["station_id"] == station_id] if compatible else [],
            "published_candidates": [r for r in read_csv(review / "relationships/published_address_candidates.csv") if r["station_id"] == station_id] if compatible else []}
    if (root / "agency_review.json").exists():
        agency, am = archive.open_generation(root, "agency_review")
        compatible = am["inventory_pointer"] == om["inventory_pointer"] and all(
            am[kind + "_pointer"] == archive.read_json(root / (kind + ".json")) for kind in ("network", "link_review"))
        relationships["original_agency_review"] = {
            "status": "available" if compatible else "source_version_mismatch_refresh_agency_review",
            "generation": am["generation"],
            "station_decision": [r for r in read_csv(agency / "relationships/station_agency_review.csv")
                                 if r["station_id"] == station_id] if compatible else [],
            "static_feature_links": [r for r in read_csv(agency / "relationships/supported_static_station_features.csv")
                                     if r["station_id"] == station_id] if compatible else [],
            "routing_supported": False}
    if (root / "local_review.json").exists():
        from data.usgs_water.local_review import compatible as local_compatible
        local, lm = archive.open_generation(root, "local_review")
        is_current = local_compatible(lm, root, om["inventory_pointer"])
        relationships["local_operating_agency_review"] = {
            "status": "available" if is_current else "source_version_mismatch_refresh_local_review",
            "generation": lm["generation"], "routing_supported": False,
            "station_decision": [r for r in read_csv(local / "relationships/station_local_review.csv")
                                 if r["station_id"] == station_id] if is_current else [],
            "metadata_links": [r for r in read_csv(local / "relationships/station_local_links.csv")
                               if r["station_id"] == station_id] if is_current else []}
        # Context alternatives remain separate from accepted station relationships.
        local_section = relationships["local_operating_agency_review"]
        source_ids = {source for row in local_section["station_decision"]
                      for source in row["source_ids"].split(";")}
        alternatives_path = local / "relationships/source_alternatives.csv"
        local_section["alternate_source_context"] = [
            row for row in read_csv(alternatives_path) if row["original_source_id"] in source_ids
        ] if is_current and alternatives_path.exists() else []
    return {"evaluated_at_utc": now.isoformat(), "station": station,
            "inventory_generation": im["generation"], "observation_generation": om["generation"],
            "current_values": conditions, "coverage": "latest_values_available" if readings else "no_latest_values_returned",
            "series_metadata": series, "relationships": relationships,
            "interpretation": "Latest reported values may be stale or provisional. Station altitude is not an established gauge-zero datum. "
                              "Connected waterways and containing basins are not predicted flooded areas. No historical level series is stored."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--station", help="Exact agency-qualified ID, e.g. USGS-11464000")
    group.add_argument("--name", help="Case-insensitive substring of a published station name")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.name:
        inventory, _ = archive.open_generation(args.directory, "inventory")
        stations = archive.read_json(inventory / "stations.geojson.gz")["features"]
        result = [{"station_id": f["id"], "name": f["properties"].get("monitoring_location_name"),
                   "site_type": f["properties"].get("site_type")}
                  for f in stations if args.name.casefold() in (f["properties"].get("monitoring_location_name") or "").casefold()]
    else:
        result = report(args.directory, args.station)
    if args.output:
        archive.write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
