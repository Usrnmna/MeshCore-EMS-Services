"""Refresh validated wildfire snapshots; standalone execution never starts a scheduler."""

if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "scripts"

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from . import wildfire_settings as settings
from . import dataset_paths
from .fire_weather import fetch_fwf
from .fire_environment_sources import HMS_URL, NFDRS_URL, FEMS_URL, hms, nfdrs, fems
from .wildfire_sources import Client, NWS, SOURCES, STATE_URL, ZONE_URL
from .wildfire_spatial import checked_geometry, prepare_zones, scope
from .wildfire_store import Store, encode

SEED = settings.ROOT / "data" / "wildfire"


def seed(store):
    """Initialize offline zones from a checksum-verified package snapshot."""
    if store.status("zones").get("fetched"):
        return
    directory = dataset_paths.resolve("wildfire", SEED)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    raw = (directory / "zones.geojson").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["sha256"]:
        raise ValueError("Bundled wildfire zone checksum mismatch")
    features = json.loads(raw)["features"]
    if len(features) != manifest["feature_count"]:
        raise ValueError("Bundled wildfire zone count mismatch")
    store.replace("zones", features, manifest["source"], now=manifest["retrieved_at"])


def boundaries(client):
    """Retrieve California and all intersecting candidate fire zones, retaining whole geometry."""
    states = client.arcgis(STATE_URL, "STUSPS='CA'")
    if len(states) != 1:
        raise ValueError("California reference boundary missing or ambiguous")
    california = checked_geometry(states[0])
    candidates = client.arcgis(ZONE_URL, bounds=california.bounds)
    return prepare_zones(candidates, california), states


def refresh(store, config, only=None, force=False, client=None):
    """Refresh sources independently under one lease; failures retain successful snapshots."""
    client = client or Client(240, store.path.parent / "wildfire-downloads")
    report = {}
    with store.lease():
        seed(store)
        zones = store.features("zones")
        _, bounds = scope(zones, config["maximum_radius_miles"])
        offices = sorted({o.strip() for f in zones for o in f["properties"]["cwa"].split(",")})
        jobs = {
            "zones": (config["boundary_interval"], ZONE_URL, lambda: boundaries(client)[0]),
            "egp": (config["incident_interval"], SOURCES["egp"][0], None),
            "incidents": (config["incident_interval"], SOURCES["incidents"][0], None),
            "perimeters": (config["perimeter_interval"], SOURCES["perimeters"][0], None),
            "alerts": (config["alert_interval"], NWS + "/alerts/active", client.alerts),
            "hms": (config["smoke_interval"], HMS_URL, lambda: hms(client)),
            "nfdrs": (config["danger_interval"], NFDRS_URL, lambda: nfdrs(client)),
        }
        if config["fems_station_ids"]:
            jobs["fems"] = (config["danger_interval"], FEMS_URL,
                            lambda: fems(client, config["fems_station_ids"]))
        for office in offices:
            jobs["fwf:" + office] = (config["weather_interval"], f"{NWS}/products/types/FWF/locations/{office}",
                                      lambda office=office: fetch_fwf(client, office))
        for name in config["context_sources"]:
            if name in SOURCES:
                jobs[name] = (config["context_interval"], SOURCES[name][0], None)
        # Explicit local requests can populate optional sources without enabling recurring downloads.
        for name in only or []:
            if name in SOURCES and name not in jobs:
                jobs[name] = (config["context_interval"], SOURCES[name][0], None)
        if only and set(only) - jobs.keys():
            raise ValueError("Unknown source: " + ", ".join(sorted(set(only) - jobs.keys())))
        # Oldest attempts run first so a large optional feed cannot starve later feeds.
        ordered = sorted(jobs, key=lambda name: store.status(name).get("attempted") or 0)
        for name in ordered:
            interval, url, loader = jobs[name]
            if only and name not in only:
                continue
            status = store.status(name)
            last_attempt = status.get("attempted") or 0
            if not force and time.time() - last_attempt < interval:
                continue
            if time.monotonic() >= client.deadline:
                break
            try:
                features = loader() if loader else client.source(name, bounds)
                for feature in features:
                    if feature.get("geometry") is not None:
                        checked_geometry(feature)
                # Validate required attribution before declaring the core feed usable.
                required = {"egp": "IrwinID", "incidents": "IrwinID"}
                if name in required and any(not f["properties"].get(required[name]) for f in features):
                    raise ValueError(f"{name} contains an incident without its IRWIN identifier")
                if name == "perimeters":
                    for feature in features:
                        p = feature["properties"]
                        p["join_status"] = "linked" if p.get("attr_IrwinID") or p.get("poly_IRWINID") else "unlinked"
                store.replace(name, features, url, history_days=config["history_days"])
                report[name] = {"count": len(features), "ok": True}
                if name == "zones":
                    _, bounds = scope(features, config["maximum_radius_miles"])
            except Exception as exc:
                store.fail(name, exc)
                report[name] = {"ok": False, "error": str(exc)}
    return report


def main(argv=None):
    """Perform a bounded refresh, cache-status inspection, or GeoJSON export."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=settings.database_path())
    parser.add_argument("--source", action="append", help="Refresh only this source (repeatable)")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--export", metavar="SOURCE", help="Write cached features as GeoJSON to stdout")
    args = parser.parse_args(argv)
    try:
        if args.status or args.export:
            with Store(args.db) as store:
                result = ({"type": "FeatureCollection", "features": store.features(args.export)}
                          if args.export else store.statuses())
        else:
            with Store(args.db, writable=True) as store:
                result = refresh(store, settings.load(), args.source, args.force)
        print(encode(result))
        failed = {} if args.status or args.export else {k: v for k, v in result.items() if not v["ok"]}
        if failed:
            print(encode(failed), file=sys.stderr)
        return 1 if failed else 0
    except Exception as exc:
        print(encode({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
