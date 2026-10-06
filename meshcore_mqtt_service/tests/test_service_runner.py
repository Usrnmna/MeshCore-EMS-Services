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


def serial_device(name, vid=None, hwid=""):
    """Build an enumerated port record without opening a physical serial device."""
    return SimpleNamespace(device=name, vid=vid, hwid=hwid)


class ServiceRunnerTests(unittest.TestCase):
    def test_auto_port_setting_is_case_insensitive_on_both_platforms(self):
        """Automatic selection is a config value, never a platform-specific port name."""
        for platform in ("nt", "posix"):
            for setting in ("auto", "AUTO", "Auto"):
                with self.subTest(platform=platform, setting=setting):
                    self.assertEqual(runner.validate_serial_port(setting, platform), "auto")

    def test_auto_detects_windows_com_and_linux_usb_or_acm(self):
        """USB identity may come from a vendor ID or the enumerator's hardware ID."""
        cases = [
            ("nt", serial_device("COM23", vid=0x303A)),
            ("posix", serial_device("/dev/ttyUSB2", vid=0x10C4)),
            ("posix", serial_device("/dev/ttyACM4", hwid="usb VID:PID=303A:1001")),
        ]
        for platform, device in cases:
            with self.subTest(platform=platform, port=device.device):
                with patch(
                    "serial.tools.list_ports.comports", return_value=[device]
                ) as enumerate_ports:
                    self.assertEqual(runner.select_serial_port("auto", platform), device.device)
                    enumerate_ports.assert_called_once_with()

    def test_auto_ignores_bluetooth_nonusb_and_invalid_platform_ports(self):
        """Unrelated serial devices and invalid port strings cannot become candidates."""
        devices = [
            serial_device("COM7", hwid="BTHENUM\\{bluetooth-service}"),
            serial_device("COM8", hwid="ACPI\\PNP0501"),
            serial_device("/dev/ttyUSB0", vid=0x1234),
            serial_device("COM9; unexpected", vid=0x1234),
            serial_device("COM24", vid=0x303A),
        ]
        with patch("serial.tools.list_ports.comports", return_value=devices):
            self.assertEqual(runner.select_serial_port("auto", "nt"), "COM24")

    def test_no_or_multiple_usb_devices_fail_without_guessing(self):
        """Absence and ambiguity require a useful error instead of opening an arbitrary port."""
        cases = [
            ([], "No USB"),
            ([serial_device("COM5", hwid="BTHENUM")], "No USB"),
            (
                [serial_device("COM23", vid=0x303A), serial_device("COM24", vid=0x1234)],
                "Multiple USB",
            ),
        ]
        for devices, message in cases:
            with self.subTest(message=message, count=len(devices)):
                with patch("serial.tools.list_ports.comports", return_value=devices):
                    with self.assertRaisesRegex(ConnectionError, message):
                        runner.select_serial_port("auto", "nt")

    def test_explicit_fixed_port_bypasses_usb_enumeration(self):
        """An operator's fixed override stays usable even when several USB devices exist."""
        with patch(
            "serial.tools.list_ports.comports", side_effect=AssertionError("must not enumerate")
        ):
            self.assertEqual(runner.select_serial_port("COM31", "nt"), "COM31")
            self.assertEqual(runner.select_serial_port("/dev/ttyACM8", "posix"), "/dev/ttyACM8")

    def test_auto_rescans_after_port_renumbering_and_deduplicates_records(self):
        """Repeated starts observe fresh port numbers while duplicate records count once."""
        old = serial_device("COM23", vid=0x303A)
        new = serial_device("COM27", vid=0x303A)
        with patch(
            "serial.tools.list_ports.comports", side_effect=[[old, old], [new]]
        ) as enumerate_ports:
            self.assertEqual(runner.select_serial_port("auto", "nt"), "COM23")
            self.assertEqual(runner.select_serial_port("auto", "nt"), "COM27")
            self.assertEqual(enumerate_ports.call_count, 2)

    def test_platform_ports_and_injection_rejected(self):
        for port in ("COM1", "COM11"):
            self.assertEqual(runner.validate_serial_port(port, "nt"), port)
        for port in ("/dev/ttyACM0", "/dev/ttyUSB1", "/dev/serial/by-id/usb-Test_123-if00"):
            self.assertEqual(runner.validate_serial_port(port, "posix"), port)
        for platform, port in (
            ("nt", "COM1; reboot"),
            ("nt", "COM0"),
            ("posix", "/dev/serial/by-id/../../etc/passwd"),
            ("posix", "COM1"),
            ("nt", None),
        ):
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
            with patch.object(
                service, "run_mode", new=AsyncMock(side_effect=ConnectionError("lost"))
            ):
                with self.assertRaises(ConnectionError):
                    await runner.supervise({}, install_signals=False)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
