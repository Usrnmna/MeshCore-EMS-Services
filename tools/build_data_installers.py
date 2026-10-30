"""Build separate dataset installers without installing software or acquiring live data.

Each collection has Windows x64, Linux x86_64 and Raspberry Pi ARM64 artifacts.
Only enumerated maintenance sources and published reference seeds enter payloads.
Downloaded water generations, environments and operator state are never packaged.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import uuid

from build_installers import download_only, water_download_rules
from artifact_provenance import source_hashes, write_provenance
from distribution_policy import is_local_reference, validate_tree
from build_documentation import render_document

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v0.9.8-beta"
DATASETS = ("ebmud", "basin_plans", "flood_impacts", "usgs_water", "wildfire",
            "landslide", "california_state_parks", "satellites")
DISPLAY_NAMES = dict(zip(DATASETS, ("EBMUD", "Basin Plans", "Flood Reference", "USGS Water",
                                   "Wildfire", "Landslide", "California State Parks", "Satellites")))
PLATFORMS = {"linux-x86_64": "x86_64", "raspberry-pi-arm64": "aarch64"}
SEEDS = {"ebmud": "data/ebmud", "california_state_parks": "data/california_state_parks",
         "wildfire": "data/wildfire", "landslide": "meshcore_mqtt_service/data/landslide"}


def digest(data):
    """Return the content hash used for package and extracted payload validation."""
    return hashlib.sha256(data).hexdigest()


def source_inventory(root=ROOT):
    """Enumerate maintained code and curated settings, excluding downloaded state."""
    paths = {"LICENSE", "README.md", "INSTALL.md", "docs/DATA_PACKAGES.md",
             "installers/VALIDATION.md", "installers/datasets/BUILD.md",
             "meshcore_mqtt_service/config.json", "meshcore_mqtt_service/gis_settings.json",
             "data/flood_impacts/pilot.json", "data/usgs_water/local_review_rules.json",
             "satellite_database/settings.json", "satellite_database/operator_overrides.json",
             "satellite_database/schema.sql"}
    source_directories = (
        "installers/datasets", "data/basin_plans", "data/flood_impacts", "data/usgs_water",
        "data/ebmud", "data/california_state_parks", "satellite_database",
        "meshcore_mqtt_service/scripts",
    )
    for directory in source_directories:
        for path in (root / directory).glob("*.py"):
            if not path.name.startswith("test_"):
                paths.add(path.relative_to(root).as_posix())
        paths.update(path.relative_to(root).as_posix()
                     for path in (root / directory).glob("requirements*.txt"))
    for directory, suffixes in (("installers/datasets/windows", {".ps1", ".cmd", ".iss"}),
                                ("installers/datasets/linux", {".sh"}),
                                ("installers/desktop", {".sh", ".ps1", ".iss"})):
        for path in (root / directory).iterdir():
            if path.is_file() and path.suffix in suffixes:
                paths.add(path.relative_to(root).as_posix())
    paths.update(path.relative_to(root).as_posix()
                 for path in (root / "installers/datasets").glob("requirements*.txt"))
    paths.add("installers/desktop/locking.py")
    paths.add("installers/desktop/native_environment.py")
    paths.update({"installers/desktop/staging.py", "installers/desktop/windows_trust.py", "installers/desktop/authorization.py"})
    for path in (root / "docs").rglob("*"):
        if path.is_file() and not any(part.startswith(".") or part == "__pycache__"
                                      for part in path.relative_to(root / "docs").parts):
            paths.add(path.relative_to(root).as_posix())
    for directory in (*source_directories[1:-1], "meshcore_mqtt_service", "meshcore_mqtt_service_windows"):
        paths.update(path.relative_to(root).as_posix() for path in (root / directory).glob("*.md"))
    # The same maintained download-only policy applies to generated reports and data.
    rules = water_download_rules()
    return sorted(relative for relative in paths
                  if not is_local_reference(relative) and not download_only(Path(relative), rules))


def seed_inventory(dataset, root=ROOT):
    """Include complete maintained reference snapshots, preserving original bytes."""
    if dataset not in SEEDS:
        return []
    directory = root / SEEDS[dataset]
    return sorted(path for path in directory.rglob("*") if path.is_file()
                  and not any(part.startswith(".") or part == "__pycache__"
                              for part in path.relative_to(directory).parts)
                  and path.suffix not in {".py", ".pyc", ".pyo"})


def provenance_sources(dataset, root=ROOT):
    """Include payload sources, seeds, and the recipe that selects/compiles them."""
    return ([root / relative for relative in source_inventory(root)] + seed_inventory(dataset, root)
            + [root / "tools/build_data_installers.py", root / "tools/build_installers.py",
               root / "tools/artifact_provenance.py", root / "tools/distribution_policy.py", root / "tools/build_documentation.py", root / ".gitignore"])


def stage_payload(destination, dataset, root=ROOT, version=VERSION):
    """Make an immutable build snapshot and its exact per-file integrity inventory."""
    if dataset not in DATASETS:
        raise ValueError("Unknown dataset")
    destination.mkdir(parents=True, exist_ok=False)
    inventory = {}
    sources = [(root / relative, Path(relative)) for relative in source_inventory(root)]
    sources += [(path, Path("seeds") / dataset / path.relative_to(root / SEEDS[dataset]))
                for path in seed_inventory(dataset, root)]
    for source, relative in sources:
        data = source.read_bytes()
        if relative.as_posix() == "data/ebmud/README.md":
            data = render_document(source, root, {path for path, _ in sources}).encode("utf-8")
        if source.suffix == ".sh":
            data = data.replace(b"\r\n", b"\n")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        inventory[relative.as_posix()] = digest(data)
    (destination / "dataset-id.txt").write_text(dataset + "\n", encoding="utf-8", newline="\n")
    inventory["dataset-id.txt"] = digest((dataset + "\n").encode())
    package = json.dumps({"dataset": dataset, "version": version,
                          "capabilities": ["retain-data-v1", "maintenance-lock-v1", "dataset-lock-recovery-v1"]}, indent=2) + "\n"
    (destination / "DATA-PACKAGE.json").write_text(package, encoding="utf-8", newline="\n")
    inventory["DATA-PACKAGE.json"] = digest(package.encode())
    manifest = {"version": version, "dataset": dataset, "files": inventory}
    (destination / "PAYLOAD-MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def linux_installer(payload, output, dataset, platform, version=VERSION):
    """Produce a self-contained source bundle with checksum and inspection commands."""
    validate_tree(payload)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                entry = tarfile.TarInfo(path.relative_to(payload).as_posix())
                data = path.read_bytes()
                entry.size = len(data)
                entry.mode = 0o755 if path.suffix == ".sh" else 0o644
                archive.addfile(entry, io.BytesIO(data))
    compressed = buffer.getvalue()
    template = (ROOT / "installers/datasets/linux/header.sh").read_text(encoding="utf-8")
    for key, value in {"ARCH": PLATFORMS[platform], "SHA": digest(compressed),
                       "DATASET": dataset, "VERSION": version}.items():
        template = template.replace("@" + key + "@", value)
    target = output / f"MeshCore-EMS-Data-{dataset}-{version}-{platform}.run"
    target.write_bytes(template.replace("\r\n", "\n").encode() + compressed)
    target.chmod(0o755)
    return target


def compile_windows_tool(destination, version=VERSION):
    """Compile the readable entry point once with the pinned PS2EXE toolchain.

    The executable stays outside the shared Linux/Pi payload. Preserve the exact
    input and output hashes beside the binary for release and native-test evidence.
    """
    destination.mkdir(parents=True, exist_ok=False)
    source = destination / "dataset.ps1"
    shutil.copy2(ROOT / "installers/datasets/windows/dataset.ps1", source)
    executable = destination / "Dataset.exe"
    numeric_version = re.match(r"v(\d+\.\d+\.\d+)", version).group(1) + ".0"
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(ROOT / "installers/datasets/windows/build_tool.ps1"),
                    "-Source", str(source), "-Output", str(executable), "-Version", numeric_version], check=True)
    metadata = {"ps2exe_version": "1.0.18", "version": numeric_version,
                "source_sha256": digest(source.read_bytes()), "executable_sha256": digest(executable.read_bytes()),
                "compiler_script_sha256": digest((ROOT / "installers/datasets/windows/build_tool.ps1").read_bytes())}
    (destination / "BUILD.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return executable


def main():
    """Build selected packages and publish a local checksum inventory on success."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", choices=DATASETS)
    parser.add_argument("--version", default=VERSION, help="Independent data release version, for example v1.0.0")
    parser.add_argument("--linux-only", action="store_true")
    parser.add_argument("--output", type=Path, help="Local dataset installer output directory; default dist/VERSION/datasets")
    parser.add_argument("--iscc", type=Path, default=ROOT / ".build/inno/ISCC.exe")
    parser.add_argument("--sign-tool", metavar="NAME=COMMAND", help="Optional Inno Setup signing tool definition")
    args = parser.parse_args()
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", args.version):
        parser.error("--version must use vMAJOR.MINOR.PATCH with an optional release suffix")
    if not args.linux_only and not args.iscc.is_file():
        parser.error("Inno Setup compiler unavailable; use --iscc or --linux-only")
    signing = []
    if args.sign_tool:
        name, separator, command = args.sign_tool.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or not command.strip():
            parser.error("--sign-tool requires NAME=COMMAND with an alphanumeric tool name")
        signing = [f"/S{name}={command}", f"/DSignToolName={name}"]
    output = (args.output or ROOT / "dist" / args.version / "datasets").resolve()
    output.mkdir(parents=True, exist_ok=True)
    build = ROOT / ".build" / ("data-installers-" + uuid.uuid4().hex[:12])
    executable = None if args.linux_only else compile_windows_tool(build / "windows-tool", args.version)
    artifacts = []
    for dataset in args.dataset or DATASETS:
        payload = build / dataset / "payload"
        input_hashes = source_hashes(provenance_sources(dataset), ROOT)
        manifest = stage_payload(payload, dataset, version=args.version)
        for platform in PLATFORMS:
            artifacts.append(linux_installer(payload, output, dataset, platform, args.version))
        if not args.linux_only:
            subprocess.run([str(args.iscc), *signing, f"/DPayloadDir={payload}", f"/DReleaseDir={output}",
                            f"/DDataset={dataset}", f"/DReleaseVersion={args.version}",
                            f"/DDatasetName={DISPLAY_NAMES[dataset]}", f"/DMaintenanceExe={executable}",
                            str(ROOT / "installers/datasets/windows/setup.iss")], check=True)
            artifacts.append(output / f"MeshCore-EMS-Data-{dataset}-{args.version}-windows-x64-setup.exe")
        for artifact in artifacts:
            if not artifact.name.startswith(f"MeshCore-EMS-Data-{dataset}-"):
                continue
            if source_hashes(provenance_sources(dataset), ROOT) != input_hashes:
                raise RuntimeError("Source changed during compilation; rebuild before assembling a desktop kit")
            target = "windows-x64" if artifact.suffix == ".exe" else ("raspberry-pi-arm64" if "raspberry-pi-arm64" in artifact.name else "linux-x86_64")
            write_provenance(artifact, "dataset", provenance_sources(dataset), root=ROOT, target=target, dataset=dataset)
        print(f"{dataset}: packaged {len(manifest['files'])} source and seed files", flush=True)
    # Include previously built subsets in the distribution-wide checksum inventory.
    releases = sorted(path for path in output.iterdir() if path.suffix in {".exe", ".run"})
    (output / "SHA256SUMS.txt").write_text("".join(f"{digest(path.read_bytes())}  {path.name}\n" for path in releases), encoding="utf-8")
    print(f"Built {len(artifacts)} installers in {output}")
    print(f"Build snapshot: {build}")


if __name__ == "__main__":
    main()
