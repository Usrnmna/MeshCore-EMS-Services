"""Statewide published station-to-network links and Basin Plan reach candidates."""

from collections import Counter, defaultdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from data.basin_plans import reference
from data.flood_impacts import archive
from data.usgs_water.client import Client
from data.usgs_water.relationships import read_csv, table, text

NLDI = "https://api.water.usgs.gov/nldi/linked-data/nwissite"


def refresh_network(root, basin_root, resume=None):
    """Query every statewide stage/discharge station by its published identifier.

    Four bounded workers retrieve independent records. A 404 is explicit source
    absence; transport errors fail publication and remain resumable.
    """
    from data.usgs_water.refresh import build_stage, retain_code
    pointer = archive.read_json(root / "inventory.json")
    inventory, im = archive.open_generation(root, "inventory", pointer)
    stations = archive.read_json(inventory / "stations.geojson.gz")["features"]
    ids = {str(f["id"]) for f in stations}
    settings = {"inventory_pointer": pointer, "basin_pointer": archive.read_json(Path(basin_root) / "sources.json")}
    stage, identifier, _ = build_stage(root, "network", resume, settings)
    client = Client(stage)
    client.fetch("nldi_docs", "https://api.water.usgs.gov/nldi/docs", as_json=False)
    queried = {f["properties"]["monitoring_location_id"] for f in
               archive.read_json(inventory / "time_series.geojson.gz")["features"]}
    def retrieve(sid):
        # Each worker owns its HTTP session and disjoint raw response paths.
        worker = Client(stage, attempts=3, timeout=(10, 30))
        try:
            data = worker.fetch(f"nldi_stations/{sid}", NLDI + "/" + sid,
                                {"f": "json"}, accepted_statuses=(404,))
            features = data.get("features", [])
            if data.get("status_code", data.get("status")) == 404:
                return []
            if len(features) > 1 or any(f["properties"]["identifier"] != sid for f in features):
                raise ValueError(f"Ambiguous NLDI identity: {sid}")
            if not features and "features" not in data:
                raise ValueError(f"Unexpected NLDI response: {sid}")
            return features
        finally:
            worker.session.close()
    selected = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for count, features in enumerate(pool.map(retrieve, sorted(queried)), 1):
            selected.extend(features)
            if count % 100 == 0 or count == len(queried):
                print(f"NLDI: {count:,}/{len(queried):,} statewide stations; {len(selected):,} matched", flush=True)
    archive.write_json(stage / "station_network_locations.geojson.gz", {"type": "FeatureCollection", "features": selected})
    matched = {f["properties"]["identifier"]: f["properties"] for f in selected}
    links = []
    by_reach = defaultdict(list)
    for station in stations:
        sid = str(station["id"])
        p = matched.get(sid, {})
        comid = text(p.get("comid"))
        row = {"station_id": sid, "station_name": station["properties"].get("monitoring_location_name", ""),
               "reach_id": comid, "reachcode": text(p.get("reachcode")), "measure": text(p.get("measure")),
               "mainstem_uri": text(p.get("mainstem")), "network": "USGS_NLDI_NHDPlus" if comid else "",
               "status": ("published_exact_identifier" if comid else "unresolved_no_published_NLDI_link"
                          if sid in queried else "not_queried_no_stage_discharge_series"),
               "source_url": NLDI + "/" + sid if p else NLDI}
        links.append(row)
        if row["reachcode"]:
            by_reach[row["reachcode"]].append(row)
    table(stage, "station_reach_links", links,
          ("station_id", "station_name", "reach_id", "reachcode", "measure", "mainstem_uri", "network", "status", "source_url"))
    snapshot, bm = reference.open_snapshot(basin_root)
    candidates = []
    for entry in bm["datasets"]:
        if entry["name"] not in ("ReachcodeTable", "Reachcodes"):
            continue
        for record in reference.iter_snapshot_records(snapshot, entry, bm):
            p = record.get("properties", record)
            lower = {key.lower(): value for key, value in p.items()}
            reachcode = text(lower.get("reachcode"))
            for link in by_reach.get(reachcode, []):
                candidates.append({"station_id": link["station_id"], "reach_id": link["reach_id"], "reachcode": reachcode,
                    "waterbody_key": text(lower.get("wb_refkey", lower.get("wbrefkey"))),
                    "dataset_key": entry["key"], "source_object_id": p.get(entry["object_id_field"]),
                    "region_plan_category": entry["category"],
                    "status": "exact_reachcode_candidate_segment_extent_and_network_vintage_unverified"})
    table(stage, "station_basin_plan_candidates", candidates,
          ("station_id", "reach_id", "reachcode", "waterbody_key", "dataset_key", "source_object_id", "region_plan_category", "status"))
    candidate_counts = Counter(r["station_id"] for r in candidates)
    coverage = [{"station_id": r["station_id"], "network_status": r["status"],
                 "basin_plan_candidates": candidate_counts[r["station_id"]],
                 "basin_plan_status": "candidates_require_review" if candidate_counts[r["station_id"]] else "no_exact_reachcode_match"}
                for r in links]
    table(stage, "station_link_coverage", coverage,
          ("station_id", "network_status", "basin_plan_candidates", "basin_plan_status"))
    # Keep the established directed tributary network as a relationship table.
    import shutil
    source = inventory / "relationships/flood_reference/flow_connections.csv"
    shutil.copyfile(source, stage / "relationships/flow_connections.csv")
    region_members = defaultdict(set)
    for row in read_csv(inventory / "relationships/station_region_plan.csv"):
        region_members[row["region"]].add(row["station_id"])
    for slug, station_ids in region_members.items():
        rows = [r for r in links if r["station_id"] in station_ids]
        archive.write_csv(stage / "regions" / slug / "station_reach_links.csv", rows, tuple(links[0]))
    retain_code(stage)
    target, manifest = archive.publish(root, stage, identifier, "network", {
        **settings, "enumeration": "Exact-ID NLDI query for every California station with stage/discharge metadata",
        "counts": {"california_stations_queried": len(queried), "california_network_locations": len(selected),
                   "stations_with_reach": sum(bool(r["reach_id"]) for r in links), "basin_plan_candidates": len(candidates)},
        "routing_limit": "Statewide station links; directed flow_connections remain the verified Russian River subset",
    })
    (root / "NETWORK.md").write_text("# Statewide station-to-waterway relationships\n\n"
        f"[Generation manifest]({target.relative_to(root).as_posix()}/manifest.json)\n\n"
        + "\n".join(f"- {key}: {value:,}" for key, value in manifest["counts"].items())
        + "\n\nPublished station links identify network seeds. The separate [statewide routing collection](ROUTING_METHODS.md) "
        "extends those seeds to downstream waterways and basin review candidates; neither collection predicts inundation. "
          "Basin Plan matches are reachcode candidates with segment extent and source vintage unresolved. "
          "The [supplemental review](LINK_REVIEW_METHODS.md) supplies separately labeled addresses "
          "to routing while preserving this primary station-link archive.\n", encoding="utf-8")
    return target
