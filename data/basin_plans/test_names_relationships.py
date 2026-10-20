"""Exercise actual named records, tributary associations, scoped joins, and hierarchy decoding."""

import gzip
import hashlib
import json
from pathlib import Path
import unittest

import names
import organize
import refresh
import relationships
from test_organize import make_snapshot, active_review, read_catalog
from test_refresh import temporary_directory


def populate(source, manifest, index, attributes, table=False):
    """Install complete small record batches with genuine ID and checksum evidence."""
    entry = manifest["datasets"][index]
    entry["kind"] = "table" if table else "spatial"
    fields = sorted({field for row in attributes for field in row})
    entry["object_id_field"] = "OID"
    features = [{"attributes": row} if table else
                {"type": "Feature", "properties": row, "geometry": {"type": "Point", "coordinates": [-122, 38]}}
                for row in attributes]
    raw = refresh.json_bytes({"features": features})
    base = Path(entry["path"]).parent
    chunk_path = (base / "raw/batch.json.gz").as_posix()
    target = source / chunk_path
    target.parent.mkdir(parents=True)
    target.write_bytes(gzip.compress(raw))
    entry["chunks"] = [{"path": chunk_path, "count": len(features),
                        "raw_sha256": hashlib.sha256(raw).hexdigest(), **refresh.digest_file(target)}]
    evidence_path = (base / "ids_after.json").as_posix()
    refresh.write_json(source / evidence_path, {"objectIds": [row["OID"] for row in attributes]})
    entry["id_evidence_path"] = evidence_path
    entry["record_count"] = len(features)
    (source / entry["path"]).write_bytes(gzip.compress(refresh.json_bytes(
        {"rows": attributes} if table else {"type": "FeatureCollection", "features": features})))
    entry.update(refresh.digest_file(source / entry["path"]))
    refresh.write_json(source / entry["metadata_path"], {"fields": [{"name": field} for field in fields]})


def select_fixture(root, source, manifest):
    """Finalize the fixture manifest after all batches and metadata are populated."""
    manifest["files"] = {path.relative_to(source).as_posix(): refresh.digest_file(path)
                         for path in source.rglob("*") if path.is_file() and path.name != "manifest.json"}
    refresh.write_json(source / "manifest.json", manifest)
    refresh.write_json(root / "sources.json", {"snapshot_id": manifest["snapshot_id"],
                       "manifest_path": f"snapshots/{manifest['snapshot_id']}/manifest.json",
                       "manifest_sha256": refresh.digest_file(source / "manifest.json")["sha256"]})


class NamedRelationshipTests(unittest.TestCase):
    def test_names_tributaries_and_complete_membership(self):
        with temporary_directory() as temp:
            root = Path(temp)
            source, manifest = make_snapshot(root, "names", [("regions/02_san_francisco_bay", "BasinPlanLines")])
            rows = [
                {"OID": 1, "WB_NAME": "San Pablo Creek", "GNIS_NAME": "San Pablo Creek", "PARENT_WB": None},
                {"OID": 2, "WB_NAME": "Small Creek", "GNIS_NAME": "Small Creek", "PARENT_WB": "San Pablo Creek", "TRIB_METHOD": "Trace", "TRIB_EXCLUSION": "retain this note", "WBID_T": "Trib"},
                {"OID": 3, "WB_NAME": None, "GNIS_NAME": None, "PARENT_WB": "San Pablo Creek", "WBID_T": "Trib"},
                {"OID": 4, "WB_NAME": "Other Creek", "PARENT_WB": "Missing River"},
                {"OID": 5, "WB_NAME": "undefined", "PARENT_WB": None},
                {"OID": 6, "WB_NAME": None, "PARENT_WB": None},
            ]
            populate(source, manifest, 0, rows)
            select_fixture(root, source, manifest)
            organize.organize_active(root)
            matches = names.search_names("san PABLO creek", root, exact=True, region="2", name_field="wb_name")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["sample_object_ids"], [1])
            self.assertEqual([row["object_id"] for row in names.matching_records(matches, root)], [1])
            self.assertEqual(names.search_names("San Pablo", root, region="3"), [])
            self.assertEqual(len(names.search_names("San Pablo Creek", root, exact=True,
                                                   category="san_francisco_bay", name_field="WB_NAME")), 1)
            links = names.search_waterway_links("San Pablo Creek", root, exact=True, direction="children")
            self.assertEqual(len(links), 2)
            self.assertEqual({row["object_id"] for row in names.linked_records(links, root)}, {2, 3})
            self.assertTrue(all(row["resolution_status"] == "one_candidate_group" for row in links))
            self.assertIn("retain this note", {row["trib_exclusion"] for row in links})
            unresolved = names.search_waterway_links("Missing River", root)
            self.assertEqual(unresolved[0]["resolution_status"], "unresolved_parent_name")
            review = active_review(root)
            self.assertEqual(len(read_catalog(review / "regions/02_san_francisco_bay/waterway_links.csv")), 3)
            coverage = json.loads((review / "name_coverage.json").read_bytes())[0]
            self.assertEqual(coverage["records_with_no_name"], 1)
            self.assertEqual(coverage["records_with_only_placeholder_names"], 1)
            organize.verify_organization(root)

    def test_key_joins_missing_keys_and_ambiguous_groups(self):
        with temporary_directory() as temp:
            root = Path(temp)
            category = "regions/02_san_francisco_bay"
            source, manifest = make_snapshot(root, "joins", [(category, name) for name in
                                              ("BasinPlanLines", "BPLinesDiss", "WB_BenUses", "ReachcodeTable")])
            populate(source, manifest, 0, [{"OID": 1, "wb_name": "Creek", "wbf_id": 7, "wb_refkey": "001"},
                                          {"OID": 2, "wb_name": "Creek", "wbf_id": 7, "wb_refkey": "001"},
                                          {"OID": 3, "wb_name": "No key", "wbf_id": None, "wb_refkey": None}])
            populate(source, manifest, 1, [{"OID": 11, "wbf_id": 7.0, "wb_refkey": "001"},
                                          {"OID": 12, "wbf_id": 7, "wb_refkey": "001"}])
            populate(source, manifest, 2, [{"OID": 21, "wbf_id": 7, "bu_code": "COLD", "bu_name": "Cold habitat"},
                                          {"OID": 22, "wbf_id": 7.0, "bu_code": "WARM", "bu_name": "Warm habitat"}], True)
            populate(source, manifest, 3, [{"OID": 31, "WBREFKEY": "001", "REACHCODE": "000123"},
                                          {"OID": 32, "WBREFKEY": "1", "REACHCODE": "000456"}], True)
            select_fixture(root, source, manifest)
            organize.organize_active(root)
            review = active_review(root)
            uses = read_catalog(review / "relationships/beneficial_uses.csv")
            matched = next(row for row in uses if row["source_dataset"] == "example/0" and row["status"] == "matched_key_group")
            self.assertEqual((matched["source_records"], matched["target_records"]), ("2", "2"))
            members = list(relationships.read_members(review / "relationships" / matched["target_members_path"],
                                                       matched["target_fields"], matched["target_key_json"]))
            self.assertEqual({row["bu_code"] for row in members}, {"COLD", "WARM"})
            self.assertTrue(any(row["status"] == "missing_key_no_join" for row in uses))
            grouped = read_catalog(review / "relationships/segment_groups.csv")
            self.assertTrue(any(row["status"] == "ambiguous_target_records" for row in grouped))
            reaches = read_catalog(review / "relationships/hydrography_reachcodes.csv")
            self.assertTrue(any(row["target_key_json"] == '["1"]' and row["status"] == "unmatched_target_key" for row in reaches))
            organize.verify_organization(root)

    def test_calwater_codes_include_two_digit_regions(self):
        with temporary_directory() as temp:
            root = Path(temp)
            source, manifest = make_snapshot(root, "calwater", [(organize.CALWATER, "CalWater_Hydrologic_Unit"),
                                                                  (organize.CALWATER, "CalWater_Hydrologic_PW")])
            populate(source, manifest, 0, [{"OID": 1, "rbu": 10123, "huname": "Example Unit"}])
            populate(source, manifest, 1, [{"OID": 2, "rbuaspw": 10123000201.0, "first_cdfpwsname": "Example Creek"},
                                          {"OID": 3, "rbuaspw": 99999000201, "first_cdfpwsname": "Unmatched Creek"}])
            select_fixture(root, source, manifest)
            organize.organize_active(root)
            rows = read_catalog(active_review(root) / "relationships/calwater_hierarchy.csv")
            self.assertTrue(any(row["target_key_json"] == "[10123]" and row["status"] == "verified_code_parent" for row in rows))
            self.assertTrue(any(row["status"] == "unmatched_parent_code" for row in rows))
            self.assertEqual(len(names.search_names("Example Creek", root, category="calwater")), 1)
            organize.verify_organization(root)


if __name__ == "__main__":
    unittest.main()
