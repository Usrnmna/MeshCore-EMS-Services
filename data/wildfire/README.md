# California-associated fire-weather zones

[Documentation index](../../docs/README.md) | [Terminal commands and all maintenance options](../../docs/CLI_REFERENCE.md).

`zones.geojson` preserves complete official NWS fire-weather polygons selected
by at least one hectare of overlap with California. Interstate portions are
retained. The October 20, 2026 snapshot contains 186 zones, including CAZ272
and NVZ420.

`manifest.json` records source URLs, retrieval time, SHA-256, feature count,
source dates and the selected IDs. Identical maintained source copies are
under both platform folders' `data/wildfire/` directories. Service installers
and standalone service ZIPs exclude those reference bytes; installed deployments
use the [independent wildfire data package](../../docs/DATA_PACKAGES.md).
Dynamic incident, perimeter, weather and context data belong to the ignored
runtime cache rather than this directory.

Rebuild from the repository root with `python tools/prepare_wildfire_data.py`.
This explicitly replaces the three maintained seed copies after validation.
NWS/NOAA and NIFC source attribution remains in the manifest and properties.

See the [wildfire commands, sources, interpretation and maintenance guide](../../meshcore_mqtt_service/WILDFIRE_GUIDE.md).
