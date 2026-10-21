"""Rebuild and mirror the complete California-associated NWS fire-zone seed."""

import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "meshcore_mqtt_service"))
from scripts.wildfire_refresh import boundaries
from scripts.wildfire_sources import Client, STATE_URL, ZONE_URL
from scripts.wildfire_store import encode


def main():
    """Download validated polygons; publish identical seeds only after all checks pass."""
    client = Client(240)
    zones, states = boundaries(client)
    payload = (encode({"type": "FeatureCollection", "features": zones}) + "\n").encode()
    manifest = {
        "schema_version": 1, "retrieved_at": time.time(), "source": ZONE_URL,
        "california_reference": STATE_URL, "feature_count": len(zones),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "selection": "Full NWS fire-zone polygons intersecting California by at least 1 hectare; no state clipping.",
        "source_dates": sorted({str(z["properties"].get("idp_filedate")) for z in zones}),
        "zone_ids": sorted(z["id"] for z in zones),
    }
    for directory in (ROOT / "data" / "wildfire",
                      ROOT / "meshcore_mqtt_service" / "data" / "wildfire",
                      ROOT / "meshcore_mqtt_service_windows" / "data" / "wildfire"):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "zones.geojson").write_bytes(payload)
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(zones)} whole zones; {len(payload):,} bytes; SHA256 {manifest['sha256']}")


if __name__ == "__main__":
    main()
