"""Unattended entry point used by Windows SCM and Linux systemd installers."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal

import service

ENVIRONMENT_KEYS = {"AIRNOW_API_KEY", "MESHCORE_MQTT_USERNAME", "MESHCORE_MQTT_PASSWORD"}


def validate_serial_port(port, platform=None):
    """Only explicit serial devices are allowed; never invoke an unattended dialog."""
    platform = platform or os.name
    if not isinstance(port, str):
        raise ValueError("Set serial_port in the installed config.json")
    windows = bool(re.fullmatch(r"COM[1-9][0-9]*", port, re.I))
    linux = bool(re.fullmatch(r"/dev/tty(?:ACM|USB)[0-9]+", port) or
                 re.fullmatch(r"/dev/serial/by-id/[A-Za-z0-9_.:+-]+", port))
    if not (windows if platform == "nt" else linux):
        raise ValueError("Use COM1 or another COM port on Windows; /dev/ttyUSB0, "
                         "/dev/ttyACM0, or /dev/serial/by-id/... on Linux")
    return port


def load_environment(path):
    """Read optional credentials without accepting interpreter/path overrides."""
    if path is None or not path.exists():
        return
    values = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(values, dict) or set(values) - ENVIRONMENT_KEYS:
        raise ValueError("environment.json only accepts AirNow and MQTT credentials")
    if any(not isinstance(value, str) for value in values.values()):
        raise ValueError("Environment values must be strings")
    os.environ.update(values)


async def supervise(config, stop_file=None, *, install_signals=True):
    """Cancel the bridge on SIGTERM or SCM stop; allow its finally blocks to run."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    if install_signals and os.name == "posix":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

    async def wait_for_stop():
        while not stop.is_set():
            if stop_file is not None and stop_file.exists():
                return
            try:
                await asyncio.wait_for(stop.wait(), 0.25)
            except asyncio.TimeoutError:
                pass

    worker = asyncio.create_task(service.run_mode(config, "bridge"))
    stopper = asyncio.create_task(wait_for_stop())
    try:
        done, _ = await asyncio.wait((worker, stopper), return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            await worker
            raise RuntimeError("Bridge exited unexpectedly; the service manager can restart it")
    finally:
        worker.cancel()
        stopper.cancel()
        await asyncio.gather(worker, stopper, return_exceptions=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate configuration/dependencies without connecting")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    validate_serial_port(config.get("serial_port"))
    service.validate_config(config.get("responder", {"enabled": False}), service.ROOT)
    if config["command_timeout"] <= 0 or config["command_interval"] < 0:
        raise ValueError("Invalid command timing")
    prefix = config["mqtt"]["prefix"].strip("/")
    if not prefix or any(c in prefix for c in "+#\x00"):
        raise ValueError("Invalid MQTT prefix")
    load_environment(args.environment)
    # Import checks establish an installed runtime without opening serial/network connections.
    import meshcore, paho.mqtt.client, amqtt, serial, skyfield.api  # noqa: F401
    if args.check:
        print("Service configuration and dependencies are ready.")
        return 0
    service.RUNTIME = args.state_dir.resolve()
    service.RUNTIME.mkdir(parents=True, exist_ok=True)
    log = RotatingFileHandler(service.RUNTIME / "service.log", maxBytes=5_000_000,
                              backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[log, logging.StreamHandler()],
                        format="%(asctime)s %(levelname)s %(message)s")
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.chdir(service.ROOT)
    asyncio.run(supervise(config, args.stop_file))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.exception("Installed service stopped")
        raise SystemExit(1)
