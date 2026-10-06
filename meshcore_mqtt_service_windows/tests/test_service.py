"""Offline bridge tests: MQTT input validation, event encoding, durable SQLite state, and a fake radio."""

import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import service


class ServiceTests(unittest.TestCase):
    def test_packet_keeps_metadata_and_binary(self):
        record = service.envelope(
            "RX_LOG_DATA",
            {"snr": -3.5, "rssi": -112, "raw": b"\x00\xff", "path": "aabb", "text": "hello"},
            "COM11",
            {"source": "radio"},
        )
        decoded = json.loads(json.dumps(record))
        self.assertEqual(decoded["payload"]["raw"], {"encoding": "hex", "data": "00ff"})
        self.assertEqual(decoded["payload"]["snr"], -3.5)
        self.assertEqual(decoded["attributes"]["source"], "radio")

    def test_secret_redaction(self):
        self.assertEqual(service.normalize({"private_key": "hidden"})["private_key"], "[redacted]")

    def test_message_is_one_argument(self):
        rid, tokens = service.validate_request(
            b'{"id":"test1","argv":["chan","0","hello; reboot"]}'
        )
        self.assertEqual(tokens, ["chan", "0", "hello; reboot"])

    def test_invalid_commands(self):
        for argv in [
            ["script", "evil.txt"],
            ["infos", "reboot"],
            ["-s", "COM9"],
            ["chan", "x", "text"],
            ["msg", "Alice", "\nreboot"],
            ["msg", "A", "x" * 151],
        ]:
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                service.validate_request(json.dumps({"id": "test", "argv": argv}).encode())

    def test_invalid_request_shapes(self):
        for value in [[], None, {"argv": ["infos"]}, {"id": "../bad", "argv": ["infos"]}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                service.validate_request(json.dumps(value).encode())

    def test_outbox_and_request_dedup_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.sqlite3"
            store = service.Store(path)
            store.put("events/test", {"text": "kept"})
            self.assertTrue(store.claim("abc"))
            store.db.close()
            reopened = service.Store(path)
            self.assertFalse(reopened.claim("abc"))
            row = reopened.next()
            self.assertEqual(json.loads(row[2]), {"text": "kept"})
            reopened.ack(row[0])
            self.assertIsNone(reopened.next())
            reopened.db.close()

    def test_real_cli_command_parser_with_fake_radio(self):
        async def run():
            cli = service.prepare_cli()
            output = __import__("io").StringIO()
            mc = SimpleNamespace(
                self_info={"name": "synthetic node", "public_key": "abcd"},
                commands=SimpleNamespace(send_appstart=AsyncMock()),
            )
            self.assertTrue(await cli.process_cmds(mc, ["infos"], json_output=True, sink=output))
            self.assertEqual(json.loads(output.getvalue())["name"], "synthetic node")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
