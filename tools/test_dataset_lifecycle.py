"""Isolated retention and maintenance-planning contracts for independent packages."""

from dataclasses import replace
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installers.datasets import manage
from installers.datasets.gui import discovery, planning, execution
from installers.desktop import locking


class RetentionTests(unittest.TestCase):
    def test_retained_uninstall_does_not_change_registry_or_generations(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "data"
            def acquire(name, destination, *args, **kwargs):
                (destination / "fixture.txt").write_text("retained bytes")
            record = manage.install(root, "ebmud", Path(folder), acquire=acquire, validate=lambda *args: None)
            registry = (root / "datasets.json").read_bytes()
            result = manage.retain(root, "ebmud")
            self.assertTrue(result["data_retained"])
            self.assertEqual((root / "datasets.json").read_bytes(), registry)
            manage.verify_record(root, "ebmud", record)
            # Reinstallation reuses the same validated generation; no acquisition.
            recovered = manage.install(root, "ebmud", Path(folder), acquire=lambda *args: self.fail("Acquired again"), validate=lambda *args: None)
            self.assertEqual(recovered, record)

    def snapshot(self):
        result = discovery.Snapshot(Path("C:/retained-data").resolve(), "windows-x64")
        for name in planning.DATASETS:
            prefix = Path("C:/fixture-tools").resolve() / name
            package = discovery.Package("ready", prefix, result.root, (str(prefix / "Dataset.exe"),),
                                        (str(prefix / "unins000.exe"),), capabilities=("retain-data-v1", "maintenance-lock-v1"))
            result.collections[name] = discovery.Collection(package, "valid", managed=True)
        return result

    def test_retained_custom_root_hint_does_not_claim_package_or_data_ownership(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / "custom data root"
            root.mkdir()
            def private_fixture(path, content):
                Path(path).write_bytes(content)
            with patch("installers.desktop.locking.maintenance_directory", return_value=base / "maintenance"), \
                    patch.object(locking, "create_private_directory", side_effect=lambda path: Path(path).mkdir(mode=0o700)), \
                    patch.object(locking, "create_private_file", side_effect=private_fixture):
                (base / "maintenance").mkdir()
                manage.remember_retained_root(root, "ebmud")
            self.assertEqual((base / "maintenance/retained-roots/ebmud.txt").read_text().strip(), str(root.resolve()))
            self.assertFalse((root / "datasets.json").exists())

    def test_retaining_tools_removal_does_not_remove_data_dependents(self):
        snapshot = self.snapshot()
        snapshot.collections["basin_plans"] = replace(snapshot.collections["basin_plans"], dependents=("flood_impacts",))
        plan = planning.make_plan(snapshot, "retain_selected", ("basin_plans",), Path("."))
        self.assertFalse(plan.blocked)
        self.assertEqual([operation.kind for operation in plan.operations], ["uninstall_tools"])
        self.assertNotIn("/REMOVEDATA=1", plan.operations[0].command)

    def test_legacy_backend_cannot_claim_tools_only_retention(self):
        snapshot = self.snapshot()
        entry = snapshot.collections["ebmud"]
        snapshot.collections["ebmud"] = replace(entry, package=replace(entry.package, capabilities=()))
        plan = planning.make_plan(snapshot, "retain_selected", ("ebmud",), Path("."))
        self.assertFalse(plan.operations)
        self.assertIn("retain-data", plan.blocked[0])

    def test_explicit_data_removal_selects_native_flag(self):
        plan = planning.make_plan(self.snapshot(), "uninstall_selected", ("ebmud",), Path("."))
        self.assertIn("/REMOVEDATA=1", plan.operations[0].command)

    def test_maintenance_verbs_use_only_registered_launcher(self):
        for verb in ("verify", "update", "rollback"):
            plan = planning.make_plan(self.snapshot(), verb + "_selected", ("ebmud",), Path("."))
            self.assertEqual(plan.operations[0].kind, verb)
            self.assertEqual(plan.operations[0].command[-1], verb)

    def test_explicit_repair_provisions_current_tools_even_when_data_is_valid(self):
        snapshot = self.snapshot()
        state = snapshot.collections["ebmud"]
        snapshot.collections["ebmud"] = replace(state, package=replace(state.package, capabilities=()))
        with patch.object(planning, "installer_artifact", return_value=(Path("C:/current setup.exe"), "a" * 64)):
            plan = planning.make_plan(snapshot, "repair_selected", ("ebmud",), Path("."))
        self.assertFalse(plan.blocked)
        self.assertEqual(plan.operations[0].kind, "setup")
        self.assertIn("/DATAROOT=" + str(snapshot.root), plan.operations[0].command)


@unittest.skipUnless(os.name == "nt" or getattr(os, "geteuid", lambda: -1)() == 0,
                     "Protected POSIX recovery fixtures run in the separate root-only CI step")
class DatasetLockRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "data"
        self.root.mkdir()
        self.archive = Path(self.temporary.name) / "protected-fixture"
        self.archive.mkdir()
        self.addCleanup(patch.stopall)
        patch.dict(os.environ).start()
        os.environ.pop(locking.VARIABLE, None)
        patch.object(locking, "_private_owner").start()
        patch.object(locking, "operation_lock", side_effect=lambda: nullcontext()).start()
        patch.object(locking, "maintenance_directory", return_value=self.archive).start()
        patch.object(locking, "_native_process_gate", return_value=[]).start()
        def private_fixture(path, content):
            with Path(path).open("xb") as stream:
                stream.write(content)
            if os.name != "nt":
                Path(path).chmod(0o600)
        patch.object(locking, "create_private_file", side_effect=private_fixture).start()

    def record(self):
        path = self.root / ".datasets.lock"
        value = {"schema": 2, "pid": 999991, "creation": "11", "lease": "a" * 32,
                 "coordinated": True, "started": "fixture"}
        path.write_text(json.dumps(value))
        if os.name != "nt":
            path.chmod(0o600)
        return path

    def test_new_coordinated_lock_records_creation_identity_and_private_schema(self):
        with patch.dict(os.environ, {locking.VARIABLE: "b" * 32}), \
                patch.object(manage, "protected_data_root", side_effect=lambda *args, **kwargs: nullcontext()):
            with manage.locked(self.root):
                path = self.root / ".datasets.lock"
                value = json.loads(path.read_text())
                self.assertEqual(value["schema"], 2)
                self.assertEqual(value["pid"], os.getpid())
                self.assertEqual(value["creation"], locking.process_identity(os.getpid()))
                self.assertTrue(value["coordinated"])
                if os.name != "nt":
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(path.exists())

    def test_reviewed_dead_owner_lock_archives_without_touching_data_or_registry(self):
        path = self.record()
        (self.root / "datasets.json").write_text('{"schema":1,"datasets":{}}')
        (self.root / "retained.txt").write_text("preserved")
        before = (self.root / "datasets.json").read_bytes()
        with patch.object(locking, "_process_state", return_value="dead"):
            status = manage.inspect_lock_recovery(self.root)
            self.assertTrue(status["recoverable"], status)
            result = manage.recover_lock(self.root, status["revision"])
        self.assertFalse(path.exists())
        self.assertTrue(Path(result["archive"]).is_file())
        self.assertEqual((self.root / "datasets.json").read_bytes(), before)
        self.assertEqual((self.root / "retained.txt").read_text(), "preserved")

    def test_live_owner_and_unknown_native_child_each_block_recovery(self):
        path = self.record()
        with patch.object(locking, "_process_state", return_value="live"):
            self.assertFalse(manage.inspect_lock_recovery(self.root)["recoverable"])
        with patch.object(locking, "_process_state", return_value="dead"), patch.object(locking, "_native_process_gate", return_value=[{"pid": 1, "state": "unknown"}]):
            self.assertFalse(manage.inspect_lock_recovery(self.root)["recoverable"])
        self.assertTrue(path.exists())

    def test_pid_reuse_checks_creation_identity_instead_of_current_pid_alone(self):
        self.record()
        with patch.object(locking, "process_identity", return_value="22"):
            self.assertTrue(manage.inspect_lock_recovery(self.root)["recoverable"])

    def test_legacy_record_never_uses_pid_age_or_reuse_for_recovery(self):
        path = self.record()
        path.write_text("pid=999991 started=historical")
        status = manage.inspect_lock_recovery(self.root)
        self.assertFalse(status["recoverable"])
        self.assertTrue(path.exists())

    def test_changed_record_invalidates_review_without_removing_it(self):
        path = self.record()
        with patch.object(locking, "_process_state", return_value="dead"):
            status = manage.inspect_lock_recovery(self.root)
            path.write_text(path.read_text().replace('"11"', '"33"'))
            with self.assertRaisesRegex(RuntimeError, "changed"):
                manage.recover_lock(self.root, status["revision"])
        self.assertTrue(path.exists())

    def test_recovery_plan_uses_one_registered_backend_for_shared_root(self):
        status = {"revision": "a" * 64, "recoverable": True, "detail": "fixture"}
        snapshot = discovery.Snapshot(self.root, "windows-x64")
        for name in planning.DATASETS:
            prefix = self.root / "tools" / name
            package = discovery.Package("ready", prefix, self.root, (str(prefix / "Dataset.exe"),),
                                        capabilities=("dataset-lock-recovery-v1",))
            snapshot.collections[name] = discovery.Collection(package, "broken")
        with patch.object(manage, "inspect_lock_recovery", return_value=status):
            plan = planning.make_plan(snapshot, "recover_selected", ("ebmud", "landslide"), self.root)
        self.assertFalse(plan.blocked)
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].kind, "recover_lock")
        self.assertEqual(plan.operations[0].command[-3:], ("recover-lock", "-ReviewedLock", "a" * 64))

    def test_demo_recovery_does_not_inspect_host_locks_or_processes(self):
        snapshot = discovery.demo_snapshot(self.root, "windows-x64")
        with patch.object(manage, "inspect_lock_recovery", side_effect=AssertionError("Inspected host")):
            plan = planning.make_plan(snapshot, "recover_selected", ("ebmud",), self.root, demo=True)
        self.assertFalse(plan.blocked)
        self.assertEqual(plan.operations[0].kind, "recover_lock")

    def test_batch_recovery_accepts_broken_data_without_claiming_it_was_repaired(self):
        self.record()
        snapshot = discovery.Snapshot(self.root, "windows-x64")
        for name in planning.DATASETS:
            package = discovery.Package("ready", self.root / "tools" / name, self.root,
                                        ("fixture-launcher",), capabilities=("dataset-lock-recovery-v1",))
            snapshot.collections[name] = discovery.Collection(package, "broken")
        with patch.object(locking, "_process_state", return_value="dead"):
            plan = planning.make_plan(snapshot, "recover_selected", ("ebmud",), self.root)
            def launch(operation, emit):
                manage.recover_lock(self.root, operation.command[-1])
                return 0
            results = execution.run_batch(plan, self.root, threading.Event(), lambda *args: None, lambda *args: None,
                scan=lambda *args, **kwargs: snapshot, launch=launch, lock=lambda *args: nullcontext(),
                is_privileged=lambda: True, target=lambda: "windows-x64")
        self.assertEqual(results[0].outcome, "succeeded")
        self.assertIn("separate operation", results[0].detail)
        self.assertEqual(snapshot.collections["ebmud"].data, "broken")


if __name__ == "__main__":
    unittest.main()
