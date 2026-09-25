"""Build standalone service ZIPs from current source, without local state.

Run from anywhere: python tools/package_services.py
Shared implementations must agree; resolve differences before packaging rather
than silently distributing two versions. Platform-specific files stay separate.
"""
from pathlib import Path
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("meshcore_mqtt_service", "meshcore_mqtt_service_windows")
COMMON = {
    ".gitignore", "README.md", "RELEASE_NOTES.md", "START-HERE.txt",
    "config.json", "requirements.txt", "service.py", "responder.py",
    "flood_alarm.py", "check_live.py",
}
PLATFORM = {
    PACKAGES[0]: {"Start-Service.sh", "setup.sh", "run.sh", "verify.sh"},
    PACKAGES[1]: {"Start-Service.exe", "Start-Service.cs", "setup.cmd",
                  "setup.ps1", "run.cmd", "run.ps1", "verify.cmd"},
}


def package_files(name):
    base = ROOT / name
    files = [base / entry for entry in COMMON | PLATFORM[name]]
    files += sorted((base / "scripts").glob("*.py"))
    files += sorted((base / "tests").glob("test_*.py"))
    for path in files:
        if not path.is_file():
            raise ValueError(f"Missing package file: {path}")
    if not list((base / "tests").glob("test_*.py")):
        raise ValueError(f"Missing tests: {base}")
    config = json.loads((base / "config.json").read_text(encoding="utf-8-sig"))
    for spec in config["responder"]["commands"].values():
        if base / spec["script"] not in files:
            raise ValueError(f"Configured script omitted from package: {spec['script']}")
    return sorted(files)


def main():
    # Validate both packages before replacing either distribution.
    inventories = {name: package_files(name) for name in PACKAGES}
    left, right = (ROOT / name for name in PACKAGES)
    shared = {"responder.py", "flood_alarm.py", "requirements.txt"}
    shared |= {p.relative_to(ROOT / name).as_posix()
               for name, files in inventories.items() for p in files
               if p.parent.name in {"scripts", "tests"}}
    # These tests deliberately exercise different serial ports/topic namespaces.
    shared -= {"tests/test_responder.py", "tests/test_mqtt_integration.py"}
    for relative in sorted(shared):
        if (left / relative).read_bytes() != (right / relative).read_bytes():
            raise ValueError(f"Shared code differs; reconcile newer changes first: {relative}")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    for name, files in inventories.items():
        destination = output / (name + ".zip")
        temporary = destination.with_suffix(".zip.tmp")
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    archive.write(path, path.relative_to(ROOT).as_posix())
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None:
                    raise ValueError(f"Archive validation failed: {name}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"Built {destination.relative_to(ROOT)} ({len(files)} files)")


if __name__ == "__main__":
    main()
