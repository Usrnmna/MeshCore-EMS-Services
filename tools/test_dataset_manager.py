"""Exercise data-loss boundaries with real directories and injected source failures."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dataset_manager", ROOT / "installers/datasets/manage.py")
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class DatasetManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "state"
        self.payload = Path(self.temporary.name) / "payload"
        self.payload.mkdir()
        self.value = "verified first version"

    def acquire(self, dataset, directory, payload, dependencies, **kwargs):
        (directory / "data.txt").write_text(self.value)

    def validate(self, dataset, directory, payload, dependencies):
        if not (directory / "data.txt").read_text():
            raise ValueError("Empty provider response")

    def install(self, dataset="ebmud", **kwargs):
        return manager.install(self.root, dataset, self.payload,
                               acquire=kwargs.pop("acquire", self.acquire),
                               validate=kwargs.pop("validate", self.validate), **kwargs)

    def current(self, dataset="ebmud"):
        return manager.selected(self.root, manager.registry(self.root), dataset)

    def contents(self, record, dataset="ebmud"):
        return (manager.record_path(self.root, dataset, record) / "data.txt").read_text()

    def test_all_eight_collections_preserve_directory_and_selection_on_outage(self):
        for dataset in manager.DATASETS:
            with self.subTest(dataset=dataset):
                for dependency in manager.DATASETS[dataset]:
                    if dependency not in manager.registry(self.root)["datasets"]:
                        self.install(dependency)
                original = self.install(dataset)
                before = (self.root / "datasets.json").read_bytes()
                def unavailable(*args, **kwargs):
                    raise TimeoutError("source server unavailable")
                with self.assertRaises(TimeoutError):
                    self.install(dataset, update=True, acquire=unavailable)
                self.assertEqual((self.root / "datasets.json").read_bytes(), before)
                self.assertEqual(self.contents(original, dataset), self.value)
                self.assertEqual(manager.status(self.root, dataset)["last_attempt"]["state"], "failed")

    def test_empty_partial_corrupt_and_disk_exhausted_updates_preserve_bytes(self):
        original = self.install()
        before = (self.root / "datasets.json").read_bytes()
        for error in (ValueError("truncated"), OSError("disk full"), KeyboardInterrupt()):
            def fail(dataset, directory, *args, **kwargs):
                (directory / "data.txt").write_text("partial")
                raise error
            with self.assertRaises(type(error)):
                self.install(update=True, acquire=fail)
            self.assertEqual((self.root / "datasets.json").read_bytes(), before)
            self.assertEqual(self.contents(original), self.value)
        self.value = ""
        with self.assertRaisesRegex(ValueError, "Empty"):
            self.install(update=True)
        self.assertEqual((self.root / "datasets.json").read_bytes(), before)

    def test_failed_atomic_activation_keeps_registry_and_old_files(self):
        original = self.install()
        before = (self.root / "datasets.json").read_bytes()
        replace = os.replace
        def fail_registry(source, target):
            if Path(target).name == "datasets.json":
                raise PermissionError("registry locked")
            return replace(source, target)
        with patch.object(manager.os, "replace", side_effect=fail_registry):
            with self.assertRaises(PermissionError):
                self.install(update=True)
        self.assertEqual((self.root / "datasets.json").read_bytes(), before)
        self.assertEqual(self.contents(original), self.value)

    def test_success_and_rollback_retain_both_complete_generations(self):
        first = self.install()
        self.value = "verified second version"
        second = self.install(update=True)
        self.assertNotEqual(first, second)
        self.assertEqual(self.contents(first), "verified first version")
        self.assertEqual(self.contents(second), self.value)
        manager.rollback(self.root, "ebmud")
        self.assertEqual(self.current(), first)
        manager.rollback(self.root, "ebmud")
        self.assertEqual(self.current(), second)

    def test_reinstall_never_downloads_or_downgrades_existing_data(self):
        first = self.install()
        def forbidden(*args, **kwargs):
            self.fail("Reinstall must not acquire a replacement")
        self.assertEqual(self.install(acquire=forbidden), first)

    def test_corrupt_current_reinstall_does_not_erase_or_repair_in_place(self):
        first = self.install()
        path = manager.record_path(self.root, "ebmud", first) / "data.txt"
        path.write_text("operator edit")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.install()
        self.assertEqual(path.read_text(), "operator edit")

    def test_failed_legacy_migration_preserves_entire_legacy_directory(self):
        legacy = self.root / "ebmud"
        legacy.mkdir(parents=True)
        (legacy / "data.txt").write_text("valid legacy")
        def fail(*args, **kwargs):
            raise ConnectionError("source down")
        with self.assertRaises(ConnectionError):
            self.install(update=True, acquire=fail)
        self.assertEqual((legacy / "data.txt").read_text(), "valid legacy")
        self.assertFalse((self.root / "datasets.json").exists())

    def test_resume_keeps_previous_active_until_completed(self):
        first = self.install()
        def fail(dataset, directory, *args, **kwargs):
            (directory / "download.part").write_text("retained partial bytes")
            raise TimeoutError()
        with self.assertRaises(TimeoutError):
            self.install(update=True, acquire=fail)
        candidate = manager.status(self.root, "ebmud")["last_attempt"]["candidate"]
        def resume(dataset, directory, *args, **kwargs):
            self.assertTrue(kwargs["resume"])
            self.assertEqual((directory / "download.part").read_text(), "retained partial bytes")
            self.assertEqual(self.current(), first)
            self.acquire(dataset, directory, *args, **kwargs)
        second = self.install(update=True, resume=candidate, acquire=resume)
        self.assertNotEqual(first, second)

    def test_prerequisite_updates_do_not_retarget_existing_dependent(self):
        basin = self.install("basin_plans")
        flood = self.install("flood_impacts")
        water = self.install("usgs_water")
        self.value = "new basin"
        self.install("basin_plans", update=True)
        manager.verify_record(self.root, "usgs_water", water)
        self.assertTrue(manager.record_path(self.root, "basin_plans", basin).exists())
        with self.assertRaisesRegex(ValueError, "Update flood_impacts"):
            self.install("usgs_water", update=True)
        self.assertEqual(self.current("flood_impacts"), flood)
        self.assertEqual(self.current("usgs_water"), water)

    def test_mutable_legacy_prerequisite_requires_import_before_pin(self):
        legacy = self.root / "basin_plans"
        legacy.mkdir(parents=True)
        (legacy / "data.txt").write_text("legacy basin")
        with self.assertRaisesRegex(ValueError, "validate and pin"):
            self.install("flood_impacts")
        self.assertFalse((self.root / "datasets.json").exists())

    def test_resume_rejects_changed_installer_payload(self):
        (self.payload / "PAYLOAD-MANIFEST.json").write_text('{"version":1}')
        self.install()
        def fail(*args, **kwargs):
            raise TimeoutError()
        with self.assertRaises(TimeoutError):
            self.install(update=True, acquire=fail)
        candidate = manager.status(self.root, "ebmud")["last_attempt"]["candidate"]
        (self.payload / "PAYLOAD-MANIFEST.json").write_text('{"version":2}')
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            self.install(update=True, resume=candidate)

    def test_uninstall_blocks_dependencies_and_preserves_unowned_data(self):
        basin = self.install("basin_plans")
        self.install("flood_impacts")
        with self.assertRaisesRegex(ValueError, "required"):
            manager.uninstall(self.root, "basin_plans", purge=True)
        self.assertTrue(manager.record_path(self.root, "basin_plans", basin).exists())
        manager.uninstall(self.root, "flood_impacts")
        manager.uninstall(self.root, "basin_plans")
        self.assertFalse(manager.record_path(self.root, "basin_plans", basin).exists())

    def test_modified_generation_and_legacy_preserved_unless_owned_purge(self):
        first = self.install()
        content = manager.record_path(self.root, "ebmud", first)
        (content / "custom.txt").write_text("operator data")
        legacy = self.root / "ebmud"
        legacy.mkdir()
        (legacy / "custom.txt").write_text("legacy")
        result = manager.uninstall(self.root, "ebmud")
        self.assertTrue(result["retained"])
        self.assertTrue(content.exists())
        with self.assertRaisesRegex(ValueError, "uninstalled"):
            self.current()
        manager.uninstall(self.root, "ebmud", purge=True)
        self.assertFalse(content.exists())
        self.assertEqual((legacy / "custom.txt").read_text(), "legacy")

    def test_owned_directory_with_extra_unowned_file_is_retained(self):
        record = self.install()
        parent = manager.record_path(self.root, "ebmud", record).parent
        (parent / "operator.txt").write_text("retain")
        manager.uninstall(self.root, "ebmud", purge=True)
        self.assertTrue(parent.exists())

    def test_concurrent_update_and_traversal_are_rejected(self):
        self.install()
        with manager.locked(self.root):
            with self.assertRaises(FileExistsError):
                self.install(update=True)
        for path in ("../outside", str(self.payload.resolve())):
            with self.assertRaises(ValueError):
                manager.contained(self.root, path)

    def test_status_write_failure_cannot_undo_successful_activation(self):
        write = manager.write_json
        def fail_status(path, value):
            if Path(path).parent.name == "status":
                raise OSError("status file unavailable")
            write(path, value)
        with patch.object(manager, "write_json", side_effect=fail_status):
            record = self.install()
        self.assertEqual(self.current(), record)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_restrictive_umask_does_not_publish_unreadable_data(self):
        previous = os.umask(0o077)
        try:
            record = self.install()
        finally:
            os.umask(previous)
        content = manager.record_path(self.root, "ebmud", record)
        self.assertEqual(content.stat().st_mode & 0o777, 0o755)
        self.assertEqual((content / "data.txt").stat().st_mode & 0o777, 0o644)
        self.assertEqual((self.root / "datasets.json").stat().st_mode & 0o777, 0o644)

    def test_candidate_permission_failure_preserves_previous_selection(self):
        record = self.install()
        with patch.object(manager, "readable_candidate", side_effect=PermissionError("chmod failed")):
            with self.assertRaises(PermissionError):
                self.install(update=True)
        self.assertEqual(self.current(), record)


if __name__ == "__main__":
    unittest.main()
