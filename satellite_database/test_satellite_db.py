"""Behavior tests: missing capabilities, failures, stale evidence, refresh safety."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import shutil
import uuid
import unittest
from unittest.mock import patch

import satellite_db as app
from catalog import classify, normalize_operation, tle_epoch
from reports import parse_amsat_reports, match_operation
from sources import SourceReader


class TestDirectory:
    """Workspace-local test files; normal inherited Windows permissions."""
    def __init__(self):
        self.path = app.HERE / ("test-work-" + uuid.uuid4().hex)
        self.path.mkdir(mode=0o777)
        self.name = str(self.path)

    def cleanup(self):
        resolved = self.path.resolve()
        if resolved.parent != app.HERE or not resolved.name.startswith("test-work-"):
            raise ValueError("Refusing to clean outside the test workspace")
        shutil.rmtree(resolved)

    def __enter__(self):
        return self.name

    def __exit__(self, *args):
        self.cleanup()


def time_ago(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days, seconds=1)).isoformat()


def transmitter(identity="beacon", **changes):
    row = {"uuid": identity, "sat_id": "sat1", "description": "CW beacon", "mode": "CW", "type": "Transmitter",
           "downlink_low": 435000000, "uplink_low": None, "service": "Amateur", "status": "active", "updated": time_ago(100)}
    row.update(changes)
    return row


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TestDirectory()
        self.root = Path(self.temp.name)
        self.settings = app.settings_from(app.HERE / "settings.json")
        self.settings.update(database=self.root / "test.sqlite3", cache_directory=self.root / "raw", export_directory=self.root / "export")
        self.overrides = self.root / "overrides.json"
        self.overrides.write_text('{}', encoding="utf-8")
        self.satellites = [{"sat_id": "sat1", "norad_cat_id": 12345, "name": "TestSat", "status": "in orbit"}]
        self.transmitters = [transmitter(), transmitter("repeater", description="FM repeater", mode="FM", uplink_low=145990000)]

    def tearDown(self):
        self.temp.cleanup()

    def refresh(self, tx=None, fail=False):
        data = {self.settings["sources"]["satellites"]: self.satellites,
                self.settings["sources"]["transmitters"]: tx if tx is not None else self.transmitters,
                self.settings["sources"]["amsat"]: [{"name": "TestSat", "satnogs_id": "sat1", "norad_id": "12345"}]}
        def records(reader, url, field):
            if fail:
                raise ValueError("Source unavailable")
            reader.receipts.append({"url": url, "fetched_at": time_ago(), "sha256": "fixture"})
            return data[url]
        args = argparse.Namespace(offline=True, no_celestrak=True, overrides=self.overrides)
        with patch.object(SourceReader, "records", records), patch.object(SourceReader, "read", side_effect=ValueError("No report fixture")), patch.object(app, "fetch_orbits", return_value=[]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return app.refresh(self.settings, args)

    def evidence(self, operation, status="active", days=0, kind="reception_report"):
        return {"operation_id": "satnogs:" + operation, "status": status, "observed_at": time_ago(days),
                "source_url": "https://example.org/operator", "note": "Explicit test evidence", "evidence_kind": kind}

    def save(self, *observations):
        db = app.connect(self.settings)
        try:
            ids = {r[0] for r in db.execute("SELECT operation_id FROM operations")}
            with db:
                for observation in observations:
                    app.validate_observation(observation, ids)
                    app.save_observation(db, observation)
        finally:
            db.close()

    def rows(self):
        db = app.connect(self.settings)
        try:
            return {r["operation_id"]: r for r in app.operation_rows(db, self.settings)}
        finally:
            db.close()

    def test_only_existing_capabilities_are_created(self):
        self.refresh()
        self.assertEqual(set(self.rows()), {"satnogs:beacon", "satnogs:repeater"})
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.save(self.evidence("sstv", "inactive", kind="confirmed_failure"))

    def test_repeater_failure_does_not_disable_beacon(self):
        self.refresh()
        self.save(self.evidence("repeater", "inactive", kind="confirmed_failure"), self.evidence("beacon"))
        rows = self.rows()
        self.assertEqual(rows["satnogs:repeater"]["current_status"], "inactive")
        self.assertEqual(rows["satnogs:beacon"]["current_status"], "active")

    def test_not_heard_is_not_failure(self):
        self.refresh()
        with self.assertRaisesRegex(ValueError, "confirmed_failure"):
            self.save(self.evidence("repeater", "inactive"))
        self.save(self.evidence("repeater", "unknown"))
        self.assertEqual(self.rows()["satnogs:repeater"]["current_status"], "unknown")

    def test_catalog_inactive_does_not_prove_broken(self):
        self.refresh([transmitter(status="inactive")])
        op = self.rows()["satnogs:beacon"]
        self.assertEqual(op["catalog_status"], "inactive")
        self.assertEqual(op["current_status"], "unknown")

    def test_scheduled_off_is_separate(self):
        self.refresh()
        self.save(self.evidence("repeater", "scheduled_off", kind="operator_schedule"))
        self.assertEqual(self.rows()["satnogs:repeater"]["current_status"], "scheduled_off")

    def test_stale_and_future_evidence(self):
        self.refresh()
        self.save(self.evidence("beacon", days=31))
        self.assertEqual(self.rows()["satnogs:beacon"]["current_status"], "unknown")
        with self.assertRaisesRegex(ValueError, "nonfuture"):
            self.save(self.evidence("beacon", days=-1))

    def test_conflicting_same_interval_is_unknown(self):
        self.refresh()
        active = self.evidence("beacon")
        unknown = dict(active, status="unknown", note="Not heard at another station")
        self.save(active, unknown)
        row = self.rows()["satnogs:beacon"]
        self.assertEqual(row["current_status"], "unknown")
        self.assertTrue(row["conflicting_evidence"])

    def test_removed_capability_retained_without_failure(self):
        self.refresh()
        self.refresh([transmitter()])
        row = self.rows()["satnogs:repeater"]
        self.assertFalse(row["present_in_latest_source"])
        self.assertEqual(row["current_status"], "unknown")

    def test_repeated_refresh_does_not_duplicate(self):
        self.refresh()
        self.refresh()
        self.assertEqual(len(self.rows()), 2)
        db = app.connect(self.settings)
        try:
            self.assertEqual(db.execute("SELECT count(*) FROM operation_versions").fetchone()[0], 2)
        finally:
            db.close()

    def test_source_failure_preserves_database(self):
        self.refresh()
        before = self.settings["database"].read_bytes()
        with self.assertRaises(ValueError):
            self.refresh(fail=True)
        self.assertEqual(before, self.settings["database"].read_bytes())

    def test_invalid_observation_rolls_back_before_update(self):
        self.refresh()
        before = self.settings["database"].read_bytes()
        self.overrides.write_text(json.dumps({"observations": [self.evidence("missing")]}))
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual(before, self.settings["database"].read_bytes())

    def test_no_uplink_is_unknown_not_assumed_impossible(self):
        self.refresh()
        self.assertEqual(self.rows()["satnogs:beacon"]["uplink_availability"], "unknown")

    def test_frequency_span_is_not_signal_bandwidth(self):
        tx = transmitter(downlink_high=435050000, type="Transponder")
        op = normalize_operation(tx, "sat1", ["beacon"], "test", "https://example.org", time_ago())
        self.assertEqual(op["passband_width_hz"], 50000)
        self.assertIsNone(op["occupied_bandwidth_hz"])

    def test_downlink_sstv_and_weather_are_in_scope(self):
        for tx, scope in [(transmitter(mode="SSTV", description="Image"), "image_downlink"),
                          (transmitter(mode="BPSK", description="HRIT EMWIN", service="Meteorological", downlink_low=1694100000), "weather_alerts")]:
            scopes, _ = classify(tx, False, self.settings)
            self.assertIn(scope, scopes)

    def test_fm_packet_is_not_voice(self):
        tx = transmitter(mode="FM", description="APRS digipeater", uplink_low=145825000)
        scopes, _ = classify(tx, True, self.settings)
        self.assertIn("two_way_data", scopes)
        self.assertNotIn("two_way_voice", scopes)

    def test_sstv_does_not_invent_modulation(self):
        tx = transmitter(mode="SSTV", description="SSTV")
        op = normalize_operation(tx, "sat1", ["image_downlink"], "test", "https://example.org", time_ago())
        self.assertIsNone(op["modulation"])
        self.assertEqual(op["protocols"], ["SSTV"])

    def test_decayed_satellite_excluded_entirely(self):
        self.satellites[0]["status"] = "re-entered"
        self.refresh()
        self.assertEqual(self.rows(), {})

    def test_newly_retired_satellite_pruned_on_refresh(self):
        self.refresh()
        self.save(self.evidence("beacon"))
        self.satellites[0]["status"] = "re-entered"
        self.refresh()
        self.assertEqual(self.rows(), {})
        db = app.connect(self.settings)
        try:
            for table in ("satellites", "operations", "observations", "operation_versions", "operation_scopes"):
                self.assertEqual(db.execute("SELECT count(*) FROM " + table).fetchone()[0], 0)
        finally:
            db.close()

    def test_operator_retirement_overrides_in_orbit(self):
        self.overrides.write_text(json.dumps({"retired_satellites": [{"names": ["TestSat"], "source_url": "https://example.org", "reason": "Decommissioned"}]}))
        self.refresh()
        self.assertEqual(self.rows(), {})

    def test_export_has_all_capabilities_and_sources(self):
        self.refresh()
        data = app.read_json(self.settings["export_directory"] / "satellites.json")
        self.assertEqual(len(data["operations"]), 2)
        self.assertIn("source_url", data["operations"][0])
        self.assertTrue((self.settings["export_directory"] / "operations.csv").exists())

    @unittest.skipUnless(importlib.util.find_spec("skyfield"), "optional Skyfield not installed")
    def test_position_serialization_and_stale_elements(self):
        self.refresh()
        db = app.connect(self.settings)
        try:
            epoch = time_ago()
            elements = {"OBJECT_NAME": "TestSat", "OBJECT_ID": "2024-001A", "EPOCH": epoch,
                        "MEAN_MOTION": 15.5, "ECCENTRICITY": 0.0003, "INCLINATION": 51.6,
                        "RA_OF_ASC_NODE": 120.0, "ARG_OF_PERICENTER": 140.0, "MEAN_ANOMALY": 205.0,
                        "EPHEMERIS_TYPE": 0, "CLASSIFICATION_TYPE": "U", "NORAD_CAT_ID": 12345,
                        "ELEMENT_SET_NO": 1, "REV_AT_EPOCH": 1, "BSTAR": 0.0001,
                        "MEAN_MOTION_DOT": 0.0, "MEAN_MOTION_DDOT": 0.0}
            with db:
                db.execute("INSERT INTO orbits VALUES (?,?,?,?,?,?)", ("sat1", "https://example.org", "OMM_JSON", epoch, epoch, json.dumps(elements)))
            args = argparse.Namespace(satellite="12345", latitude=37.7749, longitude=-122.4194, altitude=20, at=epoch)
            output = io.StringIO()
            with redirect_stdout(output):
                app.position(db, self.settings, args)
            data = json.loads(output.getvalue())
            self.assertIsInstance(data["above_geometric_horizon"], bool)
            self.assertTrue(0 <= data["azimuth_true_deg"] <= 360)
            self.assertTrue(-90 <= data["elevation_deg"] <= 90)
            self.assertGreater(data["range_km"], 0)
            args.at = time_ago(30)
            with self.assertRaisesRegex(ValueError, "refresh before calculating"):
                app.position(db, self.settings, args)
        finally:
            db.close()


class ParserAndCacheTests(unittest.TestCase):
    def test_report_parsing_and_time_interval(self):
        page = """tips.a1 = new Array( 5, 5, 120, 'Heard<br>N0CALL<br>AA00<br>2026-09-24<br>9:16-:30 UTC');
<tr><td><a>TEST_[FM]</a></td><td onMouseOver=docTips.show('a1')>1</td></tr>"""
        rows = parse_amsat_reports(page)
        self.assertEqual(rows[0]["reported_status"], "Heard")
        self.assertEqual(rows[0]["observed_at"], "2026-09-24T09:16:00+00:00")

    def test_broken_report_page_fails_visibly(self):
        with self.assertRaises(ValueError):
            parse_amsat_reports("<html>Site unavailable</html>")

    def test_ambiguous_modes_not_assigned(self):
        sats = {"s": {"satellite_id": "s", "name": "TEST"}}
        ops = {key: {"satellite_id": "s", "operation_id": key, "source_reported_status": "active", "source_mode": "SSTV", "scopes": ["image_downlink"], "protocols": ["SSTV"]} for key in ("one", "two")}
        report = {"satellite_label": "TEST", "mode_label": "SSTV"}
        self.assertIsNone(match_operation(report, sats, ops, {}))

    def test_tle_epoch_not_download_time(self):
        self.assertEqual(tle_epoch('1 25544U 98067A   26267.00000000  .00000000'), "2026-09-24T00:00:00+00:00")

    def test_offline_cache_checksum_and_original_timestamp(self):
        with TestDirectory() as directory:
            settings = app.settings_from(app.HERE / "settings.json")
            url = "https://example.org/data"
            key = hashlib.sha256(url.encode()).hexdigest()
            body = b'[]'
            meta = {"url": url, "fetched_at": time_ago(40), "sha256": hashlib.sha256(body).hexdigest()}
            path = Path(directory)
            (path / (key + ".body")).write_bytes(body)
            (path / (key + ".json")).write_text(json.dumps(meta))
            reader = SourceReader(path, settings, offline=True)
            self.assertEqual(reader.read(url)[1]["fetched_at"], meta["fetched_at"])
            (path / (key + ".body")).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, "checksum"):
                reader.read(url)

    def test_pagination_collects_all_pages(self):
        with TestDirectory() as directory:
            reader = SourceReader(directory, app.settings_from(app.HERE / "settings.json"))
            pages = [(json.dumps({"results": [{"id": 1}], "next": "?page=2"}).encode(), {}),
                     (json.dumps({"results": [{"id": 2}], "next": None}).encode(), {})]
            with patch.object(reader, "read", side_effect=pages):
                self.assertEqual(len(reader.records("https://example.org/data", "id")), 2)


if __name__ == "__main__":
    unittest.main()
