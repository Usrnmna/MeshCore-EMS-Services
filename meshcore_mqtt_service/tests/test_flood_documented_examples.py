"""Exercise documented hypothetical replies through the real subscription queue.

Only clocks, provider reads and the radio callback are simulated. Expected
response text is read from the shipped guide, including punctuation and timezone.
"""

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
import unittest
from unittest.mock import AsyncMock, patch

from flood_alarm import FloodAlarms
from test_floodwarn_responses import NOW, record, snapshot

ROOT = Path(__file__).resolve().parents[1]
EXPIRES = datetime(2026, 10, 21, 4, tzinfo=timezone.utc).timestamp()
UPDATE = "Material update replaces a queued version"
CANCEL = "Confirmed cancellation removes a queued active alert"
EXPIRE = "Expiration suppresses an active notification"
DISAPPEAR = "Disappearance remains explicitly unconfirmed"
RECOVERY = "Outage suppresses active notices; recovery restates current alerts"


def documented_examples():
    """Read only lifecycle examples; fail if their section or scenario headings drift."""
    guide = (ROOT / "WATER_GUIDE.md").read_text(encoding="utf-8")
    section = guide.split("### Hypothetical lifecycle and recovery examples\n", 1)[1]
    section = section.split("\n## ", 1)[0]
    sections = re.findall(r"^#### ([^\n]+)\n(.*?)(?=^#### |\Z)", section, re.M | re.S)
    return section, {
        title: re.findall(r"```text\n(.*?)\n```", body, re.S)
        for title, body in sections
    }


class DocumentedNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        timezone_patch = patch.dict(
            os.environ, {"MESHCORE_TIMEZONE": "America/Los_Angeles"}
        )
        timezone_patch.start()
        self.addCleanup(timezone_patch.stop)
        self.section, self.examples = documented_examples()
        self.now, self.tick = NOW, 100.0
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.data = self.source()
        self.notify = AsyncMock()
        self.alarms = FloodAlarms(
            self.db,
            "default",
            "key",
            {},
            AsyncMock(side_effect=lambda *args: deepcopy(self.data)),
            self.notify,
            lambda: True,
            lambda: self.now,
            monotonic=lambda: self.tick,
        )
        request = dict(
            id="enroll",
            command="!floodalarm",
            sender="Alice",
            sender_timestamp=int(self.now),
            arguments=["Sacramento"],
        )
        self.assertTrue(self.alarms.remember(request, self.now))
        _, error = await self.alarms.control(request)
        self.assertEqual(error, "")
        self.alarms.acknowledge(request)
        self.assertTrue(await self.alarms.send_one())
        self.notify.reset_mock()

    def source(self, *alerts):
        """Use a fresh synthetic point response without gauge observations or history."""
        value = snapshot(*alerts)
        value["fetched"] = self.now
        value["official"]["data"]["fetched"] = self.now
        return value

    def warning(self, **fields):
        return record(expires=EXPIRES, **fields)

    def advance(self, seconds):
        self.now += seconds
        self.tick += seconds

    async def poll(self, *alerts, cancelled=(), unavailable=False):
        """Drive the scheduled source check, including its baseline and queue mutations."""
        self.advance(300)
        self.data = self.source(*alerts)
        self.data["official"]["data"]["cancelled_ids"] = list(cancelled)
        if unavailable:
            self.data["official"] = {"status": "unavailable"}
        self.assertTrue(await self.alarms.check_one())

    def queued_reading(self):
        item = next(iter(self.alarms.pending.values()))
        return dict(item["reading"], _notification=item)

    async def assert_responses(self, expected):
        """Require exact complete responses, five-second minimum gaps and no extra output."""
        self.notify.reset_mock()
        for index, text in enumerate(expected):
            if index:
                self.assertFalse(await self.alarms.send_one())
                self.advance(4)
                self.assertFalse(await self.alarms.send_one())
                self.advance(1)
            self.assertTrue(await self.alarms.send_one())
            self.assertEqual(self.notify.await_args.args[1], text)
        self.advance(5)
        self.assertFalse(await self.alarms.send_one())
        self.assertEqual([c.args[1] for c in self.notify.await_args_list], expected)
        self.assertFalse(self.alarms.pending)

    async def test_document_inventory_keeps_all_nine_hypothetical_responses_covered(
        self,
    ):
        self.assertIn("hypothetical, not live", self.section)
        counts = {
            title: len(blocks) for title, blocks in self.examples.items() if blocks
        }
        self.assertEqual(
            counts, {UPDATE: 1, CANCEL: 1, EXPIRE: 2, DISAPPEAR: 1, RECOVERY: 4}
        )
        self.assertTrue(
            all(
                text.startswith("NWS") or text.startswith("No active")
                for blocks in self.examples.values()
                for text in blocks
            )
        )

    async def check_update(self, replacement):
        await self.poll(self.warning())
        old = self.queued_reading()
        updated = self.warning(
            key="b" if replacement else "a",
            fingerprint="material-update",
            references=["a"] if replacement else [],
        )
        await self.poll(updated)
        self.assertFalse(self.alarms.notification_current(old))
        self.assertEqual(len(self.alarms.pending), 1)
        await self.assert_responses(self.examples[UPDATE])
        await self.poll(updated)
        self.assertFalse(await self.alarms.send_one())
        self.assertEqual(self.notify.await_count, 1)

    async def test_documented_update_replaces_queued_same_id_version(self):
        await self.check_update(False)

    async def test_documented_update_follows_published_replacement_id(self):
        await self.check_update(True)

    async def test_documented_cancellation_suppresses_active_and_then_reports_empty(
        self,
    ):
        await self.poll(self.warning())
        old = self.queued_reading()
        await self.poll(cancelled=["a"])
        self.assertFalse(self.alarms.notification_current(old))
        await self.assert_responses(self.examples[CANCEL] + [self.examples[EXPIRE][1]])

    async def test_expired_queued_alert_waits_for_successful_check_before_expiry_notice(
        self,
    ):
        await self.poll(record(expires=self.now + 305))
        old = self.queued_reading()
        self.advance(5)
        self.assertFalse(self.alarms.notification_current(old))
        self.assertFalse(await self.alarms.send_one())
        self.notify.assert_not_awaited()
        await self.poll()
        await self.assert_responses(self.examples[EXPIRE])

    async def test_documented_disappearance_is_unconfirmed_and_suppresses_active(self):
        await self.poll(self.warning())
        old = self.queued_reading()
        await self.poll()
        self.assertFalse(self.alarms.notification_current(old))
        await self.assert_responses(self.examples[DISAPPEAR])

    async def test_documented_outage_and_recovery_restate_active_with_uncertainty(self):
        value = self.warning(severity="Unknown")
        await self.poll(value)
        old = self.queued_reading()
        await self.poll(unavailable=True)
        self.assertFalse(self.alarms.notification_current(old))
        await self.assert_responses([self.examples[RECOVERY][0]])
        await self.poll(unavailable=True)
        self.assertFalse(await self.alarms.send_one())
        await self.poll(value)
        await self.assert_responses(self.examples[RECOVERY][1:3])

    async def test_documented_empty_feed_recovery_does_not_emit_active_description(
        self,
    ):
        await self.poll(unavailable=True)
        await self.assert_responses([self.examples[RECOVERY][0]])
        await self.poll()
        await self.assert_responses([self.examples[RECOVERY][3]])

    async def test_returning_alert_suppresses_queued_cancellation_and_no_alert_claim(
        self,
    ):
        value = self.warning()
        await self.poll(value)
        await self.poll(cancelled=["a"])
        removed = [
            dict(item["reading"], _notification=item)
            for item in self.alarms.pending.values()
        ]
        self.assertEqual(len(removed), 2)
        await self.poll(value)
        self.assertTrue(
            all(not self.alarms.notification_current(item) for item in removed)
        )
        self.assertEqual(len(self.alarms.pending), 1)
        await self.assert_responses(
            [self.examples[UPDATE][0].replace("UPDATED", "NEW", 1)]
        )

    async def test_update_during_radio_wait_invalidates_old_guard_and_preserves_replacement(
        self,
    ):
        await self.poll(self.warning())

        async def radio_wait(reading, text):
            self.assertTrue(self.alarms.notification_current(reading))
            await self.poll(self.warning(fingerprint="material-update"))
            self.assertFalse(self.alarms.notification_current(reading))

        self.notify.side_effect = radio_wait
        self.assertTrue(await self.alarms.send_one())
        self.assertEqual(len(self.alarms.pending), 1)
        self.notify.side_effect = None
        self.assertFalse(await self.alarms.send_one())
        self.advance(5)
        await self.assert_responses(self.examples[UPDATE])


if __name__ == "__main__":
    unittest.main()
