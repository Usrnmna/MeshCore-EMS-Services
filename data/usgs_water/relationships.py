"""Source-key joins and explicitly derived statewide CalWater membership tables."""

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import shutil

import numpy as np
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from data.basin_plans import reference
from data.basin_plans.organize import CALWATER_LEVELS, REGIONS
from data.flood_impacts import archive


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def table(stage, name, rows, fields):
    archive.write_csv(stage / "relationships" / (name + ".csv"), rows, fields)


def text(value):
    return "" if value is None else str(value)


def station_row(feature):
    p = feature["properties"]
    return {"station_id": str(feature["id"]), "station_name": p.get("monitoring_location_name", ""),
            "agency_code": p.get("agency_code", ""), "site_type": p.get("site_type", ""),
            "usgs_huc": p.get("hydrologic_unit_code", "")}


def calwater_memberships(stage, stations, basin_root):
    """Intersect station points with each published CalWater level, preserving ties.

    Region/plan review attribution comes from the containing HU's published rb
    and hbpaname fields. It is not an independently surveyed regulatory boundary.
    """
    snapshot, manifest = reference.open_snapshot(basin_root)
    points = [shape(f["geometry"]) if f.get("geometry") else None for f in stations]
    memberships, region_links, catalog = [], [], []
    diagnostic = []
    hierarchy = {"01_hydrologic_regions": ("hrc", "hrc"),
                 "02_hydrologic_units": ("rbu", "huname"),
                 "03_hydrologic_areas": ("rbua", "first_haname"),
                 "04_hydrologic_subareas": ("rbuas", "first_hsaname"),
                 "05_super_planning_watersheds": ("rbuasp", "first_cdfspwname"),
                 "06_planning_watersheds": ("rbuaspw", "first_cdfpwsname")}
    for entry in manifest["datasets"]:
        if entry["name"] not in CALWATER_LEVELS:
            continue
        level, title = CALWATER_LEVELS[entry["name"]]
        features = list(reference.iter_snapshot_records(snapshot, entry, manifest))
        geometries = []
        for f in features:
            geometry = shape(f["geometry"]) if f.get("geometry") else None
            if geometry is not None and not geometry.is_valid:
                diagnostic.append({"dataset_key": entry["key"], "object_id": f["properties"][entry["object_id_field"]],
                                   "action": "derived_make_valid_only_original_preserved"})
                geometry = shapely.make_valid(geometry)
            geometries.append(geometry)
        # Test prepared polygons first: California's detailed coastlines make
        # repeated unprepared point-versus-polygon predicates prohibitively slow.
        polygon_array = np.asarray(geometries, dtype=object)
        point_array = np.asarray(points, dtype=object)
        shapely.prepare(polygon_array)
        tree = STRtree(geometries)
        candidates = tree.query(point_array)
        mask = shapely.intersects(polygon_array[candidates[1]], point_array[candidates[0]])
        matches = candidates[:, mask]
        counts = Counter(int(index) for index in matches[0])
        basin_counts = Counter(int(index) for index in matches[1])
        code_field, name_field = hierarchy[level]
        level_rows = []
        for si, bi in zip(*matches):
            station, p = stations[int(si)], features[int(bi)]["properties"]
            row = {"station_id": str(station["id"]), "basin_id": f"{entry['key']}:{p[entry['object_id_field']]}",
                   "level": level, "basin_code": text(p.get(code_field)), "basin_name": text(p.get(name_field)),
                   "source_dataset_key": entry["key"], "source_object_id": p[entry["object_id_field"]],
                   "status": "multiple_spatial_matches" if counts[int(si)] > 1 else "unique_spatial_match",
                   "method": "derived_point_intersects_polygon", "match_count": counts[int(si)]}
            level_rows.append(row)
            if level == "02_hydrologic_units":
                rb = text(p.get("rb"))
                region = next((slug for slug in REGIONS if slug[:2] == rb.zfill(2)), "unassigned")
                region_links.append({"station_id": str(station["id"]), "region": region,
                                     "plan": p.get("hbpaname", ""), "basin_id": row["basin_id"],
                                     "method": "derived_HU_point_membership_then_published_rb_hbpaname",
                                     "status": row["status"]})
        memberships.extend(level_rows)
        folder = stage / "calwater" / level
        archive.write_csv(folder / "station_membership.csv", level_rows,
                          ("station_id", "basin_id", "level", "basin_code", "basin_name", "source_dataset_key",
                           "source_object_id", "status", "method", "match_count"))
        basins = [{"basin_id": f"{entry['key']}:{f['properties'][entry['object_id_field']]}",
                   "basin_code": text(f["properties"].get(code_field)),
                   "basin_name": text(f["properties"].get(name_field)), "station_count": basin_counts[i]}
                  for i, f in enumerate(features)]
        archive.write_csv(folder / "catalog.csv", basins, ("basin_id", "basin_code", "basin_name", "station_count"))
        (folder / "README.md").write_text(f"# {title}\n\nAll {len(features):,} published polygons are cataloged. "
            "Station membership is a derived point intersection, not a contributing drainage area or a flood extent. "
            "Boundary matches remain multiple. Geometry remains in the pinned Basin Plan snapshot.\n", encoding="utf-8")
        catalog.append({"level": level, "basins": len(features), "memberships": len(level_rows)})
    assigned = {r["station_id"] for r in region_links}
    region_links.extend({"station_id": str(f["id"]), "region": "unassigned", "plan": "", "basin_id": "",
                         "method": "no_containing_calwater_HU", "status": "unresolved"}
                        for f in stations if str(f["id"]) not in assigned)
    table(stage, "station_region_plan", region_links,
          ("station_id", "region", "plan", "basin_id", "method", "status"))
    archive.write_json(stage / "geometry_diagnostics.json", diagnostic)
    return memberships, region_links, catalog


def build_inventory(stage, stations, series, basin_root, flood_root):
    """Build statewide relationships; pin and preserve the existing tributary tables."""
    series_rows, series_counts = [], Counter()
    for feature in series:
        p = feature["properties"]
        series_counts[p["monitoring_location_id"]] += 1
        series_rows.append({"station_id": p["monitoring_location_id"], "time_series_id": str(feature["id"]),
            **{k: p.get(k) for k in ("parameter_code", "parameter_name", "unit_of_measure", "statistic_id",
              "computation_period_identifier", "computation_identifier", "primary", "begin", "end",
              "sublocation_identifier", "parent_time_series_id")}, "thresholds_json": json.dumps(p.get("thresholds"))})
    series_fields = ("station_id", "time_series_id", "parameter_code", "parameter_name", "unit_of_measure",
                     "statistic_id", "computation_period_identifier", "computation_identifier", "primary", "begin",
                     "end", "sublocation_identifier", "parent_time_series_id", "thresholds_json")
    table(stage, "station_time_series", series_rows, series_fields)
    memberships, region_links, calwater_catalog = calwater_memberships(stage, stations, basin_root)
    table(stage, "station_calwater_membership", memberships,
          ("station_id", "basin_id", "level", "basin_code", "basin_name", "source_dataset_key",
           "source_object_id", "status", "method", "match_count"))
    station_map = {str(f["id"]): station_row(f) for f in stations}
    region_members = defaultdict(set)
    for row in region_links:
        region_members[row["region"]].add(row["station_id"])
    coverage_rows = []
    for slug, label in {**REGIONS, "unassigned": "Unassigned regional review"}.items():
        selected = region_members[slug]
        folder = stage / "regions" / slug
        rows = [{**station_map[s], "stage_discharge_series": series_counts[s]} for s in sorted(selected)]
        archive.write_csv(folder / "stations.csv", rows,
                          ("station_id", "station_name", "agency_code", "site_type", "usgs_huc", "stage_discharge_series"))
        archive.write_json(folder / "stations.geojson.gz", {"type": "FeatureCollection",
                          "features": [f for f in stations if str(f["id"]) in selected]})
        regional_series = [row for row in series_rows if row["station_id"] in selected]
        archive.write_csv(folder / "station_time_series.csv", regional_series, series_fields)
        catalog_rows = [{"title": "Monitoring locations", "path": "stations.csv", "records": len(rows)},
                        {"title": "Stage and discharge time series", "path": "station_time_series.csv", "records": len(regional_series)},
                        {"title": "Station geometry and original attributes", "path": "stations.geojson.gz", "records": len(rows)}]
        archive.write_csv(folder / "catalog.csv", catalog_rows, ("title", "path", "records"))
        (folder / "README.md").write_text(f"# {label}\n\nCalifornia monitoring locations attributed through "
            "CalWater HU point membership and published Water Board region codes. Multiple region matches are retained; "
            "regional counts must not be summed as unique stations. `station_time_series.csv` distinguishes instantaneous, "
            "daily and annual series. Measurements join by exact station and series identifiers in the independently "
            "refreshed observations collection. The six CalWater categories remain separate under `../../calwater/`.\n",
            encoding="utf-8")
        coverage_rows.append({"region": slug, "stations": len(rows), "stations_with_series": sum(series_counts[s] > 0 for s in selected),
                              "series": len(regional_series)})
    archive.write_csv(stage / "region_coverage.csv", coverage_rows, ("region", "stations", "stations_with_series", "series"))
    # Pin existing immutable evidence; do not replace established relationships.
    basin_pointer = archive.read_json(Path(basin_root) / "sources.json")
    flood_pointer = archive.read_json(Path(flood_root) / "static.json")
    flood, fm = archive.open_generation(flood_root, "static", flood_pointer)
    source_tables = flood / "regions" / fm["config"]["region"] / "relationships"
    links = {"USGS-" + r["usgs_id"]: r for r in read_csv(source_tables / "gauge_reach_links.csv")}
    crosswalk, reaches, upstream = [], [], []
    for feature in stations:
        station = str(feature["id"])
        link = links.get(station)
        crosswalk.append({"station_id": station, "agency_code": feature["properties"]["agency_code"],
                          "station_number": feature["properties"]["monitoring_location_number"],
                          "nwps_lid": link["gauge_lid"] if link else "", "cdec_id": "",
                          "nwps_status": "published_exact_usgs_id" if link else "unresolved",
                          "cdec_status": "not_verified"})
        reaches.append({"station_id": station, "reach_id": link["reach_id"] if link else "",
                        "reachcode": link["reachcode"] if link else "", "network": link["network"] if link else "",
                        "status": "published_identifier_match" if link else "unresolved_no_verified_network_link",
                        "source_url": link["source_url"] if link else ""})
        p = feature["properties"]
        upstream.append({"station_id": station, "drainage_area_sq_mi": p.get("drainage_area"),
                         "contributing_drainage_area_sq_mi": p.get("contributing_drainage_area"),
                         "usgs_huc": p.get("hydrologic_unit_code"), "upstream_polygon_status": "not_delineated",
                         "note": "published_station_attributes_not_CalWater_point_membership"})
    table(stage, "station_identifiers", crosswalk,
          ("station_id", "agency_code", "station_number", "nwps_lid", "cdec_id", "nwps_status", "cdec_status"))
    table(stage, "station_reach_links", reaches, ("station_id", "reach_id", "reachcode", "network", "status", "source_url"))
    table(stage, "station_contributing_areas", upstream,
          ("station_id", "drainage_area_sq_mi", "contributing_drainage_area_sq_mi", "usgs_huc", "upstream_polygon_status", "note"))
    # Copies are hash-bound by this generation and retain original row semantics.
    target = stage / "relationships" / "flood_reference"
    target.mkdir(parents=True, exist_ok=True)
    for path in source_tables.glob("*.csv"):
        shutil.copyfile(path, target / path.name)
    org = Path(basin_root) / basin_pointer["organization_path"]
    archive.write_json(stage / "basin_relationship_references.json", {
        "source_pointer": basin_pointer, "organization_path": str(org.resolve()),
        "relationships": [{"path": str(p.relative_to(org)), **archive.digest(p)}
                          for p in org.rglob("*.csv") if "relationship" in str(p) or p.name == "waterway_links.csv"],
        "note": "Published parent/tributary attributions are distinct from directed flow_connections.csv",
    })
    dataset_rows = [{"dataset": "stations", "region": "California state_code=06", "plan": "multiple_or_unresolved",
                     "source": "https://api.waterdata.usgs.gov/ogcapi/v1/collections/monitoring-locations",
                     "retrieval_date": archive.utc_now(), "evidence": "raw/stations/*receipt.json"},
                    {"dataset": "time_series", "region": "California exact station-ID subset", "plan": "multiple_or_unresolved",
                     "source": "https://api.waterdata.usgs.gov/ogcapi/v1/collections/time-series-metadata",
                     "retrieval_date": archive.utc_now(), "evidence": "raw/series_*/*receipt.json"}]
    table(stage, "dataset_provenance", dataset_rows, ("dataset", "region", "plan", "source", "retrieval_date", "evidence"))
    return {"basin_pointer": basin_pointer, "flood_pointer": flood_pointer,
            "calwater_catalog": calwater_catalog,
            "counts": {"stations_with_stage_discharge_series": len(series_counts), "calwater_memberships": len(memberships),
                       "verified_reach_links": sum(bool(r["reach_id"]) for r in reaches)}}


def build_observations(stage, inventory, latest, station_counts, series_counts):
    """Make completeness, absent observations, metadata drift and aliases inspectable."""
    station_ids = [f["id"] for f in archive.read_json(inventory / "stations.geojson.gz")["features"]]
    series = {str(f["id"]): f["properties"] for f in archive.read_json(inventory / "time_series.geojson.gz")["features"]}
    rows = []
    for station in station_ids:
        rows.append({"station_id": station,
                     **{f"{label}_{parameter}": station_counts[(station, source, parameter)]
                        for label, source in (("latest", "latest-continuous"),)
                        for parameter in ("00060", "00065")}})
    table(stage, "station_measurement_coverage", rows,
          ("station_id", "latest_00060", "latest_00065"))
    fields = tuple(latest[0]) if latest else ("monitoring_location_id", "time_series_id", "time", "value")
    archive.write_csv(stage / "latest_measurements.csv", latest, fields)
    metadata_links = [{"time_series_id": sid, "source_collection": source, "parameter_code": parameter,
                       "records": count, "metadata_status": "exact_id_match" if sid in series else "missing_metadata"}
                      for (sid, source, parameter), count in sorted(series_counts.items())]
    table(stage, "measurement_series_links", metadata_links,
          ("time_series_id", "source_collection", "parameter_code", "records", "metadata_status"))
    aliases = {r["station_id"]: r["nwps_lid"] for r in read_csv(inventory / "relationships/station_identifiers.csv") if r["nwps_lid"]}
    lineage = [{"station_id": station, "nwps_lid": lid, "relationship": "same_published_USGS_station",
                "independent_measurement": "false", "observation_deduplication_key": "time_series_id + time",
                "note": "NWPS observation feed may relay USGS; forecasts remain separate"}
               for station, lid in aliases.items()]
    table(stage, "measurement_lineage", lineage,
          ("station_id", "nwps_lid", "relationship", "independent_measurement", "observation_deduplication_key", "note"))
    from data.usgs_water.analysis import write_conditions, applicable_thresholds
    from datetime import datetime, timezone
    write_conditions(stage, inventory, latest)
    threshold_rows = applicable_thresholds(series, datetime.now(timezone.utc))
    table(stage, "station_current_thresholds", threshold_rows,
          ("station_id", "time_series_id", "parameter_code", "unit_of_measure", "name", "reference_code",
           "reference_value", "start", "end", "status", "interpretation"))
    provenance = []
    for path in sorted((stage / "raw").glob("latest-continuous_*/*.receipt.json")):
        receipt = archive.read_json(path)
        provenance.append({"dataset": path.parent.name, "region": "California state_code=06", "plan": "multiple_or_unresolved",
                           "source": receipt["url"], "retrieval_date": receipt["retrieved_at_utc"],
                           "evidence": str(path.relative_to(stage)).replace("\\", "/")})
    table(stage, "dataset_provenance", provenance, ("dataset", "region", "plan", "source", "retrieval_date", "evidence"))
    return {"stations_with_latest_values": len({station for station, source, _ in station_counts}),
            "series_missing_metadata": sorted({r["time_series_id"] for r in metadata_links if r["metadata_status"] != "exact_id_match"})}
