"""Immutable flood-reference generations, HTTP receipts, and verified offline reads."""

from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parent

# Shared publication contracts include the existing USGS maintenance generations.
GENERATION_KINDS = frozenset({
    "static", "observations", "inventory", "network", "routing",
    "link_review", "agency_review", "local_review",
})


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open("rb") as stream:
        return {"sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
                "byte_count": Path(path).stat().st_size}


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f"Path outside generation: {relative}")
    return path


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)


def read_json(path):
    raw = Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if Path(path).suffix == ".gz" else raw)


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


class AcquisitionBudget:
    """Share finite request, response, feature and wall-time limits across a batch.

    Defaults match a small reviewed batch. Constructing a budget is not acquisition
    authorization; the maintenance caller must supply the reviewed source scope.
    """

    def __init__(self, requests=40, total_bytes=32*1024*1024, response_bytes=8*1024*1024,
                 features=512, seconds=180, retries=2):
        values = (requests, total_bytes, response_bytes, features, seconds)
        if any(type(v) is not int or v <= 0 for v in values) or type(retries) is not int or not 0 <= retries <= 2:
            raise ValueError('Invalid acquisition limits')
        self.requests = requests
        self.remaining_bytes = total_bytes
        self.response_bytes = min(response_bytes, total_bytes)
        self.features = features
        self.until = time.monotonic() + seconds
        self.retries = retries

    def tick(self):
        """Reject an expired batch before requests and between streamed chunks."""
        remaining = self.until-time.monotonic()
        if remaining <= 0:
            raise ValueError('Acquisition duration limit')
        return remaining

    def request(self):
        remaining = self.tick()
        if self.requests <= 0:
            raise ValueError('Acquisition request limit')
        self.requests -= 1
        return min(45, remaining)

    def read(self, response):
        """Bound raw response memory, including bytes consumed by failed attempts."""
        chunks, size = [], 0
        while True:
            self.tick()
            chunk = response.read(min(65536, self.response_bytes-size+1, self.remaining_bytes+1))
            self.tick()
            if not chunk:
                return b''.join(chunks)
            size += len(chunk)
            self.remaining_bytes -= len(chunk)
            if size > self.response_bytes or self.remaining_bytes < 0:
                raise ValueError('Acquisition byte limit')
            chunks.append(chunk)


def fetch(stage, name, url, params=None, *, budget=None):
    """Archive exact response bytes and request provenance; reject API errors.

    GET requests use bounded retries. A failed build retains its pending evidence
    and never replaces the active pointer. Content is compressed losslessly.
    """
    budget = budget or AcquisitionBudget()
    if not re.fullmatch(r'[A-Za-z0-9_]+', name):
        raise ValueError('Invalid acquisition artifact name')
    path = safe_path(stage, f"raw/{name}.json.gz")
    receipt_path = safe_path(stage, f"raw/{name}.receipt.json")
    if path.exists() or receipt_path.exists():
        raise ValueError('Original acquisition artifacts already exist')
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    for attempt in range(budget.retries+1):
        try:
            request = Request(url, headers={"User-Agent": "MC-EMS-offline-flood-reference/1.0"})
            with urlopen(request, timeout=budget.request()) as response:
                raw = budget.read(response)
                headers = dict(response.headers)
            break
        except (URLError, TimeoutError, HTTPError):
            if attempt == budget.retries:
                raise
            time.sleep(min(attempt + 1, budget.tick()))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(gzip.compress(raw, mtime=0))
    write_json(receipt_path, {
        "url": url, "retrieved_at_utc": utc_now(), "response_headers": headers,
        "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_byte_count": len(raw),
        **digest(path),
    })
    document = json.loads(raw)
    if isinstance(document, dict) and ("error" in document or document.get("exceededTransferLimit")):
        raise ValueError(f"API error or truncated response: {url}")
    return document


def arcgis(stage, name, layer_url, where, *, budget=None):
    """Export an exact ID set in bounded batches, retaining metadata and ID evidence."""
    budget = budget or AcquisitionBudget()
    metadata = fetch(stage, name + "_metadata", layer_url, {"f": "json"}, budget=budget)
    oid = metadata["objectIdField"]
    ids = fetch(stage, name + "_ids", layer_url + "/query",
                {"f": "json", "where": where, "returnIdsOnly": "true"}, budget=budget).get("objectIds")
    if not isinstance(ids, list) or any(type(i) is not int or i < 0 for i in ids):
        raise ValueError('Missing or invalid ArcGIS ID inventory')
    if len(ids) > budget.features:
        raise ValueError('Acquisition feature limit')
    budget.features -= len(ids)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate ArcGIS object IDs")
    features = []
    for offset in range(0, len(ids), 100):
        data = fetch(stage, f"{name}_batch_{offset:06}", layer_url + "/query", {
            "f": "geojson", "objectIds": ",".join(map(str, sorted(ids)[offset:offset + 100])),
            "outFields": "*", "outSR": 4326, "returnGeometry": "true",
        }, budget=budget)
        if not isinstance(data.get('features'), list) or len(data['features']) > min(100, len(ids)-offset):
            raise ValueError('Invalid or excessive ArcGIS features')
        # outSR requests do not prove that the provider returned the requested CRS.
        if data.get('crs') not in (None,
                {'type': 'name', 'properties': {'name': 'EPSG:4326'}},
                {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'}}):
            raise ValueError('Unsupported ArcGIS response CRS')
        for feature in data['features']:
            geometry = feature.get('geometry')
            if 'crs' in feature or isinstance(geometry, dict) and 'crs' in geometry:
                raise ValueError('Nested ArcGIS response CRS is unsupported')
        features.extend(data["features"])
    actual = [feature["properties"][oid] for feature in features]
    if any(type(i) is not int for i in actual) or len(actual) != len(ids) or set(actual) != set(ids):
        raise ValueError(f"Incomplete ArcGIS export: {name}")
    result = {"type": "FeatureCollection", "features": features}
    write_json(stage / f"inputs/{name}.geojson.gz", result)
    return result


@contextmanager
def build_lock(root):
    """Prevent concurrent pointer publication; never remove another process's lock."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".refresh.lock"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(f"pid={os.getpid()} started={utc_now()}\n")
    try:
        yield
    finally:
        path.unlink()


def begin(root, kind):
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex[:8]
    stage = root / kind / (".pending-" + identifier)
    stage.mkdir(parents=True)
    return stage, identifier


def generation_files(stage):
    """Hash isolated regular artifacts; reject links before any validator can write.

    Candidate files must not alias retained generations or external source files.
    The manifest is checked for aliases too, before its contents are replaced.
    """
    files = {}
    for path in sorted(stage.rglob('*')):
        if (path.is_symlink() or getattr(path, 'is_junction', lambda: False)()
                or path.is_file() and path.stat().st_nlink > 1):
            raise ValueError('Candidate contains linked artifacts')
        relative = path.relative_to(stage).as_posix()
        safe_path(stage, relative)
        if path.is_file() and relative != 'manifest.json':
            files[relative] = digest(path)
    return files


def publish(root, stage, identifier, kind, details, *, activate=True, validator=None):
    """Seal hashed artifacts, optionally validate, then optionally replace the active pointer.

    Detached candidates use the existing generation layout without changing readers.
    Validation cannot alter artifacts or reserved manifest identity fields.
    """
    if set(details) & {'schema_version', 'generation', 'kind', 'complete', 'created_at_utc', 'files'}:
        raise ValueError('Reserved generation identity fields')
    if (not re.fullmatch(r'[A-Za-z0-9_-]+', identifier) or kind not in GENERATION_KINDS
            or stage.is_symlink() or getattr(stage, 'is_junction', lambda: False)()
            or stage.resolve() != (root/kind/('.pending-'+identifier)).resolve()):
        raise ValueError('Publication requires its isolated pending generation')
    files = generation_files(stage)
    manifest = {"schema_version": 1, "generation": identifier, "kind": kind,
                "complete": True, "created_at_utc": utc_now(), **details, "files": files}
    write_json(stage / "manifest.json", manifest)
    expected_manifest = (stage/'manifest.json').read_bytes()
    if validator is not None:
        validator(stage, manifest)
    # Validators receive a mutable dictionary; it is not the independent baseline.
    manifest = json.loads(expected_manifest)
    files = manifest['files']
    actual = generation_files(stage)
    if actual != files or (stage/'manifest.json').read_bytes() != expected_manifest:
        raise ValueError('Candidate changed during validation')
    target = root / kind / identifier
    for attempt in range(5):
        try:
            stage.rename(target)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))
    pointer = {"manifest_path": f"{kind}/{identifier}/manifest.json", **digest(target / "manifest.json")}
    if not activate:
        return target, manifest
    temporary = root / (kind + ".download")
    write_json(temporary, pointer)
    os.replace(temporary, root / (kind + ".json"))
    return target, manifest


def open_generation(root, kind="static", pointer=None):
    """Verify the pointer and all files before offline analysis; no network fallback."""
    pointer = pointer or read_json(Path(root) / (kind + ".json"))
    path = safe_path(root, pointer["manifest_path"])
    if digest(path) != {k: pointer[k] for k in ("sha256", "byte_count")}:
        raise ValueError("Manifest checksum mismatch")
    manifest = read_json(path)
    if not manifest.get("complete") or manifest["kind"] != kind:
        raise ValueError("Incomplete or incorrect generation")
    for relative, expected in manifest["files"].items():
        if digest(safe_path(path.parent, relative)) != expected:
            raise ValueError(f"Artifact checksum mismatch: {relative}")
    return path.parent, manifest
