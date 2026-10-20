"""Regression checks for local identities, retrieval failures and current-only selection."""

import copy
import unittest

from data.flood_impacts import archive
from data.usgs_water.local_review import RULES, derive, select_excerpts, source_alternatives, station_signature


class LocalReviewTests(unittest.TestCase):
    def setUp(self):
        self.sid = "USGS-11312672"
        self.station = {"properties": {"monitoring_location_name": "VICTORIA CANAL"},
                        "geometry": {"type": "Point", "coordinates": [-121.5, 37.8]}}
        self.excerpt = {"id": "alias", "text": "VCU 11312672"}
        self.source = {"id": "dwr", "url": "https://water.ca.gov/example",
                       "format": "html", "excerpts": [self.excerpt]}
        self.link = {"relationship_type": "published_station_alias", "target_namespace": "CDEC",
                     "target_id": "VCU", "target_name": "Victoria Canal", "source_id": "dwr",
                     "excerpt_ids": ["alias"]}
        self.rules = {"sources": [self.source], "stations": {self.sid: {
            "station_signature": station_signature(self.station), "finding": "Alias only.",
            "source_ids": ["dwr"], "links": [self.link]}}}
        self.receipt = {"source_id": "dwr", "source_url": self.source["url"],
                        "retrieved_at_utc": "2026-10-20T00:00:00Z",
                        "status": "verified_selected_metadata", "excerpts": [self.excerpt]}
        self.prior = {"station_id": self.sid, "station_name": "VICTORIA CANAL",
                      "status": "conflicting_agency_and_catalog_addresses"}

    def run_review(self):
        return derive([self.prior], {self.sid: self.station}, self.rules, [self.receipt])

    def test_exact_alias_has_no_routing(self):
        decisions, links = self.run_review()
        self.assertEqual(links[0]["target_id"], "VCU")
        self.assertFalse(links[0]["routing_supported"])
        self.assertEqual(decisions[0]["network_address_status"], "unresolved")
        self.assertEqual(decisions[0]["reach_id"], "")

    def test_changed_station_location_withholds_manual_link(self):
        self.station = copy.deepcopy(self.station)
        self.station["geometry"]["coordinates"][0] = -120
        decisions, links = self.run_review()
        self.assertEqual(links, [])
        self.assertEqual(decisions[0]["status"], "station_metadata_changed_requires_review")

    def test_historical_role_remains_dated_metadata_without_routing(self):
        self.link.update(relationship_type="documents_diversion_to",
                         source_vintage="1998", temporal_scope="historical_documented_role")
        decisions, links = self.run_review()
        self.assertEqual(links[0]["source_vintage"], "1998")
        self.assertEqual(links[0]["temporal_scope"], "historical_documented_role")
        self.assertFalse(links[0]["routing_supported"])
        self.assertEqual(decisions[0]["reach_id"], "")

    def test_old_and_dated_links_have_the_same_export_columns(self):
        original = self.run_review()[1][0]
        self.link.update(source_vintage="2023", temporal_scope="report_station_identifier")
        dated = self.run_review()[1][0]
        self.assertEqual(set(original), set(dated))
        self.assertEqual(original["temporal_scope"], "published_metadata_not_current_operation")

    def test_failed_source_cannot_promote_even_with_old_excerpts(self):
        self.receipt["status"] = "retrieval_failed"
        self.assertEqual(self.run_review()[1], [])

    def test_changed_source_withholds_partial_match(self):
        self.receipt["status"] = "selected_metadata_changed"
        self.assertEqual(self.run_review()[1], [])

    def test_name_only_cannot_authorize_alias(self):
        self.excerpt["text"] = "Victoria Canal VCU"
        with self.assertRaisesRegex(ValueError, "exact published"):
            self.run_review()

    def test_station_id_must_be_complete(self):
        self.excerpt["text"] = "VCU 113126720"
        with self.assertRaisesRegex(ValueError, "exact published"):
            self.run_review()

    def test_wrong_source_url_fails(self):
        self.receipt["source_url"] = "https://example.org"
        with self.assertRaisesRegex(ValueError, "another source"):
            self.run_review()

    def test_incomplete_verified_receipt_fails(self):
        self.receipt["excerpts"] = []
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.run_review()

    def test_new_station_remains_explicit(self):
        self.rules["stations"] = {}
        decisions, links = self.run_review()
        self.assertEqual(links, [])
        self.assertEqual(decisions[0]["status"], "local_source_review_required")

    def test_metadata_selector_excludes_adjacent_observations(self):
        found, missing = select_excerpts(
            b"<p>VCU 11312672</p><table><tr><td>2020-01-01</td><td>9.5 feet</td></tr></table>",
            self.source)
        self.assertEqual(found, [self.excerpt])
        self.assertEqual(missing, [])
        self.assertNotIn("9.5", str(found))

    def test_changed_literal_remains_missing(self):
        found, missing = select_excerpts(b"<p>VCU 11313240</p>", self.source)
        self.assertEqual(found, [])
        self.assertEqual(missing, ["alias"])

    def test_modesto_rules_preserve_verified_utf8_apostrophe(self):
        # An implicit Windows code-page read previously corrupted this rule while
        # the agency response remained byte-identical. Exercise the maintained
        # configuration and actual HTML selection together.
        rules = archive.read_json(RULES)
        source = next(row for row in rules["sources"] if row["id"] == "modesto_dam")
        literal = "the head of each District\u2019s canal system"
        self.assertEqual(source["excerpts"], [{"id": "canal_heads", "text": literal}])
        content = ('<meta charset="utf-8"><p>' + literal + '</p>').encode("utf-8")
        found, missing = select_excerpts(content, source)
        self.assertEqual(found, source["excerpts"])
        self.assertEqual(missing, [])

    def test_corrupted_unicode_rule_is_not_silently_normalized(self):
        literal = "the head of each District\u2019s canal system"
        corrupted = literal.encode("utf-8").decode("cp1252")
        source = {"format": "html", "excerpts": [{"id": "canal_heads", "text": corrupted}]}
        content = ('<meta charset="utf-8"><p>' + literal + '</p>').encode("utf-8")
        found, missing = select_excerpts(content, source)
        self.assertEqual(found, [])
        self.assertEqual(missing, ["canal_heads"])

    def test_verified_alternate_preserves_original_failure_without_station_link(self):
        original = {**self.receipt, "source_id": "unavailable", "status": "retrieval_failed",
                    "source_url": "https://water.ca.gov/unavailable", "excerpts": []}
        rules = {"source_alternatives": [{
            "original_source_id": "unavailable", "alternate_source_id": "dwr",
            "scope": "Facility description", "limitation": "No exact station key",
        }]}
        row = source_alternatives(rules, [original, self.receipt])[0]
        self.assertEqual(row["original_status"], "retrieval_failed")
        self.assertTrue(row["context_available"])
        self.assertFalse(row["station_match_supported"])
        self.assertFalse(row["routing_supported"])

    def test_failed_or_changed_alternative_does_not_supply_verified_context(self):
        rules = {"source_alternatives": [{
            "original_source_id": "dwr", "alternate_source_id": "alternate",
            "scope": "Facility description", "limitation": "No exact station key",
        }]}
        for status in ("retrieval_failed", "selected_metadata_changed"):
            with self.subTest(status=status):
                alternate = {**self.receipt, "source_id": "alternate", "status": status}
                row = source_alternatives(rules, [self.receipt, alternate])[0]
                self.assertFalse(row["context_available"])
                self.assertFalse(row["station_match_supported"])

    def test_source_without_station_key_is_only_context(self):
        self.rules["stations"][self.sid]["links"] = []
        self.excerpt["text"] = "Victoria Canal facility description"
        decisions, links = self.run_review()
        self.assertEqual(links, [])
        self.assertEqual(decisions[0]["status"], "local_context_only_routing_unresolved")


if __name__ == "__main__":
    unittest.main()
