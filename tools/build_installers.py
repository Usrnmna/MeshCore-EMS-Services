"""Build online Windows x64 and Linux x86_64/ARM64 installers from this workspace.

Windows compilation needs the .NET Framework C# compiler and Inno Setup 6.7+.
Linux .run payloads are architecture-neutral source; architecture is checked at install.
No Python runtimes, pip wheels, environments or private state are embedded.
"""

from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

from package_services import package_files, PACKAGES
from artifact_provenance import source_hashes, write_provenance
from distribution_policy import is_local_reference, validate_paths, validate_tree
from build_documentation import render_document

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v0.9.8-beta"


def water_download_rules():
    """Read the existing root-anchored download-only policy without requiring Git."""
    prefixes = ("/data/basin_plans/", "/data/flood_impacts/", "/data/usgs_water/")
    return [line.strip() for line in (ROOT / ".gitignore").read_text().splitlines()
            if line.strip().lstrip("!").startswith(prefixes)]


def download_only(relative, rules):
    """Apply those collection-specific directory/file rules and explicit exceptions."""
    excluded = False
    name = relative.as_posix()
    for rule in rules:
        include = rule.startswith("!")
        pattern = rule.lstrip("!").lstrip("/")
        matches = (name.startswith(pattern) if pattern.endswith("/")
                   else PurePosixPath(name).match(pattern))
        if matches:
            excluded = not include
    return excluded


def sha(data):
    """Return the SHA-256 digest used by payload manifests and download checks."""
    return hashlib.sha256(data).hexdigest()


def source_files():
    """Collect maintained source, documentation, and data without runtime state or environments."""
    download_rules = water_download_rules()
    files = {
        ROOT / p
        for p in (
            "README.md",
            "RELEASE_NOTES.md",
            "RELEASE_v0.9.8-beta.md",
            "INSTALL.md",
            "LICENSE",
            "AGENTS.md",
            ".gitignore",
            ".gitattributes",
            "archive/README.md",
        )
    }
    for package in PACKAGES:
        files.update(package_files(package))
    for folder in ("satellite_database", "data", "docs", "installers", "tools"):
        for path in (ROOT / folder).rglob("*"):
            relative = path.relative_to(ROOT)
            if (
                not path.is_file()
                or is_local_reference(relative)
                or any(p.startswith(".") or p in {"__pycache__", "runtime"} for p in relative.parts)
                or path.suffix in {".pyc", ".pyo"}
                or path.name.endswith(("-wal", "-shm"))
                or download_only(relative, download_rules)
                # Dataset installers own reference bytes. Keep maintained download
                # tools/guides and curated inputs, never a development snapshot.
                or (relative.parts[0] == "data" and
                    (any(p in {"snapshots", "organized", "raw", "originals", "source", "metadata", "geojson", "boundaries"}
                         for p in relative.parts[2:-1]) or
                     (path.suffix not in {".py", ".md", ".txt"} and
                      relative.as_posix() not in {
                          "data/flood_impacts/pilot.json", "data/usgs_water/local_review_rules.json"})))
            ):
                continue
            files.add(path)
    return validate_paths(files, ROOT)


def stage_payload(destination):
    """Create an isolated build snapshot with normalized shell files and an integrity manifest."""
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {}
    inputs = source_files()
    for path in inputs:
        relative = path.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        if relative.as_posix() == "data/ebmud/README.md":
            data = render_document(path, ROOT, set(inputs)).encode("utf-8")
        # Linux scripts must have LF line endings even when built from Windows Git.
        if path.suffix in {".sh", ".service"} or path.name == "satellite-catalog":
            data = data.replace(b"\r\n", b"\n")
        target.write_bytes(data)
        manifest[relative.as_posix()] = sha(data)
    capabilities = json.dumps({"schema": 1, "capabilities": ["staged-startup-v1", "settings-v2", "operation-lock-v1", "channel-history-v1"]}, indent=2) + "\n"
    (destination / "DESKTOP-CAPABILITIES.json").write_text(capabilities, encoding="utf-8", newline="\n")
    manifest["DESKTOP-CAPABILITIES.json"] = sha(capabilities.encode("utf-8"))
    (destination / "PAYLOAD-MANIFEST.json").write_text(
        json.dumps({"version": VERSION, "files": manifest}, indent=2) + "\n", encoding="utf-8"
    )


def linux_installer(payload, output, arch):
    """Write a checksum-protected self-extracting Linux installer for the selected architecture."""
    validate_tree(payload)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(payload.rglob("*")):
            if not path.is_file():
                continue
            data = path.read_bytes()
            entry = tarfile.TarInfo(path.relative_to(payload).as_posix())
            entry.size = len(data)
            entry.mode = (
                0o755 if path.suffix == ".sh" or path.name == "satellite-catalog" else 0o644
            )
            archive.addfile(entry, io.BytesIO(data))
    archive_bytes = buffer.getvalue()
    header = """#!/usr/bin/env bash
set -euo pipefail
expected_arch="@ARCH@"
expected_sha="@SHA@"
case "${1:-}" in
    --help) echo 'MeshCore EMS v0.9.8-beta online installer (@ARCH@)'
        echo 'sudo bash installer.run [--transport serial|tcp|ble] [--port auto|DEVICE] [--tcp-host IP --tcp-port 5000] [--ble-address ADDRESS] [--channel NAME | --channels-config FILE] [--no-start]'
        echo 'Inspection: bash installer.run --check | --extract EMPTY_DIRECTORY'; exit 0 ;;
esac
line=$(awk '/^__MESHCORE_PAYLOAD__$/{print NR+1; exit}' "$0")
actual_sha=$(tail -n +"$line" "$0" | sha256sum | cut -d ' ' -f1)
[[ $actual_sha == "$expected_sha" ]] || { echo 'Installer payload checksum mismatch.' >&2; exit 1; }
if [[ ${1:-} == --check ]]; then echo 'v0.9.8-beta @ARCH@: payload checksum verified'; exit 0; fi
if [[ ${1:-} == --extract ]]; then
    destination=${2:?Specify an empty destination directory}
    mkdir -p -- "$destination"
    [[ -z $(ls -A -- "$destination") ]] || { echo 'Extraction directory must be empty.' >&2; exit 1; }
    tail -n +"$line" "$0" | tar -xz --no-same-owner -C "$destination"
    echo "Extracted workspace to $destination"; exit 0
fi
[[ $(uname -m) == "$expected_arch" ]] || { echo "Use the installer for $(uname -m), not $expected_arch." >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo 'Run the installer with sudo.' >&2; exit 1; }
temporary=$(mktemp -d /tmp/meshcore-ems.XXXXXXXX)
cleanup() { case "$temporary" in /tmp/meshcore-ems.*) rm -rf -- "$temporary" ;; esac; }
trap cleanup EXIT
tail -n +"$line" "$0" | tar -xz --no-same-owner -C "$temporary"
bash "$temporary/installers/linux/install.sh" "$@"
exit 0
__MESHCORE_PAYLOAD__
""".replace(
        "@ARCH@", arch
    ).replace(
        "@SHA@", sha(archive_bytes)
    )
    label = "raspberry-pi-arm64" if arch == "aarch64" else "linux-x86_64"
    path = output / f"MeshCore-EMS-{VERSION}-{label}.run"
    path.write_bytes(header.encode() + archive_bytes)
    path.chmod(0o755)
    return path


def main():
    """Build platform installers and checksums locally; never install or publish them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", type=Path, default=ROOT / ".build/inno/ISCC.exe")
    parser.add_argument("--linux-only", action="store_true")
    parser.add_argument("--output", type=Path, help="Local installer output directory; default dist/VERSION")
    args = parser.parse_args()
    output = (args.output or ROOT / "dist" / VERSION).resolve()
    output.mkdir(parents=True, exist_ok=True)
    import uuid

    work = ROOT / ".build"
    work.mkdir(exist_ok=True)
    # Keep a unique build snapshot for audit/reproduction; never overwrite a live install.
    build = work / ("installers-" + uuid.uuid4().hex[:12])
    build.mkdir()
    payload = build / "payload"
    input_hashes = source_hashes(source_files(), ROOT)
    stage_payload(payload)
    artifacts = [linux_installer(payload, output, arch) for arch in ("x86_64", "aarch64")]
    if not args.linux_only:
        csc = (
            Path(os.environ.get("WINDIR", r"C:\Windows"))
            / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        )
        subprocess.run(
            [
                str(csc),
                "/nologo",
                "/target:exe",
                "/platform:x64",
                "/r:System.ServiceProcess.dll",
                "/out:" + str(payload / "MeshCoreEMS.Service.exe"),
                str(ROOT / "installers/windows/ServiceHost.cs"),
            ],
            check=True,
        )
        manifest_path = payload / "PAYLOAD-MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["MeshCoreEMS.Service.exe"] = sha(
            (payload / "MeshCoreEMS.Service.exe").read_bytes()
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        subprocess.run(
            [
                str(args.iscc),
                "/Qp",
                "/DPayloadDir=" + str(payload),
                "/DReleaseDir=" + str(output),
                str(ROOT / "installers/windows/setup.iss"),
            ],
            check=True,
        )
        artifacts.append(output / f"MeshCore-EMS-{VERSION}-windows-x64-setup.exe")
    shutil.copy2(ROOT / "INSTALL.md", output / "INSTALL.md")
    shutil.copy2(ROOT / "installers/VALIDATION.md", output / "VALIDATION.md")
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{sha(path.read_bytes())}  {path.name}\n" for path in artifacts), encoding="utf-8"
    )
    for artifact in artifacts:
        if source_hashes(source_files(), ROOT) != input_hashes:
            raise RuntimeError("Source changed during compilation; rebuild before assembling a desktop kit")
        target = "windows-x64" if artifact.suffix == ".exe" else ("raspberry-pi-arm64" if "raspberry-pi-arm64" in artifact.name else "linux-x86_64")
        write_provenance(artifact, "service", source_files(), root=ROOT, target=target)
    print("Payload snapshot:", payload)
    resolved_root = ROOT.resolve()
    for path in artifacts:
        resolved_path = path.resolve()
        try:
            display_path = resolved_path.relative_to(resolved_root)
        except ValueError:
            # --output may legitimately select a directory outside the project.
            display_path = resolved_path
        print(f"{display_path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
