"""Offline scientific-boundary, routing, provenance, and publication regression tests."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

from shapely.geometry import box, mapping

from data.flood_impacts import archive, hydro, refresh


@contextmanager
def workspace():
    root = archive.ROOT / (".test-refresh-" + uuid4().hex)
    root.mkdir()
    try:
        yield root
    finally:
        if root.resolve().parent != archive.ROOT.resolve() or not root.name.startswith(".test-refresh-"):
            raise ValueError("Unexpected test cleanup path")
        shutil.rmtree(root)


def flow(comid, upstream, downstream, **extra):
    return {"properties": {"comid": comid, "fromnode": upstream, "tonode": downstream, **extra}}


class RoutingTests(unittest.TestCase):
    def test_branches_and_missing_boundaries(self):
        rows = hydro.flow_connections([flow(1, 10, 20), flow(2, 20, 30), flow(3, 20, 40), flow(4, 99, 100)])
        self.assertEqual(hydro.downstream("1", rows), {"1", "2", "3"})
        self.assertEqual(sum(r["status"] == "outside_subset_or_missing" for r in rows), 3)

    def test_missing_nodes_do_not_join(self):
        rows = hydro.flow_connections([flow(1, None, 0), flow(2, 0, None)])
        self.assertTrue(all(not r["to_reach_id"] for r in rows))

    def test_cycles_terminate(self):
        rows = hydro.flow_connections([flow(1, 1, 2), flow(2, 2, 1)])
        self.assertEqual(hydro.downstream("1", rows), {"1", "2"})


class ScenarioTests(unittest.TestCase):
    def test_interval_stage_field_and_fragment_union(self):
        with workspace() as root:
            archive.write_json(root / "inputs/scenario_layers.json", [{"id": 2}])
            properties = {"ahps_lid": "heac1", "interval_stage": 21, "is_interval": "True", "stage_uni": "FT",
                          "magnitude": "action", "fim_version": "6.2", "model_version": "4.9.20.1", "oid": 1}
            geom = mapping(box(-123, 38, -122.99, 38.01))
            features = [{"type": "Feature", "geometry": geom, "properties": properties},
                        {"type": "Feature", "geometry": geom, "properties": {**properties, "oid": 2}}]
            archive.write_json(root / "inputs/catfim_2.geojson.gz", {"features": features})
            context = hydro.GeometryContext()
            scenarios = refresh.create_scenarios(root, context)
            self.assertEqual(len(scenarios), 1)
            self.assertEqual(scenarios[0][0]["stage"], 21)
            self.assertAlmostEqual(scenarios[0][1].area, context.project(geom, "original").area)

    def test_partial_basin_and_nested_levels_remain_separate(self):
        context = hydro.GeometryContext()
        scenarios = [({"scenario_id": "one"}, box(5, 0, 15, 10))]
        basins = [({"basin_id": "a", "calwater_level": "PW"}, box(0, 0, 10, 10)),
                  ({"basin_id": "b", "calwater_level": "HU"}, box(0, 0, 20, 10))]
        rows, features = hydro.basin_impacts(scenarios, basins, context)
        self.assertEqual([r["affected_area_m2"] for r in rows], [50, 100])
        self.assertEqual([r["basin_fraction"] for r in rows], [0.5, 0.5])
        self.assertEqual(len(features), 2)

    def test_touching_boundary_has_no_affected_area(self):
        rows, _ = hydro.basin_impacts([({"scenario_id": "s"}, box(10, 0, 20, 10))],
                                     [({"basin_id": "b"}, box(0, 0, 10, 10))], hydro.GeometryContext())
        self.assertEqual(rows, [])

    def test_invalid_geometry_repair_is_recorded(self):
        context = hydro.GeometryContext()
        geom = {"type": "Polygon", "coordinates": [[[-123, 38], [-122, 39], [-123, 39], [-122, 38], [-123, 38]]]}
        self.assertTrue(context.project(geom, "fixture").is_valid)
        self.assertEqual(context.diagnostics[0]["status"], "derived_make_valid")


class StageTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
        self.gauge = {"lid": "HEAC1", "usgsId": "11464000", "inService": {"enabled": True},
                      "datums": {"vertical": {"value": [{"abbrev": "NAVD88", "value": 79.98}]}}}
        self.site = {"mapped": "yes", "usgs_gage": "11464000", "nws_data_vertical_datum_name": "NAVD 1988", "nws_data_zero_datum": "79.98"}
        self.scenarios = [{"scenario_id": str(s), "gauge_lid": "HEAC1", "stage": s, "stage_units": "FT"} for s in (20, 21)]
        self.series = {"observed": {"primaryName": "Stage", "primaryUnits": "ft",
                                  "data": [{"validTime": self.now.isoformat(), "primary": 20.5}]}}

    def compare(self):
        return hydro.stage_comparison(self.gauge, self.series, self.site, self.scenarios, "observed", self.now, 6)

    def test_bracket_without_interpolation(self):
        row = self.compare()
        self.assertEqual((row["lower_scenarios"], row["upper_scenarios"]), ("20", "21"))
        self.assertIn("no event inundation", row["interpretation"])

    def test_stale_data_does_not_select_scenario(self):
        self.series["observed"]["data"][0]["validTime"] = (self.now - timedelta(hours=7)).isoformat()
        row = self.compare()
        self.assertEqual(row["status"], "stale_measurement_or_forecast")
        self.assertEqual(row["lower_scenarios"], "")

    def test_future_observation_is_rejected(self):
        self.series["observed"]["data"][0]["validTime"] = (self.now + timedelta(hours=1)).isoformat()
        self.assertEqual(self.compare()["status"], "missing_measurement")

    def test_out_of_range_is_not_no_flood(self):
        self.series["observed"]["data"][0]["primary"] = 0
        self.assertEqual(self.compare()["status"], "outside_published_stage_range")

    def test_changed_datum_blocks_comparison(self):
        self.site["nws_data_zero_datum"] = "80.1"
        self.assertEqual(self.compare()["status"], "datum_unknown_or_changed")

    def test_missing_map_remains_explicit(self):
        self.site["mapped"] = "no"
        self.assertEqual(self.compare()["status"], "no_published_inundation_coverage")

    def test_wrong_units_do_not_compare(self):
        self.series["observed"]["primaryUnits"] = "m"
        self.assertEqual(self.compare()["status"], "unsupported_measurement_or_units")
        self.assertEqual(self.compare()["stage_ft"], "")

    def test_null_series_is_missing(self):
        self.series["observed"] = None
        self.assertEqual(self.compare()["status"], "missing_measurement")

    def test_null_datum_is_explicitly_unknown(self):
        self.gauge["datums"] = None
        self.assertEqual(self.compare()["status"], "datum_unknown_or_changed")

    def test_null_service_status_is_unknown(self):
        self.gauge["inService"] = None
        self.assertEqual(self.compare()["status"], "station_service_status_unknown")

    def test_forecast_issue_age_and_future_peak(self):
        self.series["forecast"] = {"primaryName": "Stage", "primaryUnits": "ft", "issuedTime": self.now.isoformat(),
                                   "data": [{"validTime": (self.now + timedelta(hours=2)).isoformat(), "primary": 21},
                                            {"validTime": (self.now - timedelta(hours=1)).isoformat(), "primary": 99}]}
        row = hydro.stage_comparison(self.gauge, self.series, self.site, self.scenarios, "forecast", self.now, 24)
        self.assertEqual(row["stage_ft"], 21)
        self.series["forecast"]["issuedTime"] = (self.now - timedelta(days=2)).isoformat()
        row = hydro.stage_comparison(self.gauge, self.series, self.site, self.scenarios, "forecast", self.now, 24)
        self.assertEqual(row["status"], "stale_measurement_or_forecast")


class ArchiveTests(unittest.TestCase):
    def test_atomic_publication_and_tamper_detection(self):
        with workspace() as root:
            stage, identifier = archive.begin(root, "static")
            archive.write_json(stage / "fixture.json", {"name": "Lower Dunn Creek"})
            path, _ = archive.publish(root, stage, identifier, "static", {})
            archive.open_generation(root)
            (path / "fixture.json").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum"):
                archive.open_generation(root)

    def test_failed_refresh_keeps_active_pointer(self):
        with workspace() as root:
            stage, identifier = archive.begin(root, "static")
            archive.write_json(stage / "fixture.json", {})
            archive.publish(root, stage, identifier, "static", {})
            before = (root / "static.json").read_bytes()
            with patch.object(refresh, "acquire", side_effect=RuntimeError("HTTP failure")):
                with self.assertRaises(RuntimeError):
                    refresh.refresh_static(root, {}, root)
            self.assertEqual((root / "static.json").read_bytes(), before)

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            archive.safe_path(archive.ROOT, "../outside.json")

    def test_arcgis_incomplete_batch_rejected(self):
        with workspace() as root:
            replies = [{"objectIdField": "oid"}, {"objectIds": [1, 2]},
                       {"features": [{"properties": {"oid": 1}}]}]
            with patch.object(archive, "fetch", side_effect=replies):
                with self.assertRaisesRegex(ValueError, "Incomplete"):
                    archive.arcgis(root, "test", "https://example.test/layer", "1=1")


if __name__ == "__main__":
    unittest.main()
