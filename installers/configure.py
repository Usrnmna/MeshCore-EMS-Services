"""Initialize installed settings/data without replacing operator state on upgrade."""

import argparse
import copy
from contextlib import closing
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys


def write_json(path, value):
    """Replace one JSON file atomically; restrict new POSIX files before replacement."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(path)


def channel_settings(package):
    """Use the installed package's schema and migration, without opening the radio."""
    sys.path.insert(0, str(package))
    try:
        channels = importlib.import_module("channels")
        responder = importlib.import_module("responder")

        def validate(config, root):
            """Check channel privacy first, then enabled command scripts and limits."""
            # Validate privacy settings even while the responder is disabled.
            channels.validate_channels(config)
            responder.validate_config(config, root)

        return channels.migrate_config, validate
    finally:
        sys.path.pop(0)


def import_channels(responder, path):
    """Apply registry and explicit assignments; reject typos instead of ignoring them."""
    values = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(values, dict) or set(values) != {"channels", "command_channels"}:
        raise ValueError("Channels JSON must contain channels and command_channels only")
    assignments = values["command_channels"]
    if not isinstance(assignments, dict):
        raise ValueError("command_channels must map command phrases to channel ID lists")
    unknown = set(assignments) - set(responder["commands"])
    if unknown:
        raise ValueError("Unknown command assignments: " + ", ".join(sorted(unknown)))
    responder["channels"] = values["channels"]
    for command, ids in assignments.items():
        responder["commands"][command]["channels"] = ids


def backup_state(config_path, state):
    """Save a dated config and consistent SQLite snapshots before changing settings."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = state / "backups" / stamp
    destination.mkdir(parents=True, mode=0o700)
    shutil.copy2(config_path, destination / "config.json")
    for source in (state / "runtime").glob("*.sqlite3"):
        # SQLite backup incorporates committed WAL data; a plain file copy may not.
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(destination / source.name)) as backup:
                original.backup(backup)
        if os.name != "nt":
            (destination / source.name).chmod(0o600)
    if os.name != "nt":
        (destination / "config.json").chmod(0o600)
    return destination


def configure_connection(
    config, package, platform, port, transport, tcp_host, tcp_port, ble_address
):
    """Merge explicit transport options, then validate before writing installed settings."""
    sys.path.insert(0, str(package))
    try:
        from radio_connection import connection_settings

        kinds = set()
        if port is not None:
            kinds.add("serial")
        if tcp_host is not None or tcp_port is not None:
            kinds.add("tcp")
        if ble_address is not None:
            kinds.add("ble")
        if transport is not None:
            kinds.add(transport)
        if len(kinds) > 1:
            raise ValueError("Connection options must select exactly one transport")
        previous = config.get("connection", {"type": "serial"})
        kind = next(iter(kinds)) if kinds else previous.get("type", "serial")
        values = dict(previous) if previous.get("type", "serial") == kind else {"type": kind}
        values["type"] = kind
        if port is not None:
            config["serial_port"] = "auto" if port.lower() == "auto" else port
        for name, value in (("host", tcp_host), ("port", tcp_port), ("address", ble_address)):
            if value is not None:
                values[name] = value
        config["connection"] = values
        settings = connection_settings(config, "nt" if platform == "windows" else "posix")
        if kind == "tcp":
            values.setdefault("port", settings["port"])
    finally:
        sys.path.pop(0)


def configure(
    root,
    state,
    config_dir,
    platform,
    port=None,
    channel=None,
    channels_config=None,
    transport=None,
    tcp_host=None,
    tcp_port=None,
    ble_address=None,
):
    """Merge settings, validate, back up existing state, then write installed files.

    Existing program assignments are preserved. An existing registry disables new
    programs until explicitly assigned; legacy settings retain their one channel.
    This function never connects to or programs a radio, and never starts services.
    """
    package = root / (
        "meshcore_mqtt_service_windows" if platform == "windows" else "meshcore_mqtt_service"
    )
    state.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    (state / "runtime").mkdir(exist_ok=True)
    defaults = json.loads((package / "config.json").read_text(encoding="utf-8-sig"))
    config_path = config_dir / "config.json"
    current = (
        json.loads(config_path.read_text(encoding="utf-8-sig"))
        if config_path.exists()
        else defaults
    )
    migrate, validate = channel_settings(package)
    responder = current["responder"]
    # Operator programs live beside installed settings so application upgrades
    # never replace them. A custom absolute location remains operator-managed.
    programs = config_dir / "programs"
    programs.mkdir(exist_ok=True, mode=0o750)
    responder.setdefault("program_directory", str(programs.resolve()))
    had_registry = "channels" in responder
    # Preserve assignments on upgrade; new commands require opt-in on a registry.
    for command, spec in defaults["responder"]["commands"].items():
        if command not in responder["commands"]:
            added = copy.deepcopy(spec)
            added["channels"] = [] if had_registry else ["default"]
            responder["commands"][command] = added
    migrate(responder)
    # Omitted installer options preserve the saved connection on upgrades.
    configure_connection(
        current, package, platform, port, transport, tcp_host, tcp_port, ble_address
    )
    if channel:
        if channels_config:
            raise ValueError("Use --channel or --channels-config, not both")
        if len(responder["channels"]) != 1:
            raise ValueError("--channel is ambiguous with multiple channels; use --channels-config")
        key = next(iter(responder["channels"]))
        responder["channels"][key]["name"] = channel
        # Legacy --channel selects an existing named radio channel. A Public or
        # private name must not inherit the shipped hashtag key-derivation rule.
        # Explicit private-key settings remain authoritative when already present.
        if responder["channels"][key]["type"] != "private":
            responder["channels"][key]["type"] = "existing"
    if channels_config:
        import_channels(responder, channels_config)
    validate(responder, package)
    if config_path.exists():
        backup_state(config_path, state)
        shutil.copy2(config_path, config_dir / "config.before-install.json")
    write_json(config_path, current)
    environment = config_dir / "environment.json"
    if not environment.exists():
        write_json(environment, {})
    # Copy supplied snapshots only on first installation. Never reset a refreshed catalog.
    for source in (root / "data").rglob("*"):
        if source.is_file():
            destination = state / "data" / source.relative_to(root / "data")
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    satellite = config_dir / "satellite-settings.json"
    if not satellite.exists():
        settings = json.loads((root / "satellite_database/settings.json").read_text())
        settings.update(
            database=str(state / "data/satellites/satellites.sqlite3"),
            cache_directory=str(state / "data/satellites/raw"),
            export_directory=str(state / "data/satellites"),
        )
        write_json(satellite, settings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "state", "config-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--platform", choices=("windows", "linux"), required=True)
    parser.add_argument(
        "--port",
        help="Select serial: auto or a fixed device; omission preserves installed settings",
    )
    parser.add_argument("--transport", choices=("serial", "tcp", "ble"))
    parser.add_argument("--tcp-host", help="MeshCore node IP address")
    parser.add_argument(
        "--tcp-port", type=int, help="TCP port (new TCP connections default to 5000)"
    )
    parser.add_argument("--ble-address", help="Previously paired BLE address")
    parser.add_argument("--channel")
    parser.add_argument(
        "--channels-config",
        type=Path,
        help="JSON with channels and command_channels; assignments use stable channel IDs",
    )
    args = parser.parse_args()
    configure(
        args.root.resolve(),
        args.state.resolve(),
        args.config_dir.resolve(),
        args.platform,
        args.port,
        args.channel,
        args.channels_config,
        args.transport,
        args.tcp_host,
        args.tcp_port,
        args.ble_address,
    )
