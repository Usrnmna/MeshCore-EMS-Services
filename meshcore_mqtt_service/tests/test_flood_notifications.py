"""Offline CAP priority, independent response pacing and stale-queue guards."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import AsyncMock

from flood_alarm import FloodAlarms, NOTIFICATION_PAUSE_SECONDS
from scripts import water_lookup, water_notifications as notices, water_settings
from test_floodalarm import NOW, alert, sample


def hazard(key, **fields):
    value = alert(key)
    value.update(urgency="Immediate", severity="Severe", certainty="Observed")
    value.update(fields)
    return value


class PriorityTests(unittest.TestCase):
    def test_shipped_radio_interval_matches_five_second_notification_pause(self):
        """Prevent the shared transmitter default from adding the former 15-second delay."""
        config = json.loads(
            (Path(__file__).resolve().parents[1] / "config.json").read_bytes()
        )
        self.assertEqual(config["command_interval"], 5)
        self.assertEqual(config["command_interval"], NOTIFICATION_PAUSE_SECONDS)

    def test_priority_is_lexicographic_with_recent_effective_time_and_stable_ties(self):
        for field, high, low in (
            ("urgency", "Immediate", "Expected"),
            ("severity", "Extreme", "Severe"),
            ("certainty", "Observed", "Likely"),
            ("effective", NOW - 1, NOW - 60),
        ):
            with self.subTest(field=field):
                a, b = hazard("z", **{field: high}), hazard("a", **{field: low})
                self.assertLess(
                    notices.priority(notices.active_notice(a, "NEW")),
                    notices.priority(notices.active_notice(b, "NEW")),
                )
        urgent = hazard("urgent", severity="Minor", certainty="Unlikely")
        severe = hazard("severe", urgency="Expected", severity="Extreme")
        self.assertLess(
            notices.priority(notices.active_notice(urgent, "NEW")),
            notices.priority(notices.active_notice(severe, "NEW")),
        )
        self.assertLess(
            notices.priority(notices.active_notice(hazard("a"), "NEW")),
            notices.priority(notices.active_notice(hazard("b"), "NEW")),
        )

    def test_unknown_fields_are_conservative_without_inventing_source_values(self):
        for field in notices.PRIORITY_FIELDS:
            for missing in (None, "", "Unknown", "unexpected"):
                with self.subTest(field=field, missing=missing):
                    a = hazard("a", **{field: missing})
                    notice = notices.active_notice(a, "NEW")
                    self.assertEqual(notice["alert"][field], missing)
                    self.assertIn(
                        "Priority unknown.",
                        notices.format_notification(notice, "City", NOW),
                    )
                    highest = hazard("a", **{field: notices.PRIORITY_FIELDS[field][0]})
                    self.assertEqual(
                        notices.priority(notice),
                        notices.priority(notices.active_notice(highest, "NEW")),
                    )
        likely = notices.active_notice(hazard("a", certainty="Very Likely"), "NEW")
        self.assertNotIn("uncertain", notices.format_notification(likely, "City", NOW))
        self.assertEqual(
            notices.priority(likely),
            notices.priority(
                notices.active_notice(hazard("a", certainty="Likely"), "NEW")
            ),
        )

    def test_active_event_and_action_are_concise_and_inactive_notices_remain_distinct(self):
        for event, (_, description) in notices.ALERTS.items():
            notice = notices.active_notice(hazard("a", event=event), "UPDATED")
            text = notices.format_notification(notice, "Sacramento", NOW)
            self.assertIn(event.upper(), text.upper())
            self.assertLessEqual(len(("@Reader " + text).encode()), 150)
            if event == "Flash Flood Warning":
                self.assertIn("Move to higher ground now", text)
            self.assertTrue(text.startswith("NWS"))
            self.assertNotIn("point", text)
            self.assertNotIn("http", text)
        before = water_lookup.compact(sample(events={"a": hazard("a")}))
        cancelled = sample()
        cancelled["official"]["data"]["cancelled_ids"] = ["a"]
        output = notices.official_notifications(before, cancelled, NOW)
        self.assertEqual(len(output), 2)
        self.assertIn("cancelled by NWS", output[0]["text"])
        self.assertIn("Not an all-clear", output[0]["text"])
        self.assertFalse(any(n["kind"] == "alert" for n in output))

    def test_missing_alert_suppresses_empty_feed_claim_including_recovery(self):
        for recovered in (False, True):
            for other_end in ('none', 'cancelled', 'expired'):
                with self.subTest(recovered=recovered, other_end=other_end):
                    events = {'missing': hazard('missing', event='Flash Flood Warning')}
                    if other_end != 'none':
                        events['other'] = hazard('other', expires=NOW if other_end == 'expired' else NOW + 7200)
                    before = water_lookup.compact(sample(events=events))
                    if recovered:
                        before['official_status'] = 'unavailable'
                    current = sample()
                    if other_end == 'cancelled':
                        current['official']['data']['cancelled_ids'] = ['other']
                    output = notices.official_notifications(before, current, NOW)
                    texts = [notice['text'] for notice in output]
                    self.assertTrue(any('cancellation unconfirmed' in text for text in texts))
                    self.assertFalse(any('No active NWS flood alerts' in text for text in texts))
                    if recovered:
                        self.assertIn('NWS monitoring restored.', texts)

    def test_confirmed_end_or_initial_empty_feed_keeps_qualified_status(self):
        for state in ('initial', 'cancelled', 'expired'):
            for recovered in (False, True):
                with self.subTest(state=state, recovered=recovered):
                    before = None if state == 'initial' else water_lookup.compact(sample(
                        events={'a': hazard('a', expires=NOW if state == 'expired' else NOW + 7200)}))
                    if recovered:
                        before = before or water_lookup.compact(sample())
                        before['official_status'] = 'unavailable'
                    current = sample()
                    if state == 'cancelled':
                        current['official']['data']['cancelled_ids'] = ['a']
                    output = notices.official_notifications(before, current, NOW)
                    self.assertTrue(any('No active NWS flood alerts' in n.get('text', '') for n in output))
                    if state != 'initial':
                        self.assertTrue(any('Not an all-clear' in n.get('text', '') for n in output))

    def test_snapshot_rejects_future_expired_invalid_time_or_mismatched_id(self):
        for fields in (
            {"effective": NOW + 1},
            {"expires": NOW},
            {"effective": None},
            {"effective": float("nan")},
            {"id": "different"},
            {"severity": []},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                water_lookup.checked_snapshot(
                    sample(events={"a": hazard("a", **fields)}),
                    water_settings.validate({}),
                    NOW,
                )
        value = sample()
        value["official"]["data"]["fetched"] = NOW - 301
        with self.assertRaisesRegex(ValueError, "source time"):
            water_lookup.checked_snapshot(value, water_settings.validate({}), NOW)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now, self.tick = NOW, 100.0
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.data = sample(self.now)
        self.data["conditions"] = {}
        self.read = AsyncMock(side_effect=lambda *args: deepcopy(self.data))
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
            monotonic=lambda: self.tick,
        )
        self.serial = 0
        await self.enroll()
        await self.alarms.send_one()
        self.notify.reset_mock()

    def advance(self, seconds):
        self.now += seconds
        self.tick += seconds

    def request(self, text="Test City", sender="Alice"):
        self.serial += 1
        return dict(
            id=str(self.serial),
            command="!floodalarm",
            sender=sender,
            sender_timestamp=int(self.now) + self.serial,
            arguments=[text],
        )

    async def enroll(self, sender="Alice", ack=True):
        request = self.request(sender=sender)
        self.alarms.remember(request, self.now)
        text, _ = await self.alarms.control(request)
        if ack:
            self.alarms.acknowledge(request)
        return request, text

    async def poll(self, events=None, unavailable=False, cancelled=None):
        self.advance(300)
        self.data = sample(self.now, events=events)
        self.data["conditions"] = {}
        self.data["official"]["data"]["cancelled_ids"] = cancelled or []
        if unavailable:
            self.data["official"] = {"status": "unavailable"}
        await self.alarms.check_one()

    async def test_all_alerts_are_independent_and_pause_starts_after_completion(self):
        events = {
            str(i): hazard(str(i), urgency="Future" if i else "Immediate")
            for i in range(5)
        }
        await self.poll(events)
        starts = []

        async def notify(reading, text):
            self.assertTrue(self.alarms.notification_current(reading))
            starts.append(self.tick)
            self.tick += 2  # Simulated time for all radio chunks, not just enqueue.

        self.notify.side_effect = notify
        for i in range(5):
            self.assertTrue(await self.alarms.send_one())
            self.assertFalse(await self.alarms.send_one())
            self.tick += 4.999
            self.assertFalse(await self.alarms.send_one())
            self.tick += 0.0011
        self.assertEqual(len(starts), 5)
        self.assertTrue(all(b - a >= 7 for a, b in zip(starts, starts[1:])))
        self.assertEqual(NOTIFICATION_PAUSE_SECONDS, 5)
        for call in self.notify.await_args_list:
            self.assertEqual(call.args[1].count("Test City"), 1)
            self.assertEqual(call.args[1].count("NWS Flood Watch"), 1)
        self.assertFalse(self.alarms.pending)

    async def test_new_high_priority_alert_moves_ahead_of_unsent_lower_priority(self):
        low = hazard("low", urgency="Future")
        await self.poll({"low": low})
        high = hazard("high", event="Flash Flood Warning", severity="Extreme")
        await self.poll({"low": low, "high": high})
        await self.alarms.send_one()
        self.assertIn("FLASH FLOOD WARNING", self.notify.await_args.args[1])
        self.advance(5)
        await self.alarms.send_one()
        self.assertIn("Flood Watch", self.notify.await_args.args[1])

    async def test_unchanged_poll_preserves_pending_notice_but_not_repeats_after_send(
        self,
    ):
        value = hazard("a")
        await self.poll({"a": value})
        await self.poll({"a": value})
        await self.alarms.send_one()
        await self.poll({"a": value})
        self.assertFalse(await self.alarms.send_one())
        self.assertEqual(self.notify.await_count, 1)

    async def test_superseded_update_replaces_pending_and_identical_id_replacement_survives(
        self,
    ):
        original = hazard("a")
        await self.poll({"a": original})
        updated = hazard(
            "b", fingerprint="new", references=["a"], event="Flood Warning"
        )
        await self.poll({"b": updated})
        self.assertEqual(len(self.alarms.pending), 1)
        await self.alarms.send_one()
        self.assertIn("NWS FLOOD WARNING. | UPDATED", self.notify.await_args.args[1])
        fresh = hazard("c")
        await self.poll({"c": fresh})
        replacement = hazard("d", references=["c"])
        await self.poll({"d": replacement})
        await self.alarms.send_one()
        self.assertEqual(
            self.notify.await_args.args[0]["_notification"]["notice"]["alert"]["id"],
            "d",
        )

    async def test_unconfirmed_removal_sends_no_empty_feed_notice_after_poll_or_recovery(self):
        for recovered in (False, True):
            with self.subTest(recovered=recovered):
                await self.poll({'a': hazard('a', event='Flash Flood Warning')})
                if recovered:
                    await self.poll(unavailable=True)
                await self.poll({})
                self.notify.reset_mock()
                while await self.alarms.send_one():
                    self.advance(5)
                texts = [call.args[1] for call in self.notify.await_args_list]
                self.assertTrue(any('missing; cancellation unconfirmed' in text for text in texts))
                self.assertFalse(any('No active NWS flood alerts' in text for text in texts))
                self.assertEqual(len(texts), 2 if recovered else 1)
                self.assertFalse(self.alarms.pending)
                await self.poll({})
                self.assertFalse(await self.alarms.send_one())

    async def test_cancelled_or_expired_pending_alert_cannot_send_active_description(
        self,
    ):
        await self.poll({"a": hazard("a")})
        await self.poll({}, cancelled=["a"])
        await self.alarms.send_one()
        self.assertIn("cancelled by NWS", self.notify.await_args.args[1])
        self.assertNotIn("Conditions favorable", self.notify.await_args.args[1])
        self.advance(5)
        await self.alarms.send_one()
        self.assertIn("No active NWS flood alerts", self.notify.await_args.args[1])
        await self.poll({"b": hazard("b", expires=self.now + 305)})
        self.advance(5)
        self.assertFalse(await self.alarms.send_one())

    async def test_outage_suppresses_queued_active_notice_then_recovery_restates_active(
        self,
    ):
        value = hazard("a")
        await self.poll({"a": value})
        await self.poll(unavailable=True)
        await self.alarms.send_one()
        self.assertEqual(
            self.notify.await_args.args[1],
            "NWS alerts unavailable; status unknown. | Test City",
        )
        await self.poll(unavailable=True)
        self.assertFalse(await self.alarms.send_one())
        await self.poll({"a": value})
        await self.alarms.send_one()
        self.assertIn("NWS Flood Watch. | ACTIVE", self.notify.await_args.args[1])
        self.advance(5)
        await self.alarms.send_one()
        self.assertIn("monitoring restored", self.notify.await_args.args[1])

    async def test_no_alert_status_is_removed_if_an_alert_appears_before_delivery(self):
        await self.poll({"a": hazard("a")})
        await self.poll({}, cancelled=["a"])
        await self.poll({"b": hazard("b", references=["a"])})
        await self.alarms.send_one()
        self.advance(5)
        self.assertFalse(await self.alarms.send_one())
        self.assertNotIn("No active", self.notify.await_args.args[1])

    async def test_stop_replacement_expiry_and_assignment_disable_pending_output(self):
        for action in ("stop", "replacement", "expiry", "assignment"):
            with self.subTest(action=action):
                self.allowed = True
                self.data = sample(self.now)
                await self.enroll()
                await self.poll({"a": hazard("a", expires=self.now + 10000)})
                if action == "stop":
                    self.alarms.remember(self.request("stop"), self.now)
                elif action == "replacement":
                    self.alarms.remember(self.request("Other City"), self.now)
                elif action == "expiry":
                    self.advance(14400)
                else:
                    self.allowed = False
                self.assertFalse(await self.alarms.send_one())
        self.notify.assert_not_awaited()

    async def test_radio_wait_guard_rejects_changed_alert_and_keeps_replacement(self):
        await self.poll({"a": hazard("a")})

        async def radio_wait(reading, text):
            self.assertTrue(self.alarms.notification_current(reading))
            await self.poll({"a": hazard("a", fingerprint="changed")})
            self.assertFalse(self.alarms.notification_current(reading))

        self.notify.side_effect = radio_wait
        await self.alarms.send_one()
        self.assertEqual(len(self.alarms.pending), 1)
        self.notify.side_effect = None
        self.advance(5)
        await self.alarms.send_one()
        self.assertIn("UPDATED", self.notify.await_args.args[1])

    async def test_stale_queue_requests_refresh_without_sending_then_recovers(self):
        value = hazard("a")
        await self.poll({"a": value})
        self.advance(301)
        self.assertFalse(await self.alarms.send_one())
        self.assertTrue(self.alarms.pending)
        self.assertLessEqual(self.alarms.row("Alice")["next_check"], self.now)
        await self.poll({"a": value})
        self.assertTrue(await self.alarms.send_one())

    async def test_failed_send_is_not_replayed_and_other_alerts_wait_five_seconds(self):
        await self.poll({"a": hazard("a"), "b": hazard("b")})
        self.notify.side_effect = RuntimeError("uncertain acceptance")
        with self.assertRaises(RuntimeError):
            await self.alarms.send_one()
        self.notify.side_effect = None
        self.assertFalse(await self.alarms.send_one())
        self.advance(5)
        self.assertTrue(await self.alarms.send_one())
        self.assertEqual(
            self.notify.await_args.args[0]["_notification"]["notice"]["alert"]["id"],
            "b",
        )

    async def test_initial_alerts_wait_for_ack_and_restart_does_not_replay_queue(self):
        self.advance(5)
        self.data = sample(self.now, events={"a": hazard("a")})
        request, text = await self.enroll(ack=False)
        self.assertNotIn("Flood Watch", text)
        self.assertFalse(await self.alarms.send_one())
        self.alarms.acknowledge(request)
        self.assertTrue(self.alarms.pending)
        restarted = FloodAlarms(
            self.db,
            "default",
            "key",
            {},
            self.read,
            self.notify,
            lambda: True,
            lambda: self.now,
            monotonic=lambda: self.tick,
        )
        self.assertFalse(restarted.pending)
        self.assertTrue(restarted.current(restarted.row("Alice")))
        await self.alarms.send_one()
        self.assertIn("| ACTIVE", self.notify.await_args.args[1])
        self.assertNotIn("readings", self.alarms.row("Alice")["baseline"])

    async def test_polling_continues_while_notification_waits_on_radio(self):
        await self.poll({"a": hazard("a")})
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked(*args):
            entered.set()
            await release.wait()

        self.notify.side_effect = blocked
        task = asyncio.create_task(self.alarms.send_one())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await self.poll({"a": hazard("a"), "b": hazard("b", severity="Extreme")})
            self.assertEqual(len(self.alarms.pending), 2)
        finally:
            release.set()
            await task

    async def test_service_shutdown_cancels_both_workers_and_does_not_replay(self):
        await self.poll({"a": hazard("a")})
        entered = asyncio.Event()

        async def block(*args):
            entered.set()
            await asyncio.Event().wait()

        self.notify.side_effect = block
        task = asyncio.create_task(self.alarms.run())
        try:
            await asyncio.wait_for(entered.wait(), 1)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(self.alarms.pending)


if __name__ == "__main__":
    unittest.main()
