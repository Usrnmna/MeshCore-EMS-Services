"""Offline GUI planning, native-record discovery and batch failure-boundary tests."""

from contextlib import nullcontext
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installers.datasets import manage
from installers.datasets.gui import discovery, execution, planning
from installers.datasets.gui.catalog import DATASETS, LABELS


class GuiCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()
        self.root = self.folder / "data"
        self.payload = self.folder / "payload"
        self.payload.mkdir()
        self.target = "windows-x64"

    def snapshot(self, *, ready=(), data=()):
        snapshot = discovery.Snapshot(self.root, self.target)
        for name in DATASETS:
            prefix = self.folder / "tools" / name
            package = discovery.Package("ready" if name in ready else "missing", prefix,
                self.root if name in ready else None, (str(prefix / "Dataset.exe"),), (str(prefix / "unins000.exe"),))
            snapshot.collections[name] = discovery.Collection(package, "valid" if name in data else "missing")
        return snapshot

    def plan(self, snapshot, action="install_selected", selected=("ebmud",)):
        with patch.object(planning, "installer_artifact", return_value=(self.folder / "setup.exe", "")):
            return planning.make_plan(snapshot, action, selected, self.folder)

    def install(self, name="ebmud", **kwargs):
        def acquire(dataset, directory, *args, **kw):
            (directory / "data.txt").write_text("validated fixture", encoding="utf-8")
        return manage.install(self.root, name, self.payload,
                              acquire=kwargs.pop("acquire", acquire), validate=lambda *a: None, **kwargs)

    def package(self, name="ebmud"):
        """Create a native-record fixture without registering or installing anything."""
        prefix = self.folder / "tools" / name
        payload = prefix / "payload"
        (payload / "installers/datasets").mkdir(parents=True)
        for path in (prefix / "Dataset.exe", prefix / "unins000.exe", prefix / "python.exe", payload / "installers/datasets/manage.py"):
            path.write_text("fixture")
        manage.write_json(prefix / "runtime.json", {"dataset": name, "root": str(self.root), "python": str(prefix / "python.exe")})
        manage.write_json(payload / "DATA-PACKAGE.json", {"dataset": name, "version": "v1.0.0"})
        (payload / "dataset-id.txt").write_text(name)
        return prefix, {name: (prefix, '"' + str(prefix / "unins000.exe") + '"')}

    def scan(self, locations=None):
        return discovery.inspect(self.root, self.target, base=self.folder / "tools", locations=locations or {})

    def test_metadata_covers_every_existing_package(self):
        import build_data_installers
        self.assertEqual(set(DATASETS), set(LABELS))
        self.assertEqual(set(DATASETS), set(build_data_installers.DATASETS))
        self.assertEqual({key: value[0] for key, value in LABELS.items()}, build_data_installers.DISPLAY_NAMES)

    def test_unknown_action_or_identifier_is_rejected(self):
        with self.assertRaises(ValueError):
            self.plan(self.snapshot(), "purge")
        with self.assertRaises(ValueError):
            self.plan(self.snapshot(), selected=("../service",))

    def test_empty_selection_has_no_changes(self):
        self.assertEqual(self.plan(self.snapshot(), selected=()).operations, [])

    def test_install_expands_prerequisites_in_order(self):
        plan = self.plan(self.snapshot(), selected=("usgs_water",))
        self.assertEqual([op.dataset for op in plan.operations], ["basin_plans", "flood_impacts", "usgs_water"])
        self.assertIn("Required prerequisite", plan.operations[0].reason)

    def test_valid_installations_are_skipped_without_updates(self):
        snapshot = self.snapshot(ready=DATASETS, data=DATASETS)
        for action in ("missing_packages", "missing_data", "install_selected"):
            with self.subTest(action=action):
                self.assertEqual(self.plan(snapshot, action).operations, [])

    def test_missing_data_uses_installed_launcher_without_setup(self):
        snapshot = self.snapshot(ready=DATASETS, data=set(DATASETS) - {"ebmud"})
        plan = self.plan(snapshot, "missing_data")
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].kind, "install_data")
        self.assertEqual(plan.operations[0].command[-1], "install")

    def test_missing_package_with_valid_data_runs_setup_not_update(self):
        snapshot = self.snapshot(ready=set(DATASETS) - {"ebmud"}, data=DATASETS)
        plan = self.plan(snapshot, "missing_packages")
        self.assertEqual([op.dataset for op in plan.operations], ["ebmud"])
        self.assertEqual(plan.operations[0].kind, "setup")
        self.assertIn("/DATAROOT=" + str(self.root), plan.operations[0].command)

    def test_damaged_package_is_not_silently_repaired_by_missing_only(self):
        snapshot = self.snapshot(ready=DATASETS, data=DATASETS)
        state = snapshot.collections["ebmud"]
        snapshot.collections["ebmud"] = replace(state, package=replace(state.package, state="broken"))
        plan = self.plan(snapshot, "missing_packages")
        self.assertFalse(plan.operations)
        self.assertTrue(any("repair" in line for line in plan.skipped))
        self.assertEqual(self.plan(snapshot).operations[0].kind, "setup")

    def test_broken_active_data_is_never_replaced(self):
        snapshot = self.snapshot(ready=("ebmud",))
        snapshot.collections["ebmud"] = replace(snapshot.collections["ebmud"], data="broken")
        plan = self.plan(snapshot)
        self.assertFalse(plan.operations)
        self.assertTrue(plan.blocked)

    def test_mismatched_data_root_blocks_even_uninstall(self):
        snapshot = self.snapshot(ready=("ebmud",), data=("ebmud",))
        state = snapshot.collections["ebmud"]
        snapshot.collections["ebmud"] = replace(state, package=replace(state.package, root=self.folder / "other"))
        for action in ("install_selected", "uninstall_selected"):
            self.assertTrue(self.plan(snapshot, action).blocked)

    def test_selected_uninstall_does_not_silently_cascade(self):
        snapshot = self.snapshot(ready=DATASETS, data=DATASETS)
        snapshot.collections["basin_plans"] = replace(snapshot.collections["basin_plans"], dependents=("flood_impacts", "usgs_water"))
        plan = self.plan(snapshot, "uninstall_selected", ("basin_plans",))
        self.assertFalse(plan.operations)
        self.assertIn("Select dependents explicitly", plan.blocked[0])

    def test_uninstall_all_uses_reverse_order_without_purge(self):
        plan = self.plan(self.snapshot(ready=DATASETS, data=DATASETS), "uninstall_all")
        names = [op.dataset for op in plan.operations]
        self.assertLess(names.index("usgs_water"), names.index("flood_impacts"))
        self.assertLess(names.index("flood_impacts"), names.index("basin_plans"))
        self.assertNotIn("purge", " ".join(" ".join(op.command) for op in plan.operations).lower())

    def test_missing_tools_with_managed_data_blocks_removal(self):
        snapshot = self.snapshot(data=("ebmud",))
        snapshot.collections["ebmud"] = replace(snapshot.collections["ebmud"], managed=True)
        self.assertTrue(self.plan(snapshot, "uninstall_all").blocked)

    def test_inconsistent_dependency_generations_block_install(self):
        snapshot = self.snapshot(data=("basin_plans", "flood_impacts"))
        snapshot.collections["usgs_water"] = replace(snapshot.collections["usgs_water"], dependency_error="Update flood_impacts against selected basin")
        self.assertTrue(self.plan(snapshot, selected=("usgs_water",)).blocked)

    def test_directory_alone_is_not_a_valid_package_or_dataset(self):
        (self.root / "ebmud").mkdir(parents=True)
        (self.folder / "tools/ebmud").mkdir(parents=True)
        state = self.scan().collections["ebmud"]
        self.assertEqual(state.package.state, "missing")
        self.assertEqual(state.data, "unmanaged")

    def test_registered_tools_and_verified_active_data_are_separate(self):
        _, locations = self.package()
        self.assertEqual(self.scan(locations).collections["ebmud"].package.state, "ready")
        self.assertEqual(self.scan(locations).collections["ebmud"].data, "missing")
        self.install()
        self.assertEqual(self.scan(locations).collections["ebmud"].data, "valid")

    def test_same_version_native_repair_invalidates_reviewed_package_revision(self):
        prefix, locations = self.package()
        before = self.scan(locations)
        old_plan = self.plan(before)
        identity = (prefix / "payload/DATA-PACKAGE.json").read_bytes()
        (prefix / "Dataset.exe").write_bytes(b"same-version repaired executable")
        after = self.scan(locations)
        self.assertNotEqual(before.collections["ebmud"].package.revision, after.collections["ebmud"].package.revision)
        self.assertEqual((prefix / "payload/DATA-PACKAGE.json").read_bytes(), identity)
        self.assertNotEqual(old_plan.registry_fingerprint, self.plan(after).registry_fingerprint)

    def test_corrupt_receipt_or_data_is_reported_and_unchanged(self):
        record = self.install()
        path = manage.record_path(self.root, "ebmud", record) / "data.txt"
        path.write_text("operator modification")
        before = (self.root / "datasets.json").read_bytes()
        self.assertEqual(self.scan().collections["ebmud"].data, "broken")
        self.assertEqual(path.read_text(), "operator modification")
        self.assertEqual((self.root / "datasets.json").read_bytes(), before)

    def test_corrupt_global_registry_aborts_discovery(self):
        self.root.mkdir()
        (self.root / "datasets.json").write_text("not json")
        with self.assertRaises(ValueError):
            self.scan()

    def test_last_failed_update_does_not_mark_valid_data_missing(self):
        self.install()
        manage.attempt_status(self.root, "ebmud", {"state": "failed", "candidate": "abc", "error": "offline"})
        state = self.scan().collections["ebmud"]
        self.assertEqual(state.data, "valid")
        self.assertIn("offline", state.detail)

    def test_first_failed_acquisition_is_incomplete(self):
        manage.attempt_status(self.root, "ebmud", {"state": "failed", "candidate": "abc"})
        self.assertEqual(self.scan().collections["ebmud"].data, "incomplete")

    def test_package_identity_runtime_and_uninstaller_are_checked(self):
        prefix, locations = self.package()
        for filename in ("runtime.json", "payload/DATA-PACKAGE.json"):
            path = prefix / filename
            original = path.read_bytes()
            path.write_text('{}')
            self.assertEqual(self.scan(locations).collections["ebmud"].package.state, "broken")
            path.write_bytes(original)
        locations["ebmud"] = (prefix, str(self.folder / "other.exe"))
        self.assertEqual(self.scan(locations).collections["ebmud"].package.state, "broken")

    def test_native_log_residue_does_not_count_as_installed(self):
        (self.folder / "tools/ebmud/logs").mkdir(parents=True)
        unowned = self.folder / "tools/ebmud/payload/custom-notes.txt"
        unowned.parent.mkdir()
        unowned.write_text("operator file retained after uninstall")
        self.assertEqual(self.scan().collections["ebmud"].package.state, "missing")

    def test_retained_uninstalled_data_does_not_require_another_removal(self):
        record = self.install()
        path = manage.record_path(self.root, "ebmud", record) / "data.txt"
        path.write_text("modified, retained")
        manage.uninstall(self.root, "ebmud")
        snapshot = self.scan()
        self.assertFalse(snapshot.collections["ebmud"].managed)
        self.assertEqual(self.plan(snapshot, "uninstall_all").operations, [])
        self.assertTrue(path.is_file())

    def test_existing_installer_copy_preserves_bytes_and_target_separation(self):
        import build_dataset_gui
        checksums = []
        for name in DATASETS:
            for suffix in ("windows-x64-setup.exe", "linux-x86_64.run", "raspberry-pi-arm64.run"):
                path = self.folder / f"MeshCore-EMS-Data-{name}-v1.0.0-{suffix}"
                path.write_bytes((name + suffix).encode())
                checksums.append(planning.file_hash(path) + "  " + path.name + "\n")
        (self.folder / "SHA256SUMS.txt").write_text("".join(checksums))
        destination = self.folder / "copied"
        with patch.object(build_dataset_gui.subprocess, "run", side_effect=AssertionError("No compilation allowed")):
            build_dataset_gui.copy_installers(self.folder, destination, self.target)
        self.assertEqual(len(list(destination.glob("*.exe"))), 8)
        self.assertEqual(list(destination.glob("*.run")), [])
        for path in destination.glob("*.exe"):
            self.assertEqual(path.read_bytes(), (self.folder / path.name).read_bytes())

    def test_windows_build_excludes_unrelated_dll_search_paths(self):
        import build_dataset_gui
        with patch.object(build_dataset_gui.sys, "platform", "win32"), patch.dict(os.environ, {"PATH": "unrelated-icu-directory"}):
            environment = build_dataset_gui.build_environment()
        self.assertNotIn("unrelated-icu-directory", environment["PATH"])
        self.assertIn(str(Path(sys.executable).parent), environment["PATH"])

    def test_linux_runtime_record_and_paths(self):
        prefix = self.folder / "tools/ebmud"
        release = prefix / "releases/runtime.test"
        payload = release / "payload"
        (payload / "installers/datasets").mkdir(parents=True)
        (release / "venv/bin").mkdir(parents=True)
        for path in (prefix / "dataset", prefix / "uninstall", release / "venv/bin/python", payload / "installers/datasets/manage.py"):
            path.write_text("fixture")
            path.chmod(0o755)
        (prefix / "data-root.txt").write_text(str(self.root))
        (payload / "dataset-id.txt").write_text("ebmud")
        manage.write_json(payload / "DATA-PACKAGE.json", {"dataset": "ebmud"})
        # Patch resolution only at the published current link; Windows test hosts
        # need no symlink privileges to exercise the Linux record contract.
        original_resolve = Path.resolve
        def resolve(path, *args, **kwargs):
            if path == prefix / "current":
                path = release
            return original_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolve):
            package = discovery.read_package("ebmud", "linux-x86_64", {}, prefix.parent)
        self.assertEqual(package.state, "ready", package.detail)
        self.assertEqual(package.uninstaller, (str(prefix / "uninstall"),))

    def artifact(self, target="windows-x64", version="v1.0.0"):
        suffix = "windows-x64-setup.exe" if target == "windows-x64" else target + ".run"
        path = self.folder / f"MeshCore-EMS-Data-ebmud-{version}-{suffix}"
        path.write_bytes(b"fixture artifact")
        (self.folder / "SHA256SUMS.txt").write_text(planning.file_hash(path) + "  " + path.name + "\n")
        return path

    def test_artifact_selection_is_target_specific_and_checksummed(self):
        path = self.artifact()
        self.assertEqual(planning.installer_artifact(self.folder, "ebmud", self.target)[0], path.resolve())
        with self.assertRaises(ValueError):
            planning.installer_artifact(self.folder, "ebmud", "linux-x86_64")
        path.write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "mismatched"):
            planning.installer_artifact(self.folder, "ebmud", self.target)

    def test_multiple_releases_require_explicit_folder_choice(self):
        self.artifact(version="v1.0.0")
        self.artifact(version="v2.0.0")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            planning.installer_artifact(self.folder, "ebmud", self.target)

    def execute(self, plan, scan, launch, cancel=None):
        return execution.run_batch(plan, self.folder, cancel or threading.Event(), lambda text: None, lambda *args: None,
                                   scan=scan, launch=launch, lock=lambda target: nullcontext(),
                                   is_privileged=lambda: True, target=lambda: self.target)

    def test_demo_cannot_discover_lock_or_launch(self):
        plan = planning.make_plan(discovery.demo_snapshot(self.root, self.target), "missing_data", (), self.folder, demo=True)
        def forbidden(*args, **kwargs):
            self.fail("Demo accessed a host operation")
        results = execution.run_batch(plan, self.folder, threading.Event(), lambda text: None, lambda *args: None,
                                     scan=forbidden, launch=forbidden, lock=forbidden, is_privileged=forbidden, target=forbidden)
        self.assertTrue(results)
        self.assertTrue(all(item.outcome == "simulated" for item in results))
        self.assertFalse(self.root.exists())

    def test_cancel_before_batch_starts_no_package(self):
        before = self.snapshot(ready=DATASETS)
        plan = self.plan(before, selected=("ebmud", "landslide"))
        cancel = threading.Event()
        cancel.set()
        results = self.execute(plan, lambda *a, **kw: before, lambda *a: self.fail("Launched"), cancel)
        self.assertTrue(all(item.outcome == "cancelled" for item in results))

    def test_cancel_during_package_allows_completion_and_verification(self):
        before = self.snapshot(ready=DATASETS)
        after = self.snapshot(ready=DATASETS, data=("ebmud",))
        plan = self.plan(before, selected=("ebmud", "landslide"))
        cancel = threading.Event()
        calls = []
        def launch(operation, emit):
            calls.append(operation.dataset)
            cancel.set()
            return 0
        scans = iter((before, after))
        results = self.execute(plan, lambda *a, **kw: next(scans), launch, cancel)
        self.assertEqual(calls, ["ebmud"])
        self.assertEqual([item.outcome for item in results], ["succeeded", "cancelled"])

    def test_failure_stops_dependents_and_preserves_real_active_data(self):
        record = self.install()
        registry = (self.root / "datasets.json").read_bytes()
        before = self.snapshot(ready=DATASETS)
        plan = self.plan(before, selected=("ebmud", "landslide"))
        def launch(operation, emit):
            def fail(*args, **kwargs):
                raise OSError("offline fixture")
            try:
                self.install(update=True, acquire=fail)
            except OSError:
                return 20
        results = self.execute(plan, lambda *a, **kw: before, launch)
        self.assertEqual([item.outcome for item in results], ["failed", "not run"])
        self.assertIn("20", results[0].detail)
        self.assertEqual((self.root / "datasets.json").read_bytes(), registry)
        manage.verify_record(self.root, "ebmud", record)

    def test_zero_exit_without_valid_data_is_failure(self):
        before = self.snapshot(ready=DATASETS)
        results = self.execute(self.plan(before), lambda *a, **kw: before, lambda *a: 0)
        self.assertEqual(results[0].outcome, "failed")

    def test_changed_registry_blocks_stale_plan_before_launch(self):
        before = self.snapshot(ready=DATASETS)
        plan = self.plan(before)
        before.registry = {"changed": True}
        with self.assertRaisesRegex(RuntimeError, "changed since review"):
            self.execute(plan, lambda *a, **kw: before, lambda *a: self.fail("Launched"))

    def test_existing_backend_lock_blocks_before_discovery(self):
        self.root.mkdir()
        (self.root / ".datasets.lock").write_text("pid=fixture")
        plan = self.plan(self.snapshot(ready=DATASETS))
        with self.assertRaisesRegex(RuntimeError, "locked"):
            self.execute(plan, lambda *a, **kw: self.fail("scanned"), lambda *a: self.fail("launched"))

    @unittest.skipUnless(os.name == "nt" or getattr(os, "geteuid", lambda: -1)() == 0,
                         "Protected POSIX lease fixture runs in the separate root-only CI step")
    def test_batch_lock_is_exclusive_across_data_roots(self):
        from installers.desktop import locking
        def private_fixture(path, content):
            with Path(path).open("xb") as stream:
                stream.write(content)
            if os.name != "nt":
                Path(path).chmod(0o600)
        with patch.object(locking, "lock_directory", return_value=self.folder), patch.object(locking, "_secure_directory"), \
                patch.object(locking, "_private_owner"), patch.object(locking, "create_private_file", side_effect=private_fixture), \
                patch.object(locking, "create_private_directory", side_effect=lambda path: Path(path).mkdir(mode=0o700)):
            with execution.batch_lock(self.target):
                with patch.dict(os.environ):
                    os.environ.pop(locking.VARIABLE, None)
                    with self.assertRaisesRegex(RuntimeError, "Another maintenance"):
                        with execution.batch_lock(self.target):
                            self.fail("Distinct caller acquired the lease")
            self.assertFalse((self.folder / "lease").exists())

    def test_live_subprocess_output_and_nonzero_exit(self):
        command = (sys.executable, "-c", "import sys; print('fixture progress', flush=True); sys.exit(7)")
        operation = planning.Operation("ebmud", "fixture", command, "fixture", self.folder)
        output = []
        # Streaming is exercised with a disposable unprivileged Python child;
        # installed-path protection has separate native metadata/handle tests.
        self.assertEqual(execution._run_process(operation, output.append), 7)
        self.assertIn("fixture progress", "".join(output))

    def test_log_tail_skips_old_runs_and_decodes_utf16(self):
        log = self.folder / "logs"
        log.mkdir()
        (log / "old.stdout.log").write_text("old")
        tail = execution.LogTail(log)
        path = log / "new.stdout.log"
        path.write_text("new line", encoding="utf-16")
        output = []
        tail.poll(output.append)
        tail.poll(output.append)
        self.assertEqual("".join(output).count("new line"), 1)
        self.assertNotIn("old.stdout", "".join(output))


if __name__ == "__main__":
    unittest.main()
