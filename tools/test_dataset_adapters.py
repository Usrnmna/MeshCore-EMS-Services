"""Offline acquisition and validation regressions for independent data installers."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dataset_adapters", ROOT / "installers/datasets/adapters.py")
adapters = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapters)


def write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def point_collection():
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "id": 1,
             "properties": {}, "geometry": {"type": "Point", "coordinates": [-122, 38]}}]}


def gis_seed(directory, dataset="ebmud"):
    """Produce all required layer identities with independently hashed fixture bytes."""
    layers = adapters.EBMUD_LAYERS if dataset == "ebmud" else adapters.PARK_LAYERS
    entries, files = {}, {}
    for name in layers:
        path = directory / (name + ".geojson")
        write(path, point_collection())
        metadata = {"sha256": adapters.digest(path), "byte_count": path.stat().st_size}
        entries[name] = {"path": path.name, "feature_count": 1, **metadata}
        files[path.name] = metadata
    write(directory / "sources.json", {"datasets": entries, "files": files})


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payload = self.root / "payload"
        self.payload.mkdir()
        self.previous = self.root / "previous"
        self.previous.mkdir()
        (self.previous / "valid.txt").write_text("last validated data", encoding="utf-8")
        self.candidate = self.root / "candidate"

    def test_network_failure_changes_only_candidate(self):
        gis_seed(self.previous)
        original = {str(path.relative_to(self.previous)): path.read_bytes()
                    for path in self.previous.rglob("*") if path.is_file()}

        def interrupted(*args):
            (self.candidate / "trails.geojson").write_text("truncated", encoding="utf-8")
            raise TimeoutError("source unavailable")

        with patch.object(adapters, "worker", side_effect=interrupted):
            with self.assertRaises(TimeoutError):
                adapters.acquire("ebmud", self.candidate, self.payload, {}, self.previous, update=True)
        self.assertEqual(original, {str(path.relative_to(self.previous)): path.read_bytes()
                                   for path in self.previous.rglob("*") if path.is_file()})
        self.assertTrue((self.candidate / "trails.geojson").exists())

    def test_disk_full_during_copy_preserves_original(self):
        with patch.object(adapters.shutil, "copy2", side_effect=OSError("No space left")):
            with self.assertRaises(OSError):
                adapters.acquire("ebmud", self.candidate, self.payload, {}, self.previous)
        self.assertEqual((self.previous / "valid.txt").read_text(), "last validated data")

    def test_existing_legacy_install_is_imported_without_network_or_seed_downgrade(self):
        with patch.object(adapters, "worker") as worker:
            adapters.acquire("wildfire", self.candidate, self.payload, {}, self.previous)
        worker.assert_not_called()
        self.assertEqual((self.candidate / "valid.txt").read_bytes(), (self.previous / "valid.txt").read_bytes())

    def test_rejects_candidate_overlapping_previous_or_dependency(self):
        for destination in (self.previous, self.previous / "candidate", self.root):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                adapters.acquire("basin_plans", destination, self.payload, {}, self.previous)
        with self.assertRaises(ValueError):
            adapters.acquire("flood_impacts", self.previous, self.payload, {"basin_plans": self.previous})

    def test_curated_update_uses_supplied_seed(self):
        seed = self.payload / "seeds/landslide"
        seed.mkdir(parents=True)
        (seed / "review.txt").write_text("new reviewed catalog", encoding="utf-8")
        with patch.object(adapters, "worker") as worker:
            adapters.acquire("landslide", self.candidate, self.payload, {}, self.previous, update=True)
        worker.assert_not_called()
        self.assertEqual((self.candidate / "review.txt").read_text(), "new reviewed catalog")
        self.assertTrue((self.previous / "valid.txt").exists())

    def test_gis_checksum_empty_and_missing_layers_rejected(self):
        for dataset in ("ebmud", "california_state_parks"):
            directory = self.root / dataset
            gis_seed(directory, dataset)
            adapters._validate_gis(dataset, directory)
            manifest = adapters.read_json(directory / "sources.json")
            name = next(iter(manifest["datasets"]))
            entry = manifest["datasets"][name]
            path = directory / entry["path"]
            path.write_text("broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                adapters._validate_gis(dataset, directory)
            write(path, {"type": "FeatureCollection", "features": []})
            entry.update(sha256=adapters.digest(path), byte_count=path.stat().st_size, feature_count=0)
            write(directory / "sources.json", manifest)
            with self.assertRaises(ValueError):
                adapters._validate_gis(dataset, directory)
            del manifest["datasets"][name]
            write(directory / "sources.json", manifest)
            with self.assertRaisesRegex(ValueError, "layers"):
                adapters._validate_gis(dataset, directory)

    def test_geojson_http_200_error_and_truncation_rejected(self):
        path = self.root / "response.geojson"
        for document in ({"error": {"code": 500}},
                         {**point_collection(), "exceededTransferLimit": True}):
            write(path, document)
            with self.assertRaises(ValueError):
                adapters.geojson(path)

    def test_manifest_paths_cannot_escape_collection(self):
        for path in ("../previous/valid.txt", str(self.previous / "valid.txt")):
            with self.assertRaises(ValueError):
                adapters.safe_path(self.payload, path)

    def test_satellite_warning_status_is_failure(self):
        with patch.object(adapters.subprocess, "run", side_effect=subprocess.CalledProcessError(2, ["refresh"])):
            with self.assertRaises(subprocess.CalledProcessError):
                adapters.run_script(self.payload, "satellite_database/satellite_db.py", "refresh")
        write(self.previous / "coverage.json", {"warnings": ["orbit server unavailable"]})
        with self.assertRaisesRegex(ValueError, "source failure"):
            adapters._validate_satellites(self.previous)

    def test_satellite_empty_source_is_not_hidden_by_old_database(self):
        write(self.previous / "coverage.json", {"warnings": [], "source_satellites": 0})
        with self.assertRaisesRegex(ValueError, "Empty satellite"):
            adapters._validate_satellites(self.previous)

    def test_basin_resume_passes_native_snapshot_identifier(self):
        pending = self.candidate / "snapshots/.pending-retry123"
        pending.mkdir(parents=True)
        with patch.object(adapters, "run_script") as runner:
            adapters.acquire("basin_plans", self.candidate, self.payload, {}, update=True, resume=True)
        self.assertEqual(runner.call_args.args[-2:], ("--resume", "retry123"))

    def test_partial_basin_discovery_cannot_replace_complete_previous(self):
        def snapshot(directory, keys, items):
            manifest = {"snapshot_id": "fixture", "complete": True,
                        "datasets": [{"key": key} for key in keys],
                        "items": [{"id": key} for key in items]}
            write(directory / "manifest.json", manifest)
            write(directory / "sources.json", {"snapshot_id": "fixture", "manifest_path": "manifest.json",
                  "manifest_sha256": adapters.digest(directory / "manifest.json")})
        snapshot(self.previous, ["north/0", "south/0"], ["north", "south"])
        snapshot(self.candidate, ["north/0"], ["north"])
        with self.assertRaisesRegex(ValueError, "lost previously installed"):
            adapters._require_basin_coverage(self.candidate, self.previous)
        snapshot(self.candidate, ["north/0", "south/0", "new/0"], ["north", "south", "new"])
        adapters._require_basin_coverage(self.candidate, self.previous)

    def test_static_flood_validation_without_optional_observations_keeps_semantic_checks(self):
        from data.flood_impacts import archive
        from data.flood_impacts.validate import validate
        root = self.root / "flood"
        stage, identifier = archive.begin(root, "static")
        region = stage / "regions/test"
        archive.write_json(region / "waterways.geojson.gz", {"features": [
            {"properties": {"comid": "1", "fromnode": "a", "tonode": "b"}},
            {"properties": {"comid": "2", "fromnode": "wrong", "tonode": "c"}}]})
        for name in ("inundation_scenarios", "scenario_basin_portions"):
            archive.write_json(region / (name + ".geojson.gz"), {"features": []})
        for name in ("flow_connections", "gauge_reach_links", "scenario_basin_impacts"):
            archive.write_csv(region / "relationships" / (name + ".csv"), [], ["from_reach_id", "to_reach_id"])
        archive.publish(root, stage, identifier, "static", {"config": {"region": "test", "metric_crs": "EPSG:3310"}})
        result = validate(root, include_observations=False)
        self.assertIsNone(result["observation_generation"])
        self.assertEqual(result["network_reaches"], 2)
        with self.assertRaises(FileNotFoundError):
            validate(root)
        target, manifest = archive.open_generation(root)
        with patch("data.flood_impacts.validate.table", return_value=[{"from_reach_id": "1", "to_reach_id": "2"}]):
            with self.assertRaisesRegex(ValueError, "matching published nodes"):
                validate(root, include_observations=False)

    def test_water_failure_stops_before_index_and_preserves_dependency(self):
        dependency = self.root / "basin"
        dependency.mkdir()
        (dependency / "sources.json").write_text("pinned source", encoding="utf-8")
        calls = []

        def fail_observations(*args):
            mode = args[args.index("--mode") + 1]
            calls.append(mode)
            if mode == "observations":
                raise TimeoutError("measurement endpoint failed")

        with patch.object(adapters, "run_script", side_effect=fail_observations), patch.object(adapters, "worker") as worker:
            with self.assertRaises(TimeoutError):
                adapters.acquire("usgs_water", self.candidate, self.payload,
                                 {"basin_plans": dependency, "flood_impacts": self.previous})
        self.assertEqual(calls, ["inventory", "observations"])
        worker.assert_not_called()
        self.assertEqual((dependency / "sources.json").read_text(), "pinned source")
        self.assertEqual(adapters.read_json(self.candidate / "acquisition-progress.json")["completed"], ["inventory"])

    def test_water_resume_rejects_changed_dependency_before_acquisition(self):
        self.candidate.mkdir()
        write(self.candidate / "acquisition-progress.json", {"dependencies": {}, "completed": ["inventory"]})
        with patch.object(adapters, "run_script") as runner, self.assertRaisesRegex(ValueError, "changed dependencies"):
            adapters.acquire("usgs_water", self.candidate, self.payload,
                             {"basin_plans": self.previous, "flood_impacts": self.previous}, resume=True)
        runner.assert_not_called()

    def test_new_water_metadata_failure_is_rejected_despite_valid_manifest(self):
        write(self.previous / "review.json", {"source_status_counts": {"retrieval_failed": 1}})
        write(self.previous / "local_review.json", {"manifest_path": "review.json",
              "sha256": adapters.digest(self.previous / "review.json"),
              "byte_count": (self.previous / "review.json").stat().st_size})
        with self.assertRaisesRegex(ValueError, "providers failed"):
            adapters._require_water_sources(self.previous)
        write(self.previous / "review.json", {"source_status_counts": {"verified_selected_metadata": 4}})
        write(self.previous / "local_review.json", {"manifest_path": "review.json",
              "sha256": adapters.digest(self.previous / "review.json"),
              "byte_count": (self.previous / "review.json").stat().st_size})
        adapters._require_water_sources(self.previous)

    def test_real_curated_seeds_validate_offline(self):
        adapters.validate("landslide", ROOT / "meshcore_mqtt_service/data/landslide", ROOT, {})
        adapters.validate("wildfire", ROOT / "data/wildfire", ROOT, {})


if __name__ == "__main__":
    unittest.main()
