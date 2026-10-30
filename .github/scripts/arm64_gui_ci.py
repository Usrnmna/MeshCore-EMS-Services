"""Prepare ARM64 source plugins and verify frozen applications on Debian 12.

Only dependency installation runs as container root. Repository programs run as
the host runner UID/GID, keeping source checks and generated files unprivileged.
The temporary container never publishes an image or installs a service.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[2]
IMAGE = "python:3.13-bookworm"
SOURCE_PLUGINS = Path(".build/ci-arm64-image-search")
BOOTSTRAP = r"""set -eu
apt-get update
apt-get install --yes --no-install-recommends \
  build-essential cmake ninja-build pkg-config p7zip-full patchelf util-linux binutils \
  libwebp-dev=1.2.4-0.2+deb12u1 libtiff-dev=4.5.0-6+deb12u4 \
  libegl1 libopengl0 libgl-dev libegl-dev libxkbcommon0 libdbus-1-3 libfontconfig1
python -m pip install --no-cache-dir -r installers/datasets/gui/requirements-build.txt
python -m pip check
exec setpriv --reuid="$1" --regid="$2" --clear-groups \
  python .github/scripts/arm64_gui_ci.py "$3" --inside
"""


def run(arguments):
    """Propagate command failures without substituting source smoke for frozen."""
    subprocess.run([str(value) for value in arguments], cwd=ROOT, check=True)


def container_command(mode, uid, gid):
    """Build a fixed container invocation without forwarding host Qt overrides."""
    if mode not in {"prepare", "frozen"} or uid <= 0 or gid < 0:
        raise ValueError("Expected a supported mode and an unprivileged runner UID/GID")
    return ["docker", "run", "--rm", "--platform", "linux/arm64",
            "--mount", "type=bind,source=" + str(ROOT) + ",target=/workspace",
            "--workdir", "/workspace", "--env", "QT_QPA_PLATFORM=offscreen",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "HOME=/tmp",
            "--env", "PIP_DISABLE_PIP_VERSION_CHECK=1",
            IMAGE, "sh", "-c", BOOTSTRAP, "arm64-gui-ci", str(uid), str(gid), mode]


def prepare_source_plugins():
    """Reuse the builder's verified recipe cache and expose only two plugins."""
    sys.path.insert(0, str(ROOT / "tools"))
    from build_arm64_image_plugins import PLUGINS, file_hash, prepare

    recipe_key = file_hash(ROOT / "tools/build_arm64_image_plugins.py")[:12]
    prepared = prepare(ROOT / ".build" / ("arm64-image-plugins-" + recipe_key))
    destination = ROOT / SOURCE_PLUGINS / "imageformats"
    destination.mkdir(parents=True, exist_ok=True)
    for name in PLUGINS:
        shutil.copy2(prepared / name, destination / name)


def verify_service_payloads(directory, version):
    """Require both service payloads and validate their bytes and capabilities."""
    artifacts = list(directory.glob("*.run"))
    assert len(artifacts) == 2, "Both Linux service payloads must be built"
    for artifact in artifacts:
        header, payload = artifact.read_bytes().split(b"\n__MESHCORE_PAYLOAD__\n", 1)
        expected = re.search(rb'expected_sha="([0-9a-f]{64})"', header)[1].decode()
        assert hashlib.sha256(payload).hexdigest() == expected, artifact.name
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            manifest = json.load(archive.extractfile("PAYLOAD-MANIFEST.json"))
            assert manifest["version"] == version, artifact.name
            assert set(archive.getnames()) == set(manifest["files"]) | {"PAYLOAD-MANIFEST.json"}
            for name, digest in manifest["files"].items():
                assert hashlib.sha256(archive.extractfile(name).read()).hexdigest() == digest, name
            capabilities = json.load(archive.extractfile("DESKTOP-CAPABILITIES.json"))
            assert "channel-history-v1" in capabilities["capabilities"]


def verify_frozen():
    """Build both native executables and exercise their bundled history/images."""
    sys.path.insert(0, str(ROOT))
    from installers.desktop.version import VERSION

    # Source plugin discovery must never supply dependencies to frozen evidence.
    for name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "LD_LIBRARY_PATH", "LD_PRELOAD"):
        os.environ.pop(name, None)
    evidence = ROOT / ".build/ci-frozen"
    evidence.mkdir(parents=True)
    for kind, name in (("dataset", "MeshCore-EMS-Dataset-Manager"),
                       ("service", "MeshCore-EMS-Service-Setup")):
        output = evidence / kind
        build = [sys.executable, "tools/build_dataset_gui.py", "--output", output]
        if kind == "service":
            build.append("--service")
        run(build)
        smoke = [sys.executable, "tools/test_packaged_history.py", "--application", output / name / name,
                 "--expected-version", VERSION, "--output", evidence / (kind + "-history.json")]
        if kind == "dataset":
            smoke.append("--include-datasets-only")
        run(smoke)
    run([sys.executable, "tools/build_installers.py", "--linux-only",
         "--output", evidence / "service-installers"])
    verify_service_payloads(evidence / "service-installers", VERSION)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "frozen"))
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if platform.system() != "Linux" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise ValueError("This CI helper requires an ARM64 Linux runner")
    if arguments.inside:
        if os.getuid() == 0:
            raise ValueError("Repository verification must run as the unprivileged runner")
        if arguments.mode == "prepare":
            prepare_source_plugins()
        else:
            verify_frozen()
    else:
        run(container_command(arguments.mode, os.getuid(), os.getgid()))
        if arguments.mode == "prepare":
            with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as environment:
                environment.write("QT_PLUGIN_PATH=" + str(ROOT / SOURCE_PLUGINS) + "\n")


if __name__ == "__main__":
    main()
