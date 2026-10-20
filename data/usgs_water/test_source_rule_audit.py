"""Checks for false encoding alarms and source-change attribution."""

import unittest

from data.usgs_water.audit_source_rules import encoding_findings, same_body_differences
from data.usgs_water.local_review import select_excerpts


class SourceRuleAuditTests(unittest.TestCase):
    def test_legitimate_unicode_is_preserved(self):
        self.assertEqual(encoding_findings({"text": "District\u2019s caf\u00e9 r\u00edo \u2013 canal"}), [])

    def test_cp1252_and_latin1_corruption_are_flagged(self):
        for codec in ("cp1252", "latin1"):
            with self.subTest(codec=codec):
                text = "District\u2019s".encode("utf-8").decode(codec)
                findings = encoding_findings({"text": text})
                self.assertIn("possible_utf8_misdecode_via_" + codec, findings[0]["reasons"])

    def test_replacement_and_hidden_control_are_flagged(self):
        findings = encoding_findings({"items": ["canal\ufffd", "river\x00name"]})
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[1]["path"], "$.items[1]")

    def test_same_body_with_changed_rule_is_not_agency_change(self):
        source = {"excerpts": [{"text": "District\u2019s"}]}
        old_source = {"excerpts": [{"text": "District\u00e2\u20ac\u2122s"}]}
        receipt = {"source_url": "https://agency.example/page", "original_document_sha256": "same",
                   "status": "verified_selected_metadata", "missing_excerpt_ids": []}
        old = {**receipt, "status": "selected_metadata_changed", "missing_excerpt_ids": ["head"]}
        rows = same_body_differences(source, receipt, [("old", old_source, old)])
        self.assertTrue(rows[0]["selection_rule_changed"])

    def test_missing_or_different_hash_does_not_imply_same_body(self):
        source = {"excerpts": []}
        receipt = {"source_url": "https://agency.example/page", "original_document_sha256": "",
                   "status": "retrieval_failed"}
        old = {**receipt, "status": "verified_selected_metadata"}
        self.assertEqual(same_body_differences(source, receipt, [("old", source, old)]), [])
        receipt["original_document_sha256"] = "new"
        old["original_document_sha256"] = "old"
        self.assertEqual(same_body_differences(source, receipt, [("old", source, old)]), [])

    def test_html_entities_and_layout_whitespace_do_not_cause_false_mismatch(self):
        source = {"format": "html", "excerpts": [
            {"id": "head", "text": "District\u2019s canal system"}]}
        found, missing = select_excerpts(
            b'<meta charset="utf-8"><p>District&rsquo;s&nbsp;canal\n\t system</p>', source)
        self.assertEqual(found, source["excerpts"])
        self.assertEqual(missing, [])

    def test_punctuation_changes_remain_explicit(self):
        source = {"format": "html", "excerpts": [
            {"id": "head", "text": "District\u2019s canal system"}]}
        found, missing = select_excerpts(b"<p>District's canal system</p>", source)
        self.assertEqual(found, [])
        self.assertEqual(missing, ["head"])


if __name__ == "__main__":
    unittest.main()
