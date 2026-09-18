"""Real local broker test, no radio or radio transmissions. Requires loopback sockets."""
import asyncio
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from meshcore import EventType

import paho.mqtt.client as mqtt
import service


class MQTTIntegration(unittest.TestCase):
    def test_channel_request_runs_script_and_real_cli_reply_helper(self):
        async def run():
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            broker = await service.start_local_broker(port)
            ready, received = threading.Event(), threading.Event()
            replies = []
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="responder-test-subscriber")
            client.on_connect = lambda c,u,f,r,p: c.subscribe("meshcore/windows/events/bot_reply", qos=1)
            client.on_subscribe = lambda *args: ready.set()
            def receive(c, u, msg):
                replies.append(json.loads(msg.payload))
                received.set()
            client.on_message = receive
            cfg = json.loads((service.ROOT / "config.json").read_text())
            cfg["mqtt"]["port"] = port
            cfg["command_interval"] = 0
            async def get_channel(index):
                if index > 1:
                    return SimpleNamespace(type=EventType.ERROR)
                return SimpleNamespace(type=EventType.CHANNEL_INFO, payload={
                    "channel_name": "Public" if index == 0 else "#autatestbot", "channel_idx": index})
            mc = SimpleNamespace(self_info={"name": "Bot"}, is_connected=True,
                commands=SimpleNamespace(get_channel=get_channel, send_chan_msg=AsyncMock(return_value=
                    SimpleNamespace(type=EventType.MSG_SENT, payload={"sent": True}))),
                disconnect=AsyncMock(), unsubscribe=lambda subscription: None)
            def subscribe(event_type, callback):
                mc.callback = callback
                return 1
            mc.subscribe = subscribe
            async def fetch():
                event = SimpleNamespace(type=EventType.CHANNEL_MSG_RECV, attributes={}, payload={
                    "channel_idx": 1, "txt_type": 0, "text": "Alice: !status",
                    "sender_timestamp": int(time.time())})
                await mc.callback(event)
                await mc.callback(event)  # A duplicate must not launch another script.
            mc.start_auto_message_fetching = fetch
            cli, _ = service.prepare_cli()
            task = None
            try:
                client.connect_async("127.0.0.1", port)
                client.loop_start()
                self.assertTrue(await asyncio.to_thread(ready.wait, 8))
                with tempfile.TemporaryDirectory() as folder, patch.object(service, "RUNTIME", Path(folder)):
                    task = asyncio.create_task(service.bridge_loop(mc, cli, cfg, "COM11"))
                    self.assertTrue(await asyncio.to_thread(received.wait, 8), "No bot reply published")
                    self.assertEqual(replies[0]["payload"]["text"], "@Alice Local command service is running.")
                    mc.commands.send_chan_msg.assert_awaited_once_with(1, "@Alice Local command service is running.")
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    task = None
            finally:
                if task:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                client.disconnect()
                await asyncio.to_thread(client.loop_stop)
                await broker.shutdown()
        asyncio.run(run())

    def test_qos1_roundtrip_and_durable_outbox(self):
        async def run():
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            broker = await service.start_local_broker(port)
            ready, received = threading.Event(), threading.Event()
            messages = []
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bridge-integration")
            client.on_connect = lambda c, u, f, r, p: c.subscribe("test/events/#", qos=1)
            client.on_subscribe = lambda *args: ready.set()
            def on_message(c, u, msg):
                messages.append(json.loads(msg.payload))
                received.set()
            client.on_message = on_message
            task = None
            try:
                client.connect_async("127.0.0.1", port)
                client.loop_start()
                self.assertTrue(await asyncio.to_thread(ready.wait, 8), "Subscription not acknowledged")
                with tempfile.TemporaryDirectory() as folder:
                    store = service.Store(Path(folder) / "outbox.sqlite3")
                    event = service.envelope("CHANNEL_MSG_RECV", {"text": "local test", "snr": 5.25}, "COM-test")
                    store.put("test/events/channel_msg_recv", event)
                    task = asyncio.create_task(service.publish_outbox(client, store))
                    self.assertTrue(await asyncio.to_thread(received.wait, 8), "MQTT event not received")
                    for _ in range(100):
                        if store.next() is None:
                            break
                        await asyncio.sleep(0.05)
                    self.assertIsNone(store.next(), "Outbox was not acknowledged")
                    self.assertEqual(messages[0], event)
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    task = None
                    store.db.close()
            finally:
                if task:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                client.disconnect()
                await asyncio.to_thread(client.loop_stop)
                await broker.shutdown()
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
