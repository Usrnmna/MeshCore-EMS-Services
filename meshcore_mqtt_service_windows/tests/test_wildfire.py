"""Offline regression coverage for wildfire source integrity, geography and alarms."""

import asyncio
import copy
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import wildfire_lookup as lookup
from scripts.fire_weather import fire_alerts, parse_fwf, ugc_codes
from scripts.wildfire_refresh import seed
from scripts.wildfire_settings import validate
from scripts.wildfire_sources import Client, timestamp
from scripts.wildfire_spatial import point_zones
from scripts.wildfire_store import Store
from wildfire_service import WildfireAlarms, changes
from responder import Responder, match_command, validate_config, reply_parts

GUID = "11111111-1111-4111-8111-111111111111"


def feature(key, properties=None, geometry=None):
    return dict(type="Feature", id=key, properties=properties or {}, geometry=geometry)


def zone():
    return feature("CAZ001", dict(name="Test", cwa="REV"),
                   dict(type="Polygon", coordinates=[[[-121, 39], [-119, 39], [-119, 41], [-121, 41], [-121, 39]]]))


def snapshot():
    return dict(zones=["CAZ001"], incidents={GUID: dict(name="Test", acres=10, containment=None, perimeter=False)}, alerts={})


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "wildfire.sqlite3"
        self.store = Store(self.path, writable=True)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_failed_replace_preserves_snapshot_and_index(self):
        self.store.replace("zones", [zone()], "test", now=100)
        with self.assertRaises(ValueError):
            self.store.replace("zones", [zone(), zone()], "test", now=200)
        self.store.fail("zones", "offline", now=200)
        self.assertEqual(len(self.store.features("zones", (-120, 40, -120, 40))), 1)
        self.assertEqual(self.store.status("zones")["fetched"], 100)
        self.assertEqual(self.store.status("zones")["error"], "offline")

    def test_successful_empty_snapshot_is_distinct_from_failure(self):
        self.store.replace("alerts", [feature("a")], "test", now=100)
        self.store.replace("alerts", [], "test", now=200)
        self.assertEqual(self.store.features("alerts"), [])
        self.assertEqual(self.store.status("alerts")["count"], 0)
        self.assertIsNone(self.store.status("alerts")["error"])

    def test_unchanged_source_retains_recent_last_seen_history(self):
        self.store.replace("alerts", [feature("a")], "test", now=100)
        self.store.replace("alerts", [feature("a")], "test", now=700000)
        self.assertEqual(self.store.db.execute("SELECT captured FROM history").fetchone()[0], 700000)

    def test_large_reference_download_resumes_complete_batches(self):
        class Fake(Client):
            fail = True
            calls = []
            def get(self, url, params=None, post=False):
                if not url.endswith("/query"):
                    return dict(objectIdField="OID", maxRecordCount=1)
                if params.get("returnIdsOnly"):
                    return dict(objectIds=[1, 2])
                key = int(params["objectIds"])
                self.calls.append(key)
                if self.fail and key == 2:
                    raise TimeoutError("budget")
                return dict(features=[feature(str(key), {"OID": key})])
        client = Fake(stage_dir=Path(self.temp.name) / "stage")
        with self.assertRaises(TimeoutError):
            client.arcgis("https://test", resume=True)
        client.fail = False
        result = client.arcgis("https://test", resume=True)
        self.assertEqual(len(result), 2)
        self.assertEqual(client.calls, [1, 2, 2])
        self.assertEqual(list(client.stage_dir.glob("*.json")), [])

    def test_writer_lease_excludes_competitor(self):
        with self.store.lease():
            with Store(self.path, writable=True) as second:
                with self.assertRaises(RuntimeError):
                    with second.lease():
                        pass
        with self.store.lease():
            pass

    def test_unknown_schema_is_not_overwritten(self):
        self.store.db.execute("PRAGMA user_version=42")
        with self.assertRaises(ValueError):
            Store(self.path, writable=True)
        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], 42)

    def test_seed_covers_interstate_tahoe_and_nevada_named_zone(self):
        seed(self.store)
        zones = self.store.features("zones")
        self.assertIn("CAZ272", [z["id"] for z in point_zones(zones, 39.25, -119.96)])
        self.assertIn("NVZ420", [z["id"] for z in zones])
        self.assertTrue(next(z for z in zones if z["id"] == "CAZ272")["properties"]["cross_state"])

    def test_perimeter_intersection_includes_fire_with_origin_outside(self):
        self.store.replace("zones", [zone()], "test")
        self.store.replace("incidents", [feature("1", dict(IrwinID=GUID, IncidentName="Border",
                                 IncidentTypeCategory="WF", PercentContained=None),
                                 dict(type="Point", coordinates=[-118, 40]))], "test")
        self.store.replace("egp", [], "test")
        self.store.replace("perimeters", [feature("2", dict(attr_IrwinID=GUID), zone()["geometry"])], "test")
        result = lookup.report("fires", "CAZ001", self.store)
        self.assertEqual(len(result["incidents"]), 1)
        self.assertIsNone(result["incidents"][0]["containment"])
        self.assertIn("contained unknown", lookup.format_report(result))

    def test_near_filters_radius_and_preserves_unknown_containment(self):
        self.store.replace('zones', [zone()], 'test')
        self.store.replace('incidents', [
            feature('1', dict(IrwinID=GUID, IncidentName='Near Fire', IncidentTypeCategory='WF'),
                    dict(type='Point', coordinates=[-120.01, 40])),
            feature('2', dict(IrwinID='22222222-2222-4222-8222-222222222222',
                              IncidentName='Outside', IncidentTypeCategory='WF'),
                    dict(type='Point', coordinates=[-119, 40])),
        ], 'test')
        for source in ('egp', 'perimeters'):
            self.store.replace(source, [], 'test')
        result = lookup.report('fires', 'near 40 -120 within 2', self.store)
        self.assertEqual([record['name'] for record in result['incidents']], ['Near Fire'])
        self.assertGreater(result['incidents'][0]['distance_miles'], 0)
        self.assertLess(result['incidents'][0]['distance_miles'], 2)
        for sender in ('Alice', 'a' * 80):
            with patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                parts = reply_parts(sender, lookup.format_report(result), max_parts=1)
                self.assertEqual(len(parts), 1)
                self.assertLessEqual(len(parts[0].encode()), 150)
                self.assertIn('Near Fire', parts[0])
                self.assertIn('contained unknown', parts[0])
                self.assertNotIn('Outside', parts[0])
                self.assertNotIn('1 incident records', parts[0])
                self.assertNotIn(GUID, parts[0])
                if sender == 'Alice':
                    self.assertIn(f"{result['incidents'][0]['distance_miles']:.2f} mi map distance", parts[0])
        self.assertEqual(result['incidents'][0]['display_id'], GUID)
        self.assertEqual(lookup.report('fire', GUID, self.store)['incidents'][0]['id'], GUID)
        empty = lookup.report('fires', 'near 40 -120 within 0.1', self.store)
        self.assertEqual(empty['incidents'], [])

    def test_latest_perimeter_and_explicit_field_provenance(self):
        self.store.replace("incidents", [feature("1", dict(IrwinID=GUID, IncidentName="Fire",
                                 IncidentTypeCategory="WF", PercentContained=20, ModifiedOnDateTime_dt=100000))], "test")
        self.store.replace("egp", [feature("2", dict(IrwinID=GUID, Name="Fire", DailyAcres=35,
                                  PercentContained=None, Last_Time_Information_Modified=200000))], "test")
        self.store.replace("perimeters", [
            feature("p1", dict(attr_IrwinID=GUID, poly_PolygonDateTime=100000), zone()["geometry"]),
            feature("p2", dict(attr_IrwinID=GUID, poly_PolygonDateTime=200000), zone()["geometry"]),
            feature("unmapped", dict(attr_IrwinID=GUID, poly_PolygonDateTime=300000)),
        ], "test")
        record = lookup.incidents(self.store)[GUID]
        self.assertEqual(record["field_sources"]["containment"], "incidents")
        self.assertEqual(record["field_times"]["containment"], 100)
        self.assertEqual([f["id"] for f in record["perimeters"]], ["p2"])

    def test_disappeared_fire_is_last_known_only(self):
        self.store.replace("zones", [zone()], "test", now=100)
        self.store.replace("incidents", [feature("1", dict(IrwinID=GUID, IncidentName="Gone"))], "test", now=100)
        self.store.replace("incidents", [], "test", now=200)
        self.assertEqual(lookup.incidents(self.store), {})
        result = lookup.report("fire", GUID, self.store, now=200)
        self.assertTrue(result["incidents"][0]["historical"])
        self.assertEqual(result["incidents"][0]["last_seen"], 100)
        self.assertIn("status unconfirmed", lookup.format_report(result))

    def test_stale_monitor_does_not_return_empty_all_clear(self):
        with self.assertRaises(ValueError):
            lookup.monitor_snapshot(dict(sources=[dict(source="alerts", stale=True)], incidents=[], alerts=[], zones=[]))

    def test_firezone_location_includes_alert_status_and_missing_data(self):
        self.store.replace("zones", [zone()], "test")
        initial = lookup.report("firezone", "40, -120", self.store)
        self.assertEqual(initial["zones"][0]["id"], "CAZ001")
        self.assertIn("data limited", lookup.format_report(initial).lower())
        self.assertIn("alert status unknown", lookup.format_report(initial))
        self.store.replace("alerts", [feature("a", dict(
            event="Red Flag Warning", status="Actual", messageType="Alert",
            geocode={"UGC": ["CAZ001"]}, expires="2099-10-21T12:00:00Z",
            headline="Red Flag Warning for the test zone"))], "test")
        result = lookup.report("firezone", "40 -120", self.store)
        self.assertIn("Red Flag Warning", lookup.format_report(result))
        self.store.replace("alerts", [], "test")
        self.assertIn("no active NWS fire-weather", lookup.format_report(lookup.report("firezone", "CAZ001", self.store)))


class SourceTests(unittest.TestCase):
    def test_arcgis_missing_batch_rejected(self):
        class Fake(Client):
            def get(self, url, params=None, post=False):
                if not url.endswith("/query"):
                    return dict(objectIdField="OID", maxRecordCount=10)
                if params.get("returnIdsOnly"):
                    return dict(objectIds=[1, 2])
                return dict(features=[feature("1", {"OID": 1})])
        with self.assertRaises(ValueError):
            Fake().arcgis("https://test")

    def test_null_arcgis_inventory_requires_zero_count(self):
        class Fake(Client):
            count = 0
            def get(self, url, params=None, post=False):
                if not url.endswith("/query"):
                    return dict(objectIdField="OID")
                if params.get("returnIdsOnly"):
                    return dict(objectIds=None)
                return dict(count=self.count)
        self.assertEqual(Fake().arcgis("https://test"), [])
        client = Fake()
        client.count = 1
        with self.assertRaises(ValueError):
            client.arcgis("https://test")

    def test_egp_audit_timestamp(self):
        self.assertEqual(timestamp("operator, 2026-10-20 02:3206.517 UTC"),
                         timestamp("2026-10-20T02:32:06.517Z"))
        with self.assertRaises(ValueError):
            timestamp("2026-10-20 02:32:06")

    def test_outlook_layer_ids_are_namespaced(self):
        class Fake(Client):
            def get(self, *args, **kwargs):
                return dict(layers=[dict(id=1, name="Day 1", subLayerIds=None),
                                    dict(id=4, name="Day 2", subLayerIds=None)])
            def arcgis(self, *args, **kwargs):
                return [feature("1")]
        result = Fake().source("spc", (-121, 39, -119, 41))
        self.assertEqual([f["id"] for f in result], ["1:1", "4:1"])
        self.assertEqual(result[1]["properties"]["source_layer"], "Day 2")

    def test_ugc_compression_and_multiple_states(self):
        self.assertEqual(ugc_codes("CAZ270>272-NVZ420-211200-"), ["CAZ270", "CAZ271", "CAZ272", "NVZ420"])
        with self.assertRaises(ValueError):
            ugc_codes("CAZ272>270-211200-")

    def test_multiline_fwf_retains_wind_height(self):
        product = dict(id="p", issuanceTime="2026-10-20T12:00:00Z",
                       productText="Discussion\nCAZ270>272-\nNVZ420-211200-\nLake\n.TODAY...\nMin Humidity....15 percent.\n20-Foot Winds..NW 10 mph.\n.TONIGHT...\nMax Humidity....60 percent.\n$$\nNVZ420 - explanatory station text\n")
        result = parse_fwf(product)
        self.assertEqual(len(result["sections"]), 4)
        self.assertEqual(len(result["sections"]["CAZ272"]["periods"]), 2)
        self.assertIn("20-Foot Winds", result["raw"])

    def test_null_geometry_alert_matches_ugc_and_expiry(self):
        alert = feature("a", dict(event="Red Flag Warning", status="Actual", messageType="Alert",
                                  geocode={"UGC": ["CAZ272"]}, expires="2026-10-21T12:00:00Z"))
        self.assertEqual(len(fire_alerts([alert], {"CAZ272"}, now=100)), 1)
        self.assertEqual(fire_alerts([alert], {"CAZ272"}, now=9999999999), [])
        alert["properties"]["messageType"] = "Cancel"
        self.assertEqual(fire_alerts([alert], {"CAZ272"}, now=100), [])

    def test_command_validation_and_config(self):
        config = json.loads((ROOT / "config.json").read_bytes())["responder"]
        validate_config(config, ROOT)
        self.assertEqual(match_command("!firezone CAZ272", config["commands"])[1], ["CAZ272"])
        self.assertIsNotNone(match_command("!fires near Reno NV within 999", config["commands"])[2])
        self.assertIsNotNone(match_command("!fire --refresh", config["commands"])[2])
        for location in ("39.25, -119.96", "39.25 -119.96", "96161", "Truckee", "Incline Village NV"):
            with self.subTest(location=location):
                self.assertIsNone(match_command("!firezone " + location, config["commands"])[2])
        with self.assertRaises(ValueError):
            validate({"context_sources": ["unknown"]})
        with self.assertRaises(ValueError):
            validate({"incident_interval": 1})


class AlarmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = sqlite3.connect(":memory:")
        self.now = 1000
        self.value, self.sent, self.fail = snapshot(), [], False
        async def read(target):
            if self.fail:
                raise ValueError("offline")
            return copy.deepcopy(self.value)
        async def notify(reading, text):
            self.sent.append(text)
        self.alarms = WildfireAlarms(self.db, "default", "identity", {}, read, notify, lambda: True,
                                    clock=lambda: self.now)
        self.request = dict(sender="Sam", command="!firealarm", arguments=["on CAZ001"],
                            id="r1", sender_timestamp=1000)

    async def asyncTearDown(self):
        self.db.close()

    async def enroll(self):
        self.assertTrue(self.alarms.remember(self.request, self.now))
        text, detail = await self.alarms.control(self.request)
        self.assertIn("monitoring set", text)
        self.assertFalse(self.alarms.current(self.alarms.row("Sam")))
        self.alarms.acknowledge(self.request)
        self.assertTrue(self.alarms.current(self.alarms.row("Sam")))

    async def test_enrollment_keeps_active_warning_with_maximum_sender_tag(self):
        self.value['alerts'] = {
            'watch': {'event': 'Fire Weather Watch', 'digest': 'w'},
            'warning': {'event': 'Red Flag Warning', 'digest': 'r'},
        }
        self.assertTrue(self.alarms.remember(self.request, self.now))
        text, error = await self.alarms.control(self.request)
        self.assertFalse(error)
        reply = reply_parts('A' * 80, text, max_parts=1)
        self.assertEqual(len(reply), 1)
        self.assertLessEqual(len(reply[0].encode()), 150)
        self.assertIn('Red Flag Warning', reply[0])
        self.assertIn('monitoring set', reply[0])

    async def test_ack_baseline_and_meaningful_change(self):
        await self.enroll()
        self.now += 301
        await self.alarms.check_one()
        self.assertEqual(self.sent, [])
        self.value["incidents"][GUID]["containment"] = 20
        self.now += 301
        await self.alarms.check_one()
        self.assertIn("containment now 20%.", self.sent[0])

    async def test_outage_retains_baseline_and_reports_once(self):
        await self.enroll()
        baseline = self.alarms.row("Sam")["baseline"]
        self.fail = True
        for _ in range(2):
            self.now += 301
            await self.alarms.check_one()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.alarms.row("Sam")["baseline"], baseline)
        self.fail = False
        self.now += 301
        await self.alarms.check_one()
        self.assertIn("available again", self.sent[-1])

    async def test_off_and_revision_guard(self):
        await self.enroll()
        old = self.alarms.row("Sam")
        off = dict(self.request, id="r2", sender_timestamp=1001, arguments=["off"])
        self.alarms.remember(off, self.now)
        self.assertFalse(self.alarms.current(old))
        self.assertFalse(self.alarms.control_current(self.request))
        self.assertFalse(self.alarms.remember(self.request, self.now))

    async def test_cancellation_while_enrollment_awaits(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def delayed(target):
            entered.set()
            await finish.wait()
            return snapshot()
        self.alarms.read = delayed
        self.alarms.remember(self.request, self.now)
        task = asyncio.create_task(self.alarms.control(self.request))
        await entered.wait()
        self.alarms.remember(dict(self.request, id="off", sender_timestamp=1001, arguments=["off"]), self.now)
        finish.set()
        text, _ = await task
        self.assertIn("superseded", text)
        self.assertFalse(self.alarms.row("Sam")["enabled"])

    async def test_expiry(self):
        await self.enroll()
        self.now += 4 * 3600
        self.assertFalse(self.alarms.current(self.alarms.row("Sam")))
        self.assertFalse(await self.alarms.check_one())

    async def test_removed_channel_disables_subscription_during_state_binding(self):
        from channels import bind_state
        await self.enroll()
        bind_state(self.db, {})
        self.assertFalse(self.alarms.row("Sam")["enabled"])

    async def test_failed_enrollment_never_claims_started(self):
        self.fail = True
        self.alarms.remember(self.request, self.now)
        text, _ = await self.alarms.control(self.request)
        self.assertIn("not started", text)
        self.assertFalse(self.alarms.row("Sam")["enabled"])

    def test_cumulative_threshold_and_disappearance_wording(self):
        before, after = snapshot(), snapshot()
        after["incidents"][GUID]["acres"] += 99
        self.assertEqual(changes(before, after, validate({})), [])
        after["incidents"][GUID]["acres"] += 1
        self.assertTrue(changes(before, after, validate({})))
        after["incidents"] = {}
        self.assertIn("status unconfirmed", changes(before, after, validate({}))[0])


class ResponderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_firealarm_control_uses_service_and_guarded_ack(self):
        db = sqlite3.connect(":memory:")
        try:
            config = json.loads((ROOT / "config.json").read_bytes())["responder"]
            config["sender_cooldown"] = 0
            send = AsyncMock()
            bot = Responder(ROOT, db, config, 3, "Local Bot", send)
            bot.fire_alarms.read = AsyncMock(return_value=snapshot())
            now = int(time.time())
            def packet(phrase, at):
                return dict(channel_idx=3, txt_type=0, text="Sam: " + phrase, sender_timestamp=at)
            self.assertTrue(bot.accept(packet("!firealarm on CAZ001", now)))
            self.assertFalse(await bot.process_one(alarm_only=True))
            self.assertTrue(await bot.process_one(alarm_only=False))
            self.assertTrue(bot.fire_alarms.current(bot.fire_alarms.row("Sam")))
            self.assertTrue(send.await_args.kwargs["guard"]())
            self.assertTrue(bot.accept(packet("!firealarm off", now + 1)))
            self.assertFalse(bot.fire_alarms.current(bot.fire_alarms.row("Sam")))
            await bot.process_one(alarm_only=False)
            self.assertIn("stopped", send.await_args.args[1])
        finally:
            db.close()

    async def test_slow_fire_enrollment_does_not_block_flood_ack(self):
        from test_floodalarm import sample
        db = sqlite3.connect(":memory:")
        finish, entered = asyncio.Event(), asyncio.Event()
        task = None
        try:
            config = json.loads((ROOT / "config.json").read_bytes())["responder"]
            send = AsyncMock()
            bot = Responder(ROOT, db, config, 3, "Local Bot", send)
            bot.alarms.read = AsyncMock(side_effect=lambda *args: sample(time.time()))
            async def delayed(target):
                entered.set()
                await finish.wait()
                return snapshot()
            bot.fire_alarms.read = delayed
            now = int(time.time())
            for sender, phrase in (("Sam", "!firealarm on CAZ001"), ("Alex", "!floodalarm Truckee")):
                self.assertTrue(bot.accept(dict(channel_idx=3, txt_type=0, text=sender + ": " + phrase,
                                                sender_timestamp=now)))
            task = asyncio.create_task(bot.process_one(alarm_only=False))
            await entered.wait()
            self.assertTrue(await bot.process_one(alarm_only=True))
            self.assertTrue(any("Flood monitoring set" in call.args[1] for call in send.await_args_list))
            self.assertFalse(task.done())
        finally:
            finish.set()
            if task:
                await task
            db.close()


if __name__ == "__main__":
    unittest.main()
