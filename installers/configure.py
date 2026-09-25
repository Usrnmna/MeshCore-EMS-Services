"""Initialize installed settings/data without replacing operator state on upgrade."""
import argparse
import json
from pathlib import Path
import shutil


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def configure(root, state, config_dir, platform, port, channel=None):
    package = root / ("meshcore_mqtt_service_windows" if platform == "windows" else "meshcore_mqtt_service")
    state.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    (state / "runtime").mkdir(exist_ok=True)
    defaults = json.loads((package / "config.json").read_text(encoding="utf-8-sig"))
    config_path = config_dir / "config.json"
    current = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else defaults
    # Preserve customization; add command entries introduced by the new release.
    for command, spec in defaults["responder"]["commands"].items():
        current["responder"]["commands"].setdefault(command, spec)
    current["serial_port"] = port
    if channel:
        current["responder"]["channel_name"] = channel
    if config_path.exists():
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
        settings.update(database=str(state / "data/satellites/satellites.sqlite3"),
                        cache_directory=str(state / "data/satellites/raw"),
                        export_directory=str(state / "data/satellites"))
        write_json(satellite, settings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "state", "config-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--platform", choices=("windows", "linux"), required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--channel")
    args = parser.parse_args()
    configure(args.root.resolve(), args.state.resolve(), args.config_dir.resolve(),
              args.platform, args.port, args.channel)
