"""Install independent reference collections without replacing usable data on failure.

Acquisition writes only an unpublished generation. A single atomic registry write
selects a complete, verified generation. Failed and previous generations remain on
disk; cleanup is an explicit, receipt-scoped uninstall operation.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext, ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

DATASETS = {
    "ebmud": (), "california_state_parks": (), "wildfire": (),
    "landslide": (), "satellites": (), "basin_plans": (),
    "flood_impacts": ("basin_plans",),
    "usgs_water": ("basin_plans", "flood_impacts"),
}


def utc_now():
    """Return an acquisition/status timestamp without changing source timestamps."""
    return datetime.now(timezone.utc).isoformat()


def default_root():
    """Use the same persistent collection root as installed service readers."""
    if os.environ.get("MESHCORE_DATA_DIR"):
        return Path(os.environ["MESHCORE_DATA_DIR"])
    if os.environ.get("MESHCORE_RUNTIME_DIR"):
        return Path(os.environ["MESHCORE_RUNTIME_DIR"]).parent / "data"
    if os.name == "nt":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "MeshCore-EMS/data"
    return Path("/var/lib/meshcore-ems/data")


def read_json(path):
    """Read a UTF-8 JSON document; missing or malformed state is an error."""
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    """Flush a same-directory temporary file before atomically selecting its bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def contained(root, relative):
    """Reject absolute paths, traversal, and links before accessing owned state."""
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts or any(p in ("..", ".") for p in relative.parts):
        raise ValueError("Invalid managed relative path")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Links are not permitted in managed dataset paths")
    if not path.resolve().is_relative_to(root) or path.resolve() == root:
        raise ValueError("Managed path escapes its data root")
    return path


def registry(root):
    """Read the sole activation registry; never recover corruption by resetting it."""
    path = root / "datasets.json"
    result = read_json(path) if path.exists() else {"schema": 1, "datasets": {}}
    if result.get("schema") != 1 or not isinstance(result.get("datasets"), dict):
        raise ValueError("Unsupported dataset registry")
    return result


@contextmanager
def protected_data_root(root, *, create=False):
    """Retain a trusted data-root boundary throughout coordinated native mutation.

    POSIX ancestors are root-owned and cannot be modified by other accounts.
    Windows retains pinned handles and checks ownership/DACLs on the entire
    existing chain. Unsafe custom locations require a protected graphical
    selection; existing owners or parent permissions are never repaired here.
    """
    root = Path(root).absolute()
    if not root.is_absolute() or root == Path(root.anchor) or any(part in {".", ".."} for part in root.parts):
        raise ValueError("A canonical absolute dataset root is required")
    if os.name == "nt":
        from installers.desktop.windows_trust import protected_data_root as protect
        with protect(root, create=create):
            yield root
        return
    for path in (*reversed(root.parents), root):
        if not path.exists():
            if not create:
                raise FileNotFoundError(str(path))
            path.mkdir(mode=0o755)
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise PermissionError("Dataset storage and every ancestor must be root-owned and not group/other writable. Select a protected location in the graphical installer; existing custom directory permissions were not changed.")
    yield root


@contextmanager
def locked(root):
    """Serialize install, update, rollback and removal across dependent collections.

An interrupted process leaves its lock for deliberate operator recovery. A lock
is never stolen based on age or PID reuse, and readers do not require the lock.
"""
    from installers.desktop import locking
    token = os.environ.get(locking.VARIABLE, "")
    coordinated = bool(re.fullmatch("[0-9a-f]{32}", token))
    guard = protected_data_root(root, create=True) if coordinated else nullcontext()
    with guard:
        with _locked_record(root, token, coordinated):
            yield


@contextmanager
def _locked_record(root, token, coordinated):
    """Write one ownership-backed serialization record inside an already guarded root."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".datasets.lock"
    from installers.desktop import locking
    value = {"schema": 2, "pid": os.getpid(), "creation": locking.process_identity(os.getpid()),
             "lease": token if coordinated else "", "coordinated": coordinated, "started": utc_now()}
    content = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    if coordinated:
        locking.create_private_file(path, content)
    else:
        # Direct library use has no delegated native work to prove recoverable.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
    try:
        yield
    finally:
        path.unlink()


@contextmanager
def _recovery_record(root, *, delete=False):
    """Anchor the exact reviewed lock and prevent path replacement during removal."""
    from installers.desktop import locking
    root = Path(root).resolve()
    with ExitStack() as resources:
        if os.name == "nt":
            import ctypes
            import msvcrt
            from installers.desktop.authorization import _windows_locked_handle
            for directory in (*reversed(root.parents), root):
                handle, close = _windows_locked_handle(directory, directory=True)
                resources.callback(close, handle)
            handle, close = _windows_locked_handle(root / ".datasets.lock", directory=False, delete=delete)
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            resources.callback(os.close, descriptor)
            locking._private_owner(root / ".datasets.lock")
            def remove():
                from ctypes import wintypes
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
                value = wintypes.BOOL(True)
                if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(value), ctypes.sizeof(value)):
                    raise ctypes.WinError(ctypes.get_last_error())
        else:
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
            resources.callback(os.close, directory)
            metadata = os.fstat(directory)
            if metadata.st_uid != 0 or metadata.st_mode & 0o022:
                raise PermissionError("Dataset lock recovery requires a root-owned data directory without group/other write access")
            descriptor = os.open(".datasets.lock", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory)
            resources.callback(os.close, descriptor)
            def remove():
                before = os.fstat(descriptor)
                after = os.stat(".datasets.lock", dir_fd=directory, follow_symlinks=False)
                if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                    raise RuntimeError("Dataset lock changed during recovery")
                os.unlink(".datasets.lock", dir_fd=directory)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
            raise ValueError("Dataset lock must be a bounded regular file")
        if os.name != "nt" and (metadata.st_uid != 0 or metadata.st_mode & 0o077):
            raise PermissionError("Legacy or unprotected dataset lock requires external administrator review")
        yield descriptor, remove


def _inspect_lock_descriptor(descriptor):
    """Validate current lock ownership and native-child absence without exposing tokens."""
    from installers.desktop import locking
    os.lseek(descriptor, 0, os.SEEK_SET)
    content = os.read(descriptor, 4097)
    revision = hashlib.sha256(content).hexdigest()
    try:
        value = json.loads(content)
        if not isinstance(value, dict) or set(value) != {"schema", "pid", "creation", "lease", "coordinated", "started"} or value.get("schema") != 2:
            raise ValueError("Legacy or unknown lock schema cannot be recovered graphically")
        if type(value["pid"]) is not int or value["pid"] <= 0 or not isinstance(value["creation"], str) or not value["creation"].isdigit() or value["coordinated"] is not True or not isinstance(value["lease"], str) or not re.fullmatch("[0-9a-f]{32}", value["lease"]):
            raise ValueError("Dataset lock lacks complete privileged owner/lease evidence")
        if locking._process_state(value["pid"], value["creation"]) != "dead":
            raise ValueError("Dataset lock owner is still live or inaccessible")
        if locking._native_process_gate(value["lease"]):
            raise ValueError("A delegated or potential native maintenance process is still live or inaccessible")
        return {"revision": revision, "recoverable": True, "detail": "Reviewed schema-2 orphan can be archived; dataset registry, receipts and files remain unchanged."}, content
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        return {"revision": revision, "recoverable": False, "detail": str(error)}, content


def inspect_lock_recovery(root):
    """Inspect one fixed dataset lock; unknown ownership or legacy records fail closed."""
    try:
        with _recovery_record(root) as (descriptor, remove):
            return _inspect_lock_descriptor(descriptor)[0]
    except FileNotFoundError:
        return {"revision": "", "recoverable": False, "detail": "No dataset lock exists."}
    except (OSError, ValueError, RuntimeError) as error:
        return {"revision": "", "recoverable": False, "detail": str(error)}


def recover_lock(root, expected_revision):
    """Archive only a reviewed schema-2 orphan under a fresh global maintenance lease."""
    from installers.desktop import locking
    if not isinstance(expected_revision, str) or not re.fullmatch("[0-9a-f]{64}", expected_revision):
        raise ValueError("A reviewed dataset-lock fingerprint is required")
    with locking.operation_lock():
        with _recovery_record(root, delete=True) as (descriptor, remove):
            status, content = _inspect_lock_descriptor(descriptor)
            if status["revision"] != expected_revision or not status["recoverable"]:
                raise RuntimeError("Dataset lock evidence changed or remains unsafe: " + status["detail"])
            root_id = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:20]
            archive = locking.maintenance_directory() / ("dataset-lock-" + root_id + "-" + expected_revision + "-" + uuid.uuid4().hex + ".json")
            locking.create_private_file(archive, content)
            # Recheck live-process evidence after durable archival, immediately before removal.
            if not _inspect_lock_descriptor(descriptor)[0]["recoverable"]:
                raise RuntimeError("Native process evidence changed; dataset lock was retained")
            remove()
    return {"recovered": True, "archive": str(archive), "detail": "Orphaned dataset lock archived. Registry, data, receipts and failed candidates were retained. Review the next maintenance operation separately."}


def digest(path):
    """Stream hashes so multi-gigabyte originals need not fit in memory."""
    with path.open("rb") as stream:
        return {"sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
                "bytes": path.stat().st_size}


def inventory(directory):
    """Record all owned files, rejecting links and transient SQLite sidecars."""
    result = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        contained(directory, relative)
        if path.is_file():
            if path.name.endswith(("-wal", "-shm", "-journal")):
                raise ValueError("Unclosed SQLite state in candidate: " + relative)
            result[relative] = digest(path)
    if not result:
        raise ValueError("Dataset candidate is empty")
    return result


def readable_candidate(root, content):
    """Publish public references readable by service accounts despite a restrictive umask.

Only the new candidate files are adjusted. Existing generations and unrelated
operator files retain their permissions. Windows inherits its data-root ACL.
"""
    if os.name == "nt":
        return
    for path in content.rglob("*"):
        contained(content, path.relative_to(content))
        path.chmod(0o755 if path.is_dir() else 0o644)
    directory = content
    while directory != root.parent:
        directory.chmod(0o755)
        if directory == root:
            break
        directory = directory.parent


def record_path(root, dataset, record):
    """Resolve an activation record only inside the named collection's ownership."""
    root = Path(root).resolve()
    path = contained(root, record["path"])
    if record.get("legacy"):
        if path != root / dataset:
            raise ValueError("Invalid legacy dataset path")
    else:
        parts = Path(record["path"]).parts
        if len(parts) != 4 or parts[:2] != (".datasets", dataset) or parts[-1] != "content":
            raise ValueError("Invalid dataset generation path")
        receipt = contained(root, record["receipt"])
        if receipt != path.parent / "receipt.json":
            raise ValueError("Invalid dataset receipt path")
    return path


def selected(root, state, dataset):
    """Resolve managed selection or an existing legacy collection without adopting it."""
    entry = state["datasets"].get(dataset)
    if entry is not None:
        if not entry.get("active"):
            raise ValueError(f"Dataset {dataset} is uninstalled")
        record = entry["active"]
        record_path(root, dataset, record)
        return record
    legacy = contained(root, dataset)
    if legacy.is_dir() and any(legacy.iterdir()):
        return {"path": dataset, "legacy": True}
    raise ValueError(f"Install prerequisite dataset {dataset} first")


def dependencies_for(root, state, dataset):
    """Pin prerequisite generations and reject an inconsistent water build set."""
    records = {name: selected(root, state, name) for name in DATASETS[dataset]}
    for name, record in records.items():
        if record.get("legacy"):
            raise ValueError(f"Install prerequisite dataset {name} to validate and pin its legacy data first")
        receipt = read_json(contained(root, record["receipt"]))
        for dependency, pinned in receipt["dependencies"].items():
            if dependency in records and pinned != records[dependency]:
                raise ValueError(f"Update {name} against the selected {dependency} before updating {dataset}")
    return records


def verify_record(root, dataset, record):
    """Verify receipt ownership and every installed byte before reuse or rollback."""
    path = record_path(root, dataset, record)
    if record.get("legacy"):
        return
    receipt = read_json(contained(root, record["receipt"]))
    if receipt.get("dataset") != dataset or receipt.get("schema") != 1 or receipt.get("path") != record["path"]:
        raise ValueError("Dataset receipt identity mismatch")
    if inventory(path) != receipt["files"]:
        raise ValueError("Installed dataset has changed; retained without overwriting")
    for dependency, pinned in receipt["dependencies"].items():
        verify_record(root, dependency, pinned)


def status(root, dataset):
    """Report selection and last attempt separately so failure never implies empty data."""
    result = {"dataset": dataset, "selection": registry(root)["datasets"].get(dataset)}
    path = root / ".datasets" / "status" / (dataset + ".json")
    result["last_attempt"] = read_json(path) if path.exists() else None
    return result


def attempt_status(root, dataset, result):
    """Best-effort diagnostics cannot turn a successful commit into a failed update."""
    try:
        write_json(root / ".datasets/status" / (dataset + ".json"), result)
    except OSError as error:
        print("Could not save dataset status: " + str(error), file=sys.stderr)


def install(root, dataset, payload, update=False, resume=None, acquire=None, validate=None):
    """Build a candidate in isolation, validate it, and commit one activation pointer.

Failed candidates and all previous directories are retained. A repeated install
checks the selected generation rather than downgrading it to a shipped seed.
Callbacks are injectable to exercise failure boundaries without live providers.
Root aliases are resolved before deriving candidate and receipt paths.
"""
    root = Path(root).resolve()
    if acquire is None or validate is None:
        from adapters import acquire as acquire_default, validate as validate_default
        acquire = acquire or acquire_default
        validate = validate or validate_default
    with locked(root):
        state = registry(root)
        entry = state["datasets"].get(dataset, {})
        previous = entry.get("active")
        if previous and not update and not resume:
            verify_record(root, dataset, previous)
            return previous
        if previous is None and dataset not in state["datasets"] and (root / dataset).is_dir():
            previous = {"path": dataset, "legacy": True}
        # An explicit update of a valid legacy collection never overwrites that directory.
        pinned = dependencies_for(root, state, dataset)
        dependency_paths = {name: record_path(root, name, record) for name, record in pinned.items()}
        for name, record in pinned.items():
            verify_record(root, name, record)
            validate(name, dependency_paths[name], payload, dependency_paths)
        generation = resume or uuid.uuid4().hex
        if len(generation) != 32 or any(c not in "0123456789abcdef" for c in generation):
            raise ValueError("Resume requires the 32-character candidate identifier")
        directory = contained(root, f".datasets/{dataset}/{generation}")
        content = directory / "content"
        pending = {"schema": 1, "dataset": dataset, "dependencies": pinned,
                   "previous": previous, "update": update,
                   "payload": digest(payload / "PAYLOAD-MANIFEST.json")
                   if (payload / "PAYLOAD-MANIFEST.json").exists() else None}
        if resume:
            if (directory / "receipt.json").exists() or read_json(directory / "pending.json") != pending:
                raise ValueError("Candidate is complete or its inputs changed; start a new update")
        else:
            # Space estimates cover the known local copy, not an unbounded provider
            # response. Exhaustion during acquisition still cannot affect active data.
            seed = payload / "seeds" / dataset
            source = record_path(root, dataset, previous) if previous else seed
            estimated = sum(p.stat().st_size for p in source.rglob("*") if p.is_file()) if source.exists() else 0
            if shutil.disk_usage(root).free < estimated + 64 * 1024 * 1024:
                raise OSError("Insufficient staging space; active data retained")
            content.mkdir(parents=True, exist_ok=False)
            write_json(directory / "pending.json", pending)
        try:
            acquire(dataset, content, payload, dependency_paths,
                    previous=record_path(root, dataset, previous) if previous else None,
                    update=update, resume=bool(resume))
            validate(dataset, content, payload, dependency_paths)
            readable_candidate(root, content)
            record = {"path": content.relative_to(root).as_posix(),
                      "receipt": (directory / "receipt.json").relative_to(root).as_posix()}
            receipt = {"schema": 1, "dataset": dataset, "path": record["path"],
                       "installed_at": utc_now(), "dependencies": pinned,
                       "files": inventory(content)}
            if (payload / "DATA-PACKAGE.json").exists():
                receipt["package"] = read_json(payload / "DATA-PACKAGE.json")
            write_json(directory / "receipt.json", receipt)
            verify_record(root, dataset, record)
            # All functional validation precedes activation. The only published write
            # is the atomic registry replacement; a failed replacement preserves its bytes.
            state["datasets"][dataset] = {"active": record, "previous": previous}
            write_json(root / "datasets.json", state)
        except BaseException as error:
            attempt_status(root, dataset, {"state": "failed", "time": utc_now(),
                           "candidate": generation, "error": str(error),
                           "message": "Previous active dataset retained"})
            raise
        attempt_status(root, dataset, {"state": "ready", "time": utc_now(), "candidate": generation})
        return record


def rollback(root, dataset):
    """Select the previous verified generation while retaining the newer directory."""
    root = Path(root).resolve()
    with locked(root):
        state = registry(root)
        entry = state["datasets"].get(dataset, {})
        previous = entry.get("previous")
        if not previous:
            raise ValueError("No previous dataset generation")
        if previous.get("legacy"):
            raise ValueError("Legacy data remains intact; verify and import it before managed rollback")
        verify_record(root, dataset, previous)
        state["datasets"][dataset] = {"active": previous, "previous": entry.get("active")}
        write_json(root / "datasets.json", state)


def dependents(root, state, dataset):
    """Protect active and rollback prerequisites from removal, including transitive pins."""
    found = set()
    def visit(owner, record, seen):
        if not record or record.get("legacy") or record["receipt"] in seen:
            return
        seen.add(record["receipt"])
        record_path(root, owner, record)
        receipt = read_json(contained(root, record["receipt"]))
        for name, pinned in receipt["dependencies"].items():
            if name == dataset:
                found.add(owner)
            visit(name, pinned, seen)
    for owner, entry in state["datasets"].items():
        if owner != dataset:
            for key in ("active", "previous"):
                visit(owner, entry.get(key), set())
    return sorted(found)


def uninstall(root, dataset, purge=False):
    """Deselect a package, then remove only its receipt-owned unmodified generations.

Modified generations are preserved unless purge is explicit. Legacy directories,
failed candidates without receipts, and unrelated files are never deleted. A
failed deletion leaves an unselected recoverable directory, never a broken active
selection. Dataset consumers must be stopped before intentional removal.
"""
    root = Path(root).resolve()
    with locked(root):
        state = registry(root)
        required = dependents(root, state, dataset)
        if required:
            raise ValueError("Dataset is required by active/rollback packages: " + ", ".join(required))
        base = contained(root, ".datasets/" + dataset)
        removable, retained = [], []
        if base.exists():
            for directory in sorted(base.iterdir()):
                contained(root, directory.relative_to(root))
                receipt_path = directory / "receipt.json"
                if not directory.is_dir() or not receipt_path.is_file():
                    retained.append(str(directory))
                    continue
                receipt = read_json(receipt_path)
                record = {"path": (directory / "content").relative_to(root).as_posix(),
                          "receipt": receipt_path.relative_to(root).as_posix()}
                content = record_path(root, dataset, record)
                if receipt.get("dataset") != dataset or receipt.get("path") != record["path"]:
                    raise ValueError("Refusing removal of mismatched receipt")
                # Validate every descendant before any recursive deletion, even purge.
                actual = inventory(content)
                extras = {p.name for p in directory.iterdir()} - {"content", "receipt.json", "pending.json"}
                if extras or (not purge and actual != receipt["files"]):
                    retained.append(str(directory))
                else:
                    removable.append(directory)
        state["datasets"][dataset] = {"active": None, "previous": None}
        write_json(root / "datasets.json", state)
        for directory in removable:
            # The absolute target was checked above and belongs to this package.
            shutil.rmtree(directory)
        return {"removed": [str(p) for p in removable], "retained": retained,
                "legacy_preserved": str(root / dataset) if (root / dataset).exists() else None}


def retain(root, dataset):
    """Describe retained selection without changing data, receipts or registry.

    Native package uninstall uses this contract when only maintenance tooling is
    removed. Dataset dependents remain usable because their pinned content stays.
    Reinstalling the matching maintenance package verifies and reuses that data.
    """
    value = registry(Path(root))
    return {"dataset": dataset, "data_retained": True,
            "registry": str(Path(root) / "datasets.json"),
            "selection": value["datasets"].get(dataset, {}),
            "detail": "All managed, modified, rollback and legacy data remains. Reinstall maintenance tools to update or remove it."}


def remember_retained_root(root, dataset):
    """Keep a protected discovery hint after native package records are removed.

    This hint selects no data and establishes no ownership. Reinstallation must
    still verify datasets.json and content receipts. Explicit roots take priority.
    """
    from installers.desktop import locking
    if dataset not in DATASETS:
        raise ValueError("Unknown dataset root hint")
    root = Path(root).resolve()
    if not root.is_absolute() or any(ord(character) < 32 for character in str(root)):
        raise ValueError("Invalid retained root")
    directory = locking.maintenance_directory() / "retained-roots"
    try:
        locking.create_private_directory(directory)
    except FileExistsError:
        locking._private_owner(directory)
    if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
        raise ValueError("Retained root hints cannot use linked directories")
    temporary = directory / (dataset + "." + uuid.uuid4().hex + ".tmp")
    try:
        locking.create_private_file(temporary, (str(root) + "\n").encode("utf-8"))
        os.replace(temporary, directory / (dataset + ".txt"))
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    """Expose the same lifecycle to native wrappers and direct maintenance invocations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "update", "verify", "status", "rollback", "uninstall", "recover-lock"))
    parser.add_argument("--dataset", choices=tuple(DATASETS), required=True)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--payload", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--resume", help="Resume an unchanged failed candidate by its identifier")
    parser.add_argument("--purge", action="store_true", help="Uninstall also removes modified receipt-owned generations")
    parser.add_argument("--retain-data", action="store_true", help="Uninstall tooling contract: retain every dataset file and registry selection")
    parser.add_argument("--reviewed-lock", help="Exact reviewed schema-2 dataset-lock fingerprint for recover-lock")
    args = parser.parse_args(argv)
    if args.purge and args.action != "uninstall":
        parser.error("--purge requires uninstall")
    if args.retain_data and (args.action != "uninstall" or args.purge):
        parser.error("--retain-data requires uninstall without --purge")
    if args.resume and args.action not in ("install", "update"):
        parser.error("--resume requires install or update")
    if bool(args.reviewed_lock) != (args.action == "recover-lock"):
        parser.error("recover-lock requires --reviewed-lock; other operations reject it")
    root, payload = args.root.resolve(), args.payload.resolve()
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from installers.desktop.locking import operation_lock, require_consumers_stopped
        lease = operation_lock() if args.action in {"install", "update", "rollback", "uninstall", "recover-lock"} else nullcontext()
        with lease:
            if args.action in {"update", "rollback"} or (args.action == "uninstall" and not args.retain_data):
                require_consumers_stopped()
            if args.action == "recover-lock":
                result = recover_lock(root, args.reviewed_lock)
            elif args.action in ("install", "update"):
                result = install(root, args.dataset, payload, args.action == "update", args.resume)
            elif args.action == "rollback":
                rollback(root, args.dataset)
                result = status(root, args.dataset)
            elif args.action == "uninstall":
                result = retain(root, args.dataset) if args.retain_data else uninstall(root, args.dataset, args.purge)
                if args.retain_data:
                    remember_retained_root(root, args.dataset)
            elif args.action == "verify":
                record = selected(root, registry(root), args.dataset)
                if record.get("legacy"):
                    raise ValueError("Legacy directory has no ownership receipt; install the data package to validate and import it")
                verify_record(root, args.dataset, record)
                result = {"dataset": args.dataset, "verified": True}
            else:
                result = status(root, args.dataset)
            print(json.dumps(result, indent=2))
            return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print("Dataset operation failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
