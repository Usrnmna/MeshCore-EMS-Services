"""Configured channel phrase -> local Python script -> tagged channel response.

Read parse_message() for input handling, run_script() for child execution, and
Responder.process_one() for queue state and replies. Settings: config.json.
Functions that commit SQLite or launch a child process say so in their docstrings.
"""

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

from flood_alarm import ACKNOWLEDGMENT, FloodAlarms
from channels import validate_channels, channel_config, migrate_config

LOG = logging.getLogger("responder")


def validate_config(config, root):
    """Validate enabled responder settings and script paths; return None or raise before processing messages."""
    if not config.get("enabled", False):
        # Channel export policy still applies while automatic command replies are off.
        if config.get("channels") or config.get("channel_name"):
            validate_channels(config)
        return
    validate_channels(config)
    program_directory = config.get("program_directory")
    if program_directory is not None and (
        not isinstance(program_directory, str) or not Path(program_directory).is_absolute()
    ):
        raise ValueError("responder.program_directory must be an absolute directory path")
    for key in (
        "script_timeout",
        "max_output_bytes",
        "max_reply_parts",
        "max_message_age",
        "max_pending",
    ):
        if not isinstance(config.get(key), (int, float)) or config[key] <= 0:
            raise ValueError(f"responder.{key} must be positive")
    if config.get("sender_cooldown", -1) < 0:
        raise ValueError("responder.sender_cooldown must be nonnegative")
    commands = config.get("commands")
    if not isinstance(commands, dict) or not commands:
        raise ValueError("responder.commands must map phrases to scripts")
    for phrase, spec in commands.items():
        if (
            not phrase.strip()
            or phrase != phrase.strip()
            or phrase.startswith("@")
            or not phrase.isprintable()
        ):
            raise ValueError("Command phrases must be printable, trimmed and not start with @")
        script_path(root, spec["script"], program_directory)
        if not isinstance(spec.get("args", []), list) or not all(
            isinstance(x, str) for x in spec.get("args", [])
        ):
            raise ValueError("Script args must be a list of fixed strings")
        if spec.get("input", "none") not in {"none", "coordinates", "route_number", "location"}:
            raise ValueError("Command input must be none, coordinates, route_number or location")
        if spec.get("input") in {"coordinates", "route_number", "location"} and any(
            c.isspace() for c in phrase
        ):
            raise ValueError("Commands with arguments must be a single token")
        if spec.get("coordinate_style", "positional") not in {"positional", "options"}:
            raise ValueError("coordinate_style must be positional or options")
        if spec.get("coordinate_style") == "options" and spec.get("input") != "coordinates":
            raise ValueError("Named coordinate options require coordinates input")
        if "timeout" in spec and (
            type(spec["timeout"]) not in (int, float) or spec["timeout"] <= 0
        ):
            raise ValueError("Command timeout must be positive")
        if "max_reply_parts" in spec and (
            type(spec["max_reply_parts"]) is not int or spec["max_reply_parts"] <= 0
        ):
            raise ValueError("Command max_reply_parts must be a positive integer")


def match_command(phrase, commands):
    """Return (command, arguments, input_error), or None for unknown text; validate inputs without running scripts."""
    key = phrase if phrase in commands else (phrase.split(maxsplit=1)[0] if phrase else "")
    spec = commands.get(key)
    if spec is None or (spec.get("input", "none") == "none" and phrase != key):
        return None
    if spec.get("input") == "location":
        from scripts.uv_index import parse_location

        location = phrase[len(key) :].strip()
        try:
            parse_location(location)
        except ValueError as exc:
            return key, [], str(exc).replace("!uv", key)
        return key, [location], None
    if spec.get("input") == "route_number":
        route = phrase[len(key) :].strip()
        if re.fullmatch(r"[0-9]{1,3}", route) and 1 <= int(route) <= 999:
            return key, [str(int(route))], None
        return key, [], f"Use {key} ROUTE_NUMBER (1-999), for example {key} 80."
    if spec.get("input") != "coordinates":
        return key, [], None
    coordinates = phrase[len(key) :].strip()
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
    match = re.fullmatch(rf"({number})(?:\s*,\s*|\s+)({number})", coordinates)
    if match:
        latitude, longitude = map(float, match.groups())
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return key, [str(latitude), str(longitude)], None
    return (
        key,
        [],
        f"Use {key} LATITUDE LONGITUDE (decimal degrees); latitude -90..90, longitude -180..180.",
    )


def script_path(root, relative, program_directory=None):
    """Resolve a bundled script or an administrator-installed programs/*.py file.

    program_directory is a trusted absolute folder from local configuration.
    Radio messages cannot select file paths. Resolve symlinks before checking
    containment so neither ../ nor a symlink can escape the selected folder.
    """
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("Script paths must be relative .py files")
    parts = Path(relative.replace("\\", "/")).parts
    if not parts or ".." in parts:
        raise ValueError("Script paths cannot traverse parent directories")
    if parts[0] == "programs":
        if not program_directory or not Path(program_directory).is_absolute():
            raise ValueError("Set an absolute program_directory to use programs/*.py")
        base = Path(program_directory).resolve()
        path = base.joinpath(*parts[1:]).resolve()
    else:
        base = root.resolve()
        path = (base / relative).resolve()
    if not path.is_relative_to(base) or path.suffix != ".py" or not path.is_file():
        raise ValueError("Scripts must be existing .py files within their configured folder")
    # Compile without executing: catch a broken custom program during --check.
    if parts[0] == "programs":
        compile(path.read_bytes(), str(path), "exec")
    return path


def parse_message(payload, channel, own_name, config, now):
    """Return validated sender/channel/request context, or None for stale, self, reply, or unrelated messages."""
    if payload.get("channel_idx") != channel or payload.get("txt_type", 0) != 0:
        return None
    migrate_config(config)
    channel_id = config.get("channel_id", next(iter(config["channels"])))
    channel_name = config["channels"][channel_id]["name"]
    text = payload.get("text")
    timestamp = payload.get("sender_timestamp")
    if not isinstance(text, str) or type(timestamp) is not int:
        return None
    # The companion API carries channel sender names in "Name: message" text.
    sender, separator, phrase = text.partition(": ")
    sender, phrase = sender.strip(), phrase.rstrip("\0").strip()
    if (
        not separator
        or not sender
        or not sender.isprintable()
        or len(sender.encode("utf-8")) > 80
        or sender == own_name
        or phrase.startswith("@")
    ):
        return None
    matched = match_command(phrase, config["commands"])
    if matched is None:
        return None
    command, arguments, input_error = matched
    if channel_id not in config["commands"][command].get("channels", []):
        return None
    if now - timestamp > config["max_message_age"] or timestamp - now > 60:
        return None
    fingerprint = hashlib.sha256(
        json.dumps([channel_id, timestamp, text], ensure_ascii=False).encode()
    ).hexdigest()
    return {
        "id": fingerprint,
        "sender": sender,
        "phrase": phrase,
        "command": command,
        "arguments": arguments,
        "input_error": input_error,
        "channel_index": channel,
        "channel_name": channel_name,
        "channel_id": channel_id,
        "channel_identity": config.get("channel_identity"),
        "sender_timestamp": timestamp,
    }


def reply_parts(sender, output, limit=150, max_parts=4):
    """Return tagged UTF-8-safe pieces within the byte/part limits; collapse whitespace and mark truncation."""
    prefix = f"@{sender} "
    budget = limit - len(prefix.encode("utf-8"))
    if budget < 8:
        raise ValueError("Sender name leaves insufficient room for a reply")
    text = " ".join("".join(c for c in output if c.isprintable() or c.isspace()).split())
    text = text or "The script returned no text."
    parts = []
    while text and len(parts) < max_parts:
        piece = text.encode("utf-8")[:budget].decode("utf-8", "ignore")
        text = text[len(piece) :]
        if text and len(parts) == max_parts - 1:
            piece = piece.encode("utf-8")[: budget - 3].decode("utf-8", "ignore") + "..."
        parts.append(prefix + piece)
    return parts


async def run_script(root, spec, request, config):
    """Run the configured Python file with args/context, bounded stdout/stderr and timeout; return (reply, diagnostic)."""
    path = script_path(root, spec["script"], config.get("program_directory"))
    arguments = request.get("arguments", [])
    if spec.get("coordinate_style") == "options":
        if len(arguments) != 2:
            raise ValueError("Two coordinates are required")
        arguments = ["--latitude", arguments[0], "--longitude", arguments[1]]
    env = os.environ.copy()
    # A script needs message context, never channel encryption keys.
    for key in list(env):
        if key.startswith("MESHCORE_CHANNEL_KEY_"):
            env.pop(key)
    env.update(
        MESHCORE_SENDER=request["sender"],
        MESHCORE_CHANNEL=request["channel_name"],
        MESHCORE_CHANNEL_ID=request.get("channel_id", ""),
        MESHCORE_CHANNEL_INDEX=str(request["channel_index"]),
        MESHCORE_REQUEST_ID=request["id"],
        MESHCORE_PHRASE=request["phrase"],
        PYTHONIOENCODING="utf-8",
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        str(path),
        *spec.get("args", []),
        *arguments,
        cwd=root,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=(os.name == "posix"),
    )

    async def read_bounded(stream):
        """Read one child output stream as UTF-8 and raise if its independent byte limit is exceeded."""
        data = bytearray()
        while chunk := await stream.read(4096):
            data.extend(chunk)
            if len(data) > config["max_output_bytes"]:
                raise ValueError("Script output limit exceeded")
        return data.decode("utf-8", "replace")

    async def communicate():
        """Send request JSON on stdin and collect stdout, stderr, and child exit status concurrently."""
        proc.stdin.write(json.dumps(request).encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        return await asyncio.gather(
            read_bounded(proc.stdout), read_bounded(proc.stderr), proc.wait()
        )

    task = asyncio.create_task(communicate())
    try:
        stdout, stderr, code = await asyncio.wait_for(
            task, spec.get("timeout", config["script_timeout"])
        )
        if code:
            return (
                spec.get("error_reply", "The requested script failed."),
                f"exit={code}; {stderr[:2000]}",
            )
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
    """Persist accepted channel requests and process them one at a time through a supplied async send callback."""

    def __init__(self, root, db, config, channel, own_name, send, verify=None):
        """Create the request table and mark unfinished running/sending requests interrupted; commits to SQLite."""
        migrate_config(config)
        if "channel_id" not in config:
            config.update(channel_config(config, next(iter(config["channels"]))))
        self.root, self.db, self.config = root, db, config
        self.channel_id, self.verify = config["channel_id"], verify
        self.channel, self.own_name, self.send = channel, own_name, send
        db.execute(
            """CREATE TABLE IF NOT EXISTS bot_requests (
            id TEXT PRIMARY KEY, sender TEXT, created REAL, context TEXT,
            state TEXT, response TEXT, detail TEXT, channel_id TEXT)"""
        )
        if "channel_id" not in {r[1] for r in db.execute("PRAGMA table_info(bot_requests)")}:
            raise RuntimeError("Run channel state migration before starting workers")
        # Never blindly repeat a possibly completed execution or transmission.
        db.execute(
            "UPDATE bot_requests SET state='interrupted' WHERE channel_id=? AND state IN ('running','sending')",
            (self.channel_id,),
        )
        db.commit()
        self.alarms = FloodAlarms(
            db,
            self.channel_id,
            self.read_flood_status,
            self.send_flood_change,
            allowed=lambda: self.allowed("!floodalarm"),
        )
        if not self.allowed("!floodalarm"):
            db.execute(
                "UPDATE flood_subscriptions SET enabled=0 WHERE channel=?", (self.channel_id,)
            )
            db.commit()

    def allowed(self, command):
        """Check this worker's channel against the program's explicit assignment list."""
        return self.channel_id in self.config["channels"] and self.channel_id in self.config[
            "commands"
        ].get(command, {}).get("channels", [])

    def accept(self, payload, now=None):
        """Validate and queue one message unless duplicate, cooling down, or full; return whether it was accepted."""
        now = time.time() if now is None else now
        request = parse_message(payload, self.channel, self.own_name, self.config, now)
        if request is None:
            return False
        if self.db.execute("SELECT 1 FROM bot_requests WHERE id=?", (request["id"],)).fetchone():
            return False
        # Legacy request hashes used slot numbers. Context comparison preserves deduplication
        # after migration and slot moves without changing alarm revision references.
        if self.db.execute(
            """SELECT 1 FROM bot_requests WHERE channel_id=? AND sender=?
                AND json_extract(context,'$.sender_timestamp')=? AND json_extract(context,'$.phrase')=?""",
            (self.channel_id, request["sender"], request["sender_timestamp"], request["phrase"]),
        ).fetchone():
            return False
        last = self.db.execute(
            "SELECT MAX(created) FROM bot_requests WHERE sender=? AND channel_id=?",
            (request["sender"], self.channel_id),
        ).fetchone()[0]
        if last is not None and now - last < self.config["sender_cooldown"]:
            return False
        if (
            self.db.execute("SELECT COUNT(*) FROM bot_requests WHERE state='queued'").fetchone()[0]
            >= self.config["max_pending"]
        ):
            LOG.warning("Responder queue full; request ignored")
            return False
        channel_limit = self.config.get(
            "max_pending_per_channel", min(20, self.config["max_pending"])
        )
        if (
            self.db.execute(
                "SELECT COUNT(*) FROM bot_requests WHERE state='queued' AND channel_id=?",
                (self.channel_id,),
            ).fetchone()[0]
            >= channel_limit
        ):
            return False
        request["script"] = self.config["commands"][request["command"]]
        # ENROLLMENT/RENEWAL: only !floodalarm overwrites location and resets the four-hour timer.
        if request["command"] == "!floodalarm" and not request["input_error"]:
            if not self.alarms.remember(request, now):
                return False
        self.db.execute(
            "INSERT INTO bot_requests(id,sender,created,context,state,response,detail,channel_id) VALUES (?,?,?,?,?,?,?,?)",
            (
                request["id"],
                request["sender"],
                now,
                json.dumps(request),
                "queued",
                None,
                None,
                self.channel_id,
            ),
        )
        self.db.commit()
        return True

    def update(self, request_id, state, response=None, detail=None):
        """Commit request state and diagnostics, retaining the prior response when response is None."""
        self.db.execute(
            "UPDATE bot_requests SET state=?,response=COALESCE(?,response),detail=? WHERE id=?",
            (state, response, detail, request_id),
        )
        self.db.commit()

    async def process_one(self, alarm_only=None):
        """Process the oldest queued request, expire stale work, run its script and send replies; return False if empty."""
        # Separate acknowledgment worker bypasses slow weather lookups in the ordinary queue.
        rows = self.db.execute(
            "SELECT id,context FROM bot_requests WHERE state='queued' AND channel_id=? ORDER BY created",
            (self.channel_id,),
        ).fetchall()
        row = next(
            (
                row
                for row in rows
                if alarm_only is None
                or (json.loads(row[1])["command"] == "!floodalarm") == alarm_only
            ),
            None,
        )
        if row is None:
            return False
        request_id, context = row
        request = json.loads(context)
        if (
            time.time() - request["sender_timestamp"] > self.config["max_message_age"]
            or request.get("channel_id") != self.channel_id
            or request.get("channel_identity") != self.config.get("channel_identity")
            or request["channel_name"] != self.config["channel_name"]
            or not self.allowed(request["command"])
        ):
            self.update(request_id, "expired")
            return True
        # Slots can move across restarts; the stable ID and pinned key remain authoritative.
        request["channel_index"] = self.channel
        request["script"] = self.config["commands"][request["command"]]
        self.update(request_id, "running")
        try:
            if self.verify:
                await self.verify()
            try:
                if request.get("input_error"):
                    output, detail = (
                        request["input_error"],
                        "Invalid command arguments; script not executed",
                    )
                elif request["command"] == "!floodalarm":
                    output, detail = ACKNOWLEDGMENT, ""
                else:
                    output, detail = await run_script(
                        self.root, request["script"], request, self.config
                    )
            except Exception as exc:
                output, detail = "The requested script could not be run.", str(exc)
            parts = reply_parts(
                request["sender"],
                output,
                max_parts=request["script"].get("max_reply_parts", self.config["max_reply_parts"]),
            )
            self.update(request_id, "sending", json.dumps(parts), detail)
            for part in parts:
                if not self.allowed(request["command"]):
                    raise RuntimeError("Program channel assignment changed")
                await self.send(request["channel_index"], part)
            self.update(request_id, "sent", detail=detail)
            if request["command"] == "!floodalarm" and not request.get("input_error"):
                self.alarms.acknowledge(request)
        except asyncio.CancelledError:
            self.update(
                request_id, "interrupted", detail="Stopped; execution or delivery may be incomplete"
            )
            raise
        except Exception as exc:
            LOG.error("Reply failed for %s: %s", request_id, exc)
            self.update(request_id, "failed", detail=str(exc))
        return True

    async def read_flood_status(self, location):
        """Bounded JSON subprocess: API failures cannot be mistaken for a cleared flood status."""
        from scripts.flood_warn import ALERTS, format_status

        request = dict(
            arguments=[location],
            sender="Flood Alarm",
            channel_name=self.config["channel_name"],
            channel_index=self.channel,
            channel_id=self.channel_id,
            id="flood-alarm-check",
            phrase="!floodalarm " + location,
        )
        spec = dict(script="scripts/flood_warn.py", args=["--snapshot"], timeout=45)
        output, detail = await run_script(self.root, spec, request, self.config)
        try:
            data = json.loads(output)
        except ValueError as exc:
            raise RuntimeError(
                "Flood alert lookup unavailable. Will retry at the next check."
            ) from exc
        if not isinstance(data, dict) or data.get("error"):
            raise RuntimeError(
                data.get("error") if isinstance(data, dict) else "Invalid flood response."
            )
        events = data.get("events")
        if not isinstance(events, list) or any(
            not isinstance(event, str) or event not in ALERTS for event in events
        ):
            raise RuntimeError("Invalid flood status. Will retry at the next check.")
        events = [event for event in ALERTS if event in events]
        return {"events": events, "text": format_status(location, events)}

    async def send_flood_change(self, reading, output):
        """Tag changes just like !floodwarn; guard again after waiting for the radio's send slot."""
        guard = lambda: self.allowed("!floodalarm") and self.alarms.is_current(reading)
        for part in reply_parts(reading["sender"], output, max_parts=12):
            if not guard():
                break
            await self.send(self.channel, part, guard=guard)

    async def run_requests(self, alarm_only=False):
        """Drain this worker's queue without blocking the alarm scheduler or acknowledgment worker."""
        while True:
            if not await self.process_one(alarm_only=alarm_only):
                await asyncio.sleep(0.1)

    async def run(self):
        """All workers stop with the service; radio sends still use the existing shared rate limiter."""
        async with asyncio.TaskGroup() as workers:
            workers.create_task(self.run_requests())
            if self.allowed("!floodalarm"):
                workers.create_task(self.run_requests(alarm_only=True))
                workers.create_task(self.alarms.run())
