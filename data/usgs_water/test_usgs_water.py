"""Offline tests for current-only retention, acquisition integrity and interpretation."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from shapely.geometry import Point, box, mapping

from data.flood_impacts import archive
from data.usgs_water import analysis, client, refresh, relationships


@contextmanager
def workspace():
    root = refresh.ROOT / (".test-refresh-" + uuid4().hex)
    root.mkdir()
    try:
        yield root
    finally:
        if root.resolve().parent != refresh.ROOT.resolve() or not root.name.startswith(".test-refresh-"):
            raise ValueError("Unsafe test cleanup")
        shutil.rmtree(root)


def reading(value="0", parameter="00065", stamp="2026-10-20T04:00:00Z"):
    return {"id": "measurement-1", "type": "Feature", "geometry": mapping(Point(-122, 38)),
            "properties": {"monitoring_location_id": "USGS-00123456", "time_series_id": "series-1",
                           "parameter_code": parameter, "statistic_id": "00011", "time": stamp, "value": value,
                           "unit_of_measure": "ft", "approval_status": "Provisional", "qualifier": ["estimated"],
                           "last_modified": stamp}}


class ClientTests(unittest.TestCase):
    def test_pagination_follows_next_and_keeps_leading_zero_ids(self):
        with workspace() as root:
            c = client.Client(root)
            next_url = client.BASE + "/monitoring-locations/items?cursor=abc"
            with patch.object(c, "fetch", side_effect=[{"features": [{"id": "USGS-00001"}],
                "links": [{"rel": "next", "href": next_url}]}, {"features": [{"id": "USGS-00002"}]}]) as fetch:
                rows = c.collect("stations", "monitoring-locations", {"state_code": "06"})
                self.assertEqual([f["id"] for f in rows], ["USGS-00001", "USGS-00002"])
                self.assertEqual(fetch.call_args.args[1], next_url)

    def test_duplicate_ids_and_cross_collection_pages_rejected(self):
        for next_url in (client.BASE + "/monitoring-locations/items?cursor=1", client.BASE + "/daily/items?cursor=1"):
            with workspace() as root:
                c = client.Client(root)
                with patch.object(c, "fetch", side_effect=[{"features": [{"id": "one"}], "links": [{"rel": "next", "href": next_url}]},
                                                           {"features": [{"id": "one"}]}]):
                    with self.assertRaises(ValueError):
                        c.collect("stations", "monitoring-locations", {})

    def test_missing_final_records_rejected(self):
        with workspace() as root:
            c = client.Client(root)
            with patch.object(c, "fetch", return_value={"features": [{"id": "one"}], "numberMatched": 2}):
                with self.assertRaises(ValueError):
                    c.collect("stations", "monitoring-locations", {})

    def test_raw_bytes_cache_and_hash_tampering(self):
        with workspace() as root:
            c = client.Client(root)
            raw = b'{ "features": [], "original_spacing": true }\n'
            response = Mock(status_code=200, headers={}, content=raw)
            with patch.object(c.session, "get", return_value=response) as get, patch("data.usgs_water.client.time.sleep"):
                c.fetch("sample", client.BASE + "/monitoring-locations/items")
                c.fetch("sample", client.BASE + "/monitoring-locations/items")
                self.assertEqual(get.call_count, 1)
            path = root / "raw/sample.gz"
            self.assertEqual(gzip.decompress(path.read_bytes()), raw)
            path.write_bytes(gzip.compress(b'{}'))
            with self.assertRaises(ValueError):
                c.fetch("sample", client.BASE + "/monitoring-locations/items")

    def test_rate_limit_preserves_retry_time_without_retry_storm(self):
        with workspace() as root:
            c = client.Client(root)
            response = Mock(status_code=429, headers={"Retry-After": "1800"})
            with patch.object(c.session, "get", return_value=response) as get:
                with self.assertRaisesRegex(RuntimeError, "rate limit"):
                    c.fetch("sample", client.BASE + "/monitoring-locations/items")
                self.assertEqual(get.call_count, 1)
            self.assertEqual(archive.read_json(root / "rate_limit.json")["retry_after_seconds"], 1800)


class InterpretationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 5, tzinfo=timezone.utc)
        self.metadata = {"primary": "Primary", "computation_identifier": "Instantaneous"}

    def test_zero_and_negative_stages_are_valid_provisional_values(self):
        for value in ("0", "-0.32"):
            row = refresh.normalize(reading(value), "latest-continuous")
            result = analysis.condition(row, self.metadata, self.now)
            self.assertEqual(result["status"], "available")
            self.assertEqual(result["approval_status"], "Provisional")
            self.assertIn("estimated", result["qualifier"])

    def test_missing_stale_future_and_units_are_distinct(self):
        cases = [(reading("NaN"), "invalid_value"), (reading("-999999"), "invalid_value"),
                 (reading(stamp="2020-01-01T00:00:00Z"), "stale"),
                 (reading(stamp="2026-10-21T00:00:00Z"), "future_timestamp")]
        changed = reading()
        changed["properties"]["unit_of_measure"] = "m"
        cases.append((changed, "unexpected_units"))
        for feature, expected in cases:
            self.assertEqual(analysis.condition(refresh.normalize(feature, "latest-continuous"), self.metadata, self.now)["status"], expected)

    def test_noninstantaneous_metadata_is_not_a_primary_current_candidate(self):
        result = analysis.condition(refresh.normalize(reading(), "latest-continuous"),
                                    {"primary": "Primary", "computation_identifier": "Max At Event Time"}, self.now)
        self.assertEqual(result["selection_status"], "alternative_or_missing_metadata")

    def test_operational_threshold_is_not_flood_stage(self):
        periods = [{"StartTime": "2020-01-01T00:00:00Z", "EndTime": "9999-12-31T23:59:59.9999999Z", "ReferenceValue": 23}]
        metadata = {"series": {"monitoring_location_id": "USGS-1", "parameter_code": "00065", "unit_of_measure": "ft",
                    "thresholds": [{"Name": "NWS Floodstage", "Periods": periods}, {"Name": "Operational maximum", "Periods": periods}]}}
        rows = analysis.applicable_thresholds(metadata, self.now)
        self.assertEqual([r["interpretation"] for r in rows], ["published_named_flood_reference", "operational_or_other_reference"])

    def test_naive_time_is_rejected(self):
        with self.assertRaises(ValueError):
            analysis.timestamp("2026-10-20T04:00:00")


class OrganizationTests(unittest.TestCase):
    def test_boundary_membership_keeps_both_regions(self):
        with workspace() as root:
            entry = {"name": "CalWater_Hydrologic_Unit", "key": "source/1", "object_id_field": "oid"}
            features = [{"geometry": mapping(box(0, 0, 1, 1)), "properties": {"oid": 1, "rbu": 11, "rb": 1, "huname": "One", "hbpaname": "Plan A"}},
                        {"geometry": mapping(box(1, 0, 2, 1)), "properties": {"oid": 2, "rbu": 22, "rb": 2, "huname": "Two", "hbpaname": "Plan B"}}]
            stations = [{"id": "USGS-001", "geometry": mapping(Point(1, .5))}, {"id": "USGS-002", "geometry": None}]
            with patch.object(relationships.reference, "open_snapshot", return_value=(root, {"datasets": [entry]})), \
                    patch.object(relationships.reference, "iter_snapshot_records", return_value=iter(features)):
                memberships, regions, _ = relationships.calwater_memberships(root, stations, root)
            self.assertEqual(len(memberships), 2)
            self.assertTrue(all(r["status"] == "multiple_spatial_matches" for r in memberships))
            self.assertEqual({r["region"] for r in regions}, {"01_north_coast", "02_san_francisco_bay", "unassigned"})

    def test_discard_interval_data_preserves_latest_and_inventory(self):
        with workspace() as root:
            stage = root / "observations/.pending-test"
            archive.write_json(stage / "raw/continuous_00065/00001.gz", {"historical": True})
            archive.write_json(stage / "raw/latest-continuous_00065/00001.gz", {"current": True})
            refresh.discard_interval_files(stage)
            self.assertFalse((stage / "raw/continuous_00065").exists())
            self.assertTrue((stage / "raw/latest-continuous_00065/00001.gz").exists())
            with self.assertRaises(ValueError):
                refresh.remove_owned_directory(root, stage)

    def test_success_replaces_levels_failure_keeps_last_good_snapshot(self):
        with workspace() as root:
            stage, identifier = archive.begin(root, "inventory")
            archive.write_json(stage / "stations.geojson.gz", {"features": [{"id": "USGS-00123456"}]})
            archive.write_json(stage / "time_series.geojson.gz", {"features": [{"id": "series-1", "properties": {
                "monitoring_location_id": "USGS-00123456", "parameter_code": "00065", "primary": "Primary",
                "computation_identifier": "Instantaneous"}}]})
            relationships.table(stage, "station_identifiers", [], ("station_id", "nwps_lid"))
            archive.publish(root, stage, identifier, "inventory", {})
            def pages(self, name, collection, params):
                yield [reading()] if params["parameter_code"] == "00065" else []
            with patch.object(client.Client, "pages", pages):
                first = refresh.refresh_observations(root)
                second = refresh.refresh_observations(root)
            self.assertFalse(first.exists())
            self.assertTrue(second.exists())
            pointer = archive.read_json(root / "observations.json")
            with patch.object(client.Client, "pages", side_effect=RuntimeError("network unavailable")):
                with self.assertRaises(RuntimeError):
                    refresh.refresh_observations(root)
            self.assertEqual(archive.read_json(root / "observations.json"), pointer)
            archive.open_generation(root, "observations")


if __name__ == "__main__":
    unittest.main()
