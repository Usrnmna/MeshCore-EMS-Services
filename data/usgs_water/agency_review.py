"""Original-agency address evidence for conflicting and missing station links."""

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import io
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
import zipfile

import shapely
from shapely.geometry import shape

from data.flood_impacts import archive
from data.usgs_water.client import Client, BASE
from data.usgs_water.link_review import PROJECT, features, NONNETWORK, MAX_STATION_OFFSET_M
from data.usgs_water.relationships import read_csv, table

SWIM_ITEM = "https://www.sciencebase.gov/catalog/item/5ebe92af82ce476925e44b8f"
SWIM_DOWNLOAD = "https://www.sciencebase.gov/catalog/file/get/5ebe92af82ce476925e44b8f"
GAGELOC = ("https://dmap-data-commons-ow.s3.amazonaws.com/NHDPlusV21/Data/NationalData/"
           "NHDPlusV21_NationalData_GageLoc_05.7z")
REVIEW_STATUSES = {"conflicting_published_addresses", "no_corroborated_published_address"}


def check_swim_archive(bundle, metadata):
    """Require agency checksums for decision data; expose XML metadata discrepancies."""
    entries = [source for link in metadata["distributionLinks"] for source in (link.get("files") or [])]
    expected = {"SWIM_gage_loc/SWIM_gage_loc." + suffix for suffix in ("dbf", "shp", "shx", "prj")}
    if not expected.issubset({entry["name"] for entry in entries}):
        raise ValueError("Agency checksums for SWIM data files are missing")
    checks = []
    for source in entries:
        content = bundle.read(source["name"])
        if source["checksum"]["type"] != "MD5":
            raise ValueError("Unsupported publisher checksum algorithm")
        actual = hashlib.md5(content).hexdigest()
        matches = len(content) == source["size"] and actual == source["checksum"]["value"]
        if not matches and not source["name"].endswith("_Metadata.xml"):
            raise ValueError("SWIM decision data differs from agency-published checksum")
        checks.append({"file": source["name"], "published_md5": source["checksum"]["value"],
                       "downloaded_md5": actual, "published_bytes": source["size"], "downloaded_bytes": len(content),
                       "status": "verified" if matches else "publisher_xml_checksum_discrepancy",
                       "used_for_station_decisions": source["name"].endswith(".dbf")})
    return checks


def dbf_rows(content):
    """Read fixed-width dBASE character/numeric fields without coercing identifiers.

    The agency files use ASCII field names and Latin-1 scalar values. Unsupported
    field types, duplicate fields, deleted rows and truncated records fail closed.
    Numeric sentinel strings remain original values for explicit interpretation.
    """
    count, header_size, record_size = struct.unpack_from("<IHH", content, 4)
    if header_size < 33 or len(content) < header_size + count * record_size:
        raise ValueError("Truncated dBASE source")
    fields = []
    for offset in range(32, header_size - 1, 32):
        if content[offset] == 13:
            break
        name = content[offset:offset + 11].split(b"\0")[0].decode("ascii")
        if chr(content[offset + 11]) not in ("C", "N", "F", "D", "L"):
            raise ValueError("Unsupported dBASE field type")
        fields.append((name, content[offset + 16]))
    if len({name for name, _ in fields}) != len(fields) or sum(n for _, n in fields) + 1 != record_size:
        raise ValueError("Invalid dBASE field layout")
    for index in range(count):
        record = content[header_size + index * record_size:header_size + (index + 1) * record_size]
        if record[:1] != b" ":
            raise ValueError("Deleted or invalid source record")
        offset, row = 1, {}
        for name, width in fields:
            row[name] = record[offset:offset + width].decode("latin1").strip()
            offset += width
        yield row


def sevenzip_member(content, stage, suffix):
    """Read one bounded archive member in memory; never extract supplied paths."""
    local_dependencies = Path(__file__).parent / ".dependencies"
    if local_dependencies.is_dir() and str(local_dependencies) not in sys.path:
        # Standard installations take precedence over the optional workspace copy.
        sys.path.append(str(local_dependencies))
    import py7zr
    from py7zr.io import BytesIOFactory
    with py7zr.SevenZipFile(io.BytesIO(content)) as bundle:
        members = [name for name in bundle.getnames() if name.lower().endswith(suffix)]
        if len(members) != 1:
            raise ValueError(f"Expected one {suffix} member, found {members}")
        factory = BytesIOFactory(limit=100 * 1024 * 1024)
        bundle.extract(targets=members, factory=factory)
        result = factory.get(members[0])
        result.seek(0)
        return result.read()


def acquire(root, resume=None):
    """Stage metadata only; pin prior decisions and preserve exact agency responses."""
    from data.usgs_water.refresh import build_stage
    pointers = {kind + "_pointer": archive.read_json(root / (kind + ".json"))
                for kind in ("inventory", "network", "routing", "link_review")}
    review, rm = archive.open_generation(root, "link_review", pointers["link_review_pointer"])
    if any(rm[kind + "_pointer"] != pointers[kind + "_pointer"] for kind in ("inventory", "network")):
        raise ValueError("Refresh supplemental review against the active inventory and network first")
    previous_ids = []
    if (root / "agency_review.json").exists():
        _, previous = archive.open_generation(root, "agency_review")
        previous_ids = previous["station_ids"]
    ids = sorted(set(previous_ids) | {r["station_id"] for r in
                 read_csv(review / "relationships/station_link_review.csv") if r["status"] in REVIEW_STATUSES})
    settings = {**pointers, "station_ids": ids}
    stage, identifier, _ = build_stage(root, "agency_review", resume, settings)
    client = Client(stage, attempts=3, timeout=(10, 60))
    metadata_record = client.fetch("swim_metadata", SWIM_ITEM, {"format": "json"})
    content = client.fetch("swim_archive", SWIM_DOWNLOAD, as_json=False)
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        checks = check_swim_archive(bundle, metadata_record)
        archive.write_json(stage / "source_integrity.json", checks)
        swim = list(dbf_rows(bundle.read("SWIM_gage_loc/SWIM_gage_loc.dbf")))
        metadata = bundle.read("SWIM_gage_loc/SWIM_gage_loc_Metadata.xml")
        (stage / "swim_metadata.xml").write_bytes(metadata)
    content = client.fetch("gageloc_archive", GAGELOC, as_json=False)
    dbf = sevenzip_member(content, stage, "gageloc.dbf")
    (stage / "gageloc.dbf").write_bytes(dbf)
    gageloc = list(dbf_rows(dbf))
    archive.write_json(stage / "swim_selected.json", [r for r in swim if "USGS-" + r["Gage_no"] in ids])
    archive.write_json(stage / "gageloc_selected.json", [r for r in gageloc if "USGS-" + r["SOURCE_FEA"] in ids])

    def retrieve(sid):
        worker = Client(stage, attempts=3, timeout=(10, 30))
        try:
            station = worker.fetch("usgs_station/" + sid, BASE + "/monitoring-locations/items/" + sid, {"f": "json"})
            if station["id"] != sid or station["properties"]["agency_code"] != "USGS":
                raise ValueError("Original USGS station identity mismatch")
            primary = worker.fetch("nldi/" + sid, "https://api.water.usgs.gov/nldi/linked-data/nwissite/" + sid,
                                   {"f": "json"}, accepted_statuses=(404,))
            return sid, station, features(primary)
        finally:
            worker.session.close()
    with ThreadPoolExecutor(max_workers=3) as pool:
        current = list(pool.map(retrieve, ids))
    archive.write_json(stage / "current_station_metadata.json", {sid: station for sid, station, _ in current})
    print("Agency metadata acquired for", len(ids), "stations", flush=True)
    return stage, identifier, settings


def assess(station, prior, gages, swim, candidates, lookup):
    """Resolve static addresses only; agency exclusions never create routing.

    GageLoc's FLComID is the flowline identifier; its COMID field identifies the
    event and is zero in this release. Review notes can veto a plausible-looking
    old address. Agreement with a nonnetwork feature does not supply topology.
    """
    sid = station["id"]
    p = station["properties"]
    if p["agency_code"] != "USGS" or "USGS-" + p["monitoring_location_number"] != sid:
        raise ValueError("USGS station identity is inconsistent")
    notes = " | ".join(r.get(k, "") for r in swim for k in
                       ("QC_notes1", "Rev_notes2", "Ver_notes3") if r.get(k))
    result = {"station_id": sid, "station_name": p["monitoring_location_name"],
              "previous_status": prior["status"], "status": "", "reason": "",
              "reach_id": "", "reachcode": "", "station_offset_m": "", "routing_supported": False,
              "swim_qc": ";".join(r["QC_final"] for r in swim), "swim_notes": notes,
              "gage_record_count": len(gages), "evidence_class": "", "source_url": GAGELOC,
              "usgs_metadata_url": BASE + "/monitoring-locations/items/" + sid + "?f=json",
              "swim_source_url": SWIM_ITEM,
              "source_vintage": "GageLoc event dates retained per candidate; SWIM 2021 release published 2023"}

    def finish(status, reason):
        result.update(status=status, reason=reason)
        return result

    # These statements explicitly reject the old location, not merely network
    # routing. A nearby feature must not override the agency's correction.
    if any(text in notes.lower() for text in
           ("site should be on wasteway diversion", "wrong location and wrong connections")):
        return finish("agency_rejects_legacy_address", "USGS review identifies a wrong or unrepresented channel; old GageLoc address withheld")
    if len(gages) > 1 or len(swim) > 1:
        return finish("ambiguous_agency_records", "Multiple exact-ID agency records require review")
    if not gages:
        if notes:
            return finish("agency_documents_network_limitation", "USGS review documents absent or unsuitable hydrography; no supported feature address")
        return finish("no_published_agency_address_found", "Station identity confirmed; no exact-ID address in the checked agency releases")
    g = gages[0]
    if (g["SOURCE_FEA"] != sid.removeprefix("USGS-") or g["SOURCE_ORI"] != "USGS, Water Resources Division"
            or g["EventType"] != "StreamGage"):
        return finish("agency_identity_conflict", "GageLoc source identity or event type is inconsistent")
    rid, code = g["FLComID"], g["REACHCODE"]
    if not rid.isdigit() or int(rid) <= 0 or not code.isdigit() or len(code) != 14:
        return finish("missing_agency_address_keys", "Positive FLComID and 14-digit reachcode are required")
    # Existing conflicts require agreement with the internally consistent SB19
    # address, not substitution of another old address based on distance.
    if prior["status"] == "conflicting_published_addresses":
        sb = [r for r in candidates if r["source"] == "sb19"]
        if len(sb) != 1 or (rid, code) != (sb[0]["reach_id"], sb[0]["reachcode"]):
            return finish("conflicting_agency_and_catalog_addresses", "Original GageLoc does not corroborate the SB19 address; alternatives retained")
    feature = lookup(rid)
    if not feature or feature["reachcode"] != code:
        return finish("agency_feature_key_conflict", "Original address does not resolve to the checked USGS feature and reachcode")
    if not station.get("geometry") or not feature.get("geometry"):
        return finish("agency_geometry_missing", "Source geometry needed for consistency checks is missing")
    point = shapely.transform(shape(station["geometry"]), PROJECT, interleaved=False)
    line = shapely.transform(shape(feature["geometry"]), PROJECT, interleaved=False)
    distance = point.distance(line)
    result["station_offset_m"] = round(distance, 3)
    if distance > MAX_STATION_OFFSET_M:
        return finish("agency_address_spatial_mismatch", "Current station lies beyond the documented tolerance from the published feature")
    if feature["collection"] != "nonnetwork":
        return finish("agency_network_address_requires_review", "Legacy network address requires separate flow and site-role review before use")
    result.update(reach_id=rid, reachcode=code,
                  evidence_class="published_original_agency_static_address_keys_and_geometry_checked")
    return finish("supported_static_nonnetwork_address", "Original agency FLComID/reachcode and current station geometry support a static address; downstream topology absent")


def derive(stage, settings, root, offline=False):
    """Rebuild decisions from pinned inputs; archive every queried feature."""
    review, _ = archive.open_generation(root, "link_review", settings["link_review_pointer"])
    routing, _ = archive.open_generation(root, "routing", settings["routing_pointer"])
    stations = archive.read_json(stage / "current_station_metadata.json")
    priors = {r["station_id"]: r for r in read_csv(review / "relationships/station_link_review.csv")}
    gages, swim, prior_candidates = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in archive.read_json(stage / "gageloc_selected.json"):
        gages["USGS-" + row["SOURCE_FEA"]].append(row)
    for row in archive.read_json(stage / "swim_selected.json"):
        swim["USGS-" + row["Gage_no"]].append(row)
    for row in read_csv(review / "relationships/published_address_candidates.csv"):
        prior_candidates[row["station_id"]].append(row)
    decisions, candidate_rows, geometries = [], [], {}
    client = None if offline else Client(stage, attempts=3, timeout=(10, 30))
    with closing(sqlite3.connect((routing / "routing.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as db:
        cache = {}

        def lookup(rid):
            if rid in cache:
                return cache[rid]
            row = db.execute("SELECT reachcode,feature_type,geometry_wkb FROM reaches WHERE reach_id=?", (rid,)).fetchone()
            if row:
                value = {"reachcode": row[0], "feature_type": row[1], "collection": "network",
                         "geometry": json.loads(shapely.to_geojson(shapely.from_wkb(row[2])))}
            else:
                document = (archive.read_json(stage / "raw/nonnetwork" / (rid + ".gz")) if offline else
                            client.fetch("nonnetwork/" + rid, NONNETWORK + "/" + rid, {"f": "json"}, accepted_statuses=(404,)))
                fs = features(document)
                if not fs:
                    value = None
                else:
                    f = fs[0]
                    if len(fs) != 1 or str(f["properties"]["comid"]) != rid:
                        raise ValueError("USGS returned a different feature ID")
                    geometries[rid] = f
                    value = {"reachcode": f["properties"]["reachcode"], "feature_type": f["properties"]["ftype"],
                             "collection": "nonnetwork", "geometry": f["geometry"]}
            cache[rid] = value
            return value

        for sid in settings["station_ids"]:
            station = stations[sid]
            decision = assess(station, priors[sid], gages[sid], swim[sid], prior_candidates[sid], lookup)
            fresh_primary = features(archive.read_json(stage / "raw/nldi" / (sid + ".gz")))
            if any(f["properties"].get("identifier") != sid for f in fresh_primary):
                raise ValueError("NLDI returned a different station")
            if any(f["properties"].get("comid") not in (None, "", 0) for f in fresh_primary):
                decision.update(status="primary_address_available_refresh_network", reach_id="", reachcode="",
                                evidence_class="", reason="Fresh NLDI now supplies an address; refresh primary network before resolving supplements")
            decisions.append(decision)
            for g in gages[sid]:
                rid = g["FLComID"]
                feature = lookup(rid) if rid.isdigit() and int(rid) > 0 else None
                distance = ""
                if feature and station.get("geometry") and feature.get("geometry"):
                    point = shapely.transform(shape(station["geometry"]), PROJECT, interleaved=False)
                    line = shapely.transform(shape(feature["geometry"]), PROJECT, interleaved=False)
                    distance = round(point.distance(line), 3)
                candidate_rows.append({"station_id": sid, "source": "EPA_USGS_GageLoc_v05",
                    "reach_id": rid, "reachcode": g["REACHCODE"], "event_date": g["EVENTDATE"],
                    "collection": feature["collection"] if feature else "",
                    "actual_reachcode": feature["reachcode"] if feature else "", "station_offset_m": distance,
                    "status": "candidate_not_automatic_routing", "source_url": GAGELOC})
    if client:
        client.session.close()
    return decisions, candidate_rows, list(geometries.values())


def refresh_agency_review(root, resume=None):
    """Publish the agency investigation separately from preserved earlier decisions."""
    from data.usgs_water.refresh import retain_code
    stage, identifier, settings = acquire(root, resume)
    decisions, candidates, geometries = derive(stage, settings, root)
    fields = tuple(decisions[0]) if decisions else ("station_id", "status")
    table(stage, "station_agency_review", decisions, fields)
    table(stage, "supported_static_station_features",
          [r for r in decisions if r["status"] == "supported_static_nonnetwork_address"], fields)
    table(stage, "agency_address_candidates", candidates,
          tuple(candidates[0]) if candidates else ("station_id", "status"))
    archive.write_json(stage / "nonnetwork_features.geojson.gz", {"type": "FeatureCollection", "features": geometries})
    inventory, _ = archive.open_generation(root, "inventory", settings["inventory_pointer"])
    members = defaultdict(set)
    for row in read_csv(inventory / "relationships/station_region_plan.csv"):
        members[row["region"]].add(row["station_id"])
    for slug, ids in members.items():
        archive.write_csv(stage / "regions" / slug / "station_agency_review.csv",
                          [r for r in decisions if r["station_id"] in ids], fields)
    retain_code(stage)
    target, manifest = archive.publish(root, stage, identifier, "agency_review", {
        **settings, "status_counts": dict(Counter(r["status"] for r in decisions)),
        "observations_retained": False, "routing_links_added": 0,
        "interpretation": "Static agency-address review only; no direction or basin impacts inferred from nonnetwork features"})
    write_catalog(root, target, manifest, decisions)
    return target


def write_catalog(root, directory, manifest, decisions):
    """Expose every station's outcome in a readable catalog, preserving refresh layout."""
    base = directory.resolve().relative_to(root.resolve()).as_posix()
    lines = ["# Original-agency station address investigation", "",
             f"Reviewed stations: {len(decisions)}. Routing links added: 0.", "",
             f"[Decisions]({base}/relationships/station_agency_review.csv) | "
             f"[Static feature links]({base}/relationships/supported_static_station_features.csv) | "
             f"[Original address candidates]({base}/relationships/agency_address_candidates.csv) | "
             f"[Manifest]({base}/manifest.json)", "",
             "Static addresses identify mapped features without downstream topology. "
             "Earlier conflicting candidates remain in the pinned supplemental review.", "",
             "| Station | Name | Outcome | Feature |", "| --- | --- | --- | --- |"]
    for row in decisions:
        lines.append(f"| {row['station_id']} | {row['station_name']} | {row['status'].replace('_', ' ')} | {row['reach_id']} |")
    lines += ["", "See [agency-review methods and limitations](AGENCY_REVIEW_METHODS.md) and "
              "[source citations](SOURCES.md). No observation values are stored in this collection.", ""]
    (root / "AGENCY_REVIEW.md").write_text("\n".join(lines), encoding="utf-8")
