"""List/check radio channels or explicitly provision one configured channel.

Stop the service before using the serial port. Listing never prints keys.
Normal bridge startup does not call the provisioning operation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from channels import discover, expected_key, radio_key, resolve_channels


async def provision(mc, channel_id, config):
    """Create in an empty slot, or accept an exact existing match. Never overwrite."""
    from meshcore import EventType

    spec = config["channels"][channel_id]
    key = expected_key(spec)
    if key is None:
        raise ValueError(
            "existing channels are read-only; choose public, hashtag or private to provision"
        )
    slots = await discover(mc)
    matches = [p for p in slots if p["channel_name"] == spec["name"]]
    if "slot" in spec:
        candidates = [p for p in slots if p["channel_idx"] == spec["slot"]]
    elif matches:
        candidates = matches
    else:
        candidates = [p for p in slots if not p["channel_name"] and radio_key(p) == bytes(16)][:1]
    if len(candidates) != 1:
        raise RuntimeError(
            "No unique available slot; specify a valid empty slot or free one using the MeshCore app"
        )
    slot = candidates[0]["channel_idx"]
    # Re-read immediately before writing in case the channel was changed after discovery.
    event = await mc.commands.get_channel(slot)
    if event.type != EventType.CHANNEL_INFO or event.payload.get("channel_idx") != slot:
        raise RuntimeError("Cannot verify the target slot")
    current = event.payload
    if current["channel_name"] == spec["name"] and radio_key(current) == key:
        return slot
    if current["channel_name"] or radio_key(current) != bytes(16):
        raise RuntimeError("Target slot is occupied; provisioning will not overwrite it")
    # meshcore 2.3.11 set_channel derives keys for # names even with an explicit key.
    # Send the documented set-channel frame so private # names keep the supplied key.
    frame = b"\x20" + bytes([slot]) + spec["name"].encode("utf-8").ljust(32, b"\x00") + key
    result = await mc.commands.send(frame, [EventType.OK, EventType.ERROR])
    if result.type != EventType.OK:
        raise RuntimeError("Radio rejected channel creation")
    event = await mc.commands.get_channel(slot)
    if (
        event.type != EventType.CHANNEL_INFO
        or event.payload.get("channel_idx") != slot
        or event.payload["channel_name"] != spec["name"]
        or radio_key(event.payload) != key
    ):
        raise RuntimeError("Channel write could not be verified; inspect the radio before retrying")
    return slot


async def run(config, action, channel_id=None):
    """Open the configured radio for one operator action; always disconnect."""
    from radio_connection import radio_session

    # Protocol DEBUG logs may contain channel keys; suppress them for this tool.
    logging.getLogger("meshcore").setLevel(logging.CRITICAL)
    async with radio_session(config) as (mc, _):
        if action == "list":
            for p in await discover(mc):
                print(
                    json.dumps(
                        {
                            "slot": p["channel_idx"],
                            "name": p["channel_name"],
                            "empty": not p["channel_name"] and radio_key(p) == bytes(16),
                        }
                    )
                )
        elif action == "check":
            for channel_id, b in (await resolve_channels(mc, config["responder"])).items():
                checked = (
                    "name/slot verified; existing key pin checked at service startup"
                    if b["type"] == "existing"
                    else "name/key verified"
                )
                print(f"{channel_id}: slot {b['index']}; {checked}; MQTT export={b['mqtt_export']}")
        else:
            if channel_id not in config["responder"]["channels"]:
                raise ValueError("Unknown channel ID")
            slot = await asyncio.wait_for(provision(mc, channel_id, config["responder"]), 120)
            print(f"{channel_id}: channel verified in slot {slot}")


def main(argv=None):
    """Load settings/secrets and dispatch list, check, or explicit radio provisioning."""
    from responder import validate_config
    from service_runner import load_environment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--environment", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="Read available radio slots without printing keys")
    sub.add_parser("check", help="Verify every configured name and key without writes")
    add = sub.add_parser("provision", help="Explicitly create one channel in an empty radio slot")
    add.add_argument("channel_id")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    load_environment(args.environment)
    if args.action != "list":
        validated = dict(config["responder"], enabled=True)
        validate_config(validated, Path(__file__).resolve().parent)
        config["responder"] = validated
    asyncio.run(run(config, args.action, getattr(args, "channel_id", None)))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Channel setup failed: {exc}")
        raise SystemExit(1)
