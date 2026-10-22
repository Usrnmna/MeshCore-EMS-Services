"""Offline installed-generation discovery, removal, path isolation, and consumer regressions."""

import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from scripts import dataset_paths, gis_data, landslide_data, water_local, water_settings, wildfire_refresh


class DatasetPathTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / "runtime" / ("dataset-test-" + uuid4().hex)
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root)
        environment = patch.dict(os.environ, {"MESHCORE_DATA_DIR": str(self.root)})
        environment.start()
        self.addCleanup(environment.stop)
        self.registry = {"schema": 1, "datasets": {}}
        self.fallback = self.root / "legacy"

    def publish(self, dataset, generation="first"):
        directory = self.root / ".datasets" / dataset / generation / "content"
        directory.mkdir(parents=True, exist_ok=True)
        self.registry["datasets"][dataset] = {
            "active": {"path": directory.relative_to(self.root).as_posix(), "receipt": "receipt.json"},
            "previous": None,
        }
        self.write_registry()
        return directory

    def write_registry(self):
        (self.root / "datasets.json").write_text(json.dumps(self.registry), encoding="utf-8")

    def test_absent_entry_retains_legacy_but_explicit_removal_does_not(self):
        self.assertEqual(dataset_paths.resolve("ebmud", self.fallback), self.fallback)
        self.registry["datasets"]["ebmud"] = {"active": None}
        self.write_registry()
        with self.assertRaisesRegex(FileNotFoundError, "not installed"):
            dataset_paths.resolve("ebmud", self.fallback)

    def test_generation_switch_changes_future_reads_without_changing_pinned_path(self):
        first = self.publish("ebmud")
        pinned = dataset_paths.resolve("ebmud", self.fallback)
        second = self.publish("ebmud", "second")
        self.assertEqual(pinned, first)
        self.assertEqual(dataset_paths.resolve("ebmud", self.fallback), second)
        self.assertTrue(first.is_dir())

    def test_custom_external_path_remains_authoritative(self):
        self.publish("ebmud")
        custom = self.root.parent / "operator-owned"
        self.assertEqual(dataset_paths.resolve("ebmud", self.fallback, configured=custom), custom)

    def test_invalid_registry_and_missing_generation_do_not_fallback(self):
        directory = self.publish("ebmud")
        directory.rmdir()
        with self.assertRaises(FileNotFoundError):
            dataset_paths.resolve("ebmud", self.fallback)
        (self.root / "datasets.json").write_text("broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            dataset_paths.resolve("ebmud", self.fallback)

    def test_registry_paths_reject_traversal_absolute_and_symlink_escape(self):
        for relative in ("../escape", "/escape", "C:/escape", "C:escape", "..\\escape", "\\\\host\\share"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                dataset_paths.checked_path(self.root, relative)
        # Resolve is checked separately so this assertion does not require symlink privileges.
        with patch.object(Path, "resolve", autospec=True,
                          side_effect=lambda value: self.root if value == self.root else self.root.parent):
            with self.assertRaises(ValueError):
                dataset_paths.checked_path(self.root, ".datasets/ebmud/generation/content")

    def test_gis_default_uses_managed_generation(self):
        directory = self.publish("ebmud")
        self.assertEqual(gis_data.load_settings()["data_directory"], directory)

    def test_landslide_cache_follows_generation(self):
        first = self.publish("landslide")
        with patch.object(landslide_data, "_reference", side_effect=lambda path: path) as reader:
            self.assertEqual(landslide_data.reference(), first)
            second = self.publish("landslide", "second")
            self.assertEqual(landslide_data.reference(), second)
            self.assertEqual(reader.call_count, 2)

    def test_wildfire_existing_runtime_cache_does_not_require_reference_package(self):
        self.registry["datasets"]["wildfire"] = {"active": None}
        self.write_registry()
        store = Mock()
        store.status.return_value = {"fetched": 100}
        wildfire_refresh.seed(store)
        store.replace.assert_not_called()

    def test_water_prefers_generation_index_without_writing_it(self):
        directory = self.publish("usgs_water")
        index = directory / "water_index.sqlite3"
        with closing(sqlite3.connect(index)) as database:
            database.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT)")
            database.execute("INSERT INTO metadata VALUES('schema', '999')")
            database.commit()
        before = index.read_bytes()
        with patch.object(water_local, "readonly", wraps=water_local.readonly) as reader:
            with self.assertRaisesRegex(ValueError, "Unsupported water index"):
                water_local.context(38, -121, water_settings.validate({}), 100)
            reader.assert_called_once_with(index)
        self.assertEqual(index.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
