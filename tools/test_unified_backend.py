"""Isolated ownership, review invalidation and recovery tests for orchestration."""
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import os
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installers.datasets.gui.discovery import demo_snapshot
from installers.desktop import unified_backend as unified


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        from tools.test_desktop_staging import fixture_staging
        fixture_staging(self, self.root)
        owner = patch("installers.desktop.staging.require_trusted_owner")
        owner.start(); self.addCleanup(owner.stop)
        self.intent = dict(target="windows-x64", root=str(self.root / "data"), folder=str(self.root),
                           datasets=[], dataset_action="keep", service_action="keep", settings={},
                           startup="preserve", start=False)
        self.snapshot = demo_snapshot(Path(self.intent["root"]), "windows-x64")
        self.service = dict(registered=True, state="running", startup="automatic", settings={},
                            revision="a" * 64, capabilities=["operation-lock-v1", "settings-v2"])

    def plan(self, **changes):
        return unified.build_plan(dict(self.intent, **changes), self.snapshot, self.service, demo=True)[0]

    def test_service_bundled_commands_are_not_separate_packages(self):
        plan = self.plan(service_action="configure", settings={"commands": {"!status": False}})
        self.assertTrue(any(step["action"] == "configure" for step in plan["steps"]))
        self.assertFalse(any(step["owner"] == "!status" for step in plan["steps"]))

    def test_stop_precedes_data_and_restart_follows_validation(self):
        plan = self.plan(dataset_action="install", datasets=["usgs_water"], service_action="configure")
        actions = [step["action"] for step in plan["steps"]]
        self.assertLess(actions.index("stop"), actions.index("install_selected"))
        self.assertLess(actions.index("configure"), actions.index("start"))
        self.assertIn("basin_plans", plan["text"])

    def test_deconfiguration_leaves_service_stopped(self):
        plan = self.plan(service_action="deconfigure")
        self.assertNotIn("start", [step["action"] for step in plan["steps"]])

    def test_deconfiguration_honors_explicit_disabled_boot_policy(self):
        plan = self.plan(service_action="deconfigure", startup="disabled")
        self.assertEqual([step["action"] for step in plan["steps"]], ["stop", "deconfigure", "startup"])
        self.assertFalse(plan["blocked"])
        automatic = self.plan(service_action="deconfigure", startup="automatic")
        self.assertTrue(automatic["blocked"])

    def test_deconfiguration_review_lists_exact_owned_restores_and_conflicts(self):
        self.service["settings"] = {"deconfiguration": {"changes": [{"path": "mqtt.host", "current": {"present": True, "value": "new-host"},
            "restore": {"present": True, "value": "old-host"}}], "conflicts": ["dataset_root"]}}
        plan = self.plan(service_action="deconfigure")
        self.assertIn("RESTORE mqtt.host", plan["text"])
        self.assertIn("old-host", plan["text"])
        self.assertIn("RETAIN CONFLICT: dataset_root", plan["text"])

    def test_review_binds_configuration_artifacts_and_credentials(self):
        first = self.plan(service_action="configure")
        self.service["revision"] = "b" * 64
        second = self.plan(service_action="configure")
        self.assertNotEqual(first["digest"], second["digest"])
        self.assertNotIn("supersecret", self.plan(service_action="configure", settings={"credentials": {"AIRNOW_API_KEY": "supersecret"}})["text"])

    def test_history_credentials_are_hidden_and_missing_capability_is_optional(self):
        plan = unified.build_plan(dict(self.intent, service_action="configure", settings={"channel_history": {"enabled": True, "channel_id": "missing"}, "history_credentials": {"MESHCORE_CHANNEL_KEY_ONLY": "private-key-value"}}), self.snapshot, self.service)[0]
        self.assertFalse(plan["blocked"])
        self.assertNotIn("private-key-value", plan["text"])
        self.assertEqual(plan["history_outcome"]["status"], "not_applied")
        self.assertIn("Not applied", plan["text"])

    def test_rejected_history_only_plan_has_no_service_restart_or_save(self):
        plan = unified.build_plan(dict(self.intent, service_action="configure", settings={"channel_history": {"enabled": True, "channel_id": "missing"}}), self.snapshot, self.service)[0]
        self.assertEqual(plan["steps"], [])
        self.assertFalse(plan["blocked"])

    def test_review_explains_recording_target_retention_and_restart_without_storage_read(self):
        self.service["capabilities"].append("channel-history-v1")
        self.service["settings"] = {"channel_history": {"enabled": False}, "channels": {"channels": {"public": {"name": "Public", "type": "public", "mqtt_export": True}}}}
        plan = self.plan(service_action="configure", settings={"channel_history": {"enabled": True, "channel_id": "public"}})
        self.assertIn("86400 seconds", plan["text"])
        self.assertIn("Public (public)", plan["text"])
        self.assertIn("channel_history.sqlite3", plan["text"])
        self.assertIn("stop: yes", plan["text"])
        self.assertIn("restart: yes", plan["text"])

    def test_optional_preview_failure_does_not_invalidate_reviewed_core_digest(self):
        settings = {"credentials": {"AIRNOW_API_KEY": "new"}, "channel_history": {"enabled": False}}
        with patch.object(unified.service, "review_history", return_value={"status": "applied", "reason": "applied", "available": True}):
            before = self.plan(service_action="configure", settings=settings)
        with patch.object(unified.service, "review_history", return_value={"status": "not_applied", "reason": "unavailable", "available": False}):
            after = self.plan(service_action="configure", settings=settings)
        self.assertEqual(before["digest"], after["digest"])

    def test_review_rejected_optional_fields_are_never_promoted_during_execution(self):
        self.service["state"] = "stopped"
        settings = {"credentials": {"AIRNOW_API_KEY": "new"}, "channel_history": {"enabled": False}}
        with patch.object(unified.service, "review_history", return_value={"status": "not_applied", "reason": "unsupported", "available": False}):
            plan = self.plan(service_action="configure", settings=settings)
        requests = []
        def perform(request, emit, cancel):
            requests.append(request)
            return {}
        with patch.object(unified.service, "snapshot", return_value=self.service), patch.object(unified.service, "perform", side_effect=perform):
            unified.run_plan(plan, None, lambda _: None, threading.Event())
        self.assertEqual(requests[0]["settings"], {"credentials": {"AIRNOW_API_KEY": "new"}})

    def test_unknown_requests_and_arbitrary_commands_rejected(self):
        for extra in ({"command": "anything"}, {"dataset_action": "purge"}, {"startup": "evil"}, {"start": "yes"}):
            with self.assertRaises(ValueError):
                unified.validate_intent(dict(self.intent, **extra))

    def test_cancel_demo_never_discovers_host(self):
        plan = self.plan(service_action="configure")
        cancel = threading.Event(); cancel.set()
        with patch.object(unified, "discover", side_effect=AssertionError("host access")):
            result = unified.execute_reviewed(plan, cancel, lambda _: None, demo=True)
        self.assertFalse(result["complete"])
        self.assertTrue(all(item["outcome"] == "cancelled" for item in result["results"]))

    def test_failure_journal_retains_completed_steps_without_secrets(self):
        journal = unified.Journal(self.root / "journals", {"steps": [{"owner": "service", "action": "configure", "detail": "configure"}]})
        journal.record(0, "succeeded", "Saved settings")
        journal.finish(False)
        text = journal.path.read_text()
        self.assertIn("succeeded", text)
        self.assertNotIn("credentials", text)

    def test_disabled_policy_stops_running_service_without_restart(self):
        plan = self.plan(startup="disabled")
        self.assertEqual([step["action"] for step in plan["steps"]], ["stop", "startup"])

    def test_full_removal_uninstalls_service_before_datasets(self):
        plan = self.plan(service_action="uninstall", dataset_action="remove_data", datasets=["ebmud"])
        actions = [step["action"] for step in plan["steps"]]
        self.assertLess(actions.index("uninstall"), actions.index("uninstall_selected"))

    def test_changed_review_cannot_begin_native_execution(self):
        plan = self.plan(service_action="configure")
        with patch.object(unified, "native_target", return_value="windows-x64"), \
             patch("installers.datasets.gui.execution.privileged", return_value=True), \
             patch("installers.desktop.locking.operation_lock", return_value=nullcontext()), \
             patch.object(unified, "discover", return_value=(self.snapshot, self.service)), \
             patch.object(unified, "run_plan") as run:
            with self.assertRaisesRegex(RuntimeError, "changed after review"):
                unified.perform(dict(kind="unified", action="execute", intent=plan["intent"], digest=plan["digest"]), lambda _: None)
        run.assert_not_called()

    def test_native_failure_withholds_start_and_journals_only_safe_evidence(self):
        plan = self.plan(service_action="configure", settings={"credentials": {"AIRNOW_API_KEY": "unique-secret"}})
        logs = []
        with patch("installers.desktop.locking.maintenance_directory", return_value=self.root), \
             patch.object(unified.service, "snapshot", return_value=self.service), \
             patch.object(unified.service, "perform", side_effect=[{}, RuntimeError("unique-secret failure")]) as owner:
            result = unified.run_plan(plan, None, logs.append, threading.Event())
        self.assertFalse(result["complete"])
        self.assertEqual([item["outcome"] for item in result["results"]], ["succeeded", "failed", "not run", "not run"])
        self.assertEqual(owner.call_count, 2)
        self.assertNotIn("unique-secret", "\n".join(logs))
        self.assertNotIn("unique-secret", Path(result["journal"]).read_text())

    def test_mid_operation_cancellation_preserves_success_and_skips_start(self):
        plan = self.plan(service_action="configure")
        cancel = threading.Event()
        def perform(request, emit, marker):
            cancel.set()
            return {}
        with patch("installers.desktop.locking.maintenance_directory", return_value=self.root), \
             patch.object(unified.service, "snapshot", return_value=self.service), \
             patch.object(unified.service, "perform", side_effect=perform):
            result = unified.run_plan(plan, None, lambda _: None, cancel)
        self.assertEqual([item["outcome"] for item in result["results"]], ["succeeded", "cancelled", "cancelled", "cancelled"])

    def test_history_rejects_caller_selected_paths(self):
        with self.assertRaises(ValueError):
            unified.validate_request(dict(kind="unified", action="history", target="windows-x64", path="anything"))

    def test_initial_commands_are_available_without_importing_service_programs(self):
        settings = unified.default_settings("windows-x64")
        self.assertEqual(len(settings["commands"]), 31)
        self.assertTrue(all(spec["owner"] == "service-package" for spec in settings["commands"].values()))


if __name__ == "__main__":
    unittest.main()
