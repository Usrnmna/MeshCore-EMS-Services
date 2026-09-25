"""Read-only end-to-end check. Selects the sole supported serial entry via -S.

Requires an idle USB companion radio and unused localhost port 1883.
Opens USB and localhost sockets and writes runtime state. Sends no over-the-air messages.
"""
import asyncio
import json
import threading
import uuid
from unittest.mock import patch

import paho.mqtt.client as mqtt
import service


class SelectOnlyCOM:
    """Diagnostic selector for exactly one supported serial device; retained name also used in the Linux package."""
    def __init__(self, **kwargs):
        """Keep the choices supplied by the upstream device dialog."""
        self.values = kwargs["values"]

    async def run_async(self):
        """Return the only discovered choice; raise if no device or multiple devices exist."""
        if len(self.values) != 1:
            raise RuntimeError("This check requires exactly one discovered COM device")
        return self.values[0][0]


async def check():
    """Start a local broker and USB session, issue read-only infos, verify MQTT results, and clean up connections."""
    cfg = json.loads((service.ROOT / "config.json").read_text())
    cfg["responder"] = {"enabled": False}  # This diagnostic must remain read-only.
    if cfg["mqtt"]["host"] != "127.0.0.1" or cfg["mqtt"]["tls"]:
        raise ValueError("This check uses the local broker only")
    broker = await service.start_local_broker(cfg["mqtt"]["port"])
    rid = "smoke-" + uuid.uuid4().hex
    ready, online, done = threading.Event(), threading.Event(), threading.Event()
    events, results = [], []
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=rid)
    prefix = cfg["mqtt"]["prefix"]
    client.on_connect = lambda c, u, f, r, p: c.subscribe(prefix + "/#", qos=1)
    client.on_subscribe = lambda *a: ready.set()

    def receive(c, u, msg):
        """Collect MQTT event topics/status/results and signal waiting diagnostic steps."""
        if "/events/" in msg.topic:
            events.append(msg.topic)
        if msg.topic == prefix + "/status" and json.loads(msg.payload).get("state") == "online":
            online.set()
        if msg.topic.endswith("/results/" + rid):
            results.append(json.loads(msg.payload))
            done.set()

    client.on_message = receive
    task = None
    try:
        client.connect_async("127.0.0.1", cfg["mqtt"]["port"])
        client.loop_start()
        assert await asyncio.to_thread(ready.wait, 8), "MQTT subscription failed"
        task = asyncio.create_task(service.radio_mode(cfg))
        assert await asyncio.to_thread(online.wait, 8), "Bridge not online"
        client.publish(prefix + "/command", json.dumps({"id": rid, "argv": ["infos"]}), qos=1)
        assert await asyncio.to_thread(done.wait, 12), "No command result received"
        assert results[0]["payload"]["status"] == "completed", results
        assert events, "No events received"
        print("LIVE CHECK PASSED: radio events published; MQTT infos command executed and result received.")
        print("Event types:", sorted(set(events)))
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        client.disconnect()
        await asyncio.to_thread(client.loop_stop)
        await broker.shutdown()


if __name__ == "__main__":
    service.RUNTIME.mkdir(exist_ok=True)
    with patch("prompt_toolkit.shortcuts.radiolist_dialog", SelectOnlyCOM):
        asyncio.run(asyncio.wait_for(check(), 35))
