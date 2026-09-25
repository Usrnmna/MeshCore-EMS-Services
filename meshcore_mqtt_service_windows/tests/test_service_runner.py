"""Service lifecycle checks without installing a service or opening a radio."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import service
import service_runner as runner


class ServiceRunnerTests(unittest.TestCase):
    def test_platform_ports_and_injection_rejected(self):
        for port in ("COM1", "COM11"):
            self.assertEqual(runner.validate_serial_port(port, "nt"), port)
        for port in ("/dev/ttyACM0", "/dev/ttyUSB1", "/dev/serial/by-id/usb-Test_123-if00"):
            self.assertEqual(runner.validate_serial_port(port, "posix"), port)
        for platform, port in (("nt", "COM1; reboot"), ("nt", "COM0"),
                               ("posix", "/dev/serial/by-id/../../etc/passwd"),
                               ("posix", "COM1"), ("nt", None)):
            with self.subTest(port=port), self.assertRaises(ValueError):
                runner.validate_serial_port(port, platform)

    def test_environment_rejects_interpreter_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "environment.json"
            path.write_text(json.dumps({"PYTHONPATH": "unsafe"}))
            with self.assertRaises(ValueError):
                runner.load_environment(path)
            path.write_text(json.dumps({"AIRNOW_API_KEY": "test-key"}))
            with patch.dict(os.environ, {}, clear=True):
                runner.load_environment(path)
                self.assertEqual(os.environ["AIRNOW_API_KEY"], "test-key")

    def test_saved_port_skips_selector(self):
        async def run():
            port = "COM11" if os.name == "nt" else "/dev/ttyUSB0"
            mc = SimpleNamespace(disconnect=AsyncMock())
            cli = SimpleNamespace(interactive_loop=lambda: None, process_cmds=AsyncMock(return_value=True))
            async def main(argv):
                self.assertEqual(argv, ["-s", port, "-j", "-b", "115200"])
                await cli.interactive_loop(mc)
            cli.main = main
            with patch.object(service, "prepare_cli", return_value=(cli, {})):
                await service.radio_mode({"baudrate": 115200, "serial_port": port}, ["infos"])
            mc.disconnect.assert_awaited_once()
        asyncio.run(run())

    def test_stop_request_cancels_bridge_and_runs_cleanup(self):
        async def run(folder):
            stopped = asyncio.Event()
            async def bridge(*args):
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            stop_file = Path(folder) / "stop"
            stop_file.touch()
            with patch.object(service, "run_mode", side_effect=bridge):
                await runner.supervise({}, stop_file, install_signals=False)
            self.assertTrue(stopped.is_set())
        with tempfile.TemporaryDirectory() as folder:
            asyncio.run(run(folder))

    def test_bridge_failure_reaches_service_manager(self):
        async def run():
            with patch.object(service, "run_mode", new=AsyncMock(side_effect=ConnectionError("lost"))):
                with self.assertRaises(ConnectionError):
                    await runner.supervise({}, install_signals=False)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
