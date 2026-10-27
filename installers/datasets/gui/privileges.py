"""Reconstruct reviewed dataset operations inside a native authorized worker."""

from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading

from installers.desktop.authorization import run_authorized
from installers.desktop.staging import private_temporary_directory, write_private_file
from .catalog import DATASETS
from .discovery import Collection, Package, Snapshot, inspect, native_target, tools_base
from .execution import Result, run_batch, run_process
from .planning import ACTIONS, file_hash, make_plan

FIELDS = {"kind", "action", "selected", "root", "folder", "target", "plan_digest"}


def plan_digest(plan):
    """Bind review to every reconstructed argument, state record and artifact hash."""
    payload = json.dumps(asdict(plan), default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_request(request):
    """Accept only dataset identifiers and locations, never commands or purge flags."""
    if not isinstance(request, dict) or set(request) != FIELDS or request.get("kind") != "dataset":
        raise ValueError("Invalid dataset desktop request fields")
    if not isinstance(request["action"], str) or request["action"] not in {*ACTIONS, "inspect"} or request["target"] not in {"windows-x64", "linux-x86_64", "raspberry-pi-arm64"}:
        raise ValueError("Unsupported dataset desktop operation")
    if not isinstance(request["selected"], list) or any(not isinstance(item, str) or item not in DATASETS for item in request["selected"]):
        raise ValueError("Unknown dataset selection")
    if len(request["selected"]) > len(DATASETS) or len(set(request["selected"])) != len(request["selected"]):
        raise ValueError("Duplicate dataset selections")
    if not isinstance(request["plan_digest"], str) or not re.fullmatch("[0-9a-f]{64}", request["plan_digest"]):
        raise ValueError("Invalid reviewed-plan fingerprint")
    for field in ("root", "folder"):
        value = request[field]
        if not isinstance(value, str) or not Path(value).is_absolute() or len(value) > 4096 or any(char in value for char in ('"', "\n", "\r", "\x00")):
            raise ValueError("Dataset paths must be absolute and contain no quotes or line breaks")
        if Path(value).is_symlink():
            raise ValueError("Dataset desktop locations cannot be symbolic links")
    return request


def snapshot_payload(snapshot):
    """Serialize verified status records without widening public file permissions."""
    return json.loads(json.dumps(asdict(snapshot), default=str))


def inspect_with_authorization(root, target, emit):
    """Authorize status discovery only when protected installed state requires it."""
    try:
        return inspect(root, target, progress=emit)
    except PermissionError:
        emit("Protected installed data requires authorization for status verification.")
        request = dict(kind="dataset", action="inspect", selected=[], root=str(root),
                       folder=str(root), target=target, plan_digest="0" * 64)
        value = run_authorized(request, emit)
        snapshot = Snapshot(Path(value["root"]), value["target"], registry=value["registry"])
        for name, item in value["collections"].items():
            package = item["package"]
            package["prefix"] = Path(package["prefix"])
            package["root"] = Path(package["root"]) if package["root"] else None
            package["launcher"] = tuple(package["launcher"])
            package["uninstaller"] = tuple(package["uninstaller"])
            package["capabilities"] = tuple(package.get("capabilities", ()))
            item["package"] = Package(**package)
            item["dependents"] = tuple(item["dependents"])
            snapshot.collections[name] = Collection(**item)
        return snapshot


def service_state(target):
    """Read only this product's service state, without starting or stopping it."""
    try:
        if target == "windows-x64":
            if os.name == "nt":
                import ctypes
                buffer = ctypes.create_unicode_buffer(32768)
                if not ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)):
                    return "unknown"
                executable = str(Path(buffer.value) / "sc.exe")
            else:
                executable = r"C:\Windows\System32\sc.exe"
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            result = subprocess.run([executable, "query", "MeshCoreEMS"], capture_output=True,
                                    text=True, timeout=15, **options)
            if result.returncode == 1060:
                return "missing"
            if result.returncode:
                return "unknown"
            # SCM's numeric state is stable even when display labels are localized.
            match = re.search(r":\s*([1-7])\s+\S+\s*$", result.stdout, re.MULTILINE)
            if not match:
                return "unknown"
            return {"1": "stopped", "4": "running"}.get(match[1], "pending")
        result = subprocess.run(["/usr/bin/systemctl", "show", "meshcore-ems.service",
                                 "--property=LoadState", "--property=ActiveState"],
                                capture_output=True, text=True, timeout=15)
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if fields.get("LoadState") == "not-found":
            return "missing"
        if result.returncode:
            return "unknown"
        return "stopped" if fields.get("ActiveState") in {"inactive", "failed"} else "running"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def require_stopped(target, *, query=service_state):
    """Fail closed before removing data that an installed EMS service could consume."""
    if query(target) not in {"stopped", "missing"}:
        raise RuntimeError("Dataset removal is blocked while MeshCore EMS is running or its stopped state cannot be verified. Open Service Setup and Maintenance, choose Stop, then review this removal again.")


def _trusted_installed_operation(operation, target):
    """Require installed tools below the native package base and root ownership on Unix."""
    expected = tools_base(target) / operation.dataset
    if target == "windows-x64":
        # Windows locations come from the protected machine uninstall registry;
        # retain legitimate custom installation directories selected by Inno.
        from installers.desktop.windows_trust import validate_paths
        validate_paths([operation.prefix, operation.command[0]])
        executable = Path(operation.command[0]).resolve()
        if not executable.is_relative_to(operation.prefix.resolve()):
            raise ValueError("Dataset maintenance program escapes its registered package")
        return
    if operation.prefix != expected:
        raise ValueError("Installed dataset tools must use their registered native package location")
    # `current` is deliberately a symlink. Resolve it, then check every executable
    # ancestor to prevent a writable runtime from supplying privileged commands.
    executable = Path(operation.command[0] if operation.command[0] != "/bin/bash" else operation.command[1]).resolve()
    if not executable.is_relative_to(expected.resolve()):
        raise ValueError("Dataset maintenance program escapes its package")
    for path in (executable, *executable.parents):
        metadata = path.stat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError("Installed dataset tools must be root-owned and not writable by other accounts")
        if path == Path("/opt"):
            break


def _launch_checked(operation, emit, target):
    """Stage setup bytes privately; maintenance remains owned by its native package."""
    if operation.kind != "setup":
        _trusted_installed_operation(operation, target)
        return run_process(operation, emit)
    source_index = 0 if target == "windows-x64" else 1
    source = Path(operation.command[source_index])
    if target == "windows-x64":
        from installers.desktop.windows_trust import validate_paths
        existing = next(path for path in (operation.prefix, *operation.prefix.parents) if path.exists())
        validate_paths([existing])
    with private_temporary_directory("meshcore-reviewed-installer-") as temporary:
        staged = Path(temporary) / source.name
        write_private_file(staged, source=source)
        if file_hash(staged) != operation.artifact_hash:
            raise ValueError("Installer bytes changed after review")
        command = list(operation.command)
        command[source_index] = str(staged)
        return run_process(replace(operation, command=tuple(command)), emit)


def perform(request, emit, cancel=None, *, on_result=None):
    """Reconstruct the plan inside authorization and preserve backend batch semantics."""
    validate_request(request)
    if request["target"] != native_target():
        raise ValueError("Dataset request target does not match this computer")
    root, folder = Path(request["root"]), Path(request["folder"])
    snapshot = inspect(root, request["target"], progress=emit)
    if request["action"] == "inspect":
        return snapshot_payload(snapshot)
    plan = make_plan(snapshot, request["action"], request["selected"], folder)
    if plan_digest(plan) != request["plan_digest"]:
        raise RuntimeError("Package, dataset or installer state changed after review. Refresh and review a new plan.")
    if plan.action.startswith("uninstall") or plan.action in {"retain_selected", "update_selected", "rollback_selected"}:
        require_stopped(plan.target)
    def launch(operation, emit):
        if operation.kind in {"uninstall", "uninstall_tools", "update", "rollback"}:
            require_stopped(plan.target)
        return _launch_checked(operation, emit, plan.target)
    from installers.desktop.locking import operation_lock
    with operation_lock():
        results = run_batch(plan, folder, cancel or threading.Event(), emit,
                            lambda done, total: emit(f"Completed {done} of {total} package operations"), launch=launch, on_result=on_result)
    return [asdict(result) for result in results]


def execute_reviewed(plan, folder, cancel, emit, progress):
    """Run simulated batches locally; authorize real operations through native dialogs."""
    if plan.demo:
        return run_batch(plan, folder, cancel, emit, progress)
    request = dict(kind="dataset", action=plan.action, selected=list(plan.selected),
                   root=str(plan.root), folder=str(folder), target=plan.target,
                   plan_digest=plan_digest(plan))
    results = run_authorized(request, emit, cancel)
    progress(len(results), len(plan.operations))
    return [Result(**result) for result in results]
