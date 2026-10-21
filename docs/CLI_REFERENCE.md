# Terminal commands and maintenance options

Radio messages and terminal commands have separate interfaces. Radio replies are
one tagged message of at most 150 UTF-8 bytes. [Tagged examples](../meshcore_mqtt_service/RESPONSE_EXAMPLES.md)
and [conditional response fields](../meshcore_mqtt_service/RESPONSE_FORMATTING.md)
describe presentation; supported local JSON/snapshot modes retain structured data.

Radio and terminal invocations use different argument conventions. Radio replies are
one tagged message of at most 150 UTF-8 bytes. [Tagged examples](../meshcore_mqtt_service/RESPONSE_EXAMPLES.md)
and [conditional response fields](../meshcore_mqtt_service/RESPONSE_FORMATTING.md)
describe presentation; supported local JSON/snapshot modes retain structured data.

Radio and terminal invocations use different argument conventions. The paired
[radio command and subcommand reference](../meshcore_mqtt_service/COMMAND_REFERENCE.md#subcommand-index)
documents all 31 registered MeshCore commands. This guide lists operator,
maintenance, collection, and satellite interfaces. Library helpers without an
executable entry point are described in component function references.

Examples use the Linux package; the Windows package contains the same Python
programs. Use the interpreter belonging to the deployment. Commands in the next
two sections run from a platform package unless an example includes a root path.
`PATH`, `LOCATION`, `SOURCE`, and similar uppercase terms are placeholders.
Most argparse-based programs support `--help` without performing their action.
Manual location parsers instead accept the `help` query documented below.

## Service and channel operation

| Program or launcher | Commands and options | Behavior |
| --- | --- | --- |
| `bash Start-Service.sh` / `Start-Service.exe` | Continuous foreground operation; Windows `--check`, `--ports` | Starts the package launcher; requires its console to remain open. No boot service is installed by these launchers. |
| `bash setup.sh` / `setup.cmd` | No command-specific arguments | Prepares the platform virtual environment and pinned dependencies. |
| `bash run.sh MODE` / `run.cmd MODE` | `bridge`, `watch`, `ports`, `broker`, `cli TOKENS...` | Selects the corresponding `service.py` mode. `watch` consumes MQTT; `ports` enumerates interfaces; `broker` runs the local broker; `cli` connects to the node. |
| `python service.py` | `--config PATH`, `--environment PATH`, then one mode above | Configuration and restricted credentials precede the mode. `bridge` owns the selected serial/BLE/TCP connection; stop it before another process opens that node. |
| `python service_runner.py` | Required `--config PATH`, `--state-dir PATH`; optional `--environment PATH`, `--stop-file PATH`, `--check` | Installed-service entry point. `--check` validates settings and dependencies without opening the radio. |
| `python channel_setup.py` | Required `--config PATH`; optional `--environment PATH`; `list`, `check`, or `provision CHANNEL_ID` | `list` and `check` inspect the radio. Only explicit `provision` writes an empty channel slot after validation. Stop the bridge first. |
| `python check_live.py` | No options | Opens the configured radio and an isolated loopback MQTT broker for a read-only device query. This is a hardware diagnostic, not an offline test. |
| `bash verify.sh` / `verify.cmd` | No command-specific arguments | Runs package `tests/` and dependency checks using the package environment. |

The [multi-channel guide](../meshcore_mqtt_service/MULTI_CHANNEL_GUIDE.md) covers
private-key environment variables, channel identity, external Python programs,
upgrade preservation, and installed paths. MQTT command JSON is a separate
[integration interface](ARCHITECTURE.md#mqtt-interface), not a radio subcommand.

## Dedicated lookup programs

| Program family in `scripts/` | Arguments and options | Notes |
| --- | --- | --- |
| `status.py`, `time_now.py` | No arguments | Local responder text or the configured reply timezone. |
| `airnow_aqi.py` | `LATITUDE LONGITUDE` | `AIRNOW_API_KEY` is required. |
| `highway_info.py` | `[ROUTE_NUMBER]` | Integer 1-999; omitted route invokes a terminal input prompt. |
| `nearby_river_stations.py` | `--latitude`, `--longitude`, `--radius`, `--timeout`, `--mesh-text` | Radius is miles and timeout is seconds. Default output is structured JSON; `--mesh-text` requests a compact reply. |
| `uv_index.py`, `heat_adv.py`, `snowpack.py` | `LOCATION` | Coordinates or supported place/ZIP formats; snowpack is California-only. |
| `lightning.py` | `[--timezone IANA_ZONE] LOCATION` | A leading standalone timezone override is supported; service requests use the shared responder setting. |
| `trail.py`, `rec.py`, `peak.py`, `park.py`, `boundary.py` | `[--settings PATH] QUERY...` | The radio query grammar without the `!COMMAND` word. `help` or an empty query lists syntax. |
| `gis_lookup.py` compatibility interface | `--kind {trail,rec,peak,park,boundary} --query QUERY [--settings PATH]` | Shared helper CLI; shipped radio registrations use dedicated programs. |
| `firezone.py`, `fires.py`, `fire.py`, `firewx.py`, `firewarn.py`, `firedata.py`, `firealarm.py` | `--json`, `--db PATH`, `--refresh`, then `QUERY...` | Reads cached wildfire products. Explicit `--refresh` performs bounded acquisition. `--monitor` is supported only by `firealarm.py` and emits its compact service snapshot. |
| `smoke.py`, `firedanger.py` | `--json`, `--db PATH`, `--refresh`, then `LOCATION` | Point smoke or ERC/fuel context; no zone-ID or paging input. |
| `slidewarn.py`, `slideinfo.py`, `slidealarm.py` | `--json` or `--snapshot`, then `QUERY...`; `help` / `--help` | California/Nevada queries; `slideinfo` also accepts `near LOCATION`. Alarm controls use `on`, `status`, and `off`. |
| `waterway.py`, `basin.py`, `floodstatus.py`, `flood_warn.py`, `floodalarm.py` | `--json` or `--snapshot`, then `QUERY...`; `help` / `--help` | Water locations must resolve unambiguously. Alarm queries include `conditions LOCATION`, `status`, and `stop`. |

Standalone alarm execution produces a lookup or structured snapshot. It cannot
create, renew, stop, or inspect a persistent service subscription. Those controls
must arrive through the running service on an assigned channel. JSON responses
can contain an explicit error even when the program exits successfully; exit
status alone is not a successful-data assertion.

## Runtime data maintenance

| Program | Options | Effect |
| --- | --- | --- |
| `scripts/wildfire_refresh.py` | `--db PATH`, repeatable `--source SOURCE`, `--force`, `--status`, `--export SOURCE` | Refresh due sources by default. `--force` bypasses due timing; `--status` inspects source status; `--export` writes cached GeoJSON. Status/export do not perform provider acquisition. |
| `scripts/water_refresh.py` | `--index`, `--noaa-identifiers`, `--data-directory PATH` | At least one action is required; both can be combined. Build the separate static index or recheck the supplemental NOAA/agency/map/vertical-identity evidence. `--data-directory` selects index inputs, not the runtime review destination. |
| `python tools/prepare_wildfire_data.py` from repository root | No options | Acquires California and intersecting whole-zone boundaries and mirrors the reviewed, checksummed seed into both packages. |

Wildfire explicit source names include `zones`, `egp`, `incidents`, `perimeters`,
`alerts`, `hms`, `nfdrs`, configured `fems`, office-specific `fwf:OFFICE`, and all
twelve [supplementary categories](../meshcore_mqtt_service/WILDFIRE_GUIDE.md#sources-and-supplementary-categories).
`fems` requires configured station IDs and credentials. A source must be present
in the current refresh job set; invalid names fail. Repeated `--source` selects
several products. Radio requests do not accept these refresh flags.

The [water setup sequence](WATER_DATA_SETUP.md) explains collection dependencies,
index schema, on-demand caches, current-only readings, explicit access failures,
and the absence of an installed statewide download schedule.

## Offline reference collections

Run these commands from the repository root. Refresh commands can download large
datasets and write generation state. Verification, reporting, and offline rebuild
commands require their documented local inputs. Downloaded water collections are
excluded from Git and installer payloads.

| Command | Complete option set | Purpose and detail |
| --- | --- | --- |
| `python data/ebmud/refresh_geojson.py` | `--check` | Verify all downloads; omit `--check` to replace local snapshots. [Refresh and repair](../data/ebmud/README.md#manual-refresh). |
| `python data/ebmud/repair_geojson.py` | No options | Derive valid local polygons while preserving affected source bytes and provenance. |
| `python data/california_state_parks/reference.py` | No options | Verify manifest-indexed files and load all eleven dataset types without network access. [Collection guide](../data/california_state_parks/README.md). |
| `python data/basin_plans/refresh.py` | `--directory PATH`, `--resume ID`, `--workers {1,2,3,4}` | Acquire or resume the statewide collection and organized review generations. [Basin Plan acquisition](../data/basin_plans/README.md#acquire-or-update-the-complete-collection). |
| `python data/basin_plans/reference.py` | `--directory PATH`, `--records` | Verify local collection files; `--records` also verifies archived record IDs. |
| `python data/basin_plans/organize.py` | `--directory PATH`, `--verify` | Build regional review organization or verify the existing generation. |
| `python data/basin_plans/native_inventory.py` | `--directory PATH` | Inventory preserved native downloads and source fields. |
| `python data/basin_plans/names.py QUERY` | `--directory`, `--exact`, `--region`, `--category`, `--name-field`, `--limit`, `--records`, `--links`, `--direction {both,children,parents}` | Search source names and published parent/tributary associations. `--limit 0` displays all catalog matches; `--records` emits every matched original record as JSON Lines. [Relationships](../data/basin_plans/RELATIONSHIPS.md). |
| `python data/flood_impacts/refresh.py` | `--directory`, `--config`, `--basin-directory`, `--mode {all,static,observations}`, `--offline` | Build the Russian River pilot or refresh its separate static and observation evidence; `--offline` rebuilds static outputs from verified cache. [Pilot refresh](../data/flood_impacts/README.md#refresh-and-offline-rebuild). |
| `python data/flood_impacts/report.py` | `--directory`, `--gauge`, `--scenario`, `--at`, `--verify`, `--output` | Report current reference evidence or an explicitly hypothetical static scenario. `--at` selects an ISO UTC evaluation time. |
| `python data/flood_impacts/validate.py` | `--directory`, `--output` | Independently verify the pilot's relationships, geometry, and retained evidence. |
| `python -m data.usgs_water.refresh` | `--directory`, `--mode`, `--basin-directory`, `--flood-directory`, `--resume`, `--reuse-routing-sources` | Refresh current values or a selected metadata/review generation. Modes are listed below. [USGS refresh](../data/usgs_water/README.md#refresh). |
| `python -m data.usgs_water.report` | `--directory`, either `--station ID` or `--name TEXT`, `--output` | Inspect exact agency-qualified station IDs or matching source names. |
| `python -m data.usgs_water.validate` | `--directory`, `--flood-directory`, `--output` | Verify inventory, latest observations, and flood-pilot integration. |
| `python -m data.usgs_water.validate_routing` | `--directory`, `--output` | Verify source-directed downstream paths and CalWater relationships. |
| `python -m data.usgs_water.validate_link_review` | `--directory`, `--output` | Verify supplemental station-link review decisions. |
| `python -m data.usgs_water.validate_agency_review` | `--directory`, `--output` | Verify original-agency evidence and supported static addresses. |
| `python -m data.usgs_water.validate_local_review` | `--directory`, `--output` | Verify local operating-agency metadata decisions. |
| `python -m data.usgs_water.audit_source_rules` | `--directory`, `--rules`, `--output` | Audit curated source-rule evidence with reproducible diagnostics. [Audit procedure](../data/usgs_water/SOURCE_RULE_AUDIT.md). |

USGS refresh modes are `all`, `inventory`, `observations`, `network`,
`link-review`, `agency-review`, `local-review`, and `routing`. `--resume` selects
a pending directory and requires one specific mode. `--reuse-routing-sources`
rebuilds routing from matching verified geometry and intersections. Observation
refresh keeps one latest value per returned time series and replaces the prior
snapshot; it does not create a reading history. The independent flood pilot has
separate observed/forecast source evidence and retention rules.

## Satellite catalog

Run `python satellite_database/satellite_db.py [--settings PATH] SUBCOMMAND`.
Global settings precede the subcommand. These are local catalog tools and have
no registered MeshCore command.

| Subcommand | Options or positional inputs | Result |
| --- | --- | --- |
| `refresh` | `--offline`, `--no-celestrak`, `--overrides PATH` | Merge and export the catalog from provider responses or verified caches. |
| `list` | `--satellite`, `--scope`, `--status {active,inactive,scheduled_off,unknown}`, `--json` | Query supported operations and current evidence freshness. |
| `show` | `SATELLITE` | Display all stored capabilities and evidence for one match. |
| `summary` | None | Report coverage, source timestamps, classification warnings, and errors. |
| `export` | None | Regenerate JSON/CSV snapshots without network acquisition. |
| `import-observations` | `FILE` | Add dated evidence for already supported capabilities. |
| `position` | `SATELLITE LATITUDE LONGITUDE`, `--altitude METRES`, `--at ISO_UTC` | Use stored orbital elements and optional Skyfield for observer pointing. |

[Satellite scope, source licenses, and status interpretation](../satellite_database/README.md)
distinguish catalog evidence from real-time transmission or reception.

## Installer, packaging, and documentation tools

| Command | Options | Effect |
| --- | --- | --- |
| `python tools/package_services.py` | No options | Verify shared-package parity and build both standalone ZIPs with SHA-256 files. |
| `python tools/build_installers.py` | `--iscc PATH`, `--linux-only` | Build current-version OS installers; neither installs nor publishes them. |
| `python installers/configure.py` | Required `--root`, `--state`, `--config-dir`, `--platform {windows,linux}`; optional `--port`, `--transport {serial,ble,tcp}`, `--tcp-host`, `--tcp-port`, `--ble-address`, `--channel`, `--channels-config` | Merge installed settings, preserve operator state, and create backups without opening a radio or starting a service. |
| `python tools/check_documentation.py` | No options | Check source command/subcommand and tagged-example coverage, exact response byte counts, local links, badge counts, paired reference parity, and publication exclusions. |

The [installation guide](../INSTALL.md) lists Windows installer parameters,
Linux installer options, extraction/check modes, uninstall behavior, preservation,
credentials, and target-build requirements. The [development guide](DEVELOPMENT.md)
defines local and GitHub offline checks and their evidence boundaries.
