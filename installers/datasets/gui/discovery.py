"""Read native package records and verify active data without changing either."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import platform

from installers.datasets import manage
from .catalog import DATASETS


def native_target():
    """Identify supported native builds; never run an artifact for another target."""
    machine = platform.machine().lower()
    if platform.system() == "Windows" and machine in ("amd64", "x86_64"):
        return "windows-x64"
    if platform.system() == "Linux":
        if machine == "x86_64":
            return "linux-x86_64"
        if machine in ("aarch64", "arm64"):
            return "raspberry-pi-arm64"
    raise ValueError("Supported targets: Windows x64, Linux x86_64 and Raspberry Pi ARM64")


def tools_base(target):
    """Return the existing native package location, independent of the data root."""
    if target == "windows-x64":
        return Path(os.environ.get("ProgramW6432", os.environ.get("ProgramFiles", r"C:\Program Files"))) / "MeshCore-EMS-Data"
    return Path("/opt/meshcore-ems-data")


def windows_locations():
    """Read the exact stable Inno AppIds in the 64-bit machine uninstall registry."""
    import winreg
    result = {}
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for name in DATASETS:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + "\\MeshCore-EMS-Data-" + name + "_is1",
                                 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        except FileNotFoundError:
            continue
        with key:
            try:
                location = winreg.QueryValueEx(key, "InstallLocation")[0]
                uninstall = winreg.QueryValueEx(key, "UninstallString")[0]
            except FileNotFoundError as error:
                raise ValueError("Incomplete Windows package registration for " + name + "; repair the native package record") from error
            result[name] = (Path(location), uninstall)
    return result


@dataclass(frozen=True)
class Package:
    state: str
    prefix: Path
    root: Path | None = None
    launcher: tuple[str, ...] = ()
    uninstaller: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class Collection:
    package: Package
    data: str
    detail: str = ""
    dependents: tuple[str, ...] = ()
    dependency_error: str = ""
    managed: bool = False


@dataclass
class Snapshot:
    root: Path
    target: str
    collections: dict[str, Collection] = field(default_factory=dict)
    registry: dict = field(default_factory=dict)


def read_package(name, target, locations, base):
    """Validate package identity, runtime references, launchers and recorded root.

    A native package record is required. Directory existence alone never counts
    as installation. Broken packages retain their location for explicit repair.
    Linux's published current runtime and data-root.txt are its package records.
    """
    prefix = base / name
    root = None
    try:
        if target == "windows-x64":
            record = locations.get(name)
            if record is None:
                remnants = any((prefix / item).is_file() for item in
                               ("runtime.json", "Dataset.exe", "payload/DATA-PACKAGE.json", "payload/installers/datasets/manage.py"))
                state = "broken" if remnants else "missing"
                return Package(state, prefix, detail="No Windows package registration; rerun setup if files remain.")
            prefix, uninstall_text = record
            prefix = prefix.resolve()
            settings = manage.read_json(prefix / "runtime.json")
            if settings["dataset"] != name:
                raise ValueError("Runtime dataset identity mismatch")
            root = Path(settings["root"])
            interpreter = Path(settings["python"])
            payload = prefix / "payload"
            # Inno records a quoted executable without arguments. Do not execute
            # arbitrary registry command text through a shell.
            uninstall_path = Path(uninstall_text.strip().strip('"'))
            if uninstall_path.parent.resolve() != prefix or not uninstall_path.name.startswith("unins") or uninstall_path.suffix.lower() != ".exe":
                raise ValueError("Unexpected registered uninstaller")
            launcher = (str(prefix / "Dataset.exe"),)
            uninstaller = (str(uninstall_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
            required = [interpreter, Path(launcher[0]), uninstall_path]
        else:
            if not (prefix / "data-root.txt").is_file():
                return Package("broken" if prefix.exists() else "missing", prefix,
                               detail="No published data-root record; rerun setup if files remain.")
            root = Path((prefix / "data-root.txt").read_text().strip())
            release = (prefix / "current").resolve(strict=True)
            if not release.is_relative_to((prefix / "releases").resolve()):
                raise ValueError("Runtime selection escapes package releases")
            payload = release / "payload"
            interpreter = release / "venv/bin/python"
            launcher = (str(prefix / "dataset"),)
            uninstaller = (str(prefix / "uninstall"),)
            required = [interpreter, Path(launcher[0]), Path(uninstaller[0])]
        if not root.is_absolute() or not interpreter.is_absolute():
            raise ValueError("Runtime paths must be absolute")
        if target == "windows-x64" and not interpreter.resolve().is_relative_to(prefix):
            raise ValueError("Private interpreter escapes package directory")
        identity = manage.read_json(payload / "DATA-PACKAGE.json")
        if identity.get("dataset") != name or (payload / "dataset-id.txt").read_text().strip() != name:
            raise ValueError("Payload identity mismatch")
        required.append(payload / "installers/datasets/manage.py")
        if not all(path.is_file() for path in required):
            raise ValueError("Maintenance runtime, manager or launcher is missing")
        if target != "windows-x64" and not all(os.access(path, os.X_OK) for path in required[:3]):
            raise ValueError("Maintenance programs are not executable")
        return Package("ready", prefix, root.resolve(), launcher, uninstaller,
                       "Package " + str(identity.get("version", "unknown version")))
    except (OSError, ValueError, KeyError, TypeError) as error:
        return Package("broken", prefix, root.resolve() if root and root.is_absolute() else None,
                       detail=str(error) + "; rerun the matching setup to repair tools.")


def inspect(root, target, *, base=None, locations=None, names=None, progress=lambda message: None):
    """Hash active receipts, expose incomplete attempts and preserve corrupt state.

    This can be slow for large collections and must run outside the GUI thread.
    Invalid global registry state aborts discovery instead of appearing empty.
    """
    root = Path(root).resolve()
    state = manage.registry(root)
    if target == "windows-x64" and locations is None:
        locations = windows_locations()
    base = base or tools_base(target)
    result = Snapshot(root, target, registry=state)
    for name in DATASETS if names is None else names:
        progress("Checking " + name)
        package = read_package(name, target, locations or {}, base)
        entry = state["datasets"].get(name, {})
        active = entry.get("active")
        data, detail = "missing", "No active managed dataset."
        dependency_error = ""
        try:
            if active:
                if active.get("legacy"):
                    data, detail = "unmanaged", "Legacy selection has no validated ownership receipt."
                else:
                    manage.verify_record(root, name, active)
                    data, detail = "valid", "Active selection and receipt file hashes verified."
            elif name not in state["datasets"] and (root / name).is_dir():
                data, detail = "unmanaged", "Legacy directory remains unmodified; installation may import it."
            last = manage.status(root, name)["last_attempt"]
            if last and last.get("state") == "failed":
                if data == "missing":
                    data = "incomplete"
                detail += " Last attempt failed: " + str(last.get("error", "unknown"))
                detail += "; candidate " + str(last.get("candidate", "unknown"))
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            data = "broken"
            detail = str(error) + "; inspect existing verify/update/rollback commands. No automatic replacement."
        try:
            dependents = tuple(manage.dependents(root, state, name))
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            # Unknown ownership is a blocker, not evidence of no dependencies.
            dependents = ("<unreadable dependency receipts>",)
            detail += " Removal blocked: " + str(error)
        if all(state["datasets"].get(dep, {}).get("active") for dep in DATASETS[name]):
            try:
                manage.dependencies_for(root, state, name)
            except (OSError, ValueError, KeyError, TypeError) as error:
                dependency_error = str(error)
        # Retained modified files and unpublished candidates are not active data.
        # Their directory presence must not turn an uninstalled package into one
        # requiring removal, particularly after a successful conservative uninstall.
        managed = bool(active or entry.get("previous"))
        result.collections[name] = Collection(package, data, detail, dependents, dependency_error, managed)
    return result


def demo_snapshot(root, target):
    """Create illustrative states entirely in memory, without inspecting the host."""
    snapshot = Snapshot(Path(root).resolve(), target)
    for index, name in enumerate(DATASETS):
        package = Package("ready" if index < 2 else "missing", Path("demo-tools") / name,
                          snapshot.root, ("demo-maintenance",), ("demo-uninstaller",))
        data = "valid" if index == 0 else "incomplete" if index == 1 else "missing"
        snapshot.collections[name] = Collection(package, data, "SIMULATED state; no filesystem operations.")
    return snapshot
