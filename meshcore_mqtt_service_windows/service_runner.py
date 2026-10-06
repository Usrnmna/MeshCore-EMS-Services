"""Unattended entry point used by Windows SCM and Linux systemd installers."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal

import service
from channels import SECRET_ENV, expected_key
from radio_connection import connection_settings, select_serial_port, validate_serial_port

ENVIRONMENT_KEYS = {"AIRNOW_API_KEY", "MESHCORE_MQTT_USERNAME", "MESHCORE_MQTT_PASSWORD"}


def load_environment(path):
    """Read optional credentials without accepting interpreter/path overrides."""
    if path is None or not path.exists():
        return
    values = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(values, dict) or any(
        k not in ENVIRONMENT_KEYS and not SECRET_ENV.fullmatch(k) for k in values
    ):
        raise ValueError(
            "environment.json only accepts AirNow, MQTT and MESHCORE_CHANNEL_KEY_... credentials"
        )
    if any(not isinstance(value, str) for value in values.values()):
        raise ValueError("Environment values must be strings")
    if (
        os.name == "posix"
        and any(SECRET_ENV.fullmatch(k) for k in values)
        and path.stat().st_mode & 0o027
    ):
        raise ValueError(
            "Channel credential file must be mode 600, or mode 640 with a trusted service group"
        )
    os.environ.update(values)


async def supervise(config, stop_file=None, *, install_signals=True):
    """Cancel the bridge on SIGTERM or SCM stop; allow its finally blocks to run."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    if install_signals and os.name == "posix":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

    async def wait_for_stop():
        """Watch the SCM stop file or process signal without blocking other workers."""
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
    """Validate installed paths/secrets, optionally check offline, then supervise the service."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration/dependencies without connecting",
    )
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    connection_settings(config)
    service.validate_config(config.get("responder", {"enabled": False}), service.ROOT)
    if config["command_timeout"] <= 0 or config["command_interval"] < 0:
        raise ValueError("Invalid command timing")
    prefix = config["mqtt"]["prefix"].strip("/")
    if not prefix or any(c in prefix for c in "+#\x00"):
        raise ValueError("Invalid MQTT prefix")
    load_environment(args.environment)
    for spec in config.get("responder", {}).get("channels", {}).values():
        expected_key(spec)
    # Import checks establish an installed runtime without opening serial/network connections.
    import meshcore, paho.mqtt.client, amqtt, serial, skyfield.api  # noqa: F401

    if args.check:
        print("Service configuration and dependencies are ready.")
        return 0
    service.RUNTIME = args.state_dir.resolve()
    service.RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        service.RUNTIME.chmod(0o700)
    log = RotatingFileHandler(
        service.RUNTIME / "service.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[log, logging.StreamHandler()],
        format="%(asctime)s %(levelname)s %(message)s",
    )
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
