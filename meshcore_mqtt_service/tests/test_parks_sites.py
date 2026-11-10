"""W04 filtering, reference semantics, proximity bounds and command integration."""
import builtins
import contextlib
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
from scripts import parks_sites as sites
from scripts import stateparks_lookup as parks
from scripts.command_dependencies import dependency_status

ROOT = Path(__file__).resolve().parents[1]


def point(ident, properties, lat=38, lon=-122):
    return {"type": "Feature", "properties": dict(properties, FID=ident),
            "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def fixture():
    return {
        "park_boundaries": [{"type": "Feature", "properties": {
            "FID": 1, "UNITNBR": "007", "UNITNAME": "Example State Park"}, "geometry": None}],
        "campgrounds": [
            point(10, {"Campground": "Oak Sites 1-3", "UNITNBR": "007", "TYPE": "Environmental Camp Area", "SUBTYPE": "Tent Only"}),
            point(11, {"Campground": "Horse Camp", "UNITNBR": "007", "TYPE": "Horse Camp Area", "SUBTYPE": "Not Defined"}, 38.01),
        ],
        "parking": [
            point(20, {"NAME": "Lot", "UNITNBR": "007", "SUBTYPE": "Vehicle", "USETYPE": "Day Use (Fee)", "TRAILHEAD": "No"}),
            point(21, {"NAME": "Trail Lot", "UNITNBR": "007", "SUBTYPE": "Equestrian", "USETYPE": "Day Use (No Fee)", "TRAILHEAD": "Yes"}, 38.01),
        ],
    }


def write_generation(root, data):
    """Write only W04 collections so unrelated entry-point data cannot be required."""
    generation = root / "generations" / "parks" / "selected"
    generation.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "geojson_crs": "EPSG:4326", "datasets": {}}
    for name, features in data.items():
        raw = json.dumps({"type": "FeatureCollection", "features": features}).encode()
        (generation / (name + ".json")).write_bytes(raw)
        manifest["datasets"][name] = {"path": name + ".json", "object_id_field": "FID",
            "feature_count": len(features), "byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (generation / "sources.json").write_text(json.dumps(manifest))
    (root / "datasets.json").write_text(json.dumps({"schema": 1, "datasets": {
        "california_state_parks": {"active": {"path": "generations/parks/selected"}}}}))
    return generation


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture()

    def query(self, command, text):
        return sites.lookup(command, sites.parse(command, text), self.data)

    def test_exact_names_source_ids_and_unit_ambiguity(self):
        for command, query, ident in (("camp", " oak   SITES 1-3 ", 10), ("parking", "Lot", 20)):
            self.assertIn(f"#{ident}", self.query(command, query))
            self.assertIn(f"#{ident}", self.query(command, f"id {ident}"))
            result = self.query(command, "unit 007")
            self.assertIn(f"!{command} id", result)
            self.assertIn(str(ident), result)
            self.assertIn(str(ident + 1), result)
        self.assertIn("No matching", self.query("camp", "Example State Park"))
        self.assertIn("No matching", self.query("camp", "unit 7"))

    def test_multiple_same_name_records_are_not_deduplicated(self):
        duplicate = copy.deepcopy(self.data["campgrounds"][0])
        duplicate["properties"]["FID"] = 12
        self.data["campgrounds"].append(duplicate)
        result = self.query("camp", "Oak Sites 1-3")
        for value in ("Ambiguous", "10", "12"):
            self.assertIn(value, result)

    def test_filters_apply_before_distance_ranking_and_geometry(self):
        self.data["campgrounds"][0]["geometry"] = None
        self.assertIn("#11", self.query("camp", "near 38 -122 type=horse"))
        self.assertIn("#21", self.query("parking", "near 38 -122 trailhead=yes use=day-no-fee"))
        self.assertIn("No eligible", self.query("parking", "near 38 -122 trailhead=yes use=day-fee"))

    def test_unknown_and_qualified_values_do_not_pass_affirmative_filters(self):
        p = self.data["parking"][0]["properties"]
        for raw in (None, "", "Unknown", "Yes (seasonal)", True):
            p["TRAILHEAD"] = raw
            self.assertIn("No matching", self.query("parking", "id 20 trailhead=yes"))
            self.assertIn("#20", self.query("parking", "id 20 trailhead=unknown"))
        self.data["campgrounds"][0]["properties"]["SUBTYPE"] = "Multiple types"
        self.assertIn("No matching", self.query("camp", "id 10 subtype=tent-only"))
        self.assertIn("#10", self.query("camp", "id 10 subtype=multiple"))
        self.assertEqual(sites.category({"TYPE": "Future Category"}, "TYPE", sites.CAMP_TYPES), "unknown")

    def test_parking_type_uses_subtype_not_empty_type(self):
        self.data["parking"][0]["properties"]["TYPE"] = ""
        self.assertIn("#20", self.query("parking", "Lot type=vehicle"))
        self.assertIn("No matching", self.query("parking", "Lot type=boat"))

    def test_radius_default_maximum_and_exact_boundary(self):
        from pyproj import Geod
        geod = Geod(ellps="WGS84")
        lon, lat, _ = geod.fwd(-122, 38, 0, 1609.344)
        self.data["campgrounds"] = [point(10, {"Campground": "Boundary"}, lat, lon)]
        self.assertIn("#10", self.query("camp", "near 38 -122 1"))
        lon, lat, _ = geod.fwd(-122, 38, 0, 1609.444)
        self.data["campgrounds"][0]["geometry"]["coordinates"] = [lon, lat]
        self.assertIn("No eligible", self.query("camp", "near 38 -122 1"))
        with patch.object(sites, "radius_limit", return_value=2):
            self.assertEqual(sites.parse("camp", "near 38 -122")[1][2], 2)
            for radius in ("0", "-1", "2.01", "inf", "nan"):
                with self.subTest(radius=radius), self.assertRaises(ValueError):
                    sites.parse("camp", "near 38 -122 " + radius)

    def test_tied_nearest_records_are_ambiguous(self):
        self.data["parking"][1]["geometry"] = self.data["parking"][0]["geometry"]
        result = self.query("parking", "near 38 -122")
        for text in ("Ambiguous", "20", "21"):
            self.assertIn(text, result)

    def test_unnamed_and_missing_point_geometry(self):
        self.data["campgrounds"][0]["properties"]["Campground"] = "  "
        self.assertIn("Unnamed feature", self.query("camp", "id 10"))
        for geometry in (None, {}, {"type": "Polygon", "coordinates": []},
                         {"type": "Point", "coordinates": [True, 38]},
                         {"type": "Point", "coordinates": [-122, float("nan")]},
                         {"type": "Point", "coordinates": [181, 38]},
                         {"type": "Point", "coordinates": []}):
            self.data["campgrounds"][0]["geometry"] = geometry
            self.assertIn("Coordinates unavailable", self.query("camp", "id 10"))
            with self.subTest(geometry=geometry), self.assertRaises(ValueError):
                self.query("camp", "near 38 -122")

    def test_invalid_and_oversized_queries(self):
        for text in ("near", "near 60 -122", "near x y", "near 38 -122 1 2", "id", "id --flag",
                     "unit 007 extra", "type=horse", "id 10 type=horse type=horse", "id 10 use=day-fee",
                     "id 10 type=nonsense", "id 10\n", "é" * 76, "--foo=bar"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                sites.parse("camp", text)

    def test_literal_names_escape_reserved_query_words(self):
        for command, layer, field, ident in (("camp", "campgrounds", "Campground", 10),
                                              ("parking", "parking", "NAME", 20)):
            for name in ("near rr 7 North Grove CG", "Near Kiosk Short term parking", "help", "id 123", "type=horse"):
                self.data[layer][0]["properties"][field] = name
                self.assertIn(f"#{ident}", self.query(command, "name " + name))
        with self.assertRaises(ValueError):
            sites.parse("camp", "name")

    def test_filter_help_exposes_all_values_in_bounded_groups(self):
        for sender in ("Alice", "é" * 40):
            with patch.dict(os.environ, {"MESHCORE_SENDER": sender}):
                for command, fields in sites.FILTERS.items():
                    self.assertIn("name", sites.help_text(command))
                    for field, (_, mapping) in fields.items():
                        groups = sites.HELP_GROUPS.get(command, {}).get(field, {})
                        summary = sites.help_text(command, field)
                        outputs = []
                        if groups:
                            for group in groups:
                                self.assertIn(group, summary)
                                parsed = sites.parse(command, f"help {field} {group}")
                                outputs.append(sites.help_text(command, parsed[1]))
                        else:
                            outputs.append(summary)
                        expected = set(mapping) | {"unknown"}
                        visible = set()
                        for output in outputs:
                            self.assertLessEqual(len(("@" + sender + " " + output).encode()), 150)
                            self.assertTrue(output.startswith(field + "="))
                            visible.update(output.split("=", 1)[1].strip().split(","))
                        self.assertEqual(visible, expected)

    def test_extreme_numeric_geometry_is_rejected_without_overflow(self):
        for coords in ([10 ** 400, 38], [-122, 10 ** 400]):
            self.data["campgrounds"][0]["geometry"]["coordinates"] = coords
            with self.assertRaises(sites.QueryError):
                self.query("camp", "near 38 -122")
            self.assertIn("Coordinates unavailable", self.query("camp", "id 10"))

    def test_settings_reads_radius_only_and_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Path(temp) / "gis.json"
            for value in (3, 1.5, 0, -1, True, "25", float("nan"), 10 ** 400):
                settings.write_text(json.dumps({"maximum_radius_miles": value}))
                with patch.object(sites, "SETTINGS_FILE", settings):
                    if value in (3, 1.5):
                        self.assertEqual(sites.radius_limit(), value)
                    else:
                        with self.assertRaises(ValueError):
                            sites.radius_limit()

    def test_reference_qualifiers_distance_and_ids_survive_long_sender(self):
        self.data["campgrounds"][0]["properties"]["Campground"] = "Long name " * 30
        for sender in ("Alice", "a" * 80, "é" * 40):
            with patch.dict(os.environ, {"MESHCORE_SENDER": sender}):
                for command, ident in (("camp", 10), ("parking", 20)):
                    for query in (f"id {ident}", "near 38 -122"):
                        result = self.query(command, query)
                        parts = responder.reply_parts(sender, result, max_parts=1)
                        self.assertEqual(len(parts), 1)
                        self.assertLessEqual(len(parts[0].encode()), 150)
                        for word in (f"#{ident}", "record", "reference"):
                            self.assertIn(word, result)
                        if query.startswith("near"):
                            self.assertIn("mi straight-line", result)
                        self.assertNotIn("Unable to return", result)

    def test_recorded_fee_and_site_group_are_not_operational_claims(self):
        result = self.query("parking", "id 20")
        self.assertIn("Recorded use: Day Use (Fee)", result)
        camp = self.query("camp", "id 10")
        self.assertIn("Oak Sites 1-3", camp)
        self.assertIn("Camp record", camp)
        for output in (result, camp):
            self.assertNotRegex(output.lower(), r"\b(open|vacant|available today|free parking|book now)\b")

    def test_unit_join_preserves_original_ids_and_avoids_conflicting_park_names(self):
        self.data["campgrounds"][0]["properties"].update(Campground="", TYPE="", SUBTYPE="", UNITNBR=7)
        self.data["park_boundaries"][0]["properties"]["UNITNBR"] = "7"
        output = sites.format_record("camp", self.data["campgrounds"][0], self.data)
        self.assertIn("unit 7", output)
        # Check the association without crowding out the optional name.
        with patch.object(sites, "compact_fields", side_effect=lambda essential, fields: " | ".join([essential] + fields)):
            self.assertIn("Park: Example State Park", sites.format_record("camp", self.data["campgrounds"][0], self.data))
            self.data["park_boundaries"].append({"properties": {"UNITNBR": 7, "UNITNAME": "Different"}})
            self.assertNotIn("Park:", sites.format_record("camp", self.data["campgrounds"][0], self.data))

    def test_help_and_exact_selection_work_without_pyproj(self):
        real_import = builtins.__import__
        def without_projection(name, *args, **kwargs):
            if name.split(".")[0] == "pyproj":
                raise ImportError("unavailable")
            return real_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=without_projection):
            for command in ("camp", "parking"):
                with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(sites, "load_snapshot") as load:
                    self.assertEqual(sites.main(command, ["help"]), 0)
                    load.assert_not_called()
                self.assertIn("!" + command, output.getvalue())
                self.assertIn("reference", self.query(command, "id 10" if command == "camp" else "id 20"))
                with patch.object(sites, "load_snapshot", return_value=self.data):
                    self.assertIn("Partial", dependency_status("!" + command))

    def test_help_filter_values_and_expected_failure_replies(self):
        for command in ("camp", "parking"):
            for field in sites.FILTERS[command]:
                self.assertIn(field, sites.help_text(command, field))
            with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(sites, "load_snapshot", side_effect=FileNotFoundError("private/path")):
                self.assertEqual(sites.main(command, ["id 10"]), 0)
            self.assertIn("unavailable", output.getvalue())
            self.assertNotIn("private", output.getvalue())


class SiteIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_generation_cli_service_channel_and_removal(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MESHCORE_DATA_DIR": temp}):
            root = Path(temp)
            data = fixture()
            data["campgrounds"].append(point(12, {"Campground": "near rr 7 North Grove CG"}, 38.02))
            data["parking"].append(point(22, {"NAME": "Near Kiosk Short term parking"}, 38.02))
            generation = write_generation(root, data)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            config = json.loads((ROOT / "config.json").read_bytes())["responder"]
            config["sender_cooldown"] = 0
            send = AsyncMock()
            with contextlib.closing(sqlite3.connect(":memory:")) as db:
                bot = responder.Responder(ROOT, db, config, 3, "Local Bot", send)
                for command, query, ident in (("camp", "Oak Sites 1-3", 10), ("parking", "near 38 -122 trailhead=yes", 21),
                                               ("camp", "name near rr 7 North Grove CG", 12),
                                               ("parking", "name Near Kiosk Short term parking", 22)):
                    proc = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / (command + ".py")), query], capture_output=True, text=True, check=True)
                    self.assertIn(f"#{ident}", proc.stdout)
                    self.assertEqual(proc.stderr, "")
                    self.assertTrue(bot.accept({"channel_idx": 3, "txt_type": 0, "text": f"Alice: !{command} {query}", "sender_timestamp": int(time.time())}))
                    self.assertTrue(await bot.process_one())
                    channel, output = send.await_args.args
                    self.assertEqual(channel, 3)
                    self.assertTrue(output.startswith("@Alice "))
                    self.assertIn(f"#{ident}", output)
                    self.assertLessEqual(len(output.encode()), 150)
                for command, query, expected in (("camp", "help type access", "walk-in"),
                                                  ("parking", "help type other", "campground-spur"),
                                                  ("camp", "near bad coordinates", "must be numbers"),
                                                  ("parking", "id 20 trailhead=maybe", "Unknown filter value")):
                    request = {"command": "!" + command, "arguments": [query], "sender": "é" * 40,
                               "channel_name": "default", "channel_id": "default", "channel_index": 3,
                               "id": "w04-review", "phrase": "!" + command + " " + query}
                    output, detail = await responder.run_script(ROOT, config["commands"]["!" + command], request, config)
                    self.assertIn(expected, output)
                    self.assertEqual(detail, "")
                    self.assertLessEqual(len(responder.reply_parts(request["sender"], output, max_parts=1)[0].encode()), 150)
                config["commands"]["!camp"]["channels"] = []
                self.assertFalse(bot.accept({"channel_idx": 3, "txt_type": 0, "text": "Bob: !camp id 10", "sender_timestamp": int(time.time())}))
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})
            for command in ("!camp", "!parking"):
                self.assertIn("Local data checked", dependency_status(command))
            (generation / "campgrounds.json").write_text("corrupt")
            self.assertIn("Unavailable", dependency_status("!camp"))
            self.assertIn("Local data checked", dependency_status("!parking"))
            (root / "datasets.json").write_text(json.dumps({"schema": 1, "datasets": {"california_state_parks": {"active": None}}}))
            for command in ("camp", "parking"):
                proc = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / (command + ".py")), "id 10"], capture_output=True, text=True, check=True)
                self.assertIn("unavailable", proc.stdout)
                self.assertIn("Unavailable", dependency_status("!" + command))

    def test_collection_selection_and_integrity(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MESHCORE_DATA_DIR": temp}):
            root = Path(temp)
            generation = write_generation(root, fixture())
            selected = parks.load_snapshot(("park_boundaries", "campgrounds"))
            self.assertEqual(len(selected["campgrounds"]), 2)
            self.assertNotIn("parking", selected)
            manifest = json.loads((generation / "sources.json").read_bytes())
            manifest["datasets"]["campgrounds"]["object_id_field"] = "UNITNBR"
            (generation / "sources.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                parks.load_snapshot(("park_boundaries", "campgrounds"))

    def test_generation_is_pinned_when_registry_changes_during_read(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MESHCORE_DATA_DIR": temp}):
            root = Path(temp) / ".." / Path(temp).name
            generation = write_generation(root, fixture())
            original = parks.verified_json
            def remove_during_read(directory, relative, metadata):
                result = original(directory, relative, metadata)
                (root / "datasets.json").write_text(json.dumps({"schema": 1, "datasets": {
                    "california_state_parks": {"active": None}}}))
                self.assertTrue(directory.samefile(generation))
                return result
            with patch.object(parks, "verified_json", side_effect=remove_during_read):
                selected = parks.load_snapshot(("park_boundaries", "parking"))
            self.assertEqual(selected["parking"][0]["properties"]["FID"], 20)
            with self.assertRaises(FileNotFoundError):
                parks.load_snapshot(("park_boundaries", "parking"))


if __name__ == "__main__":
    unittest.main()
