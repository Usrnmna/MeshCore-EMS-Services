"""Location-pinned flood controls, current-state comparison and responder integration."""

import asyncio
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import AsyncMock, patch

from flood_alarm import FloodAlarms
from scripts import water_lookup, water_sources, water_settings, floodalarm
from scripts.water_changes import changes
import responder

ROOT = Path(__file__).resolve().parents[1]
NOW = 1792500000
POINT = [38.5, -122.9]


def sample(now=NOW, events=None, state="no_flooding"):
    alerts = {} if events is None else events
    return {
        "point": POINT.copy(),
        "target": "Test City",
        "fetched": now,
        "mode": "conditions",
        "official": {
            "status": "available",
            "data": {"alerts": alerts, "cancelled_ids": [], "fetched": now},
        },
        "conditions": {
            "gauge:A": {
                "state": state,
                "label": "Example upstream gauge",
                "evidence": "derived_graph_plus_basin_overlap",
            }
        },
    }


def alert(key="a", fingerprint="first", references=None):
    return {
        "id": key,
        "event": "Flood Watch",
        "expires": NOW + 7200,
        "effective": NOW - 60,
        "references": references or [],
        "fingerprint": fingerprint,
        "headline": "Watch",
        "instruction": "Review NWS guidance",
        "url": "https://api.weather.gov/alerts/" + key,
    }


class ChangeTests(unittest.TestCase):
    def test_readable_gauge_labels_keep_categories_uncertainty_and_source_status(self):
        cases = {'major': 'major flooding', 'moderate': 'moderate flooding',
                 'minor': 'minor flooding', 'action': 'action stage',
                 'threshold_unavailable': 'threshold unknown', 'unavailable': 'data unavailable',
                 'stale': 'data stale', 'invalid': 'data invalid', 'future': 'future-dated reading',
                 'out_of_service': 'out of service', 'no_flooding': 'below flood stage',
                 'unrecognized_state': 'status unknown', 'coverage_lost': 'coverage lost'}
        for state, label in cases.items():
            for count in (1, 2):
                previous = sample(state='minor' if state == 'no_flooding' else 'no_flooding')
                previous['conditions'] = {f'gauge:{i}': dict(previous['conditions']['gauge:A']) for i in range(count)}
                current = deepcopy(previous)
                for value in current['conditions'].values():
                    value.update(state=state, reading_status='unavailable')
                if state == 'coverage_lost':
                    current['conditions'] = {}
                for sender in ('Alice', 'a' * 80, '温' * 26):
                    with self.subTest(state=state, count=count, sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                        _, notices = changes(water_lookup.compact(previous), current, NOW)
                        self.assertEqual(len(notices), 1)
                        text = responder.reply_parts(sender, notices[0], max_parts=1)[0]
                        self.assertIn(f'{count} gauge' + ('s' if count != 1 else '') + ': ' + label, text)
                        self.assertIn('not an all-clear' if state == 'coverage_lost' else 'not point flooding', text)
                        self.assertLessEqual(len(text.encode()), 150)
                        self.assertNotIn('Unable to return', text)
                        self.assertNotIn('DERIVED gauges', text)
                        self.assertNotIn('=', text)
                        if sender == 'Alice':
                            self.assertIn('Example upstream gauge [ID 0]', text)
                            if state != 'coverage_lost':
                                self.assertIn('USGS unavailable', text)

    def test_named_gauge_and_identifier_are_distinct_and_long_names_are_whole(self):
        previous = sample()
        for name in ('Example upstream gauge', 'Gauge (' + '温' * 80 + ')'):
            current = sample(state='major')
            current['conditions']['gauge:A'].update(label=name, noaa_identity_status='matched_agency_successor', reading_status='stale')
            text = changes(water_lookup.compact(previous), current, NOW)[1][0]
            self.assertIn('1 gauge: major flooding; not point flooding.', text)
            self.assertNotIn('A Example', text)
            self.assertEqual(text.count('('), text.count(')'))
            if name == 'Example upstream gauge':
                self.assertIn('Example upstream gauge [ID A]', text)
                self.assertIn('USGS stale', text)
                self.assertIn('agency successor', text)
            else:
                self.assertNotIn('温', text)

    def test_large_change_set_keeps_all_baselines_and_prioritizes_remote_hazard(self):
        previous = sample()
        previous["conditions"] = {
            f"gauge:USGS-{i:04d}": dict(
                state="no_flooding",
                label=f"Gauge {i}",
                evidence="derived_graph_plus_basin_overlap",
                reading_status="available",
            )
            for i in range(200)
        }
        current = deepcopy(previous)
        for value in current["conditions"].values():
            value.update(
                state="threshold_unavailable", reading_status="stale", value=999999
            )
        current["conditions"]["gauge:USGS-0199"]["state"] = "major"
        baseline, messages = changes(water_lookup.compact(previous), current, NOW)
        self.assertEqual(len(baseline["conditions"]), 200)
        self.assertNotIn("999999", json.dumps(baseline))
        output = " ".join(messages)
        self.assertIn("1 gauge: major flooding", output)
        self.assertIn("USGS-0199", output)
        self.assertLessEqual(len(("@Reader " + output).encode()), 150)
        self.assertNotIn("more changes", output)
        self.assertLess(len(output), 800)
        self.assertEqual(changes(baseline, current, NOW)[1], [])
        recovered = deepcopy(current)
        recovered["conditions"]["gauge:USGS-0100"]["reading_status"] = "available"
        self.assertIn("USGS available", " ".join(changes(baseline, recovered, NOW)[1]))

    def test_lost_links_are_counted_and_not_reported_as_clear(self):
        previous = sample()
        previous["conditions"] = {
            f"gauge:{i}": dict(
                state="major",
                label=f"Gauge {i}",
                evidence="derived_graph_plus_basin_overlap",
            )
            for i in range(100)
        }
        current = sample()
        current["conditions"] = {}
        baseline, messages = changes(water_lookup.compact(previous), current, NOW)
        self.assertEqual(baseline["conditions"], {})
        self.assertIn("100 gauges: coverage lost", " ".join(messages))
        self.assertIn("not an all-clear", " ".join(messages))
        self.assertLess(len(" ".join(messages)), 800)

    def test_material_update_cancellation_and_expiry(self):
        old = water_lookup.compact(sample(events={"a": alert()}))
        new = sample(events={"b": alert("b", references=["a"])})
        self.assertEqual(changes(old, new, NOW)[1], [])
        new["official"]["data"]["alerts"]["b"]["fingerprint"] = "changed"
        self.assertIn("UPDATED", changes(old, new, NOW)[1][0])
        clear = sample()
        self.assertIn("cancellation unconfirmed", changes(old, clear, NOW)[1][0])
        clear["official"]["data"]["cancelled_ids"] = ["a"]
        self.assertIn("cancelled by NWS", changes(old, clear, NOW)[1][0])
        clear["official"]["data"]["cancelled_ids"] = []
        self.assertIn("expired", changes(old, clear, NOW + 7200)[1][0])

    def test_partial_outage_never_clears_alerts_and_recovers(self):
        before = water_lookup.compact(sample(events={"a": alert()}))
        failed = sample(state="stale")
        failed["official"] = {"status": "unavailable", "error": "offline"}
        after, messages = changes(before, failed, NOW)
        self.assertEqual(after["alerts"], before["alerts"])
        self.assertTrue(any("stale" in m for m in messages))
        self.assertEqual(changes(after, failed, NOW)[1], [])
        self.assertTrue(
            any(
                "restored" in m
                for m in changes(after, sample(events={"a": alert()}), NOW)[1]
            )
        )

    def test_baseline_has_no_measurements_and_unchanged_is_quiet(self):
        s = sample()
        s["local"] = {"readings": [{"value": 1234, "time": "old"}]}
        baseline = water_lookup.compact(s)
        self.assertNotIn("1234", json.dumps(baseline))
        self.assertEqual(changes(baseline, s, NOW)[1], [])
        s["conditions"] = {}
        self.assertIn("coverage lost", changes(baseline, s, NOW)[1][0])


class AlarmTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = NOW
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.read = AsyncMock(side_effect=lambda *args: sample(self.now))
        self.notify = AsyncMock()
        self.allowed = True
        self.alarms = FloodAlarms(
            self.db,
            "default",
            "key",
            {},
            self.read,
            self.notify,
            lambda: self.allowed,
            lambda: self.now,
            monotonic=lambda: self.now,
        )
        self.serial = 0

    def request(self, text="conditions Test City", sender="Alice"):
        self.serial += 1
        return {
            "id": str(self.serial),
            "command": "!floodalarm",
            "sender": sender,
            "sender_timestamp": int(self.now) + self.serial,
            "arguments": [text],
        }

    async def enroll(self, text="conditions Test City", sender="Alice", ack=True):
        r = self.request(text, sender)
        self.assertTrue(self.alarms.remember(r, self.now))
        text, _ = await self.alarms.control(r)
        if ack:
            self.alarms.acknowledge(r)
        return r, text

    async def test_status_summarizes_all_gauges_without_listing_them(self):
        value = sample(self.now)
        value["conditions"] = {
            f"gauge:{i}": dict(
                state="threshold_unavailable",
                label=f"Station {i}",
                evidence="derived_graph_plus_basin_overlap",
                reading_status="stale",
                routing_caveats="tidal_reaches",
            )
            for i in range(200)
        }
        self.read.side_effect = lambda *args: deepcopy(value)
        await self.enroll()
        text, _ = await self.alarms.control(self.request("status"))
        self.assertIn("Data limited", text)
        self.assertIn("status may be unknown", text)
        self.assertEqual(len(json.loads(self.alarms.row("Alice")["baseline"])["conditions"]), 200)
        self.assertNotIn("Station 199", text)
        self.assertLess(len(text), 650)

    async def test_resolves_before_enrollment_and_waits_for_ack(self):
        r, text = await self.enroll(ack=False)
        self.assertIn("Flood monitoring set", text)
        self.assertFalse(await self.alarms.check_one())
        self.alarms.acknowledge(r)
        self.now += 300
        self.assertTrue(await self.alarms.check_one())
        self.read.assert_awaited_with("38.5 -122.9", "conditions")
        self.notify.assert_not_awaited()

    async def test_ambiguous_or_unavailable_enrollment_is_disabled(self):
        self.read.side_effect = ValueError("Ambiguous location")
        _, text = await self.enroll()
        self.assertIn("not started", text)
        self.assertFalse(self.alarms.row("Alice")["enabled"])
        self.read.side_effect = lambda *args: dict(
            sample(self.now), official={"status": "unavailable"}
        )
        _, text = await self.enroll()
        self.assertIn("not started", text)

    async def test_status_stop_renewal_expiry_and_one_shot(self):
        r, _ = await self.enroll()
        row = self.alarms.row("Alice")
        status = self.request("status")
        self.alarms.remember(status, self.now)
        self.assertIn("conditions", (await self.alarms.control(status))[0])
        self.assertEqual(row, self.alarms.row("Alice"))
        self.assertFalse(self.alarms.remember(dict(r, command="!floodwarn"), self.now))
        self.now += 60
        await self.enroll("Test City")
        self.assertEqual(self.alarms.row("Alice")["mode"], "alerts")
        self.now += 4 * 3600
        self.assertFalse(await self.alarms.check_one())
        await self.enroll()
        stop = self.request("stop")
        self.alarms.remember(stop, self.now)
        self.assertFalse(self.alarms.current(self.alarms.row("Alice")))
        self.assertIn("stopped", (await self.alarms.control(stop))[0])

    async def test_threshold_change_outage_recovery_no_numeric_history(self):
        await self.enroll()
        await self.alarms.send_one()  # Separate initial no-alert notification.
        self.notify.reset_mock()
        self.now += 300
        self.read.side_effect = lambda *args: sample(self.now, state="action")
        await self.alarms.check_one()
        await self.alarms.send_one()
        self.assertIn("1 gauge: action stage; not point flooding.", self.notify.await_args.args[1])
        self.now += 300
        await self.alarms.check_one()
        await self.alarms.send_one()
        self.assertEqual(self.notify.await_count, 1)
        self.read.side_effect = ValueError("offline")
        for i in range(2):
            self.now += 300
            await self.alarms.check_one()
            await self.alarms.send_one()
        self.assertEqual(self.notify.await_count, 2)
        self.read.side_effect = lambda *args: sample(self.now, state="action")
        self.now += 300
        await self.alarms.check_one()
        await self.alarms.send_one()
        self.assertIn("restored", self.notify.await_args.args[1])
        self.assertNotIn("readings", self.alarms.row("Alice")["baseline"])

    async def test_inflight_cancel_and_changed_point_suppress_output(self):
        await self.enroll()
        self.now += 300

        async def delayed(*args):
            self.alarms.remember(self.request("stop"), self.now)
            return sample(self.now, state="major")

        self.read.side_effect = delayed
        await self.alarms.check_one()
        self.notify.assert_not_awaited()
        self.read.side_effect = lambda *args: sample(self.now)
        await self.enroll()
        self.now += 300
        self.read.side_effect = lambda *args: dict(sample(self.now), point=[39, -121])
        await self.alarms.check_one()
        self.assertIn("location changed", self.alarms.row("Alice")["error"])

    async def test_sender_channel_identity_and_restart(self):
        await self.enroll()
        await self.enroll(sender="Bob")
        before = self.alarms.row("Alice")
        restarted = FloodAlarms(
            self.db,
            "default",
            "key",
            {},
            self.read,
            self.notify,
            lambda: True,
            lambda: self.now,
        )
        self.assertEqual(restarted.row("Alice"), before)
        other = FloodAlarms(
            self.db,
            "other",
            "other",
            {},
            self.read,
            self.notify,
            lambda: True,
            lambda: self.now,
        )
        self.assertIsNone(other.row("Alice"))
        changed = FloodAlarms(
            self.db,
            "default",
            "changed",
            {},
            self.read,
            self.notify,
            lambda: True,
            lambda: self.now,
        )
        self.assertFalse(changed.row("Alice")["enabled"])

    async def test_legacy_migration_preserves_deadline_and_pins_once(self):
        self.db.execute(
            "CREATE TABLE flood_subscriptions(channel TEXT,sender TEXT,location TEXT,last_heard REAL,sender_timestamp INTEGER,revision TEXT,enabled INTEGER,ready INTEGER,next_check REAL,baseline TEXT,checked_at REAL,error TEXT)"
        )
        self.db.execute(
            "INSERT INTO flood_subscriptions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "default",
                "Legacy",
                "Test City",
                NOW - 100,
                1,
                "old",
                1,
                1,
                NOW,
                "[]",
                None,
                None,
            ),
        )
        migrated = FloodAlarms(
            self.db,
            "default",
            "key",
            {},
            self.read,
            self.notify,
            lambda: True,
            lambda: self.now,
        )
        self.assertEqual(migrated.row("Legacy")["expires"], NOW - 100 + 14400)
        await migrated.check_one()
        self.assertEqual(json.loads(migrated.row("Legacy")["point"]), POINT)
        self.assertEqual(
            self.db.execute("SELECT enabled FROM flood_subscriptions").fetchone()[0], 0
        )


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "config.json").read_bytes())["responder"]
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.send = AsyncMock()
        self.bot = responder.Responder(ROOT, self.db, self.cfg, 3, "Bot", self.send)

    async def test_control_guard_and_no_retained_values(self):
        now = time.time()
        packet = {
            "channel_idx": 3,
            "txt_type": 0,
            "sender_timestamp": int(now),
            "text": "Alice: !floodalarm conditions 38.5 -122.9",
        }
        with patch.object(self.bot.alarms, "read", return_value=sample(now)):
            self.assertTrue(self.bot.accept(packet))
            await self.bot.process_one()
        self.assertTrue(self.bot.alarms.row("Alice")["ready"])
        self.assertTrue(
            all(call.kwargs["guard"]() for call in self.send.await_args_list)
        )
        self.assertEqual(
            self.db.execute("SELECT response FROM bot_requests").fetchone()[0], "[]"
        )
        self.bot.alarms.remember(
            {
                "id": "stop",
                "command": "!floodalarm",
                "sender": "Alice",
                "sender_timestamp": int(now) + 1,
                "arguments": ["stop"],
            },
            now,
        )
        self.assertFalse(self.send.await_args.kwargs["guard"]())

    async def test_new_commands_and_subprocess_snapshot_validation(self):
        responder.validate_config(self.cfg, ROOT)
        for command in (
            "!waterway",
            "!basin",
            "!floodstatus",
            "!floodwarn",
            "!floodalarm",
        ):
            self.assertEqual(
                responder.match_command(command + " 38 -121", self.cfg["commands"]),
                (command, ["38 -121"], None),
            )
        for output in ("{}", "not JSON", '{"error":"offline"}'):
            with patch.object(
                responder, "run_script", return_value=(output, "")
            ), self.assertRaises(RuntimeError):
                await self.bot.read_flood_status("38 -121")
        with patch.object(
            responder, "run_script", return_value=(json.dumps(sample(time.time())), "")
        ) as run:
            await self.bot.read_flood_status("38 -121", "conditions")
            self.assertEqual(run.call_args.args[1]["args"], ["--snapshot"])
            self.assertEqual(run.call_args.args[2]["arguments"], ["conditions 38 -121"])

    async def test_standalone_alarm_does_not_subscribe(self):
        with patch.object(water_lookup, "snapshot", return_value=sample()), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as out:
            floodalarm.main(["Test City"])
        self.assertIn("no subscription", out.getvalue())

    async def test_independent_notifications_use_tagged_chunks_and_guard_after_radio_wait(
        self,
    ):
        now = time.time()
        tick = [100.0]
        self.bot.alarms.monotonic = lambda: tick[0]
        first = dict(
            alert("a"),
            effective=now - 60,
            expires=now + 7200,
            urgency="Immediate",
            severity="Extreme",
            certainty="Observed",
            event="Flash Flood Warning",
        )
        second = dict(
            alert("b"),
            effective=now - 60,
            expires=now + 7200,
            urgency="Future",
            severity="Severe",
            certainty="Possible",
        )
        packet = dict(
            channel_idx=3,
            txt_type=0,
            sender_timestamp=int(now),
            text="Alice: !floodalarm Test City",
        )
        with patch.object(
            self.bot.alarms,
            "read",
            return_value=sample(now, events={"a": first, "b": second}),
        ):
            self.assertTrue(self.bot.accept(packet))
            await self.bot.process_one()
        self.send.reset_mock()
        await self.bot.alarms.send_one()
        first_calls = list(self.send.await_args_list)
        self.assertEqual(len(first_calls), 1)
        joined = "".join(call.args[1][len("@Alice ") :] for call in first_calls)
        self.assertIn("NWS FLASH FLOOD WARNING", joined)
        self.assertIn("Move to higher ground now", joined)
        self.assertNotIn("Flood Watch", joined)
        self.assertTrue(
            all(
                call.args[0] == 3 and len(call.args[1].encode()) <= 150
                for call in first_calls
            )
        )
        self.assertFalse(await self.bot.alarms.send_one())
        tick[0] += 5
        accepted = []

        async def stop_during_radio_wait(channel, text, *, guard=None):
            self.bot.alarms.remember(
                dict(
                    id="stop",
                    command="!floodalarm",
                    sender="Alice",
                    sender_timestamp=int(now) + 1,
                    arguments=["stop"],
                ),
                now,
            )
            if guard():
                accepted.append(text)

        self.send.side_effect = stop_during_radio_wait
        await self.bot.alarms.send_one()
        self.assertFalse(accepted)


if __name__ == "__main__":
    unittest.main()
