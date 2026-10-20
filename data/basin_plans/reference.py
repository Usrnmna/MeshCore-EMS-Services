"""Read and verify the Basin Plan archive offline, without network fallbacks."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def safe_path(root, relative):
    """Resolve a manifest path only within its snapshot directory."""
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f"Path leaves the snapshot: {relative}")
    return path


def verify_file(path, metadata):
    """Raise on a missing file, unexpected length, or SHA-256 mismatch."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if path.stat().st_size != metadata["byte_count"] or digest.hexdigest() != metadata["sha256"]:
        raise ValueError(f"Checksum or size mismatch: {path}")


def open_snapshot(directory=ROOT):
    """Return the active snapshot directory and its checksum-verified manifest."""
    directory = Path(directory).resolve()
    pointer = json.loads((directory / "sources.json").read_bytes())
    path = safe_path(directory, pointer["manifest_path"])
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pointer["manifest_sha256"]:
        raise ValueError("Manifest checksum mismatch")
    manifest = json.loads(raw)
    if not manifest.get("complete") or manifest["snapshot_id"] != pointer["snapshot_id"]:
        raise ValueError("Incomplete snapshot or mismatched generation")
    return path.parent, manifest


def load_manifest(directory=ROOT):
    """Read active snapshot provenance and the complete categorized inventory."""
    return open_snapshot(directory)[1]


def iter_records(key, directory=ROOT):
    """Yield verified spatial features or table dictionaries one batch at a time.

    Keys are service-item-ID/layer-ID pairs listed in the manifest. Iteration
    preserves source batch order and avoids loading an entire regional layer.
    Membership validation completes only when the iterator is exhausted.
    """
    root, manifest = open_snapshot(directory)
    entry = next((e for e in manifest["datasets"] if e["key"] == key), None)
    if entry is None:
        raise KeyError(key)
    yield from iter_snapshot_records(root, entry, manifest)


def iter_snapshot_records(root, entry, manifest):
    """Read an explicit snapshot, including an unpublished refresh, with full ID validation."""
    key = entry["key"]
    evidence_path = safe_path(root, entry["id_evidence_path"])
    verify_file(evidence_path, manifest["files"][entry["id_evidence_path"]])
    expected = set(json.loads(evidence_path.read_bytes())["objectIds"])
    seen = set()
    for chunk in entry["chunks"]:
        path = safe_path(root, chunk["path"])
        verify_file(path, chunk)
        with gzip.open(path, "rb") as stream:
            raw = stream.read()
        if hashlib.sha256(raw).hexdigest() != chunk["raw_sha256"]:
            raise ValueError(f"Raw response checksum mismatch: {path}")
        document = json.loads(raw)
        if "error" in document:
            raise ValueError(f"Archived ArcGIS error: {path}")
        features = document["features"]
        if len(features) != chunk["count"]:
            raise ValueError(f"Batch count mismatch: {path}")
        for feature in features:
            attributes = feature["properties"] if entry["kind"] == "spatial" else feature["attributes"]
            identifier = attributes[entry["object_id_field"]]
            if identifier in seen or identifier not in expected:
                raise ValueError(f"Duplicate or unexpected ID {identifier}: {path}")
            seen.add(identifier)
            yield feature if entry["kind"] == "spatial" else attributes
    if seen != expected or len(seen) != entry["record_count"]:
        raise ValueError(f"Incomplete dataset: {key}")


def verify_files(directory=ROOT, records=False):
    """Check every indexed file; optionally validate all archived record IDs."""
    root, manifest = open_snapshot(directory)
    for relative, metadata in manifest["files"].items():
        verify_file(safe_path(root, relative), metadata)
    total = 0
    if records:
        for entry in manifest["datasets"]:
            count = sum(1 for _ in iter_records(entry["key"], directory))
            total += count
            print(f"Verified {entry['category']}/{entry['name']}: {count:,}", flush=True)
    return {"files": len(manifest["files"]), "datasets": len(manifest["datasets"]),
            "records_checked": total}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--records", action="store_true", help="Also verify every archived record ID")
    arguments = parser.parse_args()
    print(json.dumps(verify_files(arguments.directory, arguments.records), indent=2))
