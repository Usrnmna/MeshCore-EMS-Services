"""Assemble a native desktop kit from fresh, independently built applications.

This developer tool copies checked artifacts only. It never installs packages,
requests elevation, downloads datasets, or starts services. Build on each target;
the toolkit does not cross-compile GUI runtimes.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import tarfile

import build_data_installers as data_builder
import build_dataset_gui as gui_builder
import build_installers as service_builder
from distribution_policy import validate_tree
from build_documentation import copy_documentation
from artifact_provenance import file_hash, verify_provenance
from installers.datasets.gui.discovery import native_target
from installers.datasets.gui.planning import installer_artifact

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("windows-x64", "linux-x86_64", "raspberry-pi-arm64")


def checked_child(root, relative):
    """Reject manifest traversal and symlinks that escape a native app bundle."""
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe bundle manifest path")
    child = root / relative
    if not child.resolve().is_relative_to(root):
        raise ValueError("Bundle link escapes the application directory")
    return child


def validate_linux_baseline(record, target):
    """Reject builds newer than Debian 12/Bookworm's glibc before kit assembly.

    This conservative host-baseline gate is necessary but does not replace a
    bundled ELF dependency audit or a native clean-desktop acceptance test.
    """
    if target == "windows-x64":
        return
    baseline = record.get("build_libc", [])
    if (not isinstance(baseline, list) or len(baseline) != 2 or baseline[0] != "glibc"
            or not isinstance(baseline[1], str) or not re.fullmatch(r"\d+\.\d+", baseline[1])
            or tuple(map(int, baseline[1].split("."))) > (2, 36)):
        raise ValueError("Rebuild the Linux/Pi GUI on glibc 2.36 or older for Debian 12/Bookworm compatibility; this build is for newer-host validation only")


def verify_gui(folder, target, app):
    """Require matching native binaries, current compiled sources and intact files."""
    folder = Path(folder).resolve()
    record = json.loads((folder / "BUILD.json").read_text(encoding="utf-8"))
    if record.get("target") != target:
        raise ValueError("GUI build target does not match the kit target")
    validate_linux_baseline(record, target)
    if record.get("app") != app:
        raise ValueError("Wrong GUI application: keep service and dataset installers separate")
    if record.get("source_sha256") != gui_builder.source_hashes():
        raise ValueError("GUI/worker source changed since compilation; rebuild the native application")
    name = gui_builder.APP_NAME if app == "dataset" else gui_builder.SERVICE_APP_NAME
    executable = folder / (name + (".exe" if target == "windows-x64" else ""))
    if not executable.is_file():
        raise ValueError("Native GUI executable is missing")
    manifest = record.get("bundle_sha256")
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("GUI file inventory is missing; rebuild it")
    for relative, expected in manifest.items():
        child = checked_child(folder, relative)
        if not child.is_file() or file_hash(child) != expected:
            raise ValueError("GUI bundle file changed: " + relative)
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p != folder / "BUILD.json"}
    if actual != set(manifest):
        raise ValueError("GUI bundle contains additional or missing files")
    return folder


def service_artifact(folder, target):
    """Select exactly one checksummed installer matching the native kit platform."""
    folder = Path(folder).resolve()
    suffix = "windows-x64-setup.exe" if target == "windows-x64" else target + ".run"
    expression = re.compile(r"MeshCore-EMS-v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?-" + re.escape(suffix))
    matches = [p for p in folder.iterdir() if p.is_file() and expression.fullmatch(p.name)]
    if len(matches) != 1:
        raise ValueError("Choose a service installer folder with exactly one matching target/version")
    artifact = matches[0]
    checksums = {}
    for line in (folder / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            checksums[parts[1].lstrip("*")] = parts[0].lower()
    if checksums.get(artifact.name) != file_hash(artifact):
        raise ValueError("Service installer checksum does not match")
    return artifact


def copy_artifact(artifact, destination):
    """Copy immutable installer bytes and their source provenance together."""
    destination.mkdir(parents=True, exist_ok=True)
    digest = file_hash(artifact)
    target = destination / artifact.name
    shutil.copy2(artifact, target)
    if file_hash(target) != digest:
        raise ValueError("Installer changed while copying")
    provenance = artifact.with_name(artifact.name + ".provenance.json")
    shutil.copy2(provenance, destination / provenance.name)
    return target, digest


def desktop_entry(title, relative):
    """Create a relocatable desktop launcher; %k supplies the launcher location.

    The fixed shell expression only locates an adjacent native GUI. It neither
    elevates nor accepts installation commands. Desktop trust prompts remain
    controlled by the file manager and must be qualified on the target desktop.
    """
    command = f'exec "$(dirname -- "$1")/{relative}"'
    escaped = command.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    # The key-file layer consumes one escaping level before Exec is parsed.
    exec_value = ('/bin/sh -c "' + escaped + '" meshcore-desktop %k').replace("\\", "\\\\")
    return ("[Desktop Entry]\nType=Application\nVersion=1.0\nName=" + title + "\n"
            'Exec=' + exec_value + '\n'
            "Terminal=false\nCategories=System;Settings;\n")


def make_archive(folder, target):
    """Use tar for Linux so extraction retains native executable/link metadata."""
    folder = Path(folder)
    validate_tree(folder)
    if target == "windows-x64":
        return Path(shutil.make_archive(str(folder), "zip", folder.parent, folder.name))
    path = Path(str(folder) + ".tar.gz")
    def permissions(entry):
        # Windows fixture builds cannot represent POSIX executable bits. The
        # native release path retains all modes and explicitly marks GUI launchers.
        name = Path(entry.name).name
        if entry.isfile() and (name in {gui_builder.APP_NAME, gui_builder.SERVICE_APP_NAME}
                               or name.endswith(".desktop")):
            entry.mode |= 0o111
        return entry
    with tarfile.open(path, "w:gz", dereference=False) as archive:
        archive.add(folder, arcname=folder.name, filter=permissions)
    return path


def start_guide(target):
    """Keep the extracted kit's instructions independent of source-checkout links."""
    guide = (ROOT / "docs/DESKTOP_INSTALLATION.md").read_text(encoding="utf-8").split("## Developer packaging", 1)[0]
    guide = re.sub(r"\[([^\]]+)\]\((?!https?://)[^)]+\)", r"\1", guide)
    if target == "windows-x64":
        launch = "Open `dataset-manager/MeshCore-EMS-Dataset-Manager.exe` for unified installation and maintenance. Service Setup remains available as an independent fallback."
    else:
        launch = "Open `1-Installation.desktop`; use the graphical **Allow Launching** action when required. Service Setup remains available as an independent fallback."
    return "Target: **" + target + "**\n\n" + launch + "\n\n" + guide


def build(output, dataset_gui, service_gui, service_installers, dataset_installers, *, target=None):
    """Validate all inputs before creating a new kit; never overwrite distributions."""
    target = target or native_target()
    if target not in TARGETS or target != native_target():
        raise ValueError("Build a kit on its matching native platform; GUI cross-compilation is unavailable")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a new output directory")
    dataset_gui = verify_gui(dataset_gui, target, "dataset")
    service_gui = verify_gui(service_gui, target, "service")
    service = service_artifact(service_installers, target)
    verify_provenance(service, "service", service_builder.source_files(), root=ROOT, target=target)
    datasets = []
    for name in data_builder.DATASETS:
        artifact, digest = installer_artifact(dataset_installers, name, target)
        verify_provenance(artifact, "dataset", data_builder.provenance_sources(name), root=ROOT, target=target, dataset=name)
        datasets.append(artifact)
    output.mkdir(parents=True)
    shutil.copytree(dataset_gui, output / "dataset-manager", symlinks=True)
    shutil.copytree(service_gui, output / "service-setup", symlinks=True)
    service_folder = output / "dataset-manager/service-installers"
    copied_service, service_hash = copy_artifact(service, service_folder)
    (service_folder / "SHA256SUMS.txt").write_text(f"{service_hash}  {copied_service.name}\n", encoding="utf-8")
    dataset_folder = output / "dataset-manager/datasets"
    dataset_folder.mkdir(exist_ok=True)
    entries = []
    for artifact in datasets:
        copied, digest = copy_artifact(artifact, dataset_folder)
        entries.append(f"{digest}  {copied.name}\n")
    (dataset_folder / "SHA256SUMS.txt").write_text("".join(entries), encoding="utf-8")
    (output / "START-HERE.md").write_text(start_guide(target), encoding="utf-8")
    copy_documentation(ROOT, output / "documentation")
    with (output / "START-HERE.md").open("a", encoding="utf-8") as guide:
        guide.write("\n[Complete installation and maintenance documentation]"
                    "(documentation/docs/DESKTOP_INSTALLATION.md).\n")
    shutil.copy2(ROOT / "LICENSE", output / "LICENSE")
    if target != "windows-x64":
        for label, title, relative in (
                ("1-Installation.desktop", "MeshCore EMS Installation and Maintenance", "dataset-manager/" + gui_builder.APP_NAME),
                ("2-Service-Setup.desktop", "Independent EMS Service Setup", "service-setup/" + gui_builder.SERVICE_APP_NAME)):
            path = output / label
            path.write_text(desktop_entry(title, relative), encoding="utf-8", newline="\n")
            path.chmod(0o755)
    files = {p.relative_to(output).as_posix(): file_hash(p) for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "KIT.json").write_text(json.dumps({"schema": 1, "target": target, "version": service_builder.VERSION,
        "separate_installers": True, "files": files}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "SHA256SUMS.txt").write_text("".join(f"{digest}  {name}\n" for name, digest in files.items())
        + f"{file_hash(output / 'KIT.json')}  KIT.json\n", encoding="utf-8")
    archive = make_archive(output, target)
    archive.with_name(archive.name + ".sha256").write_text(f"{file_hash(archive)}  {archive.name}\n", encoding="utf-8")
    print("Desktop kit: " + str(archive))
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New kit directory")
    parser.add_argument("--dataset-gui", type=Path, required=True, help="Fresh native Dataset Manager app directory")
    parser.add_argument("--service-gui", type=Path, required=True, help="Fresh native Service Setup app directory")
    parser.add_argument("--service-installers", type=Path, default=ROOT / "dist" / service_builder.VERSION)
    parser.add_argument("--dataset-installers", type=Path, default=ROOT / "dist" / service_builder.VERSION / "datasets")
    args = parser.parse_args()
    build(args.output, args.dataset_gui, args.service_gui, args.service_installers, args.dataset_installers)


if __name__ == "__main__":
    main()
