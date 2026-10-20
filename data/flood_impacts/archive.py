"""Immutable flood-reference generations, HTTP receipts, and verified offline reads."""

from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parent


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


def fetch(stage, name, url, params=None):
    """Archive exact response bytes and request provenance; reject API errors.

    GET requests use bounded retries. A failed build retains its pending evidence
    and never replaces the active pointer. Content is compressed losslessly.
    """
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "MC-EMS-offline-flood-reference/1.0"})
            with urlopen(request, timeout=45) as response:
                raw = response.read()
                headers = dict(response.headers)
            break
        except (URLError, TimeoutError, HTTPError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    path = safe_path(stage, f"raw/{name}.json.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, mtime=0))
    write_json(stage / f"raw/{name}.receipt.json", {
        "url": url, "retrieved_at_utc": utc_now(), "response_headers": headers,
        "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_byte_count": len(raw),
        **digest(path),
    })
    document = json.loads(raw)
    if isinstance(document, dict) and ("error" in document or document.get("exceededTransferLimit")):
        raise ValueError(f"API error or truncated response: {url}")
    return document


def arcgis(stage, name, layer_url, where):
    """Export an exact ID set in bounded batches, retaining metadata and ID evidence."""
    metadata = fetch(stage, name + "_metadata", layer_url, {"f": "json"})
    oid = metadata["objectIdField"]
    ids = fetch(stage, name + "_ids", layer_url + "/query",
                {"f": "json", "where": where, "returnIdsOnly": "true"}).get("objectIds") or []
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate ArcGIS object IDs")
    features = []
    for offset in range(0, len(ids), 100):
        data = fetch(stage, f"{name}_batch_{offset:06}", layer_url + "/query", {
            "f": "geojson", "objectIds": ",".join(map(str, sorted(ids)[offset:offset + 100])),
            "outFields": "*", "outSR": 4326, "returnGeometry": "true",
        })
        features.extend(data["features"])
    actual = [feature["properties"][oid] for feature in features]
    if len(actual) != len(ids) or set(actual) != set(ids):
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


def publish(root, stage, identifier, kind, details):
    """Publish only after every artifact is written and hashed; preserve older generations."""
    files = {p.relative_to(stage).as_posix(): digest(p) for p in sorted(stage.rglob("*")) if p.is_file()}
    manifest = {"schema_version": 1, "generation": identifier, "kind": kind,
                "complete": True, "created_at_utc": utc_now(), **details, "files": files}
    write_json(stage / "manifest.json", manifest)
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
