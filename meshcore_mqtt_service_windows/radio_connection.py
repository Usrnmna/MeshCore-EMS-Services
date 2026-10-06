"""Connection settings and bounded MeshCore sessions shared by all radio tools."""

import asyncio
from contextlib import asynccontextmanager
import ipaddress
import logging
import math
import os
import re

LOG = logging.getLogger("bridge")
DEFAULT_TCP_PORT = 5000
DEFAULT_CONNECT_TIMEOUT = 30
DISCONNECT_TIMEOUT = 5


def connection_settings(config, platform=None):
    """Validate without device I/O; legacy settings continue to select USB serial.

    Serial port and baudrate remain top-level settings for backwards compatibility.
    Only the active transport's fields are accepted inside the connection object.
    BLE pairing belongs to the OS; a service must not wait for interactive prompts.
    """
    values = config.get("connection", {"type": "serial"})
    if not isinstance(values, dict):
        raise ValueError("connection must be an object")
    kind = values.get("type", "serial")
    fields = {"serial": set(), "tcp": {"host", "port"}, "ble": {"address"}}
    if not isinstance(kind, str) or kind not in fields:
        raise ValueError("connection.type must be serial, tcp, or ble")
    if set(values) - (fields[kind] | {"type", "timeout"}):
        raise ValueError("Unknown or conflicting fields in connection settings")
    timeout = values.get("timeout", DEFAULT_CONNECT_TIMEOUT)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or not 1 <= timeout <= 300
    ):
        raise ValueError("connection.timeout must be 1 to 300 seconds")
    result = {"type": kind, "timeout": timeout}
    if kind == "serial":
        result["port"] = validate_serial_port(config.get("serial_port", "auto"), platform)
        baud = config.get("baudrate", 115200)
        if type(baud) is not int or baud <= 0:
            raise ValueError("baudrate must be a positive integer")
        result["baudrate"] = baud
    elif kind == "tcp":
        host = values.get("host")
        if not isinstance(host, str):
            raise ValueError("connection.host must be the node's local IP address")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise ValueError("connection.host must be an IPv4 or IPv6 address") from None
        if address.is_unspecified or address.is_multicast:
            raise ValueError("connection.host must identify one reachable node")
        port = values.get("port", DEFAULT_TCP_PORT)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("connection.port must be an integer from 1 to 65535")
        result.update(host=host, port=port)
    else:
        address = values.get("address")
        if not isinstance(address, str) or not re.fullmatch(
            r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", address
        ):
            raise ValueError("connection.address must be a BLE address such as AA:BB:CC:DD:EE:FF")
        result["address"] = address.upper()
    return result


def device_metadata(endpoint):
    """Keep device.port compatible for serial consumers; add transport identity."""
    if isinstance(endpoint, dict):
        return dict(endpoint)
    return {"port": endpoint}


async def close_radio(mc, transport):
    """Release SDK and partially opened transports, even after a failed handshake."""
    try:
        await asyncio.wait_for(mc.disconnect(), DISCONNECT_TIMEOUT)
    except Exception:
        LOG.warning("Radio session cleanup did not complete")
    finally:
        # The SDK manager skips transport cleanup if connect() never succeeded.
        try:
            await asyncio.wait_for(transport.disconnect(), DISCONNECT_TIMEOUT)
        except Exception:
            LOG.warning("Radio transport cleanup did not complete")


@asynccontextmanager
async def radio_session(config):
    """Open exactly one selected node and always close it on failure, stop, or exit.

    Retain the SDK instance before connecting so cancellation during connection
    cannot orphan a socket/BLE client. The service manager owns reconnection:
    every restarted session rechecks channels and never replays uncertain sends.
    """
    from meshcore import MeshCore
    from meshcore.serial_cx import SerialConnection
    from meshcore.tcp_cx import TCPConnection
    from meshcore.ble_cx import BLEConnection

    settings = connection_settings(config)
    kind = settings["type"]
    if kind == "serial":
        port = select_serial_port(settings["port"])
        endpoint = {"type": kind, "port": port}
    elif kind == "tcp":
        endpoint = {"type": kind, "port": settings["port"], "host": settings["host"]}
    else:
        endpoint = {"type": kind, "port": None, "address": settings["address"]}
    LOG.info("Connecting to %s radio: %s", kind, endpoint)
    mc = transport = None
    try:
        async with asyncio.timeout(settings["timeout"]):
            # Preserve the SDK serial factory's DTR fallback after a failed handshake.
            for dtr in (True, False) if kind == "serial" else (True,):
                if kind == "serial":
                    transport = SerialConnection(port, settings["baudrate"], cx_dly=0.1, dtr=dtr)
                elif kind == "tcp":
                    transport = TCPConnection(settings["host"], settings["port"])
                else:
                    transport = BLEConnection(address=settings["address"])
                mc = MeshCore(transport, auto_reconnect=False)
                if await mc.connect() is not None:
                    break
                await close_radio(mc, transport)
                mc = transport = None
            if mc is None:
                raise ConnectionError(f"No MeshCore companion handshake over {kind}")
        yield mc, endpoint
    finally:
        if mc is not None:
            await close_radio(mc, transport)


def validate_serial_port(port, platform=None):
    """Accept automatic USB detection or one platform-valid fixed port; no device I/O."""
    platform = platform or os.name
    if not isinstance(port, str):
        raise ValueError("Set serial_port in the installed config.json")
    if port.lower() == "auto":
        return "auto"
    windows = bool(re.fullmatch(r"COM[1-9][0-9]*", port, re.I))
    linux = bool(
        re.fullmatch(r"/dev/tty(?:ACM|USB)[0-9]+", port)
        or re.fullmatch(r"/dev/serial/by-id/[A-Za-z0-9_.:+-]+", port)
    )
    if not (windows if platform == "nt" else linux):
        raise ValueError(
            "Use auto for USB detection, COM1 or another COM port on Windows; /dev/ttyUSB0, "
            "/dev/ttyACM0, or /dev/serial/by-id/... on Linux"
        )
    return port


def select_serial_port(port="auto", platform=None):
    """Return a fixed port or the sole currently attached USB serial device.

    Rescan for every connection attempt so COM/tty renumbering is harmless.
    Enumeration only: never probe unrelated serial devices or pick the first of
    several candidates. The MeshCore handshake still verifies the selected radio.
    """
    port = validate_serial_port(port, platform)
    if port != "auto":
        return port
    from serial.tools.list_ports import comports

    candidates = set()
    for device in comports():
        is_usb = device.vid is not None or "USB" in (device.hwid or "").upper()
        if not is_usb:
            continue
        try:
            candidate = validate_serial_port(device.device, platform)
        except ValueError:
            continue
        candidates.add(candidate)
    if not candidates:
        raise ConnectionError(
            "No USB serial device detected. Connect the MeshCore USB companion and retry."
        )
    if len(candidates) != 1:
        raise ConnectionError(
            "Multiple USB serial devices detected: "
            + ", ".join(sorted(candidates))
            + ". Set serial_port to the intended device or disconnect the others."
        )
    return candidates.pop()
