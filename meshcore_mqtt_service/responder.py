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

from flood_alarm import FloodAlarms
from scripts.water_settings import validate as validate_water
from wildfire_service import WildfireAlarms
from landslide_service import LandslideAlarms
from scripts.landslide_settings import validate as validate_landslide
from scripts.wildfire_settings import validate as validate_wildfire
from channels import validate_channels, channel_config, migrate_config
from scripts.time_settings import DEFAULT_TIMEZONE, display_timezone

LOG = logging.getLogger("responder")


def validate_config(config, root):
    """Validate enabled responder settings and script paths; return None or raise before processing messages."""
    if not config.get("enabled", False):
        # Channel export policy still applies while automatic command replies are off.
        if config.get("channels") or config.get("channel_name"):
            validate_channels(config)
        return
    if "timezone" in config and not isinstance(config["timezone"], str):
        raise ValueError("responder.timezone must be an IANA timezone name")
    display_timezone(config.get("timezone", DEFAULT_TIMEZONE))
    validate_channels(config)
    validate_wildfire(config.get("wildfire", {}))
    validate_landslide(config.get("landslide", {}))
    validate_water(config.get("water", {}))
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
        if spec.get("input", "none") not in {"none", "coordinates", "route_number", "location", "gis_query", "fire_query", "slide_query", "water_query"}:
            raise ValueError("Command input must be none, coordinates, route_number, location, gis_query, fire_query, slide_query or water_query")
        if spec.get("input") in {"coordinates", "route_number", "location", "gis_query", "fire_query", "slide_query", "water_query"} and any(
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
    if re.search(r"^\s*details(?:\s|$)|\s+page\s+\d+\s*$", phrase[len(key):], re.I):
        return key, [], f"Details and paging are not supported. Use {key} with its normal query."
    if spec.get("input") == "water_query":
        from scripts.water_lookup import parse_query
        query = phrase[len(key):].strip() or "help"
        try:
            parse_query(key, query)
        except ValueError as exc:
            return key, [], str(exc)
        return key, [query], None
    if spec.get("input") == "slide_query":
        from scripts.landslide_lookup import parse_query
        query = phrase[len(key):].strip() or "help"
        try:
            parse_query(key, query)
        except ValueError as exc:
            return key, [], str(exc)
        return key, [query], None
    if spec.get("input") == "fire_query":
        from scripts.wildfire_lookup import parse_query
        query = phrase[len(key):].strip() or "help"
        try:
            parse_query(key, query)
        except ValueError as exc:
            return key, [], str(exc)
        return key, [query], None
    if spec.get("input") == "gis_query":
        from scripts.gis_data import parse_query

        query = phrase[len(key):].strip() or "help"
        try:
            parse_query(query)
        except ValueError as exc:
            return key, [], str(exc)
        return key, [query], None
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
    """Return numbered, word-aware UTF-8 radio messages with explicit overflow."""
    from scripts.response_text import tagged_parts, compact_fields
    if max_parts == 1:
        output = compact_fields(output, sender=sender)
    return tagged_parts(sender, output, limit, max_parts)


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
        MESHCORE_REPLY_PARTS="1",
        MESHCORE_CHANNEL=request["channel_name"],
        MESHCORE_CHANNEL_ID=request.get("channel_id", ""),
        MESHCORE_CHANNEL_INDEX=str(request["channel_index"]),
        MESHCORE_REQUEST_ID=request["id"],
        MESHCORE_PHRASE=request["phrase"],
        MESHCORE_TIMEZONE=display_timezone(config.get("timezone", DEFAULT_TIMEZONE)).key,
        MESHCORE_RUNTIME_DIR=str(config.get("_runtime_directory", root / "runtime")),
        MESHCORE_WILDFIRE_SETTINGS=json.dumps(validate_wildfire(config.get("wildfire", {}))),
        MESHCORE_LANDSLIDE_SETTINGS=json.dumps(validate_landslide(config.get("landslide", {}))),
        MESHCORE_WATER_SETTINGS=json.dumps(validate_water(config.get("water", {}))),
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
        try:
            proc.stdin.write(json.dumps(request).encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            # Short programs may exit successfully without reading their optional context.
            # Their exit status and bounded stdout still determine the result.
            pass
        finally:
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
            db, self.channel_id, config.get("channel_identity"), config.get("water", {}),
            self.read_flood_status, self.send_flood_change, lambda: self.allowed("!floodalarm"))

        self.fire_alarms = WildfireAlarms(
            db, self.channel_id, config.get("channel_identity"), config.get("wildfire", {}),
            self.read_fire_status, self.send_fire_change, lambda: self.allowed("!firealarm"))

        self.slide_alarms = LandslideAlarms(
            db, self.channel_id, config.get("channel_identity"), config.get("landslide", {}),
            self.read_slide_status, self.send_slide_change, lambda: self.allowed("!slidealarm"))

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
        # Only explicit flood controls can reserve, cancel or renew a subscription.
        if request["command"] == "!floodalarm" and not request["input_error"]:
            if not self.alarms.remember(request, now):
                return False
        if request["command"] == "!firealarm" and not request["input_error"]:
            if not self.fire_alarms.remember(request, now):
                return False
        if request["command"] == "!slidealarm" and not request["input_error"]:
            if not self.slide_alarms.remember(request, now):
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
        context_row = self.db.execute("SELECT context FROM bot_requests WHERE id=?", (request_id,)).fetchone()
        if context_row and json.loads(context_row[0]).get("command") in {"!waterway", "!basin", "!floodstatus", "!floodalarm"}:
            response = "[]"  # Values are transmitted but are not retained in request history.
        self.db.execute(
            "UPDATE bot_requests SET state=?,response=COALESCE(?,response),detail=? WHERE id=?",
            (state, response, detail, request_id),
        )
        self.db.commit()

    async def process_one(self, alarm_only=None):
        """Process the oldest queued request, expire stale work, run its script and send replies; return False if empty."""
        # A separate flood-control worker bypasses lookups in the ordinary queue.
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
                elif request["command"] == "!slidealarm":
                    output, detail = await self.slide_alarms.control(request)
                elif request["command"] == "!firealarm":
                    output, detail = await self.fire_alarms.control(request)
                elif request["command"] == "!floodalarm":
                    output, detail = await self.alarms.control(request)
                else:
                    output, detail = await run_script(
                        self.root, request["script"], request, self.config
                    )
            except Exception as exc:
                output, detail = "The requested script could not be run.", str(exc)
            parts = reply_parts(
                request["sender"],
                output,
                max_parts=1,
            )
            self.update(request_id, "sending", json.dumps(parts), detail)
            for part in parts:
                if not self.allowed(request["command"]):
                    raise RuntimeError("Program channel assignment changed")
                if request["command"] == "!floodalarm" and not request.get("input_error"):
                    guard = lambda: self.alarms.control_current(request)
                    if not guard():
                        raise RuntimeError("Flood control request superseded or expired")
                    await self.send(request["channel_index"], part, guard=guard)
                elif request["command"] == "!slidealarm" and not request.get("input_error"):
                    guard = lambda: self.slide_alarms.control_current(request)
                    if not guard():
                        raise RuntimeError("Landslide control request superseded or expired")
                    await self.send(request["channel_index"], part, guard=guard)
                elif request["command"] == "!firealarm" and not request.get("input_error"):
                    guard = lambda: self.fire_alarms.control_current(request)
                    if not guard():
                        raise RuntimeError("Wildfire control request superseded or expired")
                    await self.send(request["channel_index"], part, guard=guard)
                else:
                    await self.send(request["channel_index"], part)
            self.update(request_id, "sent", detail=detail)
            if request["command"] == "!floodalarm" and not request.get("input_error"):
                self.alarms.acknowledge(request)
            if request["command"] == "!firealarm" and not request.get("input_error"):
                self.fire_alarms.acknowledge(request)
            if request["command"] == "!slidealarm" and not request.get("input_error"):
                self.slide_alarms.acknowledge(request)
        except asyncio.CancelledError:
            self.update(
                request_id, "interrupted", detail="Stopped; execution or delivery may be incomplete"
            )
            raise
        except Exception as exc:
            LOG.error("Reply failed for %s: %s", request_id, exc)
            self.update(request_id, "failed", detail=str(exc))
        return True

    async def read_slide_status(self, target):
        """Read a bounded structured point snapshot; subsequent checks reuse enrollment coordinates."""
        from scripts.landslide_lookup import checked_snapshot
        request = dict(arguments=["on " + target], sender="Landslide Alarm",
                       channel_name=self.config["channel_name"], channel_index=self.channel,
                       channel_id=self.channel_id, id="landslide-check", phrase="!slidealarm")
        output, detail = await run_script(
            self.root, dict(script="scripts/slidealarm.py", args=["--snapshot"], timeout=45),
            request, dict(self.config, max_output_bytes=12 * 1024 * 1024))
        try:
            return checked_snapshot(json.loads(output), validate_landslide(self.config.get("landslide", {})))
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Landslide alert data unavailable: " + str(exc)) from exc

    async def send_slide_change(self, reading, output):
        """Route tagged landslide updates through the shared radio queue with a revision guard."""
        guard = lambda: self.slide_alarms.current(reading)
        for part in reply_parts(reading["sender"], output, max_parts=1):
            if not guard():
                break
            await self.send(self.channel, part, guard=guard)

    async def read_fire_status(self, target):
        """Resolve enrollment through a bounded child; subsequent checks use fixed zone IDs."""
        targets = target if isinstance(target, list) else [target]
        merged = {"zones": [], "incidents": {}, "alerts": {}}
        for location in targets:
            request = dict(arguments=["on " + location], sender="Wildfire Alarm",
                           channel_name=self.config["channel_name"], channel_index=self.channel,
                           channel_id=self.channel_id, id="wildfire-check", phrase="!firealarm")
            output, detail = await run_script(
                self.root, dict(script="scripts/firealarm.py", args=["--monitor"], timeout=45),
                request, dict(self.config, max_output_bytes=8 * 1024 * 1024))
            try:
                data = json.loads(output)
            except ValueError as exc:
                raise ValueError("Wildfire cache unavailable; refresh and check source status.") from exc
            if data.get("error"):
                raise ValueError(data["error"])
            snapshot = data
            if not isinstance(snapshot.get("zones"), list) or not all(
                isinstance(snapshot.get(key), dict) for key in ("incidents", "alerts")
            ):
                raise ValueError("Invalid wildfire monitor response")
            merged["zones"] += snapshot["zones"]
            merged["incidents"].update(snapshot["incidents"])
            merged["alerts"].update(snapshot["alerts"])
        merged["zones"] = sorted(set(merged["zones"]))
        return merged

    async def send_fire_change(self, reading, output):
        """Recheck subscription validity inside the existing shared radio send queue."""
        guard = lambda: self.fire_alarms.current(reading)
        for part in reply_parts(reading["sender"], output, max_parts=1):
            if not guard():
                break
            await self.send(self.channel, part, guard=guard)

    async def read_flood_status(self, location, mode="alerts"):
        """Read a bounded structured location snapshot; scheduled checks use pinned coordinates."""
        from scripts.water_lookup import checked_snapshot
        query = ("conditions " if mode == "conditions" else "") + location
        request = dict(arguments=[query], sender="Flood Alarm", channel_name=self.config["channel_name"],
                       channel_index=self.channel, channel_id=self.channel_id,
                       id="flood-alarm-check", phrase="!floodalarm")
        output, detail = await run_script(
            self.root, dict(script="scripts/floodalarm.py", args=["--snapshot"], timeout=90),
            request, dict(self.config, max_output_bytes=2 * 1024 * 1024))
        try:
            return checked_snapshot(json.loads(output), validate_water(self.config.get("water", {})))
        except (ValueError, TypeError, KeyError) as exc:
            raise RuntimeError("Flood monitoring data unavailable: " + str(exc)) from exc

    async def send_flood_change(self, reading, output):
        """Send tagged flood-monitor changes on the subscribing channel.

        Recheck subscription, source freshness and queued alert version after the
        shared radio send-slot wait. FloodAlarms spaces completed responses.
        """
        guard = lambda: self.allowed("!floodalarm") and self.alarms.notification_current(reading)
        for part in reply_parts(reading["sender"], output, max_parts=1):
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
            if self.allowed("!floodalarm"):
                workers.create_task(self.alarms.run())
            if self.allowed("!firealarm"):
                workers.create_task(self.fire_alarms.run())
            if self.allowed("!slidealarm"):
                workers.create_task(self.slide_alarms.run())
