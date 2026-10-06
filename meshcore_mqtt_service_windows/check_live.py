"""Read-only end-to-end check. Uses the configured serial, BLE, or TCP connection.

Requires an idle compatible companion radio and unused configured localhost port (1884 by default).
Opens the configured radio interface and localhost sockets and writes runtime state. Sends no over-the-air messages.
"""

import asyncio
import json
import threading
import uuid

import paho.mqtt.client as mqtt
import service


async def check():
    """Start a local broker and radio session, issue read-only infos, verify MQTT results, and clean up connections."""
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
        assert await asyncio.to_thread(online.wait, 2 * cfg.get("connection", {}).get("timeout", 30) + 10), "Bridge not online"
        client.publish(prefix + "/command", json.dumps({"id": rid, "argv": ["infos"]}), qos=1)
        assert await asyncio.to_thread(done.wait, 12), "No command result received"
        assert results[0]["payload"]["status"] == "completed", results
        assert events, "No events received"
        print(
            "LIVE CHECK PASSED: radio events published; MQTT infos command executed and result received."
        )
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
    asyncio.run(check())
