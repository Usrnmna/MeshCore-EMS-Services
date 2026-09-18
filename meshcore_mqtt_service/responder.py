"""Exact channel phrase -> local Python script -> tagged channel response."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path
import signal
import sys
import time

LOG = logging.getLogger("responder")


def validate_config(config, root):
    if not config.get("enabled", False):
        return
    if not isinstance(config.get("channel_name"), str) or not config["channel_name"]:
        raise ValueError("responder.channel_name is required")
    for key in ("script_timeout", "max_output_bytes", "max_reply_parts", "max_message_age", "max_pending"):
        if not isinstance(config.get(key), (int, float)) or config[key] <= 0:
            raise ValueError(f"responder.{key} must be positive")
    if config.get("sender_cooldown", -1) < 0:
        raise ValueError("responder.sender_cooldown must be nonnegative")
    commands = config.get("commands")
    if not isinstance(commands, dict) or not commands:
        raise ValueError("responder.commands must map phrases to scripts")
    for phrase, spec in commands.items():
        if not phrase.strip() or phrase != phrase.strip() or phrase.startswith("@") or not phrase.isprintable():
            raise ValueError("Command phrases must be printable, trimmed and not start with @")
        script_path(root, spec["script"])
        if not isinstance(spec.get("args", []), list) or not all(isinstance(x, str) for x in spec.get("args", [])):
            raise ValueError("Script args must be a list of fixed strings")
        if spec.get("input", "none") not in {"none", "coordinates", "route_number"}:
            raise ValueError("Command input must be none, coordinates or route_number")
        if spec.get("input") in {"coordinates", "route_number"} and any(c.isspace() for c in phrase):
            raise ValueError("Commands with arguments must be a single token")
        if spec.get("coordinate_style", "positional") not in {"positional", "options"}:
            raise ValueError("coordinate_style must be positional or options")
        if spec.get("coordinate_style") == "options" and spec.get("input") != "coordinates":
            raise ValueError("Named coordinate options require coordinates input")
        if "timeout" in spec and (type(spec["timeout"]) not in (int, float) or spec["timeout"] <= 0):
            raise ValueError("Command timeout must be positive")


def match_command(phrase, commands):
    key = phrase if phrase in commands else (phrase.split(maxsplit=1)[0] if phrase else "")
    spec = commands.get(key)
    if spec is None or (spec.get("input", "none") == "none" and phrase != key):
        return None
    if spec.get("input") == "route_number":
        route = phrase[len(key):].strip()
        if re.fullmatch(r"[0-9]{1,3}", route) and 1 <= int(route) <= 999:
            return key, [str(int(route))], None
        return key, [], f"Use {key} ROUTE_NUMBER (1-999), for example {key} 80."
    if spec.get("input") != "coordinates":
        return key, [], None
    coordinates = phrase[len(key):].strip()
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
    match = re.fullmatch(rf"({number})(?:\s*,\s*|\s+)({number})", coordinates)
    if match:
        latitude, longitude = map(float, match.groups())
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return key, [str(latitude), str(longitude)], None
    return key, [], f"Use {key} LATITUDE LONGITUDE (decimal degrees); latitude -90..90, longitude -180..180."


def script_path(root, relative):
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()) or path.suffix != ".py" or not path.is_file():
        raise ValueError("Scripts must be existing .py files within the service folder")
    return path


async def resolve_channel(mc, name):
    """Resolve by configured name; never silently fall back to public channel 0."""
    from meshcore import EventType
    matches = []
    for index in range(256):
        event = await asyncio.wait_for(mc.commands.get_channel(index), 10)
        if event.type == EventType.ERROR:
            break
        if event.type != EventType.CHANNEL_INFO:
            raise RuntimeError("Unexpected response while reading radio channels")
        if event.payload.get("channel_name") == name:
            matches.append(int(event.payload["channel_idx"]))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one configured channel named {name!r}, found {len(matches)}. Configure that channel on the node first.")
    return matches[0]


def parse_message(payload, channel, own_name, config, now):
    if payload.get("channel_idx") != channel or payload.get("txt_type", 0) != 0:
        return None
    text = payload.get("text")
    timestamp = payload.get("sender_timestamp")
    if not isinstance(text, str) or type(timestamp) is not int:
        return None
    # The companion API carries channel sender names in "Name: message" text.
    sender, separator, phrase = text.partition(": ")
    sender, phrase = sender.strip(), phrase.rstrip("\0").strip()
    if (not separator or not sender or not sender.isprintable() or
            len(sender.encode("utf-8")) > 80 or sender == own_name or
            phrase.startswith("@")):
        return None
    matched = match_command(phrase, config["commands"])
    if matched is None:
        return None
    command, arguments, input_error = matched
    if now - timestamp > config["max_message_age"] or timestamp - now > 60:
        return None
    fingerprint = hashlib.sha256(json.dumps([channel, timestamp, text], ensure_ascii=False).encode()).hexdigest()
    return {"id": fingerprint, "sender": sender, "phrase": phrase,
            "command": command, "arguments": arguments, "input_error": input_error,
            "channel_index": channel, "channel_name": config["channel_name"],
            "sender_timestamp": timestamp}


def reply_parts(sender, output, limit=150, max_parts=4):
    prefix = f"@{sender} "
    budget = limit - len(prefix.encode("utf-8"))
    if budget < 8:
        raise ValueError("Sender name leaves insufficient room for a reply")
    text = " ".join("".join(c for c in output if c.isprintable() or c.isspace()).split())
    text = text or "The script returned no text."
    parts = []
    while text and len(parts) < max_parts:
        piece = text.encode("utf-8")[:budget].decode("utf-8", "ignore")
        text = text[len(piece):]
        if text and len(parts) == max_parts - 1:
            piece = piece.encode("utf-8")[:budget - 3].decode("utf-8", "ignore") + "..."
        parts.append(prefix + piece)
    return parts


async def run_script(root, spec, request, config):
    path = script_path(root, spec["script"])
    arguments = request.get("arguments", [])
    if spec.get("coordinate_style") == "options":
        if len(arguments) != 2:
            raise ValueError("Two coordinates are required")
        arguments = ["--latitude", arguments[0], "--longitude", arguments[1]]
    env = os.environ.copy()
    env.update(MESHCORE_SENDER=request["sender"], MESHCORE_CHANNEL=request["channel_name"],
               MESHCORE_CHANNEL_INDEX=str(request["channel_index"]), MESHCORE_REQUEST_ID=request["id"],
               MESHCORE_PHRASE=request["phrase"], PYTHONIOENCODING="utf-8")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-u", str(path), *spec.get("args", []), *arguments, cwd=root, env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=(os.name == "posix"))

    async def read_bounded(stream):
        data = bytearray()
        while chunk := await stream.read(4096):
            data.extend(chunk)
            if len(data) > config["max_output_bytes"]:
                raise ValueError("Script output limit exceeded")
        return data.decode("utf-8", "replace")

    async def communicate():
        proc.stdin.write(json.dumps(request).encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        return await asyncio.gather(read_bounded(proc.stdout), read_bounded(proc.stderr), proc.wait())

    task = asyncio.create_task(communicate())
    try:
        stdout, stderr, code = await asyncio.wait_for(task, spec.get("timeout", config["script_timeout"]))
        if code:
            return spec.get("error_reply", "The requested script failed."), f"exit={code}; {stderr[:2000]}"
        return stdout, stderr[:2000]
    except (asyncio.TimeoutError, ValueError) as exc:
        return "The requested script timed out or exceeded its output limit.", str(exc)
    finally:
        if proc.returncode is None:
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class Responder:
    def __init__(self, root, db, config, channel, own_name, send):
        self.root, self.db, self.config = root, db, config
        self.channel, self.own_name, self.send = channel, own_name, send
        db.execute("""CREATE TABLE IF NOT EXISTS bot_requests (
            id TEXT PRIMARY KEY, sender TEXT, created REAL, context TEXT,
            state TEXT, response TEXT, detail TEXT)""")
        # Never blindly repeat a possibly completed execution or transmission.
        db.execute("UPDATE bot_requests SET state='interrupted' WHERE state IN ('running','sending')")
        db.commit()

    def accept(self, payload, now=None):
        now = time.time() if now is None else now
        request = parse_message(payload, self.channel, self.own_name, self.config, now)
        if request is None:
            return False
        if self.db.execute("SELECT 1 FROM bot_requests WHERE id=?", (request["id"],)).fetchone():
            return False
        last = self.db.execute("SELECT MAX(created) FROM bot_requests WHERE sender=?", (request["sender"],)).fetchone()[0]
        if last is not None and now - last < self.config["sender_cooldown"]:
            return False
        if self.db.execute("SELECT COUNT(*) FROM bot_requests WHERE state='queued'").fetchone()[0] >= self.config["max_pending"]:
            LOG.warning("Responder queue full; request ignored")
            return False
        request["script"] = self.config["commands"][request["command"]]
        self.db.execute("INSERT INTO bot_requests VALUES (?,?,?,?,?,?,?)",
                        (request["id"], request["sender"], now, json.dumps(request), "queued", None, None))
        self.db.commit()
        return True

    def update(self, request_id, state, response=None, detail=None):
        self.db.execute("UPDATE bot_requests SET state=?,response=COALESCE(?,response),detail=? WHERE id=?",
                        (state, response, detail, request_id))
        self.db.commit()

    async def process_one(self):
        row = self.db.execute("SELECT id,context FROM bot_requests WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
        if row is None:
            return False
        request_id, context = row
        request = json.loads(context)
        if (time.time() - request["sender_timestamp"] > self.config["max_message_age"] or
                request["channel_index"] != self.channel or request["channel_name"] != self.config["channel_name"]):
            self.update(request_id, "expired")
            return True
        self.update(request_id, "running")
        try:
            try:
                if request.get("input_error"):
                    output, detail = request["input_error"], "Invalid command arguments; script not executed"
                else:
                    output, detail = await run_script(self.root, request["script"], request, self.config)
            except Exception as exc:
                output, detail = "The requested script could not be run.", str(exc)
            parts = reply_parts(request["sender"], output, max_parts=self.config["max_reply_parts"])
            self.update(request_id, "sending", json.dumps(parts), detail)
            for part in parts:
                await self.send(request["channel_index"], part)
            self.update(request_id, "sent", detail=detail)
        except asyncio.CancelledError:
            self.update(request_id, "interrupted", detail="Stopped; execution or delivery may be incomplete")
            raise
        except Exception as exc:
            LOG.error("Reply failed for %s: %s", request_id, exc)
            self.update(request_id, "failed", detail=str(exc))
        return True

    async def run(self):
        while True:
            if not await self.process_one():
                await asyncio.sleep(0.1)
