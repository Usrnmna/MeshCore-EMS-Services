"""Replay local operator metadata links and verify unchanged current-only retention."""

import argparse
from collections import Counter
from contextlib import closing
import json

from data.flood_impacts import archive
from data.usgs_water.local_review import compatible, derive, source_alternatives
from data.usgs_water.audit_source_rules import audit_generation
from data.usgs_water.relationships import read_csv
from data.usgs_water.refresh import ROOT
from data.usgs_water.validate_link_review import connect, csv_record


def validate(root):
    """Verify manifests, reviewed selections, all unresolved decisions and routing limits.

    Original document hashes record acquisition provenance. Offline replay verifies
    retained excerpts, not discarded full PDF bodies; this distinction is explicit.
    """
    directory, manifest = archive.open_generation(root, "local_review")
    observations, om = archive.open_generation(root, "observations")
    if not compatible(manifest, root, om["inventory_pointer"]):
        raise ValueError("Local review has stale dependencies")
    agency, _ = archive.open_generation(root, "agency_review", manifest["agency_review_pointer"])
    priors = [r for r in read_csv(agency / "relationships/station_agency_review.csv")
              if r["status"] != "supported_static_nonnetwork_address"]
    rules = archive.read_json(directory / "review_rules.json")
    # The JSON copy is serialized identically to the maintained rule file.
    if archive.digest(directory / "review_rules.json")["sha256"] != manifest["rules_sha256"]:
        raise ValueError("Rules differ from the pinned review")
    if "source_rule_audit_summary" in manifest:
        saved_audit = archive.read_json(directory / "source_rule_audit.json")
        replay = audit_generation(root, directory, manifest["generation"], manifest["rules_sha256"],
                                  saved_audit["history_pointers"])
        comparable = lambda result: {k: v for k, v in result.items() if k != "audited_at_utc"}
        if comparable(saved_audit) != comparable(replay):
            raise ValueError("Source-rule audit cannot be replayed")
        if saved_audit["summary"] != manifest["source_rule_audit_summary"]:
            raise ValueError("Source-rule audit summary differs from manifest")
    receipts = [archive.read_json(directory / "evidence" / (source["id"] + ".json"))
                for source in rules["sources"]]
    decisions, links = derive(priors, archive.read_json(agency / "current_station_metadata.json"), rules, receipts)
    alternatives = source_alternatives(rules, receipts)
    for name, rows in (("station_local_review", decisions), ("station_local_links", links),
                       ("source_alternatives", alternatives)):
        if [csv_record(r) for r in rows] != read_csv(directory / "relationships" / (name + ".csv")):
            raise ValueError("Local relationship export cannot be replayed")
    if len(decisions) != manifest["reviewed_station_count"] or len(links) != manifest["supported_link_count"]:
        raise ValueError("Manifest counts differ from replay")
    if any(row["routing_supported"] for row in links + decisions):
        raise ValueError("Unsupported routing promotion")
    if any(row["station_match_supported"] or row["routing_supported"] for row in alternatives):
        raise ValueError("Alternate context promoted to station or routing match")
    if sum(row["context_available"] for row in alternatives) != manifest["alternate_context_count"]:
        raise ValueError("Alternate source availability differs from manifest")
    if any(row["reach_id"] or row["reachcode"] for row in decisions):
        raise ValueError("A local metadata link acquired a hydrography address")
    inventory, _ = archive.open_generation(root, "inventory", manifest["inventory_pointer"])
    members = read_csv(inventory / "relationships/station_region_plan.csv")
    for region in {r["region"] for r in members}:
        ids = {r["station_id"] for r in members if r["region"] == region}
        expected = [csv_record(r) for r in decisions if r["station_id"] in ids]
        if expected != read_csv(directory / "regions" / region / "station_local_review.csv"):
            raise ValueError("Region catalog differs from statewide decisions")
    readings = read_csv(observations / "latest_measurements.csv")
    if len(readings) != len({r["time_series_id"] for r in readings}):
        raise ValueError("Multiple values per series")
    if {p.resolve() for p in (root / "observations").iterdir() if p.is_dir()} != {observations.resolve()}:
        raise ValueError("Extra observation generations retained")
    if manifest["observations_retained"] is not False or any(
            path.suffix in (".pdf", ".html", ".parquet") for path in directory.rglob("*")):
        raise ValueError("Full report or measurement files entered the metadata collection")
    routing, rm = archive.open_generation(root, "routing")
    with closing(connect(routing)) as db:
        routed = {r[0] for r in db.execute(
            "SELECT station_id FROM station_routing_coverage WHERE reachable_reaches>0")}
    current_ids = {r["monitoring_location_id"] for r in readings}
    return {"validated_at_utc": archive.utc_now(), "local_review_generation": manifest["generation"],
            "reviewed_stations": len(decisions), "supported_metadata_relationships": len(links),
            "stations_with_supported_metadata": len({r["station_id"] for r in links}),
            "unresolved_hydrography_addresses": len(decisions), "routing_links_added": 0,
            "source_status_counts": dict(Counter(r["status"] for r in receipts)),
            "source_rule_audit_summary": manifest.get("source_rule_audit_summary"),
            "verified_alternate_contexts": sum(r["context_available"] for r in alternatives),
            "original_sources_with_verified_alternates": sorted({
                r["original_source_id"] for r in alternatives if r["context_available"]}),
            "current_observation_generation": om["generation"], "current_readings": len(readings),
            "routing_generation": rm["generation"],
            "current_stations_with_routing": len(current_ids & routed),
            "current_stations_without_routing": len(current_ids - routed),
            "reviewed_stations_with_routing": sorted({r["station_id"] for r in decisions} & routed),
            "level_history_retained": False,
            "verification_scope": "Manifest hashes, exact retained metadata, decision replay, region tables and retention; "
                                  "discarded document bodies cannot be rehashed offline"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=type(ROOT), default=ROOT)
    parser.add_argument("--output", type=type(ROOT))
    args = parser.parse_args()
    result = validate(args.directory)
    if args.output:
        archive.write_json(args.output, result)
    print(json.dumps(result, indent=2))
