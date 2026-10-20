"""Refresh integration: diagnostics, publication failure, and current-only isolation."""

from contextlib import ExitStack, redirect_stdout
import io
import unittest
from unittest.mock import patch

from data.flood_impacts import archive
from data.usgs_water.audit_source_rules import audit, audit_generation
from data.usgs_water.local_review import refresh_local_review, station_signature
from data.usgs_water.relationships import read_csv
from data.usgs_water.test_usgs_water import workspace


class RefreshAuditTests(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(workspace())
        self.rules_path = self.root / "rules.json"
        self.station = {"properties": {"monitoring_location_name": "Canal"},
                        "geometry": {"type": "Point", "coordinates": [-121, 38]}}
        self.rules = {"sources": [{
            "id": "operator", "url": "https://agency.example/canal", "format": "html",
            "excerpts": [{"id": "head", "text": "District\u2019s canal"}],
        }], "stations": {"USGS-00123456": {
            "station_signature": station_signature(self.station), "source_ids": ["operator"],
            "finding": "Exact hydrography address is unresolved.", "links": [],
        }}}
        archive.write_json(self.rules_path, self.rules)
        stage, identifier = archive.begin(self.root, "inventory")
        archive.write_csv(stage / "relationships/station_region_plan.csv",
                          [{"station_id": "USGS-00123456", "region": "central_valley"}],
                          ("station_id", "region"))
        archive.publish(self.root, stage, identifier, "inventory", {})
        stage, identifier = archive.begin(self.root, "agency_review")
        archive.write_csv(stage / "relationships/station_agency_review.csv", [{
            "station_id": "USGS-00123456", "station_name": "Canal", "status": "unresolved",
        }], ("station_id", "station_name", "status"))
        archive.write_json(stage / "current_station_metadata.json", {"USGS-00123456": self.station})
        archive.publish(self.root, stage, identifier, "agency_review", {
            "inventory_pointer": archive.read_json(self.root / "inventory.json")})
        # A sentinel detects accidental observation writes without fixture levels.
        (self.root / "observations.json").write_bytes(b"unchanged-current-snapshot")
        self.receipt = {
            "source_id": "operator", "source_url": "https://agency.example/canal",
            "title": "Canal", "publisher": "Agency", "retrieved_at_utc": "2026-10-20T00:00:00Z",
            "status": "verified_selected_metadata", "original_document_sha256": "same-body",
            "excerpts": self.rules["sources"][0]["excerpts"], "missing_excerpt_ids": [],
        }

    def refresh(self):
        output = io.StringIO()
        with patch("data.usgs_water.local_review.RULES", self.rules_path), \
                patch("data.usgs_water.local_review.acquire_source", return_value=self.receipt), \
                patch("data.usgs_water.refresh.retain_code"), redirect_stdout(output):
            directory = refresh_local_review(self.root)
        self.assertEqual((self.root / "observations.json").read_bytes(), b"unchanged-current-snapshot")
        self.assertFalse((self.root / "observations").exists())
        return directory, output.getvalue()

    def test_refresh_publishes_manifest_bound_audit_and_latest_copy(self):
        directory, output = self.refresh()
        _, manifest = archive.open_generation(self.root, "local_review")
        saved = archive.read_json(directory / "source_rule_audit.json")
        self.assertIn("source_rule_audit.json", manifest["files"])
        self.assertEqual(saved, archive.read_json(self.root / "source_rule_audit.json"))
        self.assertEqual(saved["summary"], manifest["source_rule_audit_summary"])
        self.assertIn("Source-rule audit: 0 encoding flags", output)
        self.assertEqual(read_csv(directory / "relationships/station_local_links.csv"), [])
        replay = audit(self.root, self.rules_path)
        self.assertEqual(saved["summary"], replay["summary"])

    def test_encoding_and_identical_body_mismatch_are_flagged_without_routing(self):
        self.refresh()
        self.rules["sources"][0]["excerpts"][0]["text"] = "District\u00e2\u20ac\u2122s canal"
        archive.write_json(self.rules_path, self.rules)
        self.receipt = {**self.receipt, "status": "selected_metadata_changed",
                        "excerpts": [], "missing_excerpt_ids": ["head"]}
        directory, output = self.refresh()
        saved = archive.read_json(directory / "source_rule_audit.json")
        self.assertEqual(saved["summary"]["encoding_findings"], 1)
        self.assertEqual(saved["summary"]["current_same_body_discrepancy_sources"], ["operator"])
        self.assertIn("WARNING encoding:", output)
        self.assertIn("WARNING current_same_body_discrepancy_sources: operator", output)
        decision = read_csv(directory / "relationships/station_local_review.csv")[0]
        self.assertEqual(decision["network_address_status"], "unresolved")
        self.assertEqual(decision["routing_supported"], "False")
        self.assertEqual(read_csv(directory / "relationships/station_local_links.csv"), [])

    def test_audit_failure_leaves_active_pointer_and_latest_copy_unchanged(self):
        self.refresh()
        pointer = (self.root / "local_review.json").read_bytes()
        latest = (self.root / "source_rule_audit.json").read_bytes()
        with patch("data.usgs_water.audit_source_rules.audit_generation", side_effect=ValueError("audit failure")):
            with self.assertRaisesRegex(ValueError, "audit failure"):
                self.refresh()
        self.assertEqual((self.root / "local_review.json").read_bytes(), pointer)
        self.assertEqual((self.root / "source_rule_audit.json").read_bytes(), latest)
        self.assertEqual((self.root / "observations.json").read_bytes(), b"unchanged-current-snapshot")

    def test_invalid_utf8_stops_before_acquisition(self):
        self.refresh()
        pointer = (self.root / "local_review.json").read_bytes()
        self.rules_path.write_bytes(b'{"text":"\x92"}')
        with patch("data.usgs_water.local_review.RULES", self.rules_path), \
                patch("data.usgs_water.local_review.acquire_source") as fetch:
            with self.assertRaises(UnicodeDecodeError):
                refresh_local_review(self.root)
            fetch.assert_not_called()
        self.assertEqual((self.root / "local_review.json").read_bytes(), pointer)

    def test_recovered_old_mismatch_is_history_not_current_alert(self):
        self.receipt = {**self.receipt, "status": "selected_metadata_changed",
                        "excerpts": [], "missing_excerpt_ids": ["head"]}
        self.refresh()
        self.receipt = {**self.receipt, "status": "verified_selected_metadata",
                        "excerpts": self.rules["sources"][0]["excerpts"], "missing_excerpt_ids": []}
        directory, output = self.refresh()
        saved = archive.read_json(directory / "source_rule_audit.json")
        self.assertEqual(saved["summary"]["current_same_body_discrepancy_sources"], [])
        self.assertEqual(saved["summary"]["historical_comparison_count"], 1)
        self.assertNotIn("WARNING", output)

    def test_all_mode_reaches_the_same_audited_refresh(self):
        from data.usgs_water.refresh import main
        with ExitStack() as stack:
            for name in ("refresh.refresh_inventory", "refresh.refresh_observations",
                         "network.refresh_network", "routing.refresh_routing"):
                stack.enter_context(patch("data.usgs_water." + name))
            stack.enter_context(patch("data.usgs_water.refresh.retain_code"))
            stack.enter_context(patch("data.usgs_water.local_review.RULES", self.rules_path))
            stack.enter_context(patch("data.usgs_water.local_review.acquire_source", return_value=self.receipt))
            stack.enter_context(patch("sys.argv", ["refresh", "--mode", "all", "--directory", str(self.root)]))
            stack.enter_context(redirect_stdout(io.StringIO()))
            main()
        directory, _ = archive.open_generation(self.root, "local_review")
        self.assertTrue((directory / "source_rule_audit.json").exists())
        self.assertEqual((self.root / "observations.json").read_bytes(), b"unchanged-current-snapshot")

    def test_resume_audits_reused_receipts_and_pins_history(self):
        first, _ = self.refresh()
        original = archive.read_json(first / "source_rule_audit.json")
        with patch("data.usgs_water.audit_source_rules.audit_generation", side_effect=ValueError("interrupt")):
            with self.assertRaisesRegex(ValueError, "interrupt"):
                self.refresh()
        pending = next((self.root / "local_review").glob(".pending-*"))
        with patch("data.usgs_water.local_review.RULES", self.rules_path), \
                patch("data.usgs_water.local_review.acquire_source") as fetch, \
                patch("data.usgs_water.refresh.retain_code"), redirect_stdout(io.StringIO()):
            resumed = refresh_local_review(self.root, pending)
            fetch.assert_not_called()
        self.assertTrue((resumed / "source_rule_audit.json").exists())
        replay = audit_generation(self.root, first, original["local_review_generation"],
                                  original["rules_sha256"], original["history_pointers"])
        comparable = lambda r: {k: v for k, v in r.items() if k != "audited_at_utc"}
        self.assertEqual(comparable(original), comparable(replay))


if __name__ == "__main__":
    unittest.main()
