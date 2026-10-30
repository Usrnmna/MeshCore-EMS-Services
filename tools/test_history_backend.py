"""Read-only desktop history request and trusted installed reader contracts."""
import json
from contextlib import ExitStack, contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from installers.datasets.gui.discovery import native_target


def request(action="catalog", **query):
    return dict(schema=1, kind="history", target=native_target(), action=action, query=query)


class HistoryBackendTests(unittest.TestCase):
    def backend(self):
        from installers.desktop import history_backend
        return history_backend

    def test_strict_requests_reject_mutation_and_injection(self):
        backend = self.backend()
        self.assertEqual(backend.validate_history_request(request()), request())
        for update in ({"schema": True}, {"schema": 2}, {"kind": "service"},
                       {"target": "other"}, {"action": "start"}, {"sql": "select 1"},
                       {"database": "/tmp/private"}, {"module": "evil"}, {"command": "evil"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                backend.validate_history_request(dict(request(), **update))
        for query in ({"channel_id": "../escape"}, {"channel_id": "a" * 65},
                      {"channel_id": "public", "page_size": True},
                      {"channel_id": "public", "page_size": 201},
                      {"channel_id": "public", "start": "2026-01-01"},
                      {"channel_id": "public", "cursor": "not a cursor"},
                      {"channel_id": "public", "sender": "x" * 4097},
                      {"channel_id": "public", "sender": "x", "sender_prefix": "y"},
                      {"channel_id": "public", "database": "elsewhere"}):
            with self.subTest(query=query), self.assertRaises(ValueError):
                backend.validate_history_request(request("page", **query))

    def test_sender_whitespace_and_aware_dates_preserved(self):
        value = request("page", channel_id="public", sender_prefix=" a ", start="2026-01-01T01:00:00+01:00")
        self.assertEqual(self.backend().validate_history_request(value), value)

    def test_only_permission_denial_requests_authorization_once(self):
        backend = self.backend()
        with patch.object(backend, "perform", side_effect=PermissionError()), \
             patch("installers.desktop.authorization.run_authorized", return_value={"channels": []}) as authorize:
            self.assertEqual(backend.query_history(request(), lambda _: self.fail("private log"), threading.Event()), {"channels": []})
            self.assertEqual(authorize.call_count, 1)
        with patch.object(backend, "perform", side_effect=RuntimeError("Database unavailable")), \
             patch("installers.desktop.authorization.run_authorized") as authorize:
            with self.assertRaises(RuntimeError):
                backend.query_history(request(), lambda _: None, threading.Event())
            authorize.assert_not_called()

    def test_catalog_and_missing_database_are_read_only(self):
        backend = self.backend()
        from installers.desktop import service_backend
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_name = "meshcore_mqtt_service_windows" if native_target() == "windows-x64" else "meshcore_mqtt_service"
            package = root / package_name
            package.mkdir()
            shutil.copy(Path(__file__).resolve().parents[1] / package_name / "channel_history.py", package)
            (root / "config.json").write_text(json.dumps({"channel_history": {"enabled": True, "channel_id": "public"}}))
            with patch.object(service_backend, "installed_paths", return_value=(root, root, root, root / "python", "test")), \
                 patch("installers.desktop.history_state.service_state", return_value="stopped"), \
                 patch.object(service_backend, "installed_capabilities", return_value=["channel-history-v1"]), \
                 patch.object(service_backend, "trusted_installed", side_effect=lambda path, root: Path(path)), \
                 patch("installers.desktop.windows_trust.protected_paths", side_effect=lambda paths: nullcontext()), \
                 patch.object(service_backend, "control", side_effect=AssertionError("service mutation")), \
                 patch.object(service_backend, "configure_installed", side_effect=AssertionError("configuration mutation")):
                value = backend.read_installed(request())
                self.assertEqual(value["availability"], "not_created")
                self.assertEqual(value["settings"], {"enabled": True, "channel_id": "public"})
                self.assertFalse((root / "runtime").exists())
                with self.assertRaisesRegex(RuntimeError, "not created"):
                    backend.read_installed(request("page", channel_id="public"))
                database = root / "runtime/channel_history/channel_history.sqlite3"
                database.parent.mkdir(parents=True)
                database.write_bytes(b"not a database")
                with self.assertRaisesRegex(RuntimeError, "unavailable"):
                    backend.read_installed(request())
                self.assertEqual(database.read_bytes(), b"not a database")

    def test_unsupported_capability_never_loads_module(self):
        backend = self.backend()
        from installers.desktop import service_backend
        with patch.object(service_backend, "installed_paths", return_value=(Path("missing"),) * 4 + ("test",)), \
             patch("installers.desktop.history_state.service_state", return_value="stopped"), \
             patch.object(service_backend, "installed_capabilities", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "update required"):
                backend.read_installed(request())

    def test_untrusted_installed_module_is_not_an_authorization_trigger(self):
        backend = self.backend()
        from installers.desktop import service_backend
        with patch.object(service_backend, "installed_paths", return_value=(Path("missing"),) * 4 + ("test",)), \
             patch("installers.desktop.history_state.service_state", return_value="stopped"), \
             patch.object(service_backend, "installed_capabilities", return_value=["channel-history-v1"]), \
             patch.object(service_backend, "trusted_installed", side_effect=PermissionError("unsafe code")):
            with self.assertRaisesRegex(RuntimeError, "Untrusted"):
                backend.read_installed(request())

    @contextmanager
    def installed_store(self):
        """Build a real SQLite store while replacing only native installation discovery."""
        from installers.desktop import service_backend
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            package = "meshcore_mqtt_service_windows" if native_target() == "windows-x64" else "meshcore_mqtt_service"
            (root / package).mkdir()
            shutil.copy(Path(__file__).resolve().parents[1] / package / "channel_history.py", root / package)
            database = root / "runtime/channel_history/channel_history.sqlite3"
            database.parent.mkdir(parents=True)
            writer = sqlite3.connect(database)
            stack.callback(writer.close)
            writer.executescript('''PRAGMA user_version=1; PRAGMA journal_mode=WAL;
CREATE TABLE channel_messages(event_id TEXT PRIMARY KEY, received_at_us INTEGER,
channel_id TEXT, channel_name TEXT, channel_identity TEXT, channel_index INTEGER,
binding_source TEXT, binding_observed_at INTEGER, text TEXT, sender TEXT,
source_message_id TEXT, sender_timestamp INTEGER, payload TEXT, attributes TEXT,
device TEXT, reception_json TEXT);''')
            stamp = time.time_ns() // 1000 - 10_000_000
            def insert(event, received=stamp):
                writer.execute('INSERT INTO channel_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (event, received, "public", "Public", "identity", 0, "passive_snapshot", received,
                     " PRIVATE\né›ª\x00 ", None, None, 123, '{"data":{"encoding":"hex","data":"00ff"}}', '{}', '{}', '{}'))
                writer.commit()
            insert("one")
            for name, value in (("installed_paths", (root, root, root, root / "python", "test")),
                                ("installed_capabilities", ["channel-history-v1"])):
                stack.enter_context(patch.object(service_backend, name, return_value=value))
            stack.enter_context(patch("installers.desktop.history_state.service_state", return_value="stopped"))
            stack.enter_context(patch.object(service_backend, "trusted_installed", side_effect=lambda path, root: Path(path)))
            stack.enter_context(patch("installers.desktop.windows_trust.protected_paths", side_effect=lambda paths: nullcontext()))
            for name in ("control", "configure_installed", "check_connection", "validate_installed"):
                stack.enter_context(patch.object(service_backend, name, side_effect=AssertionError("History invoked a mutation or radio check")))
            yield root, writer, insert

    def test_real_reader_utc_metadata_and_concurrent_writer_remain_read_only(self):
        backend = self.backend()
        original_connect = sqlite3.connect
        statements = []
        def read_only_connection(path, **options):
            self.assertTrue(path.endswith("?mode=ro"))
            self.assertTrue(options["uri"])
            self.assertEqual(options["timeout"], 1)
            connection = original_connect(path, **options)
            connection.set_trace_callback(statements.append)
            return connection
        with self.installed_store() as (root, writer, insert), patch.object(sqlite3, "connect", side_effect=read_only_connection):
            catalog = backend.read_installed(request())
            self.assertEqual(catalog["channels"][0]["channel_id"], "public")
            first = backend.read_installed(request("page", channel_id="public"))
            self.assertEqual(first["messages"][0]["text"], " PRIVATE\né›ª\x00 ")
            self.assertEqual(first["messages"][0]["payload"]["data"], {"encoding": "hex", "data": "00ff"})
            self.assertTrue(first["messages"][0]["received_at"].endswith("+00:00"))
            insert("two")
            writer.execute("DELETE FROM channel_messages WHERE event_id='one'")
            writer.commit()
            second = backend.read_installed(request("page", channel_id="public"))
            self.assertEqual([row["event_id"] for row in second["messages"]], ["two"])
        self.assertFalse(any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE")) for statement in statements))

    def test_unsupported_database_schema_is_not_empty_or_generic_success(self):
        with self.installed_store() as (_, writer, _):
            writer.execute("PRAGMA user_version=99")
            with self.assertRaisesRegex(RuntimeError, "Unsupported history schema"):
                self.backend().read_installed(request())

    def test_reader_rechecks_module_trust_after_path_pinning(self):
        from installers.desktop import service_backend
        with self.installed_store() as (root, _, _), patch.object(service_backend, "trusted_installed", side_effect=[root / "substituted.py", PermissionError("substituted")]):
            with self.assertRaisesRegex(RuntimeError, "Untrusted"):
                self.backend().read_installed(request())

    def test_catalog_observation_and_diagnostics_exclude_untrusted_text(self):
        with self.installed_store() as (root, _, _):
            status = root / "runtime/channel_history/status.json"
            status.write_text(json.dumps(dict(state="ready", committed=1, missed=2, observed_at="2026-10-28T10:00:00+00:00", last_error="PRIVATE BODY", reasons={"PRIVATE BODY": 99})))
            value = self.backend().read_installed(request())
            self.assertTrue(value["observed_at"].endswith("+00:00"))
            self.assertEqual(value["latest_received_at"], value["channels"][0]["latest_received_at"])
            self.assertEqual(value["diagnostics"]["committed"], 1)
            self.assertNotIn("PRIVATE BODY", json.dumps(value["diagnostics"]))
            status.write_text("{invalid")
            self.assertIsNone(self.backend().read_installed(request())["diagnostics"])

    def test_fixed_storage_path_rejects_redirected_files_and_sidecars(self):
        import os
        from types import SimpleNamespace
        backend = self.backend()
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            database = state / 'runtime/channel_history/channel_history.sqlite3'
            database.parent.mkdir(parents=True)
            for name in (database, Path(str(database) + '-wal'), database.parent / 'status.json'):
                # Covers Windows reparse metadata without requiring symlink privileges.
                original = Path.lstat
                def lstat(path, *args, **kwargs):
                    if path == name:
                        return SimpleNamespace(st_mode=0o100600, st_file_attributes=0x400)
                    return original(path, *args, **kwargs)
                with patch.object(Path, 'lstat', lstat), self.assertRaisesRegex(RuntimeError, 'Untrusted'):
                    backend.validate_storage_path(state, database)
            if os.name != 'nt':
                destination = state / 'other.sqlite3'; destination.touch()
                database.symlink_to(destination)
                with self.assertRaisesRegex(RuntimeError, 'Untrusted'):
                    backend.validate_storage_path(state, database)


if __name__ == "__main__":
    unittest.main()
