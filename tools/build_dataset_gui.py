"""Package only the dataset GUI; optionally copy already-built native installers.

Run on each target OS/architecture. No dataset builder, installer, uninstaller,
provider acquisition or service operation is invoked by this script.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installers.datasets.gui.catalog import DATASETS
from installers.datasets.gui.discovery import native_target
from installers.datasets.gui.planning import file_hash, installer_artifact

APP_NAME = "MeshCore-EMS-Dataset-Manager"


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


def build(output, installer_folder=None):
    """Build a native onedir executable with its editable form and source snapshot."""
    target = native_target()
    if output.exists():
        raise ValueError("Choose a new --output directory; existing distributions are not overwritten")
    if installer_folder:
        # Validate all inputs before spending time on executable packaging.
        for name in DATASETS:
            installer_artifact(installer_folder, name, target)
    work = ROOT / ".build" / ("dataset-gui-" + uuid.uuid4().hex[:12])
    work.mkdir(parents=True)
    gui = ROOT / "installers/datasets/gui"
    command = [sys.executable, "-m", "PyInstaller", "--onedir", "--windowed", "--noupx",
               "--name", APP_NAME, "--distpath", str(output), "--workpath", str(work / "work"),
               "--specpath", str(work), "--paths", str(ROOT),
               "--add-data", str(gui / "main_window.ui") + ":installers/datasets/gui",
               "--exclude-module", "PyQt5", "--exclude-module", "PySide6",
               "--exclude-module", "adapters",
               str(gui / "main.py")]
    subprocess.run(command, check=True, cwd=ROOT, env=build_environment())
    bundle = output / APP_NAME
    shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE")
    shutil.copy2(ROOT / "docs/DATASET_GUI.md", bundle / "README.md")
    # Preserve inspectable Python and the maintained form beside the executable.
    source = bundle / "source"
    for path in [ROOT / "LICENSE", ROOT / "installers/datasets/manage.py", *gui.glob("*.py"), *gui.glob("*.ui"), *gui.glob("*.txt"),
                 ROOT / "tools/build_dataset_gui.py", ROOT / "docs/DATASET_GUI.md", ROOT / "docs/DATA_PACKAGES.md"]:
        destination = source / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    if installer_folder:
        copy_installers(installer_folder, bundle / "datasets", target)
    versions = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    (bundle / "BUILD.json").write_text(json.dumps({"target": target, "python": sys.version,
        "dependencies": versions.splitlines(), "reused_installers": bool(installer_folder),
        "ui_sha256": file_hash(gui / "main_window.ui")}, indent=2) + "\n", encoding="utf-8")
    archive = Path(shutil.make_archive(str(output / (APP_NAME + "-" + target)), "zip", output, APP_NAME))
    (output / "SHA256SUMS.txt").write_text(f"{file_hash(archive)}  {archive.name}\n", encoding="utf-8")
    print("Built GUI only: " + str(archive))
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New output directory; default dist/dataset-manager/<native-target>")
    parser.add_argument("--installers", type=Path, help="Optionally bundle the eight existing installers for this target")
    args = parser.parse_args()
    build((args.output or ROOT / "dist/dataset-manager" / native_target()).resolve(), args.installers)


if __name__ == "__main__":
    main()
