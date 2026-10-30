"""Protect publication and checkout rules without changing the working index."""

import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
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
            "docs/superpowers/plans/release.md",
            "docs/superpowers/specs/channel-history.md",
            "runtime/channel_history/channel_history.sqlite3",
            "meshcore_mqtt_service/runtime/channel_history/status.json",
            "meshcore_mqtt_service_windows/runtime/channel_history/channel_history.sqlite3-wal",
            "meshcore-history-example/request.json",
            "meshcore-desktop-example/result.json",
            ".cache/release-v098/ci-config-audit.md",
        }
        retained = {
            ".github/workflows/ci.yml", ".github/dependabot.yml", ".github/requirements-ci.txt",
            "installers/desktop/unified_backend.py", "installers/desktop/maintenance_lock.ps1",
            "installers/datasets/gui/main_window.ui", "installers/datasets/gui/requirements-build.txt",
            "docs/DESKTOP_INSTALLATION.md", "tests/fixtures/authorization.log",
            "environment.json.example", "environment.json.template", "data/usgs_water/local_review_rules.json",
            "docs/CHANNEL_HISTORY_VERIFICATION.md", "meshcore_mqtt_service/CHANNEL_HISTORY.md",
            "installers/desktop/history_backend.py", "tools/test_history_process.py",
            "tests/fixtures/meshcore-history-example/request.json",
            "tests/fixtures/reference.sqlite3", "data/satellites/satellites.sqlite3",
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
            "tests/fixtures/reference.sqlite3": ("unset", "unspecified"),
            "data/reference/receipt.zip": ("unset", "unspecified"),
        }
        result = subprocess.run(["git", "check-attr", "-z", "--stdin", "text", "eol"], cwd=ROOT,
                                input="\0".join(expected).encode() + b"\0", capture_output=True, check=True)
        fields = result.stdout.decode().rstrip("\0").split("\0")
        actual = {(fields[index], fields[index + 1]): fields[index + 2] for index in range(0, len(fields), 3)}
        for path, (text, eol) in expected.items():
            with self.subTest(path=path):
                self.assertEqual(actual[path, "text"], text)
                self.assertEqual(actual[path, "eol"], eol)

    def test_local_planning_documents_are_not_tracked(self):
        """Keep planning files local without deleting or opening their contents."""
        result = subprocess.run(
            ["git", "ls-files", "--", "docs/superpowers"], cwd=ROOT,
            capture_output=True, check=True,
        )
        self.assertEqual(result.stdout, b"", "Local planning files must be removed from the index only")

    def test_git_archives_exclude_even_force_added_planning_documents(self):
        """Exercise export-ignore in a disposable tree without creating a commit."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            subprocess.run(["git", "init", "--quiet", str(directory)], check=True, capture_output=True)
            shutil.copy2(ROOT / ".gitattributes", directory / ".gitattributes")
            for relative in ("docs/superpowers/plans/private.md", "docs/superpowers/specs/private.md",
                             "docs/CHANNEL_HISTORY_VERIFICATION.md", "README.md"):
                path = directory / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Fixture documentation.\n", encoding="utf-8")
            subprocess.run(["git", "add", "--force", "."], cwd=directory, check=True, capture_output=True)
            tree = subprocess.check_output(["git", "write-tree"], cwd=directory).decode().strip()
            data = subprocess.check_output(["git", "archive", "--format=tar", tree], cwd=directory)
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                names = set(archive.getnames())
            self.assertFalse(any(name == "docs/superpowers" or name.startswith("docs/superpowers/")
                                 for name in names), names)
            self.assertIn("docs/CHANNEL_HISTORY_VERIFICATION.md", names)
            self.assertIn("README.md", names)
            self.assertTrue((directory / "docs/superpowers/plans/private.md").is_file())


if __name__ == "__main__":
    unittest.main()
