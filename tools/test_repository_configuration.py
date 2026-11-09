"""Protect publication and checkout rules without changing the working index."""

import os
import json
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
            ".reference-only/reference-catalog.json",
            "local-data/.reference-only/rollback/catalog.json",
            ".local-data-staging/B03/evidence.xml",
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
            "RELEASE_v0.9.9-beta.md", "docs/COMMAND_IMPLEMENTATION.md",
            "meshcore_mqtt_service/scripts/reference_catalog.py",
            "meshcore_mqtt_service_windows/tests/test_reference_catalog.py",
            "data/flood_impacts/test_archive_publication.py",
            ".github/workflows/ci.yml", ".github/dependabot.yml",
            "installers/desktop/unified_backend.py", "installers/desktop/maintenance_lock.ps1",
            "installers/datasets/gui/main_window.ui", "installers/datasets/gui/requirements-build.txt",
            "docs/DESKTOP_INSTALLATION.md", "tests/fixtures/authorization.log",
            "environment.json.example", "environment.json.template", "data/usgs_water/local_review_rules.json",
        }
        self.assertEqual(ignored_paths(ROOT, sorted(excluded | retained)), excluded)

    def test_standalone_ignore_rules_preserve_sources_and_reference_inputs(self):
        excluded = {".env", "environment.json", "environment.json.old", "dist/installer.exe",
                    ".build/result.json", "logs/service.log", "catalog.sqlite3-wal", ".datasets.lock",
                    ".reference-only/reference-catalog.json", "data/.reference-only/tile.xml",
                    ".local-data-staging/B03/receipt.json", ".gui-manager.lock",
                    "satellite-settings.json.tmp"}
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
            "local-data/.reference-only/tile.xml": ("unset", "unspecified"),
            "local-data/.reference-only/README.md": ("unset", "lf"),
            ".local-data-staging/B03/metadata.json": ("unset", "lf"),
            ".local-data-staging/B03/check.py": ("unset", "lf"),
        }
        result = subprocess.run(["git", "check-attr", "-z", "--stdin", "text", "eol"], cwd=ROOT,
                                input="\0".join(expected).encode() + b"\0", capture_output=True, check=True)
        fields = result.stdout.decode().rstrip("\0").split("\0")
        actual = {(fields[index], fields[index + 1]): fields[index + 2] for index in range(0, len(fields), 3)}
        for path, (text, eol) in expected.items():
            with self.subTest(path=path):
                self.assertEqual(actual[path, "text"], text)
                self.assertEqual(actual[path, "eol"], eol)

    def test_paired_command_sources_are_included_and_identical(self):
        """Check distributable helpers and tests without building archives or importing commands."""
        from tools.package_services import PACKAGES, package_files

        inventories = [{p.relative_to(ROOT / name).as_posix() for p in package_files(name)}
                       for name in PACKAGES]
        shared = {name for inventory in inventories for name in inventory
                  if name.startswith(("scripts/", "tests/"))}
        for name in shared:
            for inventory in inventories:
                self.assertIn(name, inventory)
            if name not in {"tests/test_responder.py", "tests/test_mqtt_integration.py"}:
                self.assertEqual((ROOT / PACKAGES[0] / name).read_bytes(),
                                 (ROOT / PACKAGES[1] / name).read_bytes(), name)
        for package, inventory in zip(PACKAGES, inventories):
            commands = json.loads((ROOT / package / "config.json").read_bytes())["responder"]["commands"]
            self.assertEqual(len({spec["script"] for spec in commands.values()}), len(commands))
            self.assertTrue({"!floodwarn", "!floodstatus", "!floodalarm"} <= commands.keys())
            self.assertFalse({"!floodref", "!rivertrend"} & commands.keys())
            for spec in commands.values():
                self.assertIn(spec["script"], inventory)


if __name__ == "__main__":
    unittest.main()
