"""Offline channel isolation, identity, migration and privacy regression tests."""

import base64
import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from meshcore import EventType
import channels
import channel_setup
from flood_alarm import FloodAlarms
import responder

ROOT = Path(__file__).resolve().parents[1]
KEY = bytes(range(16))


def config():
    """Return independent public/private configuration without real deployment data."""
    return {
        "enabled": True,
        "script_timeout": 5,
        "max_output_bytes": 4096,
        "max_reply_parts": 4,
        "max_message_age": 300,
        "sender_cooldown": 30,
        "max_pending": 10,
        "max_pending_per_channel": 2,
        "channels": {
            "community": {"name": "Public", "type": "public", "mqtt_export": True},
            "ops": {
                "name": "#Operations",
                "type": "private",
                "mqtt_export": False,
                "secret_env": "MESHCORE_CHANNEL_KEY_OPS",
            },
        },
        "commands": {
            "!status": {"script": "scripts/status.py", "channels": ["community", "ops"]},
            "!time": {"script": "scripts/time_now.py", "channels": ["ops"]},
            "!floodalarm": {
                "script": "scripts/flood_warn.py",
                "input": "location",
                "channels": ["community", "ops"],
            },
        },
    }


def radio_slot(index, name, key=KEY):
    """Build the companion's documented channel response shape."""
    return {"channel_idx": index, "channel_name": name, "channel_secret": key}


def radio(slots):
    """Simulate bounded read-only channel discovery with no serial connection."""

    async def get_channel(index):
        """Return each simulated slot or the companion's unsupported-index error."""
        if index >= len(slots):
            return SimpleNamespace(type=EventType.ERROR, payload={})
        return SimpleNamespace(type=EventType.CHANNEL_INFO, payload=slots[index])

    return SimpleNamespace(commands=SimpleNamespace(get_channel=AsyncMock(side_effect=get_channel)))


def bindings():
    """Create stable test identities independently of the resolver under test."""
    return {
        channel_id: dict(
            spec,
            id=channel_id,
            index=index,
            identity=channels.identity(
                radio_slot(index, spec["name"], channels.PUBLIC_KEY if index == 0 else KEY)
            ),
        )
        for index, (channel_id, spec) in enumerate(config()["channels"].items())
    }


def packet(index, phrase="!status", sender="Alice", timestamp=None):
    """Create a received channel message with a current or explicit sender timestamp."""
    return {
        "channel_idx": index,
        "txt_type": 0,
        "text": f"{sender}: {phrase}",
        "sender_timestamp": int(time.time()) if timestamp is None else timestamp,
    }


class ConfigurationTests(unittest.TestCase):
    def test_legacy_migration_preserves_all_command_assignments(self):
        cfg = {"channel_name": "#old", "commands": {"!one": {}, "!two": {}}}
        self.assertTrue(channels.migrate_config(cfg))
        self.assertNotIn("channel_name", cfg)
        self.assertEqual(cfg["channels"]["default"]["name"], "#old")
        self.assertTrue(cfg["channels"]["default"]["mqtt_export"])
        self.assertTrue(all(s["channels"] == ["default"] for s in cfg["commands"].values()))
        snapshot = copy.deepcopy(cfg)
        self.assertFalse(channels.migrate_config(cfg))
        self.assertEqual(snapshot, cfg)

    def test_added_channel_does_not_inherit_programs(self):
        cfg = config()
        cfg["channels"]["new"] = {"name": "#new", "type": "hashtag", "mqtt_export": False}
        channels.validate_channels(cfg)
        self.assertTrue(all("new" not in s["channels"] for s in cfg["commands"].values()))

    def test_invalid_registry_and_assignments_are_rejected(self):
        changes = [
            lambda c: c.update(channels={}),
            lambda c: c["channels"]["ops"].update(secret_env="SECRET"),
            lambda c: c["channels"]["ops"].update(key=KEY.hex()),
            lambda c: c["channels"]["ops"].update(mqtt_export="false"),
            lambda c: c["channels"]["community"].update(slot=True),
            lambda c: c["channels"]["community"].update(type="hashtag"),
            lambda c: c["channels"]["ops"].update(name="x" * 33),
            lambda c: c["commands"]["!status"].update(channels=["unknown"]),
            lambda c: c["commands"]["!status"].update(channels=["ops", "ops"]),
            lambda c: c["commands"]["!status"].pop("channels"),
            lambda c: c.update(max_pending_per_channel=0),
        ]
        for change in changes:
            with self.subTest(change=change):
                cfg = config()
                change(cfg)
                with self.assertRaises(ValueError):
                    channels.validate_channels(cfg)

    def test_empty_assignment_disables_program_and_duplicate_slots_fail(self):
        cfg = config()
        cfg["commands"]["!status"]["channels"] = []
        channels.validate_channels(cfg)
        for spec in cfg["channels"].values():
            spec["slot"] = 1
        with self.assertRaises(ValueError):
            channels.validate_channels(cfg)

    def test_public_hashtag_and_private_key_semantics(self):
        self.assertEqual(channels.expected_key({"type": "public"}), channels.PUBLIC_KEY)
        self.assertEqual(
            channels.expected_key({"type": "hashtag", "name": "#community"}),
            hashlib.sha256(b"#community").digest()[:16],
        )
        for value in [KEY.hex(), base64.b64encode(KEY).decode()]:
            with patch.dict(os.environ, {"MESHCORE_CHANNEL_KEY_OPS": value}):
                # A private name beginning with # must still use the explicitly supplied key.
                self.assertEqual(channels.expected_key(config()["channels"]["ops"]), KEY)
        self.assertIsNone(channels.expected_key({"type": "existing"}))

    def test_invalid_secret_values_are_not_echoed(self):
        for secret in ["sensitive-invalid-secret", "00", "", base64.b64encode(b"short").decode()]:
            with self.subTest(secret=secret), self.assertRaises(ValueError) as caught:
                channels.decode_key(secret)
            if secret:
                self.assertNotIn(secret, str(caught.exception))
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            channels.expected_key(config()["channels"]["ops"])

    def test_export_policy_does_not_leak_private_or_unclassified_traffic(self):
        bound = bindings()
        self.assertTrue(channels.export_allowed("CHANNEL_MSG_RECV", {"channel_idx": 0}, bound))
        for payload in [{"channel_idx": 1}, {"channel_idx": 99}, {}, {"channel_id": "ops"}]:
            self.assertFalse(channels.export_allowed("CHANNEL_MSG_RECV", payload, bound))
        self.assertFalse(channels.export_allowed("RX_LOG_DATA", {}, bound))
        self.assertTrue(channels.export_allowed("BATTERY", {}, bound))


class RadioIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = config()
        self.slots = [radio_slot(0, "Public", channels.PUBLIC_KEY), radio_slot(1, "#Operations")]
        self.secret = patch.dict(os.environ, {"MESHCORE_CHANNEL_KEY_OPS": KEY.hex()})
        self.secret.start()
        self.addCleanup(self.secret.stop)

    async def test_binds_mixed_channels_without_radio_writes(self):
        mc = radio(self.slots)
        result = await channels.resolve_channels(mc, self.cfg)
        self.assertEqual({key: b["index"] for key, b in result.items()}, {"community": 0, "ops": 1})
        self.assertFalse(
            any("secret" in field for b in result.values() for field in b if field != "secret_env")
        )

    async def test_missing_ambiguous_wrong_key_and_wrong_slot_fail_closed(self):
        cases = [
            [self.slots[0]],
            self.slots + [radio_slot(2, "#Operations")],
            [self.slots[0], radio_slot(1, "#Operations", b"x" * 16)],
        ]
        for slots in cases:
            with self.subTest(slots=slots), self.assertRaises(RuntimeError):
                await channels.resolve_channels(radio(slots), self.cfg)
        self.cfg["channels"]["ops"]["slot"] = 0
        with self.assertRaises(RuntimeError):
            await channels.resolve_channels(radio(self.slots), self.cfg)

    async def test_explicit_slot_disambiguates_duplicate_names(self):
        self.cfg["channels"]["ops"]["slot"] = 1
        result = await channels.resolve_channels(
            radio(self.slots + [radio_slot(2, "#Operations")]), self.cfg
        )
        self.assertEqual(result["ops"]["index"], 1)

    async def test_verification_detects_changed_name_key_and_slot(self):
        bound = (await channels.resolve_channels(radio(self.slots), self.cfg))["ops"]
        await channels.verify_binding(radio(self.slots), bound)
        for changed in [
            radio_slot(1, "Other"),
            radio_slot(1, "#Operations", b"x" * 16),
            radio_slot(0, "#Operations"),
        ]:
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                await channels.verify_binding(radio([self.slots[0], changed]), bound)


class StateMigrationTests(unittest.TestCase):
    def test_failed_migration_rolls_back_schema_and_rows_then_can_retry(self):
        """A bad legacy row must not leave markers that bypass migration on retry."""
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute(
                """CREATE TABLE bot_requests (id TEXT PRIMARY KEY, sender TEXT, created REAL,
                        context TEXT, state TEXT, response TEXT, detail TEXT)"""
            )
            valid = json.dumps({"channel_name": "#Operations"})
            rows = [
                ("first", "Alice", 100, valid, "queued", None, None),
                ("broken", "Bob", 101, "{invalid-json", "queued", None, None),
            ]
            db.executemany("INSERT INTO bot_requests VALUES (?,?,?,?,?,?,?)", rows)
            db.commit()
            before_schema = db.execute(
                "SELECT name,sql FROM sqlite_master ORDER BY name"
            ).fetchall()
            with self.assertRaises(ValueError):
                channels.bind_state(db, bindings())
            self.assertEqual(
                db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall(),
                before_schema,
            )
            self.assertEqual(
                db.execute("SELECT * FROM bot_requests ORDER BY created").fetchall(), rows
            )
            db.execute("UPDATE bot_requests SET context=? WHERE id='broken'", (valid,))
            db.commit()
            channels.bind_state(db, bindings())
            self.assertEqual(
                db.execute("SELECT channel_id,state FROM bot_requests ORDER BY created").fetchall(),
                [("ops", "queued"), ("ops", "queued")],
            )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM channel_bindings").fetchone()[0], 2)

    def test_pin_survives_slot_move_but_rejects_new_name_or_key(self):
        with closing(sqlite3.connect(":memory:")) as db:
            bound = bindings()
            channels.bind_state(db, bound)
            bound["ops"]["index"] = 7
            channels.bind_state(db, bound)
            for field, value in [("name", "Other"), ("identity", "different")]:
                changed = copy.deepcopy(bound)
                changed["ops"][field] = value
                with self.subTest(field=field), self.assertRaises(RuntimeError):
                    channels.bind_state(db, changed)

    def test_legacy_requests_and_alarms_migrate_with_database_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bridge.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "CREATE TABLE bot_requests (id TEXT PRIMARY KEY, context TEXT, state TEXT, created REAL)"
                )
                for key, name in [("valid", "#Operations"), ("unknown", "Removed")]:
                    db.execute(
                        "INSERT INTO bot_requests VALUES (?,?,?,?)",
                        (key, json.dumps({"channel_name": name}), "queued", 100),
                    )
                alarms = FloodAlarms(db, "#Operations", AsyncMock(), AsyncMock())
                alarms.remember(
                    {
                        "command": "!floodalarm",
                        "sender": "Alice",
                        "sender_timestamp": 100,
                        "arguments": ["94501"],
                        "id": "legacy-alarm",
                    },
                    100,
                )
                channels.bind_state(db, bindings())
                row = db.execute(
                    "SELECT channel_id,context FROM bot_requests WHERE id='valid'"
                ).fetchone()
                self.assertEqual(row[0], "ops")
                self.assertEqual(
                    json.loads(row[1])["channel_identity"], bindings()["ops"]["identity"]
                )
                self.assertEqual(
                    db.execute("SELECT state FROM bot_requests WHERE id='unknown'").fetchone()[0],
                    "expired",
                )
                self.assertEqual(
                    db.execute("SELECT channel FROM flood_subscriptions").fetchone()[0], "ops"
                )
                channels.bind_state(db, bindings())
                self.assertEqual(
                    db.execute("SELECT channel FROM flood_subscriptions").fetchone()[0], "ops"
                )
            with closing(
                sqlite3.connect(Path(folder) / "bridge.before-channels.sqlite3")
            ) as backup:
                self.assertNotIn(
                    "channel_id",
                    [row[1] for row in backup.execute("PRAGMA table_info(bot_requests)")],
                )
                self.assertEqual(
                    backup.execute("SELECT channel FROM flood_subscriptions").fetchone()[0],
                    "#Operations",
                )

    def test_legacy_replay_is_rejected_after_migration_and_slot_move(self):
        with closing(sqlite3.connect(":memory:")) as db:
            cfg, bound = config(), bindings()
            now = int(time.time())
            old_slot = 7
            message = packet(old_slot, timestamp=now)
            legacy_id = hashlib.sha256(
                json.dumps([old_slot, now, message["text"]]).encode()
            ).hexdigest()
            request = {
                "id": legacy_id,
                "sender": "Alice",
                "phrase": "!status",
                "command": "!status",
                "arguments": [],
                "input_error": None,
                "channel_name": "#Operations",
                "channel_index": old_slot,
                "sender_timestamp": now,
            }
            db.execute(
                """CREATE TABLE bot_requests (id TEXT PRIMARY KEY, sender TEXT, created REAL,
                        context TEXT, state TEXT, response TEXT, detail TEXT)"""
            )
            db.execute(
                "INSERT INTO bot_requests VALUES (?,?,?,?,?,?,?)",
                (legacy_id, "Alice", now - 100, json.dumps(request), "sent", None, None),
            )
            db.commit()
            channels.bind_state(db, bound)
            bot = responder.Responder(
                ROOT, db, channels.channel_config(cfg, "ops", bound["ops"]), 1, "Bot", AsyncMock()
            )
            self.assertFalse(bot.accept(packet(1, timestamp=now), now=now))

    def test_removing_channel_expires_queued_requests_and_disables_alarms(self):
        with closing(sqlite3.connect(":memory:")) as db:
            cfg, bound = config(), bindings()
            channels.bind_state(db, bound)
            bot = responder.Responder(
                ROOT, db, channels.channel_config(cfg, "ops", bound["ops"]), 1, "Bot", AsyncMock()
            )
            self.assertTrue(bot.accept(packet(1, "!floodalarm 94501")))
            channels.bind_state(db, {"community": bound["community"]})
            self.assertEqual(db.execute("SELECT state FROM bot_requests").fetchone()[0], "expired")
            self.assertFalse(bot.alarms.row("Alice")["enabled"])


class ProvisionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = config()
        self.secret = patch.dict(os.environ, {"MESHCORE_CHANNEL_KEY_OPS": KEY.hex()})
        self.secret.start()
        self.addCleanup(self.secret.stop)
        self.slots = [radio_slot(0, "Public", channels.PUBLIC_KEY), radio_slot(1, "", bytes(16))]
        self.mc = radio(self.slots)

        async def write_frame(frame, events):
            """Apply a set-channel protocol frame to the simulated radio's state."""
            index = frame[1]
            self.slots[index] = radio_slot(index, frame[2:34].rstrip(b"\0").decode(), frame[34:])
            return SimpleNamespace(type=EventType.OK, payload={})

        self.mc.commands.send = AsyncMock(side_effect=write_frame)

    async def test_private_hashtag_name_keeps_secret_and_creation_is_idempotent(self):
        self.assertEqual(await channel_setup.provision(self.mc, "ops", self.cfg), 1)
        self.assertEqual(self.slots[1]["channel_name"], "#Operations")
        self.assertEqual(self.slots[1]["channel_secret"], KEY)
        # Verify the documented set-channel wire layout, including exactly 32 name bytes.
        frame = self.mc.commands.send.await_args.args[0]
        self.assertEqual(frame, b"\x20\x01" + b"#Operations".ljust(32, b"\0") + KEY)
        self.assertEqual(await channel_setup.provision(self.mc, "ops", self.cfg), 1)
        self.mc.commands.send.assert_awaited_once()

    async def test_occupied_target_and_read_only_existing_channel_cannot_be_written(self):
        self.cfg["channels"]["ops"]["slot"] = 0
        with self.assertRaises(RuntimeError):
            await channel_setup.provision(self.mc, "ops", self.cfg)
        self.cfg["channels"]["ops"]["type"] = "existing"
        with self.assertRaises(ValueError):
            await channel_setup.provision(self.mc, "ops", self.cfg)
        self.mc.commands.send.assert_not_awaited()

    async def test_radio_rejection_and_failed_readback_are_reported(self):
        self.mc.commands.send = AsyncMock(
            return_value=SimpleNamespace(type=EventType.ERROR, payload={})
        )
        with self.assertRaises(RuntimeError):
            await channel_setup.provision(self.mc, "ops", self.cfg)
        # An OK response without the expected persisted name/key is still a failure.
        self.mc.commands.send.return_value = SimpleNamespace(type=EventType.OK, payload={})
        with self.assertRaises(RuntimeError):
            await channel_setup.provision(self.mc, "ops", self.cfg)

    async def test_wrong_slot_reread_prevents_a_write(self):
        self.mc.commands.get_channel = AsyncMock(
            return_value=SimpleNamespace(
                type=EventType.CHANNEL_INFO, payload=radio_slot(0, "", bytes(16))
            )
        )
        with patch.object(channel_setup, "discover", AsyncMock(return_value=self.slots)):
            with self.assertRaises(RuntimeError):
                await channel_setup.provision(self.mc, "ops", self.cfg)
        self.mc.commands.send.assert_not_awaited()


class ChannelIsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.cfg = config()
        self.send = AsyncMock()
        self.bots = [
            responder.Responder(
                ROOT,
                self.db,
                channels.channel_config(self.cfg, key, binding),
                binding["index"],
                "Bot",
                self.send,
            )
            for key, binding in bindings().items()
        ]

    async def test_same_message_has_independent_dedup_cooldown_and_destination(self):
        public, private = self.bots
        now = int(time.time())
        self.assertTrue(public.accept(packet(0, timestamp=now), now=now))
        self.assertFalse(public.accept(packet(0, timestamp=now), now=now))
        self.assertTrue(private.accept(packet(1, timestamp=now), now=now))
        self.assertFalse(private.accept(packet(1, "!time", timestamp=now), now=now))
        self.assertEqual(
            self.db.execute("SELECT COUNT(DISTINCT id) FROM bot_requests").fetchone()[0], 2
        )
        with patch.object(responder, "run_script", AsyncMock(return_value=("done", ""))):
            await private.process_one()
            await public.process_one()
        self.assertEqual(
            [call.args for call in self.send.await_args_list],
            [(1, "@Alice done"), (0, "@Alice done")],
        )

    async def test_denied_program_cannot_queue_or_execute_after_assignment_removed(self):
        public, private = self.bots
        self.assertFalse(public.accept(packet(0, "!time")))
        self.assertTrue(private.accept(packet(1, "!time")))
        self.cfg["commands"]["!time"]["channels"] = []
        with patch.object(responder, "run_script", AsyncMock()) as run:
            self.assertTrue(await private.process_one())
            run.assert_not_awaited()
        self.send.assert_not_awaited()
        self.assertEqual(self.db.execute("SELECT state FROM bot_requests").fetchone()[0], "expired")

    async def test_channel_queue_limit_leaves_room_for_other_channel(self):
        public, private = self.bots
        self.assertTrue(public.accept(packet(0, sender="Alice")))
        self.assertTrue(public.accept(packet(0, sender="Bob")))
        self.assertFalse(public.accept(packet(0, sender="Carol")))
        self.assertTrue(private.accept(packet(1, sender="Carol")))

    async def test_same_sender_alarms_are_independent_and_revocation_stops_one(self):
        public, private = self.bots
        self.assertTrue(public.accept(packet(0, "!floodalarm 94501")))
        self.assertTrue(private.accept(packet(1, "!floodalarm 94502")))
        await public.process_one()
        await private.process_one()
        self.assertEqual(public.alarms.row("Alice")["location"], "94501")
        self.assertEqual(private.alarms.row("Alice")["location"], "94502")
        self.assertTrue(public.alarms.row("Alice")["ready"])
        self.cfg["commands"]["!floodalarm"]["channels"] = ["ops"]
        public.alarms.read_status = AsyncMock()
        self.assertFalse(await public.alarms.check_one())
        public.alarms.read_status.assert_not_awaited()
        self.assertFalse(public.alarms.row("Alice")["enabled"])
        self.assertTrue(private.alarms.row("Alice")["enabled"])

    async def test_stale_radio_identity_prevents_execution_and_reply(self):
        bot = self.bots[1]
        bot.verify = AsyncMock(side_effect=RuntimeError("Radio key changed"))
        self.assertTrue(bot.accept(packet(1)))
        with patch.object(responder, "run_script", AsyncMock()) as run:
            await bot.process_one()
            run.assert_not_awaited()
        self.send.assert_not_awaited()
        self.assertEqual(self.db.execute("SELECT state FROM bot_requests").fetchone()[0], "failed")

    async def test_script_receives_channel_context_without_any_channel_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "inspect_context.py").write_text(
                "import json,os,sys\n"
                "request=json.load(sys.stdin)\n"
                "print(json.dumps({'id':os.environ['MESHCORE_CHANNEL_ID'],"
                "'name':os.environ['MESHCORE_CHANNEL'],'slot':os.environ['MESHCORE_CHANNEL_INDEX'],"
                "'keys':[k for k in os.environ if k.startswith('MESHCORE_CHANNEL_KEY_')],"
                "'request_id':request['channel_id']}))\n",
                encoding="utf-8",
            )
            bot = self.bots[1]
            request = responder.parse_message(packet(1), 1, "Bot", bot.config, time.time())
            with patch.dict(
                os.environ,
                {
                    "MESHCORE_CHANNEL_KEY_OPS": KEY.hex(),
                    "MESHCORE_CHANNEL_KEY_OTHER": "another-private-key",
                },
            ):
                output, detail = await responder.run_script(
                    root, {"script": "inspect_context.py"}, request, bot.config
                )
            self.assertEqual(detail, "")
            self.assertEqual(
                json.loads(output),
                {"id": "ops", "name": "#Operations", "slot": "1", "keys": [], "request_id": "ops"},
            )


class ExternalProgramTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        """Create separate package and operator-program folders containing only test files."""
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.root = self.base / "package"
        self.programs = self.base / "operator-programs"
        self.root.mkdir()
        self.programs.mkdir()
        (self.programs / "hello.py").write_text("print('external script')\n", encoding="utf-8")
        (self.base / "outside.py").write_text("print('outside')\n", encoding="utf-8")

    def test_program_prefix_resolves_configured_folder_while_builtin_stays_local(self):
        """Explicit programs/ paths select operator files without changing package scripts."""
        (self.root / "builtin.py").write_text("print('builtin')\n", encoding="utf-8")
        self.assertEqual(
            responder.script_path(self.root, "programs/hello.py", str(self.programs)),
            (self.programs / "hello.py").resolve(),
        )
        self.assertEqual(
            responder.script_path(self.root, "builtin.py", str(self.programs)),
            (self.root / "builtin.py").resolve(),
        )

    def test_external_traversal_absolute_paths_and_nonpython_files_are_rejected(self):
        """Only existing Python files inside the configured operator directory may execute."""
        (self.programs / "notes.txt").write_text("not executable", encoding="utf-8")
        for relative in [
            "programs/../outside.py",
            "programs/../../outside.py",
            str(self.base / "outside.py"),
            "programs/notes.txt",
            "programs/missing.py",
        ]:
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                responder.script_path(self.root, relative, str(self.programs))
        with self.assertRaises(ValueError):
            responder.script_path(self.root, "programs/hello.py", "relative-directory")

    def test_external_symlink_cannot_escape_program_directory(self):
        """Resolved symlink targets must remain within the configured program directory."""
        link = self.programs / "escape.py"
        try:
            link.symlink_to(self.base / "outside.py")
        except OSError as exc:
            self.skipTest(f"Host cannot create a test symlink: {exc}")
        with self.assertRaises(ValueError):
            responder.script_path(self.root, "programs/escape.py", str(self.programs))

    async def test_custom_program_executes_on_assigned_channel_and_persists_request(self):
        """An added program runs from disk, receives channel context, and replies privately."""
        (self.programs / "hello.py").write_text(
            "import json,os,sys\n"
            "request=json.load(sys.stdin)\n"
            "print('Hello ' + request['sender'] + ' on ' + os.environ['MESHCORE_CHANNEL_ID'])\n",
            encoding="utf-8",
        )
        cfg = config()
        cfg["program_directory"] = str(self.programs)
        cfg["commands"] = {"!hello": {"script": "programs/hello.py", "channels": ["ops"]}}
        responder.validate_config(cfg, self.root)
        with closing(sqlite3.connect(":memory:")) as db:
            send = AsyncMock()
            bound = bindings()
            public = responder.Responder(
                self.root,
                db,
                channels.channel_config(cfg, "community", bound["community"]),
                0,
                "Bot",
                send,
            )
            private = responder.Responder(
                self.root, db, channels.channel_config(cfg, "ops", bound["ops"]), 1, "Bot", send
            )
            self.assertFalse(public.accept(packet(0, "!hello")))
            self.assertTrue(private.accept(packet(1, "!hello")))
            self.assertTrue(await private.process_one())
            send.assert_awaited_once_with(1, "@Alice Hello Alice on ops")
            row = db.execute("SELECT state,channel_id,context FROM bot_requests").fetchone()
            self.assertEqual(row[:2], ("sent", "ops"))
            self.assertEqual(json.loads(row[2])["command"], "!hello")


if __name__ == "__main__":
    unittest.main()
