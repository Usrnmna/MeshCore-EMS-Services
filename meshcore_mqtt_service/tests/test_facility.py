"""W05 source eligibility, partial coverage, reference semantics and integration."""
import contextlib
import builtins
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import responder
from scripts import facility_lookup as facility
from scripts import gis_data
from scripts.command_dependencies import dependency_status

ROOT = Path(__file__).resolve().parents[1]


def feature(ident, source, lat=38.001, **properties):
    """Create an independently identified point in the source's native schema."""
    key = "OBJECTID" if source == "ebmud" else "FID"
    return {"type": "Feature", "properties": dict(properties, **{key: ident}),
            "geometry": {"type": "Point", "coordinates": [-122, lat]}}


def fixtures():
    return {
        "ebmud": [feature(1, "ebmud", LABEL="Lake Site", RESTROOM="ADA", DRINKING_WATER="Yes",
                          PICNIC_AREA="Yes", BOAT_LAUNCH="Yes"),
                  feature(2, "ebmud", lat=38, LABEL="Nonqualifying", RESTROOM="No", DRINKING_WATER="Unknown")],
        "parks": [feature(10, "parks", lat=38.002, TYPE="Vault toilet", SHARE="Public", DETAIL="Toilet"),
                  feature(11, "parks", lat=38, TYPE="Office", SHARE="Public", DETAIL="Office with restroom")],
    }


def write_sources(root, data):
    """Install separate deterministic generations without bundled source fallbacks."""
    registry = {"schema": 1, "datasets": {}}
    for source, collection in (("ebmud", "ebmud"), ("parks", "california_state_parks")):
        directory = root / (source + "-selected")
        directory.mkdir()
        manifest = {"datasets": {}}
        if source == "ebmud":
            manifest["coordinate_reference_system"] = "WGS 84 (EPSG:4326)"
            layers = {"recreation_points": data[source]}
        else:
            manifest.update(schema_version=1, geojson_crs="EPSG:4326")
            layers = {"buildings": data[source], "picnic_grounds": [feature(21, "parks", TYPE="Developed Family Picnic Area", SHARE="Public")]}
        for name, records in layers.items():
            raw = json.dumps({"type": "FeatureCollection", "features": records}).encode()
            (directory / (name + ".json")).write_bytes(raw)
            manifest["datasets"][name] = {"path": name + ".json", "feature_count": len(records),
                "byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "object_id_field": "FID"}
        (directory / "sources.json").write_text(json.dumps(manifest))
        registry["datasets"][collection] = {"active": {"path": directory.name}}
    (root / "datasets.json").write_text(json.dumps(registry))
    return registry


class FacilityTests(unittest.TestCase):
    def setUp(self):
        self.data = fixtures()

    def query(self, text):
        with patch.object(facility, "load_source", side_effect=lambda source, category: self.data[source]):
            return facility.lookup(facility.parse(text))

    def test_filter_before_ranking_and_preserve_ada(self):
        output = self.query("restrooms near 38 -122")
        self.assertIn("ebmud#1", output)
        self.assertIn("restroom ADA", output)
        self.assertIn("site ref", output)
        self.assertNotIn("partial", output)
        self.assertIn("parks#10", self.query("restrooms near 38 -122 source=parks"))

    def test_explicit_source_only_reads_that_collection(self):
        with patch.object(facility, "load_source", return_value=self.data["parks"]) as load:
            result = facility.lookup(facility.parse("restrooms source=parks near 38 -122 2"))
            load.assert_called_once_with("parks", "restrooms")
        self.assertIn("parks#10", result)
        self.assertNotIn("partial", result)

    def test_unknown_negative_and_qualified_flags_are_not_affirmative(self):
        for value in (None, "", "No", "Unknown", True, 1, "Yes (seasonal)"):
            self.data["ebmud"][0]["properties"]["DRINKING_WATER"] = value
            self.assertIn("No matching", self.query("water near 38 -122 source=ebmud"))

    def test_nonpublic_context_and_service_types_are_excluded(self):
        for properties in ({"TYPE": "Office", "SHARE": "Public", "DETAIL": "Visitor center restroom"},
                           {"TYPE": "Combo building", "SHARE": "Public"},
                           {"TYPE": "Comfort station", "SHARE": "Internal Use Only"},
                           {"TYPE": "Comfort station", "SHARE": ""},
                           {"TYPE": "Comfort station", "SHARE": "Public", "DETAIL": "Employee facilities"},
                           {"TYPE": "Comfort station", "SHARE": "Public", "DETAIL": "Service Yard restroom"}):
            with self.subTest(properties=properties):
                self.data["parks"] = [feature(10, "parks", **properties)]
                self.assertIn("No matching", self.query("restrooms near 38 -122 source=parks"))

    def test_only_classified_picnic_areas_and_combined_visitor_type(self):
        for kind in ("Developed Family Camp Area", "Undefined", "Garden, Historic, Period"):
            self.data["parks"] = [feature(10, "parks", TYPE=kind, SHARE="Public", DETAIL="picnic tables")]
            self.assertIn("No matching", self.query("picnic near 38 -122 source=parks"))
        self.data["parks"] = [feature(10, "parks", TYPE="Primitive Group Picnic Area", SHARE="Public")]
        self.assertIn("primitive group picnic", self.query("picnic near 38 -122 source=parks"))
        self.data["parks"] = [feature(10, "parks", TYPE="Museum/Visitor center", SHARE="Public")]
        output = self.query("visitors near 38 -122")
        self.assertIn("museum/visitor", output)
        self.assertIn("partial", output)
        self.assertIn("ebmud unsupported", output)

    def test_unsupported_water_and_boat_sources_are_explicit(self):
        for category in ("water", "boatlaunch"):
            with patch.object(facility, "load_source") as load:
                output = facility.lookup(facility.parse(category + " near 38 -122 source=parks"))
                load.assert_not_called()
                self.assertIn("unsupported", output)
            output = self.query(category + " near 38 -122")
            self.assertIn("ebmud#1", output)
            self.assertIn("partial", output)
            if category == "water":
                self.assertIn("potability unknown", output)

    def test_source_failure_preserves_available_results_without_leaking_paths(self):
        def load(source, category):
            if source == "parks":
                raise ValueError("private/path and secret")
            return self.data[source]
        with patch.object(facility, "load_source", side_effect=load):
            output = facility.lookup(facility.parse("restrooms near 38 -122"))
        for text in ("ebmud#1", "partial", "parks unavailable"):
            self.assertIn(text, output)
        self.assertNotIn("private", output)
        self.assertNotIn("secret", output)
        with patch.object(facility, "load_source", side_effect=FileNotFoundError):
            self.assertIn("source data unavailable", facility.lookup(facility.parse("restrooms near 38 -122")))

    def test_incomplete_eligible_geometry_reports_partial_coverage(self):
        self.data["ebmud"][1]["properties"]["RESTROOM"] = "Yes"
        for geometry in (None, {"type": "Point", "coordinates": [True, 38]},
                         {"type": "Point", "coordinates": [10 ** 400, 38]}):
            self.data["ebmud"][1]["geometry"] = geometry
            output = self.query("restrooms near 38 -122")
            self.assertIn("partial", output)
            self.assertIn("ebmud incomplete", output)
        self.data["ebmud"][1]["properties"]["RESTROOM"] = "No"
        self.assertNotIn("partial", self.query("restrooms near 38 -122"))

    def test_distinct_coincident_and_similar_records_are_not_merged(self):
        self.data["parks"][0]["geometry"] = copy.deepcopy(self.data["ebmud"][0]["geometry"])
        self.data["parks"][0]["properties"]["DETAIL"] = "Lake Site"
        output = self.query("restrooms near 38 -122")
        for text in ("Multiple", "ebmud#1", "parks#10"):
            self.assertIn(text, output)
        self.data["ebmud"].append(copy.deepcopy(self.data["ebmud"][0]))
        self.data["ebmud"][-1]["properties"]["OBJECTID"] = 3
        self.assertIn("ebmud#3", self.query("restrooms near 38 -122 source=ebmud"))

    def test_exact_radius_boundary_and_no_match(self):
        from pyproj import Geod
        lon, lat, _ = Geod(ellps="WGS84").fwd(-122, 38, 0, 1609.344)
        self.data["ebmud"][0]["geometry"]["coordinates"] = [lon, lat]
        self.assertIn("ebmud#1", self.query("restrooms near 38 -122 1 source=ebmud"))
        self.assertIn("No matching", self.query("restrooms near 38 -122 0.9 source=ebmud"))

    def test_conditional_source_wording_and_negation_are_indivisible(self):
        self.data["parks"] = [feature(10, "parks", TYPE="Developed Family Picnic Area", SHARE="Public")]
        for note in ("Non-reservable picnic area", "Picnic Area - need reservations", "7 tables (2 ADA accessible sites)"):
            self.data["parks"][0]["properties"]["DETAIL"] = note
            with patch.dict(os.environ, {"MESHCORE_SENDER": "Alice"}):
                output = self.query("picnic near 38 -122 source=parks")
                self.assertEqual(output.count(note), 1)
            with patch.dict(os.environ, {"MESHCORE_SENDER": "é" * 40}):
                result = self.query("picnic near 38 -122 source=parks")
                self.assertTrue(note in result or "conditions cannot fit" in result)
                self.assertLessEqual(len(("@" + "é" * 40 + " " + result).encode()), 150)

    def test_removed_abandoned_and_operating_conditions_cannot_disappear(self):
        self.data["parks"] = [feature(10, "parks", TYPE="Vault toilet", SHARE="Public")]
        for note in ("(appears to have been removed)", "Abandoned Vault toilet - overgrown",
                     "Not abandoned; limited hours", "Toilet out of service", "Toilet not operating",
                     "Toilet temporarily unavailable"):
            self.data["parks"][0]["properties"]["DETAIL"] = note
            for sender in ("Alice", "é" * 40):
                with self.subTest(note=note, sender=sender), patch.dict(os.environ, {"MESHCORE_SENDER": sender}):
                    output = self.query("restrooms near 38 -122 source=parks")
                    core = output.split(" | ", 1)[0]
                    self.assertTrue(note in core or "conditions cannot fit" in core, output)
                    self.assertIn("parks#10", core)
                    self.assertLessEqual(len(responder.reply_parts(sender, output, max_parts=1)[0].encode()), 150)

    def test_missing_proximity_dependency_keeps_help_and_safe_error_replies(self):
        real_import = builtins.__import__
        def without_pyproj(name, *args, **kwargs):
            if name.split(".")[0] == "pyproj":
                raise ImportError("private dependency path")
            return real_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=without_pyproj):
            for query in ("help", "help categories", "help sources"):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(facility.main([query]), 0)
                self.assertNotIn("unavailable", output.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(facility.main(["restrooms near 38 -122"]), 0)
            self.assertIn("dependency unavailable", output.getvalue())
            self.assertNotIn("private", output.getvalue())
            self.assertIn("Unavailable", dependency_status("!facility"))

    def test_source_qualifiers_survive_maximum_sender_and_unicode_names(self):
        self.data["ebmud"][0]["properties"]["LABEL"] = "湖" * 100
        for sender in ("Alice", "é" * 40, "a" * 80):
            with patch.dict(os.environ, {"MESHCORE_SENDER": sender}):
                for category, required in (("restrooms", "ADA"), ("water", "potability unknown")):
                    result = self.query(category + " near 38 -122")
                    self.assertIn(required, result)
                    self.assertIn("ebmud#1", result)
                    self.assertIn("ref", result)
                    self.assertNotIn("Unable to return", result)
                    parts = responder.reply_parts(sender, result, max_parts=1)
                    self.assertEqual(len(parts), 1)
                    self.assertLessEqual(len(parts[0].encode()), 150)

    def test_bounded_grammar_and_help(self):
        for text in ("shelter near 38 -122", "water name", "water near 38 -122 source=other", "water near 38 -122 source=parks source=ebmud",
                     "water near nan -122", "water near 38 -122 -1", "water near 38 -122 26", "water near 0 0",
                     "water near 38 -122 type=horse", "water near 38 -122\n", "é" * 76):
            with self.subTest(text=text), self.assertRaises(ValueError):
                facility.parse(text)
        with patch.object(facility, "load_source") as load, patch.dict(os.environ, {"MESHCORE_SENDER": "é" * 40}):
            for topic in ("", "categories", "sources"):
                output = facility.lookup(facility.parse("help " + topic))
                self.assertLessEqual(len(("@" + "é" * 40 + " " + output).encode()), 150)
            load.assert_not_called()


class FacilityIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_service_channel_replies_removal_and_no_mutation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MESHCORE_DATA_DIR": temp}):
            root = Path(temp)
            data = fixtures()
            data["parks"][0]["properties"]["DETAIL"] = "(appears to have been removed)"
            registry = write_sources(root, data)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            config = json.loads((ROOT / "config.json").read_bytes())["responder"]
            config["sender_cooldown"] = 0
            query = "restrooms near 38 -122"
            direct = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/facility.py"), query], capture_output=True, text=True, check=True)
            self.assertIn("ebmud#1", direct.stdout)
            self.assertEqual(direct.stderr, "")
            send = AsyncMock()
            with contextlib.closing(sqlite3.connect(":memory:")) as db:
                bot = responder.Responder(ROOT, db, config, 3, "Local Bot", send)
                self.assertTrue(bot.accept({"channel_idx": 3, "txt_type": 0, "text": "Alice: !facility " + query, "sender_timestamp": int(time.time())}))
                self.assertTrue(await bot.process_one())
                channel, reply = send.await_args.args
                self.assertEqual(channel, 3)
                self.assertIn("@Alice ebmud#1", reply)
                for sender in ("Alice", "é" * 40):
                    request = {"command": "!facility", "arguments": [query + " source=parks"],
                               "sender": sender, "channel_name": "default", "channel_id": "default",
                               "channel_index": 3, "id": "w05-review", "phrase": "!facility " + query}
                    output, detail = await responder.run_script(ROOT, config["commands"]["!facility"], request, config)
                    self.assertEqual(detail, "")
                    self.assertIn("parks#10", output)
                    self.assertTrue("(appears to have been removed)" in output or "conditions cannot fit" in output)
                    self.assertLessEqual(len(responder.reply_parts(sender, output, max_parts=1)[0].encode()), 150)
                config["commands"]["!facility"]["channels"] = []
                self.assertFalse(bot.accept({"channel_idx": 3, "txt_type": 0, "text": "Bob: !facility " + query, "sender_timestamp": int(time.time())}))
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})
            self.assertIn("Partial", dependency_status("!facility"))
            registry["datasets"]["california_state_parks"]["active"] = None
            (root / "datasets.json").write_text(json.dumps(registry))
            output = facility.lookup(facility.parse(query))
            self.assertIn("ebmud#1", output)
            self.assertIn("partial", output)
            self.assertIn("parks unavailable", output)
            registry["datasets"]["ebmud"]["active"] = None
            (root / "datasets.json").write_text(json.dumps(registry))
            self.assertIn("Unavailable", dependency_status("!facility"))
            request["arguments"] = [query]
            output, detail = await responder.run_script(ROOT, config["commands"]["!facility"], request, config)
            self.assertIn("source data unavailable", output)
            self.assertEqual(detail, "")

    def test_integrity_crs_and_duplicate_ids_fail_per_source(self):
        for fault in ("hash", "crs", "duplicate"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MESHCORE_DATA_DIR": temp}):
                data = fixtures()
                if fault == "duplicate":
                    data["ebmud"].append(copy.deepcopy(data["ebmud"][0]))
                root = Path(temp)
                write_sources(root, data)
                if fault == "hash":
                    (root / "ebmud-selected/recreation_points.json").write_text("corrupt")
                elif fault == "crs":
                    path = root / "ebmud-selected/sources.json"
                    manifest = json.loads(path.read_bytes())
                    manifest["coordinate_reference_system"] = "EPSG:3857"
                    path.write_text(json.dumps(manifest))
                output = facility.lookup(facility.parse("restrooms near 38 -122"))
                self.assertIn("parks#10", output)
                self.assertIn("partial", output)
                self.assertIn("ebmud unavailable", output)

    def test_custom_ebmud_path_remains_authoritative(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_sources(root, fixtures())
            settings_path = root / "custom-gis.json"
            settings = json.loads((ROOT / "gis_settings.json").read_bytes())
            settings["data_directory"] = str(root / "ebmud-selected")
            settings_path.write_text(json.dumps(settings))
            with patch.object(facility, "load_settings", side_effect=lambda: gis_data.load_settings(settings_path)):
                self.assertEqual(facility.load_source("ebmud", "restrooms")[0]["properties"]["OBJECTID"], 1)

    def test_ebmud_refresh_lock_or_manifest_change_preserves_parks_results(self):
        for failure in ("lock", "changed"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MESHCORE_DATA_DIR": temp}):
                root = Path(temp)
                write_sources(root, fixtures())
                ebmud = root / "ebmud-selected"
                original = gis_data.Snapshot.load_dataset
                def change_after_read(snapshot, name):
                    result = original(snapshot, name)
                    with (ebmud / "sources.json").open("ab") as stream:
                        stream.write(b" ")
                    return result
                if failure == "lock":
                    (ebmud / ".refresh.lock").touch()
                manager = patch.object(gis_data.Snapshot, "load_dataset", change_after_read) if failure == "changed" else contextlib.nullcontext()
                with manager:
                    result = facility.lookup(facility.parse("restrooms near 38 -122"))
                for text in ("parks#10", "partial", "ebmud unavailable"):
                    self.assertIn(text, result)


if __name__ == "__main__":
    unittest.main()
