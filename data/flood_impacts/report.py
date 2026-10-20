"""Inspect verified flood relationships and compare cached stages entirely offline."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

if __package__:
    from . import archive, hydro
else:
    import archive
    import hydro


def table(directory, name):
    with (directory / "relationships" / (name + ".csv")).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def report(root, gauge_lid, scenario_id=None, now=None):
    """Use the observation generation's pinned static inputs; freshness is checked at read time."""
    now = now or datetime.now(timezone.utc)
    observations, observation_manifest = archive.open_generation(root, "observations")
    static, manifest = archive.open_generation(root, pointer=observation_manifest["static_pointer"])
    config = manifest["config"]
    if gauge_lid not in [s["lid"] for s in config["stations"]]:
        raise ValueError("Gauge is outside this configured pilot")
    region = static / "regions" / config["region"]
    gauge = archive.read_json(observations / f"raw/gauge_{gauge_lid}.json.gz")
    series = archive.read_json(observations / f"raw/stageflow_{gauge_lid}.json.gz")
    sites = archive.read_json(static / "inputs/pilot_sites.geojson.gz")["features"]
    site = next((f["properties"] for f in sites if f["properties"]["ahps_lid"].upper() == gauge_lid), {})
    scenarios = [s for s in table(region, "inundation_scenarios") if s["gauge_lid"] == gauge_lid]
    link = next(r for r in table(region, "gauge_reach_links") if r["gauge_lid"] == gauge_lid)
    comparisons = [hydro.stage_comparison(gauge, series, site, scenarios, kind, now, config[age_key])
                   for kind, age_key in (("observed", "observation_max_age_hours"),
                                         ("forecast", "forecast_max_age_hours"))]
    # A new gauge/reach assignment requires a static refresh and review, even if
    # the agency's USGS station ID remains unchanged.
    if (link["status"] != "published_identifier_match" or
            hydro.identifier(gauge.get("reachId")) != link["reach_id"]):
        for comparison in comparisons:
            comparison.update(status="gauge_reach_requires_review", lower_scenarios="", upper_scenarios="")
    result = {"title": config["title"], "gauge": gauge["name"], "region": config["region"],
              "static_generation": manifest["generation"], "observation_generation": observation_manifest["generation"],
              "gauge_reach_link": link, "comparisons": comparisons,
              "coverage": next(r for r in table(region, "coverage") if r["gauge_lid"] == gauge_lid),
              "downstream_basin_relationship_count": sum(r["gauge_lid"] == gauge_lid for r in table(region, "gauge_downstream_basins")),
              "available_scenarios": [{k: s[k] for k in ("scenario_id", "stage", "stage_units", "category")} for s in scenarios],
              "interpretation": "Static scenario review, not an observed or forecast flood footprint. "
                                "Connected basins are not necessarily flooded; empty coverage does not mean no flood."}
    if scenario_id:
        selected = next((s for s in scenarios if s["scenario_id"] == scenario_id), None)
        if selected is None:
            raise ValueError("Scenario does not belong to the selected gauge")
        result["selected_what_if_scenario"] = selected
        result["basin_portions"] = [r for r in table(region, "scenario_basin_impacts") if r["scenario_id"] == scenario_id]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=archive.ROOT)
    parser.add_argument("--gauge", default="HEAC1")
    parser.add_argument("--scenario", help="Review a specific static scenario; never labels it as a current flood")
    parser.add_argument("--at", help="Evaluate freshness at an explicit ISO UTC time for reproducible historical review")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output", type=Path, help="Write the report as JSON")
    args = parser.parse_args()
    if args.verify:
        checked = []
        for kind in ("static", "observations"):
            _, manifest = archive.open_generation(args.directory, kind)
            checked.append({"kind": kind, "generation": manifest["generation"], "verified_files": len(manifest["files"])})
        print(json.dumps(checked, indent=2))
        return
    now = hydro.parse_time(args.at) if args.at else None
    if args.at and now is None:
        parser.error("--at requires an ISO time with a timezone")
    result = report(args.directory, args.gauge.upper(), args.scenario, now)
    if args.output:
        archive.write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
