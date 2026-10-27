"""Protect publication and checkout rules without changing the working index."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def ignored_paths(directory, paths):
    """Query virtual paths without creating credentials, datasets or build files."""
    result = subprocess.run(
        ["git", "-c", "core.excludesFile=" + os.devnull, "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=directory, input="\0".join(paths).encode() + b"\0", capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return set(result.stdout.decode().rstrip("\0").split("\0")) - {""}


class RepositoryConfigurationTests(unittest.TestCase):
    def test_desktop_outputs_are_private_and_sources_remain_publishable(self):
        excluded = {
            "dist/unified-desktop/evidence/smoke-windows.json",
            ".build/gui/work/Analysis-00.toc",
            "MeshCore-EMS-Dataset-Manager.spec",
            "MeshCore-EMS-Service-Setup.spec",
            ".venv-dataset-gui/pyvenv.cfg",
            "environment.json.backup",
            ".datasets/ebmud/generation/content/manifest.json",
            "datasets.json",
        }
        retained = {
            ".github/workflows/ci.yml", ".github/dependabot.yml",
            "installers/desktop/unified_backend.py", "installers/desktop/maintenance_lock.ps1",
            "installers/datasets/gui/main_window.ui", "installers/datasets/gui/requirements-build.txt",
            "docs/DESKTOP_INSTALLATION.md", "tests/fixtures/authorization.log",
            "environment.json.example", "environment.json.template", "data/usgs_water/local_review_rules.json",
        }
        self.assertEqual(ignored_paths(ROOT, sorted(excluded | retained)), excluded)

    def test_standalone_ignore_rules_preserve_sources_and_reference_inputs(self):
        excluded = {".env", "environment.json", "environment.json.old", "dist/installer.exe",
                    ".build/result.json", "logs/service.log", "catalog.sqlite3-wal", ".datasets.lock"}
        retained = {"scripts/status.py", "config.json", "settings.json", "reference.sqlite3",
                    "originals/receipt.zip", "tests/fixtures/provider.log", "README.md",
                    ".env.example", "environment.json.example", "environment.json.template"}
        for package in ("meshcore_mqtt_service", "meshcore_mqtt_service_windows", "satellite_database"):
            with self.subTest(package=package), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                subprocess.run(["git", "init", "--quiet", str(directory)], check=True, capture_output=True)
                shutil.copy2(ROOT / package / ".gitignore", directory / ".gitignore")
                self.assertEqual(ignored_paths(directory, sorted(excluded | retained)), excluded)

    def test_native_launchers_and_immutable_payloads_have_explicit_attributes(self):
        expected = {
            "installers/linux/install.sh": ("set", "lf"),
            "kit/1-Installation.desktop": ("set", "lf"),
            "kit/installer.sha256": ("set", "lf"),
            "installers/windows/install.ps1": ("set", "crlf"),
            "fixture/helper.psm1": ("set", "crlf"),
            "fixture/helper.psd1": ("set", "crlf"),
            ".github/workflows/ci.yml": ("set", "lf"),
            "kit/installer.run": ("unset", "unspecified"),
            "kit/runtime.so": ("unset", "unspecified"),
            "kit/contents.tar": ("unset", "unspecified"),
            "kit/application.ico": ("unset", "unspecified"),
            "data/usgs_water/inventory/generation/source.py": ("unset", "lf"),
            "data/usgs_water/README.md": ("set", "lf"),
        }
        result = subprocess.run(["git", "check-attr", "-z", "--stdin", "text", "eol"], cwd=ROOT,
                                input="\0".join(expected).encode() + b"\0", capture_output=True, check=True)
        fields = result.stdout.decode().rstrip("\0").split("\0")
        actual = {(fields[index], fields[index + 1]): fields[index + 2] for index in range(0, len(fields), 3)}
        for path, (text, eol) in expected.items():
            with self.subTest(path=path):
                self.assertEqual(actual[path, "text"], text)
                self.assertEqual(actual[path, "eol"], eol)


if __name__ == "__main__":
    unittest.main()
