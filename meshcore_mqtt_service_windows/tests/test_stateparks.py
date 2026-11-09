"""State Parks identity and entrance selection tests."""
import hashlib
import builtins
import contextlib
import io
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

from scripts import stateparks_lookup as parks
from scripts.command_dependencies import dependency_status
import responder


def feature(properties, geometry):
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def write_snapshot(root, data, repaired_ids=None):
    """Create a verified offline generation, including optional repair provenance."""
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "geojson_crs": "EPSG:4326", "datasets": {}, "files": {}}
    for key, oid in (("park_boundaries", "FID"), ("park_entry_points", "OBJECTID")):
        raw = json.dumps({"type": "FeatureCollection", "features": data[key]}).encode()
        (root / (key + ".json")).write_bytes(raw)
        manifest["datasets"][key] = {"path": key + ".json", "object_id_field": oid,
            "feature_count": len(data[key]), "byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if repaired_ids is not None:
        raw = json.dumps({"features": [{"object_id": ident} for ident in repaired_ids]}).encode()
        (root / "repair.json").write_bytes(raw)
        manifest["files"]["repair.json"] = {"byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        manifest["datasets"]["park_boundaries"]["geometry_repair"] = {
            "report_path": "repair.json", "repaired_feature_count": len(repaired_ids)}
    (root / "sources.json").write_text(json.dumps(manifest))
    return manifest


class StateParksTests(unittest.TestCase):
    def setUp(self):
        polygon = {"type": "Polygon", "coordinates": [[[-122, 38], [-121.9, 38], [-121.9, 38.1], [-122, 38.1], [-122, 38]]]}
        self.data = {"park_boundaries": [feature({"FID": 1, "UNITNBR": "007", "UNITNAME": "Sample Park", "SUBTYPE": "Park"}, polygon)],
                     "park_entry_points": [feature({"OBJECTID": 11, "UNIT_NBR": "007", "PARK_NAME": "Sample Park", "STREET_ADDRESS": "1 Road"}, {"type": "Point", "coordinates": [-122, 38]})]}

    def test_name_id_and_entrance(self):
        self.assertIn("unit 007", parks.lookup("statepark", "sample park", self.data))
        self.assertIn("unit 007", parks.lookup("statepark", "  SAMPLE   park ", self.data))
        self.assertIn("unit 007", parks.lookup("statepark", "id 007", self.data))
        self.assertIn("11", parks.lookup("entrance", "Sample Park", self.data))
        self.assertIn("38.00000,-122.00000", parks.lookup("entrance", "id 11", self.data))
        self.assertIn("No matching", parks.lookup("statepark", "id 7", self.data))

    def test_ambiguous_name_and_multiple_entrances(self):
        self.data["park_boundaries"].append(feature({"UNITNBR": "008", "UNITNAME": "Sample Park"}, None))
        self.assertIn("Ambiguous", parks.lookup("statepark", "Sample Park", self.data))
        self.data["park_entry_points"].append(feature({"OBJECTID": 12, "UNIT_NBR": "007"}, {"type": "Point", "coordinates": [-122, 38]}))
        self.assertIn("Ambiguous", parks.lookup("entrance", "unit 007", self.data))

    def test_proximity_and_invalid_geometry(self):
        self.assertIn("Boundary approx", parks.lookup("statepark", "near 38.2 -122", self.data))
        with self.assertRaises(ValueError):
            parks.lookup("statepark", "near 60 -122", self.data)
        self.data["park_entry_points"][0]["geometry"] = None
        with self.assertRaises(ValueError):
            parks.lookup("entrance", "id 11", self.data)

    def test_same_unit_multiple_features_and_blank_name(self):
        duplicate = feature({"FID": 2, "UNITNBR": "007", "UNITNAME": ""}, self.data["park_boundaries"][0]["geometry"])
        self.data["park_boundaries"].append(duplicate)
        self.assertIn("Sample Park", parks.lookup("statepark", "id 007", self.data))
        self.assertIn("Boundary approx", parks.lookup("statepark", "near 38.2 -122", self.data))

    def test_snapshot_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_snapshot(root, self.data)
            with patch.object(parks, "resolve", return_value=root):
                self.assertEqual(len(parks.load_snapshot()["park_boundaries"]), 1)
                (root / "park_boundaries.json").write_bytes(b"changed")
                with self.assertRaises(ValueError):
                    parks.load_snapshot()

    def test_ambiguity_includes_correct_selector_and_candidate_ids(self):
        self.data["park_boundaries"].append(feature({"FID": 2, "UNITNBR": "008", "UNITNAME": "Sample Park"}, None))
        for command, selector in (("statepark", "id"), ("entrance", "unit")):
            result = parks.lookup(command, "Sample Park", self.data)
            self.assertIn("!" + command + " " + selector, result)
            self.assertIn("007", result)
            self.assertIn("008", result)
        self.data["park_entry_points"].append(feature({"OBJECTID": 12, "UNIT_NBR": "007"}, None))
        result = parks.lookup("entrance", "unit 007", self.data)
        for value in ("!entrance id", "11", "12"):
            self.assertIn(value, result)

    def test_identity_and_help_do_not_require_geometry_libraries(self):
        real_import = builtins.__import__
        def without_geometry(name, *args, **kwargs):
            if name.split(".")[0] in {"shapely", "pyproj"}:
                raise ImportError("geometry unavailable")
            return real_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=without_geometry):
            self.assertIn("!statepark", parks.lookup("statepark", "help", {}))
            self.assertIn("007", parks.lookup("statepark", "id 007", self.data))
            self.assertIn("38.00000", parks.lookup("entrance", "id 11", self.data))

    def test_qualifiers_identity_and_distance_fit_long_sender(self):
        self.data["park_boundaries"][0]["properties"]["UNITNAME"] = "Long park name " * 20
        for sender in ("Alice", "a" * 80, "é" * 40):
            with patch.dict(os.environ, {"MESHCORE_SENDER": sender}):
                for command, query, required in (
                    ("statepark", "id 007", ("007", "ref")),
                    ("entrance", "id 11", ("11", "38.00000,-122.00000", "ref")),
                    ("statepark", "near 38.2 -122", ("007", "approx", "mi")),
                ):
                    result = parks.lookup(command, query, self.data)
                    tagged = responder.reply_parts(sender, result, max_parts=1)
                    self.assertEqual(len(tagged), 1)
                    self.assertLessEqual(len(tagged[0].encode()), 150)
                    self.assertNotIn("Unable to return", tagged[0])
                    for word in required:
                        self.assertIn(word, tagged[0].lower())

    def test_null_boundary_does_not_silently_claim_nearest(self):
        self.data["park_boundaries"].append(feature({"FID": 2, "UNITNBR": "008"}, None))
        with self.assertRaises(ValueError):
            parks.lookup("statepark", "near 38.2 -122", self.data)

    def test_blank_units_do_not_merge_tied_boundaries(self):
        self.data["park_boundaries"][0]["properties"]["UNITNBR"] = ""
        self.data["park_boundaries"].append(feature({"FID": 2, "UNITNBR": "", "UNITNAME": "Other"}, self.data["park_boundaries"][0]["geometry"]))
        self.assertIn("Multiple", parks.lookup("statepark", "near 38.2 -122", self.data))

    def test_numeric_unit_types_join_without_losing_zero_padding(self):
        self.data["park_boundaries"][0]["properties"]["UNITNBR"] = 7
        self.data["park_entry_points"][0]["properties"]["UNIT_NBR"] = "7"
        self.assertIn("11", parks.lookup("entrance", "Sample Park", self.data))
        self.assertEqual(parks.unit(" 007 "), "007")
        self.assertEqual(parks.unit(True), "")

    def test_expected_failures_are_successful_radio_replies(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(parks, "load_snapshot", side_effect=FileNotFoundError("private/path")):
            self.assertEqual(parks.main("statepark", ["id 007"]), 0)
        self.assertIn("unavailable", output.getvalue())
        self.assertNotIn("private", output.getvalue())

    def test_missing_dataset_is_reported_in_command_discovery(self):
        with patch.object(parks, "load_snapshot", side_effect=FileNotFoundError):
            for command in ("!statepark", "!entrance"):
                self.assertIn("Unavailable", dependency_status(command))

    def test_repaired_boundary_uncertainty_is_mandatory_and_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_snapshot(root, self.data, [1])
            with patch.object(parks, "resolve", return_value=root):
                data = parks.load_snapshot()
                with patch.dict(os.environ, {"MESHCORE_SENDER": "é" * 40}):
                    result = parks.lookup("statepark", "near 38.05 -121.95", data)
                    self.assertIn("repair uncertain", result)
                    self.assertIn("0.0 mi", result)
                    self.assertLessEqual(len(("@" + "é" * 40 + " " + result).encode()), 150)
                (root / "repair.json").write_text('{"features": []}')
                with self.assertRaises(ValueError):
                    parks.load_snapshot()

    def test_manifest_paths_ids_counts_and_crs_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for key, value in (("path", "../outside.json"), ("path", "C:/private/data.json"),
                               ("feature_count", 2), ("object_id_field", "UNITNBR")):
                manifest = write_snapshot(root, self.data)
                manifest["datasets"]["park_boundaries"][key] = value
                (root / "sources.json").write_text(json.dumps(manifest))
                with self.subTest(key=key, value=value), patch.object(parks, "resolve", return_value=root):
                    with self.assertRaises(ValueError):
                        parks.load_snapshot()
            for key, value in (("schema_version", 2), ("geojson_crs", "EPSG:3857")):
                manifest = write_snapshot(root, self.data)
                manifest[key] = value
                (root / "sources.json").write_text(json.dumps(manifest))
                with patch.object(parks, "resolve", return_value=root), self.assertRaises(ValueError):
                    parks.load_snapshot()
            self.data["park_boundaries"].append(self.data["park_boundaries"][0])
            write_snapshot(root, self.data)
            with patch.object(parks, "resolve", return_value=root), self.assertRaises(ValueError):
                parks.load_snapshot()

    def test_changed_manifest_and_bounded_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_snapshot(root, self.data)
            original = parks.read_json
            calls = 0
            def changed_manifest(path, limit):
                nonlocal calls
                raw, data = original(path, limit)
                if path.name == "sources.json":
                    calls += 1
                    if calls == 2:
                        return raw + b" ", data
                return raw, data
            with patch.object(parks, "resolve", return_value=root), patch.object(parks, "read_json", side_effect=changed_manifest):
                with self.assertRaisesRegex(ValueError, "changed"):
                    parks.load_snapshot()
            with self.assertRaisesRegex(ValueError, "bound"):
                parks.read_json(root / "sources.json", 10)

    def test_malformed_geometries_and_invalid_queries(self):
        for coordinates in (None, [], [1], [True, 38], [float("nan"), 38], [181, 38], "-122,38"):
            self.data["park_entry_points"][0]["geometry"] = {"type": "Point", "coordinates": coordinates}
            with self.subTest(coordinates=coordinates), self.assertRaises(ValueError):
                parks.lookup("entrance", "id 11", self.data)
        for geometry in (None, {}, {"type": "Point", "coordinates": [-122, 38]},
                         {"type": "Polygon", "coordinates": []}):
            self.data["park_boundaries"][0]["geometry"] = geometry
            with self.subTest(geometry=geometry), self.assertRaises(ValueError):
                parks.lookup("statepark", "near 38 -122", self.data)
        for command, query in (("statepark", "near nan -122"), ("statepark", "near 0 0"),
                               ("statepark", "near bad -122"), ("statepark", "id"),
                               ("entrance", "id 11 extra"), ("entrance", "unit")):
            with self.subTest(query=query), self.assertRaises(ValueError):
                parks.lookup(command, query, self.data)

    def test_wholly_blank_name_and_conflicting_classifications(self):
        self.data["park_boundaries"][0]["properties"]["UNITNAME"] = ""
        self.assertIn("unit 007", parks.lookup("statepark", "id 007", self.data))
        self.assertIn("Unnamed", parks.lookup("statepark", "id 007", self.data))
        self.data["park_boundaries"].append(feature({"FID": 2, "UNITNBR": "007", "SUBTYPE": "Other"}, None))
        self.assertIn("Classification varies", parks.lookup("statepark", "id 007", self.data))

    def test_nearest_different_units_tied(self):
        self.data["park_boundaries"].append(feature({"FID": 2, "UNITNBR": "008"}, self.data["park_boundaries"][0]["geometry"]))
        result = parks.lookup("statepark", "near 38.05 -121.95", self.data)
        for phrase in ("Multiple", "unit 007", "unit 008"):
            self.assertIn(phrase, result)

    def test_missing_unit_does_not_hide_an_ambiguous_name(self):
        self.data["park_boundaries"].append(feature({"FID": 2, "UNITNAME": "Sample Park"}, None))
        for command in ("statepark", "entrance"):
            self.assertIn("ambiguous", parks.lookup(command, "Sample Park", self.data))

    def test_malformed_feature_and_repair_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for ident in (None, True, "1", [], -1):
                self.data["park_boundaries"][0]["properties"]["FID"] = ident
                write_snapshot(root, self.data)
                with self.subTest(ident=ident), patch.object(parks, "resolve", return_value=root), self.assertRaises(ValueError):
                    parks.load_snapshot()
            self.data["park_boundaries"][0]["properties"]["FID"] = 1
            for ids in ([2], [1, 1], [True]):
                write_snapshot(root, self.data, ids)
                with self.subTest(ids=ids), patch.object(parks, "resolve", return_value=root), self.assertRaises(ValueError):
                    parks.load_snapshot()

    def test_partial_proximity_dependency_and_input_bounds(self):
        real_import = builtins.__import__
        def without_geometry(name, *args, **kwargs):
            if name.split(".")[0] in {"shapely", "pyproj"}:
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)
        with patch.object(parks, "load_snapshot", return_value=self.data), patch("builtins.__import__", side_effect=without_geometry):
            self.assertIn("Partial", dependency_status("!statepark"))
            self.assertIn("Local data checked", dependency_status("!entrance"))
        for query in ("é" * 76, "Sample\nPark", "Sample\tPark"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch.object(parks, "load_snapshot") as load:
                self.assertEqual(parks.main("statepark", [query]), 0)
                load.assert_not_called()
            self.assertIn("Invalid query", output.getvalue())


class StateParksIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_generation_direct_and_service_invocation(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / "config.json").read_text())["responder"]
        fixture = StateParksTests()
        fixture.setUp()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MESHCORE_DATA_DIR": temp}):
            data_root = Path(temp)
            generation = data_root / "generations" / "parks" / "custom"
            write_snapshot(generation, fixture.data, [1])
            registry = data_root / "datasets.json"
            registry.write_text(json.dumps({"schema": 1, "datasets": {
                "california_state_parks": {"active": {"path": "generations/parks/custom"}}}}))
            before = {p.relative_to(data_root): p.read_bytes() for p in data_root.rglob("*") if p.is_file()}
            for command, query, expected in (("statepark", "id 007", "unit 007"),
                                             ("entrance", "id 11", "38.00000,-122.00000"),
                                             ("statepark", "near 38.05 -121.95", "repair uncertain"),
                                             ("statepark", "near bad -122", "Use !statepark near")):
                direct = subprocess.run([sys.executable, "-B", str(root / "scripts" / (command + ".py")), query],
                                        capture_output=True, text=True, check=True)
                self.assertIn(expected, direct.stdout)
                self.assertEqual(direct.stderr, "")
                request = {"command": "!" + command, "arguments": [query], "sender": "é" * 40,
                           "channel_name": "default", "channel_id": "default", "channel_index": 3,
                           "id": "parks-test", "phrase": "!" + command + " " + query}
                result, detail = await responder.run_script(root, config["commands"]["!" + command], request, config)
                self.assertIn(expected, result)
                self.assertEqual(detail, "")
                self.assertLessEqual(len(responder.reply_parts(request["sender"], result, max_parts=1)[0].encode()), 150)
            self.assertEqual(before, {p.relative_to(data_root): p.read_bytes() for p in data_root.rglob("*") if p.is_file()})
            # Exercise command acceptance and the actual origin-channel reply path.
            send = AsyncMock()
            config["sender_cooldown"] = 0
            with contextlib.closing(sqlite3.connect(":memory:")) as db:
                bot = responder.Responder(root, db, config, 3, "Local Bot", send)
                for command, query in (("statepark", "id 007"), ("entrance", "id 11")):
                    self.assertTrue(bot.accept({"channel_idx": 3, "txt_type": 0,
                        "text": f"Alice: !{command} {query}", "sender_timestamp": int(time.time())}))
                    self.assertTrue(await bot.process_one())
                    channel, body = send.await_args.args
                    self.assertEqual(channel, 3)
                    self.assertTrue(body.startswith("@Alice "))
                    self.assertIn("ref", body)
                    self.assertLessEqual(len(body.encode()), 150)
                config["commands"]["!entrance"]["channels"] = []
                self.assertFalse(bot.accept({"channel_idx": 3, "txt_type": 0,
                    "text": "Bob: !entrance id 11", "sender_timestamp": int(time.time())}))
            registry.write_text(json.dumps({"schema": 1, "datasets": {"california_state_parks": {"active": None}}}))
            request.update(arguments=["id 007"], command="!statepark")
            result, detail = await responder.run_script(root, config["commands"]["!statepark"], request, config)
            self.assertIn("data unavailable", result)
            self.assertEqual(detail, "")
            with self.assertRaises(FileNotFoundError):
                parks.load_snapshot()


if __name__ == "__main__":
    unittest.main()
