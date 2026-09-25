"""USB MeshCore connection, MQTT event delivery, and channel-command orchestration.

Start reading at main() -> run_mode() -> radio_mode() -> bridge_loop().
Operator settings live in config.json; see README.md for configuration guidance.
This module opens serial/network connections and writes runtime/bridge.sqlite3.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import logging
import os
from pathlib import Path
import queue
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from enum import Enum

from responder import Responder, resolve_channel, validate_config

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
LOG = logging.getLogger("bridge")


def normalize(value):
    """Preserve packet data including binary fields; omit secret key material."""
    if isinstance(value, dict):
        return {str(k): ("[redacted]" if str(k).lower() in
                {"private_key", "priv_key", "secret", "password", "channel_secret"}
                else normalize(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    if isinstance(value, bytes):
        return {"encoding": "hex", "data": value.hex()}
    if isinstance(value, Enum):
        return value.name
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def envelope(kind, payload, port=None, attributes=None):
    """Wrap a payload in a timestamped, uniquely identified MQTT event; normalize binary and secret fields."""
    return {"schema": 1, "id": str(uuid.uuid4()),
            "received_at": datetime.now(timezone.utc).isoformat(),
            "event": kind, "device": {"port": port},
            "payload": normalize(payload), "attributes": normalize(attributes or {})}


class Store:
    """Durable, at-least-once publication; IDs permit consumer deduplication."""
    def __init__(self, path):
        """Open SQLite and create the durable event outbox and MQTT request-ID tables; writes to disk."""
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, topic TEXT, body TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY)")
        self.db.commit()

    def put(self, topic, body):
        """Serialize one event to JSON and commit it to the pending MQTT outbox."""
        self.db.execute("INSERT INTO outbox(topic,body) VALUES (?,?)", (topic, json.dumps(body)))
        self.db.commit()

    def claim(self, request_id):
        """Persist a request ID and return True only for its first appearance, preventing duplicate execution."""
        cur = self.db.execute("INSERT OR IGNORE INTO requests VALUES (?)", (request_id,))
        self.db.commit()
        return cur.rowcount == 1

    def next(self):
        """Return the oldest pending (row_id, topic, JSON_body), or None; does not remove it."""
        return self.db.execute("SELECT id,topic,body FROM outbox ORDER BY id LIMIT 1").fetchone()

    def ack(self, row_id):
        """Delete and commit a published outbox row after broker acknowledgement."""
        self.db.execute("DELETE FROM outbox WHERE id=?", (row_id,))
        self.db.commit()


def validate_request(raw):
    """Validate raw MQTT JSON against allowed CLI commands; return (id, argv) or raise ValueError."""
    if len(raw) > 8192:
        raise ValueError("Command exceeds 8192 bytes")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Command must be a JSON object")
    rid, tokens = data.get("id"), data.get("argv")
    if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", rid):
        raise ValueError("id must be 1-100 letters, digits, underscores or hyphens")
    if not isinstance(tokens, list) or not tokens or not all(isinstance(t, str) for t in tokens):
        raise ValueError("argv must be a nonempty array of strings")
    sizes = {"infos": 1, "ver": 1, "contacts": 1, "self_telemetry": 1,
             "clock": 1, "msg": 3, "chan": 3}
    if tokens[0] not in sizes or len(tokens) != sizes[tokens[0]]:
        raise ValueError("Unsupported command or incorrect argument count")
    if any("\x00" in t or "\r" in t or "\n" in t for t in tokens):
        raise ValueError("Arguments must be single-line text")
    if tokens[0] == "chan" and not re.fullmatch(r"\d{1,2}", tokens[1]):
        raise ValueError("Channel must be a numeric index")
    if tokens[0] in {"msg", "chan"} and (not tokens[1] or not tokens[2]
                                           or len(tokens[2].encode("utf-8")) > 150):
        raise ValueError("Destination and message required; message limit is 150 UTF-8 bytes")
    return rid, tokens


def make_mqtt(config, incoming, watch=False):
    """Start the MQTT client's background loop; subscribe to commands or watch events on connection."""
    import paho.mqtt.client as mqtt
    cfg = config["mqtt"]
    prefix = cfg["prefix"].strip("/")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=cfg["client_id"] + ("-watch-" + uuid.uuid4().hex[:8] if watch else ""))
    username = os.environ.get(cfg["username_env"])
    if username:
        client.username_pw_set(username, os.environ.get(cfg["password_env"]))
    if cfg.get("tls"):
        ca = cfg.get("ca_file")
        client.tls_set(ca_certs=str(ROOT / ca) if ca else None)
    client.reconnect_delay_set(1, 30)
    client.max_queued_messages_set(100)
    if not watch:
        client.will_set(prefix + "/status", '{"state":"offline"}', qos=1, retain=True)

    def on_connect(c, userdata, flags, reason, properties):
        """Subscribe after broker connection and publish retained online status for the bridge."""
        if reason.is_failure:
            LOG.error("MQTT connection refused: %s", reason)
            return
        c.subscribe(prefix + ("/events/#" if watch else "/command"), qos=1)
        if not watch:
            c.publish(prefix + "/status", '{"state":"online"}', qos=1, retain=True)
        LOG.info("MQTT connected to %s:%s", cfg["host"], cfg["port"])

    def on_message(c, userdata, message):
        """Reject retained bridge commands and enqueue incoming messages; log and discard queue overflow."""
        if message.retain and not watch:
            LOG.warning("Ignoring retained command")
            return
        try:
            incoming.put_nowait((message.topic, message.payload))
        except queue.Full:
            LOG.error("Incoming queue full; message rejected")

    client.on_connect, client.on_message = on_connect, on_message
    client.connect_async(cfg["host"], int(cfg["port"]), keepalive=30)
    client.loop_start()
    return client


async def publish_outbox(client, store):
    """Continuously publish queued events at QoS 1; delete rows only after acknowledgement, retaining failures."""
    while True:
        row = store.next()
        if row and client.is_connected():
            info = client.publish(row[1], row[2], qos=1, retain=False)
            try:
                await asyncio.to_thread(info.wait_for_publish, 5)
                if info.is_published():
                    store.ack(row[0])
            except (RuntimeError, ValueError):
                pass  # Keep the row until a broker acknowledgement arrives.
        await asyncio.sleep(0.05 if row else 0.25)


async def bridge_loop(mc, cli, config, port):
    """Own the connected radio/MQTT session, persist events, run the responder, and serialize radio actions."""
    bot_config = config.get("responder", {"enabled": False})
    validate_config(bot_config, ROOT)
    channel = await resolve_channel(mc, bot_config["channel_name"]) if bot_config.get("enabled") else None
    incoming = queue.Queue(maxsize=100)
    store = Store(RUNTIME / "bridge.sqlite3")
    prefix = config["mqtt"]["prefix"].strip("/")
    client = make_mqtt(config, incoming)
    publisher = asyncio.create_task(publish_outbox(client, store))
    command_lock = asyncio.Lock()
    next_command = 0.0

    async def execute(action):
        """Run one radio action under the shared lock, honoring command timeout and spacing in seconds."""
        nonlocal next_command
        async with command_lock:
            await asyncio.sleep(max(0, next_command - time.monotonic()))
            try:
                return await asyncio.wait_for(action(), config["command_timeout"])
            finally:
                next_command = time.monotonic() + config["command_interval"]

    async def send_reply(index, text, *, guard=None):
        """Recheck the channel name, send a tagged reply, and persist its result as a BOT_REPLY event."""
        from meshcore import EventType
        async def action():
            # Do not send to a different channel if the radio was reconfigured.
            """Verify the target channel still matches, ask the radio to send, and record acceptance; not recipient delivery."""
            info = await mc.commands.get_channel(index)
            if info.type != EventType.CHANNEL_INFO or info.payload.get("channel_name") != bot_config["channel_name"]:
                raise RuntimeError("Reply channel configuration changed")
            # ALARM EXPIRY: check after rate-limit/USB waits, immediately before transmission.
            if guard is not None and not guard():
                return
            result = await cli.send_chan_msg(mc, index, text)
            if result is None or result.type == EventType.ERROR:
                raise RuntimeError("Radio did not accept the channel reply")
            store.put(prefix + "/events/bot_reply", envelope("BOT_REPLY", {
                "channel_idx": index, "text": text, "result": result.payload}, port))
        await execute(action)

    bot = Responder(ROOT, store.db, bot_config, channel, mc.self_info.get("name", ""), send_reply) if channel is not None else None
    bot_task = asyncio.create_task(bot.run()) if bot else None

    async def receive(event):
        """Persist each radio event and offer decoded channel messages to the responder queue."""
        record = envelope(event.type.name, event.payload, port, getattr(event, "attributes", {}))
        store.put(prefix + "/events/" + event.type.name.lower(), record)
        if bot and event.type.name == "CHANNEL_MSG_RECV":
            bot.accept(event.payload)

    subscription = mc.subscribe(None, receive)
    store.put(prefix + "/events/node", envelope("NODE", mc.self_info, port))
    try:
        await mc.start_auto_message_fetching()
        LOG.info("Bridge active on %s. Ctrl+C stops it.", port)
        if bot:
            LOG.info("Automatic replies enabled on %s (channel %s)", bot_config["channel_name"], channel)
        while mc.is_connected:
            if publisher.done():
                publisher.result()
            if bot_task and bot_task.done():
                bot_task.result()
            try:
                topic, raw = incoming.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            try:
                rid, tokens = validate_request(raw)
            except (ValueError, UnicodeError) as exc:
                store.put(prefix + "/errors", envelope("COMMAND_REJECTED", {"error": str(exc)}, port))
                continue
            if not store.claim(rid):
                continue
            output = io.StringIO()
            result = {"request_id": rid}
            try:
                ok = await execute(lambda: cli.process_cmds(mc, tokens.copy(), json_output=True, sink=output))
                result.update(status="completed" if ok else "error", output=output.getvalue())
            except asyncio.TimeoutError:
                result.update(status="unknown", error="Timed out; command may have reached the radio. Not retried.")
            except Exception as exc:
                result.update(status="error", error=str(exc), output=output.getvalue())
            store.put(prefix + "/results/" + rid, envelope("COMMAND_RESULT", result, port))
        raise ConnectionError("USB radio disconnected. Restart to select a discovered serial device with -S.")
    finally:
        mc.unsubscribe(subscription)
        if bot_task:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)
        await mc.disconnect()
        publisher.cancel()
        await asyncio.gather(publisher, return_exceptions=True)
        if client.is_connected():
            info = client.publish(prefix + "/status", '{"state":"offline"}', qos=1, retain=True)
            await asyncio.to_thread(info.wait_for_publish, 2)
        client.disconnect()
        client.loop_stop()
        store.db.close()


def supported_serial_port(port):
    """Return whether this package accepts the discovered serial-port name."""
    return bool(re.fullmatch(r"COM\d+", port, re.I))


def prepare_cli():
    # Upstream reads configuration at import time. Keep that configuration here.
    """Import the upstream CLI with package-local runtime settings and install the USB-only device selector."""
    home = RUNTIME / "home"
    local_config = home / ".config" / "meshcore"
    local_config.mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = os.environ["HOME"] = str(home)
    from meshcore_cli import meshcore_cli as cli
    cli.BLEAK_AVAILABLE = False
    original_dialog = cli.radiolist_dialog
    selected = {}

    def serial_dialog(**kwargs):
        """Filter discovered choices to supported serial devices and retain the user's selected device."""
        kwargs["values"] = [(value, label) for value, label in kwargs["values"]
                            if value.get("type") == "serial" and
                            supported_serial_port(value.get("port", ""))]
        if not kwargs["values"]:
            raise RuntimeError("No COM devices discovered. Connect a USB serial companion node and check Windows Device Manager.")
        dialog = original_dialog(**kwargs)

        class Selection:
            """Adapter that records the upstream device dialog's result before returning it."""
            async def run_async(self):
                """Await the device selection, save the selected port details, and return the user's choice."""
                choice = await dialog.run_async()
                if choice:
                    selected.update(choice)
                return choice
        return Selection()

    cli.radiolist_dialog = serial_dialog
    return cli, selected


async def radio_mode(config, command=None):
    """Use the upstream -S selector, then run the bridge or one CLI command; disconnect on completion."""
    cli, selected = prepare_cli()
    entered = False

    async def run_connected(mc, **kwargs):
        """Handle the selected radio session and dispatch either continuous bridge work or one CLI command."""
        nonlocal entered
        entered = True
        if command is None:
            try:
                await bridge_loop(mc, cli, config, selected["port"])
            finally:
                if mc.is_connected:
                    await mc.disconnect()
        else:
            try:
                if not await cli.process_cmds(mc, command.copy(), json_output=True):
                    raise RuntimeError("CLI command failed")
            finally:
                await mc.disconnect()

    run_connected.__dict__.update(cli.interactive_loop.__dict__)
    cli.interactive_loop = run_connected
    # Installed services opt into a saved port; foreground launchers retain -S.
    port = config.get("serial_port")
    if port:
        from service_runner import validate_serial_port
        validate_serial_port(port)
        selected["port"] = port
        connection = ["-s", port]
    else:
        connection = ["-S"]
    await cli.main([*connection, "-j", "-b", str(config["baudrate"])])
    if not entered:
        raise RuntimeError("No radio session started (no device, cancelled selection, or connection failed).")


async def watch(config):
    """Print MQTT event messages as JSON lines until cancelled; never opens a serial connection."""
    incoming = queue.Queue(maxsize=1000)
    client = make_mqtt(config, incoming, watch=True)
    try:
        while True:
            try:
                topic, raw = incoming.get_nowait()
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeError):
                    body = {"encoding": "base64", "data": base64.b64encode(raw).decode()}
                print(json.dumps({"topic": topic, "message": body}), flush=True)
            except queue.Empty:
                await asyncio.sleep(0.1)
    finally:
        client.disconnect()
        client.loop_stop()


async def start_local_broker(port=1884):
    """Start and return an anonymous broker bound to localhost; the caller must shut it down."""
    from amqtt.broker import Broker
    broker = Broker({
        "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}}
    })
    await broker.start()
    LOG.info("Local MQTT broker listening on 127.0.0.1:%s", port)
    return broker


async def run_mode(config, mode, command=None):
    """Start/reuse the local broker when required, dispatch a mode, and stop any broker created here."""
    broker = None
    if mode == "broker" or (mode == "bridge" and config.get("local_broker", False)):
        cfg = config["mqtt"]
        if cfg["host"] != "127.0.0.1" or cfg.get("tls"):
            raise ValueError("Built-in broker requires mqtt.host=127.0.0.1 and tls=false; disable local_broker for an external broker")
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", cfg["port"]), 1)
        except (ConnectionRefusedError, asyncio.TimeoutError):
            broker = await start_local_broker(cfg["port"])
        else:
            writer.close()
            await writer.wait_closed()
            if mode == "broker":
                raise RuntimeError("A server already listens on the configured local MQTT port")
            LOG.info("Using existing server on local MQTT port %s", cfg["port"])
    try:
        if mode == "broker":
            await asyncio.Event().wait()
        elif mode == "watch":
            await watch(config)
        else:
            await radio_mode(config, command)
    finally:
        if broker:
            await broker.shutdown()


def main():
    """Parse mode/config options, create runtime storage, validate settings, and start the selected mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("bridge", help="Select USB serial with MeshCore-cli -S and run bridge and channel responder")
    sub.add_parser("watch", help="Consume bridged MQTT packet events as JSON lines; no USB connection")
    sub.add_parser("ports", help="List discovered Windows COM devices")
    sub.add_parser("broker", help="Run the bundled local MQTT broker without connecting a radio")
    command = sub.add_parser("cli", help="Select USB serial with -S and execute local CLI command tokens")
    command.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    RUNTIME.mkdir(exist_ok=True)
    os.chdir(ROOT)
    if args.mode == "ports":
        from serial.tools.list_ports import comports
        ports = [p for p in comports() if supported_serial_port(p.device)]
        for p in ports:
            print(f"{p.device}: {p.description} [{p.hwid}]")
        if not ports:
            print("No USB serial devices discovered.")
        return 0
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    validate_config(config.get("responder", {"enabled": False}), ROOT)
    prefix = config["mqtt"]["prefix"].strip("/")
    if not prefix or any(c in prefix for c in "+#\x00"):
        raise ValueError("MQTT prefix must be a nonempty topic without wildcards")
    if config["command_timeout"] <= 0 or config["command_interval"] < 0:
        raise ValueError("Invalid command timeout or interval")
    if args.mode == "cli" and (not args.argv or args.argv[0].startswith("-")):
        parser.error("Provide CLI commands, for example: cli infos. Connection flags are managed by -S.")
    asyncio.run(run_mode(config, args.mode, args.argv if args.mode == "cli" else None))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        LOG.error("%s", exc)
        sys.exit(1)
