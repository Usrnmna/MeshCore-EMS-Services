"""Installed satellite generation discovery and immutable access regressions."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import satellite_db as app
from test_satellite_db import TestDirectory


class ManagedDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TestDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content = self.root / ".datasets" / "satellites" / "first" / "content"
        self.content.mkdir(parents=True)
        registry = {"schema": 1, "datasets": {"satellites": {"active": {
            "path": self.content.relative_to(self.root).as_posix(), "receipt": "receipt.json"}}}}
        (self.root / "datasets.json").write_text(json.dumps(registry), encoding="utf-8")
        environment = patch.dict(os.environ, {"MESHCORE_DATA_DIR": str(self.root)})
        environment.start()
        self.addCleanup(environment.stop)

    def test_default_paths_follow_generation_and_mutations_are_rejected(self):
        settings = app.settings_from(app.HERE / "settings.json")
        self.assertEqual(settings["database"], self.content / "satellites.sqlite3")
        self.assertTrue(settings["managed_snapshot"])
        for command in ("refresh", "export", "import-observations"):
            arguments = [command] + (["missing.json"] if command == "import-observations" else [])
            with self.subTest(command=command), redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(app.main(arguments), 1)
                self.assertIn("immutable", errors.getvalue())
        self.assertEqual(list(self.content.iterdir()), [])

    def test_managed_summary_reads_dated_coverage_without_writing(self):
        database = sqlite3.connect(self.content / "satellites.sqlite3")
        database.close()
        coverage = self.content / "coverage.json"
        coverage.write_text('{"current_status_evaluated_at":"2020-01-01T00:00:00Z"}', encoding="utf-8")
        before = {p.name: p.read_bytes() for p in self.content.iterdir()}
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(app.main(["summary"]), 0)
        self.assertIn("2020-01-01", output.getvalue())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.content.iterdir()})

    def test_custom_external_settings_remain_authoritative(self):
        values = app.read_json(app.HERE / "settings.json")
        external = self.root.parent / "custom-satellite-catalog"
        values.update(database=str(external / "catalog.sqlite3"),
                      cache_directory=str(external / "raw"), export_directory=str(external))
        settings_file = self.root / "custom.json"
        settings_file.write_text(json.dumps(values), encoding="utf-8")
        settings = app.settings_from(settings_file)
        self.assertEqual(settings["database"], external / "catalog.sqlite3")
        self.assertFalse(settings["managed_snapshot"])

    def test_installed_shortcut_uses_service_shared_root_without_pinning_generation(self):
        directory = self.root / "installed-settings"
        directory.mkdir()
        default_root = self.root / "old-default-data"
        values = app.read_json(app.HERE / "settings.json")
        values.update(database=str(default_root / "satellites/satellites.sqlite3"),
                      cache_directory=str(default_root / "satellites/raw"),
                      export_directory=str(default_root / "satellites"))
        settings_file = directory / "satellite-settings.json"
        settings_file.write_text(json.dumps(values), encoding="utf-8")
        (directory / "config.json").write_text(json.dumps({"dataset_root": str(self.root)}), encoding="utf-8")
        before = settings_file.read_bytes()
        with patch.object(app.dataset_paths, "data_root", return_value=default_root):
            settings = app.settings_from(settings_file)
        self.assertEqual(settings["database"], self.content / "satellites.sqlite3")
        self.assertTrue(settings["managed_snapshot"])
        self.assertEqual(settings_file.read_bytes(), before)

    def test_shared_root_does_not_override_an_explicit_external_catalog(self):
        directory = self.root / "installed-settings"
        directory.mkdir()
        external = self.root / "external-catalog"
        values = app.read_json(app.HERE / "settings.json")
        values.update(database=str(external / "operator.sqlite3"), cache_directory=str(external / "raw"), export_directory=str(external))
        settings_file = directory / "satellite-settings.json"
        settings_file.write_text(json.dumps(values), encoding="utf-8")
        (directory / "config.json").write_text(json.dumps({"dataset_root": str(self.root)}), encoding="utf-8")
        self.assertEqual(app.settings_from(settings_file)["database"], external / "operator.sqlite3")

    def test_explicit_staging_settings_do_not_redirect_to_published_generation(self):
        candidate = self.root / ".datasets" / "satellites" / "pending" / "content"
        candidate.mkdir(parents=True)
        values = app.read_json(app.HERE / "settings.json")
        values.update(database=str(candidate / "satellites.sqlite3"),
                      cache_directory=str(candidate / "raw"), export_directory=str(candidate))
        settings_file = candidate / "settings.json"
        settings_file.write_text(json.dumps(values), encoding="utf-8")
        settings = app.settings_from(settings_file)
        self.assertEqual(settings["database"], candidate / "satellites.sqlite3")
        self.assertFalse(settings["managed_snapshot"])
        (candidate.parent / "receipt.json").write_text("{}", encoding="utf-8")
        self.assertTrue(app.settings_from(settings_file)["managed_snapshot"])


if __name__ == "__main__":
    unittest.main()
