"""Review missing station addresses against published identifiers and network keys."""

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3

from pyproj import Transformer
import shapely
from shapely.geometry import shape

from data.flood_impacts import archive
from data.usgs_water.client import Client
from data.usgs_water.relationships import read_csv, table

NLDI = "https://api.water.usgs.gov/nldi/linked-data"
SB19 = "https://sb19.linked-data.internetofwater.dev/collections/ca_gages"
REFERENCE = "https://reference.geoconnex.us/collections/gages"
STATE_ITEM = "https://gispublic.waterboards.ca.gov/portal/sharing/rest/content/items/32dfb85bd2744487affe6e3475190093"
NONNETWORK = "https://api.water.usgs.gov/fabric/pygeoapi/collections/nhdflowline_nonnetwork/items"
MAX_STATION_OFFSET_M = 250
MAX_PUBLISHED_SNAP_OFFSET_M = 10
PROJECT = Transformer.from_crs(4326, 3310, always_xy=True).transform


def key(value):
    """Normalize integer COMIDs without changing string station IDs or reachcodes."""
    if value in (None, "", 0):
        return ""
    number = float(value)
    if number <= 0 or not number.is_integer():
        raise ValueError(f"Invalid COMID: {value}")
    return str(int(number))


def features(document):
    """Separate an explicit source absence from an unexpected API response."""
    if document.get("type") == "Feature":
        return [document]
    if document.get("type") == "FeatureCollection":
        return document["features"]
    if document.get("status") == 404 or document.get("code") == "NotFound":
        return []
    raise ValueError("Unexpected station-source response")


def candidate(sid, source, feature):
    """Retain each published address independently, including contradictory ones."""
    p = feature["properties"]
    if source == "nwissite":
        rid, code = p.get("comid"), p.get("reachcode")
    elif source == "reference_gages":
        rid, code = p.get("nhdpv2_comid"), p.get("nhdpv2_reachcode")
    else:
        rid, code = p.get("comid_medres"), p.get("rchcd_medres")
    return {"station_id": sid, "source": source, "source_feature_id": str(feature.get("id", p.get("objectid", ""))),
            "reach_id": key(rid), "reachcode": str(code or "").strip(),
            "evidence_class": "published_address_candidate_not_automatically_routable"}


def assess_station(station, primary, references, state, sb19, lookup):
    """Require identity, consistent published keys and spatial QA before promotion.

    Distances reject inconsistent addresses; they never select a nearest reach.
    A nonnetwork feature can support a static address but never downstream flow.
    """
    sid = station["id"]
    number = sid.removeprefix("USGS-")
    rows = [candidate(sid, source, f) for source, fs in
            (("nwissite", primary), ("reference_gages", references), ("waterboards", state), ("sb19", sb19))
            for f in fs]
    result = {"station_id": sid, "station_name": station["properties"].get("monitoring_location_name", ""),
              "site_type": station["properties"].get("site_type", ""), "status": "", "reason": "",
              "reach_id": "", "reachcode": "", "station_offset_m": "", "published_snap_offset_m": "",
              "evidence_class": "", "source_url": ""}

    def finish(status, reason):
        result.update(status=status, reason=reason)
        return result, rows

    if len(primary) > 1 or any(f["properties"].get("identifier") != sid for f in primary):
        return finish("ambiguous_primary_identity", "Primary source did not identify one exact station")
    if any(f["properties"].get("provider_id") != sid or
           f["properties"].get("provider") != "https://waterdata.usgs.gov" for f in references):
        return finish("reference_identity_conflict", "Reference provider or station identity disagrees")
    primary_id = key(primary[0]["properties"].get("comid")) if primary else ""
    if primary_id:
        found = lookup(primary_id)
        if found and found["feature_type"] == "Coastline":
            return finish("coastline_not_river_routing", "Published primary address is a coastline; no river reassignment")
        return finish("primary_address_requires_network_refresh", "Primary address now exists; refresh the primary network before supplementing")
    if len(state) > 1 or len(sb19) > 1:
        return finish("ambiguous_catalog_identity", "Multiple catalog records match the station ID")
    if not state or not sb19:
        return finish("no_corroborated_published_address", "No paired Water Board and SB19 station address; proximity is not used")
    p, q = state[0]["properties"], sb19[0]["properties"]
    if (p.get("siteid") != number or p.get("operator") != "USGS" or q.get("site_id") != number
            or str(sb19[0].get("id")) != number or q.get("operator") != "USGS" or q.get("datasource") != "NWIS"
            or q.get("provider") != "https://waterdata.usgs.gov"
            or q.get("weblink") != "https://geoconnex.us/usgs/monitoring-location/" + number):
        return finish("catalog_identity_conflict", "Agency, provider or exact station identifier disagrees")
    rid, code = key(p.get("comid_medres")), str(p.get("rchcd_medres") or "").strip()
    if not rid or not code:
        return finish("missing_catalog_address", "Published COMID or reachcode is missing")
    if rid != key(q.get("comid_medres")) or code != str(q.get("rchcd_medres") or "").strip():
        return finish("conflicting_published_addresses", "Water Board and SB19 COMID/reachcode pairs disagree")
    for feature in references:
        reference = feature["properties"]
        reference_id = key(reference.get("nhdpv2_comid"))
        reference_code = str(reference.get("nhdpv2_reachcode") or "").strip()
        if (reference_id and reference_id != rid) or (reference_code and reference_code != code):
            return finish("reference_address_conflict", "Reference-gage address contradicts the paired catalog address")
    indexed = lookup(rid)
    if not indexed:
        return finish("address_absent_from_checked_hydrography", "Published feature is absent from checked network and nonnetwork sources")
    if indexed["reachcode"] != code:
        return finish("reachcode_conflict", "Published COMID resolves to a different USGS reachcode")
    if indexed["feature_type"] == "Coastline":
        return finish("coastline_not_river_routing", "Supplemental address resolves to coastline")
    if not station.get("geometry") or not state[0].get("geometry") or not indexed.get("geometry"):
        return finish("missing_geometry_for_address_check", "Geometry needed for consistency checks is missing")
    line = shapely.transform(shape(indexed["geometry"]), PROJECT, interleaved=False)
    point = shapely.transform(shape(station["geometry"]), PROJECT, interleaved=False)
    published = shapely.transform(shape(state[0]["geometry"]), PROJECT, interleaved=False)
    offset, snap = line.distance(point), line.distance(published)
    result.update(reach_id=rid, reachcode=code, station_offset_m=round(offset, 3),
                  published_snap_offset_m=round(snap, 3))
    if offset > MAX_STATION_OFFSET_M or snap > MAX_PUBLISHED_SNAP_OFFSET_M:
        return finish("spatial_consistency_requires_review", "Published address exceeds the documented spatial QA tolerance")
    result.update(evidence_class="published_supplemental_address_identity_keys_and_geometry_checked",
                  source_url=STATE_ITEM + ";https://geoconnex.us/ca-gage-assessment/gages/" + number)
    if indexed["collection"] == "nonnetwork":
        return finish("supported_nonnetwork_address_no_downstream", "Static feature address supported; USGS supplies no routable network topology")
    if indexed["enabled"] != 1 or indexed["flow_direction"] != "With Digitized":
        return finish("network_direction_requires_review", "Published feature lacks supported flow direction or enabled status")
    return finish("supported_supplemental_routing", "Exact station identity and published address agree; existing USGS network keys verified")


def review_scope(root, network, routing, prior_ids=()):
    """Review current unsupported stations and retain earlier review IDs on refresh."""
    observations, _ = archive.open_generation(root, "observations")
    current = {r["monitoring_location_id"] for r in read_csv(observations / "latest_measurements.csv")}
    links = {r["station_id"]: r for r in read_csv(network / "relationships/station_reach_links.csv")}
    selected = set(prior_ids)
    with closing(sqlite3.connect((routing / "routing.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for sid in current:
            link = links.get(sid, {})
            row = db.execute("SELECT feature_type,enabled,flow_direction FROM reaches WHERE reach_id=?",
                             (link.get("reach_id", ""),)).fetchone()
            if not row or row[0] == "Coastline" or row[1:] != (1, "With Digitized"):
                selected.add(sid)
    return sorted(selected)


def refresh_link_review(root, resume=None):
    """Archive bounded metadata requests and publish an auditable supplemental review."""
    from data.usgs_water.refresh import build_stage, retain_code
    pointers = {kind + "_pointer": archive.read_json(root / (kind + ".json"))
                for kind in ("inventory", "network", "routing")}
    inventory, _ = archive.open_generation(root, "inventory", pointers["inventory_pointer"])
    network, nm = archive.open_generation(root, "network", pointers["network_pointer"])
    routing, _ = archive.open_generation(root, "routing", pointers["routing_pointer"])
    if nm["inventory_pointer"] != pointers["inventory_pointer"]:
        raise ValueError("Refresh network against the active inventory before link review")
    previous_ids = []
    if (root / "link_review.json").exists():
        _, previous = archive.open_generation(root, "link_review")
        previous_ids = previous["station_ids"]
    ids = review_scope(root, network, routing, previous_ids)
    settings = {**pointers, "station_ids": ids}
    stage, identifier, _ = build_stage(root, "link_review", resume, settings)
    client = Client(stage, attempts=3, timeout=(10, 30))
    item = client.fetch("waterboards_item", STATE_ITEM, {"f": "json"})
    service = client.fetch("waterboards_service", item["url"], {"f": "json"})
    if not any(layer["id"] == 0 for layer in service["layers"]):
        raise ValueError("Expected Water Board station layer is missing")
    client.fetch("waterboards_layer", item["url"] + "/0", {"f": "json"})
    client.fetch("sb19_collection", SB19, {"f": "json"})
    client.fetch("ref_schema", REFERENCE + "/queryables", {"f": "json"})
    where = "siteid IN (" + ",".join("'" + sid.removeprefix("USGS-") + "'" for sid in ids) + ")"
    url = item["url"] + "/0/query"
    object_ids = client.fetch("waterboards_ids", url, {"f": "json", "where": where, "returnIdsOnly": "true"})["objectIds"]
    document = client.fetch("waterboards_stations", url, {"f": "geojson", "objectIds": ",".join(map(str, sorted(object_ids))),
                            "outFields": "*", "outSR": 4326, "returnGeometry": "true"}) if object_ids else {"features": []}
    actual_ids = [f["properties"]["objectid"] for f in document["features"]]
    after = client.fetch("waterboards_ids_after", url, {"f": "json", "where": where, "returnIdsOnly": "true"})["objectIds"]
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(object_ids) or set(after) != set(object_ids):
        raise ValueError("Incomplete or changing Water Board station enumeration")
    state = defaultdict(list)
    for f in document["features"]:
        sid = "USGS-" + f["properties"]["siteid"]
        if sid not in ids:
            raise ValueError("Source ignored requested station filter")
        state[sid].append(f)

    def retrieve(sid):
        worker = Client(stage, attempts=3, timeout=(10, 30))
        number = sid.removeprefix("USGS-")
        try:
            primary = features(worker.fetch("nldi_recheck/" + sid, NLDI + "/nwissite/" + sid,
                                           {"f": "json"}, accepted_statuses=(404,)))
            ca = features(worker.fetch("ca_gages/" + sid, NLDI + "/ca_gages/" + number,
                                      {"f": "json"}, accepted_statuses=(404,)))
            sb = features(worker.fetch("sb19_identity/" + sid, SB19 + "/items/" + number,
                                       {"f": "json"}, accepted_statuses=(404,))) if ca or state[sid] else []
            ref = worker.fetch("reference_gages/" + sid, REFERENCE + "/items",
                               {"f": "json", "provider_id": sid, "limit": 100})
            if ref.get("numberMatched") != len(ref.get("features", [])):
                raise ValueError("Reference gage results were truncated")
            return sid, primary, ref["features"], sb
        finally:
            worker.session.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        source_rows = list(pool.map(retrieve, ids))
    stations = {f["id"]: f for f in archive.read_json(inventory / "stations.geojson.gz")["features"]}
    decisions, candidates, supplemental_geometry = [], [], {}
    with closing(sqlite3.connect((routing / "routing.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        cache = {}

        def lookup(rid):
            if rid in cache:
                return cache[rid]
            row = db.execute("SELECT reachcode,feature_type,enabled,flow_direction,geometry_wkb FROM reaches WHERE reach_id=?", (rid,)).fetchone()
            if row:
                import json
                result = dict(zip(("reachcode", "feature_type", "enabled", "flow_direction"), row[:4]))
                result.update(collection="network", geometry=json.loads(shapely.to_geojson(shapely.from_wkb(row[4]))))
            else:
                data = client.fetch("nonnetwork/" + rid, NONNETWORK + "/" + rid, {"f": "json"}, accepted_statuses=(404,))
                fs = features(data)
                if not fs:
                    cache[rid] = None
                    return None
                p = fs[0]["properties"]
                if key(p["comid"]) != rid:
                    raise ValueError("Nonnetwork service returned a different COMID")
                supplemental_geometry[rid] = fs[0]
                result = {"reachcode": p["reachcode"], "feature_type": p["ftype"], "enabled": None,
                          "flow_direction": p["flowdir"], "geometry": fs[0]["geometry"], "collection": "nonnetwork"}
            cache[rid] = result
            return result

        for sid, primary, refs, sb in source_rows:
            result, rows = assess_station(stations[sid], primary, refs, state[sid], sb, lookup)
            # Resolve all candidate keys for review even when disagreement blocks promotion.
            for row in rows:
                record = lookup(row["reach_id"]) if row["reach_id"] else None
                row.update(hydrography_collection=record["collection"] if record else "",
                           hydrography_reachcode=record["reachcode"] if record else "",
                           key_check=("consistent" if record and record["reachcode"] == row["reachcode"]
                                      else "reachcode_conflict" if record else "no_checked_feature"))
            decisions.append(result)
            candidates.extend(rows)
            print(sid, result["status"], flush=True)
    fields = tuple(decisions[0]) if decisions else ("station_id", "status")
    table(stage, "station_link_review", decisions, fields)
    table(stage, "published_address_candidates", candidates, tuple(candidates[0]) if candidates else ("station_id",))
    for name, status in (("supplemental_routing_links", "supported_supplemental_routing"),
                         ("supported_nonnetwork_addresses", "supported_nonnetwork_address_no_downstream")):
        table(stage, name, [r for r in decisions if r["status"] == status], fields)
    archive.write_json(stage / "nonnetwork_features.geojson.gz",
                       {"type": "FeatureCollection", "features": list(supplemental_geometry.values())})
    region_ids = defaultdict(set)
    for row in read_csv(inventory / "relationships/station_region_plan.csv"):
        region_ids[row["region"]].add(row["station_id"])
    for slug, members in region_ids.items():
        archive.write_csv(stage / "regions" / slug / "station_link_review.csv",
                          [r for r in decisions if r["station_id"] in members], fields)
    retain_code(stage)
    target, manifest = archive.publish(root, stage, identifier, "link_review", {
        **settings, "status_counts": dict(Counter(r["status"] for r in decisions)), "observations_retained": False,
        "spatial_qa_tolerances_m": {"station": MAX_STATION_OFFSET_M, "published_snap": MAX_PUBLISHED_SNAP_OFFSET_M},
        "source_limit": "SB19 is a secondary catalog originating in a 2020 snapshot; agreement is source consistency, not independent hydraulic validation"})
    base = target.resolve().relative_to(root.resolve()).as_posix()
    lines = ["# Supplemental station-link review", "", f"Reviewed stations: {len(ids)}.", "",
             f"[Full station decisions]({base}/relationships/station_link_review.csv) | "
             f"[All published candidates]({base}/relationships/published_address_candidates.csv) | "
             f"[Source manifest]({base}/manifest.json)", "", "| Decision | Stations |", "| --- | ---: |"]
    lines.extend(f"| {status} | {count} |" for status, count in manifest["status_counts"].items())
    lines += ["", f"[Supported routing links]({base}/relationships/supplemental_routing_links.csv)",
              f"[Supported static nonnetwork addresses]({base}/relationships/supported_nonnetwork_addresses.csv)", "",
              "Nonnetwork addresses do not establish downstream flow. Conflicts and missing links remain explicit. "
              "No readings are stored in this collection. See [review methods](LINK_REVIEW_METHODS.md).",
              "A separate [original-agency investigation](AGENCY_REVIEW_METHODS.md) records later static-address "
              "resolutions while preserving these original decisions.", ""]
    (root / "LINK_REVIEW.md").write_text("\n".join(lines), encoding="utf-8")
    return target


def effective_links(root, network, inventory_pointer, network_pointer, review_pointer=None):
    """Overlay supported supplemental links while retaining the primary source table."""
    links = read_csv(network / "relationships/station_reach_links.csv")
    if review_pointer is None and not (root / "link_review.json").exists():
        return links, None
    pointer = review_pointer or archive.read_json(root / "link_review.json")
    directory, manifest = archive.open_generation(root, "link_review", pointer)
    if manifest["inventory_pointer"] != inventory_pointer or manifest["network_pointer"] != network_pointer:
        raise ValueError("Supplemental link review is stale; refresh --mode link-review before routing")
    additions = {r["station_id"]: r for r in read_csv(directory / "relationships/supplemental_routing_links.csv")}
    for link in links:
        extra = additions.get(link["station_id"])
        link["supplemental_evidence"] = ""
        if extra:
            if link["reach_id"] and (link["reach_id"], link["reachcode"]) != (extra["reach_id"], extra["reachcode"]):
                raise ValueError("Supplemental address conflicts with a published primary station link")
            link.update(reach_id=extra["reach_id"], reachcode=extra["reachcode"],
                        measure="", mainstem_uri="", network="NHDPlusV2_published_supplemental_SB19",
                        status="supported_supplemental_routing", source_url=extra["source_url"],
                        supplemental_evidence=extra["evidence_class"])
    return links, pointer
