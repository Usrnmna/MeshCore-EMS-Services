"""Regression checks for the isolated packaged-history verification seam."""
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from installers.desktop import history_smoke as smoke


class HistorySmokeTests(unittest.TestCase):
    def test_exited_process_during_proc_read_is_not_reported_alive(self):
        from tools import test_packaged_history as verifier
        for operation in ("exists", "read_text"):
            for error in (FileNotFoundError(errno.ENOENT, "Synthetic vanished proc entry"),
                          ProcessLookupError(errno.ESRCH, "Synthetic exited process")):
                with self.subTest(operation=operation, error=type(error).__name__), \
                     patch.object(verifier.os, "name", "posix"), patch.object(verifier, "Path") as path:
                    path.return_value.exists.return_value = True
                    getattr(path.return_value, operation).side_effect = error
                    try:
                        alive = verifier.process_alive(12345)
                    except (FileNotFoundError, ProcessLookupError):
                        self.fail("A process that exited during proc lookup must be reported as exited")
                    self.assertFalse(alive)

    def test_unreadable_proc_entry_does_not_claim_process_exit(self):
        from tools import test_packaged_history as verifier
        for operation in ("exists", "read_text"):
            for error in (PermissionError(errno.EACCES, "Synthetic unreadable proc entry"),
                          OSError(errno.EIO, "Synthetic proc I/O error")):
                with self.subTest(operation=operation, error=type(error).__name__), \
                     patch.object(verifier.os, "name", "posix"), patch.object(verifier, "Path") as path:
                    path.return_value.exists.return_value = True
                    getattr(path.return_value, operation).side_effect = error
                    with self.assertRaises(type(error)):
                        verifier.process_alive(12345)

    def test_fixture_uses_real_read_only_paging_and_preserves_metadata(self):
        with smoke.fixture_reader() as read:
            catalog = read(smoke.request())
            self.assertEqual([item["channel_id"] for item in catalog["channels"]], ["previous", "private", "public"])
            first = read(smoke.request("page", channel_id="public", page_size=200))
            second = read(smoke.request("page", channel_id="public", page_size=200, cursor=first["next_cursor"]))
            self.assertEqual([len(page["messages"]) for page in (first, second)], [200, 5])
            self.assertEqual(first["messages"][0]["text"], smoke.SYNTHETIC_TEXT)
            self.assertEqual(first["messages"][0]["payload"]["data"]["data"], "00ff")
            self.assertEqual(datetime.fromisoformat(first["queried_at"]).tzinfo, timezone.utc)
            self.assertEqual(len({row["event_id"] for page in (first, second) for row in page["messages"]}), 205)

    def test_smoke_mode_cannot_choose_paths_programs_or_bypass_request_validation(self):
        for value in ("../read", "shell", "--history-read", "read /tmp/example"):
            with self.assertRaises(ValueError):
                smoke.smoke_command(value)
            with self.assertRaises(ValueError):
                smoke.helper_main(value)
        with smoke.fixture_reader() as read:
            for value in (dict(smoke.request(), database="elsewhere"), smoke.request("page", channel_id="../escape")):
                with self.assertRaises(ValueError):
                    read(value)

    def test_entry_points_dispatch_smoke_helpers_before_loading_qt(self):
        from installers.desktop import service_main
        from installers.datasets.gui import main
        for entry in (service_main.main, main.main):
            with patch.object(smoke, "helper_main", return_value=37) as helper:
                self.assertEqual(entry(["--history-smoke-helper", "session"]), 37)
                helper.assert_called_once_with("session")
            with self.assertRaises(ValueError):
                entry(["--history-smoke-helper", "read", "/arbitrary"])

    @unittest.skipUnless(os.name == "nt", "Windows windowed Python stdio")
    def test_windowed_python_recovers_only_redirected_helper_streams(self):
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file():
            self.skipTest("Windowed Python is unavailable")
        from tools.test_packaged_history import helper_exchange
        script = Path(__file__).resolve().parents[1] / "installers/desktop/service_main.py"
        result, code, _ = helper_exchange([str(pythonw), str(script)], dict(smoke.request(), action="invalid"), normal=True)
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
