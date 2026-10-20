"""Offline regression tests for archive completeness and publication boundaries."""

import gzip
import json
from pathlib import Path
from contextlib import contextmanager
import shutil
from uuid import uuid4
import unittest
from unittest.mock import patch

import reference
import refresh


@contextmanager
def temporary_directory():
    """Use inherited workspace ACLs for portable Windows test directories."""
    root = Path(__file__).resolve().parent
    path = root / (".test-refresh-" + uuid4().hex)
    path.mkdir()
    try:
        yield str(path)
    finally:
        if path.resolve().is_relative_to(root):
            shutil.rmtree(path)


class DownloadTests(unittest.TestCase):
    def test_regional_categories(self):
        self.assertEqual(refresh.category("San Francisco Bay Basin Plan"), "regions/02_san_francisco_bay")
        self.assertEqual(refresh.category("Central Valley Tulare Basin Plan"), "regions/05_central_valley/tulare")
        self.assertEqual(refresh.category("Central Valley Sacramento and San Joaquin"),
                         "regions/05_central_valley/sacramento_san_joaquin")
        self.assertEqual(refresh.category("California Basin Plan Beneficial Uses"), "statewide")
        self.assertEqual(refresh.category("CalWater Watersheds (v.2.2.1)"), "hydrologic_boundaries/calwater_2_2_1")

    def test_nested_operational_layers_exclude_basemap(self):
        document = {"operationalLayers": [{"title": "group", "layers": [{"itemId": "boundary"}]}],
                    "tables": [{"itemId": "uses"}], "baseMap": {"baseMapLayers": [{"itemId": "tiles"}]}}
        self.assertEqual([x.get("itemId") for x in refresh.operational_layers(document)],
                         [None, "boundary", "uses"])

    def test_exact_ids_not_just_count(self):
        for features in ([{"attributes": {"OID": 1}}, {"attributes": {"OID": 1}}],
                         [{"attributes": {"OID": 1}}, {"attributes": {"OID": 3}}]):
            with self.assertRaises(ValueError):
                refresh.validate_batch({"features": features}, [1, 2], "OID", False)

    def test_truncation_and_error_envelopes(self):
        with self.assertRaises(ValueError):
            refresh.validate_batch({"features": [], "exceededTransferLimit": True}, [], "OID", False)
        with self.assertRaises(ValueError):
            refresh.decode_json(b'{"error":{"code":500,"message":"failure"}}')

    def test_null_geometry_and_table_attributes_preserved(self):
        feature = {"type": "Feature", "properties": {"OID": 1, "code": "0012", "note": None}, "geometry": None}
        result = refresh.validate_batch({"type": "FeatureCollection", "features": [feature]}, [1], "OID", True)
        self.assertEqual(result, [feature])

    def test_path_escape(self):
        with temporary_directory() as temp:
            with self.assertRaises(ValueError):
                refresh.safe_path(Path(temp), "../outside")
            with self.assertRaises(ValueError):
                reference.safe_path(Path(temp), "../outside")

    def test_batched_download_and_offline_records(self):
        with temporary_directory() as temp:
            root = Path(temp)
            archive = refresh.Archive(root)
            item = {"id": "example", "title": "San Diego Basin Plan", "url": "https://example.invalid/FeatureServer"}
            layer = {"id": 4, "name": "related", "type": "Table"}

            def respond(url, parameters=None):
                if parameters is None:
                    return refresh.json_bytes({"type": "Table", "maxRecordCount": 2,
                                               "fields": [{"name": "OID", "type": "esriFieldTypeOID"}]})
                if "returnCountOnly" in parameters:
                    return b'{"count":3}'
                if "returnIdsOnly" in parameters:
                    return b'{"objectIds":[3,1,2]}'
                return refresh.json_bytes({"features": [{"attributes": {"OID": int(i), "value": "001"}}
                                                          for i in parameters["objectIds"].split(",")]})

            with patch.object(refresh, "request", side_effect=respond):
                entry = refresh.download_layer(archive, item, layer)
            self.assertEqual(entry["record_count"], 3)
            self.assertEqual(len(entry["chunks"]), 2)
            with patch.object(refresh, "request", side_effect=respond) as remote:
                entry = refresh.download_layer(archive, item, layer)
                self.assertFalse(any("objectIds" in (call.args[1] or {})
                                     for call in remote.call_args_list if len(call.args) > 1))
            # Missing output is rebuilt from verified batches without redownloading records.
            (root / entry["path"]).unlink()
            with patch.object(refresh, "request", side_effect=respond) as remote:
                entry = refresh.download_layer(archive, item, layer)
                self.assertFalse(any("objectIds" in (call.args[1] or {})
                                     for call in remote.call_args_list if len(call.args) > 1))
            with gzip.open(root / entry["path"], "rt", encoding="utf-8") as stream:
                rows = json.load(stream)["rows"]
            self.assertEqual([r["OID"] for r in rows], [1, 2, 3])
            self.assertEqual(rows[0]["value"], "001")

            manifest = {"complete": True, "snapshot_id": "test", "datasets": [entry],
                        "files": {p.relative_to(root).as_posix(): refresh.digest_file(p)
                                  for p in root.rglob("*") if p.is_file()}}
            refresh.write_json(root / "manifest.json", manifest)
            refresh.write_json(root / "sources.json", {"snapshot_id": "test", "manifest_path": "manifest.json",
                                "manifest_sha256": refresh.digest_file(root / "manifest.json")["sha256"]})
            self.assertEqual(list(reference.iter_records(entry["key"], root)), rows)
            reference.verify_files(root)
            (root / entry["chunks"][0]["path"]).write_bytes(b"damaged")
            with self.assertRaises(ValueError):
                list(reference.iter_records(entry["key"], root))

    def test_failure_preserves_active_pointer(self):
        with temporary_directory() as temp:
            root = Path(temp)
            pointer = root / "sources.json"
            pointer.write_bytes(b"previous generation")
            with patch.object(refresh, "discover", side_effect=ValueError("offline")):
                with self.assertRaises(ValueError):
                    refresh.refresh(root)
            self.assertEqual(pointer.read_bytes(), b"previous generation")
            self.assertFalse((root / ".refresh.lock").exists())

    def test_failed_item_prevents_publication_after_downloads(self):
        with temporary_directory() as temp:
            root = Path(temp)
            (root / "sources.json").write_bytes(b"last good snapshot")
            item = {"id": "example", "title": "North Coast data", "type": "File Geodatabase"}
            with patch.object(refresh, "discover", return_value=[item]), \
                 patch.object(refresh, "archive_item", side_effect=ValueError("broken archive")), \
                 patch.object(refresh, "request", return_value=b"<html></html>"):
                with self.assertRaises(RuntimeError):
                    refresh.refresh(root)
            self.assertEqual((root / "sources.json").read_bytes(), b"last good snapshot")
            report = json.loads(next(root.glob("snapshots/.pending-*/manifest.json")).read_bytes())
            self.assertFalse(report["complete"])
            self.assertEqual(report["errors"][0]["error"], "broken archive")

    def test_invalid_zip_is_not_cached_as_success(self):
        with temporary_directory() as temp:
            archive = refresh.Archive(Path(temp))
            with patch.object(refresh, "request", return_value=b"<html>failed</html>"):
                with self.assertRaises(refresh.zipfile.BadZipFile):
                    archive.fetch_binary("native/example.zip", "https://example.invalid/file", True)
            self.assertFalse((Path(temp) / "native/example.zip.receipt.json").exists())

    def test_changing_membership_rejects_dataset(self):
        with temporary_directory() as temp:
            archive = refresh.Archive(Path(temp))
            item = {"id": "example", "title": "California Basin Plan", "url": "https://example.invalid/MapServer"}
            metadata = {"type": "Table", "fields": [{"name": "OID", "type": "esriFieldTypeOID"}]}
            with patch.object(archive, "fetch_json", return_value=metadata), \
                 patch.object(refresh, "object_ids", side_effect=[[], [1]]):
                # Metadata normally creates the containing directory.
                (Path(temp) / "statewide/services/example/00_table").mkdir(parents=True)
                with self.assertRaises(ValueError):
                    refresh.download_layer(archive, item, {"id": 0, "name": "table", "type": "Table"})
            self.assertFalse(any(Path(temp).rglob("dataset.json")))


if __name__ == "__main__":
    unittest.main()
