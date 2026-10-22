"""Acquire and verify isolated dataset generations without modifying active data.

The lifecycle manager owns locks, activation, receipts, rollback, and removal.
These adapters only write the supplied candidate directory. Source utilities run
in separate interpreters so their module paths and settings cannot leak between
collections. Any subprocess failure, including satellite warning status 2,
aborts the candidate instead of silently accepting partial source availability.
"""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time


DATASETS = frozenset({"ebmud", "california_state_parks", "wildfire", "landslide",
                      "basin_plans", "flood_impacts", "usgs_water", "satellites"})
EBMUD_LAYERS = frozenset({"trails", "recreation_points", "trail_endpoints", "peaks",
                        "additional_trails", "reservoir_annotations", "reservoirs",
                        "recreation_areas", "watershed_boundary", "ebrpd",
                        "ebrpd_display_2_jan_14", "adjacent_local_parks_jan_14"})
PARK_LAYERS = frozenset({"park_boundaries", "routes", "buildings", "structures",
                       "picnic_grounds", "campgrounds", "parking", "park_entry_points",
                       "sectors", "districts", "field_divisions"})
BASIN_CATEGORIES = frozenset({"hydrologic_boundaries/calwater_2_2_1", "statewide",
    "regions/01_north_coast", "regions/02_san_francisco_bay", "regions/03_central_coast",
    "regions/04_los_angeles", "regions/05_central_valley/sacramento_san_joaquin",
    "regions/05_central_valley/tulare", "regions/06_lahontan", "regions/07_colorado_river",
    "regions/08_santa_ana", "regions/09_san_diego"})


def read_json(path):
    """Read UTF-8 JSON; decoding failures invalidate the candidate."""
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    """Write candidate metadata without changing timestamps inside source data."""
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def safe_path(root, relative):
    """Reject absolute paths, traversal, and links outside the collection."""
    root = Path(root).resolve()
    relative = Path(relative)
    target = (root / relative).resolve()
    if relative.is_absolute() or target == root or not target.is_relative_to(root):
        raise ValueError("Dataset path leaves its collection: " + str(relative))
    return target


def digest(path):
    """Hash large archives incrementally rather than loading them into memory."""
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def verify_file(path, metadata):
    """Require a manifest checksum and, when recorded, the exact byte count."""
    if (digest(path) != metadata["sha256"] or
            ("byte_count" in metadata and path.stat().st_size != metadata["byte_count"])):
        raise ValueError("Dataset checksum or size mismatch: " + str(path))


def copy_tree(source, destination):
    """Copy files without hard links; reject symlinks and retain source mtimes."""
    source = Path(source)
    if not source.is_dir() or source.is_symlink():
        raise ValueError("Missing or linked dataset seed: " + str(source))
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("Dataset seeds must not contain symbolic links")
        relative = path.relative_to(source)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        target = safe_path(destination, relative)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def run_script(payload, relative, *arguments):
    """Run a shipped acquisition utility and propagate every nonzero status."""
    script = safe_path(payload, relative)
    # Several water validators use package imports without altering sys.path.
    # Module execution makes their payload-root package imports deterministic.
    command = ([sys.executable, "-m", ".".join(Path(relative).with_suffix("").parts)]
               if Path(relative).parts[0] == "data" else [sys.executable, str(script)])
    subprocess.run([*command, *(str(value) for value in arguments)], cwd=payload, check=True)


def worker(action, dataset, directory, payload, dependencies):
    """Isolate legacy import names while sharing the maintained implementations."""
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", action,
                    dataset, str(directory), str(payload),
                    json.dumps({name: str(path) for name, path in dependencies.items()})],
                   cwd=payload, check=True)


def require_dataset(dataset):
    if dataset not in DATASETS:
        raise ValueError("Unknown dataset: " + dataset)


def acquire(dataset, destination, payload, dependencies, previous=None, update=False, resume=False):
    """Populate an isolated candidate; never remove or write previous/dependencies.

    Curated Parks and landslide snapshots come from the current installer seed.
    Network datasets refresh into the candidate. Resume retains failed artifacts;
    only explicitly checkpointed USGS phases are skipped.
    """
    require_dataset(dataset)
    destination, payload = Path(destination).resolve(), Path(payload).resolve()
    protected = [Path(path).resolve() for path in dependencies.values()]
    if previous is not None:
        protected.append(Path(previous).resolve())
    if any(destination == path or destination.is_relative_to(path) or path.is_relative_to(destination)
           for path in protected):
        raise ValueError("Candidate overlaps an active or dependency collection")
    destination.mkdir(parents=True, exist_ok=True)
    if not resume and any(destination.iterdir()):
        raise ValueError("Acquisition requires an empty candidate directory")
    if previous is not None and not update and not resume:
        copy_tree(previous, destination)
        if dataset == "usgs_water":
            worker("index", dataset, destination, payload, dependencies)
        return
    if dataset in {"ebmud", "california_state_parks", "wildfire", "landslide"}:
        if not resume:
            source = previous if dataset == "ebmud" and previous else payload / "seeds" / dataset
            copy_tree(source, destination)
        if update and dataset in {"ebmud", "wildfire"}:
            worker("acquire", dataset, destination, payload, dependencies)
    elif dataset == "basin_plans":
        arguments = ["--directory", destination]
        pending = sorted((destination / "snapshots").glob(".pending-*"))
        if resume and len(pending) == 1:
            arguments += ["--resume", pending[0].name.removeprefix(".pending-")]
        elif resume and len(pending) > 1:
            raise ValueError("Ambiguous Basin Plan pending snapshots")
        run_script(payload, "data/basin_plans/refresh.py", *arguments)
        if previous is not None:
            _require_basin_coverage(destination, Path(previous))
    elif dataset == "flood_impacts":
        run_script(payload, "data/flood_impacts/refresh.py", "--directory", destination,
                   "--config", payload / "data/flood_impacts/pilot.json", "--mode", "static",
                   "--basin-directory", dependencies["basin_plans"])
    elif dataset == "usgs_water":
        _acquire_water(destination, payload, dependencies, resume)
    else:
        if previous is not None and not resume:
            copy_tree(previous, destination)
        worker("acquire", dataset, destination, payload, dependencies)


def _acquire_water(destination, payload, dependencies, resume):
    """Build reviewed water generations in dependency order, then their index."""
    checkpoint = destination / "acquisition-progress.json"
    pins = {name: str(Path(path).resolve()) for name, path in dependencies.items()}
    completed = []
    if resume and checkpoint.exists():
        saved = read_json(checkpoint)
        if saved["dependencies"] != pins:
            raise ValueError("Cannot resume water acquisition with changed dependencies")
        completed = saved["completed"]
    phases = ("inventory", "observations", "network", "routing", "link-review",
              "agency-review", "local-review", "routing-reviewed")
    for phase in phases:
        if phase in completed:
            continue
        mode = "routing" if phase == "routing-reviewed" else phase
        args = ["--directory", destination, "--mode", mode,
                "--basin-directory", dependencies["basin_plans"],
                "--flood-directory", dependencies["flood_impacts"]]
        if phase == "routing-reviewed":
            args.append("--reuse-routing-sources")
        pending = sorted((destination / mode.replace("-", "_")).glob(".pending-*"))
        if resume and len(pending) == 1:
            args += ["--resume", pending[0]]
        elif resume and len(pending) > 1:
            raise ValueError("Ambiguous pending water phase: " + phase)
        run_script(payload, "data/usgs_water/refresh.py", *args)
        if phase == "local-review":
            _require_water_sources(destination)
        completed.append(phase)
        write_json(checkpoint, {"dependencies": pins, "completed": completed})
    worker("index", "usgs_water", destination, payload, dependencies)


def _require_water_sources(directory):
    """Reject newly built metadata with failed provider retrievals.

    Legacy import validation remains read-only and accepts previously reviewed
    alternative-source evidence. A new acquisition must not replace that useful
    evidence with an incomplete refresh, even when the legacy utility permits it.
    """
    pointer = read_json(directory / "local_review.json")
    path = safe_path(directory, pointer["manifest_path"])
    verify_file(path, pointer)
    manifest = read_json(path)
    failures = manifest.get("source_status_counts", {}).get("retrieval_failed", 0)
    if failures or manifest.get("source_rule_audit_summary", {}).get("retrieval_failure_sources"):
        raise ValueError("Water metadata providers failed; the previous dataset must remain active")


def _basin_manifest(directory):
    """Read only a checksum-bound snapshot manifest, including for baseline checks."""
    pointer = read_json(directory / "sources.json")
    path = safe_path(directory, pointer["manifest_path"])
    verify_file(path, {"sha256": pointer["manifest_sha256"]})
    manifest = read_json(path)
    if not manifest.get("complete") or manifest["snapshot_id"] != pointer["snapshot_id"]:
        raise ValueError("Incomplete Basin Plan snapshot")
    return manifest


def _require_basin_coverage(directory, previous):
    """Reject silent disappearance of a previously installed provider or layer.

    Provider membership changes require a reviewed installer update instead of
    treating a successful but partial discovery response as a complete archive.
    Record counts are not fixed: legitimate source edits can change them.
    """
    current, old = _basin_manifest(directory), _basin_manifest(previous)
    for field, key in (("datasets", "key"), ("items", "id")):
        missing = {entry[key] for entry in old[field]} - {entry[key] for entry in current[field]}
        if missing:
            raise ValueError("Basin Plan discovery lost previously installed " + field + ": " + ", ".join(sorted(missing)))


def validate(dataset, directory, payload, dependencies):
    """Require source integrity, nonempty usable content, and dependency consistency."""
    require_dataset(dataset)
    worker("validate", dataset, Path(directory), Path(payload), dependencies)


def geojson(path, expected=None, allow_null=False):
    """Validate complete, nonempty collections and usable source geometries."""
    from shapely.geometry import shape
    document = read_json(path)
    features = document.get("features")
    if (document.get("type") != "FeatureCollection" or not isinstance(features, list)
            or not features or document.get("exceededTransferLimit")
            or (document.get("properties") or {}).get("exceededTransferLimit")
            or (expected is not None and len(features) != expected)):
        raise ValueError("Empty, truncated, or inconsistent GeoJSON: " + str(path))
    for feature in features:
        if feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
            raise ValueError("Invalid GeoJSON feature")
        geometry = feature.get("geometry")
        if geometry is None and allow_null:
            continue
        parsed = shape(geometry)
        if parsed.is_empty or not parsed.is_valid:
            raise ValueError("Invalid or empty dataset geometry: " + str(path))
    return features


def _validate_gis(dataset, directory):
    manifest = read_json(directory / "sources.json")
    entries = manifest["datasets"]
    required = EBMUD_LAYERS if dataset == "ebmud" else PARK_LAYERS
    if not required.issubset(entries):
        raise ValueError("Required GIS layers are missing")
    for entry in entries.values():
        path = safe_path(directory, entry["path"])
        verify_file(path, entry)
        geojson(path, entry["feature_count"], allow_null=dataset == "ebmud")
        repair = entry.get("geometry_repair")
        if repair:
            verify_file(safe_path(directory, repair["original_path"]),
                        {"sha256": repair["original_sha256"],
                         "byte_count": repair["original_byte_count"]})
    for entry in manifest.get("service_resources", {}).values():
        verify_file(safe_path(directory, entry["path"]), entry)
    if dataset == "california_state_parks" and not manifest.get("files"):
        raise ValueError("Parks source-file manifest is missing")
    for relative, metadata in manifest.get("files", {}).items():
        verify_file(safe_path(directory, relative), metadata)


def _validate_landslide(directory):
    manifest = read_json(directory / "manifest.json")
    required = {"stations.json", "california.geojson", "nevada.geojson"}
    if not required.issubset(manifest["sha256"]):
        raise ValueError("Landslide reference manifest is incomplete")
    for relative, checksum in manifest["sha256"].items():
        verify_file(safe_path(directory, relative), {"sha256": checksum})
    stations = read_json(directory / "stations.json")
    if not stations or len(stations) != manifest["station_count"]:
        raise ValueError("Landslide station catalog is empty or incomplete")
    identifiers = set()
    for station in stations:
        coordinates = station["coordinates"]
        if (station["id"] in identifiers or not station["url"].startswith("https://")
                or len(coordinates) != 2 or not -180 <= coordinates[0] <= 180
                or not -90 <= coordinates[1] <= 90):
            raise ValueError("Invalid reviewed landslide station")
        identifiers.add(station["id"])
    for name in ("california", "nevada"):
        geojson(directory / (name + ".geojson"), 1)


def _validate_satellites(directory):
    report = read_json(directory / "coverage.json")
    if report.get("warnings"):
        raise ValueError("Satellite source failure: " + str(report["warnings"]))
    for key in ("source_satellites", "source_transmitters", "selected_satellites",
                "selected_operations", "orbital_records_loaded"):
        if not isinstance(report.get(key), int) or report[key] <= 0:
            raise ValueError("Empty satellite source or result: " + key)
    with closing(sqlite3.connect((directory / "satellites.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Satellite database integrity failure")
        for table in ("satellites", "operations", "orbits"):
            if db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] <= 0:
                raise ValueError("Empty satellite database table: " + table)
    receipts = report.get("source_receipts")
    if not receipts:
        raise ValueError("Satellite source receipts missing")
    for receipt in receipts:
        key = hashlib.sha256(receipt["url"].encode()).hexdigest()
        verify_file(directory / "raw" / (key + ".body"), receipt)


def _validate_archive(dataset, directory, payload, dependencies):
    from data.flood_impacts import archive
    if dataset == "basin_plans":
        from data.basin_plans import reference, organize
        _, manifest = reference.open_snapshot(directory)
        if not manifest.get("datasets") or not sum(entry["record_count"] for entry in manifest["datasets"]):
            raise ValueError("Basin Plan collection is empty")
        if not BASIN_CATEGORIES.issubset({entry["category"] for entry in manifest["datasets"]}):
            raise ValueError("Basin Plan discovery is missing a required regional category")
        reference.verify_files(directory, records=True)
        organize.verify_organization(directory)
        return
    if dataset == "flood_impacts":
        from data.flood_impacts.validate import validate as validate_flood
        _, manifest = archive.open_generation(directory, "static")
        required_counts = ("flow_connections", "gauge_reach_links", "inundation_scenarios",
                           "gauge_downstream_basins", "scenario_basin_impacts", "coverage")
        if not manifest.get("files") or any(manifest.get("counts", {}).get(key, 0) <= 0 for key in required_counts):
            raise ValueError("Flood reference is empty")
        if manifest["basin_source"] != read_json(dependencies["basin_plans"] / "sources.json"):
            raise ValueError("Flood reference uses a different Basin Plan generation")
        validate_flood(directory, include_observations=False)
        return
    manifests = {}
    for kind in ("inventory", "observations", "network", "routing", "link_review", "agency_review", "local_review"):
        _, manifests[kind] = archive.open_generation(directory, kind)
        if not manifests[kind].get("files"):
            raise ValueError("Water generation has no artifacts: " + kind)
    inventory = manifests["inventory"]
    if inventory["counts"]["stations"] <= 0 or inventory["counts"]["time_series"] <= 0:
        raise ValueError("Water station inventory or series are empty")
    if manifests["observations"]["stations_with_latest_values"] <= 0:
        raise ValueError("No water observations returned; retain previous dataset")
    for dependency, field, filename in (("basin_plans", "basin_pointer", "sources.json"),
                                        ("flood_impacts", "flood_pointer", "static.json")):
        if inventory[field] != read_json(dependencies[dependency] / filename):
            raise ValueError("Water generation dependency mismatch: " + dependency)
    for kind in ("routing", "link_review", "agency_review", "local_review"):
        run_script(payload, "data/usgs_water/validate_" + kind + ".py", "--directory", directory)
    with closing(sqlite3.connect((directory / "water_index.sqlite3").as_uri() + "?mode=ro", uri=True)) as index:
        if index.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Water spatial index integrity failure")
        metadata = {key: json.loads(value) for key, value in index.execute("SELECT key,value FROM metadata")}
        for kind in ("routing", "inventory"):
            if metadata[kind] != read_json(directory / (kind + ".json")):
                raise ValueError("Water spatial index generation mismatch")
        if index.execute("SELECT COUNT(*) FROM stations").fetchone()[0] != inventory["counts"]["stations"]:
            raise ValueError("Water spatial index station count mismatch")


def _worker(action, dataset, directory, payload, dependencies):
    """Dispatch only within a fresh process with paths rooted in this payload."""
    sys.path.insert(0, str(payload))
    sys.path.insert(0, str(payload / "meshcore_mqtt_service"))
    if action == "index":
        from scripts.water_local import build_index
        build_index({}, directory / "water_index.sqlite3", collection=directory)
    elif action == "acquire" and dataset == "ebmud":
        sys.path.insert(0, str(payload / "data/ebmud"))
        from refresh_geojson import refresh
        from repair_geojson import repair
        refresh(directory)
        repair(directory)
    elif action == "acquire" and dataset == "wildfire":
        from scripts.wildfire_refresh import boundaries
        from scripts.wildfire_sources import Client, STATE_URL, ZONE_URL
        from scripts.wildfire_store import encode
        zones, _ = boundaries(Client(240))
        if not zones:
            raise ValueError("Fire-weather zone source returned no zones")
        raw = (encode({"type": "FeatureCollection", "features": zones}) + "\n").encode()
        (directory / "zones.geojson").write_bytes(raw)
        write_json(directory / "manifest.json", {"schema_version": 1, "retrieved_at": time.time(),
                   "source": ZONE_URL, "california_reference": STATE_URL, "feature_count": len(zones),
                   "sha256": hashlib.sha256(raw).hexdigest(), "zone_ids": sorted(zone["id"] for zone in zones),
                   "selection": "Whole NWS fire-zone polygons intersecting California; no state clipping."})
    elif action == "acquire" and dataset == "satellites":
        settings = read_json(payload / "satellite_database/settings.json")
        settings.update(database=str(directory / "satellites.sqlite3"),
                        cache_directory=str(directory / "raw"), export_directory=str(directory))
        # A tiny positive lifetime forces online revalidation of copied cache bytes.
        settings["cache_hours"] = 1e-12
        write_json(directory / "settings.json", settings)
        run_script(payload, "satellite_database/satellite_db.py", "--settings", directory / "settings.json",
                   "refresh", "--overrides", payload / "satellite_database/operator_overrides.json")
    elif action == "validate":
        if dataset in {"ebmud", "california_state_parks"}:
            _validate_gis(dataset, directory)
        elif dataset == "landslide":
            _validate_landslide(directory)
        elif dataset == "wildfire":
            manifest = read_json(directory / "manifest.json")
            verify_file(directory / "zones.geojson", manifest)
            zones = geojson(directory / "zones.geojson", manifest["feature_count"])
            ids = [zone["id"] for zone in zones]
            if len(ids) != len(set(ids)) or sorted(ids) != manifest["zone_ids"]:
                raise ValueError("Fire-weather zone identifiers disagree with manifest")
        elif dataset == "satellites":
            _validate_satellites(directory)
        else:
            _validate_archive(dataset, directory, payload, dependencies)
    else:
        raise ValueError("Unsupported adapter action")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("acquire", "validate", "index"), required=True)
    parser.add_argument("dataset", choices=sorted(DATASETS))
    parser.add_argument("directory", type=Path)
    parser.add_argument("payload", type=Path)
    parser.add_argument("dependencies")
    args = parser.parse_args()
    _worker(args.worker, args.dataset, args.directory.resolve(), args.payload.resolve(),
            {name: Path(path) for name, path in json.loads(args.dependencies).items()})
