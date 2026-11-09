"""Read-only dataset and cached-source status regression tests."""
from contextlib import closing
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("data_status", ROOT / "scripts" / "data_status.py")
data_status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(data_status)


class DataStatusTests(unittest.TestCase):
    def test_selections_and_receipt_date_ignore_failed_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); directory = root / ".datasets" / "ebmud" / "gen1"
            (directory / "content").mkdir(parents=True)
            (directory / "content" / "test.txt").write_bytes(b"test")
            record = {"path": ".datasets/ebmud/gen1/content", "receipt": ".datasets/ebmud/gen1/receipt.json"}
            receipt = {"schema": 1, "dataset": "ebmud", "path": record["path"],
                       "installed_at": "2024-01-02T03:00:00Z", "dependencies": {}, "files": {"test.txt": {"bytes": 4, "sha256": hashlib.sha256(b"test").hexdigest()}}}
            (directory / "receipt.json").write_text(json.dumps(receipt))
            reg = root / "datasets.json"
            reg.write_text(json.dumps({"schema": 1, "datasets": {"ebmud": {"active": record}}}))
            attempt = root / ".datasets" / "status"
            attempt.mkdir()
            (attempt / "ebmud.json").write_text(json.dumps({"result": "failed", "time": "2030-01-01T00:00:00Z"}))
            status = data_status.dataset_status("ebmud", root)
            self.assertIn("2024-01-02", status)
            self.assertNotIn("2030", status)
            self.assertIn("hashes checked", status)
            reg.write_text(json.dumps({"schema": 1, "datasets": {"ebmud": {"active": None}}}))
            self.assertIn("uninstalled", data_status.dataset_status("ebmud", root))
            reg.write_text("invalid")
            self.assertIn("invalid metadata", data_status.dataset_status("ebmud", root))

    def test_dependency_missing_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); directory = root / ".datasets" / "flood_impacts" / "g"
            (directory / "content").mkdir(parents=True)
            (directory / "content" / "test.txt").write_bytes(b"test")
            rec = {"path": ".datasets/flood_impacts/g/content", "receipt": ".datasets/flood_impacts/g/receipt.json"}
            receipt = {"schema": 1, "dataset": "flood_impacts", "path": rec["path"], "installed_at": "2024-01-02T00:00:00Z", "dependencies": {"basin_plans": {"path": "../outside", "receipt": "../outside"}}, "files": {"test.txt": {"bytes": 4, "sha256": hashlib.sha256(b"test").hexdigest()}}}
            (directory / "receipt.json").write_text(json.dumps(receipt))
            (root / "datasets.json").write_text(json.dumps({"schema": 1, "datasets": {"flood_impacts": {"active": rec}}}))
            self.assertIn("dependency unavailable", data_status.dataset_status("flood_impacts", root))

    def test_cache_stale_and_no_creation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MESHCORE_RUNTIME_DIR": temp, "MESHCORE_WILDFIRE_SETTINGS": "{}"}):
            path = Path(temp) / "wildfire.sqlite3"
            self.assertIn("unavailable", data_status.source_status("zones"))
            self.assertFalse(path.exists())
            with closing(sqlite3.connect(path)) as db:
                db.execute("PRAGMA user_version=1")
                db.execute("CREATE TABLE snapshots (source TEXT PRIMARY KEY, fetched REAL, error TEXT)")
                db.execute("INSERT INTO snapshots VALUES (?,?,?)", ("zones", 1, None))
                db.commit()
            self.assertIn("stale", data_status.source_status("zones"))
            self.assertIn("not initialized", data_status.source_status("alerts"))

    def test_cli_alias_and_reply_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "datasets.json").write_text(json.dumps({"schema": 1, "datasets": {"california_state_parks": {"active": None}}}))
            env = dict(os.environ, MESHCORE_DATA_DIR=temp, MESHCORE_SENDER="é" * 40)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/data_status.py"), "parks"], env=env, text=True, capture_output=True, check=True)
            self.assertIn("uninstalled", result.stdout)
            self.assertLessEqual(len(("@" + "é" * 40 + " " + result.stdout.strip()).encode()), 150)


    def test_hash_failure_and_bounded_verification(self):
        from data_reporting import Budget, IntegrityFailure, VerificationLimit
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); file = root / "value"
            file.write_bytes(b"bad!")
            expected = {"bytes": 4, "sha256": hashlib.sha256(b"good").hexdigest()}
            with self.assertRaises(IntegrityFailure):
                Budget().verify(root, "value", expected)
            budget = Budget(); budget.remaining = 1
            with self.assertRaises(VerificationLimit):
                budget.verify(root, "value", expected)

    def test_observation_time_overrides_recent_download(self):
        from data_reporting import observation_status
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            text = "time\n2000-01-01T00:00:00Z\n" + datetime.now(timezone.utc).isoformat() + "\ninvalid\n"
            raw = text.encode(); (root / "series_conditions.csv").write_bytes(raw)
            manifest = {"kind": "observations", "complete": True, "files": {"series_conditions.csv": {"byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}}
            raw = json.dumps(manifest).encode(); (root / "manifest.json").write_bytes(raw)
            (root / "observations.json").write_text(json.dumps({"manifest_path": "manifest.json", "byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}))
            with patch.dict(os.environ, {"MESHCORE_WATER_SETTINGS": "{}"}):
                output = observation_status(root, data_status.read_json)
            self.assertIn("1 fresh; 1 stale; 1 invalid", output)

    def test_custom_water_root_overrides_uninstalled_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); custom = root / "custom"; (custom / "usgs_water").mkdir(parents=True)
            managed = root / "managed"; managed.mkdir()
            (managed / "datasets.json").write_text(json.dumps({"schema": 1, "datasets": {"usgs_water": {"active": None}}}))
            with patch.dict(os.environ, {"MESHCORE_DATA_DIR": str(managed), "MESHCORE_WATER_SETTINGS": json.dumps({"data_directory": str(custom)})}):
                self.assertEqual(data_status.configured_directory("usgs_water"), custom / "usgs_water")

    def test_point_cache_reports_failures_and_preserves_database(self):
        import time
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MESHCORE_RUNTIME_DIR": temp, "MESHCORE_WATER_SETTINGS": "{}"}):
            path = Path(temp) / "water_current.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE current(key TEXT,fetched REAL,error TEXT)")
                db.executemany("INSERT INTO current VALUES(?,?,?)", [("PRIVATE_POINT", time.time(), None), ("old", 1, None), ("failed", time.time(), "SECRET_ERROR")])
                db.commit()
            before = path.read_bytes()
            output = data_status.point_cache_status("water")
            self.assertIn("1 fresh; 1 stale; 1 failed", output)
            self.assertNotIn("PRIVATE", output); self.assertNotIn("SECRET", output)
            self.assertEqual(before, path.read_bytes())



    def test_zero_length_files_obey_deadline(self):
        from data_reporting import Budget, VerificationLimit
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "empty").write_bytes(b"")
            budget = Budget(); budget.until = 0
            with self.assertRaises(VerificationLimit):
                budget.verify(root, "empty", {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()})

    def test_failed_wildfire_refresh_does_not_report_recent_cache_healthy(self):
        import time
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MESHCORE_RUNTIME_DIR": temp, "MESHCORE_WILDFIRE_SETTINGS": "{}"}):
            with closing(sqlite3.connect(Path(temp) / "wildfire.sqlite3")) as db:
                db.execute("PRAGMA user_version=1")
                db.execute("CREATE TABLE snapshots(source TEXT,fetched REAL,error TEXT)")
                db.execute("INSERT INTO snapshots VALUES(?,?,?)", ("fwf:STO", time.time(), "SECRET_PATH"))
                db.commit()
            output = data_status.source_status("fwf:sto")
            self.assertIn("refresh failed", output)
            self.assertNotIn("SECRET", output)
            self.assertNotIn("cached;", output)

    def test_reference_invalid_shapes_and_empty_inventory_do_not_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "manifest.json").write_text(json.dumps({"sha256": []}))
            from data_reporting import IntegrityFailure
            with self.assertRaises(IntegrityFailure):
                data_status.reference_status("landslide", root)
            (root / "sources.json").write_text(json.dumps({"datasets": {}}))
            self.assertIn("unverified", data_status.reference_status("ebmud", root))

    def test_satellite_typed_root_matches_catalog_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); shared = root / "shared"; shared.mkdir()
            (root / "satellite-settings.json").write_text(json.dumps({"database": str(shared / "satellites" / "satellites.sqlite3")}))
            (root / "config.json").write_text(json.dumps({"dataset_root": str(shared)}))
            (shared / "datasets.json").write_text(json.dumps({"schema": 1, "datasets": {"satellites": {"active": None}}}))
            with patch.object(data_status, "ROOT", root):
                self.assertEqual(data_status.reporting_root("satellites"), shared)
                self.assertIn("uninstalled", data_status.dataset_status("satellites"))

    def test_custom_water_path_ignores_broken_default_registry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); shared = root / "managed"; shared.mkdir()
            custom = root / "external"; (custom / "usgs_water").mkdir(parents=True)
            (shared / "datasets.json").write_text("broken")
            with patch.dict(os.environ, {"MESHCORE_DATA_DIR": str(shared), "MESHCORE_WATER_SETTINGS": json.dumps({"data_directory": str(custom)})}):
                output = data_status.dataset_status("usgs_water")
            self.assertIn("missing", output)
            self.assertNotIn("invalid metadata", output)


if __name__ == "__main__":
    unittest.main()
