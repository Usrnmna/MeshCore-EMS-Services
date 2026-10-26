"""Exercise data-loss boundaries with real directories and injected source failures."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dataset_manager", ROOT / "installers/datasets/manage.py")
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


def windows_short_path(path):
    """Return a real 8.3 alias, skipping only when no distinct alias is available."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_short_path = kernel.GetShortPathNameW
    get_short_path.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_short_path.restype = wintypes.DWORD
    required = get_short_path(str(path), None, 0)
    if not required:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(required)
    written = get_short_path(str(path), buffer, len(buffer))
    if not written:
        raise ctypes.WinError(ctypes.get_last_error())
    if written >= len(buffer):
        raise RuntimeError("Short-path buffer size changed during fixture creation")
    alias = Path(buffer.value)
    if alias == path:
        raise unittest.SkipTest("Temporary volume does not provide a distinct Windows 8.3 alias")
    return alias


class DatasetManagerTests(unittest.TestCase):
    path_forms = ("long", "noncanonical") + (("short",) if os.name == "nt" else ())

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
        return manager.install(kwargs.pop("root", self.root), dataset, self.payload,
                               acquire=kwargs.pop("acquire", self.acquire),
                               validate=kwargs.pop("validate", self.validate), **kwargs)

    def path_root(self, form, label="paths"):
        """Create an isolated long root and return an equivalent spelling for a subtest."""
        root = (Path(self.temporary.name) / label / form / "Dataset root with spaces").resolve()
        root.mkdir(parents=True)
        if form == "noncanonical":
            return root / ".." / root.name
        if form == "short":
            alias = windows_short_path(root)
            self.assertEqual(alias.resolve(), root)
            return alias
        return root

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
        replace = os.replace
        def fail_registry(source, target):
            if Path(target).name == "datasets.json":
                raise PermissionError("registry locked")
            return replace(source, target)
        for form in self.path_forms:
            with self.subTest(path_form=form):
                root = self.path_root(form)
                canonical = root.resolve()
                original = self.install(root=canonical)
                before = (canonical / "datasets.json").read_bytes()
                with patch.object(manager.os, "replace", side_effect=fail_registry):
                    with self.assertRaises(PermissionError):
                        self.install(root=root, update=True)
                self.assertEqual((canonical / "datasets.json").read_bytes(), before)
                self.assertEqual((canonical / original["path"] / "data.txt").read_text(), self.value)

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

    def test_root_alias_install_update_and_rollback_share_generations(self):
        for form in self.path_forms:
            with self.subTest(path_form=form):
                root = self.path_root(form)
                canonical = root.resolve()
                self.value = "verified first version"
                first = self.install(root=root)
                self.assertEqual((canonical / first["path"] / "data.txt").read_text(), self.value)
                for relative in first.values():
                    self.assertFalse(Path(relative).is_absolute())
                    self.assertNotIn("..", Path(relative).parts)
                self.value = "verified second version"
                second = self.install(root=canonical, update=True)
                self.assertNotEqual(first, second)
                manager.rollback(root, "ebmud")
                state = manager.registry(canonical)["datasets"]["ebmud"]
                self.assertEqual(state, {"active": first, "previous": second})
                manager.verify_record(root, "ebmud", first)
                manager.verify_record(root, "ebmud", second)
                self.assertEqual((canonical / first["path"] / "data.txt").read_text(), "verified first version")
                self.assertEqual((canonical / second["path"] / "data.txt").read_text(), self.value)

    def test_root_alias_legacy_lookup_and_import_preserve_original(self):
        for form in self.path_forms:
            with self.subTest(path_form=form):
                root = self.path_root(form)
                legacy = root.resolve() / "ebmud"
                legacy.mkdir()
                (legacy / "data.txt").write_bytes(b"original legacy bytes")
                record = {"path": "ebmud", "legacy": True}
                self.assertEqual(manager.record_path(root, "ebmud", record), legacy)
                installed = self.install(root=root)
                state = manager.registry(root)["datasets"]["ebmud"]
                self.assertEqual(state, {"active": installed, "previous": record})
                before = (root / "datasets.json").read_bytes()
                with self.assertRaisesRegex(ValueError, "Legacy"):
                    manager.rollback(root, "ebmud")
                self.assertEqual((root / "datasets.json").read_bytes(), before)
                self.assertEqual((legacy / "data.txt").read_bytes(), b"original legacy bytes")

    def test_root_alias_failed_update_retains_registry_and_partial_candidate(self):
        for form in self.path_forms:
            with self.subTest(path_form=form):
                root = self.path_root(form)
                canonical = root.resolve()
                first = self.install(root=canonical)
                before = (canonical / "datasets.json").read_bytes()
                def unavailable(dataset, directory, *args, **kwargs):
                    (directory / "download.part").write_bytes(b"incomplete download")
                    raise TimeoutError("fixture provider unavailable")
                with self.assertRaises(TimeoutError):
                    self.install(root=root, update=True, acquire=unavailable)
                self.assertEqual((canonical / "datasets.json").read_bytes(), before)
                self.assertEqual((canonical / first["path"] / "data.txt").read_text(), self.value)
                candidate = manager.status(root, "ebmud")["last_attempt"]["candidate"]
                partial = canonical / ".datasets/ebmud" / candidate / "content/download.part"
                self.assertEqual(partial.read_bytes(), b"incomplete download")

    def test_root_alias_uninstall_removes_only_receipt_owned_generations(self):
        for form in self.path_forms:
            with self.subTest(path_form=form):
                root = self.path_root(form)
                canonical = root.resolve()
                first = self.install(root=canonical)
                other = self.install("wildfire", root=canonical)
                content = canonical / first["path"]
                legacy = canonical / "ebmud"
                legacy.mkdir()
                (legacy / "operator.txt").write_bytes(b"legacy data")
                pending = canonical / ".datasets/ebmud" / ("f" * 32)
                pending.mkdir()
                (pending / "download.part").write_bytes(b"unpublished data")
                result = manager.uninstall(root, "ebmud")
                self.assertEqual(result["removed"], [str(content.parent)])
                self.assertEqual(result["retained"], [str(pending)])
                self.assertFalse(content.exists())
                self.assertEqual((legacy / "operator.txt").read_bytes(), b"legacy data")
                self.assertEqual((pending / "download.part").read_bytes(), b"unpublished data")
                self.assertEqual((canonical / other["path"] / "data.txt").read_text(), self.value)
                manager.verify_record(root, "wildfire", other)

    def test_root_alias_uninstall_retains_modified_and_unowned_files(self):
        for form in self.path_forms:
            with self.subTest(path_form=form):
                root = self.path_root(form)
                canonical = root.resolve()
                first = self.install(root=canonical)
                modified = canonical / first["path"]
                (modified / "data.txt").write_bytes(b"operator modification")
                second = self.install(root=canonical, update=True)
                unowned = (canonical / second["path"]).parent / "operator.txt"
                unowned.write_bytes(b"unowned file")
                result = manager.uninstall(root, "ebmud")
                self.assertEqual(result["removed"], [])
                self.assertEqual((modified / "data.txt").read_bytes(), b"operator modification")
                self.assertEqual(unowned.read_bytes(), b"unowned file")
                result = manager.uninstall(root, "ebmud", purge=True)
                self.assertEqual(result["removed"], [str(modified.parent)])
                self.assertFalse(modified.exists())
                self.assertEqual(unowned.read_bytes(), b"unowned file")
                self.assertEqual((canonical / second["path"] / "data.txt").read_text(), self.value)

    def test_root_alias_mismatched_receipts_block_purge_without_deselection(self):
        for form in self.path_forms:
            for field in ("dataset", "path"):
                with self.subTest(path_form=form, mismatched_field=field):
                    root = self.path_root(form, field)
                    canonical = root.resolve()
                    record = self.install(root=canonical)
                    receipt_path = canonical / record["receipt"]
                    receipt = manager.read_json(receipt_path)
                    receipt[field] = "wildfire" if field == "dataset" else ".datasets/ebmud/other/content"
                    manager.write_json(receipt_path, receipt)
                    before = (canonical / "datasets.json").read_bytes()
                    damaged = receipt_path.read_bytes()
                    with self.assertRaisesRegex(ValueError, "mismatched receipt"):
                        manager.uninstall(root, "ebmud", purge=True)
                    self.assertEqual((canonical / "datasets.json").read_bytes(), before)
                    self.assertEqual(receipt_path.read_bytes(), damaged)
                    self.assertEqual((canonical / record["path"] / "data.txt").read_text(), self.value)

    def test_root_alias_rejects_traversal_and_cross_collection_records(self):
        for form in self.path_forms:
            with self.subTest(path_form=form):
                root = self.path_root(form)
                canonical = root.resolve()
                record = self.install(root=canonical)
                before = (canonical / "datasets.json").read_bytes()
                for path in ("../outside", ".", str(canonical / record["path"]),
                             ".datasets/ebmud/../content"):
                    with self.subTest(relative=path):
                        with self.assertRaises(ValueError):
                            manager.contained(root, path)
                invalid = [dict(record, path=".datasets/ebmud/../content",
                                receipt=".datasets/ebmud/../receipt.json"),
                           dict(record, path=record["path"].replace("/ebmud/", "/wildfire/"),
                                receipt=record["receipt"].replace("/ebmud/", "/wildfire/")),
                           dict(record, receipt="../outside"),
                           dict(record, receipt=record["receipt"].replace("receipt.json", "other.json")),
                           {"path": "wildfire", "legacy": True}]
                for bad_record in invalid:
                    with self.subTest(record=bad_record):
                        with self.assertRaises(ValueError):
                            manager.record_path(root, "ebmud", bad_record)
                self.assertEqual((canonical / "datasets.json").read_bytes(), before)
                self.assertEqual((canonical / record["path"] / "data.txt").read_text(), self.value)

    def assert_link_blocks_purge(self, root, kind, target_inside):
        """Reject real links before deselection or deletion, preserving both targets."""
        canonical = root.resolve()
        record = self.install(root=canonical)
        content = canonical / record["path"]
        target = content / "operator-files" if target_inside else canonical.parent / "outside"
        target.mkdir()
        marker = target / "operator.txt"
        marker.write_bytes(b"unowned target bytes")
        link = content / "linked-directory"
        if kind == "junction":
            host = shutil.which("powershell.exe")
            if not host:
                self.skipTest("Windows PowerShell is required to create the junction fixture")
            escaped_link = str(link).replace("'", "''")
            escaped_target = str(target).replace("'", "''")
            command = f"New-Item -ItemType Junction -Path '{escaped_link}'"
            command += f" -Target '{escaped_target}' -ErrorAction Stop | Out-Null"
            result = subprocess.run([host, "-NoProfile", "-NonInteractive", "-Command", command],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as error:
                if getattr(error, "winerror", None) == 1314:
                    self.skipTest("Windows symlink creation privilege is unavailable")
                raise
        try:
            before = (canonical / "datasets.json").read_bytes()
            with self.assertRaises(ValueError):
                manager.uninstall(root, "ebmud", purge=True)
            self.assertEqual((canonical / "datasets.json").read_bytes(), before)
            self.assertEqual((content / "data.txt").read_text(), self.value)
            self.assertEqual(marker.read_bytes(), b"unowned target bytes")
        finally:
            if kind == "junction":
                if link.exists():
                    link.rmdir()
            else:
                link.unlink(missing_ok=True)

    def test_root_alias_symlinks_block_purge_inside_and_outside_root(self):
        for form in self.path_forms:
            for inside in (False, True):
                with self.subTest(path_form=form, target_inside=inside):
                    root = self.path_root(form, "symlink-" + str(inside))
                    self.assert_link_blocks_purge(root, "symlink", inside)

    @unittest.skipUnless(os.name == "nt", "Windows junction fixtures")
    def test_root_alias_junctions_block_purge_inside_and_outside_root(self):
        for form in self.path_forms:
            for inside in (False, True):
                with self.subTest(path_form=form, target_inside=inside):
                    if inside and not hasattr(Path, "is_junction"):
                        self.skipTest("Explicit junction detection requires Python 3.12 or newer")
                    root = self.path_root(form, "junction-" + str(inside))
                    self.assert_link_blocks_purge(root, "junction", inside)


if __name__ == "__main__":
    unittest.main()
