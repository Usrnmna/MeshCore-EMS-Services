"""Offline responder tests: matching, queue states, child limits, tagged replies, and serial-device filters."""
import asyncio
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from meshcore import EventType
import responder
import service


def config():
    return copy.deepcopy(json.loads((service.ROOT / "config.json").read_text())["responder"])


def packet(sender="Alice", phrase="!status", channel=3, timestamp=None):
    return {"channel_idx": channel, "txt_type": 0, "text": f"{sender}: {phrase}",
            "sender_timestamp": int(time.time()) if timestamp is None else timestamp}


class ResponderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.send = AsyncMock()
        self.cfg = config()
        self.bot = responder.Responder(service.ROOT, self.db, self.cfg, 3, "Local Bot", self.send)

    def tearDown(self):
        self.db.close()

    async def test_real_script_returns_tag_to_same_channel_and_saves_sender(self):
        self.assertTrue(self.bot.accept(packet("Alice Smith")))
        self.assertTrue(await self.bot.process_one())
        self.send.assert_awaited_once_with(3, "@Alice Smith Local command service is running.")
        row = self.db.execute("SELECT sender,state FROM bot_requests").fetchone()
        self.assertEqual(row, ("Alice Smith", "sent"))

    async def test_interleaved_senders_keep_their_own_context(self):
        self.bot.accept(packet("Alice"))
        self.bot.accept(packet("Bob"))
        await self.bot.process_one()
        await self.bot.process_one()
        self.assertEqual([call.args[1].split()[0] for call in self.send.await_args_list], ["@Alice", "@Bob"])

    async def test_wrong_channel_unknown_phrase_self_and_reply_are_ignored(self):
        for p in [packet(channel=0), packet(phrase="prefix !status"), packet(phrase="!STATUS"),
                  packet(phrase="!status; reboot"), packet("Local Bot"), packet(phrase="@Alice !status"),
                  {**packet(), "text": "!status"}, {**packet(), "sender_timestamp": None},
                  packet(timestamp=int(time.time()) - 3600), packet(timestamp=int(time.time()) + 3600)]:
            with self.subTest(p=p):
                self.assertFalse(self.bot.accept(p))
        self.send.assert_not_awaited()

    async def test_duplicate_survives_reopen_and_path_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            db = sqlite3.connect(Path(folder) / "requests.sqlite3")
            bot = responder.Responder(service.ROOT, db, self.cfg, 3, "Bot", self.send)
            p = packet()
            self.assertTrue(bot.accept(p))
            await bot.process_one()
            db.close()
            db = sqlite3.connect(Path(folder) / "requests.sqlite3")
            bot = responder.Responder(service.ROOT, db, self.cfg, 3, "Bot", self.send)
            self.assertFalse(bot.accept({**p, "path": "different", "SNR": 5}))
            db.close()
        self.send.assert_awaited_once()

    async def test_cooldown_and_queue_limits(self):
        self.assertTrue(self.bot.accept(packet("Alice")))
        self.assertFalse(self.bot.accept(packet("Alice", "!time")))
        self.cfg["max_pending"] = 1
        self.assertFalse(self.bot.accept(packet("Bob")))

    async def test_script_receives_sender_and_channel_on_stdin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "context.py").write_text("import json,sys\nr=json.load(sys.stdin)\nprint(r['sender'] + ' on ' + r['channel_name'])\n")
            request = responder.parse_message(packet("Person Name"), 3, "Bot", self.cfg, time.time())
            text, detail = await responder.run_script(root, {"script": "context.py"}, request, self.cfg)
            self.assertEqual(text.strip(), "Person Name on #autatestbot")

    async def test_script_failure_timeout_and_excess_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request = responder.parse_message(packet(), 3, "Bot", self.cfg, time.time())
            cases = [("raise RuntimeError('private detail')", "failed"),
                     ("import time; time.sleep(10)", "timed out"),
                     ("print('x' * 100000)", "output limit")]
            self.cfg["script_timeout"] = 0.3
            for code, expected in cases:
                (root / "run.py").write_text(code)
                reply, detail = await responder.run_script(root, {"script": "run.py"}, request, self.cfg)
                self.assertIn(expected, reply)
                self.assertNotIn("private detail", reply)

    async def test_failed_send_is_not_retried(self):
        self.send.side_effect = RuntimeError("USB disconnected")
        self.bot.accept(packet())
        await self.bot.process_one()
        self.assertFalse(await self.bot.process_one())
        self.assertEqual(self.db.execute("SELECT state FROM bot_requests").fetchone()[0], "failed")

    async def test_interrupted_jobs_are_not_executed_again(self):
        self.bot.accept(packet())
        self.db.execute("UPDATE bot_requests SET state='sending'")
        self.db.commit()
        bot = responder.Responder(service.ROOT, self.db, self.cfg, 3, "Bot", self.send)
        self.assertFalse(await bot.process_one())
        self.assertEqual(self.db.execute("SELECT state FROM bot_requests").fetchone()[0], "interrupted")

    async def test_channel_name_resolution_and_missing_channel(self):
        mc = SimpleNamespace(commands=SimpleNamespace(get_channel=AsyncMock(side_effect=[
            SimpleNamespace(type=EventType.CHANNEL_INFO, payload={"channel_idx": 0, "channel_name": "Public"}),
            SimpleNamespace(type=EventType.CHANNEL_INFO, payload={"channel_idx": 1, "channel_name": "#autatestbot"}),
            SimpleNamespace(type=EventType.ERROR)])))
        self.assertEqual(await responder.resolve_channel(mc, "#autatestbot"), 1)
        mc.commands.get_channel = AsyncMock(return_value=SimpleNamespace(type=EventType.ERROR))
        with self.assertRaisesRegex(RuntimeError, "Configure that channel"):
            await responder.resolve_channel(mc, "#autatestbot")

    async def test_unicode_replies_preserve_prefix_and_byte_limit(self):
        parts = responder.reply_parts("René", "温度" * 200, max_parts=3)
        self.assertEqual(len(parts), 3)
        for part in parts:
            self.assertTrue(part.startswith("@René "))
            self.assertLessEqual(len(part.encode()), 150)
        self.assertTrue(parts[-1].endswith("..."))

    async def test_script_paths_cannot_escape_folder(self):
        self.cfg["commands"]["!status"]["script"] = "../outside.py"
        with self.assertRaises(ValueError):
            responder.validate_config(self.cfg, service.ROOT)

    async def test_linux_and_windows_serial_devices(self):
        for name in ["COM11", "/dev/ttyACM0", "/dev/ttyUSB1", "/dev/serial/by-id/usb-node"]:
            self.assertTrue(service.supported_serial_port(name))
        for name in ["", "BLE:12345", "/etc/passwd"]:
            self.assertFalse(service.supported_serial_port(name))


if __name__ == "__main__":
    unittest.main()
