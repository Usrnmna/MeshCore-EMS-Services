"""Read-only status of selected dataset generations and existing wildfire cache."""
import json
import math
import re
from pathlib import Path
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from response_text import compact_fields
from dataset_paths import data_root, checked_path
from data_reporting import Budget, IntegrityFailure, VerificationLimit, verify_files, observation_status

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATASETS = ("ebmud", "basin_plans", "flood_impacts", "usgs_water", "wildfire", "landslide", "california_state_parks", "satellites")
DEPENDENCIES = {"flood_impacts": {"basin_plans"}, "usgs_water": {"basin_plans", "flood_impacts"}}
ALIASES = {"parks": "california_state_parks", "water": "usgs_water", "flood": "flood_impacts", "basin": "basin_plans", "satellite": "satellites"}


def read_json(path):
    """Read bounded metadata without modifying or creating any files."""
    if path.stat().st_size > 8 * 1024 * 1024:
        raise VerificationLimit("Metadata too large")
    with path.open("rb") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("Metadata must be an object")
    return value


def receipt_for(root, name, record):
    """Validate a generation's receipt identity and return its pinned metadata."""
    if not isinstance(record, dict):
        raise ValueError("Invalid selection")
    content = checked_path(root, record["path"])
    parts = Path(record["path"].replace("\\", "/")).parts
    if len(parts) != 4 or parts[:2] != (".datasets", name) or parts[-1] != "content":
        raise ValueError("Invalid generation")
    receipt_path = checked_path(root, record["receipt"])
    if receipt_path != content.parent / "receipt.json":
        raise ValueError("Invalid receipt")
    if not content.is_dir():
        raise FileNotFoundError("Missing content")
    receipt = read_json(receipt_path)
    if receipt.get("schema") != 1 or receipt.get("dataset") != name or receipt.get("path") != record["path"] or not isinstance(receipt.get("dependencies"), dict) or not isinstance(receipt.get("files"), dict):
        raise ValueError("Invalid receipt identity")
    return content, receipt



def reporting_root(name):
    """Honor the independent catalog's typed shared-root setting when present."""
    if name == "satellites" and (ROOT / "satellite-settings.json").is_file() and (ROOT / "config.json").is_file():
        value = read_json(ROOT / "config.json").get("dataset_root")
        if value is not None:
            if not isinstance(value, str) or not Path(value).is_absolute() or ".datasets" in Path(value).parts:
                raise ValueError("Invalid satellite root")
            return Path(value).resolve()
    return data_root()


def configured_directory(name):
    """Use the same authoritative custom paths as existing service readers."""
    root = ROOT
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    if name == "ebmud":
        from scripts.gis_data import load_settings
        return load_settings()["data_directory"]
    if name in {"usgs_water", "basin_plans", "flood_impacts"}:
        from scripts.water_settings import load, collection, data_root as water_root
        config = load()
        if name == "usgs_water":
            return collection(config)
        from dataset_paths import resolve
        fallback = water_root(config) / name
        return resolve(name, fallback, configured=fallback, defaults=(root / "../data" / name,))
    if name == "satellites" and (root / "satellite-settings.json").is_file():
        settings = read_json(root / "satellite-settings.json")
        configured = (root / settings["database"]).resolve().parent
        shared = reporting_root(name)
        defaults = {data_root() / name, root.parent / "data" / name, shared / name}
        if configured not in defaults:
            return configured
        registry_path = checked_path(shared, "datasets.json")
        if registry_path.exists():
            registry = read_json(registry_path)
            if registry.get("schema") != 1 or not isinstance(registry.get("datasets"), dict):
                raise ValueError("Invalid satellite registry")
            entry = registry["datasets"].get(name)
            if entry is not None:
                if not isinstance(entry, dict) or "active" not in entry:
                    raise ValueError("Invalid satellite entry")
                if entry["active"] is None:
                    raise FileNotFoundError("Dataset is not installed: satellites")
                return checked_path(shared, entry["active"]["path"])
        return configured
    from dataset_paths import resolve
    fallback = root / "data" / name if name in {"wildfire", "landslide"} else root.parent / "data" / name
    return resolve(name, fallback)


def reference_status(name, directory):
    """Verify an unmanaged/custom reference using its published local manifest."""
    if not directory.is_dir():
        return name + ": data absent"
    budget = Budget()
    filename = {"wildfire": "manifest.json", "landslide": "manifest.json", "flood_impacts": "static.json", "usgs_water": "inventory.json", "satellites": "coverage.json"}.get(name, "sources.json")
    manifest = read_json(directory / filename)
    if "manifest_path" in manifest:
        target = checked_path(directory, manifest["manifest_path"])
        expected = dict(manifest)
        expected.setdefault("sha256", manifest.get("manifest_sha256"))
        expected.setdefault("byte_count", target.stat().st_size)
        budget.verify(directory, manifest["manifest_path"], expected)
        manifest = read_json(target)
        directory = target.parent
    if name in {"wildfire", "landslide"}:
        hashes = manifest["sha256"]
        hashes = {"zones.geojson": hashes} if isinstance(hashes, str) else hashes
        if not isinstance(hashes, dict) or not hashes:
            raise IntegrityFailure("Invalid reference hashes")
        for relative, digest in hashes.items():
            file = checked_path(directory, relative)
            budget.verify(directory, relative, {"sha256": digest, "bytes": file.stat().st_size})
        fetched = manifest.get("retrieved_at")
        if isinstance(fetched, (int, float)) and math.isfinite(fetched) and 0 < fetched <= datetime.now(timezone.utc).timestamp():
            return name + ": hashes checked; acquired " + datetime.fromtimestamp(fetched, timezone.utc).strftime("%Y-%m-%d")
        return name + ": reference hashes checked"
    files = manifest.get("files")
    if files:
        verify_files(directory, files, budget)
    elif isinstance(manifest.get("datasets"), dict) and manifest["datasets"]:
        for entry in manifest["datasets"].values():
            if not isinstance(entry, dict):
                raise IntegrityFailure("Invalid reference entry")
            budget.verify(directory, entry["path"], entry)
    else:
        return name + ": reference present; integrity unverified"
    dates = [entry.get("retrieved_at_utc") for entry in manifest.get("datasets", {}).values() if isinstance(entry, dict)] if isinstance(manifest.get("datasets"), dict) else []
    dates += [manifest.get("retrieved_at_utc")]
    parsed = []
    for value in dates:
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("Invalid acquisition time")
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if date.utcoffset() is None:
                raise ValueError("Undated acquisition timezone")
            parsed.append(date.astimezone(timezone.utc).strftime("%Y-%m-%d"))
    dates = parsed
    return name + ": hashes checked" + ("; acquired " + min(dates) if dates else "; acquisition unknown")


def dataset_status(name, root=None):
    """Report selected metadata and pinned prerequisites without claiming full integrity."""
    explicit_root = root is not None
    try:
        root = Path(root if explicit_root else reporting_root(name)).resolve()
        if not explicit_root:
            selected = configured_directory(name)
            if not selected.is_relative_to(root / ".datasets" / name):
                return reference_status(name, selected)
        registry_path = checked_path(root, "datasets.json")
        registry_before = read_json(registry_path) if registry_path.exists() else None
        if registry_before is not None and (registry_before.get("schema") != 1 or not isinstance(registry_before.get("datasets"), dict)):
            raise ValueError("Invalid registry")
        if not explicit_root:
            entry_before = (registry_before or {}).get("datasets", {}).get(name)
            active = entry_before.get("active") if isinstance(entry_before, dict) else None
            if active is None or selected != checked_path(root, active["path"]):
                return reference_status(name, selected)
        registry_path = checked_path(root, "datasets.json")
        if not registry_path.exists():
            return name + ": registry absent; status unknown"
        registry = read_json(registry_path)
        if registry.get("schema") != 1 or not isinstance(registry.get("datasets"), dict):
            raise ValueError("Invalid registry")
        entry = registry["datasets"].get(name)
        if entry is None:
            return name + ": not registered; status unknown"
        if not isinstance(entry, dict) or "active" not in entry:
            raise ValueError("Invalid entry")
        if entry["active"] is None:
            return name + ": explicitly uninstalled"
        content, receipt = receipt_for(root, name, entry["active"])
        budget = Budget()
        if set(receipt["dependencies"]) != DEPENDENCIES.get(name, set()):
            return name + ": invalid dependency metadata"
        for dep, pin in receipt["dependencies"].items():
            if dep not in DATASETS:
                raise ValueError("Invalid dependency")
            try:
                dep_content, dep_receipt = receipt_for(root, dep, pin)
                if set(dep_receipt["dependencies"]) != DEPENDENCIES.get(dep, set()):
                    return name + ": invalid pinned dependency metadata"
                verify_files(dep_content, dep_receipt["files"], budget)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                if isinstance(exc, (IntegrityFailure, VerificationLimit)):
                    raise
                return name + ": pinned dependency unavailable"
            for ancestor, inherited in dep_receipt["dependencies"].items():
                if ancestor in receipt["dependencies"] and receipt["dependencies"][ancestor] != inherited:
                    return name + ": incompatible pinned dependencies"
        verify_files(content, receipt["files"], budget)
        if read_json(registry_path) != registry_before:
            return name + ": selection changed; retry"
        stamp = receipt.get("installed_at")
        if not isinstance(stamp, str):
            raise ValueError("Missing acquisition time")
        date = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if date.utcoffset() is None:
            raise ValueError("Missing timezone")
        return name + ": installed " + date.astimezone(timezone.utc).strftime("%Y-%m-%d") + "Z; hashes checked"
    except IntegrityFailure:
        return name + ": integrity failed"
    except VerificationLimit:
        return name + ": verification incomplete (bounded)"
    except FileNotFoundError as exc:
        return name + (": explicitly uninstalled" if str(exc).startswith("Dataset is not installed:") else ": data or metadata missing")
    except PermissionError:
        return name + ": metadata unreadable"
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return name + ": invalid metadata; integrity unverified"


def source_status(category):
    """Read one existing wildfire source snapshot without refreshing it."""
    from wildfire_settings import database_path, load
    if category.casefold().startswith("fwf:"):
        category = "fwf:" + category[4:].upper()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}|fwf:[A-Za-z0-9_-]{1,12}", category):
        return "Use !data source wildfire CATEGORY"
    try:
        settings = load()
        path = database_path().resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Invalid cache")
            row = db.execute("SELECT fetched,error FROM snapshots WHERE source=?", (category,)).fetchone()
        if row and row[1]:
            return "wildfire " + category + ": refresh failed"
        if not row or row[0] is None:
            return "wildfire " + category + ": not initialized"
        fetched = float(row[0]); now = datetime.now(timezone.utc).timestamp()
        if not math.isfinite(fetched) or not 0 <= fetched <= now + 60:
            return "wildfire " + category + ": invalid source time"
        age = max(0, int(now - fetched))
        limit = settings["boundary_interval"] * 2 if category == "zones" else settings["stale_after"]
        return "wildfire " + category + ": " + ("stale" if age > limit else "cached") + "; age " + str(age // 60) + " min"
    except (OSError, ValueError, TypeError, OverflowError, sqlite3.Error):
        return "wildfire cache unavailable"


def point_cache_status(kind):
    """Summarize cache age/error counts without disclosing point keys or bodies."""
    if kind == "water":
        from scripts.water_settings import load, runtime
        path, table = runtime() / "water_current.sqlite3", "current"
    else:
        from scripts.landslide_settings import load, database_path
        path, table = database_path(), "points"
    try:
        ttl = load()["cache_seconds"]
        now = datetime.now(timezone.utc).timestamp()
        fresh = stale = failed = 0
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            # Table names are fixed above, never obtained from radio input.
            for fetched, error in db.execute("SELECT fetched,error FROM " + table + " LIMIT 10001"):
                if fresh + stale + failed >= 10000:
                    return kind + ": cache report exceeds bound"
                if error or fetched is None:
                    failed += 1
                elif not isinstance(fetched, (int, float)) or not 0 <= fetched <= now + 60:
                    failed += 1
                elif now - fetched > ttl:
                    stale += 1
                else:
                    fresh += 1
        return f"{kind} cache: {fresh} fresh; {stale} stale; {failed} failed"
    except (OSError, ValueError, TypeError, OverflowError, sqlite3.Error):
        return kind + " cache unavailable"


def observations():
    """Read only the selected water snapshot and preserve explicit removal."""
    try:
        return observation_status(configured_directory("usgs_water"), read_json)
    except IntegrityFailure:
        return "water observations: integrity failed"
    except VerificationLimit:
        return "water observations: verification incomplete"
    except (OSError, ValueError, KeyError, TypeError):
        return "water observations unavailable"


def main():
    """Return concise status for a dataset or a selected cached source."""
    args = sys.argv[1:]
    if len(args) > 1:
        print(compact_fields("Invalid data query.")); return
    text = args[0] if args else ""
    if not all(c.isprintable() for c in text) or len(text.encode("utf-8")) > 150:
        print(compact_fields("Invalid data query.")); return
    words = text.casefold().split()
    if not words or words == ["help"]:
        print(compact_fields("Use !data DATASET", ["parks water flood basin ebmud wildfire landslide satellites", "water observations", "source water|landslide", "source wildfire CATEGORY"]))
    elif len(words) == 1:
        name = ALIASES.get(words[0], words[0])
        print(compact_fields(dataset_status(name) if name in DATASETS else "Unknown dataset; use !data help"))
    elif len(words) == 2 and ALIASES.get(words[0], words[0]) == "usgs_water" and words[1] == "observations":
        print(compact_fields(observations()))
    elif len(words) == 2 and words[0] == "source" and words[1] in {"water", "landslide"}:
        print(compact_fields(point_cache_status(words[1])))
    elif len(words) == 3 and words[:2] == ["source", "wildfire"]:
        print(compact_fields(source_status(words[2])))
    else:
        print(compact_fields("Use !data DATASET or !data help"))


if __name__ == "__main__":
    main()
