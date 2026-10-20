"""Verify statewide routing closure, provenance, spatial links and pilot continuity."""

import argparse
from contextlib import closing
import csv
import gzip
import json
from pathlib import Path
import sqlite3
import sys

import shapely
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data.flood_impacts import archive
from data.basin_plans.organize import REGIONS
from data.usgs_water.refresh import ROOT
from data.usgs_water.validate import verify_receipts
from data.usgs_water.relationships import read_csv


def require_zero(db, query, label):
    if db.execute(query).fetchone()[0]:
        raise ValueError(label)


def validate(root):
    """Check every stored graph path and basin aggregation, with sampled geometry checks."""
    directory, manifest = archive.open_generation(root, "routing")
    if archive.read_json(root / "network.json") != manifest["network_pointer"]:
        raise ValueError("Routing uses an older station network; refresh routing")
    observations, om = archive.open_generation(root, "observations")
    if om["inventory_pointer"] != manifest["inventory_pointer"]:
        raise ValueError("Routing and current readings use different station inventories")
    inventory, im = archive.open_generation(root, "inventory", manifest["inventory_pointer"])
    network, nm = archive.open_generation(root, "network", manifest["network_pointer"])
    receipts = verify_receipts(directory)
    with closing(sqlite3.connect((directory / "routing.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA temp_store=MEMORY")
        # Index reverse edges in temporary storage so predecessor checks remain
        # bounded without modifying the immutable published database.
        db.execute("CREATE TEMP TABLE incoming_edges AS SELECT from_reach_id,to_reach_id FROM flow_connections WHERE status='published_node_connection'")
        db.execute("CREATE INDEX temp.incoming_lookup ON incoming_edges(to_reach_id,from_reach_id)")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Routing database integrity failure")
        for table, expected in manifest["counts"].items():
            if db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] != expected:
                raise ValueError(f"Manifest table count mismatch: {table}")
            exported = directory / "relationships" / f"{table}.csv.gz"
            if exported.exists():
                with gzip.open(exported, "rt", encoding="utf-8", newline="") as stream:
                    rows = csv.reader(stream)
                    columns = next(rows)
                    if columns != [row[1] for row in db.execute(f"PRAGMA table_info({table})")]:
                        raise ValueError(f"Relationship export column mismatch: {table}")
                    if sum(1 for _ in rows) != expected:
                        raise ValueError(f"Relationship export count mismatch: {table}")
        require_zero(db, """SELECT count(*) FROM flow_connections e LEFT JOIN reaches a ON a.reach_id=e.from_reach_id
            LEFT JOIN reaches b ON b.reach_id=e.to_reach_id WHERE a.reach_id IS NULL OR
            (e.to_reach_id!='' AND (b.reach_id IS NULL OR a.to_node='' OR a.to_node!=b.from_node))""", "A directed connection lacks matching published nodes")
        require_zero(db, """SELECT count(*) FROM flow_connections e JOIN reaches a ON a.reach_id=e.from_reach_id
            JOIN reaches b ON b.reach_id=e.to_reach_id WHERE e.status='published_node_connection' AND
            (a.flow_direction!='With Digitized' OR b.flow_direction!='With Digitized' OR a.enabled!=1 OR b.enabled!=1
             OR a.terminal=1 OR a.feature_type='Coastline' OR b.feature_type='Coastline')""", "Unsupported direction, terminal continuation or coastline entered river routing")
        require_zero(db, """SELECT count(*) FROM station_downstream_reaches s JOIN flow_connections e ON e.from_reach_id=s.reach_id
            WHERE e.status='published_node_connection' AND NOT EXISTS
            (SELECT 1 FROM station_downstream_reaches t WHERE t.station_id=s.station_id AND t.reach_id=e.to_reach_id)""", "A stored downstream path is truncated")
        require_zero(db, """SELECT count(*) FROM station_downstream_reaches s JOIN station_routing_coverage c USING(station_id)
            WHERE (s.minimum_hops=0 AND s.reach_id!=c.source_reach_id) OR (s.minimum_hops>0 AND NOT EXISTS
            (SELECT 1 FROM incoming_edges e JOIN station_downstream_reaches p ON p.reach_id=e.from_reach_id
             WHERE e.to_reach_id=s.reach_id AND p.station_id=s.station_id
             AND p.minimum_hops=s.minimum_hops-1))""", "An exported reach is not connected to its station seed")
        require_zero(db, """SELECT count(*) FROM station_downstream_reaches s JOIN flow_connections e ON e.from_reach_id=s.reach_id
            JOIN station_downstream_reaches t ON t.station_id=s.station_id AND t.reach_id=e.to_reach_id
            WHERE e.status='published_node_connection' AND t.minimum_hops>s.minimum_hops+1""", "Stored hops are not shortest directed paths")
        require_zero(db, """SELECT count(*) FROM reach_calwater_overlaps o LEFT JOIN reaches r USING(reach_id)
            LEFT JOIN basins b USING(basin_id) WHERE r.reach_id IS NULL OR b.basin_id IS NULL OR o.intersection_length_m<0""", "A spatial relationship has invalid keys or length")
        # Compare complete set-valued aggregation, not only exported row counts.
        expected = """SELECT s.station_id,o.basin_id,min(s.minimum_hops),count(*),sum(o.intersection_length_m>0)
                      FROM station_downstream_reaches s JOIN reach_calwater_overlaps o USING(reach_id)
                      GROUP BY s.station_id,o.basin_id"""
        actual = "SELECT station_id,basin_id,minimum_hops,connected_reach_count,positive_length_reaches FROM station_downstream_basins"
        require_zero(db, f"SELECT count(*) FROM ({expected} EXCEPT {actual})", "Missing or incorrect derived basin candidates")
        require_zero(db, f"SELECT count(*) FROM ({actual} EXCEPT {expected})", "Unsupported derived basin candidates")
        require_zero(db, "SELECT count(*) FROM station_downstream_basins WHERE impact_status!='potentially_affected_review_candidate_not_predicted_inundation'", "A basin candidate lacks its flood-interpretation boundary")
        require_zero(db, """SELECT count(*) FROM tributary_connections t LEFT JOIN flow_connections e
            ON e.from_reach_id=t.upstream_reach_id AND e.to_reach_id=t.downstream_reach_id
            WHERE e.status IS NULL OR e.status!='published_node_connection' OR t.incoming_reaches<2""", "A tributary row lacks confluence evidence")
        transform = Transformer.from_crs("EPSG:4326", "EPSG:3310", always_xy=True).transform
        samples = list(db.execute("""SELECT r.geometry_wkb,b.geometry_wkb,o.intersection_length_m FROM reach_calwater_overlaps o
            JOIN reaches r USING(reach_id) JOIN basins b USING(basin_id) WHERE CAST(r.reach_id AS INTEGER)%1009=0 LIMIT 100"""))
        for line, polygon, expected_length in samples:
            geometry = shapely.transform(shapely.from_wkb(line), transform, interleaved=False)
            actual_length = geometry.intersection(shapely.from_wkb(polygon)).length
            if abs(actual_length - expected_length) > max(.002, actual_length * 1e-7):
                raise ValueError("Sampled overlap length differs from geometry")
        station_ids = {r[0] for r in db.execute("SELECT station_id FROM station_routing_coverage")}
        from data.usgs_water.link_review import effective_links
        effective, rp = effective_links(root, network, manifest["inventory_pointer"], manifest["network_pointer"], manifest.get("link_review_pointer"))
        if rp != manifest.get("link_review_pointer"):
            raise ValueError("Routing lacks the active supplemental station-link review")
        if manifest.get("link_review_pointer") and archive.read_json(root / "link_review.json") != manifest["link_review_pointer"]:
            raise ValueError("Routing uses an older supplemental link review")
        expected_ids = {r["station_id"] for r in effective}
        if station_ids != expected_ids:
            raise ValueError("Missing station coverage statuses")
        links = {r["station_id"]: r for r in effective}
        for sid, seed, status in db.execute("SELECT station_id,source_reach_id,status FROM station_routing_coverage WHERE reachable_reaches>0"):
            code = db.execute("SELECT reachcode FROM reaches WHERE reach_id=?", (seed,)).fetchone()[0]
            if links[sid]["reachcode"] and code != links[sid]["reachcode"]:
                raise ValueError("A station reachcode changed between NLDI and routing source")
        pilot = []
        for row in read_csv(inventory / "relationships/flood_reference/gauge_reach_links.csv"):
            sid = "USGS-" + row["usgs_id"]
            old_routes = {r["reach_id"] for r in read_csv(inventory / "relationships/flood_reference/gauge_downstream_basins.csv") if r["gauge_lid"] == row["gauge_lid"]}
            current_routes = {r[0] for r in db.execute("SELECT reach_id FROM station_downstream_reaches WHERE station_id=?", (sid,))}
            if not old_routes.issubset(current_routes):
                raise ValueError("Statewide routing lost a verified Russian River pilot reach")
            pilot.append({"station_id": sid, "pilot_reaches_preserved": len(old_routes), "statewide_downstream_reaches": len(current_routes)})
        regional = {slug: db.execute("SELECT count(DISTINCT reach_id) FROM reach_regions WHERE region=?", (slug,)).fetchone()[0] for slug in REGIONS}
        if not all(regional.values()):
            raise ValueError("A California region has no routed hydrography coverage")
        statuses = dict(db.execute("SELECT status,count(*) FROM station_routing_coverage GROUP BY status"))
        calwater_reaches = db.execute("SELECT count(DISTINCT reach_id) FROM reach_calwater_overlaps").fetchone()[0]
        calwater_routable = db.execute("""SELECT count(DISTINCT o.reach_id) FROM reach_calwater_overlaps o
            JOIN reaches r USING(reach_id) WHERE r.feature_type!='Coastline' AND r.enabled=1
            AND r.flow_direction='With Digitized'""").fetchone()[0]
        calwater_levels = [{"level": level, "catalog_polygons": count, "polygons_with_reach_overlap": connected}
                          for level, count, connected in db.execute("""SELECT b.level,count(*),
                          sum(EXISTS(SELECT 1 FROM reach_calwater_overlaps o WHERE o.basin_id=b.basin_id))
                          FROM basins b GROUP BY b.level ORDER BY b.level""")]
        current_ids = {r["monitoring_location_id"] for r in read_csv(observations / "latest_measurements.csv")}
        current_coverage = {"with_routing": 0, "unresolved": 0}
        unresolved_ids = []
        for sid in current_ids:
            row = db.execute("SELECT reachable_reaches FROM station_routing_coverage WHERE station_id=?", (sid,)).fetchone()
            current_coverage["with_routing" if row and row[0] else "unresolved"] += 1
            if not row or not row[0]:
                unresolved_ids.append(sid)
    return {"validated_at_utc": archive.utc_now(), "routing_generation": manifest["generation"],
            "counts": manifest["counts"], "raw_receipts_verified": receipts, "spatial_samples_verified": len(samples),
            "regions": regional, "station_routing_statuses": statuses, "stations_with_latest_readings": current_coverage,
            "latest_stations_without_routing": sorted(unresolved_ids),
            "calwater_intersecting_reaches": calwater_reaches, "calwater_levels": calwater_levels,
            "river_routing_eligible_calwater_reaches": calwater_routable,
            "russian_river_pilot": pilot, "level_history_retained": False,
            "limits": "Graph/source consistency and sampled spatial checks, not hydraulic or observed-flood validation"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.directory)
    if args.output:
        archive.write_json(args.output, result)
    print(json.dumps(result, indent=2))
