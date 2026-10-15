"""Read verified California State Parks snapshots without network access.

Paths are relative to this module by default. Native download archives and
service metadata are indexed separately in sources.json. Geometry is never
repaired, filtered, or reprojected by this loader.
"""

from pathlib import Path
import hashlib
import json


DATA_DIRECTORY = Path(__file__).resolve().parent


def load_manifest(data_directory=DATA_DIRECTORY):
    """Return local source metadata from the selected snapshot directory."""
    return json.loads((Path(data_directory) / "sources.json").read_bytes())


def load_dataset(name, data_directory=DATA_DIRECTORY):
    """Return one GeoJSON collection after verifying its hash, count, and IDs.

    Name must be a dataset key in sources.json. Missing files, changed bytes,
    duplicate IDs, or inconsistent counts raise an exception. Geometry
    is returned as stored; any prior local repairs are recorded in the manifest.
    """
    root = Path(data_directory).resolve()
    metadata = load_manifest(root)["datasets"][name]
    path = (root / metadata["path"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Dataset path leaves the reference directory")
    raw = path.read_bytes()
    if len(raw) != metadata["byte_count"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
        raise ValueError(f"Dataset checksum or size mismatch: {name}")
    collection = json.loads(raw)
    if collection.get("type") != "FeatureCollection":
        raise ValueError(f"Expected GeoJSON FeatureCollection: {name}")
    features = collection["features"]
    identifiers = [feature["properties"][metadata["object_id_field"]] for feature in features]
    if len(features) != metadata["feature_count"] or len(set(identifiers)) != len(features):
        raise ValueError(f"Dataset count or object-ID mismatch: {name}")
    return collection


def verify_files(data_directory=DATA_DIRECTORY):
    """Verify every indexed archive, response, metadata file, and GeoJSON copy.

    Return the number of verified files. Raise ValueError at the first checksum
    or path failure. This checks local integrity, not remote data currency.
    """
    root = Path(data_directory).resolve()
    manifest = load_manifest(root)
    for relative, metadata in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Reference path leaves the data directory: {relative}")
        raw = path.read_bytes()
        if len(raw) != metadata["byte_count"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
            raise ValueError(f"Reference checksum or size mismatch: {relative}")
    return len(manifest["files"])


if __name__ == "__main__":
    print(f"Verified {verify_files()} local reference files.")
    for dataset_name in load_manifest()["datasets"]:
        print(f"{dataset_name}: {len(load_dataset(dataset_name)['features'])} features")
