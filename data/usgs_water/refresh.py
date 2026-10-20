"""Refresh all California stations and statewide stage/discharge observations."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data.flood_impacts import archive
from data.usgs_water.client import BASE, Client

ROOT = Path(__file__).resolve().parent
PARAMETERS = ("00060", "00065")


def collection(features):
    return {"type": "FeatureCollection", "features": features}


def build_stage(root, kind, resume, settings):
    """Resume an explicitly selected pending build without changing its frozen scope."""
    if resume:
        stage = Path(resume).resolve()
        if stage.parent != (root / kind).resolve() or not stage.name.startswith(".pending-"):
            raise ValueError("Resume must identify a pending build of the selected kind")
        saved = archive.read_json(stage / "settings.json")
        if any(saved.get(key) != value for key, value in settings.items() if value is not None):
            raise ValueError("Resume settings differ from the pending build")
        return stage, stage.name.removeprefix(".pending-"), saved
    stage, identifier = archive.begin(root, kind)
    archive.write_json(stage / "settings.json", settings)
    return stage, identifier, settings


def retain_code(stage):
    for path in ROOT.glob("*.py"):
        target = stage / "build_code" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    shutil.copyfile(Path(archive.__file__), stage / "build_code/archive.py")


def refresh_inventory(root, basin_root, flood_root, resume=None):
    """Inventory all CA locations, including inactive and non-USGS agency records."""
    stage, identifier, settings = build_stage(root, "inventory", resume, {"state_code": "06"})
    client = Client(stage)
    for name in ("monitoring-locations", "time-series-metadata", "continuous", "latest-continuous"):
        client.fetch(f"schemas/{name}", f"{BASE}/{name}/queryables", {"f": "json"})
    client.fetch("parameter_codes", f"{BASE}/parameter-codes/items",
                 {"f": "json", "filter": "id IN ('00060','00065')", "limit": 10})
    stations = client.collect("stations", "monitoring-locations", {"state_code": "06"})
    if not stations or any(str(f["properties"]["state_code"]) != "06" for f in stations):
        raise ValueError("Invalid statewide station inventory")
    station_ids = {str(f["id"]) for f in stations}
    archive.write_json(stage / "stations.geojson.gz", collection(stations))
    series = []
    # Metadata lacks a state filter. Enumerate both parameters nationally, then join
    # exact agency-qualified California IDs. This also retains nonspatial series.
    for parameter in PARAMETERS:
        for page in client.pages(f"series_{parameter}", "time-series-metadata", {"parameter_code": parameter}):
            series.extend(f for f in page if f["properties"]["monitoring_location_id"] in station_ids)
    archive.write_json(stage / "time_series.geojson.gz", collection(series))
    from data.usgs_water.relationships import build_inventory
    details = build_inventory(stage, stations, series, basin_root, flood_root)
    retain_code(stage)
    target, manifest = archive.publish(root, stage, identifier, "inventory", {
        "scope": "All monitoring locations with published state_code=06; stage/discharge series",
        "counts": {"stations": len(stations), "time_series": len(series), **details.pop("counts")}, **details,
    })
    write_review(root, target, manifest)
    return target


def normalize(feature, source):
    """Retain source strings, quality flags and series identity; convert no datum."""
    p = feature["properties"]
    fields = ("time_series_id", "monitoring_location_id", "parameter_code", "statistic_id", "time",
              "value", "unit_of_measure", "approval_status", "qualifier", "last_modified", "method_category")
    row = {key: (json.dumps(p.get(key), sort_keys=True) if isinstance(p.get(key), (dict, list))
                 else p.get(key)) for key in fields}
    row.update(source_feature_id=str(feature["id"]), source_collection=source)
    # Parquet schema stays stable even when a whole source page contains null flags.
    return {key: str(value) if value is not None else None for key, value in row.items()}


def parse_utc(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Observation boundaries require a timezone")
    return result.astimezone(timezone.utc)


def remove_owned_directory(path, parent):
    """Remove an obsolete USGS observation directory only within its checked parent."""
    resolved, expected_parent = Path(path).resolve(), Path(parent).resolve()
    if resolved.parent != expected_parent or Path(path).is_symlink():
        raise ValueError("Unsafe observation cleanup path")
    shutil.rmtree(resolved)


def discard_interval_files(stage):
    """Discard unfinished interval downloads when resuming a current-only build."""
    for parent in (stage / "raw", stage / "measurements"):
        if not parent.exists():
            continue
        for path in parent.glob("continuous_*"):
            if path.is_dir():
                remove_owned_directory(path, parent)
            else:
                if path.resolve().parent != parent.resolve():
                    raise ValueError("Unsafe interval cleanup path")
                path.unlink()


def refresh_observations(root, resume=None):
    """Replace the statewide latest-value snapshot; never accumulate level history."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    inventory_pointer = archive.read_json(root / "inventory.json")
    inventory, metadata = archive.open_generation(root, "inventory", inventory_pointer)
    station_ids = {f["id"] for f in archive.read_json(inventory / "stations.geojson.gz")["features"]}
    settings = {"state_code": "06", "inventory_pointer": inventory_pointer}
    stage, identifier, settings = build_stage(root, "observations", resume, settings)
    # Earlier unfinished builds may contain interval pages. They are not part of
    # the current-only product and must not enter a published manifest.
    discard_interval_files(stage)
    settings = {"state_code": "06", "inventory_pointer": inventory_pointer, "retention": "latest_values_only"}
    archive.write_json(stage / "settings.json", settings)
    client = Client(stage)
    counts, station_counts, series_counts = Counter(), Counter(), Counter()
    latest_rows, unmatched = [], Counter()
    for source in ("latest-continuous",):
        for parameter in PARAMETERS:
            params = {"state_code": "06", "parameter_code": parameter}
            path = stage / "measurements" / f"{source}_{parameter}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            writer = None
            try:
                for page in client.pages(f"{source}_{parameter}", source, params):
                    rows = [normalize(f, source) for f in page]
                    for row in rows:
                        if row["parameter_code"] != parameter:
                            raise ValueError("Source ignored parameter filter")
                        parse_utc(row["time"])  # Reject timestamps whose timezone cannot be interpreted.
                        station = row["monitoring_location_id"]
                        if station not in station_ids:
                            unmatched[station] += 1
                        station_counts[(station, source, parameter)] += 1
                        series_counts[(row["time_series_id"], source, parameter)] += 1
                    if rows:
                        table = pa.Table.from_pylist(rows, schema=pa.schema([(k, pa.string()) for k in rows[0]]))
                        if writer is None:
                            writer = pq.ParquetWriter(path, table.schema, compression="zstd")
                        writer.write_table(table)
                    counts[f"{source}_{parameter}"] += len(rows)
                    if source == "latest-continuous":
                        latest_rows.extend(rows)
            finally:
                if writer:
                    writer.close()
    from data.usgs_water.relationships import build_observations
    details = build_observations(stage, inventory, latest_rows, station_counts, series_counts)
    retain_code(stage)
    target, manifest = archive.publish(root, stage, identifier, "observations", {
        **settings, "counts": dict(counts), "unmatched_inventory_stations": dict(unmatched), **details,
        "coverage_note": "Latest available value per returned series; old last-known values retain their timestamp and stale status",
    })
    archive.open_generation(root, "observations")
    # Inventory and network archives are retained. Only obsolete measurement
    # generations and interrupted measurement builds are removed after success.
    for previous in (root / "observations").iterdir():
        if previous.is_dir() and previous.resolve() != target.resolve():
            if (previous / "settings.json").exists():
                remove_owned_directory(previous, root / "observations")
    write_review(root, target, manifest)
    return target


def write_review(root, target, manifest):
    """Expose current generation counts without rewriting any archived generation."""
    path = root / ("INVENTORY.md" if manifest["kind"] == "inventory" else "OBSERVATIONS.md")
    lines = [f"# California USGS {manifest['kind']}", "", f"Generated: {manifest['created_at_utc']}", "",
             f"[Verified generation manifest]({target.relative_to(root).as_posix()}/manifest.json)", "",
             "| Record category | Count |", "| --- | ---: |"]
    lines.extend(f"| {name} | {count:,} |" for name, count in manifest["counts"].items())
    if manifest["kind"] == "observations":
        lines += ["", f"Stations with returned latest readings: {manifest['stations_with_latest_values']:,}.",
                  "Only this measurement generation is retained; source retrieval times are recorded in its provenance table.",
                  f"[Current value provenance]({target.relative_to(root).as_posix()}/relationships/dataset_provenance.csv)"]
    lines += ["", "Counts describe source records, not distinct waterways or predicted flood areas.",
              "All nine Water Board review regions are available in the inventory generation's `regions/` folders.",
              "See [refresh and interpretation guidance](README.md).", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--mode", choices=("all", "inventory", "observations", "network", "link-review", "agency-review", "local-review", "routing"), default="all")
    parser.add_argument("--basin-directory", type=Path, default=ROOT.parent / "basin_plans")
    parser.add_argument("--flood-directory", type=Path, default=ROOT.parent / "flood_impacts")
    parser.add_argument("--resume", type=Path, help="Pending directory; requires a single --mode")
    parser.add_argument("--reuse-routing-sources", action="store_true",
                        help="Rebuild routing offline from matching verified source geometry and CalWater intersections")
    args = parser.parse_args()
    if args.resume and args.mode == "all":
        parser.error("Use a single mode for resume")
    if args.reuse_routing_sources and args.mode != "routing":
        parser.error("--reuse-routing-sources requires --mode routing")
    with archive.build_lock(args.directory):
        if args.mode in ("all", "inventory"):
            refresh_inventory(args.directory, args.basin_directory, args.flood_directory, args.resume)
        if args.mode in ("all", "observations"):
            refresh_observations(args.directory, args.resume)
        if args.mode in ("all", "network"):
            from data.usgs_water.network import refresh_network
            refresh_network(args.directory, args.basin_directory, args.resume)
        if args.mode == "link-review" or (args.mode == "all" and (args.directory / "routing.json").exists()):
            from data.usgs_water.link_review import refresh_link_review
            refresh_link_review(args.directory, args.resume)
        if args.mode == "agency-review" or (args.mode == "all" and (args.directory / "link_review.json").exists()):
            from data.usgs_water.agency_review import refresh_agency_review
            refresh_agency_review(args.directory, args.resume)
        if args.mode == "local-review" or (args.mode == "all" and (args.directory / "agency_review.json").exists()):
            from data.usgs_water.local_review import refresh_local_review
            refresh_local_review(args.directory, args.resume)
        if args.mode in ("all", "routing"):
            from data.usgs_water.routing import refresh_routing
            refresh_routing(args.directory, args.basin_directory, args.resume, args.reuse_routing_sources)


if __name__ == "__main__":
    main()
