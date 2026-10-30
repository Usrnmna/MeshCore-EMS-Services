"""Package only the dataset GUI; optionally copy already-built native installers.

Run on each target OS/architecture. No dataset builder, installer, uninstaller,
provider acquisition or service operation is invoked by this script.
"""

import argparse
from importlib.metadata import version
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from distribution_policy import validate_paths, validate_tree
from build_documentation import source_files as documentation_files, copy_documentation
from installers.desktop.version import VERSION
from installers.datasets.gui.catalog import DATASETS
from installers.datasets.gui.discovery import native_target
from installers.datasets.gui.planning import file_hash, installer_artifact

APP_NAME = "MeshCore-EMS-Dataset-Manager"
SERVICE_APP_NAME = "MeshCore-EMS-Service-Setup"


def windows_version_resource(app_name):
    """Describe the native PE version resource using the shared release identity."""
    numeric = tuple(map(int, VERSION.removeprefix("v").split("-", 1)[0].split("."))) + (0,)
    return f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={numeric!r}, prodvers={numeric!r}, mask=0x3f,
                   flags=0x2, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Usrnmna'),
    StringStruct('FileDescription', {app_name!r}),
    StringStruct('FileVersion', {VERSION!r}),
    StringStruct('ProductName', 'MeshCore EMS Services'),
    StringStruct('ProductVersion', {VERSION!r})])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
'''


def verify_gui_dependencies():
    """Reject a build environment that silently retains incompatible Qt wheels."""
    expected = {}
    requirements = ROOT / "installers/datasets/gui/requirements.txt"
    for line in requirements.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            package, release = line.split("==", 1)
            expected[package] = release.strip()
    actual = {package: version(package) for package in expected}
    if expected != actual:
        raise ValueError("GUI dependency versions differ from requirements.txt; prepare the pinned native build environment")
    return actual


def source_files():
    """Enumerate both native workers and GUI inputs for build freshness checks."""
    files = {ROOT / "LICENSE", ROOT / "installers/datasets/manage.py", ROOT / "installers/configure.py",
             ROOT / "tools/build_dataset_gui.py", ROOT / "tools/build_arm64_image_plugins.py",
             ROOT / "tools/distribution_policy.py", ROOT / "tools/build_documentation.py", ROOT / "docs/DATASET_GUI.md",
             ROOT / "docs/DATA_PACKAGES.md", ROOT / "docs/UNIFIED_INSTALLER.md"}
    files.update(ROOT / package / name for package in ("meshcore_mqtt_service", "meshcore_mqtt_service_windows")
                 for name in ("config.json", "channels.py", "channel_history.py"))
    for directory in (ROOT / "installers/datasets/gui", ROOT / "installers/desktop"):
        files.update(path for path in directory.iterdir() if path.suffix in {".py", ".ui", ".txt"})
    guide = ROOT / "docs/DESKTOP_INSTALLATION.md"
    if guide.is_file():
        files.add(guide)
    files.update(documentation_files(ROOT))
    return validate_paths(files, ROOT)


def source_hashes():
    """Record all compiled worker inputs, not only the visible Qt form."""
    return {path.relative_to(ROOT).as_posix(): file_hash(path) for path in source_files()}


def build_environment():
    """Avoid unrelated application DLLs on PATH entering a Windows GUI bundle.

    Qt resolves its own libraries through PyInstaller's Qt hooks. Windows system
    dependencies must come from Windows, not e.g. a third-party ICU distribution.
    The GUI-only build needs no external compiler or dataset build tool on PATH.
    """
    environment = dict(os.environ)
    if sys.platform == "win32":
        windows = Path(environment.get("SystemRoot", r"C:\Windows"))
        environment["PATH"] = os.pathsep.join(map(str, (Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows)))
    return environment


def copy_installers(source, destination, target):
    """Copy an existing checked artifact per collection for this target only."""
    artifacts = [installer_artifact(source, name, target) for name in DATASETS]
    destination.mkdir(parents=True, exist_ok=False)
    entries = []
    for path, digest in artifacts:
        copied = destination / path.name
        shutil.copy2(path, copied)
        if file_hash(copied) != digest:
            raise ValueError("Artifact changed while copying: " + path.name)
        entries.append(f"{digest}  {path.name}\n")
    (destination / "SHA256SUMS.txt").write_text("".join(sorted(entries)), encoding="utf-8")


def build(output, installer_folder=None, *, service=False):
    """Build a native onedir executable with its editable form and source snapshot."""
    target = native_target()
    verify_gui_dependencies()
    app_name = SERVICE_APP_NAME if service else APP_NAME
    if output.exists():
        raise ValueError("Choose a new --output directory; existing distributions are not overwritten")
    if installer_folder:
        # Validate all inputs before spending time on executable packaging.
        for name in DATASETS:
            installer_artifact(installer_folder, name, target)
    work = ROOT / ".build" / ("dataset-gui-" + uuid.uuid4().hex[:12])
    work.mkdir(parents=True)
    gui = ROOT / "installers/datasets/gui"
    inputs = source_hashes()
    image_plugins = None
    if target == "raspberry-pi-arm64":
        from build_arm64_image_plugins import prepare
        recipe_key = file_hash(ROOT / "tools/build_arm64_image_plugins.py")[:12]
        image_plugins = prepare(ROOT / ".build" / ("arm64-image-plugins-" + recipe_key))
    command = [sys.executable, "-m", "PyInstaller", "--onedir", "--windowed", "--noupx",
               "--name", app_name, "--distpath", str(output), "--workpath", str(work / "work"),
               "--specpath", str(work), "--paths", str(ROOT),
               "--add-data", str(gui / "main_window.ui") + ":installers/datasets/gui",
               "--add-data", str(ROOT / "meshcore_mqtt_service/config.json") + ":defaults/meshcore_mqtt_service",
               "--add-data", str(ROOT / "meshcore_mqtt_service_windows/config.json") + ":defaults/meshcore_mqtt_service_windows",
               "--exclude-module", "PyQt5", "--exclude-module", "PySide6",
               "--exclude-module", "adapters",
               "--hidden-import", "installers.desktop.authorization",
               "--hidden-import", "installers.desktop.service_backend",
               "--hidden-import", "installers.desktop.unified_backend",
               "--hidden-import", "installers.desktop.locking",
               "--hidden-import", "installers.desktop.history_widgets",
               "--hidden-import", "installers.desktop.history_window",
               "--hidden-import", "installers.desktop.history_process",
               "--hidden-import", "installers.desktop.history_backend",
               "--hidden-import", "installers.desktop.history_state",
               "--hidden-import", "installers.datasets.gui.privileges",
               str(ROOT / "installers/desktop/service_main.py" if service else gui / "main.py")]
    for package in ("meshcore_mqtt_service", "meshcore_mqtt_service_windows"):
        for name in ("channels.py", "channel_history.py"):
            command[-1:-1] = ["--add-data", str(ROOT / package / name) + ":defaults/" + package]
    if target == "windows-x64":
        version_file = work / "version-info.txt"
        version_file.write_text(windows_version_resource(app_name), encoding="utf-8")
        command[-1:-1] = ["--version-file", str(version_file)]
    subprocess.run(command, check=True, cwd=ROOT, env=build_environment())
    bundle = output / app_name
    image_provenance = None
    if image_plugins is not None:
        from build_arm64_image_plugins import install
        image_provenance = install(bundle, image_plugins)
    shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE")
    copy_documentation(ROOT, bundle / "documentation")
    (bundle / "README.md").write_text(
        "# MeshCore EMS " + VERSION + "\n\n"
        "See the [desktop installation and maintenance guide]"
        "(documentation/docs/DESKTOP_INSTALLATION.md).\n\n"
        "The documentation tree preserves relative links to operational guides and source examples.\n",
        encoding="utf-8")
    # Preserve inspectable Python and the maintained form beside the executable.
    source = bundle / "source"
    for path in source_files():
        if path.suffix == ".md":
            # Operational prose is provided once, with working links, above.
            continue
        destination = source / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    if installer_folder:
        copy_installers(installer_folder, bundle / "datasets", target)
    versions = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    if inputs != source_hashes():
        raise RuntimeError("GUI/worker source changed during compilation; rebuild before distributing")
    validate_tree(bundle)
    bundle_hashes = {path.relative_to(bundle).as_posix(): file_hash(path) for path in sorted(bundle.rglob("*"))
                     if path.is_file() and path.name != "BUILD.json"}
    (bundle / "BUILD.json").write_text(json.dumps({"version": VERSION, "capabilities": ["channel-history-v1"], "target": target, "app": "service" if service else "dataset", "python": sys.version,
        "dependencies": versions.splitlines(), "reused_installers": bool(installer_folder),
        "arm64_image_plugins": image_provenance,
        "build_libc": platform.libc_ver() if target != "windows-x64" else None,
        "ui_sha256": file_hash(gui / "main_window.ui"), "source_sha256": inputs,
        "bundle_sha256": bundle_hashes}, indent=2) + "\n", encoding="utf-8")
    if target == "windows-x64":
        archive = Path(shutil.make_archive(str(output / (app_name + "-" + target)), "zip", output, app_name))
    else:
        archive = output / (app_name + "-" + target + ".tar.gz")
        with tarfile.open(archive, "w:gz", dereference=False) as packed:
            packed.add(bundle, arcname=app_name)
    (output / "SHA256SUMS.txt").write_text(f"{file_hash(archive)}  {archive.name}\n", encoding="utf-8")
    print("Built GUI only: " + str(archive))
    return bundle


def build_service(output):
    """Build the independent service application with its own graphical runtime."""
    return build(output, service=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New output directory; default dist/dataset-manager/<native-target>")
    parser.add_argument("--installers", type=Path, help="Optionally bundle the eight existing installers for this target")
    parser.add_argument("--service", action="store_true", help="Build the separate service setup/maintenance window")
    args = parser.parse_args()
    folder = "service-setup" if args.service else "dataset-manager"
    build((args.output or ROOT / "dist" / folder / native_target()).resolve(), args.installers, service=args.service)


if __name__ == "__main__":
    main()
