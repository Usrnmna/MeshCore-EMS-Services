"""Exercise the actual bridge with a fake radio and retained MQTT outbox.

These tests protect channel privacy, serialized radio commands and bounded stop;
they do not send radio packets or claim hardware delivery.
"""

import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from meshcore import EventType

import service


class ChannelBridgeTests(unittest.IsolatedAsyncioTestCase):
    """Run mixed public/private requests through the production bridge coroutine."""

    async def exercise_bridge(self, *, blocked=False):
        """Build disposable state and verify routing, export policy and clean cancellation."""
        cfg = json.loads((service.ROOT / "config.json").read_text())
        cfg["command_interval"] = 0
        cfg["responder"]["channels"] = {
            "public": {"name": "Public", "type": "public", "mqtt_export": True},
            "ops": {"name": "Operations", "type": "existing", "mqtt_export": False},
        }
        for command in cfg["responder"]["commands"].values():
            command["channels"] = ["public", "ops"]
        keys = [bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72"), bytes(range(16))]
        sent = []
        finished = asyncio.Event()
        busy = False
        overlap = []
        fetch_entered = asyncio.Event()
        release_fetch = asyncio.Event()

        async def get_channel(index):
            """Flag concurrent radio commands and return a faithful channel-info event."""
            if busy:
                overlap.append(index)
            if index > 1:
                return SimpleNamespace(type=EventType.ERROR)
            await asyncio.sleep(0)
            return SimpleNamespace(
                type=EventType.CHANNEL_INFO,
                payload={
                    "channel_idx": index,
                    "channel_name": "Public" if index == 0 else "Operations",
                    "channel_secret": keys[index],
                },
            )

        async def get_msg():
            """Hold an SDK fetch in progress while receive callbacks request verification."""
            nonlocal busy
            busy = True
            fetch_entered.set()
            try:
                await release_fetch.wait()
                return SimpleNamespace(type=EventType.NO_MORE_MSGS, payload={})
            finally:
                busy = False

        mc = SimpleNamespace(
            self_info={"name": "Bot"},
            is_connected=True,
            commands=SimpleNamespace(get_channel=get_channel, get_msg=get_msg),
            unsubscribe=Mock(),
            disconnect=AsyncMock(),
        )
        callbacks = []

        def subscribe(kind, callback):
            """Keep the SDK callback without scheduling events before bridge setup."""
            mc.callback = callback
            return 1

        async def send(mc, index, text):
            """Record accepted radio sends and signal when both channel replies arrive."""
            sent.append((index, text))
            if len(sent) == 2:
                finished.set()
            return SimpleNamespace(type=EventType.MSG_SENT, payload={"sent": True})

        async def fetch():
            """Schedule SDK-like background events while a serialized fetch owns the radio."""
            callbacks.append(asyncio.create_task(mc.commands.get_msg()))
            await fetch_entered.wait()
            for index in (0, 1, 7):
                event = SimpleNamespace(
                    type=EventType.CHANNEL_MSG_RECV,
                    attributes={},
                    payload={
                        "channel_idx": index,
                        "txt_type": 0,
                        "text": "Alice: !status",
                        "sender_timestamp": int(time.time()),
                    },
                )
                callbacks.append(asyncio.create_task(mc.callback(event)))
            await asyncio.sleep(0.01)
            if not blocked:
                release_fetch.set()

        mc.subscribe = subscribe
        mc.start_auto_message_fetching = fetch
        client = SimpleNamespace(is_connected=lambda: False, disconnect=Mock(), loop_stop=Mock())

        async def retain_outbox(*args):
            """Leave events in SQLite so assertions can inspect every attempted export."""
            await asyncio.Event().wait()

        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            with patch.object(service, "RUNTIME", runtime), patch.object(
                service, "make_mqtt", return_value=client
            ), patch.object(service, "publish_outbox", retain_outbox):
                task = asyncio.create_task(
                    service.bridge_loop(mc, SimpleNamespace(send_chan_msg=send), cfg, "COM11")
                )
                try:
                    if blocked:
                        await asyncio.wait_for(fetch_entered.wait(), 2)
                        await asyncio.sleep(0.03)
                    else:
                        await asyncio.wait_for(finished.wait(), 3)
                        await asyncio.sleep(0.02)
                finally:
                    task.cancel()
                    # The fake SDK does not cancel get_msg on disconnect; real SDK does.
                    callbacks[0].cancel() if callbacks else None
                    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
                    await asyncio.gather(*callbacks, return_exceptions=True)
            mc.disconnect.assert_awaited_once()
            self.assertIs(mc.commands.get_msg, get_msg)
            self.assertEqual(overlap, [])
            if not blocked:
                self.assertEqual(
                    sorted(sent),
                    [
                        (0, "@Alice Local command service is running."),
                        (1, "@Alice Local command service is running."),
                    ],
                )
                import sqlite3

                with sqlite3.connect(runtime / "bridge.sqlite3") as db:
                    records = [json.loads(row[0]) for row in db.execute("SELECT body FROM outbox")]
                    channel_records = [r for r in records if "channel_idx" in r["payload"]]
                    self.assertTrue(channel_records)
                    self.assertEqual(
                        {r["payload"]["channel_id"] for r in channel_records}, {"public"}
                    )
                    self.assertNotIn(keys[1].hex(), json.dumps(records))
                    self.assertEqual(
                        db.execute(
                            "SELECT COUNT(*) FROM bot_requests WHERE state='sent'"
                        ).fetchone()[0],
                        2,
                    )
                db.close()

    async def test_mixed_channels_share_radio_without_exporting_private_messages(self):
        """Both requests reply independently, while private/unknown traffic stays off MQTT."""
        await self.exercise_bridge()

    async def test_stop_cancels_receive_callbacks_waiting_for_radio(self):
        """Stopping with queued verification callbacks finishes without a serial-timeout wait."""
        await self.exercise_bridge(blocked=True)


if __name__ == "__main__":
    unittest.main()
