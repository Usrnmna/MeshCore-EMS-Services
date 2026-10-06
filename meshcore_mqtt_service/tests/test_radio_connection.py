"""Transport selection, bounded lifecycle and shared tool behavior without a radio."""

import asyncio
from contextlib import asynccontextmanager
import io
import json
from pathlib import Path
import tempfile
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from meshcore import EventType
import channel_setup
import radio_connection as radio
import service


class ConnectionSettingsTests(unittest.TestCase):
    def test_legacy_and_selected_transport_validation(self):
        self.assertEqual(radio.connection_settings({})["type"], "serial")
        cfg = {
            "serial_port": "invalid",
            "baudrate": None,
            "connection": {"type": "tcp", "host": "192.168.1.50"},
        }
        self.assertEqual(radio.connection_settings(cfg)["port"], 5000)
        cfg["connection"] = {"type": "ble", "address": "aa:bb:cc:dd:ee:ff"}
        self.assertEqual(radio.connection_settings(cfg)["address"], "AA:BB:CC:DD:EE:FF")
        for connection in (
            None,
            [],
            {"type": "wifi"},
            {"type": []},
            {"type": "tcp"},
            {"type": "tcp", "host": "http://192.168.1.50"},
            {"type": "tcp", "host": "0.0.0.0"},
            {"type": "tcp", "host": "192.168.1.50", "port": True},
            {"type": "tcp", "host": "192.168.1.50", "port": 65536},
            {"type": "ble", "address": "MeshCore-first"},
            {"type": "serial", "host": "192.168.1.50"},
            {"timeout": float("nan")},
            {"timeout": True},
            {"timeout": 0},
        ):
            with self.subTest(connection=connection), self.assertRaises(ValueError):
                radio.connection_settings({"connection": connection})

    def test_endpoint_metadata_keeps_serial_port_and_has_no_credentials(self):
        serial = {"type": "serial", "port": "COM23"}
        tcp = {"type": "tcp", "host": "192.168.1.50", "port": 5000}
        ble = {"type": "ble", "address": "AA:BB:CC:DD:EE:FF", "port": None}
        for endpoint in (serial, tcp, ble):
            self.assertEqual(service.envelope("NODE", {}, endpoint)["device"], endpoint)
        self.assertEqual(service.envelope("NODE", {}, "COM23")["device"], {"port": "COM23"})


class RadioSessionTests(unittest.IsolatedAsyncioTestCase):
    def make_radio(self):
        """Keep SDK lifecycle separate from a mocked low-level transport."""
        return SimpleNamespace(connect=AsyncMock(return_value=object()), disconnect=AsyncMock())

    async def test_only_selected_transport_opens_and_closes(self):
        port = "COM23" if os.name == "nt" else "/dev/ttyUSB0"
        for kind, values, expected in (
            ("serial", {}, {"type": "serial", "port": port}),
            (
                "tcp",
                {"host": "192.168.1.50"},
                {"type": "tcp", "host": "192.168.1.50", "port": 5000},
            ),
            (
                "ble",
                {"address": "AA:BB:CC:DD:EE:FF"},
                {"type": "ble", "address": "AA:BB:CC:DD:EE:FF", "port": None},
            ),
        ):
            mc = self.make_radio()
            transport = SimpleNamespace(disconnect=AsyncMock())
            with patch("meshcore.MeshCore", return_value=mc) as sdk, patch(
                "meshcore.serial_cx.SerialConnection", return_value=transport
            ) as serial, patch(
                "meshcore.tcp_cx.TCPConnection", return_value=transport
            ) as tcp, patch(
                "meshcore.ble_cx.BLEConnection", return_value=transport
            ) as ble, patch.object(
                radio, "select_serial_port", return_value=port
            ) as select:
                async with radio.radio_session({"connection": {"type": kind, **values}}) as session:
                    self.assertIs(session[0], mc)
                    self.assertEqual(session[1], expected)
                self.assertEqual(
                    [serial.call_count, tcp.call_count, ble.call_count],
                    [int(kind == name) for name in ("serial", "tcp", "ble")],
                )
                self.assertEqual(select.call_count, int(kind == "serial"))
                sdk.assert_called_once_with(transport, auto_reconnect=False)
                mc.disconnect.assert_awaited_once()
                transport.disconnect.assert_awaited_once()

    async def test_serial_handshake_fallback_preserves_dtr_behavior(self):
        mc = self.make_radio()
        mc.connect.side_effect = [None, object()]
        transport = SimpleNamespace(disconnect=AsyncMock())
        with patch("meshcore.MeshCore", return_value=mc), patch(
            "meshcore.serial_cx.SerialConnection", return_value=transport
        ) as serial, patch.object(radio, "select_serial_port", return_value="COM23"):
            async with radio.radio_session({}):
                pass
        self.assertEqual([c.kwargs["dtr"] for c in serial.call_args_list], [True, False])
        self.assertEqual(transport.disconnect.await_count, 2)

    async def test_failure_and_cancellation_release_partial_connection(self):
        for failure in (ConnectionError("unreachable"), asyncio.CancelledError()):
            mc = self.make_radio()
            mc.connect.side_effect = failure
            transport = SimpleNamespace(disconnect=AsyncMock())
            with patch("meshcore.MeshCore", return_value=mc), patch(
                "meshcore.tcp_cx.TCPConnection", return_value=transport
            ):
                with self.assertRaises(type(failure)):
                    async with radio.radio_session(
                        {"connection": {"type": "tcp", "host": "127.0.0.1"}}
                    ):
                        self.fail("A failed connection must not start work")
            mc.disconnect.assert_awaited_once()
            transport.disconnect.assert_awaited_once()

    async def test_connection_timeout_closes_transport(self):
        mc = self.make_radio()
        mc.connect.side_effect = lambda: None

        async def stalled():
            await asyncio.Event().wait()

        mc.connect.side_effect = stalled
        transport = SimpleNamespace(disconnect=AsyncMock())
        with patch("meshcore.MeshCore", return_value=mc), patch(
            "meshcore.tcp_cx.TCPConnection", return_value=transport
        ):
            with self.assertRaises(TimeoutError):
                async with radio.radio_session(
                    {"connection": {"type": "tcp", "host": "127.0.0.1", "timeout": 1}}
                ):
                    self.fail("Timed-out connection must not start work")
        transport.disconnect.assert_awaited_once()

    async def test_real_sdk_tcp_handshake_and_remote_disconnect(self):
        """A loopback companion sends a fragmented real SELF_INFO frame, then drops TCP."""
        release = asyncio.Event()
        closed = asyncio.Event()
        requests = []

        async def companion(reader, writer):
            try:
                header = await reader.readexactly(3)
                requests.append(
                    (header[0], await reader.readexactly(int.from_bytes(header[1:], "little")))
                )
                payload = bytes([5]) + bytes(57) + b"loopback companion"
                frame = b">" + len(payload).to_bytes(2, "little") + payload
                writer.write(frame[:2])
                await writer.drain()
                await asyncio.sleep(0.01)
                writer.write(frame[2:])
                await writer.drain()
                await release.wait()
            finally:
                writer.close()
                await writer.wait_closed()
                closed.set()

        server = await asyncio.start_server(companion, "127.0.0.1", 0)
        cfg = {
            "connection": {
                "type": "tcp",
                "host": "127.0.0.1",
                "port": server.sockets[0].getsockname()[1],
            }
        }
        try:
            async with server, radio.radio_session(cfg) as (mc, endpoint):
                self.assertEqual(mc.self_info["name"], "loopback companion")
                self.assertTrue(mc.is_connected)
                self.assertEqual(endpoint["port"], cfg["connection"]["port"])
                release.set()
                async with asyncio.timeout(3):
                    while mc.is_connected:
                        await asyncio.sleep(0.01)
                self.assertEqual(requests[0][0], 0x3C)
                self.assertEqual(requests[0][1][0], 1)
        finally:
            release.set()
            await asyncio.wait_for(closed.wait(), 3)
            server.close()
            await server.wait_closed()

    async def test_tcp_health_check_recovers_from_silent_link_loss(self):
        """A healthy check is followed by a blackhole; exit despite is_connected staying true."""
        checked = 0

        async def query():
            nonlocal checked
            checked += 1
            if checked == 1:
                return SimpleNamespace(type=EventType.DEVICE_INFO)
            await asyncio.Event().wait()

        mc = SimpleNamespace(
            commands=SimpleNamespace(send_device_query=query),
            self_info={"name": "silent TCP node"},
            is_connected=True,
            subscribe=Mock(return_value=1),
            unsubscribe=Mock(),
            start_auto_message_fetching=AsyncMock(),
            disconnect=AsyncMock(),
        )
        client = SimpleNamespace(is_connected=lambda: False, disconnect=Mock(), loop_stop=Mock())

        async def retain_outbox(*args):
            await asyncio.Event().wait()

        cfg = json.loads((service.ROOT / "config.json").read_text())
        cfg["connection"] = {"type": "tcp", "host": "127.0.0.1"}
        cfg["responder"] = {"enabled": False}
        with tempfile.TemporaryDirectory() as folder, patch.object(
            service, "RUNTIME", Path(folder)
        ), patch.object(service, "TCP_HEALTH_INTERVAL_SECONDS", 0), patch.object(
            service, "TCP_HEALTH_TIMEOUT_SECONDS", 0.01
        ), patch.object(
            service, "make_mqtt", return_value=client
        ), patch.object(
            service, "publish_outbox", retain_outbox
        ):
            with self.assertRaisesRegex(ConnectionError, "health check failed"):
                await service.bridge_loop(mc, SimpleNamespace(), cfg, cfg["connection"])
        self.assertEqual(checked, 2)
        mc.disconnect.assert_awaited_once()
        client.disconnect.assert_called_once()

    async def test_bridge_cli_and_channel_setup_use_same_connection_settings(self):
        """Exercise entrypoints, including cleanup on command failure and channel listing."""
        cfg = {"connection": {"type": "tcp", "host": "192.168.1.50"}}
        mc = self.make_radio()
        mc.commands = SimpleNamespace(
            send_device_query=AsyncMock(
                return_value=SimpleNamespace(type=EventType.DEVICE_INFO, payload={"fw ver": 14})
            )
        )
        mc.set_decrypt_channel_logs = Mock()
        endpoints = []

        @asynccontextmanager
        async def session(config):
            self.assertIs(config, cfg)
            endpoints.append(config)
            try:
                yield mc, {"type": "tcp", "host": "192.168.1.50", "port": 5000}
            finally:
                await mc.disconnect()

        cli = SimpleNamespace(process_cmds=AsyncMock(return_value=True))
        with patch.object(service, "radio_session", session), patch.object(
            service, "prepare_cli", return_value=cli
        ), patch.object(service, "bridge_loop", new_callable=AsyncMock) as bridge:
            await service.radio_mode(cfg)
            bridge.assert_awaited_once()
            await service.radio_mode(cfg, ["infos"])
            cli.process_cmds.assert_awaited_once_with(mc, ["infos"], json_output=True)
            cli.process_cmds.return_value = False
            with self.assertRaisesRegex(RuntimeError, "CLI command failed"):
                await service.radio_mode(cfg, ["infos"])
        with patch.object(radio, "radio_session", session), patch.object(
            channel_setup, "discover", AsyncMock(return_value=[])
        ), patch("sys.stdout", new_callable=io.StringIO):
            await channel_setup.run(cfg, "list")
        self.assertEqual(len(endpoints), 4)
        self.assertEqual(mc.disconnect.await_count, 4)


if __name__ == "__main__":
    unittest.main()
