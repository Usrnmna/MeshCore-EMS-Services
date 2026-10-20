"""Offline checks for regional organization, preservation, and refresh publication."""

import csv
import gzip
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import organize
import refresh
from test_refresh import temporary_directory


def make_snapshot(root, snapshot_id, specifications):
    """Create small archived exports with real checksums and source relationship metadata."""
    source = root / "snapshots" / snapshot_id
    source.mkdir(parents=True)
    entries = []
    for index, (category, name) in enumerate(specifications):
        base = f"{category}/services/example/{index}"
        data_path = base + "/features.geojson.gz"
        target = source / data_path
        target.parent.mkdir(parents=True)
        target.write_bytes(gzip.compress(b'{"type":"FeatureCollection","features":[]}'))
        metadata_path = base + "/metadata.json"
        refresh.write_json(source / metadata_path,
                           {"fields": [{"name": "OID"}, {"name": "wb_name"}],
                            "relationships": [{"keyField": "WBF_ID"}]})
        entries.append({"key": f"example/{index}", "name": name, "category": category, "kind": "spatial",
                        "path": data_path, "metadata_path": metadata_path, "record_count": 0,
                        "source_url": f"https://example.invalid/FeatureServer/{index}", **refresh.digest_file(target)})
    manifest = {"complete": True, "snapshot_id": snapshot_id, "datasets": entries, "items": [],
                "files": {path.relative_to(source).as_posix(): refresh.digest_file(path)
                          for path in source.rglob("*") if path.is_file()}}
    refresh.write_json(source / "manifest.json", manifest)
    refresh.write_json(root / "sources.json", {"snapshot_id": snapshot_id,
                       "manifest_path": f"snapshots/{snapshot_id}/manifest.json",
                       "manifest_sha256": refresh.digest_file(source / "manifest.json")["sha256"]})
    return source, manifest


def active_review(root):
    """Resolve the currently selected generated review directory."""
    return root / json.loads((root / "sources.json").read_bytes())["organization_path"]


def read_catalog(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class OrganizationTests(unittest.TestCase):
    def test_regions_plans_calwater_and_original_bytes(self):
        with temporary_directory() as temp:
            root = Path(temp)
            specifications = [("regions/02_san_francisco_bay", "BasinPlanLines"),
                              ("regions/05_central_valley/tulare", "WB_BenUses"),
                              ("regions/05_central_valley/sacramento_san_joaquin", "BasinPlanPolys")]
            specifications += [(organize.CALWATER, name) for name in organize.CALWATER_LEVELS]
            source, manifest = make_snapshot(root, "first", specifications)
            original_hashes = {path.relative_to(source): refresh.digest_file(path)
                               for path in source.rglob("*") if path.is_file()}
            organize.organize_active(root)
            review = active_review(root)
            result = organize.verify_organization(root)
            self.assertEqual(result["datasets"], 9)
            for region in organize.REGIONS:
                self.assertTrue((review / "regions" / region / "README.md").is_file())
                self.assertTrue((review / "regions" / region / "catalog.csv").is_file())
            central = read_catalog(review / "regions/05_central_valley/catalog.csv")
            self.assertEqual(len(central), 2)
            for folder, _ in organize.CALWATER_LEVELS.values():
                self.assertEqual(len(read_catalog(review / organize.CALWATER / folder / "catalog.csv")), 1)
            for path, evidence in original_hashes.items():
                self.assertEqual(refresh.digest_file(source / path), evidence)
            bay = review / "regions/02_san_francisco_bay/waterbodies/line_segments.geojson.gz"
            bay.write_bytes(b"manual edit to copy")
            self.assertEqual(refresh.digest_file(source / manifest["datasets"][0]["path"]),
                             original_hashes[Path(manifest["datasets"][0]["path"])])
            with self.assertRaises(ValueError):
                organize.verify_organization(root)

    def test_colliding_names_and_unknown_layers_are_all_retained(self):
        with temporary_directory() as temp:
            root = Path(temp)
            make_snapshot(root, "first", [("regions/01_north_coast", name) for name in
                                         ("BasinPlanLines", "BasinPlanLines", "New Layer", "new_layer")])
            organize.organize_active(root)
            rows = read_catalog(active_review(root) / "catalog.csv")
            self.assertEqual(len({row["data_path"].casefold() for row in rows}), 4)
            self.assertEqual(sum("unclassified" in row["data_path"] for row in rows), 2)
            self.assertTrue(all("WBF_ID" in row["review_notes"] for row in rows))
            organize.verify_organization(root)

    def test_rebuild_has_no_stale_layers_and_keeps_old_generation(self):
        with temporary_directory() as temp:
            root = Path(temp)
            make_snapshot(root, "first", [("regions/01_north_coast", "BasinPlanLines")])
            organize.organize_active(root)
            old = active_review(root)
            (old / "manual-notes.txt").write_text("retained", encoding="utf-8")
            make_snapshot(root, "second", [("regions/09_san_diego", "BasinPlanPolys")])
            organize.organize_active(root)
            new = active_review(root)
            self.assertNotEqual(old, new)
            self.assertTrue((old / "manual-notes.txt").is_file())
            self.assertEqual(read_catalog(new / "regions/01_north_coast/catalog.csv"), [])
            self.assertEqual(len(read_catalog(new / "regions/09_san_diego/catalog.csv")), 1)
            organize.verify_organization(root)

    def test_damaged_source_prevents_pointer_change(self):
        with temporary_directory() as temp:
            root = Path(temp)
            source, manifest = make_snapshot(root, "first", [("statewide", "Beneficial Use Lines")])
            before = (root / "sources.json").read_bytes()
            (source / manifest["datasets"][0]["path"]).write_bytes(b"bad data")
            with self.assertRaises(ValueError):
                organize.organize_active(root)
            self.assertEqual((root / "sources.json").read_bytes(), before)
            self.assertFalse((root / ".refresh.lock").exists())

    def test_refresh_requires_organization_before_publication(self):
        with temporary_directory() as temp:
            root = Path(temp)
            (root / "sources.json").write_bytes(b"previous active pointer")
            with patch.object(refresh, "discover", return_value=[]), \
                 patch.object(refresh, "request", return_value=b"<html></html>"), \
                 patch.object(organize, "build_organization", side_effect=OSError("copy failed")):
                with self.assertRaises(OSError):
                    refresh.refresh(root)
            self.assertEqual((root / "sources.json").read_bytes(), b"previous active pointer")
            self.assertEqual(len(list(root.glob("snapshots/.pending-*/manifest.json"))), 1)

    def test_refresh_publishes_matching_review_and_snapshot(self):
        with temporary_directory() as temp:
            root = Path(temp)
            with patch.object(refresh, "discover", return_value=[]), \
                 patch.object(refresh, "request", return_value=b"<html></html>"):
                refresh.refresh(root)
            self.assertTrue((root / "REVIEW.md").is_file())
            organize.verify_organization(root)


if __name__ == "__main__":
    unittest.main()
