"""Download the complete public Basin Plan library into versioned offline snapshots.

Only an explicitly invoked refresh performs network I/O. Published snapshots are
immutable; sources.json selects the active generation after every task succeeds.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote, urljoin
from urllib.request import Request, urlopen
from uuid import uuid4
import zipfile

try:
    from . import organize
except ImportError:
    import organize

ROOT = Path(__file__).resolve().parent
PORTAL = "https://gispublic.waterboards.ca.gov/portal/sharing/rest"
GROUP_ID = "2de374bd11d9468d8e8919bdaf060016"
LANDING = "https://www.waterboards.ca.gov/resources/data_databases/basin_plan_portal.html"
STORY_ID = "0b6c6c39e53549f1902919627201abc5"
FOLDER = "https://gispublic.waterboards.ca.gov/portalserver/rest/services/Basin_Plan"
TIMEOUT = 180
ATTEMPTS = 4
BATCH_SIZE = 1000
WORKERS = 3
MAX_RESPONSE_BYTES = 512 * 1024 * 1024

# Regional Water Board categories; Central Valley has two published plan extracts.
CATEGORIES = (
    ("north coast", "regions/01_north_coast"),
    ("san francisco", "regions/02_san_francisco_bay"),
    ("central coast", "regions/03_central_coast"),
    ("los angeles", "regions/04_los_angeles"),
    ("sacramento", "regions/05_central_valley/sacramento_san_joaquin"),
    ("tulare", "regions/05_central_valley/tulare"),
    ("lahontan", "regions/06_lahontan"),
    ("colorado river", "regions/07_colorado_river"),
    ("santa ana", "regions/08_santa_ana"),
    ("san diego", "regions/09_san_diego"),
)


def utc_now():
    """Return an unambiguous retrieval timestamp."""
    return datetime.now(timezone.utc).isoformat()


def slug(value):
    """Convert a source label to a portable, bounded path component."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:100] or "unnamed"


def category(title):
    """Assign regional extracts by their published titles, retaining unknowns."""
    if "calwater" in title.lower():
        return "hydrologic_boundaries/calwater_2_2_1"
    for phrase, path in CATEGORIES:
        if phrase in title.lower():
            return path
    if "california basin plan" in title.lower():
        return "statewide"
    return "supporting"


def category_label(path):
    """Format archive categories as readable regional headings."""
    if path.startswith("regions/"):
        parts = path.split("/")
        number, name = parts[1].split("_", 1)
        label = f"Region {int(number)} — {name.replace('_', ' ').title()}"
        if len(parts) > 2:
            label += " — " + {"sacramento_san_joaquin": "Sacramento and San Joaquin River Basins",
                               "tulare": "Tulare Lake Basin"}.get(parts[2], parts[2])
        return label
    return {"statewide": "Statewide Basin Plan data", "supporting": "Supporting resources",
            "hydrologic_boundaries/calwater_2_2_1": "CalWater 2.2.1 hydrologic boundaries"}.get(path, path)


def safe_path(root, relative):
    """Reject downloaded resource names or manifests that escape their root."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError(f"Unsafe relative path: {relative}")
    return path


def json_bytes(document):
    return (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def write_json(path, document):
    """Replace one JSON file atomically on its destination filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".download")
    temporary.write_bytes(json_bytes(document))
    os.replace(temporary, path)


def decode_json(raw):
    """Reject ArcGIS error envelopes even when the HTTP status is successful."""
    document = json.loads(raw)
    if not isinstance(document, dict) or "error" in document:
        raise ValueError(f"Invalid ArcGIS response: {str(document)[:500]}")
    return document


def request(url, parameters=None):
    """Fetch public bytes with bounded retries; query parameters use POST."""
    body = urlencode(parameters).encode("ascii") if parameters is not None else None
    for attempt in range(ATTEMPTS):
        try:
            req = Request(url, data=body, headers={"User-Agent": "MC-EMS-BasinPlanArchive/1.0"})
            with urlopen(req, timeout=TIMEOUT) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError(f"Response exceeds configured byte limit: {url}")
            return raw
        except (URLError, TimeoutError, ConnectionError, OSError) as error:
            if isinstance(error, HTTPError) and error.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt == ATTEMPTS - 1:
                raise
            time.sleep(min(2 ** attempt, 30))


def digest_file(path):
    """Hash files incrementally, including large native geodatabases."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "byte_count": path.stat().st_size}


class Archive:
    """Store source evidence under one snapshot, with per-file provenance."""

    def __init__(self, root):
        self.root = root

    def save(self, relative, raw, url, parameters=None, compress=False):
        """Preserve response bytes (optionally gzip-wrapped) and their receipts."""
        path = safe_path(self.root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        stored = gzip.compress(raw, mtime=0) if compress else raw
        temporary = path.with_name(path.name + ".download")
        temporary.write_bytes(stored)
        os.replace(temporary, path)
        receipt = {"source_url": url, "parameters": parameters, "retrieved_at_utc": utc_now(),
                   "raw_sha256": hashlib.sha256(raw).hexdigest(), **digest_file(path)}
        write_json(path.with_name(path.name + ".receipt.json"), receipt)
        return receipt

    def fetch_json(self, relative, url, parameters=None):
        """Save valid raw JSON before returning its parsed representation."""
        raw = request(url, parameters)
        document = decode_json(raw)
        self.save(relative, raw, url, parameters)
        return document

    def fetch_binary(self, relative, url, is_zip=False):
        """Save a source download, validating ZIP payloads before acceptance."""
        path = safe_path(self.root, relative)
        receipt_path = path.with_name(path.name + ".receipt.json")
        # A resumed snapshot retains already verified native bytes and timestamps.
        if path.is_file() and receipt_path.is_file():
            receipt = json.loads(receipt_path.read_bytes())
            if receipt["source_url"] == url and all(receipt[k] == v for k, v in digest_file(path).items()):
                if is_zip:
                    with zipfile.ZipFile(path) as archive:
                        if archive.testzip():
                            raise ValueError(f"Corrupt cached ZIP: {path}")
                return
        raw = request(url)
        if raw.lstrip().startswith(b'{'):
            decode_json(raw)
        if is_zip:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                bad = archive.testzip()
                if bad:
                    raise ValueError(f"Corrupt ZIP member: {bad}")
        self.save(relative, raw, url)


def discover(archive):
    """Enumerate every group page, the story item, and the Basin_Plan folder."""
    archive.fetch_json("metadata/group.json", f"{PORTAL}/community/groups/{GROUP_ID}?f=json")
    start = 1
    items = {}
    while start != -1:
        page = archive.fetch_json(f"metadata/group_page_{start}.json", PORTAL + "/search?" + urlencode(
            {"f": "json", "q": f"group:{GROUP_ID}", "num": 100, "start": start}))
        for item in page["results"]:
            items[item["id"]] = item
        next_start = page["nextStart"]
        if next_start != -1 and next_start <= start:
            raise ValueError("Non-advancing portal pagination")
        start = next_start
    if len(items) != page["total"]:
        raise ValueError("Portal group changed during discovery")
    items[STORY_ID] = archive.fetch_json(f"metadata/story_item.json", f"{PORTAL}/content/items/{STORY_ID}?f=json")
    folder = archive.fetch_json("metadata/basin_plan_folder.json", FOLDER + "?f=json")
    known_urls = {i.get("url") for i in items.values()}
    for service in folder["services"]:
        url = FOLDER.rsplit("/", 1)[0] + "/" + service["name"] + "/" + service["type"]
        if url not in known_urls:
            key = "folder_" + slug(service["name"])
            items[key] = {"id": key, "title": service["name"], "type": "Map Service", "url": url}
    # Operational data can be nested in web-map groups and absent from the
    # library group. Basemaps are presentation dependencies, not BPMP datasets.
    inspected = set()
    while True:
        maps = [item for item in items.values() if item["type"] == "Web Map" and item["id"] not in inspected]
        if not maps:
            break
        for item in maps:
            inspected.add(item["id"])
            document = archive.fetch_json(f"metadata/discovery_maps/{item['id']}.json",
                                          f"{PORTAL}/content/items/{item['id']}/data?f=json")
            for layer in operational_layers(document):
                item_id = layer.get("itemId")
                if item_id and item_id not in items:
                    linked = archive.fetch_json(f"metadata/linked_items/{item_id}.json",
                                                f"{PORTAL}/content/items/{item_id}?f=json")
                    items[item_id] = linked
                elif not item_id and layer.get("url"):
                    match = re.match(r"(.+/(?:FeatureServer|MapServer))(?:/\d+)?$", layer["url"])
                    if match and match[1] not in {i.get("url") for i in items.values()}:
                        url = match[1]
                        key = "folder_" + hashlib.sha256(url.encode()).hexdigest()[:16]
                        items[key] = {"id": key, "title": layer.get("title", url),
                                      "type": "Feature Service" if url.endswith("FeatureServer") else "Map Service",
                                      "url": url}
    return sorted(items.values(), key=lambda item: (category(item["title"]), item["title"]))


def operational_layers(document):
    """Yield nested operational layers and tables without following basemaps."""
    for layer in document.get("operationalLayers", []) + document.get("tables", []):
        yield layer
        yield from operational_layers({"operationalLayers": layer.get("layers", [])})


def archive_item(archive, item):
    """Retain item metadata, data, metadata XML, and all item resources."""
    item_id = item["id"]
    base = f"{category(item['title'])}/metadata/items/{item_id}"
    if item_id.startswith("folder_"):
        write_json(archive.root / base / "item.json", item)
        return
    api = f"{PORTAL}/content/items/{item_id}"
    archive.fetch_json(base + "/item.json", api + "?f=json")
    kind = item["type"]
    if kind == "File Geodatabase":
        archive.fetch_binary(f"{category(item['title'])}/native/{item_id}.zip", api + "/data", True)
    elif kind == "Code Attachment":
        archive.fetch_binary(base + "/application.zip", urljoin(PORTAL, item["url"]), True)
    else:
        # Services sometimes have no item data; an empty response is retained.
        raw = request(api + "/data?f=json")
        if raw.strip():
            decode_json(raw)
        archive.save(base + "/item_data.json", raw, api + "/data?f=json")
    if "Metadata" in item.get("typeKeywords", []):
        url = api + "/info/metadata/metadata.xml"
        raw = request(url)
        if raw.lstrip().startswith(b"{"):
            decode_json(raw)
        archive.save(base + "/metadata.xml", raw, url)
    start = 1
    while start != -1:
        url = api + "/resources?" + urlencode({"f": "json", "num": 100, "start": start})
        resources = archive.fetch_json(base + f"/resources_{start}.json", url)
        for entry in resources.get("resources", []):
            name = entry["resource"]
            archive.fetch_binary(base + "/resources/" + name, api + "/resources/" + quote(name, safe="/"))
        following = resources.get("nextStart", -1)
        if following != -1 and following <= start:
            raise ValueError("Non-advancing item resources pagination")
        start = following


def object_ids(archive, base, url, label):
    """Obtain and save count/ID evidence independently of feature batches."""
    count = archive.fetch_json(base + f"/count_{label}.json", url + "/query",
                               {"where": "1=1", "returnCountOnly": "true", "f": "json"})["count"]
    ids_doc = archive.fetch_json(base + f"/ids_{label}.json", url + "/query",
                                 {"where": "1=1", "returnIdsOnly": "true", "f": "json"})
    ids = ids_doc.get("objectIds")
    if not isinstance(ids, list) or any(type(x) is not int for x in ids):
        raise ValueError("Invalid object-ID response")
    if len(ids) != count or len(set(ids)) != count:
        raise ValueError("Count/ID mismatch or truncated object-ID list")
    return sorted(ids)


def validate_batch(document, expected_ids, oid_field, spatial):
    """Require exact batch membership and reject truncated or malformed data."""
    if document.get("exceededTransferLimit") or (document.get("properties") or {}).get("exceededTransferLimit"):
        raise ValueError("Server truncated a batch")
    if spatial and document.get("type") != "FeatureCollection":
        raise ValueError("Expected GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list):
        raise ValueError("Missing feature/row list")
    key = "properties" if spatial else "attributes"
    actual = [f[key][oid_field] for f in features]
    if len(actual) != len(set(actual)) or set(actual) != set(expected_ids):
        raise ValueError("Duplicate, missing, or unexpected object IDs")
    if spatial:
        for feature in features:
            if feature.get("type") != "Feature" or "geometry" not in feature:
                raise ValueError("Malformed GeoJSON feature")
    return features


def download_layer(archive, item, layer):
    """Export a whole layer/table, preserving batches and checking ID coverage.

    Geometry is requested as WGS 84 without simplification. Raw responses remain
    separately available; table rows retain ArcGIS field types in metadata.
    """
    item_id = item["id"]
    layer_id = layer["id"]
    url = f"{item['url']}/{layer_id}"
    spatial = layer.get("type") != "Table" and bool(layer.get("geometryType"))
    name = f"{layer_id:02d}_{slug(layer['name'])}"
    base = f"{category(item['title'])}/services/{item_id}/{name}"
    previous_metadata_path = archive.root / base / "metadata.json"
    previous_metadata = (json.loads(previous_metadata_path.read_bytes())
                         if previous_metadata_path.is_file() else None)
    metadata = archive.fetch_json(base + "/metadata.json", url + "?f=json")
    if metadata.get("type") == "Group Layer":
        return None
    spatial = bool(metadata.get("geometryType"))
    oid = next(field["name"] for field in metadata["fields"] if field["type"] == "esriFieldTypeOID")
    before = object_ids(archive, base, url, "before")
    checkpoint = archive.root / base / "dataset.json"
    if previous_metadata == metadata and checkpoint.is_file():
        cached = json.loads(checkpoint.read_bytes())
        old_ids = json.loads((archive.root / cached["id_evidence_path"]).read_bytes())["objectIds"]
        records = [cached] + cached["chunks"]
        if (cached["source_url"] == url and cached["record_count"] == len(before) and before == sorted(old_ids)
                and all(safe_path(archive.root, record["path"]).is_file()
                        and all(record[k] == v for k, v in digest_file(safe_path(archive.root, record["path"])).items())
                        for record in records)):
            if before != object_ids(archive, base, url, "after"):
                raise ValueError(f"Source membership changed during revalidation: {url}")
            cached["revalidated_at_utc"] = utc_now()
            write_json(checkpoint, cached)
            print(f"Revalidated {category(item['title'])}/{name}: {len(before):,}", flush=True)
            return cached
    size = min(BATCH_SIZE, metadata.get("maxRecordCount", BATCH_SIZE))
    chunks = []
    null_geometries = 0
    geometry_types = set()
    output = base + ("/features.geojson.gz" if spatial else "/rows.json.gz")
    target = archive.root / output
    pending = target.with_name(target.name + ".download")
    first = True
    started = utc_now()
    with gzip.open(pending, "wt", encoding="utf-8", newline="\n") as stream:
        stream.write('{"type":"FeatureCollection","features":[' if spatial else '{"rows":[')
        for offset in range(0, len(before), size):
            selected = before[offset:offset + size]
            parameters = {"objectIds": ",".join(map(str, selected)), "outFields": "*",
                          "returnGeometry": str(spatial).lower(), "f": "geojson" if spatial else "json"}
            if spatial:
                parameters.update(outSR="4326", returnZ="true", returnM="false")
            chunk_path = base + f"/raw/batch_{offset // size:06d}.json.gz"
            disk = archive.root / chunk_path
            receipt_path = disk.with_name(disk.name + ".receipt.json")
            reused = False
            if disk.is_file() and receipt_path.is_file():
                receipt = json.loads(receipt_path.read_bytes())
                if (receipt["source_url"] == url + "/query" and receipt["parameters"] == parameters
                        and all(receipt[k] == v for k, v in digest_file(disk).items())):
                    raw = gzip.decompress(disk.read_bytes())
                    reused = True
            if not reused:
                raw = request(url + "/query", parameters)
            document = decode_json(raw)
            features = validate_batch(document, selected, oid, spatial)
            if not reused:
                receipt = archive.save(chunk_path, raw, url + "/query", parameters, compress=True)
            chunks.append({"path": chunk_path, "count": len(features), **receipt})
            for feature in features:
                if not first:
                    stream.write(",")
                first = False
                stream.write(json.dumps(feature if spatial else feature["attributes"],
                                        ensure_ascii=False, separators=(",", ":"), allow_nan=False))
                if spatial:
                    if feature["geometry"] is None:
                        null_geometries += 1
                    else:
                        geometry_types.add(feature["geometry"]["type"])
            if offset == 0 or (offset // size + 1) % 50 == 0:
                print(f"{category(item['title'])}/{name}: {offset + len(features):,}/{len(before):,}", flush=True)
        stream.write("]}\n")
    after = object_ids(archive, base, url, "after")
    if before != after:
        raise ValueError(f"Source membership changed during download: {url}")
    os.replace(pending, target)
    entry = {"key": f"{item_id}/{layer_id}", "category": category(item["title"]),
             "service_title": item["title"], "name": layer["name"], "source_url": url,
             "kind": "spatial" if spatial else "table", "path": output, "record_count": len(before),
             "object_id_field": oid, "metadata_path": base + "/metadata.json",
             "id_evidence_path": base + "/ids_after.json", "chunks": chunks,
             "started_at_utc": started, "completed_at_utc": utc_now(),
             "geometry_types": sorted(geometry_types), "null_geometry_count": null_geometries,
             "relationships": metadata.get("relationships", []), **digest_file(target)}
    write_json(archive.root / base / "dataset.json", entry)
    return entry


def inventory_markdown(manifest):
    """Generate a complete regional index with relative links and record counts."""
    lines = ["# Basin Plan offline inventory", "", f"Snapshot: `{manifest['snapshot_id']}`.", "",
             "Counts describe archived source records. Regional and statewide representations overlap;",
             "totals are not counts of unique waterbodies. Spatial files use gzip-compressed GeoJSON.", ""]
    spatial = sum(entry["kind"] == "spatial" for entry in manifest["datasets"])
    tables = len(manifest["datasets"]) - spatial
    native = sum(item["type"] == "File Geodatabase" for item in manifest["items"])
    lines += [f"**{spatial} spatial layers · {tables} tables · {native} native geodatabases**", ""]
    groups = sorted({i["category"] for i in manifest["datasets"]},
                    key=lambda value: (0 if value.startswith("regions/") else 1 if value == "statewide" else 2, value))
    for group in groups:
        lines += [f"## {category_label(group)}", "", f"Directory: `{group}/`.", "",
                  "| Dataset | Records | Data | Fields and relationships |", "| --- | ---: | --- | --- |"]
        for entry in manifest["datasets"]:
            if entry["category"] == group:
                format_name = "GeoJSON (.gz)" if entry["kind"] == "spatial" else "Table JSON (.gz)"
                lines.append(f"| {entry['name']} | {entry['record_count']:,} | [{format_name}]({entry['path']}) "
                             f"| [Layer metadata]({entry['metadata_path']}) |")
        for item in manifest["items"]:
            if category(item["title"]) == group and item["type"] == "File Geodatabase":
                lines += ["", f"Native archive: [{item['title']}]({group}/native/{item['id']}.zip)."]
        lines.append("")
    lines += ["## Published items", "", "| Title | Type | Category |", "| --- | --- | --- |"]
    for item in manifest["items"]:
        path = f"{category(item['title'])}/metadata/items/{item['id']}/item.json"
        lines.append(f"| [{item['title']}]({path}) | {item['type']} | {category(item['title'])} |")
    lines += ["", "## Acquisition failures", ""]
    lines += [f"- {e['task']}: {e['error']}" for e in manifest["errors"]] or ["None."]
    return "\n".join(lines) + "\n"


def refresh(root=ROOT, resume=None, workers=WORKERS):
    """Discover and download everything, publishing only a complete generation."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".refresh.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(f"PID {os.getpid()}\n")
    try:
        snapshot_id = resume or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", snapshot_id):
            raise ValueError("Invalid snapshot identifier")
        pending = root / "snapshots" / (".pending-" + snapshot_id)
        if resume and not pending.is_dir():
            raise ValueError("Requested pending snapshot does not exist")
        pending.mkdir(parents=True, exist_ok=True)
        archive = Archive(pending)
        print(f"Snapshot {snapshot_id}; pending directory: {pending}", flush=True)
        items = discover(archive)
        manifest = {"schema_version": 1, "snapshot_id": snapshot_id, "created_at_utc": utc_now(),
                    "landing_url": LANDING, "group_id": GROUP_ID, "items": items,
                    "datasets": [], "errors": [], "limitations": [
                        "Counts and IDs establish membership completeness, not a transactional snapshot of attribute edits.",
                        "Resumed runs may retain earlier verified batches and native downloads; receipts retain their timestamps.",
                        "GeoJSON requests use WGS 84, preserve available Z, and omit M; native archives retain their published schema.",
                        "No geometry repair or simplification is performed. Dataset vintages may differ.",
                        "BPMP is informational and is not a substitute for the applicable Basin Plan."]}
        jobs = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for item in items:
                jobs.append((pool.submit(archive_item, archive, item), "item " + item["title"]))
                if item["type"] in ("Feature Service", "Map Service"):
                    base = f"{category(item['title'])}/services/{item['id']}"
                    service = archive.fetch_json(base + "/service.json", item["url"] + "?f=json")
                    for layer in service.get("layers", []) + service.get("tables", []):
                        jobs.append((pool.submit(download_layer, archive, item, layer),
                                     item["title"] + "/" + layer["name"]))
            tasks = dict(jobs)
            for future in as_completed(tasks):
                try:
                    entry = future.result()
                    if entry:
                        manifest["datasets"].append(entry)
                except Exception as error:
                    print(f"FAILED {tasks[future]}: {error}", flush=True)
                    manifest["errors"].append({"task": tasks[future], "error": str(error)})
                write_json(pending / "progress.json", manifest)
        # Save the landing page and its directly linked documentation PDFs.
        try:
            raw = request(LANDING)
            archive.save("documentation/basin_plan_portal.html", raw, LANDING)
            for link in re.findall(r'href=[\"\']([^\"\']+\.pdf)[\"\']', raw.decode("utf-8"), re.I):
                url = urljoin(LANDING, html.unescape(link))
                archive.fetch_binary("documentation/" + url.rsplit("/", 1)[-1], url)
        except Exception as error:
            manifest["errors"].append({"task": "documentation", "error": str(error)})
        manifest["datasets"].sort(key=lambda e: (e["category"], e["key"]))
        manifest["completed_at_utc"] = utc_now()
        manifest["complete"] = not manifest["errors"]
        (pending / "INVENTORY.md").write_text(inventory_markdown(manifest), encoding="utf-8")
        manifest["files"] = {p.relative_to(pending).as_posix(): digest_file(p)
                             for p in sorted(pending.rglob("*")) if p.is_file()
                             and p.name not in ("manifest.json", "progress.json")
                             and not p.name.endswith(".download")}
        write_json(pending / "manifest.json", manifest)
        if manifest["errors"]:
            raise RuntimeError(f"{len(manifest['errors'])} acquisition tasks failed; resume with --resume {snapshot_id}")
        final = root / "snapshots" / snapshot_id
        # Readable copies and catalogs must succeed before the active generation changes.
        organization = organize.build_organization(root, pending, manifest, snapshot=final)
        pending.rename(final)
        write_json(root / "sources.json", {"schema_version": 1, "snapshot_id": snapshot_id,
                   "manifest_path": f"snapshots/{snapshot_id}/manifest.json",
                   "manifest_sha256": digest_file(final / "manifest.json")["sha256"],
                   "dataset_count": len(manifest["datasets"]), "updated_at_utc": utc_now(), **organization})
        organize.publish_review_index(root, organization)
        index = inventory_markdown(manifest)
        index = re.sub(r"\]\(([^)]+)\)",
                       lambda match: f"](snapshots/{snapshot_id}/{match[1]})", index)
        (root / "INVENTORY.md").write_text(index, encoding="utf-8")
        print(f"Published {len(manifest['datasets'])} datasets; inventory: {final / 'INVENTORY.md'}", flush=True)
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--resume", help="Identifier of an interrupted pending snapshot")
    parser.add_argument("--workers", type=int, default=WORKERS, choices=range(1, 5))
    args = parser.parse_args()
    refresh(args.directory, args.resume, args.workers)
