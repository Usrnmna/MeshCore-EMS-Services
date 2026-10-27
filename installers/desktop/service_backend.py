"""Validated native operations for the separate desktop service application.

Requests contain settings and a fixed operation identifier, never commands. Native
installers remain responsible for Python provisioning, service registration and
package removal. The installed interpreter validates configuration changes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from installers.datasets.gui.discovery import native_target
from installers.desktop.staging import private_temporary_directory, write_private_file
from installers.desktop.native_environment import clean_environment
from installers.datasets.gui.privileges import service_state
from installers.desktop import service_integrations as integrations

ACTIONS = {"install", "configure", "status", "start", "stop", "diagnostics", "uninstall", "startup", "validate", "deconfigure", "check_connection"}
TARGETS = {"windows-x64", "linux-x86_64", "raspberry-pi-arm64"}
SECRET = re.compile(r"MESHCORE_CHANNEL_KEY_[A-Z0-9_]+\Z")
CREDENTIALS = {"AIRNOW_API_KEY", "MESHCORE_MQTT_USERNAME", "MESHCORE_MQTT_PASSWORD"}
SETTINGS = {"transport", "serial_port", "tcp_host", "tcp_port", "ble_address", "channel", "channels", "credentials", "clear_credentials", "mqtt", "dataset_root", "commands", "programs"}


def safe_text(value, label, maximum=4096):
    """Reject controls and oversized values before native argument construction."""
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value) or '"' in value:
        raise ValueError(label + " contains invalid characters or is too long")
    return value


def validate_settings(settings):
    """Validate the GUI's bounded schema; channel semantics use installed validators."""
    if not isinstance(settings, dict) or set(settings) - SETTINGS:
        raise ValueError("Unknown service settings")
    if "dataset_root" in settings:
        value = safe_text(settings["dataset_root"], "Dataset root")
        if not Path(value).is_absolute() or ".datasets" in Path(value).parts:
            raise ValueError("Dataset root must be an absolute shared root, never a managed generation")
    if "commands" in settings:
        commands = settings["commands"]
        if not isinstance(commands, dict) or len(commands) > 256 or any(not isinstance(name, str) or len(name) > 128 or type(value) is not bool for name, value in commands.items()):
            raise ValueError("Command controls must map existing names to booleans")
    if "programs" in settings:
        integrations.validate_programs(settings["programs"])
    for name in ("transport", "serial_port", "tcp_host", "ble_address", "channel"):
        if name in settings:
            safe_text(settings[name], name)
    kind = settings.get("transport")
    if kind is not None and kind not in ("serial", "tcp", "ble"):
        raise ValueError("Choose serial, TCP or BLE")
    if "serial_port" in settings:
        port = settings["serial_port"]
        if not (port.lower() == "auto" or re.fullmatch(r"COM[1-9][0-9]*|/dev/tty(?:ACM|USB)[0-9]+|/dev/serial/by-id/[A-Za-z0-9_.:+-]+", port)):
            raise ValueError("Choose auto or a supported serial device")
    if "tcp_port" in settings and (type(settings["tcp_port"]) is not int or not 1 <= settings["tcp_port"] <= 65535):
        raise ValueError("TCP port must be between 1 and 65535")
    if "ble_address" in settings and not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", settings["ble_address"]):
        raise ValueError("Enter the previously paired BLE address")
    kinds = ({"serial"} if "serial_port" in settings else set()) | ({"tcp"} if {"tcp_host", "tcp_port"} & settings.keys() else set()) | ({"ble"} if "ble_address" in settings else set())
    if kind:
        kinds.add(kind)
    if len(kinds) > 1:
        raise ValueError("Settings must select one transport")
    if settings.get("channel") and "channels" in settings:
        raise ValueError("Use the channel field or advanced channel registry, not both")
    if "channels" in settings:
        value = settings["channels"]
        if not isinstance(value, dict) or set(value) != {"channels", "command_channels"} or not isinstance(value["channels"], dict) or not isinstance(value["command_channels"], dict):
            raise ValueError("Channel registry must contain channels and command_channels")
        for spec in value["channels"].values():
            if not isinstance(spec, dict) or set(spec) - {"name", "type", "slot", "secret_env", "mqtt_export"}:
                raise ValueError("Channel registry must use secret_env references, never inline keys")
    credentials = settings.get("credentials", {})
    clears = settings.get("clear_credentials", [])
    if not isinstance(credentials, dict) or not isinstance(clears, list):
        raise ValueError("Invalid credential settings")
    for key in [*credentials, *clears]:
        if not isinstance(key, str) or (key not in CREDENTIALS and not SECRET.fullmatch(key)):
            raise ValueError("Unsupported credential name")
    for value in credentials.values():
        if not isinstance(value, str) or len(value) > 4096 or any(ord(character) < 32 for character in value):
            raise ValueError("Credential contains control characters or is too long")
    if "mqtt" in settings:
        mqtt = settings["mqtt"]
        if not isinstance(mqtt, dict) or set(mqtt) != {"host", "port", "tls", "local_broker"}:
            raise ValueError("Invalid MQTT settings")
        safe_text(mqtt["host"], "MQTT host", 253)
        if not mqtt["host"] or type(mqtt["port"]) is not int or not 1 <= mqtt["port"] <= 65535 or type(mqtt["tls"]) is not bool or type(mqtt["local_broker"]) is not bool:
            raise ValueError("Invalid MQTT host, port or switches")
        if mqtt["local_broker"] and (mqtt["host"] != "127.0.0.1" or mqtt["tls"]):
            raise ValueError("The bundled broker requires 127.0.0.1 without TLS")
    return settings


def validate_request(request):
    """Reject extra request fields and mutation data on read-only operations."""
    if not isinstance(request, dict) or request.get("kind") != "service" or request.get("action") not in ACTIONS or request.get("target") not in TARGETS:
        raise ValueError("Invalid service operation")
    action = request["action"]
    allowed = {"kind", "action", "target"}
    if action in {"install", "configure"}:
        allowed |= {"settings", "start"}
        validate_settings(request.get("settings", {}))
        if type(request.get("start", False)) is not bool:
            raise ValueError("Invalid start selection")
    if action == "install":
        allowed |= {"folder", "artifact_sha256"}
        folder = Path(safe_text(request.get("folder"), "Installer folder"))
        if not folder.is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", request.get("artifact_sha256", "")):
            raise ValueError("Select a checked native installer folder")
    if action == "startup":
        allowed.add("mode")
        if request.get("mode") not in {"disabled", "manual", "automatic"}:
            raise ValueError("Choose disabled, manual or automatic startup")
    if set(request) - allowed:
        raise ValueError("Unexpected service operation fields")
    return request


def merge_credentials(current, settings):
    """Keep blank/unspecified secrets; clear only explicitly named credentials."""
    result = dict(current)
    for key in settings.get("clear_credentials", []):
        result.pop(key, None)
    result.update({key: value for key, value in settings.get("credentials", {}).items() if value})
    return result


def redact(text, credentials):
    """Remove known secret values from subprocess output and displayed diagnostics."""
    for value in sorted(set(credentials.values()), key=len, reverse=True):
        if value:
            text = text.replace(value, "[redacted]")
    return text


def select_installer(folder, target, expected=None):
    """Require one target-specific installer and a matching release checksum."""
    suffix = "windows-x64-setup.exe" if target == "windows-x64" else target + ".run"
    expression = re.compile(r"MeshCore-EMS-v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?-" + re.escape(suffix))
    folder = Path(folder)
    matches = [p for p in folder.iterdir() if expression.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    if len(matches) != 1:
        raise ValueError("Expected exactly one service installer for " + target)
    artifact = matches[0]
    entries = {}
    for line in (folder / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            name = parts[1].lstrip("*")
            if name in entries:
                raise ValueError("Duplicate service installer checksum")
            entries[name] = parts[0].lower()
    with artifact.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if entries.get(artifact.name) != digest or (expected is not None and digest != expected):
        raise ValueError("Service installer changed or its checksum does not match")
    return artifact


def windows_folder(identifier):
    """Resolve machine folders through Windows, rather than caller environment overrides."""
    import ctypes
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, identifier, None, 0, buffer) != 0:
        raise RuntimeError("Cannot resolve the Windows system folder")
    return Path(buffer.value)


def installed_paths(target):
    """Read the fixed native installation record; GUI requests cannot choose paths."""
    if target == "windows-x64":
        import winreg
        root = windows_folder(38) / "MeshCore-EMS"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{E76251FC-52CF-44EE-93E7-0278400F236C}_is1", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                root = Path(winreg.QueryValueEx(key, "InstallLocation")[0])
        except FileNotFoundError:
            pass
        state = windows_folder(35) / "MeshCore-EMS"
        return root, state, state, root / "python/python.exe", "windows"
    root = Path("/opt/meshcore-ems/current")
    return root, Path("/var/lib/meshcore-ems"), Path("/etc/meshcore-ems"), root / ".venv/bin/python", "linux"


def trusted_installed(path, root):
    """Require installed code under its registered root, with root ownership on Unix."""
    if os.name == "nt":
        from installers.desktop.windows_trust import validate_paths
        validate_paths([root, path])
    root = Path(root).resolve(strict=True)
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("Installed program escapes its registered directory")
    if os.name != "nt":
        for current in [path, *path.parents]:
            metadata = current.stat()
            if metadata.st_uid != 0 or metadata.st_mode & 0o022:
                raise ValueError("Installed program is not protected from modification")
    return path


def trusted_runtime(path, root):
    """Check the private interpreter or its native root-owned POSIX symlink target."""
    if os.name == "nt":
        return trusted_installed(path, root)
    resolved = Path(path).resolve(strict=True)
    for current in (resolved, *resolved.parents):
        metadata = current.stat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError("Installed interpreter is not protected from modification")
    return path


def run_native(command, emit, *, credentials=None, removal_root=None, trusted_root=None):
    """Pin protected Windows code until the child exits; native owners keep removal rights."""
    if os.name != "nt":
        return _run_native(command, emit, credentials=credentials)
    from installers.desktop.windows_trust import protected_paths
    paths = [Path(command[0])]
    paths.extend(Path(value) for value in command[1:] if isinstance(value, (str, Path))
                 and str(value).lower().endswith((".py", ".ps1")) and Path(value).is_absolute())
    if trusted_root:
        paths.append(Path(trusted_root))
    with protected_paths(paths, allow_removal_under=removal_root):
        with private_temporary_directory("meshcore-native-") as temporary:
            return _run_native(command, emit, credentials=credentials, temporary=temporary)


def _run_native(command, emit, *, credentials=None, temporary=None):
    """Execute an internally constructed argv and stream redacted output; never use a shell."""
    options = {"creationflags": subprocess.CREATE_NO_WINDOW, "cwd": str(Path(command[0]).parent)} if os.name == "nt" else {}
    environment = clean_environment(temporary)
    frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
    if frozen_windows:
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        process = subprocess.Popen([str(value) for value in command], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", env=environment, **options)
    finally:
        if frozen_windows:
            ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)
    with process:
        lines = []
        for line in process.stdout:
            text = redact(line.rstrip(), credentials or {})
            lines.append(text)
            lines = lines[-200:]
            emit(text)
        code = process.wait()
    if code:
        raise RuntimeError("Native operation failed (exit " + str(code) + ").\n" + "\n".join(lines[-15:]))
    return "\n".join(lines)


def control(action, target, emit):
    """Operate only this product's fixed native service name."""
    if action not in {"start", "stop", "status"}:
        raise ValueError("Invalid service control")
    if target == "windows-x64":
        executable = windows_folder(37) / "WindowsPowerShell/v1.0/powershell.exe"
        verb = {"start":"Start-Service", "stop":"Stop-Service"}.get(action)
        if verb:
            script = "$ErrorActionPreference='Stop'; " + verb + " -Name MeshCoreEMS; (Get-Service -Name MeshCoreEMS).WaitForStatus('" + ("Running" if action == "start" else "Stopped") + "',[TimeSpan]::FromSeconds(50)); (Get-Service -Name MeshCoreEMS).Status.ToString()"
        else:
            script = "$s=Get-Service -Name MeshCoreEMS -ErrorAction SilentlyContinue; if ($s) {$s.Status.ToString()} else {'Not installed'}"
        return run_native([executable, "-NoProfile", "-NonInteractive", "-Command", script], emit)
    if action == "status":
        result = subprocess.run(["/usr/bin/systemctl", "show", "meshcore-ems.service", "--property=LoadState,ActiveState,SubState", "--no-pager"], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Cannot query the EMS service manager")
        emit(result.stdout.strip())
        return result.stdout.strip()
    return run_native(["/usr/bin/systemctl", action, "meshcore-ems.service"], emit)


def startup_mode(target):
    """Read only the fixed service's boot policy; never infer it from running state."""
    try:
        if target == "windows-x64":
            executable = windows_folder(37) / "WindowsPowerShell/v1.0/powershell.exe"
            script = "(Get-ItemProperty -LiteralPath 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\MeshCoreEMS' -Name Start -ErrorAction Stop).Start"
            result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=20,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return {"2": "automatic", "3": "manual", "4": "disabled"}.get(result.stdout.strip(), "unknown") if result.returncode == 0 else "unknown"
        result = subprocess.run(["/usr/bin/systemctl", "is-enabled", "meshcore-ems.service"], capture_output=True, text=True, timeout=20)
        return {"enabled": "automatic", "enabled-runtime": "automatic", "disabled": "manual", "masked": "disabled"}.get(result.stdout.strip(), "unknown")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def set_startup(target, mode, emit):
    """Change this service's boot policy using fixed native arguments only."""
    if mode not in {"disabled", "manual", "automatic"}:
        raise ValueError("Invalid startup policy")
    if target == "windows-x64":
        executable = windows_folder(37) / "WindowsPowerShell/v1.0/powershell.exe"
        native = {"disabled": "Disabled", "manual": "Manual", "automatic": "Automatic"}[mode]
        script = "$ErrorActionPreference='Stop'; Set-Service -Name MeshCoreEMS -StartupType " + native
        if mode == "disabled":
            control("stop", target, emit)
        run_native([executable, "-NoProfile", "-NonInteractive", "-Command", script], emit)
    else:
        # A disabled boot policy does not claim to mask a distribution-owned unit.
        if mode == "disabled":
            control("stop", target, emit)
        run_native(["/usr/bin/systemctl", "enable" if mode == "automatic" else "disable", "meshcore-ems.service"], emit)
    actual = startup_mode(target)
    if actual != mode and not (target != "windows-x64" and mode == "disabled" and actual == "manual"):
        raise RuntimeError("Startup policy could not be verified; review service diagnostics")


def installed_capabilities(root):
    """Read a protected installation declaration; current GUI code grants no legacy capability."""
    path = Path(root) / "DESKTOP-CAPABILITIES.json"
    if not path.is_file():
        return []
    trusted_installed(path, root)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != 1 or not isinstance(value.get("capabilities"), list) or any(not isinstance(item, str) for item in value["capabilities"]):
        raise ValueError("Invalid installed service capability declaration")
    return sorted(value["capabilities"])


def snapshot(target, emit=lambda message: None):
    """Return authoritative service state and opaque revision tokens without secret values."""
    root, state, config, python, platform = installed_paths(target)
    status = service_state(target)
    registered = status != "missing"
    startup = startup_mode(target) if registered else "manual"
    digest = hashlib.sha256()
    for path in (config / "config.json", config / "environment.json", config / integrations.RECEIPT, root / "DESKTOP-CAPABILITIES.json",
                 root / "PAYLOAD-MANIFEST.json", root / "installers/desktop/service_backend.py", root / "installers/desktop/service_integrations.py", python):
        digest.update(str(path).encode("utf-8")); digest.update(b"\x00")
        if path.is_file():
            metadata = path.stat()
            digest.update(json.dumps([str(path.resolve()), metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_mode, metadata.st_uid, metadata.st_gid]).encode())
            with path.open("rb") as stream:
                digest.update(hashlib.file_digest(stream, "sha256").digest())
        else:
            digest.update(b"absent")
    digest.update(json.dumps([status, startup, str(root.resolve())]).encode("utf-8"))
    return {"registered": registered, "state": status, "startup": startup,
            "settings": configuration_summary(config), "revision": digest.hexdigest(),
            "capabilities": installed_capabilities(root) if registered else [],
            "installation_directory": str(root), "state_directory": str(state)}


def read_credentials(config):
    """Read saved secrets only inside an authorized worker, never into GUI fields."""
    path = config / "environment.json"
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def configuration_summary(config):
    """Return editable settings and credential names without returning secret values."""
    path = config / "config.json"
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    responder = value.get("responder", {})
    channels = {"channels": responder.get("channels", {}), "command_channels": {name: spec.get("channels", []) for name, spec in responder.get("commands", {}).items()}}
    mqtt = value.get("mqtt", {})
    safe_mqtt = {key: mqtt[key] for key in ("host", "port", "tls") if key in mqtt}
    safe_mqtt["local_broker"] = value.get("local_broker", False)
    preview, receipt_error = {"changes": [], "conflicts": []}, ""
    try:
        receipt = integrations.read_receipt(config)
        _, _, conflicts = integrations.revert_changes(value, receipt)
        preview["conflicts"] = conflicts
        for entry in receipt["changes"]:
            if integrations.node(value, entry["path"]) == entry["after"]:
                preview["changes"].append({"path": ".".join(entry["path"]), "current": entry["after"], "restore": entry["before"]})
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        receipt_error = "The local integration receipt requires recovery from a retained backup; its ownership cannot be inferred."
    return {"connection": value.get("connection", {}), "serial_port": value.get("serial_port", "auto"),
            "channels": channels, "mqtt": safe_mqtt,
            "dataset_root": value.get("dataset_root", ""),
            "commands": {name: {"enabled": bool(spec.get("channels")), "channels": list(spec.get("channels", [])), "script": spec.get("script", ""),
                                "owner": "operator-program" if spec.get("script", "").startswith("programs/") else "service-package"}
                         for name, spec in responder.get("commands", {}).items()},
            "credential_names": sorted(read_credentials(config)), "deconfiguration": preview,
            "deconfiguration_error": receipt_error}


def configure_installed(target, settings, emit):
    """Run the installed validator under its private interpreter; request secrets stay private."""
    root, state, config, python, platform = installed_paths(target)
    if {"dataset_root", "commands", "programs"} & settings.keys() and "settings-v2" not in installed_capabilities(root):
        raise RuntimeError("The installed maintenance backend predates unified settings. Review a service update/repair with the current native installer first.")
    program = trusted_installed(root / "installers/desktop/service_backend.py", root)
    if not python.is_file():
        raise RuntimeError("The installed service runtime is missing; run service installation/repair first")
    trusted_runtime(python, root)
    credentials = read_credentials(config)
    credentials.update(settings.get("credentials", {}))
    with private_temporary_directory("meshcore-settings-") as temporary:
        path = Path(temporary) / "settings.json"
        write_private_file(path, content=json.dumps(settings).encode("utf-8"))
        run_native([python, "-I", "-B", program, "--apply-settings", path], emit, credentials=credentials)
    validate_installed(target, emit)


def validate_installed(target, emit):
    """Run the package-owned offline readiness check without opening a radio."""
    root, state, config, python, platform = installed_paths(target)
    current = json.loads((config / "config.json").read_text(encoding="utf-8-sig"))
    validate_dataset_access(current.get("dataset_root", str(state / "data")), platform)
    trusted_runtime(python, root)
    package = root / ("meshcore_mqtt_service_windows" if platform == "windows" else "meshcore_mqtt_service")
    runner = trusted_installed(package / "service_runner.py", root)
    run_native([python, "-B", runner, "--config", config / "config.json", "--state-dir", state / "runtime", "--environment", config / "environment.json", "--check"],
               emit, credentials=read_credentials(config))


def validate_dataset_access(value, platform):
    """Check shared-root traversal without widening operator directory permissions.

    Managed dataset backends own content permissions. This check rejects private
    POSIX ancestors before a service start; Windows ACL qualification remains a
    native lifecycle check, and no ancestor ACL is rewritten here.
    """
    root = Path(value)
    if not root.is_absolute() or ".datasets" in root.parts:
        raise ValueError("Select a shared dataset root, never a generation path")
    if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        raise ValueError("Shared dataset root cannot be a symbolic link or junction")
    if platform == "windows":
        return
    import grp
    import pwd
    try:
        account = pwd.getpwnam("meshcore-ems")
        service_uid = account.pw_uid
        service_groups = {account.pw_gid, *(group.gr_gid for group in grp.getgrall() if "meshcore-ems" in group.gr_mem)}
    except KeyError:
        service_uid, service_groups = None, set()
    for directory in (root, *root.parents):
        if not directory.exists():
            continue
        metadata = directory.stat()
        # POSIX uses the owner's class first, then group, then others. A broad
        # OR would incorrectly accept other-execute when this owner lacks it.
        permission = 0o100 if metadata.st_uid == service_uid else 0o010 if metadata.st_gid in service_groups else 0o001
        if not directory.is_dir() or not metadata.st_mode & permission:
            raise ValueError("The service account cannot traverse the selected dataset root. Choose the shared default or a directory with service-readable ancestors; no ancestor permissions were changed.")


def check_connection(target, emit):
    """Run only the package's read-only channel check with exclusive EMS access."""
    from installers.datasets.gui.privileges import require_stopped
    require_stopped(target)
    root, state, config, python, platform = installed_paths(target)
    trusted_runtime(python, root)
    package = root / ("meshcore_mqtt_service_windows" if platform == "windows" else "meshcore_mqtt_service")
    program = trusted_installed(package / "channel_setup.py", root)
    return run_native([python, "-B", program, "--config", config / "config.json", "--environment", config / "environment.json", "check"],
                      emit, credentials=read_credentials(config))


def apply_settings(settings, target=None):
    """Validate, snapshot and update protected settings using installed project schemas.

    Called only by the internal installed interpreter entry point. No radio is
    opened. Existing programs, unknown future settings and blank secrets survive.
    """
    from installers import configure
    validate_settings(settings)
    target = target or native_target()
    root, state, config_dir, python, platform = installed_paths(target)
    config_path = config_dir / "config.json"
    current = json.loads(config_path.read_text(encoding="utf-8-sig"))
    candidate = copy.deepcopy(current)
    receipt = integrations.read_receipt(config_dir)
    package = root / ("meshcore_mqtt_service_windows" if platform == "windows" else "meshcore_mqtt_service")
    configure.configure_connection(candidate, package, platform, settings.get("serial_port"), settings.get("transport"),
                                   settings.get("tcp_host"), settings.get("tcp_port"), settings.get("ble_address"))
    if settings.get("channel"):
        channels = candidate["responder"].get("channels", {})
        if len(channels) != 1:
            raise ValueError("Use the advanced channel registry for multiple channels")
        spec = next(iter(channels.values()))
        spec["name"] = settings["channel"]
        if spec["type"] != "private":
            spec["type"] = "existing"
    if "channels" in settings:
        candidate["responder"]["channels"] = settings["channels"]["channels"]
        assignments = settings["channels"]["command_channels"]
        if set(assignments) - candidate["responder"]["commands"].keys():
            raise ValueError("Unknown command assignments")
        for name, ids in assignments.items():
            candidate["responder"]["commands"][name]["channels"] = ids
    if "mqtt" in settings:
        mqtt = dict(settings["mqtt"])
        candidate["local_broker"] = mqtt.pop("local_broker")
        candidate["mqtt"].update(mqtt)
    if "dataset_root" in settings:
        candidate["dataset_root"] = str(Path(settings["dataset_root"]))
    integrations.configure_commands(candidate, settings, receipt)
    created = integrations.stage_programs(candidate, settings, config_dir)
    secrets = merge_credentials(read_credentials(config_dir), settings)
    try:
        validate_candidate(candidate, secrets, package, platform)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    backup = configure.backup_state(config_path, state)
    environment_path = config_dir / "environment.json"
    if environment_path.exists():
        shutil.copy2(environment_path, backup / "environment.json")
    if (config_dir / integrations.RECEIPT).exists():
        shutil.copy2(config_dir / integrations.RECEIPT, backup / integrations.RECEIPT)
    # The service is stopped. If either sibling publication fails, restore both
    # original files while retaining the recovery snapshot for inspection.
    receipt_path = config_dir / integrations.RECEIPT
    receipt = integrations.record_changes(current, candidate, receipt)
    originals = {path: (path.read_bytes(), path.stat()) if path.exists() else None
                 for path in (environment_path, config_path, receipt_path)}
    try:
        for path, value in ((environment_path, secrets), (config_path, candidate), (receipt_path, receipt)):
            metadata = path.stat() if path.exists() else config_path.stat()
            configure.write_json(path, value)
            if os.name != "nt":
                os.chown(path, metadata.st_uid, metadata.st_gid)
                path.chmod(metadata.st_mode & 0o777)
    except OSError:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
                continue
            content, metadata = original
            temporary = path.with_suffix(path.suffix + ".restore")
            temporary.write_bytes(content)
            if os.name != "nt":
                os.chown(temporary, metadata.st_uid, metadata.st_gid)
                temporary.chmod(metadata.st_mode & 0o777)
            temporary.replace(path)
        for path in created:
            path.unlink(missing_ok=True)
        raise
    print("Service settings validated and saved. Recovery snapshot: " + str(backup))


def validate_candidate(candidate, secrets, package, platform):
    """Apply the installed schemas without importing custom programs or opening devices."""
    from installers import configure
    validate_settings({"credentials": secrets})
    sys.path.insert(0, str(package))
    try:
        from radio_connection import connection_settings
        _, validate = configure.channel_settings(package)
        validate(candidate["responder"], package)
        connection_settings(candidate, "nt" if platform == "windows" else "posix")
        from channels import expected_key
        old_environment = dict(os.environ)
        try:
            for key in list(os.environ):
                if key in CREDENTIALS or SECRET.fullmatch(key):
                    os.environ.pop(key)
            os.environ.update(secrets)
            for spec in candidate["responder"].get("channels", {}).values():
                expected_key(spec)
        finally:
            os.environ.clear(); os.environ.update(old_environment)
    finally:
        sys.path.pop(0)


def deconfigure_settings(target=None):
    """Revert unchanged receipt-owned local settings, retaining secrets, files and conflicts."""
    from installers import configure
    target = target or native_target()
    root, state, config, python, platform = installed_paths(target)
    config_path = config / "config.json"
    current = json.loads(config_path.read_text(encoding="utf-8-sig"))
    candidate, receipt, conflicts = integrations.revert_changes(current, integrations.read_receipt(config))
    package = root / ("meshcore_mqtt_service_windows" if platform == "windows" else "meshcore_mqtt_service")
    validate_candidate(candidate, read_credentials(config), package, platform)
    backup = configure.backup_state(config_path, state)
    receipt_path = config / integrations.RECEIPT
    for retained in (receipt_path, config / "environment.json"):
        if retained.exists():
            shutil.copy2(retained, backup / retained.name)
    originals = {path: (path.read_bytes(), path.stat()) if path.exists() else None for path in (config_path, receipt_path)}
    try:
        for path, value in ((config_path, candidate), (receipt_path, receipt)):
            metadata = path.stat() if path.exists() else config_path.stat()
            configure.write_json(path, value)
            if os.name != "nt":
                os.chown(path, metadata.st_uid, metadata.st_gid); path.chmod(metadata.st_mode & 0o777)
    except OSError:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True); continue
            content, metadata = original
            temporary = path.with_suffix(path.suffix + ".restore")
            temporary.write_bytes(content)
            if os.name != "nt":
                os.chown(temporary, metadata.st_uid, metadata.st_gid); temporary.chmod(metadata.st_mode & 0o777)
            temporary.replace(path)
        raise
    return {"conflicts": conflicts, "detail": "Owned local settings reverted where unchanged. Credentials, custom files, databases and conflicting settings retained.", "backup": str(backup)}


def perform(request, emit, cancel=None):
    """Serialize mutations with native maintenance tools, preserving independent ownership."""
    validate_request(request)
    if request["target"] != native_target():
        raise ValueError("Service request target does not match this computer")
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Operation cancelled before it started")
    from installers.datasets.gui.execution import privileged
    if not privileged():
        raise PermissionError("The native service operation requires desktop administrator authorization")
    if request["action"] in {"status", "diagnostics", "validate"}:
        return _perform(request, emit, cancel)
    from installers.desktop.locking import operation_lock
    with operation_lock():
        return _perform(request, emit, cancel)


def _perform(request, emit, cancel=None):
    """Dispatch an approved fixed operation; report failures without discarding installed state."""
    validate_request(request)
    if request["target"] != native_target():
        raise ValueError("Service request target does not match this computer")
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Operation cancelled before it started")
    from installers.datasets.gui.execution import privileged
    if not privileged():
        raise PermissionError("The native service operation requires desktop administrator authorization")
    action, target = request["action"], request["target"]
    root, state, config, python, platform = installed_paths(target)
    if action == "status":
        return {"status": control("status", target, emit), **snapshot(target, emit)}
    if action == "diagnostics":
        status = control("status", target, emit)
        secrets = read_credentials(config)
        reports = []
        for path in (state / "install.log", state / "runtime/service.log", state / "runtime/wrapper.log"):
            if path.is_file():
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 32768))
                    text = stream.read().decode("utf-8", errors="replace")
                reports.append(str(path) + "\n" + redact(text, secrets))
        return {"status": status, "diagnostics": "\n\n".join(reports) or "No local service logs are available."}
    if action in {"start", "stop"}:
        if action == "start":
            validate_installed(target, emit)
        control(action, target, emit)
        return {"status": control("status", target, emit)}
    if action == "startup":
        if request["mode"] == "automatic":
            validate_installed(target, emit)
        set_startup(target, request["mode"], emit)
        return snapshot(target, emit)
    if action == "validate":
        validate_installed(target, emit)
        return {"detail": "Installed configuration and dependencies validated offline; radio delivery was not tested."}
    if action == "check_connection":
        return {"detail": check_connection(target, emit), "device_writes": False}
    if action == "deconfigure":
        if "settings-v2" not in installed_capabilities(root):
            raise RuntimeError("Service maintenance backend requires update/repair before receipt-based deconfiguration")
        control("stop", target, emit)
        program = trusted_installed(root / "installers/desktop/service_backend.py", root)
        trusted_runtime(python, root)
        report = run_native([python, "-I", "-B", program, "--deconfigure-settings", target], emit, credentials=read_credentials(config))
        return json.loads(report)
    if action == "install":
        if platform == "windows":
            from installers.desktop.windows_trust import validate_paths
            existing = next(path for path in (root, *root.parents) if path.exists())
            validate_paths([existing])
        artifact = select_installer(request["folder"], target, request["artifact_sha256"])
        emit("Installing services without starting; datasets remain independently managed.")
        with private_temporary_directory("meshcore-service-install-") as temporary:
            copy_path = Path(temporary) / artifact.name
            write_private_file(copy_path, source=artifact)
            with copy_path.open("rb") as stream:
                staged_digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if staged_digest != request["artifact_sha256"]:
                raise ValueError("Service installer changed while staging")
            command = [copy_path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOSTART=1"] if platform == "windows" else ["/bin/bash", copy_path, "--no-start"]
            run_native(command, emit, credentials=request.get("settings", {}).get("credentials", {}))
        root, state, config, python, platform = installed_paths(target)
    elif action == "uninstall":
        if platform == "windows":
            candidates = list(root.glob("unins[0-9][0-9][0-9].exe"))
            if len(candidates) != 1:
                raise RuntimeError("The registered native service uninstaller is missing or ambiguous; use Windows Installed Apps")
            program = trusted_installed(candidates[0], root)
            run_native([program, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], emit, removal_root=root, trusted_root=root)
        else:
            program = trusted_installed(root / "installers/linux/uninstall.sh", root)
            run_native(["/bin/bash", program], emit)
        status = control("status", target, emit)
        if (platform == "windows" and status.strip() != "Not installed") or (platform == "linux" and "LoadState=not-found" not in status):
            raise RuntimeError("Native uninstaller exited successfully but the service is still registered. Review diagnostics before retrying.")
        return {"status": status, "detail":"Service removed. Configuration, credentials, datasets, runtime databases and recovery material were retained."}
    # Configure operations stop this service before changing the saved state.
    if action == "configure":
        status = control("status", target, emit)
        if "Not installed" in status or "LoadState=not-found" in status:
            raise RuntimeError("Install services before saving configuration")
        control("stop", target, emit)
    configure_installed(target, request.get("settings", {}), emit)
    if request.get("start", False):
        control("start", target, emit)
    return {"status": control("status", target, emit), "detail":"Service installation/settings completed. A running service does not establish radio delivery.", "settings": configuration_summary(config)}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"--apply-settings", "--deconfigure-settings"}:
        raise SystemExit("This module is an internal installed-settings worker")
    from installers.datasets.gui.execution import privileged
    from installers.desktop.locking import operation_lock
    if not privileged():
        raise SystemExit("Installed settings require native administrator authorization")
    with operation_lock():
        if sys.argv[1] == "--deconfigure-settings":
            if sys.argv[2] not in TARGETS:
                raise SystemExit("Invalid installed target")
            print(json.dumps(deconfigure_settings(sys.argv[2])))
        else:
            apply_settings(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
