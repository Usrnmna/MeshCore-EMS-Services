"""Resolve a single installed dataset generation without changing local files.

Registry reads pin each operation to one generation. Failed acquisition never
changes this registry; explicit removal prevents fallback to bundled snapshots.
"""

import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath


def data_root():
    """Return the shared persistent dataset root selected by the service environment."""
    if os.environ.get("MESHCORE_DATA_DIR"):
        return Path(os.environ["MESHCORE_DATA_DIR"]).resolve()
    if os.environ.get("MESHCORE_RUNTIME_DIR"):
        return (Path(os.environ["MESHCORE_RUNTIME_DIR"]).parent / "data").resolve()
    if os.name == "nt":
        return (Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MeshCore-EMS" / "data").resolve()
    return Path("/var/lib/meshcore-ems/data")


def checked_path(root, relative):
    """Reject absolute, traversing, or symlink-escaping registry paths."""
    if not isinstance(relative, str) or not relative:
        raise ValueError("Invalid installed dataset path")
    windows = PureWindowsPath(relative)
    portable = PurePosixPath(relative.replace("\\", "/"))
    if windows.drive or windows.root or portable.is_absolute() or ".." in portable.parts:
        raise ValueError("Installed dataset path escapes its root")
    resolved = (root / Path(*portable.parts)).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Installed dataset path escapes its root")
    return resolved


def resolve(dataset, fallback, *, configured=None, defaults=()):
    """Select an active generation, preserving an explicit external data path.

    Paths matching a shipped default or the persistent collection alias
    participate in managed discovery. Other configured paths remain authoritative.
    An absent registry entry retains legacy/source-checkout behavior; an explicit
    inactive entry or an invalid registry fails visibly instead of resurrecting data.
    """
    root = data_root()
    fallback = Path(fallback).resolve()
    if configured is not None:
        configured = Path(configured).resolve()
        known = {Path(path).resolve() for path in defaults}
        if configured not in known and configured != root / dataset:
            return configured
        fallback = configured
    registry_path = checked_path(root, "datasets.json")
    if not registry_path.exists():
        return fallback
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("schema") != 1 or not isinstance(registry.get("datasets"), dict):
        raise ValueError("Unsupported installed dataset registry")
    entry = registry["datasets"].get(dataset)
    if entry is None:
        return fallback
    if not isinstance(entry, dict):
        raise ValueError("Invalid installed dataset entry: " + dataset)
    active = entry.get("active")
    if active is None:
        raise FileNotFoundError("Dataset is not installed: " + dataset)
    if not isinstance(active, dict):
        raise ValueError("Invalid active dataset generation: " + dataset)
    selected = checked_path(root, active.get("path"))
    if not selected.is_dir():
        raise FileNotFoundError("Active dataset directory is missing: " + dataset)
    return selected
