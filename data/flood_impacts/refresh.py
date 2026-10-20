"""Acquire and rebuild a bounded, independently refreshable flood-reference pilot."""

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from shapely.geometry import box, shape
from shapely.ops import unary_union

if __package__:
    from . import archive, hydro
else:
    import archive
    import hydro

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY))
from data.basin_plans import reference as basin_reference
from data.basin_plans.organize import CALWATER_LEVELS, REGIONS

CATFIM = "https://maps.water.noaa.gov/server/rest/services/fim_libs/static_stage_based_catfim/FeatureServer"
NLDI = "https://api.water.usgs.gov/nldi/linked-data"
WFS = "https://api.water.usgs.gov/geoserver/wmadata/ows"
NWPS = "https://api.water.noaa.gov/nwps/v1/gauges"


def feature_collection(features):
    return {"type": "FeatureCollection", "features": features}


def validate_config(config):
    """Bound network requests and reject identifiers that cannot form source queries."""
    if not 0 < config["downstream_distance_km"] <= 500:
        raise ValueError("downstream_distance_km must be between 0 and 500")
    if not re.fullmatch(r"0[1-9]_[a-z_]+", config["region"]):
        raise ValueError("Use a Basin Plan region directory name")
    lids = [station["lid"] for station in config["stations"]]
    if not lids or len(lids) != len(set(lids)):
        raise ValueError("Stations must have unique LIDs")
    for station in config["stations"]:
        if not re.fullmatch(r"[A-Z0-9]{5}", station["lid"]) or not re.fullmatch(r"\d{8,15}", station["usgs_id"]):
            raise ValueError("Invalid NWPS/USGS identifier")


def acquire(stage, config):
    """Download complete configured map libraries and verified routing subsets."""
    where = "ahps_lid IN (" + ",".join("'" + s["lid"].lower() + "'" for s in config["stations"]) + ")"
    service = archive.fetch(stage, "catfim_service", CATFIM, {"f": "json"})
    archive.arcgis(stage, "california_site_inventory", CATFIM + "/0", "states LIKE '%CA%'")
    archive.arcgis(stage, "pilot_sites", CATFIM + "/0", where)
    layers = []
    for layer in service["layers"]:
        if layer["geometryType"] == "esriGeometryPolygon":
            print(f"Acquiring {layer['name']}", flush=True)
            archive.arcgis(stage, f"catfim_{layer['id']}", CATFIM + f"/{layer['id']}", where)
            layers.append(layer)
    archive.write_json(stage / "inputs/scenario_layers.json", layers)
    route_ids = set()
    for station in config["stations"]:
        lid, usgs = station["lid"], station["usgs_id"]
        gauge = archive.fetch(stage, f"gauge_{lid}", NWPS + "/" + lid)
        if gauge.get("usgsId") != usgs or gauge.get("lid") != lid:
            raise ValueError(f"NWPS station identity changed: {lid}")
        location = archive.fetch(stage, f"nldi_{lid}", NLDI + "/nwissite/USGS-" + usgs, {"f": "json"})
        if len(location["features"]) != 1 or location["features"][0]["properties"]["identifier"] != "USGS-" + usgs:
            raise ValueError(f"Ambiguous NLDI station: {lid}")
        route = archive.fetch(stage, f"route_{lid}", NLDI + "/nwissite/USGS-" + usgs + "/navigation/DD/flowlines",
                              {"f": "json", "distance": config["downstream_distance_km"]})
        route_ids.update(int(f["properties"]["nhdplus_comid"]) for f in route["features"])
    features = []
    for offset in range(0, len(route_ids), 100):
        ids = sorted(route_ids)[offset:offset + 100]
        response = archive.fetch(stage, f"flowlines_{offset:06}", WFS, {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": "wmadata:nhdflowline_network", "outputFormat": "application/json",
            "srsName": "EPSG:4326", "count": 1000,
            "CQL_FILTER": "comid IN (" + ",".join(map(str, ids)) + ")",
        })
        features.extend(response["features"])
    actual = [int(f["properties"]["comid"]) for f in features]
    if len(actual) != len(route_ids) or set(actual) != route_ids:
        raise ValueError("WFS flowline subset incomplete or duplicated")
    archive.write_json(stage / "inputs/flowlines.geojson.gz", feature_collection(features))


def local_inputs(stage, config, basin_directory):
    """Copy relevant original CalWater features and plan reach references after verification.

    The bounding envelope selects candidates only; final intersections use actual
    geometry. Every source iterator is exhausted to validate full ID membership.
    """
    snapshot, manifest = basin_reference.open_snapshot(basin_directory)
    objects = archive.read_json(stage / "inputs/flowlines.geojson.gz")["features"][:]
    for layer in archive.read_json(stage / "inputs/scenario_layers.json"):
        objects.extend(archive.read_json(stage / f"inputs/catfim_{layer['id']}.geojson.gz")["features"])
    geometries = [shape(f["geometry"]) for f in objects if f.get("geometry")]
    if not geometries:
        raise ValueError("No network or scenario geometry")
    bounds = box(min(g.bounds[0] for g in geometries), min(g.bounds[1] for g in geometries),
                 max(g.bounds[2] for g in geometries), max(g.bounds[3] for g in geometries))
    codes = {str(f["properties"]["reachcode"]) for f in objects if "reachcode" in f["properties"]}
    provenance, plan_rows = [], []
    for entry in manifest["datasets"]:
        calwater = entry["name"] in CALWATER_LEVELS
        plan = entry["name"] == "ReachcodeTable" and entry["category"].startswith("regions/" + config["region"])
        if not calwater and not plan:
            continue
        selected = []
        for record in basin_reference.iter_snapshot_records(snapshot, entry, manifest):
            if calwater:
                geometry = record.get("geometry")
                if geometry and bounds.intersects(box(*shape(geometry).bounds)):
                    selected.append(record)
            elif str(record.get("reachcode", record.get("REACHCODE", ""))) in codes:
                plan_rows.append({"dataset_key": entry["key"], "object_id": record[entry["object_id_field"]],
                                  "original_attributes": record})
        path = "inputs/" + entry["name"] + ".geojson.gz" if calwater else "inputs/plan_reach_references.json"
        if calwater:
            archive.write_json(stage / path, feature_collection(selected))
        provenance.append({"dataset_key": entry["key"], "name": entry["name"], "path": path,
                           "snapshot_id": manifest["snapshot_id"], "source_url": entry["source_url"],
                           "object_id_field": entry["object_id_field"], "source_record_count": entry["record_count"],
                           "selected_count": len(selected) if calwater else len(plan_rows),
                           "category": entry["category"], "source_sha256": entry["sha256"],
                           "completed_at_utc": entry.get("completed_at_utc", entry.get("completed_at", ""))})
    archive.write_json(stage / "inputs/plan_reach_references.json", plan_rows)
    archive.write_json(stage / "inputs/basin_provenance.json", {"source_pointer": archive.read_json(basin_directory / "sources.json"),
                       "selection_envelope_wgs84": list(bounds.bounds), "datasets": provenance})


def create_scenarios(stage, context):
    """Group same-layer/same-stage fragments without merging separate model versions."""
    groups = defaultdict(list)
    for layer in archive.read_json(stage / "inputs/scenario_layers.json"):
        for feature in archive.read_json(stage / f"inputs/catfim_{layer['id']}.geojson.gz")["features"]:
            p = feature["properties"]
            stage_value = p.get("interval_stage") if str(p.get("is_interval")).lower() == "true" else p.get("stage")
            key = (p["ahps_lid"].upper(), layer["id"], stage_value, p["stage_uni"],
                   p["magnitude"], p["fim_version"], p["model_version"])
            groups[key].append(feature)
    scenarios = []
    for key, features in sorted(groups.items()):
        lid, layer, stage_value, units, magnitude, fim_version, model_version = key
        if hydro.number(stage_value) is None:
            raise ValueError("Scenario has no valid stage")
        scenario_id = lid + "_" + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:12]
        polygons = [p for f in features for p in hydro.polygon_parts(context.project(f["geometry"], scenario_id))]
        footprint = unary_union(polygons)
        if footprint.is_empty:
            raise ValueError(f"Scenario has no polygon: {scenario_id}")
        scenario = {"scenario_id": scenario_id, "gauge_lid": lid, "stage": stage_value,
                    "stage_units": units, "category": magnitude, "fim_version": fim_version,
                    "model_version": model_version, "source_layer": layer,
                    "source_stage_field": "interval_stage" if "interval_stage" in features[0]["properties"] else "stage",
                    "source_object_ids": ";".join(str(f["properties"]["oid"]) for f in features),
                    "source_url": CATFIM + f"/{layer}",
                    "evidence_class": "experimental_static_stage_scenario", "event_valid_time": "",
                    "depth_status": "not_available", "area_m2": round(footprint.area, 3)}
        scenarios.append((scenario, footprint))
    return scenarios


def build_tables(stage, config):
    """Create inspectable relationship tables and spatial layers from archived inputs."""
    out = stage / "regions" / config["region"]
    tables = out / "relationships"
    context = hydro.GeometryContext(config["metric_crs"])
    network = archive.read_json(stage / "inputs/flowlines.geojson.gz")["features"]
    by_id = {hydro.identifier(f["properties"]["comid"]): f for f in network}
    edges = hydro.flow_connections(network)
    projected = {rid: context.project(f["geometry"], "reach:" + rid) for rid, f in by_id.items()}
    scenarios = create_scenarios(stage, context)
    provenance = archive.read_json(stage / "inputs/basin_provenance.json")
    basins, basin_features = [], []
    name_fields = ("hrname", "huname", "first_haname", "first_hsaname", "first_cdfspwname", "first_cdfpwsname")
    code_fields = ("hrc", "rbu", "rbua", "rbuas", "rbuasp", "rbuaspw")
    # The region polygons publish HRC but omit names. Use only a unique HRC/name
    # pair actually present in the archived hydrologic-unit source attributes.
    region_names = defaultdict(set)
    for feature in archive.read_json(stage / "inputs/CalWater_Hydrologic_Unit.geojson.gz")["features"]:
        props = {k.lower(): v for k, v in feature["properties"].items()}
        if props.get("hrc") and props.get("hrname"):
            region_names[str(props["hrc"])].add(props["hrname"])
    for dataset in provenance["datasets"]:
        if dataset["name"] not in CALWATER_LEVELS:
            continue
        level, title = CALWATER_LEVELS[dataset["name"]]
        index = int(level[:2]) - 1
        features = archive.read_json(stage / dataset["path"])["features"]
        for feature in features:
            p = {k.lower(): v for k, v in feature["properties"].items()}
            oid = feature["properties"][dataset["object_id_field"]]
            name = p.get(name_fields[index])
            evidence = name_fields[index] if name else "missing_name"
            candidates = region_names.get(str(p.get("hrc")), set())
            if not name and index == 0 and len(candidates) == 1:
                name, evidence = next(iter(candidates)), "unique_hydrologic_unit_hrc_hrname"
            basin = {"basin_id": dataset["dataset_key"] + ":" + str(oid), "calwater_level": level,
                     "basin_name": name or "Unnamed source feature", "basin_name_evidence": evidence,
                     "basin_code": p.get(code_fields[index], ""), "source_object_id": oid,
                     "source_dataset_key": dataset["dataset_key"]}
            boundary = context.project(feature["geometry"], basin["basin_id"])
            if boundary is not None:
                basins.append((basin, unary_union(hydro.polygon_parts(boundary))))
                basin_features.append({**feature, "properties": {**feature["properties"], **basin}})
        archive.write_json(stage / "calwater" / level / "boundaries.geojson.gz", feature_collection(features))
        archive.write_csv(stage / "calwater" / level / "catalog.csv", [{
            "title": title, "path": "boundaries.geojson.gz", "selected_features": len(features),
            "source_dataset_key": dataset["dataset_key"], "source_snapshot": dataset["snapshot_id"],
            "source_url": dataset["source_url"], "retrieved_at_utc": dataset["completed_at_utc"]}],
            ["title", "path", "selected_features", "source_dataset_key", "source_snapshot", "source_url", "retrieved_at_utc"])
        (stage / "calwater" / level / "README.md").write_text(
            f"# {title}\n\n[Catalog](catalog.csv) · [Boundaries](boundaries.geojson.gz)\n\n"
            "Original feature subset selected by the pilot envelope. All source attributes are retained.\n"
            "Boundaries are drainage categories, not flood extents. Source: "
            "[CalWater archive](../../../../../basin_plans/README.md).\n",
            encoding="utf-8")
    overlaps = []
    for rid, line in projected.items():
        if line is None:
            continue
        for basin, boundary in basins:
            if line.intersects(boundary):
                length = line.intersection(boundary).length
                if length > 0:
                    overlaps.append({"reach_id": rid, **basin, "intersection_length_m": round(length, 3),
                                     "evidence_class": "derived_spatial_overlap", "network": hydro.NETWORK})
    impacts, impact_features = hydro.basin_impacts(scenarios, basins, context)
    site_features = archive.read_json(stage / "inputs/pilot_sites.geojson.gz")["features"]
    sites = {f["properties"]["ahps_lid"].upper(): f["properties"] for f in site_features}
    if len(sites) != len(site_features):
        raise ValueError("Ambiguous CatFIM site records")
    gauge_links, downstream_basins, coverage = [], [], []
    for station in config["stations"]:
        lid = station["lid"]
        gauge = archive.read_json(stage / f"raw/gauge_{lid}.json.gz")
        nldi = archive.read_json(stage / f"raw/nldi_{lid}.json.gz")["features"][0]
        rid = hydro.identifier(nldi["properties"]["comid"])
        point = context.project({"type": "Point", "coordinates": [gauge["longitude"], gauge["latitude"]]}, lid)
        distance = point.distance(projected[rid]) if projected.get(rid) is not None else None
        source_code = str(nldi["properties"].get("reachcode", ""))
        code_matches = source_code == str(by_id[rid]["properties"]["reachcode"])
        status = "published_identifier_match" if (distance is not None and distance <= config["gauge_distance_review_m"]
                 and code_matches and hydro.identifier(gauge.get("reachId")) == rid) else "requires_manual_review"
        reachable = hydro.downstream(rid, edges)
        routed = {hydro.identifier(f["properties"]["nhdplus_comid"]) for f in
                  archive.read_json(stage / f"raw/route_{lid}.json.gz")["features"]}
        routing_status = "matches_nldi_downstream_subset" if reachable == routed else "network_subset_disagreement"
        gauge_links.append({"gauge_lid": lid, "gauge_name": gauge["name"], "usgs_id": station["usgs_id"],
                            "reach_id": rid, "reachcode": source_code, "network": hydro.NETWORK,
                            "distance_to_source_reach_m": round(distance, 3) if distance is not None else "",
                            "status": status, "routing_status": routing_status,
                            "route_distance_limit_km": config["downstream_distance_km"],
                            "source_url": NLDI + "/nwissite/USGS-" + station["usgs_id"]})
        for overlap in overlaps:
            if overlap["reach_id"] in reachable:
                downstream_basins.append({"gauge_lid": lid, **overlap,
                    "relation": "same_gauge_reach" if overlap["reach_id"] == rid else "downstream_reach_in_subset",
                    "link_status": status, "routing_status": routing_status,
                    "impact_status": "connectivity_only_inundation_unassessed"})
        site = sites.get(lid, {})
        coverage.append({"gauge_lid": lid, "mapped": site.get("mapped", "unknown"),
                         "source_status": site.get("status", "site absent from CatFIM"),
                         "scenario_count": sum(s["gauge_lid"] == lid for s, _ in scenarios),
                         "structures": "unassessed_no_operator_control_inventory",
                         "aqueduct_failure": "unassessed_no_operator_failure_scenarios",
                         "event_extent": "unassessed_static_reference_library_only"})
    crosswalk = []
    reachcodes = defaultdict(list)
    for rid, feature in by_id.items():
        reachcodes[str(feature["properties"]["reachcode"])].append(rid)
    for record in archive.read_json(stage / "inputs/plan_reach_references.json"):
        p = {k.lower(): v for k, v in record["original_attributes"].items()}
        for rid in reachcodes.get(str(p.get("reachcode")), []):
            crosswalk.append({"basin_plan_dataset_key": record["dataset_key"], "source_object_id": record["object_id"],
                              "wb_refkey": p.get("wb_refkey", p.get("wbrefkey", "")),
                              "reachcode": str(p["reachcode"]), "reach_id": rid, "network": hydro.NETWORK,
                              "status": "exact_reachcode_candidate_segment_extent_unverified"})
    rows = {
        "flow_connections": (edges, ["from_reach_id", "to_reach_id", "node_id", "network", "status", "downstream_divergence", "tidal", "evidence"]),
        "gauge_reach_links": (gauge_links, list(gauge_links[0])),
        "reach_calwater_overlaps": (overlaps, ["reach_id", "basin_id", "calwater_level", "basin_name", "basin_name_evidence", "basin_code", "source_object_id", "source_dataset_key", "intersection_length_m", "evidence_class", "network"]),
        "gauge_downstream_basins": (downstream_basins, ["gauge_lid", "reach_id", "basin_id", "calwater_level", "basin_name", "basin_name_evidence", "basin_code", "source_object_id", "source_dataset_key", "intersection_length_m", "evidence_class", "network", "relation", "link_status", "routing_status", "impact_status"]),
        "inundation_scenarios": ([s for s, _ in scenarios], ["scenario_id", "gauge_lid", "stage", "stage_units", "category", "fim_version", "model_version", "source_layer", "source_stage_field", "source_object_ids", "source_url", "evidence_class", "event_valid_time", "depth_status", "area_m2"]),
        "scenario_basin_impacts": (impacts, ["scenario_id", "basin_id", "calwater_level", "basin_name", "basin_name_evidence", "basin_code", "source_object_id", "source_dataset_key", "affected_area_m2", "basin_area_m2", "basin_fraction", "evidence_class", "depth_status", "event_valid_time", "geometry_status"]),
        "structure_connections": ([], ["structure_id", "from_reach_id", "to_reach_id", "structure_type", "operator", "operating_state", "valid_time", "source_url", "evidence_class"]),
        "basin_plan_reach_candidates": (crosswalk, ["basin_plan_dataset_key", "source_object_id", "wb_refkey", "reachcode", "reach_id", "network", "status"]),
        "coverage": (coverage, list(coverage[0])),
    }
    for name, (records, fields) in rows.items():
        archive.write_csv(tables / (name + ".csv"), records, fields)
    archive.write_json(out / "waterways.geojson.gz", feature_collection(network))
    archive.write_json(out / "calwater_review.geojson.gz", feature_collection(basin_features))
    archive.write_json(out / "inundation_scenarios.geojson.gz",
                       feature_collection([context.feature(g, s) for s, g in scenarios]))
    archive.write_json(out / "scenario_basin_portions.geojson.gz", feature_collection(impact_features))
    archive.write_json(out / "geometry_diagnostics.json", context.diagnostics)
    catalog = [{"dataset": name, "path": "relationships/" + name + ".csv", "rows": len(data[0]),
                "region": config["region"], "plan": config["plan"], "generated_at_utc": archive.utc_now(),
                "evidence": "derived; trace inputs through dataset_provenance.csv"} for name, data in rows.items()]
    source_rows = []
    for receipt_path in sorted(stage.glob("raw/*.receipt.json")):
        receipt = archive.read_json(receipt_path)
        source_rows.append({"dataset": receipt_path.name.removesuffix(".receipt.json"),
                            "source_url": receipt["url"], "retrieved_at_utc": receipt["retrieved_at_utc"],
                            "content_sha256": receipt["raw_sha256"], "hash_basis": "uncompressed_response_bytes",
                            "region": config["region"], "plan": config["plan"]})
    for source in provenance["datasets"]:
        source_rows.append({"dataset": source["dataset_key"], "source_url": source["source_url"],
                            "retrieved_at_utc": source["completed_at_utc"], "content_sha256": source["source_sha256"],
                            "hash_basis": "original_compressed_dataset_export",
                            "region": config["region"], "plan": config["plan"]})
    archive.write_csv(tables / "dataset_provenance.csv", source_rows, list(source_rows[0]))
    for name, filename, count in (("Named source waterways", "waterways.geojson.gz", len(network)),
                                  ("CalWater review boundaries", "calwater_review.geojson.gz", len(basin_features)),
                                  ("Static stage scenario footprints", "inundation_scenarios.geojson.gz", len(scenarios)),
                                  ("Scenario basin portions", "scenario_basin_portions.geojson.gz", len(impacts)),
                                  ("Source provenance", "relationships/dataset_provenance.csv", len(source_rows))):
        catalog.append({"dataset": name, "path": filename, "rows": count, "region": config["region"],
                        "plan": config["plan"], "generated_at_utc": archive.utc_now(),
                        "evidence": "see source provenance and method documentation"})
    archive.write_csv(out / "catalog.csv", catalog, list(catalog[0]))
    archive.write_csv(stage / "region_coverage.csv", [
        {"region": key, "name": title, "status": "configured_pilot" if key == config["region"] else "not_yet_assessed",
         "station_count": len(config["stations"]) if key == config["region"] else 0}
        for key, title in REGIONS.items()], ["region", "name", "status", "station_count"])
    (out / "README.md").write_text(
        f"# {config['title']}\n\n[Catalog](catalog.csv) · [Source provenance](relationships/dataset_provenance.csv)\n\n"
        f"{len(network)} source reaches; {len(scenarios)} static stage scenarios; {len(impacts)} scenario/basin portions.\n\n"
        "All intersections are derived. Connected basins are not flood extents. Each scenario is independent; "
        "do not sum nested CalWater levels. Unmapped gauges, structures, and aqueduct failures remain unassessed. "
        "The separate Basin Plan tributary table remains authoritative for its published associations.\n\n"
        "[Coverage gaps](relationships/coverage.csv) · [Gauge links](relationships/gauge_reach_links.csv) · "
        "[Directed connections](relationships/flow_connections.csv) · [Scenario portions](scenario_basin_portions.geojson.gz)\n",
        encoding="utf-8")
    return {"counts": {name: len(data[0]) for name, data in rows.items()},
            "geometry_diagnostics": len(context.diagnostics), "basin_source": provenance["source_pointer"],
            "network": hydro.NETWORK}


def refresh_static(root, config, basin_directory, offline=False):
    """Build a new static generation; offline mode replays the last verified raw inputs."""
    stage, identifier = archive.begin(root, "static")
    if offline:
        previous, manifest = archive.open_generation(root)
        if config != manifest["config"]:
            raise ValueError("Offline replay requires the archived configuration")
        for name in ("raw", "inputs"):
            shutil.copytree(previous / name, stage / name)
    else:
        acquire(stage, config)
        local_inputs(stage, config, basin_directory)
    archive.write_json(stage / "config.json", config)
    details = build_tables(stage, config)
    import pyproj
    import shapely
    details["software"] = {"python": sys.version, "shapely": shapely.__version__, "pyproj": pyproj.__version__}
    for name in ("archive.py", "hydro.py", "refresh.py", "report.py"):
        target = stage / "build_code" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(archive.ROOT / name, target)
    result = archive.publish(root, stage, identifier, "static", {"config": config, **details})
    publish_review(root, *result)
    return result


def publish_review(root, path, manifest):
    """Refresh a convenient review index after authoritative generation publication."""
    relative = path.relative_to(root).as_posix()
    region = manifest["config"]["region"]
    text = ("# Flood-impact reference review\n\n"
            f"Active static generation: `{manifest['generation']}`.\n\n"
            f"- [Regional pilot README]({relative}/regions/{region}/README.md)\n"
            f"- [Dataset catalog]({relative}/regions/{region}/catalog.csv)\n"
            f"- [Scenario-to-basin relationships]({relative}/regions/{region}/relationships/scenario_basin_impacts.csv)\n"
            f"- [Directed flow connections]({relative}/regions/{region}/relationships/flow_connections.csv)\n"
            f"- [Coverage by region]({relative}/region_coverage.csv)\n"
            f"- [Manifest and all checksums]({relative}/manifest.json)\n\n"
            "## Separate CalWater categories\n\n")
    for level, title in CALWATER_LEVELS.values():
        text += f"- [{title}]({relative}/calwater/{level}/README.md)\n"
    temporary = root / "REVIEW.download"
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(root / "REVIEW.md")


def refresh_observations(root):
    """Refresh raw gauge metadata and all returned stage/flow series independently."""
    static, manifest = archive.open_generation(root)
    stage, identifier = archive.begin(root, "observations")
    config = manifest["config"]
    measurements = []
    comparisons = []
    sites = {f["properties"]["ahps_lid"].upper(): f["properties"] for f in
             archive.read_json(static / "inputs/pilot_sites.geojson.gz")["features"]}
    region = static / "regions" / config["region"]
    with (region / "relationships/inundation_scenarios.csv").open(encoding="utf-8", newline="") as stream:
        scenarios = list(csv.DictReader(stream))
    with (region / "relationships/gauge_reach_links.csv").open(encoding="utf-8", newline="") as stream:
        gauge_links = {r["gauge_lid"]: r for r in csv.DictReader(stream)}
    for station in config["stations"]:
        lid = station["lid"]
        gauge = archive.fetch(stage, f"gauge_{lid}", NWPS + "/" + lid)
        if gauge.get("lid") != lid or gauge.get("usgsId") != station["usgs_id"]:
            raise ValueError(f"Gauge identity changed: {lid}")
        series = archive.fetch(stage, f"stageflow_{lid}", NWPS + "/" + lid + "/stageflow")
        now = datetime.now(timezone.utc)
        for kind, age_key in (("observed", "observation_max_age_hours"), ("forecast", "forecast_max_age_hours")):
            comparison = hydro.stage_comparison(gauge, series, sites.get(lid, {}), scenarios,
                                                kind, now, config[age_key])
            link = gauge_links[lid]
            if link["status"] != "published_identifier_match" or hydro.identifier(gauge.get("reachId")) != link["reach_id"]:
                comparison.update(status="gauge_reach_requires_review", lower_scenarios="", upper_scenarios="")
            comparisons.append(comparison)
        for kind in ("observed", "forecast"):
            block = series.get(kind) or {}
            for sample in block.get("data") or []:
                measurements.append({"gauge_lid": lid, "kind": kind,
                    "valid_time": sample.get("validTime", ""), "issued_time": block.get("issuedTime", ""),
                    "generated_time": sample.get("generatedTime", ""),
                    "primary_name": block.get("primaryName", ""), "primary_value": sample.get("primary"),
                    "primary_units": block.get("primaryUnits", ""),
                    "secondary_name": block.get("secondaryName", ""), "secondary_value": sample.get("secondary"),
                    "secondary_units": block.get("secondaryUnits", ""),
                    "quality_status": "source_qualifiers_retained_in_raw_no_independent_validation"})
    archive.write_csv(stage / "measurements.csv", measurements, ["gauge_lid", "kind", "valid_time", "issued_time",
                      "generated_time", "primary_name", "primary_value", "primary_units", "secondary_name",
                      "secondary_value", "secondary_units", "quality_status"])
    archive.write_csv(stage / "stage_scenario_links.csv", comparisons, list(comparisons[0]))
    details = {"config": config, "static_pointer": archive.read_json(root / "static.json"),
               "measurement_count": len(measurements)}
    return archive.publish(root, stage, identifier, "observations", details)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=archive.ROOT)
    parser.add_argument("--config", type=Path, default=archive.ROOT / "pilot.json")
    parser.add_argument("--basin-directory", type=Path, default=basin_reference.ROOT)
    parser.add_argument("--mode", choices=("all", "static", "observations"), default="all")
    parser.add_argument("--offline", action="store_true", help="Rebuild static outputs from verified cached inputs")
    args = parser.parse_args()
    config = archive.read_json(args.config)
    validate_config(config)
    if args.offline and args.mode != "static":
        parser.error("--offline requires --mode static")
    with archive.build_lock(args.directory):
        if args.mode in ("static", "all"):
            path, manifest = refresh_static(args.directory, config, args.basin_directory, args.offline)
            print(json.dumps({"published": str(path), **manifest["counts"]}, indent=2))
        if args.mode in ("observations", "all"):
            path, _ = refresh_observations(args.directory)
            print("Published observation generation: " + str(path))


if __name__ == "__main__":
    main()
