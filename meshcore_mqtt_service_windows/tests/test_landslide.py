"""Offline California/Nevada boundary, CAP lifecycle, point cache, and subscription regressions."""

import asyncio
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing, redirect_stdout
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import landslide_alerts as alerts, landslide_lookup as lookup
from scripts.landslide_data import nearest_station, reference, require_supported_location
from scripts.landslide_settings import validate
from landslide_service import LandslideAlarms, changes
from responder import Responder, match_command, validate_config, reply_parts

NOW = 1792500000
POINT = [34.15, -118.14]


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def feature(key="a", **overrides):
    props = dict(id=key, event="Flash Flood Warning", status="Actual", messageType="Alert",
                 effective=iso(NOW - 60), sent=iso(NOW - 60), expires=iso(NOW + 7200),
                 headline="Debris flows possible in the burn area", description="Rapid debris flows expected.",
                 instruction="Follow local instructions.", senderName="NWS Test Office", severity="Severe",
                 areaDesc="Test area", references=[])
    props.update(overrides)
    return dict(type="Feature", id=key, properties=props, geometry=None)


def collection(*features):
    return dict(type="FeatureCollection", features=list(features))


def snapshot(now=NOW, records=None):
    raw = collection(feature()) if records is None else collection(*records)
    return dict(alerts.select_alerts(raw, now), raw=raw, point=POINT.copy(), fetched=now,
                source="https://api.weather.gov/alerts/active?point=34.15,-118.14", coverage="test")


class LocationAndCatalogTests(unittest.TestCase):
    def test_station_name_is_complete_or_absent_never_an_excerpt(self):
        station = nearest_station(*POINT)
        for name in (station['name'], 'Station ' + '温' * 80):
            for sender in ('Alice', 'a' * 80, '温' * 26):
                with self.subTest(name=name, sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                    text = lookup.format_station(dict(station, name=name), 'Pasadena')
                    parts = reply_parts(sender, text, max_parts=1)
                    self.assertEqual(len(parts), 1)
                    self.assertLessEqual(len(parts[0].encode()), 150)
                    self.assertIn('telemetry unverified; not local coverage.', text)
                    self.assertNotIn('...', text)
                    if name == station['name'] and sender == 'Alice':
                        self.assertTrue(text.endswith(name))
                        self.assertNotIn("Catalog checked", text)
                    else:
                        self.assertNotIn(name.split()[0], text)

    def test_near_cli_preserves_catalog_uncertainty_and_distance(self):
        station = nearest_station(*POINT)
        for sender in ('Alice', 'a' * 80):
            output = io.StringIO()
            with patch.dict(os.environ, {'MESHCORE_SENDER': sender}), redirect_stdout(output):
                self.assertEqual(lookup.main('slideinfo', ['near', '34.15', '-118.14']), 0)
            parts = reply_parts(sender, output.getvalue().strip(), max_parts=1)
            self.assertEqual(len(parts), 1)
            self.assertLessEqual(len(parts[0].encode()), 150)
            self.assertIn('telemetry unverified', parts[0])
            self.assertIn('not local coverage', parts[0])
            self.assertIn(station['id'], parts[0])
            if sender == 'Alice':
                self.assertIn(f"{station['distance_miles']:.1f}mi", parts[0])
                self.assertTrue(parts[0].endswith(station["name"]))

    def test_existing_location_grammar_and_default_state(self):
        for command in lookup.COMMANDS:
            for location in ("91107", "91107-1234", "Pasadena", "Pasadena CA", "Pasadena, California",
                             "89501", "Reno NV", "Reno, Nevada", "Las Vegas NV", "Elko Nevada",
                             "34.15 -118.14", "34.15,-118.14", "34.15, -118.14"):
                query = ("on " if command == "slidealarm" else "") + location
                with self.subTest(command=command, location=location):
                    self.assertEqual(lookup.parse_query(command, query)["target"], location)

    def test_city_and_zip_share_flood_resolver(self):
        with patch.object(lookup, "resolve_location", return_value=POINT) as resolver:
            self.assertEqual(lookup.resolve("Pasadena"), tuple(POINT))
            self.assertEqual(resolver.call_args.args[0], ("city", "Pasadena", "California"))
            lookup.resolve("91107")
            self.assertEqual(resolver.call_args.args[0], ("zip", "91107", None))

    def test_actual_state_boundary_not_fire_zone_or_rectangle(self):
        for lat, lon in (POINT, (38.58, -121.49), (33.38, -118.42), (41.9, -122.5),
                         (39.25, -119.96), (39.26, -119.96), (39.53, -119.81),
                         (36.17, -115.14), (40.83, -115.76)):
            self.assertEqual(require_supported_location(lat, lon), (lat, lon))
        for point in ((42.1, -122.0), (42.1, -115.0), (40.0, -113.9), (35.0, -114.0), (32.1, -116.0),
                      (34.0, -124.0), (float("nan"), -120), (True, -120)):
            with self.subTest(point=point), self.assertRaises(ValueError):
                require_supported_location(*point)

    def test_nevada_points_work_for_every_command(self):
        for point in ((39.25, -119.96), (39.53, -119.81), (36.17, -115.14), (40.83, -115.76)):
            for command in lookup.COMMANDS:
                query = ("on " if command == "slidealarm" else "") + f"{point[0]},{point[1]}"
                target = lookup.parse_query(command, query)["target"]
                self.assertEqual(lookup.resolve(target), point)
            station = nearest_station(*point)
            self.assertIn("telemetry unverified; not local coverage.", lookup.format_station(station, str(point)))
            data = dict(snapshot(), point=list(point))
            self.assertEqual(lookup.checked_snapshot(data, validate({}), NOW)["point"], list(point))

    def test_nevada_city_and_zip_share_flood_resolver(self):
        point = (39.53, -119.81)
        for command in lookup.COMMANDS:
            for location, parsed in (("Reno NV", ("city", "Reno", "Nevada")),
                                     ("89501", ("zip", "89501", None))):
                query = ("on " if command == "slidealarm" else "") + location
                target = lookup.parse_query(command, query)["target"]
                with patch.object(lookup, "resolve_location", return_value=point) as resolver:
                    self.assertEqual(lookup.resolve(target), point)
                    self.assertEqual(resolver.call_args.args[0], parsed)

    def test_geocoded_out_of_state_point_rejected(self):
        with patch.object(lookup, "resolve_location", return_value=(40.76, -111.89)):
            with self.assertRaisesRegex(ValueError, "California"):
                lookup.resolve("84101")
        with self.assertRaisesRegex(ValueError, "California"):
            lookup.parse_query("slidewarn", "Salt Lake City UT")

    def test_invalid_inputs_and_alarm_controls(self):
        for query in ("on", "Pasadena", "on 91 -118", "on NaN,-118", "on 1 2 3"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                lookup.parse_query("slidealarm", query)
        for action in ("off", "status", "help"):
            self.assertEqual(lookup.parse_query("slidealarm", action)["action"], action)
        self.assertEqual(lookup.parse_query("slideinfo", "near Pasadena")["target"], "Pasadena")

    def test_catalog_and_castro_peak_provenance(self):
        _, stations, manifest = reference()
        self.assertEqual(len(stations), 13)
        self.assertEqual(manifest["station_count"], 13)
        castro = next(s for s in stations if s["id"] == "CASTRO-PEAK")
        self.assertIn("node-349227.geojson", castro["coordinate_source"])
        self.assertEqual(nearest_station(34.084791, -118.786117)["id"], "CASTRO-PEAK")
        self.assertEqual(nearest_station(37.761629, -122.077970)["id"], "BALT1")
        self.assertNotEqual(nearest_station(38.777177, -120.419731)["id"], "HWY50")
        for station in stations:
            require_supported_location(*reversed(station["coordinates"]))

    def test_station_output_never_claims_current_measurement(self):
        result = lookup.format_station(nearest_station(*POINT), "Pasadena")
        self.assertIn("telemetry unverified", result)
        self.assertIn("not local coverage", result)
        self.assertLessEqual(len(("@Reader " + result).encode()), 150)


class AlertTests(unittest.TestCase):
    def test_warn_and_watch_names_retained_including_null_geometry(self):
        for event in ("Flash Flood Warning", "Flood Watch", "Special Weather Statement"):
            a = alerts.select_alerts(collection(feature(event=event)), NOW)["alerts"]["a"]
            self.assertEqual(a["event"], event)
            self.assertIsNone(a["geometry"])
            self.assertIn(event, lookup.alert_summary(a))

    def test_unrelated_flood_and_fire_alerts_excluded(self):
        result = alerts.select_alerts(collection(feature(headline="Flooding", description="Heavy rain expected.",
                                                         instruction="Move to higher ground.")), NOW)
        self.assertEqual(result["alerts"], {})

    def test_hazard_spelling_and_qualified_mentions(self):
        for term in ("landslide", "landslides", "debris-flow", "debris flows", "mudslides", "mud flows"):
            self.assertIsNotNone(alerts.relevance(dict(description=term)))
        self.assertIn("precautionary", alerts.relevance(dict(instruction="Watch for mudslides.")))
        self.assertIn("qualified", alerts.relevance(dict(description="Debris flows are not expected.")))

    def test_expired_future_test_and_cancel_are_not_active(self):
        for override in (dict(expires=iso(NOW)), dict(ends=iso(NOW)), dict(effective=iso(NOW + 60)),
                         dict(status="Test"), dict(messageType="Cancel")):
            self.assertFalse(alerts.select_alerts(collection(feature(**override)), NOW)["alerts"])
        # Future onset does not hide an already-effective watch.
        self.assertTrue(alerts.select_alerts(collection(feature(event="Flood Watch", onset=iso(NOW + 3600))), NOW)["alerts"])

    def test_references_supersede_old_alert_and_cancel(self):
        updated = feature("b", messageType="Update", references=[dict(identifier="a")])
        result = alerts.select_alerts(collection(feature(), updated), NOW)
        self.assertEqual(set(result["alerts"]), {"b"})
        cancelled = feature("c", messageType="Cancel", references=[dict(identifier="a")])
        result = alerts.select_alerts(collection(feature(), cancelled), NOW)
        self.assertFalse(result["alerts"])
        self.assertEqual(result["cancelled_ids"], ["a"])

    def test_incomplete_malformed_and_duplicate_feeds_fail_closed(self):
        for value in ({}, dict(collection(), pagination={"next": "next"}), collection(feature(), feature()),
                      collection(feature(status="invalid")), collection(feature(expires="bad")),
                      collection(feature(headline=42)), collection({"properties": None})):
            with self.subTest(value=value), self.assertRaises((ValueError, RuntimeError)):
                alerts.select_alerts(value, NOW)

    def test_coverage_required_before_empty_alerts(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return {"type": "Feature", "properties": {"forecastZone": "zone"}} if "/points/" in url else collection()
        for point in (POINT, (39.25, -119.96), (39.53, -119.81), (36.17, -115.14)):
            calls.clear()
            self.assertFalse(alerts.fetch_point(*point, now=NOW, fetch=fetch)["alerts"])
            self.assertIn(f"/points/{point[0]:.6f},{point[1]:.6f}", calls[0])
            self.assertIn("point=", calls[1])
        with self.assertRaisesRegex(ValueError, "coverage"):
            alerts.fetch_point(*POINT, now=NOW, fetch=lambda url: {})

    def test_empty_and_limited_output(self):
        text = lookup.format_alerts(snapshot(records=[]), "Pasadena", validate({}))
        self.assertIn("No NWS landslide mentions", text)
        self.assertIn("not an all-clear", text)
        text = lookup.format_alerts(snapshot(records=[feature(str(i)) for i in range(4)]), "Pasadena", validate({}))
        self.assertIn("+3 alerts", text)
        self.assertIn("NWS Flash Flood Warning", text)

    def test_fresh_snapshot_validation(self):
        for invalid in (dict(snapshot(), fetched=NOW - 301), dict(snapshot(), fetched=NOW + 1),
                        dict(snapshot(), point=[40.76, -111.89]), {"error": "offline"}):
            with self.assertRaises(ValueError):
                lookup.checked_snapshot(invalid, validate({}), NOW)

    def test_meaningful_update_and_expiry(self):
        before = snapshot()
        after = snapshot(records=[feature("b", messageType="Update", references=[dict(identifier="a")])])
        self.assertEqual(changes(before, after, NOW), [])
        after = snapshot(records=[feature("b", messageType="Update", description="Debris flows observed.", references=[dict(identifier="a")])])
        self.assertIn("| Updated", changes(before, after, NOW)[0])
        self.assertIn("expired", changes(before, snapshot(records=[]), NOW + 7200)[0])
        self.assertIn("cancellation unconfirmed", changes(before, snapshot(records=[]), NOW)[0])


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "landslide.sqlite3"
        self.config = validate({})

    def tearDown(self):
        self.temp.cleanup()

    def test_shared_cache_and_expiry_rechecked(self):
        calls = []
        def fetch(lat, lon, now=None):
            calls.append((lat, lon))
            return snapshot(now, [feature(expires=iso(NOW + 60))])
        alerts.snapshot(*POINT, self.config, self.path, NOW, fetch)
        result = alerts.snapshot(*POINT, self.config, self.path, NOW + 61, fetch)
        self.assertEqual(len(calls), 1)
        self.assertFalse(result["alerts"])
        self.assertEqual(result["fetched"], NOW)

    def test_failed_refresh_preserves_data_but_cannot_claim_clear(self):
        alerts.snapshot(*POINT, self.config, self.path, NOW, lambda *a, **k: snapshot())
        def fail(*args, **kwargs):
            raise OSError("offline")
        with self.assertRaisesRegex(ValueError, "unavailable"):
            alerts.snapshot(*POINT, self.config, self.path, NOW + 301, fail)
        with self.assertRaisesRegex(ValueError, "previous data retained"):
            alerts.snapshot(*POINT, self.config, self.path, NOW + 302, fail)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT fetched FROM points").fetchone()[0], NOW)
            self.assertTrue(json.loads(db.execute("SELECT body FROM points").fetchone()[0])["alerts"])
        result = alerts.snapshot(*POINT, self.config, self.path, NOW + 602,
                                 lambda *a, **k: snapshot(NOW + 602, []))
        self.assertFalse(result["alerts"])

    def test_unknown_schema_preserved(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version=42")
        with self.assertRaisesRegex(ValueError, "schema"):
            alerts.snapshot(*POINT, self.config, self.path, NOW)

    def test_failed_refresh_also_bounds_cache_growth(self):
        alerts.snapshot(*POINT, self.config, self.path, NOW, lambda *a, **k: snapshot())
        with closing(sqlite3.connect(self.path)) as db:
            db.executemany("INSERT INTO points VALUES(?,?,?,?,?)",
                           [(str(i), None, NOW - 1, None, "offline") for i in range(1005)])
            db.execute("INSERT INTO points VALUES(?,?,?,?,?)", ("old", None, NOW - 8 * 86400, None, "offline"))
            db.commit()
        def fail(*args, **kwargs):
            raise OSError("offline")
        with self.assertRaisesRegex(ValueError, "unavailable"):
            alerts.snapshot(*POINT, self.config, self.path, NOW + 301, fail)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM points").fetchone()[0], 1000)
            self.assertIsNone(db.execute("SELECT * FROM points WHERE point='old'").fetchone())


class AlarmTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.now, self.records, self.failure = NOW, [feature()], False
        self.read_targets = []
        async def read(target):
            self.read_targets.append(target)
            if self.failure:
                raise ValueError("offline")
            return snapshot(self.now, self.records)
        self.read = read
        self.notify = AsyncMock()
        self.alarms = LandslideAlarms(self.db, "default", "identity", {}, read, self.notify,
                                      lambda: True, lambda: self.now)
        self.request = dict(command="!slidealarm", sender="Sam", id="one", sender_timestamp=NOW,
                            arguments=["on Pasadena"])

    def tearDown(self):
        self.db.close()

    async def enroll(self):
        self.assertTrue(self.alarms.remember(self.request, self.now))
        text, detail = await self.alarms.control(self.request)
        self.assertIn("monitoring set", text.lower())
        self.assertEqual(detail, "")
        self.assertFalse(self.alarms.current(self.alarms.row("Sam")))
        self.alarms.acknowledge(self.request)

    async def test_fresh_baseline_ack_and_fixed_point(self):
        await self.enroll()
        self.now += 301
        await self.alarms.check_one()
        self.assertEqual(self.read_targets[-1], "34.15 -118.14")
        self.notify.assert_not_awaited()

    async def test_nevada_subscription_keeps_resolved_point(self):
        point = [36.17, -115.14]
        async def read(target):
            self.read_targets.append(target)
            return dict(snapshot(self.now), point=point.copy())
        self.alarms.read = read
        self.request = dict(self.request, arguments=["on Las Vegas NV"])
        await self.enroll()
        self.now += 301
        await self.alarms.check_one()
        self.assertEqual(self.read_targets[-1], "36.17 -115.14")
        self.assertTrue(self.alarms.current(self.alarms.row("Sam")))

    async def test_outage_and_recovery_preserve_baseline(self):
        await self.enroll()
        baseline = self.alarms.row("Sam")["baseline"]
        self.failure = True
        for _ in range(2):
            self.now += 301
            await self.alarms.check_one()
        self.assertEqual(self.notify.await_count, 1)
        self.assertEqual(self.alarms.row("Sam")["baseline"], baseline)
        self.failure = False
        self.now += 301
        await self.alarms.check_one()
        self.assertIn("available again", self.notify.await_args.args[1])

    async def test_failed_enrollment_does_not_enable(self):
        self.failure = True
        self.alarms.remember(self.request, self.now)
        text, _ = await self.alarms.control(self.request)
        self.assertIn("not started", text)
        self.assertFalse(self.alarms.row("Sam")["enabled"])

    async def test_off_revision_expiry_and_delayed_request(self):
        await self.enroll()
        old = self.alarms.row("Sam")
        off = dict(self.request, id="two", sender_timestamp=NOW + 1, arguments=["off"])
        self.assertTrue(self.alarms.remember(off, self.now))
        self.assertFalse(self.alarms.current(old))
        self.assertFalse(self.alarms.control_current(self.request))
        self.assertFalse(self.alarms.remember(self.request, self.now))
        self.assertFalse(await self.alarms.check_one())

    async def test_renewal_and_location_replacement(self):
        await self.enroll()
        self.now += 100
        old = self.alarms.row("Sam")
        self.request = dict(self.request, id="two", sender_timestamp=NOW + 100, arguments=["on 91107"])
        await self.enroll()
        new = self.alarms.row("Sam")
        self.assertEqual(new["target"], "91107")
        self.assertEqual(new["expires"], old["expires"] + 100)
        self.assertFalse(self.alarms.current(old))
        self.now = new["expires"]
        self.assertFalse(await self.alarms.check_one())

    async def test_cancel_during_pending_enrollment(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def delayed(target):
            entered.set()
            await finish.wait()
            return snapshot(self.now)
        self.alarms.read = delayed
        self.alarms.remember(self.request, self.now)
        task = asyncio.create_task(self.alarms.control(self.request))
        await entered.wait()
        self.alarms.remember(dict(self.request, id="off", sender_timestamp=NOW + 1, arguments=["off"]), self.now)
        finish.set()
        self.assertIn("superseded", (await task)[0])
        self.assertFalse(self.alarms.row("Sam")["enabled"])

    async def test_restart_identity_and_channel_isolation(self):
        await self.enroll()
        restarted = LandslideAlarms(self.db, "default", "identity", {}, self.read, self.notify,
                                    lambda: True, lambda: self.now)
        self.assertTrue(restarted.current(restarted.row("Sam")))
        other = LandslideAlarms(self.db, "other", "identity", {}, self.read, self.notify,
                                lambda: True, lambda: self.now)
        self.assertIsNone(other.row("Sam"))
        changed = LandslideAlarms(self.db, "default", "new-key", {}, self.read, self.notify,
                                  lambda: True, lambda: self.now)
        self.assertFalse(changed.row("Sam")["enabled"])

    async def test_removed_channel_and_command_disable(self):
        from channels import bind_state
        await self.enroll()
        bind_state(self.db, {})
        self.assertFalse(self.alarms.row("Sam")["enabled"])

    async def test_one_shot_cannot_enroll(self):
        for command in ("!slidewarn", "!slideinfo"):
            self.assertFalse(self.alarms.remember(dict(self.request, command=command), self.now))
        self.assertIsNone(self.alarms.row("Sam"))


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    def test_registrations_and_validation(self):
        config = json.loads((ROOT / "config.json").read_bytes())["responder"]
        validate_config(config, ROOT)
        for command in lookup.COMMANDS:
            text = "!" + command + (" on 91107" if command == "slidealarm" else " 91107")
            self.assertIsNone(match_command(text, config["commands"])[2])

    def test_settings_reject_unsafe_values(self):
        for settings in ({"cache_seconds": 0}, {"cache_seconds": 901}, {"subscription_hours": 25},
                         {"enabled": 1}, {"max_alerts": 1.5}, {"bad": 1}):
            with self.assertRaises(ValueError):
                validate(settings)

    def test_standalone_alarm_never_claims_enrollment(self):
        with patch.object(lookup, "resolve", return_value=POINT), patch.object(alerts, "snapshot", return_value=snapshot()):
            stream = io.StringIO()
            with redirect_stdout(stream):
                lookup.main("slidealarm", ["on", "Pasadena"])
            self.assertIn("no subscription created", stream.getvalue())

    async def test_service_controls_and_guarded_delivery(self):
        db = sqlite3.connect(":memory:")
        try:
            config = json.loads((ROOT / "config.json").read_bytes())["responder"]
            config["sender_cooldown"] = 0
            send = AsyncMock()
            bot = Responder(ROOT, db, config, 3, "Bot", send)
            now = int(time.time())
            bot.slide_alarms.read = AsyncMock(return_value=snapshot(now, []))
            def packet(phrase, timestamp):
                return dict(channel_idx=3, txt_type=0, text="Sam: " + phrase, sender_timestamp=timestamp)
            self.assertTrue(bot.accept(packet("!slidealarm on 91107", now)))
            self.assertTrue(await bot.process_one())
            self.assertTrue(bot.slide_alarms.current(bot.slide_alarms.row("Sam")))
            self.assertTrue(send.await_args.kwargs["guard"]())
            self.assertTrue(bot.accept(packet("!slidealarm off", now + 1)))
            self.assertFalse(bot.slide_alarms.current(bot.slide_alarms.row("Sam")))
            await bot.process_one()
            self.assertIn("stopped", send.await_args.args[1])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
