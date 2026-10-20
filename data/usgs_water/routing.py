"""Statewide directed hydrography, tributaries and potential downstream basin links."""

from collections import Counter, defaultdict, deque
from contextlib import closing
import csv
import gzip
import json
from pathlib import Path
import shutil
import sqlite3
import xml.etree.ElementTree as ET

import numpy as np
from pyproj import Transformer
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from data.basin_plans import reference
from data.basin_plans.organize import CALWATER_LEVELS, REGIONS
from data.flood_impacts import archive
from data.usgs_water.client import Client
from data.usgs_water.relationships import read_csv

WFS = "https://api.water.usgs.gov/geoserver/wmadata/ows"
NETWORK = "NHDPlusV2_USGS_wmadata"
BBOX = (-125, 32, -113.5, 42.5)
FIELDS = ("the_geom", "comid", "gnis_name", "reachcode", "lengthkm", "fromnode", "tonode",
          "hydroseq", "dnhydroseq", "divergence", "terminalfl", "tidal", "ftype", "fcode", "flowdir", "enabled", "vpuid")
PAGE_SIZE = 5000


def identifier(value):
    """Interpret exact integer network keys; zero/null never form a connection."""
    if value is None or str(value).strip() in ("", "0"):
        return ""
    number = float(value)
    if not number.is_integer() or number < 0:
        raise ValueError(f"Invalid network identifier: {value}")
    return str(int(number))


def wfs_query(client, name, predicate):
    """Enumerate a source predicate in sorted pages with before/after count evidence."""
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
              "typeNames": "wmadata:nhdflowline_network", "CQL_FILTER": predicate}
    def count(label):
        raw = client.fetch(f"{name}/{label}", WFS, {**params, "resultType": "hits"}, as_json=False)
        value = ET.fromstring(raw).attrib.get("numberMatched")
        if value is None or not value.isdigit():
            raise ValueError("WFS did not provide an exact feature count")
        return int(value)
    expected = count("count_before")
    seen, last_id = 0, -1
    while seen < expected:
        document = client.fetch(f"{name}/page_{seen:08}", WFS, {
            **params, "outputFormat": "application/json", "srsName": "EPSG:4326",
            "count": PAGE_SIZE, "startIndex": seen, "sortBy": "comid A", "propertyName": ",".join(FIELDS),
        })
        features = document["features"]
        if not features or len(features) > PAGE_SIZE or document.get("numberReturned") != len(features):
            raise ValueError("Incomplete or incorrectly sized WFS page")
        for feature in features:
            key = int(identifier(feature["properties"]["comid"]))
            if key <= last_id:
                raise ValueError("Duplicate or out-of-order WFS reach")
            last_id = key
        seen += len(features)
        print(f"{name}: {seen:,}/{expected:,} reaches", flush=True)
        yield features
    if seen != expected or count("count_after") != expected:
        raise ValueError("WFS source changed or enumeration was incomplete")


def initialize_database(path):
    """Rebuild disposable derived tables while retaining all original cached responses."""
    if path.exists():
        if path.name != "routing.download" or not path.parent.name.startswith(".pending-"):
            raise ValueError("Unexpected derived database replacement path")
        path.unlink()
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA journal_mode=DELETE;
        CREATE TABLE reaches(reach_id TEXT PRIMARY KEY, name TEXT, reachcode TEXT, length_km REAL,
            from_node TEXT, to_node TEXT, hydroseq TEXT, downstream_hydroseq TEXT, divergence INTEGER,
            terminal INTEGER, tidal INTEGER, feature_type TEXT, flow_direction TEXT, enabled INTEGER,
            vpu TEXT, acquisition_scope TEXT, geometry_wkb BLOB);
        CREATE INDEX reach_from_node ON reaches(from_node);
        CREATE TABLE source_checks(node_id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE routing_scope_seeds(reach_id TEXT PRIMARY KEY, evidence TEXT);
        CREATE TABLE flow_connections(from_reach_id TEXT, to_reach_id TEXT, node_id TEXT, status TEXT,
            downstream_divergence INTEGER, tidal INTEGER, evidence_class TEXT,
            PRIMARY KEY(from_reach_id,to_reach_id));
        CREATE TABLE tributary_connections(upstream_reach_id TEXT, downstream_reach_id TEXT,
            upstream_name TEXT, downstream_name TEXT, node_id TEXT, incoming_reaches INTEGER,
            relationship TEXT, evidence_class TEXT, PRIMARY KEY(upstream_reach_id,downstream_reach_id));
        CREATE TABLE basins(basin_id TEXT PRIMARY KEY, level TEXT, code TEXT, name TEXT,
            dataset_key TEXT, object_id TEXT, region TEXT, plan TEXT, geometry_wkb BLOB);
        CREATE TABLE reach_calwater_overlaps(reach_id TEXT, basin_id TEXT, intersection_length_m REAL,
            relationship TEXT, evidence_class TEXT, PRIMARY KEY(reach_id,basin_id));
        CREATE INDEX overlap_by_basin ON reach_calwater_overlaps(basin_id);
        CREATE TABLE station_downstream_reaches(station_id TEXT, reach_id TEXT, minimum_hops INTEGER,
            relationship TEXT, evidence_class TEXT, PRIMARY KEY(station_id,reach_id));
        CREATE TABLE station_downstream_basins(station_id TEXT, basin_id TEXT, minimum_hops INTEGER,
            connected_reach_count INTEGER, positive_length_reaches INTEGER, relationship TEXT,
            evidence_class TEXT, impact_status TEXT, PRIMARY KEY(station_id,basin_id));
        CREATE TABLE station_routing_coverage(station_id TEXT PRIMARY KEY, source_reach_id TEXT,
            status TEXT, reachable_reaches INTEGER, reachable_basins INTEGER, unresolved_endpoints INTEGER,
            source_terminals INTEGER, tidal_reaches INTEGER, potential_divergences INTEGER);
    """)
    return db


def insert_reaches(db, features, scope):
    """Store compact published attributes and lossless geometry in a derived database."""
    rows = []
    for feature in features:
        p = feature["properties"]
        geometry = shape(feature["geometry"]) if feature.get("geometry") else None
        rows.append((identifier(p["comid"]), (p.get("gnis_name") or "").strip(), str(p.get("reachcode") or ""),
                     p.get("lengthkm"), identifier(p.get("fromnode")), identifier(p.get("tonode")),
                     identifier(p.get("hydroseq")), identifier(p.get("dnhydroseq")), p.get("divergence"),
                     p.get("terminalfl"), p.get("tidal"), p.get("ftype"), p.get("flowdir"), p.get("enabled"),
                     p.get("vpuid"), scope, shapely.to_wkb(geometry) if geometry is not None else None))
    db.executemany("INSERT OR IGNORE INTO reaches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()


def select_scope_seeds(db, basin_root, station_links):
    """Seed closure from every CalWater-intersecting reach and every CA station.

    Border context downloaded in the rectangular envelope is retained, but its
    unrelated distant drainage is not treated as a California routing obligation.
    """
    snapshot, manifest = reference.open_snapshot(basin_root)
    entry = next(d for d in manifest["datasets"] if d["name"] == "CalWater_Hydrologic_Region")
    polygons = np.asarray([shapely.make_valid(shape(f["geometry"])) for f in
                          reference.iter_snapshot_records(snapshot, entry, manifest) if f.get("geometry")], dtype=object)
    shapely.prepare(polygons)
    tree = STRtree(polygons)
    seeds = {r["reach_id"] for r in station_links if r["reach_id"]}
    cursor = db.execute("SELECT reach_id,geometry_wkb FROM reaches")
    while batch := cursor.fetchmany(2000):
        lines = shapely.from_wkb(np.asarray([row[1] for row in batch], dtype=object))
        candidates = tree.query(lines)
        hits = candidates[:, shapely.intersects(polygons[candidates[1]], lines[candidates[0]])]
        seeds.update(batch[int(i)][0] for i in hits[0])
    db.executemany("INSERT INTO routing_scope_seeds VALUES (?,?)", [(rid, "CalWater_intersection_or_published_CA_station_seed") for rid in sorted(seeds)])
    db.commit()
    return seeds


def acquire(db, client, station_links, basin_root):
    """Cover California, missing station seeds, and every published downstream exit."""
    client.fetch("wfs_capabilities", WFS, {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"}, as_json=False)
    predicate = "BBOX(the_geom," + ",".join(map(str, BBOX)) + ",'EPSG:4326')"
    for page in wfs_query(client, "statewide_envelope", predicate):
        insert_reaches(db, page, "california_and_border_envelope")
    existing = {r[0] for r in db.execute("SELECT reach_id FROM reaches")}
    missing = sorted({r["reach_id"] for r in station_links if r["reach_id"]} - existing, key=int)
    for offset in range(0, len(missing), 100):
        for page in wfs_query(client, f"station_seeds/{offset:05}", "comid IN (" + ",".join(missing[offset:offset+100]) + ")"):
            insert_reaches(db, page, "published_station_seed_outside_envelope")
    seeds = select_scope_seeds(db, basin_root, station_links)
    iteration = 0
    while True:
        # Query all outgoing nodes, including already partially represented
        # boundary junctions. The initial envelope contains entire intersecting
        # features; exits are identified geometrically by their end coordinate.
        candidates = []
        checked = {r[0] for r in db.execute("SELECT node_id FROM source_checks")}
        starts = defaultdict(list)
        properties = {}
        for rid, start, end in db.execute("SELECT reach_id,from_node,to_node FROM reaches"):
            properties[rid] = end
            if start:
                starts[start].append(rid)
        reachable, pending = set(seeds), list(seeds)
        while pending:
            rid = pending.pop()
            for target in starts.get(properties.get(rid, ""), ()):
                if target not in reachable:
                    reachable.add(target)
                    pending.append(target)
        for reach_id, node, terminal, blob, scope in db.execute("SELECT reach_id,to_node,terminal,geometry_wkb,acquisition_scope FROM reaches"):
            if reach_id not in reachable or not node or node in checked or terminal == 1:
                continue
            outside = False
            if blob:
                bounds = shapely.from_wkb(blob).bounds
                outside = bounds[0] <= BBOX[0] or bounds[1] <= BBOX[1] or bounds[2] >= BBOX[2] or bounds[3] >= BBOX[3]
            if node not in starts or outside or scope != "california_and_border_envelope":
                candidates.append(node)
        nodes = sorted(set(candidates), key=int)
        if not nodes:
            break
        for offset in range(0, len(nodes), 100):
            selected = nodes[offset:offset+100]
            for page in wfs_query(client, f"california_downstream_closure/{iteration:04}_{offset:05}", "fromnode IN (" + ",".join(selected) + ")"):
                insert_reaches(db, page, "downstream_boundary_extension")
            db.executemany("INSERT INTO source_checks VALUES (?,?)", [(node, "source_successor_query_complete") for node in selected])
            db.commit()
        iteration += 1


def graph_rows(reaches):
    """Join nonzero published nodes, retaining endpoint and direction limitations."""
    starts = defaultdict(list)
    for r in reaches:
        if r["from_node"]:
            starts[r["from_node"]].append(r)
    rows = []
    for r in reaches:
        targets = starts.get(r["to_node"], []) if r["to_node"] else []
        for target in targets or [None]:
            permitted = r["flow_direction"] == "With Digitized" and r["enabled"] == 1
            if target:
                permitted = permitted and target["flow_direction"] == "With Digitized" and target["enabled"] == 1
                status = "published_node_connection" if permitted else "direction_or_enabled_requires_review"
            else:
                status = "source_terminal" if r["terminal"] == 1 else "unresolved_source_endpoint"
            if r["terminal"] == 1:
                status = "source_terminal"
            elif r.get("feature_type") == "Coastline" or (target and target.get("feature_type") == "Coastline"):
                status = "coastline_connection_not_river_routing"
            rows.append((r["reach_id"], target["reach_id"] if target else "", r["to_node"], status,
                         target["divergence"] if target else None, r["tidal"], "published_node_key_join"))
    return rows


def downstream_hops(start, adjacency):
    """Return all possible directed branches with shortest hop counts, safely through cycles."""
    distances, pending = {start: 0}, deque([start])
    while pending:
        source = pending.popleft()
        for target in adjacency.get(source, ()):
            if target not in distances:
                distances[target] = distances[source] + 1
                pending.append(target)
    return distances


def build_graph(db):
    db.row_factory = sqlite3.Row
    reaches = [dict(r) for r in db.execute("SELECT reach_id,name,reachcode,from_node,to_node,divergence,terminal,tidal,feature_type,flow_direction,enabled FROM reaches")]
    edges = graph_rows(reaches)
    db.executemany("INSERT INTO flow_connections VALUES (?,?,?,?,?,?,?)", edges)
    names = {r["reach_id"]: r["name"] for r in reaches}
    incoming = Counter(r[1] for r in edges if r[1] and r[3] == "published_node_connection")
    tributaries = [(a, b, names[a], names[b], node, incoming[b], "confluence_incoming_branch", "published_node_key_join")
                  for a, b, node, status, _, _, _ in edges if b and incoming[b] > 1 and status == "published_node_connection"]
    db.executemany("INSERT INTO tributary_connections VALUES (?,?,?,?,?,?,?,?)", tributaries)
    db.commit()
    return reaches, edges


def build_basins(db, basin_root):
    """Intersect all acquired reaches with six independent CalWater categories."""
    snapshot, manifest = reference.open_snapshot(basin_root)
    transform = Transformer.from_crs("EPSG:4326", "EPSG:3310", always_xy=True).transform
    code_names = {"01_hydrologic_regions": ("hrc", "hrc"), "02_hydrologic_units": ("rbu", "huname"),
                  "03_hydrologic_areas": ("rbua", "first_haname"), "04_hydrologic_subareas": ("rbuas", "first_hsaname"),
                  "05_super_planning_watersheds": ("rbuasp", "first_cdfspwname"), "06_planning_watersheds": ("rbuaspw", "first_cdfpwsname")}
    basins, geometries, diagnostics = [], [], []
    hr_names = defaultdict(set)
    for entry in manifest["datasets"]:
        if entry["name"] == "CalWater_Hydrologic_Unit":
            for feature in reference.iter_snapshot_records(snapshot, entry, manifest):
                p = feature["properties"]
                if p.get("hrc") and p.get("hrname"):
                    hr_names[p["hrc"]].add(p["hrname"])
    for entry in manifest["datasets"]:
        if entry["name"] not in CALWATER_LEVELS:
            continue
        level = CALWATER_LEVELS[entry["name"]][0]
        code, name = code_names[level]
        for f in reference.iter_snapshot_records(snapshot, entry, manifest):
            p = f["properties"]
            key = f"{entry['key']}:{p[entry['object_id_field']]}"
            geom = shape(f["geometry"]) if f.get("geometry") else None
            if geom is None or geom.is_empty:
                diagnostics.append({"basin_id": key, "status": "null_or_empty_geometry"})
            elif not geom.is_valid:
                geom = shapely.make_valid(geom)
                diagnostics.append({"basin_id": key, "status": "derived_geometry_repair_original_preserved"})
            geom = shapely.transform(geom, transform, interleaved=False) if geom is not None else None
            region = next((slug for slug in REGIONS if slug[:2] == str(p.get("rb", "")).zfill(2)), "")
            basin_name = str(p.get(name) or "")
            if level == "01_hydrologic_regions" and len(hr_names.get(p.get("hrc"), set())) == 1:
                basin_name = next(iter(hr_names[p["hrc"]]))
            row = (key, level, str(p.get(code) or ""), basin_name, entry["key"], str(p[entry["object_id_field"]]),
                   region if level == "02_hydrologic_units" else "", str(p.get("hbpaname") or ""),
                   shapely.to_wkb(geom) if geom is not None else None)
            basins.append(row)
            geometries.append(geom)
    db.executemany("INSERT INTO basins VALUES (?,?,?,?,?,?,?,?,?)", basins)
    polygons = np.asarray(geometries, dtype=object)
    shapely.prepare(polygons)
    tree = STRtree(polygons)
    cursor = db.execute("SELECT reach_id,geometry_wkb FROM reaches ORDER BY CAST(reach_id AS INTEGER)")
    processed = 0
    while batch := cursor.fetchmany(2000):
        lines = shapely.from_wkb(np.asarray([r[1] for r in batch], dtype=object))
        lines = shapely.transform(lines, transform, interleaved=False)
        candidates = tree.query(lines)
        mask = shapely.intersects(polygons[candidates[1]], lines[candidates[0]])
        hits = candidates[:, mask]
        line_hits, polygon_hits = lines[hits[0]], polygons[hits[1]]
        covered = shapely.covers(polygon_hits, line_hits)
        lengths = shapely.length(line_hits)
        if (~covered).any():
            lengths[~covered] = shapely.length(shapely.intersection(line_hits[~covered], polygon_hits[~covered]))
        rows = [(batch[int(si)][0], basins[int(bi)][0], round(float(length), 3),
                 "line_overlap" if length > 0 else "boundary_touch_only", "derived_spatial_intersection_EPSG3310")
                for si, bi, length in zip(hits[0], hits[1], lengths)]
        db.executemany("INSERT INTO reach_calwater_overlaps VALUES (?,?,?,?,?)", rows)
        processed += len(batch)
        if processed % 20000 == 0:
            db.commit()
            print(f"CalWater intersections: {processed:,} reaches", flush=True)
    db.commit()
    return diagnostics


def build_station_routes(db, station_links, reaches, edges):
    """Link all inventory stations without copying any current or historical readings."""
    adjacency = defaultdict(list)
    endpoints = {}
    for a, b, _, status, _, _, _ in edges:
        if b and status == "published_node_connection":
            adjacency[a].append(b)
        elif status != "published_node_connection":
            endpoints[a] = status
    properties = {r["reach_id"]: r for r in reaches}
    overlap = defaultdict(list)
    for rid, bid, length in db.execute("SELECT reach_id,basin_id,intersection_length_m FROM reach_calwater_overlaps"):
        overlap[rid].append((bid, length))
    seeds = defaultdict(list)
    for link in station_links:
        source = properties.get(link["reach_id"])
        if source and link.get("reachcode") and link["reachcode"] != source["reachcode"]:
            db.execute("INSERT INTO station_routing_coverage VALUES (?,?,?,?,?,?,?,?,?)",
                       (link["station_id"], link["reach_id"], "published_reachcode_mismatch_requires_review", 0, 0, 0, 0, 0, 0))
            continue
        seeds[link["reach_id"]].append(link["station_id"])
    for index, (seed, station_ids) in enumerate(sorted(seeds.items()), 1):
        if not seed or seed not in properties:
            status = "missing_published_station_reach" if not seed else "published_station_reach_absent_from_source"
            db.executemany("INSERT INTO station_routing_coverage VALUES (?,?,?,?,?,?,?,?,?)",
                           [(sid, seed, status, 0, 0, 0, 0, 0, 0) for sid in station_ids])
            continue
        source = properties[seed]
        if source.get("feature_type") == "Coastline":
            db.executemany("INSERT INTO station_routing_coverage VALUES (?,?,?,?,?,?,?,?,?)",
                           [(sid, seed, "coastline_seed_not_river_routing", 0, 0, 0, 0, 0, 0) for sid in station_ids])
            continue
        if source["enabled"] != 1 or source["flow_direction"] != "With Digitized":
            db.executemany("INSERT INTO station_routing_coverage VALUES (?,?,?,?,?,?,?,?,?)",
                           [(sid, seed, "source_direction_or_enabled_requires_review", 0, 0, 0, 0, 0, 0) for sid in station_ids])
            continue
        path = downstream_hops(seed, adjacency)
        basin_paths = {}
        for rid, hops in path.items():
            for bid, length in overlap.get(rid, []):
                row = basin_paths.setdefault(bid, [hops, 0, 0])
                row[0] = min(row[0], hops)
                row[1] += 1
                row[2] += int(length > 0)
        unresolved = sum(endpoints.get(rid) not in (None, "source_terminal") for rid in path)
        terminals = sum(endpoints.get(rid) == "source_terminal" for rid in path)
        tidal = sum(properties[rid]["tidal"] == 1 for rid in path)
        divergence = sum(len(adjacency[rid]) > 1 for rid in path)
        for sid in station_ids:
            db.executemany("INSERT INTO station_downstream_reaches VALUES (?,?,?,?,?)", [
                (sid, rid, hops, "same_station_reach_extent_unresolved" if rid == seed else "possible_downstream_path",
                 "derived_directed_graph_reachability") for rid, hops in path.items()])
            db.executemany("INSERT INTO station_downstream_basins VALUES (?,?,?,?,?,?,?,?)", [
                (sid, bid, hops, count, positive, "connected_waterway_overlaps_basin" if positive else "boundary_contact_only",
                 "derived_graph_plus_spatial_overlap", "potentially_affected_review_candidate_not_predicted_inundation")
                for bid, (hops, count, positive) in basin_paths.items()])
            status = "paths_with_unresolved_endpoints" if unresolved else "paths_to_source_terminals" if terminals else "no_source_terminal_reached"
            db.execute("INSERT INTO station_routing_coverage VALUES (?,?,?,?,?,?,?,?,?)",
                       (sid, seed, status, len(path), len(basin_paths), unresolved, terminals, tidal, divergence))
        if index % 100 == 0:
            print(f"Downstream routes: {index:,}/{len(seeds):,} distinct station seeds", flush=True)
            db.commit()
    db.commit()


def export_query(db, path, query, parameters=()):
    """Write readable compressed CSV tables without materializing a large result set."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cursor = db.execute(query, parameters)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([d[0] for d in cursor.description])
        writer.writerows(cursor)


def export_tables(db, stage):
    tables = ("flow_connections", "tributary_connections", "reach_calwater_overlaps", "station_downstream_reaches",
              "station_downstream_basins", "station_routing_coverage")
    counts = {}
    for name in tables:
        counts[name] = db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        export_query(db, stage / "relationships" / (name + ".csv.gz"), f"SELECT * FROM {name}")
    counts["reaches"] = db.execute("SELECT count(*) FROM reaches").fetchone()[0]
    counts["basins"] = db.execute("SELECT count(*) FROM basins").fetchone()[0]
    export_query(db, stage / "waterways.csv.gz", "SELECT reach_id,name,reachcode,length_km,feature_type,flow_direction,tidal,acquisition_scope FROM reaches")
    export_query(db, stage / "basins.csv", "SELECT basin_id,level,code,name,dataset_key,object_id,region,plan FROM basins")
    # Stream one GIS-ready layer rather than copying the large geometry into
    # every regional relationship export. Its properties retain exact reach IDs.
    with gzip.open(stage / "waterways.geojson.gz", "wt", encoding="utf-8") as stream:
        stream.write('{"type":"FeatureCollection","features":[')
        first = True
        for rid, name, code, feature_type, scope, blob in db.execute("SELECT reach_id,name,reachcode,feature_type,acquisition_scope,geometry_wkb FROM reaches"):
            if not first:
                stream.write(",")
            first = False
            geometry = json.loads(shapely.to_geojson(shapely.from_wkb(blob))) if blob else None
            json.dump({"type": "Feature", "id": rid, "geometry": geometry,
                       "properties": {"reach_id": rid, "name": name, "reachcode": code,
                                      "feature_type": feature_type, "acquisition_scope": scope}}, stream)
        stream.write("]}\n")
    db.execute("CREATE TABLE reach_regions AS SELECT DISTINCT o.reach_id,b.region,b.plan FROM reach_calwater_overlaps o JOIN basins b USING(basin_id) WHERE b.region != '' AND o.intersection_length_m>0")
    db.execute("CREATE INDEX reach_region_lookup ON reach_regions(region,reach_id)")
    for slug, title in REGIONS.items():
        folder = stage / "regions" / slug
        export_query(db, folder / "waterways.csv.gz", "SELECT DISTINCT r.reach_id,r.name,r.reachcode,r.feature_type FROM reaches r JOIN reach_regions g USING(reach_id) WHERE g.region=?", (slug,))
        export_query(db, folder / "potential_basin_connections.csv.gz", """SELECT s.*,b.level,b.code,b.name FROM station_downstream_basins s JOIN basins b USING(basin_id)
            WHERE b.basin_id IN (SELECT o.basin_id FROM reach_calwater_overlaps o JOIN reach_regions g USING(reach_id) WHERE g.region=?)""", (slug,))
        count = db.execute("SELECT count(DISTINCT reach_id) FROM reach_regions WHERE region=?", (slug,)).fetchone()[0]
        archive.write_csv(folder / "catalog.csv", [{"title": "Named and unnamed connected waterways", "path": "waterways.csv.gz"},
            {"title": "Potential basin connections (derived, not flood extents)", "path": "potential_basin_connections.csv.gz"}], ("title", "path"))
        (folder / "README.md").write_text(f"# {title}: downstream and tributary relationships\n\n"
            f"{count:,} reaches intersect CalWater hydrologic units attributed to this Water Board region. "
            "Regional membership is derived and may overlap. Basin candidates include other nested CalWater levels "
            "that intersect these reaches; a candidate is not a prediction of inundation. Current readings join by "
            "station_id through the independently refreshed observations collection. Global directed and tributary "
            "tables remain in ../../relationships/.\n", encoding="utf-8")
    for level, title in CALWATER_LEVELS.values():
        folder = stage / "calwater" / level
        export_query(db, folder / "catalog.csv", "SELECT basin_id,code,name FROM basins WHERE level=?", (level,))
        export_query(db, folder / "potential_basin_connections.csv.gz", "SELECT s.* FROM station_downstream_basins s JOIN basins b USING(basin_id) WHERE b.level=?", (level,))
        (folder / "README.md").write_text(f"# {title}\n\nDerived directed-path and line/polygon relationships. "
            "Nested levels are independent and must not be added together as distinct flooded basins.\n", encoding="utf-8")
    db.commit()
    return counts


def refresh_routing(root, basin_root, resume=None, reuse_sources=False):
    """Publish an independently refreshable static routing generation; retain originals."""
    from data.usgs_water.refresh import build_stage, retain_code
    network_pointer = archive.read_json(root / "network.json")
    network, nm = archive.open_generation(root, "network", network_pointer)
    basin_pointer = archive.read_json(Path(basin_root) / "sources.json")
    settings = {"network_pointer": network_pointer, "inventory_pointer": nm["inventory_pointer"],
                "basin_pointer": basin_pointer, "envelope": list(BBOX), "selected_source_fields": list(FIELDS)}
    from data.usgs_water.link_review import effective_links
    links, review_pointer = effective_links(root, network, nm["inventory_pointer"], network_pointer)
    acquisition_settings = dict(settings)
    if review_pointer:
        settings["link_review_pointer"] = review_pointer
    previous = None
    if reuse_sources:
        pointer = archive.read_json(root / "routing.json")
        previous, pm = archive.open_generation(root, "routing", pointer)
        if any(pm[key] != value for key, value in acquisition_settings.items()):
            raise ValueError("Reusing routing sources requires matching inventory, network, CalWater and acquisition settings")
        with closing(sqlite3.connect((previous / "routing.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as saved:
            for link in links:
                if link.get("supplemental_evidence") and not saved.execute("SELECT 1 FROM routing_scope_seeds WHERE reach_id=?", (link["reach_id"],)).fetchone():
                    raise ValueError("New supplemental seed is outside the verified closure scope; use a full routing refresh")
        settings["reused_acquisition_pointer"] = pointer
    stage, identifier_, _ = build_stage(root, "routing", resume, settings)
    db = initialize_database(stage / "routing.download")
    try:
        archive.write_csv(stage / "relationships/effective_station_reach_links.csv", links, tuple(links[0]))
        if previous:
            reuse_acquisition(db, previous, stage)
        else:
            acquire(db, Client(stage), links, basin_root)
        reaches, edges = build_graph(db)
        diagnostics = archive.read_json(previous / "geometry_diagnostics.json") if previous else build_basins(db, basin_root)
        archive.write_json(stage / "geometry_diagnostics.json", diagnostics)
        build_station_routes(db, links, reaches, edges)
        counts = export_tables(db, stage)
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Invalid routing database")
    finally:
        db.close()
    (stage / "routing.download").replace(stage / "routing.sqlite")
    retain_code(stage)
    target, manifest = archive.publish(root, stage, identifier_, "routing", {
        **settings, "counts": counts, "network": NETWORK, "geometry_crs": "EPSG:4326 reaches; EPSG:3310 basins",
        "scope": "California and adjacent-border envelope; downstream closure from every CalWater-intersecting reach and published CA station seed",
        "interpretation": "Potential directed connections and basin review candidates; no predicted flood footprint, depth or travel time",
        "observations_retained": False,
    })
    write_routing_review(root, target, manifest)
    return target


def reuse_acquisition(db, previous, stage):
    """Rebuild graph interpretations offline from verified, unchanged source geometry.

    Source receipts, scope checks and CalWater intersections retain their pinned
    provenance. Derived routing paths and regional tables are always regenerated.
    """
    shutil.copytree(previous / "raw", stage / "raw", dirs_exist_ok=True)
    with closing(sqlite3.connect((previous / "routing.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as old:
        for table in ("reaches", "source_checks", "routing_scope_seeds", "basins", "reach_calwater_overlaps"):
            cursor = old.execute(f"SELECT * FROM {table}")
            placeholders = ",".join("?" for _ in cursor.description)
            db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", cursor)
            db.commit()


def write_routing_review(root, target, manifest):
    """Expose readable table names and regional catalogs outside the immutable archive."""
    base = target.resolve().relative_to(root.resolve()).as_posix()
    titles = {"flow_connections": "Immediate connections and endpoint statuses",
              "tributary_connections": "Tributary and confluence branches",
              "reach_calwater_overlaps": "Waterway overlaps with CalWater polygons",
              "station_downstream_reaches": "Station to downstream waterway candidates",
              "station_downstream_basins": "Station to potentially affected basin candidates",
              "station_routing_coverage": "Station routing coverage and missing-link statuses"}
    lines = ["# Statewide downstream and tributary relationships", "",
             f"[Routing manifest]({base}/manifest.json) | [Complete SQLite database]({base}/routing.sqlite) | "
             f"[Waterway GeoJSON]({base}/waterways.geojson.gz)", "",
             "Reach counts include adjacent-state context. Basin counts span six nested CalWater levels; "
             "they are not a count of distinct flooded areas. Relationship counts include repeated station "
             "associations with the same reach or basin.", "",
             "| Dataset | Rows |", "| --- | ---: |"]
    lines.extend(f"| [{title}]({base}/relationships/{key}.csv.gz) | {manifest['counts'][key]:,} |"
                 for key, title in titles.items())
    lines += [f"| [Named and unnamed waterway reaches]({base}/waterways.csv.gz) | {manifest['counts']['reaches']:,} |",
              f"| [CalWater basin catalog]({base}/basins.csv) | {manifest['counts']['basins']:,} |", "",
              "## Regional catalogs", ""]
    lines.extend(f"- [{title}]({base}/regions/{slug}/README.md)" for slug, title in REGIONS.items())
    lines += ["", "## Separate CalWater categories", ""]
    lines.extend(f"- [{title}]({base}/calwater/{slug}/README.md)" for slug, title in CALWATER_LEVELS.values())
    lines += ["", "Published node connections, derived downstream paths, and derived CalWater overlaps remain distinct. "
              "Potentially affected basins are review candidates, not predicted flooded areas. "
              "See [routing methods](ROUTING_METHODS.md) for scope and limitations.", ""]
    (root / "ROUTING.md").write_text("\n".join(lines), encoding="utf-8")


def station_context(root, station_id, inventory_pointer, limit=100):
    """Join current readings to static routing by ID, without storing readings here."""
    if not (root / "routing.json").exists():
        return {"status": "routing_not_built"}
    directory, manifest = archive.open_generation(root, "routing")
    if manifest["inventory_pointer"] != inventory_pointer:
        return {"status": "inventory_version_mismatch_refresh_routing", "routing_generation": manifest["generation"]}
    if archive.read_json(root / "network.json") != manifest["network_pointer"]:
        return {"status": "network_version_mismatch_refresh_routing", "routing_generation": manifest["generation"]}
    current_review = archive.read_json(root / "link_review.json") if (root / "link_review.json").exists() else None
    if manifest.get("link_review_pointer") != current_review:
        return {"status": "link_review_version_mismatch_refresh_routing", "routing_generation": manifest["generation"]}
    # Read-only connection; the verified generation is never modified by reports.
    with closing(sqlite3.connect((directory / "routing.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM station_routing_coverage WHERE station_id=?", (station_id,)).fetchone()
        if row is None:
            return {"status": "station_not_in_routing_inventory"}
        waterways = [dict(r) for r in db.execute("""SELECT s.*,r.name,r.reachcode,r.feature_type,r.tidal
            FROM station_downstream_reaches s JOIN reaches r USING(reach_id) WHERE s.station_id=?
            ORDER BY s.minimum_hops, CAST(s.reach_id AS INTEGER) LIMIT ?""", (station_id, limit))]
        basins = [dict(r) for r in db.execute("""SELECT s.*,b.level,b.name,b.code FROM station_downstream_basins s
            JOIN basins b USING(basin_id) WHERE s.station_id=? ORDER BY s.minimum_hops,b.level,b.basin_id LIMIT ?""", (station_id, limit))]
        return {"status": row["status"], "routing_generation": manifest["generation"], "coverage": dict(row),
                "potential_waterways": waterways, "potential_basins": basins, "display_limit_per_table": limit,
                "waterway_rows_omitted": max(0, row["reachable_reaches"] - len(waterways)),
                "basin_rows_omitted": max(0, row["reachable_basins"] - len(basins)),
                "complete_relationship_database": str(directory / "routing.sqlite"),
                "interpretation": "Graph connectivity and basin overlap only; station readings are not transferred downstream as predicted levels."}
