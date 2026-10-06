"""Channel registry, key validation, radio identity checks and state migration.

No radio writes occur here. Provisioning is an explicit channel_setup.py action.
Secrets stay in the radio/environment; only their SHA-256 identity is persisted.
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import closing
import hashlib
import hmac
import json
import os
import re
import sqlite3
from pathlib import Path

PUBLIC_KEY = bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72")
SECRET_ENV = re.compile(r"MESHCORE_CHANNEL_KEY_[A-Z0-9_]+")


def migrate_config(config):
    """Convert a legacy responder in place; never expand an existing registry."""
    if "channels" in config:
        return False
    name = config.get("channel_name")
    if not isinstance(name, str) or not name:
        return False
    config["channels"] = {"default": {"name": name, "type": "existing", "mqtt_export": True}}
    for spec in config.get("commands", {}).values():
        spec["channels"] = ["default"]
    config.pop("channel_name", None)
    return True


def validate_channels(config):
    """Validate structure offline; secret presence is checked before radio use."""
    migrate_config(config)
    registry = config.get("channels")
    if not isinstance(registry, dict) or not registry:
        raise ValueError("responder.channels must be a nonempty channel registry")
    slots = set()
    for channel_id, spec in registry.items():
        if not isinstance(channel_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", channel_id):
            raise ValueError("Channel IDs must be 1-64 letters, digits, underscores or hyphens")
        if not isinstance(spec, dict):
            raise ValueError(f"Invalid channel {channel_id}")
        if set(spec) - {"name", "type", "slot", "secret_env", "mqtt_export"}:
            raise ValueError(
                f"Unknown setting in channel {channel_id}; keys belong in environment.json"
            )
        name = spec.get("name")
        if (
            not isinstance(name, str)
            or not name
            or name != name.strip()
            or not name.isprintable()
            or len(name.encode("utf-8")) > 32
        ):
            raise ValueError(
                f"Channel {channel_id} needs a printable name of at most 32 UTF-8 bytes"
            )
        kind = spec.get("type")
        if kind not in {"public", "hashtag", "private", "existing"}:
            raise ValueError(f"Invalid type for channel {channel_id}")
        if kind == "hashtag" and not name.startswith("#"):
            raise ValueError(f"Hashtag channel {channel_id} must start with #")
        if kind == "private":
            if not isinstance(spec.get("secret_env"), str) or not SECRET_ENV.fullmatch(
                spec["secret_env"]
            ):
                raise ValueError(
                    f"Private channel {channel_id} needs a MESHCORE_CHANNEL_KEY_... secret_env"
                )
        elif "secret_env" in spec:
            raise ValueError(f"secret_env is only valid for private channel {channel_id}")
        if type(spec.get("mqtt_export")) is not bool:
            raise ValueError(f"Channel {channel_id} needs an explicit mqtt_export boolean")
        if "slot" in spec:
            slot = spec["slot"]
            if type(slot) is not int or not 0 <= slot <= 255 or slot in slots:
                raise ValueError("Channel slots must be unique integers between 0 and 255")
            slots.add(slot)
    commands = config.get("commands", {})
    if not isinstance(commands, dict):
        raise ValueError("responder.commands must map phrases to program settings")
    for phrase, spec in commands.items():
        if not isinstance(spec, dict):
            raise ValueError(f"Invalid program settings for {phrase}")
        assigned = spec.get("channels")
        if (
            not isinstance(assigned, list)
            or any(not isinstance(x, str) or x not in registry for x in assigned)
            or len(assigned) != len(set(assigned))
        ):
            raise ValueError(
                f"{phrase}.channels must list unique registered channel IDs (or [] to disable)"
            )
    max_pending = config.get("max_pending", 50)
    if type(max_pending) is not int or max_pending <= 0:
        raise ValueError("max_pending must be a positive integer")
    limit = config.get("max_pending_per_channel", min(20, max_pending))
    if type(limit) is not int or limit <= 0:
        raise ValueError("max_pending_per_channel must be a positive integer")


def decode_key(value):
    """Accept a 16-byte key in hex or standard base64 without echoing bad input."""
    try:
        if not isinstance(value, str):
            raise ValueError()
        key = (
            bytes.fromhex(value)
            if re.fullmatch(r"[0-9a-fA-F]{32}", value)
            else base64.b64decode(value, validate=True)
        )
        if len(key) != 16:
            raise ValueError()
        return key
    except (ValueError, TypeError):
        raise ValueError(
            "Channel key must be 32 hex digits or base64 encoding exactly 16 bytes"
        ) from None


def expected_key(spec):
    """Return the required wire key, or None to pin an existing radio channel."""
    kind = spec["type"]
    if kind == "public":
        return PUBLIC_KEY
    if kind == "hashtag":
        return hashlib.sha256(spec["name"].encode("utf-8")).digest()[:16]
    if kind == "private":
        value = os.environ.get(spec["secret_env"])
        if value is None:
            raise ValueError(f"Missing channel secret environment variable {spec['secret_env']}")
        return decode_key(value)
    return None


def radio_key(payload):
    """Read the SDK's binary (or hex) key field; reject incomplete radio replies."""
    key = payload.get("channel_secret")
    if isinstance(key, bytes) and len(key) == 16:
        return key
    if isinstance(key, str):
        return decode_key(key)
    raise RuntimeError("Radio returned missing or invalid channel key information")


def identity(payload):
    """Return a one-way key fingerprint used internally for identity comparisons."""
    return hashlib.sha256(radio_key(payload)).hexdigest()


async def discover(mc):
    """Read slots until the companion reports its first unsupported index."""
    from meshcore import EventType

    result = []
    for index in range(256):
        event = await asyncio.wait_for(mc.commands.get_channel(index), 10)
        if event.type == EventType.ERROR:
            if index == 0:
                raise RuntimeError("Radio channel discovery failed at slot 0")
            break
        if event.type != EventType.CHANNEL_INFO or event.payload.get("channel_idx") != index:
            raise RuntimeError("Unexpected response while reading radio channels")
        radio_key(event.payload)
        result.append(event.payload)
    return result


async def resolve_channels(mc, config):
    """Bind every configured ID to one verified radio slot. Never write/fallback."""
    validate_channels(config)
    slots = await discover(mc)
    result = {}
    used = set()
    for channel_id, spec in config["channels"].items():
        matches = [
            p
            for p in slots
            if p["channel_name"] == spec["name"]
            and ("slot" not in spec or p["channel_idx"] == spec["slot"])
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one radio channel for {channel_id}; found {len(matches)}. Configure that channel first."
            )
        payload = matches[0]
        index = payload["channel_idx"]
        if index in used:
            raise RuntimeError("Multiple channel IDs resolve to the same radio slot")
        key = expected_key(spec)
        if key is not None and not hmac.compare_digest(key, radio_key(payload)):
            raise RuntimeError(f"Radio key does not match channel {channel_id}")
        used.add(index)
        result[channel_id] = dict(spec, id=channel_id, index=index, identity=identity(payload))
    return result


async def verify_binding(mc, binding):
    """Recheck name AND key immediately before accepting/sending channel work."""
    from meshcore import EventType

    event = await mc.commands.get_channel(binding["index"])
    if (
        event.type != EventType.CHANNEL_INFO
        or event.payload.get("channel_idx") != binding["index"]
        or event.payload.get("channel_name") != binding["name"]
        or identity(event.payload) != binding["identity"]
    ):
        raise RuntimeError(
            f"Radio configuration changed for channel {binding['id']}; restart after correcting it"
        )


def bind_state(db, bindings):
    """Pin identity across restarts and back up SQLite before first schema migration."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "channel_bindings" not in tables:
        filename = db.execute("PRAGMA database_list").fetchone()[2]
        if filename and tables:
            backup = Path(filename).with_name("bridge.before-channels.sqlite3")
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as target:
                    db.backup(target)
                if os.name == "posix":
                    backup.chmod(0o600)
    # DDL and data updates must commit together. A crash cannot leave a schema
    # marker that makes the next startup skip unfinished legacy migration.
    db.execute("SAVEPOINT channel_migration")
    try:
        _migrate_state(db, bindings, tables)
    except BaseException:
        db.execute("ROLLBACK TO channel_migration")
        db.execute("RELEASE channel_migration")
        raise
    db.execute("RELEASE channel_migration")
    db.commit()


def _migrate_state(db, bindings, tables):
    """Update schema, legacy context and identity pins inside bind_state's transaction.

    Legacy rows match by unambiguous display name once. Later starts use the
    stable ID and reject name/key changes. Removed channels retain history but
    lose queued work and active alarms. This helper never commits independently.
    """
    db.execute(
        "CREATE TABLE IF NOT EXISTS channel_bindings (id TEXT PRIMARY KEY, name TEXT, identity TEXT)"
    )
    for channel_id, binding in bindings.items():
        old = db.execute(
            "SELECT name,identity FROM channel_bindings WHERE id=?", (channel_id,)
        ).fetchone()
        if old and old != (binding["name"], binding["identity"]):
            raise RuntimeError(
                f"Identity changed for {channel_id}. Restore its name/key or use a new channel ID and renew alarms."
            )
    if "bot_requests" in tables:
        columns = {r[1] for r in db.execute("PRAGMA table_info(bot_requests)")}
        if "channel_id" not in columns:
            db.execute("ALTER TABLE bot_requests ADD COLUMN channel_id TEXT")
            for request_id, context in db.execute("SELECT id,context FROM bot_requests").fetchall():
                request = json.loads(context)
                matches = [b for b in bindings.values() if b["name"] == request.get("channel_name")]
                if len(matches) == 1:
                    b = matches[0]
                    request.update(channel_id=b["id"], channel_identity=b["identity"])
                    db.execute(
                        "UPDATE bot_requests SET channel_id=?,context=? WHERE id=?",
                        (b["id"], json.dumps(request), request_id),
                    )
                else:
                    db.execute(
                        "UPDATE bot_requests SET state='expired' WHERE id=? AND state='queued'",
                        (request_id,),
                    )
        db.execute(
            "CREATE INDEX IF NOT EXISTS bot_channel_queue ON bot_requests(channel_id,state,created)"
        )
    if "flood_subscriptions" in tables and "channel_bindings" not in tables:
        # Legacy subscriptions use display names. Only an unambiguous name can migrate.
        for (name,) in db.execute("SELECT DISTINCT channel FROM flood_subscriptions").fetchall():
            matches = [b for b in bindings.values() if b["name"] == name]
            if len(matches) == 1:
                db.execute(
                    "UPDATE flood_subscriptions SET channel=? WHERE channel=?",
                    (matches[0]["id"], name),
                )
            else:
                db.execute("UPDATE flood_subscriptions SET enabled=0 WHERE channel=?", (name,))
    for channel_id, b in bindings.items():
        db.execute(
            "INSERT OR IGNORE INTO channel_bindings VALUES (?,?,?)",
            (channel_id, b["name"], b["identity"]),
        )
    if "bot_requests" in tables:
        for request_id, channel_id in db.execute(
            "SELECT id,channel_id FROM bot_requests WHERE state='queued'"
        ).fetchall():
            if channel_id not in bindings:
                db.execute("UPDATE bot_requests SET state='expired' WHERE id=?", (request_id,))
    if "flood_subscriptions" in tables:
        for (channel_id,) in db.execute(
            "SELECT DISTINCT channel FROM flood_subscriptions"
        ).fetchall():
            if channel_id not in bindings:
                db.execute(
                    "UPDATE flood_subscriptions SET enabled=0 WHERE channel=?", (channel_id,)
                )


def channel_config(config, channel_id, binding=None):
    """Give each worker a view of its channel, sharing current command assignments."""
    spec = config["channels"][channel_id]
    return dict(
        config,
        channel_id=channel_id,
        channel_name=spec["name"],
        channel_identity=(binding or {}).get("identity"),
    )


def export_allowed(kind, payload, bindings):
    """Unknown channels and unclassified packet logs never bypass export controls."""
    by_index = {b["index"]: b for b in bindings.values()}
    channel_id = payload.get("channel_id") if isinstance(payload, dict) else None
    index = payload.get("channel_idx") if isinstance(payload, dict) else None
    if channel_id is not None:
        b = bindings.get(channel_id)
        return bool(b and b["mqtt_export"])
    if index is not None:
        b = by_index.get(index)
        return bool(b and b["mqtt_export"])
    # Radio logs can contain decoded/unclassified traffic; never export those in registry mode.
    return kind in {
        "NODE",
        "BATTERY",
        "CURRENT_TIME",
        "DEVICE_INFO",
        "SELF_INFO",
        "STATS_CORE",
        "STATS_RADIO",
        "STATS_PACKETS",
        "COMMAND_REJECTED",
    }
