# MC-EMS-Services

Python services that connect an MQTT broker to a USB MeshCore Companion Node and deliver concise, useful local weather, environmental, river, and highway information over a MeshCore channel.

## OS service installers

Online installation packages support Windows x64,
Raspberry Pi ARM64, and Linux x86_64. They install Python/dependencies automatically,
include the complete workspace and reference data, and run with a saved serial port
under Windows Services or systemd. See the [installation guide](INSTALL.md).

Source-folder launchers support interactive operation.

## About

MC-EMS-Services turns a MeshCore channel into a small command-driven information service. A user sends a supported command on the configured channel, the attached computer runs the matching Python lookup, and the result is returned to the same channel with the sender's name.

```text
MeshCore user
    ↓ command over LoRa
USB Companion Node
    ↓ serial connection
Linux or Windows service
    ├─ runs the requested local Python program
    ├─ publishes radio events and commands through MQTT
    └─ sends a concise reply back to the same MeshCore channel
```

The default channel is `#autatestbot`. The channel must already exist on the Companion Node.

## Included service folders

| Folder | Platform | Purpose |
| --- | --- | --- |
| [`meshcore_mqtt_service/`](meshcore_mqtt_service/README.md) | Linux | Linux launcher, local MQTT broker, MeshCore bridge, command responder, lookup scripts, configuration, and tests. |
| [`meshcore_mqtt_service_windows/`](meshcore_mqtt_service_windows/README.md) | Windows x64 | Independent Windows package with its own settings, runtime data, setup scripts, tests, and double-click launcher. |
| [`satellite_database/`](satellite_database/README.md) | Standalone Python, Windows/Linux | Builds a sourced SQLite satellite radio catalog with capability-level status, retirement exclusions, orbital elements, and JSON/CSV exports in [`data/satellites/`](data/satellites/README.md). |

The Linux and Windows folders are self-contained. Each uses its own virtual environment, configuration, MQTT namespace, and SQLite request database.

## Workspace organization

| Location | Contents |
| --- | --- |
| `meshcore_mqtt_service/` | Linux service, shell launchers, command scripts, and `tests/`. |
| `meshcore_mqtt_service_windows/` | Windows service, Windows launchers, command scripts, and `tests/`. |
| `satellite_database/` | Independent satellite catalog program, settings, schema, and tests. |
| `data/` | EBMUD reference layers and satellite database, exports, and offline source cache. |
| [`tools/package_services.py`](tools/package_services.py) | Builds both distribution ZIPs from current source and checks shared-code parity. |
| `dist/` | Generated installation ZIPs; rebuild after source changes. |
| [`archive/`](archive/README.md) | Local historical recovery backups, excluded from version control. |

The service folders are the maintained installation sources. Shared command code
is deliberately present in both so either package can run independently. Update
both copies together; retain platform-specific serial selection and MQTT defaults.
When copies differ, compare contents and modification history and reconcile the
newer implementation before packaging. The packager rejects divergent shared code.

The highway lookup runs directly from either service package without starting
MQTT or the radio:

```console
python meshcore_mqtt_service/scripts/highway_info.py 80
```

Windows setup creates `.venv/` in the Windows service folder; Linux setup creates
`.venv-linux/` in the Linux folder. Shared reference data lives under `data/`.

Build fresh packages from the workspace root with:

```console
python tools/package_services.py
```

This replaces the two ZIPs under `dist/` and excludes environments, runtime state,
bytecode, and historical backups. The ZIPs include their own tests and documentation.

## Local GIS reference data

The project includes raw EBMUD GeoJSON snapshots in [`data/ebmud/`](data/ebmud/README.md):

- [`trails.geojson`](data/ebmud/trails.geojson): trail geometry and attributes.
- [`recreation_points.geojson`](data/ebmud/recreation_points.geojson): recreation locations and amenities.
- [`trail_endpoints.geojson`](data/ebmud/trail_endpoints.geojson): trail start/end markers.
- [`peaks.geojson`](data/ebmud/peaks.geojson): mountain peak locations and elevations.
- [`additional_trails.geojson`](data/ebmud/additional_trails.geojson): additional trail linework and attributes.
- [`boundaries/`](data/ebmud/README.md): seven GeoJSON layers covering reservoir annotations, reservoirs, recreation areas, watershed boundaries, and regional/local parks, plus raw boundary service metadata.
- [`sources.json`](data/ebmud/sources.json): source URLs, download times, counts, and checksums.

Programs can read these shared files locally without network requests. See the
[data instructions](data/ebmud/README.md) for Python loading examples and path
settings for either platform package. These are manual snapshots;
the MeshCore commands do not read them.
The instructions also explain the map-only annotation sublayer and one
preserved annotation record with null geometry.

## Included programs and services

Both platform packages contain the same service components:

| Component | File | Purpose |
| --- | --- | --- |
| MeshCore/MQTT bridge | `service.py` | Owns the selected USB serial connection, publishes radio events, accepts restricted MQTT commands, and manages the durable event outbox. |
| Channel responder | `responder.py` | Validates channel commands, records requests, runs approved scripts, and sends rate-limited replies to the requesting channel. |
| Flood monitor | `flood_alarm.py` | Stores subscriptions, schedules checks, compares alert types, and expires monitoring after four hours. |
| Installed service runner | `service_runner.py` | Runs unattended with a saved serial port, external settings, persistent state, and rotating logs. |
| Air quality lookup | `scripts/airnow_aqi.py` | Finds the nearest AirNow PM2.5 monitor and formats current AQI information. |
| Highway lookup | `scripts/highway_info.py` | Retrieves and compacts active Caltrans highway restrictions. |
| River lookup | `scripts/nearby_river_stations.py` | Finds nearby CDEC river-stage stations using NOAA station coordinates. |
| UV lookup | `scripts/uv_index.py` | Resolves coordinates, ZIP codes, or city/state text and reports the current UV index. |
| Flood-alert lookup | `scripts/flood_warn.py` | Resolves a US location and summarizes active NWS flash-flood warnings, flood warnings, advisories, and watches. |
| Snowpack lookup | `scripts/snowpack.py` | Nearest CDEC hourly snow depth, NWS next-24h snowfall, station name, and distance. |
| Local utilities | `scripts/status.py`, `scripts/time_now.py` | Report service status and current UTC time. |
| Configuration | `config.json` | Defines MQTT settings, the radio channel, commands, timeouts, cooldowns, and reply limits. |

## MeshCore commands

Send commands from another MeshCore node on `#autatestbot`.

| Command | Example | Result | Data source |
| --- | --- | --- | --- |
| `!status` | `!status` | Confirms that the local command service is running. | Local service |
| `!time` | `!time` | Returns the current UTC time. | Local system |
| `!aqi` | `!aqi 37.7749 -122.4194` | Nearest-monitor PM2.5 AQI, concentration, rating, station, distance, and observation time. | AirNow |
| `!traffic` | `!traffic 80` | Compact active California highway restrictions for route 1–999. | Caltrans |
| `!rivers` | `!rivers 39.0000, -121.0000` | Nearby river stations within 15 miles, including stage, report time, action stage, and flood stage. | CDEC and NOAA |
| `!uv` | `!uv Sacramento` | Current UV index and risk level for coordinates, a US ZIP code, or a city and state. | CurrentUVIndex.com plus location lookup |
| `!floodwarn` | `!floodwarn Sacramento` | Active flash flood warnings, flood warnings, advisories, and watches with colored squares. | NWS API, the alert source used by FlashFloodWarn |
| `!floodalarm` | `!floodalarm Sacramento` | Acknowledges immediately; checks every 20 minutes and reports changes for up to four hours. | Same NWS flood source |
| `!snowpack` | `!snowpack Truckee` | Snow depth and next-24h snowfall in inches, with nearest station and miles. Accepts California GPS, ZIP, or city. | CDEC and NWS |

Examples of accepted UV and flood-alert locations include `!uv 95814`, `!uv Reno NV`, and `!uv 38.5816, -121.4944`. The same locations work with `!floodwarn`. City names without a state default to California.

AQI lookups require an `AIRNOW_API_KEY` environment variable. Traffic, river, status, time, UV, flood-alert, and snowpack commands do not require an API key. Internet access is required for all external data lookups.

## Main features

- USB serial connection to a MeshCore Companion Node through the interactive `-S` device selector.
- Bundled local MQTT broker for operation without a separate broker installation.
- Optional external MQTT broker with username/password environment variables and TLS support.
- Radio events published as structured MQTT messages with available text, channel, timestamps, RSSI, SNR, paths, and other metadata.
- Same-channel replies prefixed with the saved sender name, such as `@Alice`.
- Exact command matching, validated arguments, fixed script paths, execution timeouts, and no shell interpretation of received text.
- Persistent SQLite request history, duplicate suppression, stale-message rejection, sender cooldowns, and bounded request queues.
- Durable QoS 1 MQTT event outbox with automatic reconnection.
- Long replies divided into as many as four 150-byte messages by default; `!floodwarn` and `!floodalarm` allow 12 so all four alert descriptions fit.
- Separate Linux and Windows MQTT ports and topic namespaces, allowing both copies to coexist on one network.

## Quick start

### Linux

Requirements: Python 3.11 or newer, virtual-environment support, and permission to access the USB serial device.

```bash
cd meshcore_mqtt_service
export AIRNOW_API_KEY="YOUR_AIRNOW_API_KEY"  # only needed for !aqi
bash Start-Service.sh
```

Choose the attached `/dev/ttyACM*` or `/dev/ttyUSB*` device when prompted. Keep the terminal open while the service is running. If access is denied, add the user to the serial-device group used by the Linux distribution, commonly `dialout`, then sign in again.

See the [Linux service README](meshcore_mqtt_service/README.md) for setup, operating modes, command details, and verification instructions.

### Windows x64

Requirements: 64-bit Python 3.11 or newer and a USB-connected MeshCore Companion Node.

1. Open the [Windows service folder instructions](meshcore_mqtt_service_windows/README.md).
2. Run `setup.cmd` once on a new computer.
3. Double-click `Start-Service.exe`.
4. Select the attached COM device in the MeshCore `-S` selector.
5. Keep the console window open while the service is running.

Set `AIRNOW_API_KEY` before starting the service if `!aqi` will be used. The interactive launcher prompts for a COM port with the default configuration, and administrator permission is normally unnecessary.

See the [Windows service README](meshcore_mqtt_service_windows/README.md) for complete setup and diagnostic instructions.

## Default platform settings

| Setting | Linux folder | Windows folder |
| --- | --- | --- |
| MQTT address | `127.0.0.1:1883` | `127.0.0.1:1884` |
| Topic prefix | `meshcore/usb` | `meshcore/windows` |
| MQTT client ID | `meshcore-usb-bridge` | `meshcore-windows-bridge` |
| Python environment | `.venv-linux/` | `.venv/` |
| Runtime database | `runtime/bridge.sqlite3` | `runtime/bridge.sqlite3` |
| Default channel | `#autatestbot` | `#autatestbot` |
| Serial speed | 115200 baud | 115200 baud |

Edit the appropriate folder's `config.json` to change the channel, broker, topics, timeouts, cooldowns, reply limits, or command definitions. Restart the service after changing its configuration.

## MQTT interface

The service can be used as a MeshCore-to-MQTT bridge even when the automatic responder is disabled.

| Topic suffix | Purpose |
| --- | --- |
| `events/<event_name>` | Radio events and available packet metadata. |
| `events/bot_reply` | Records an automatic reply accepted by the local radio. |
| `command` | Accepts non-retained JSON MeshCore CLI requests. |
| `results/<id>` | Returns MQTT command output and status. |
| `errors` | Reports rejected MQTT commands. |
| `status` | Retained online/offline state and last will. |

Supported MQTT commands include `infos`, `ver`, `contacts`, `self_telemetry`, `clock`, `msg`, and `chan`.

Example request:

```json
{"id":"info-001","argv":["infos"]}
```

Use a unique request ID for every intentional command. Restrict publishing access to the command topic when an external broker is used.

## Reliability and message handling

The service records requests before execution so sender names and request state survive restarts. It ignores duplicate, stale, future-dated, malformed, self-originated, and reply-like messages. Interrupted scripts and failed radio sends are recorded without automatic retransmission because execution or transmission may already have occurred.

A `sent` result means the local Companion Node accepted the message for transmission. It does not confirm reception by a remote node. Weather, air-quality, river, and highway reports are informational source data; the service does not replace official emergency alert delivery. `!floodwarn` summarizes active official NWS alerts at the resolved point.

## Development and verification

Run `bash verify.sh` from the Linux service folder after setup, or `verify.cmd`
from the Windows service folder. Both discover all tests in `tests/` automatically.
Run the satellite suite with `python -m unittest discover -s satellite_database`
from the workspace root.

Both service folders include tests for:

- Command parsing and input validation.
- Script execution, timeouts, failures, and output limits.
- Sender retention and same-channel tagged replies.
- Duplicate suppression and persistent request state.
- AQI, traffic, river, UV, flood-alert, and snowpack formatting with sample source responses.
- A real loopback MQTT broker with simulated radio events.
- Flood-alarm timing, expiry, renewal, background workers, and restart persistence.
- Installed service configuration and unattended startup behavior.

Automated tests use sample provider data and simulated radio events. They do not
establish physical radio delivery, live four-hour monitoring, or installation and
reboot behavior on target hardware. Follow the platform README for optional
USB/MQTT diagnostics and the [installer validation guide](installers/VALIDATION.md)
for installation checks.

## Dependencies

The service packages use MeshCore CLI, MeshCore, Paho MQTT, pyserial, and aMQTT.
Dependency pins are maintained in the [Linux requirements](meshcore_mqtt_service/requirements.txt)
and [Windows requirements](meshcore_mqtt_service_windows/requirements.txt).

Do not commit API keys, MQTT passwords, virtual environments, runtime databases, or generated cache files to a public repository.

See the platform READMEs for `!floodwarn` examples, exact reply wording, data sources, and location coverage. Restart the service after configuration changes.

## Snowpack command

Both packages support `!snowpack`. Examples: `!snowpack 39.3279, -120.1833`,
`!snowpack 96161`, or `!snowpack Truckee`. The reply format is:

```text
@Alice Snowpack: Current: 12in | Next 24h: 4in | Station: Snow Creek 2.3mi.
```

Values above are illustrative. Current depth is measured at the nearest active
CDEC hourly snow-depth station; snowfall is the NWS forecast at the requested
location for the next rolling 24 hours. Forecast boundary intervals are prorated.
Missing/stale data is shown as `unavailable`, and a valid zero is `0in`.

See the [Linux snowpack details](meshcore_mqtt_service/README.md#snowpack-snowpack)
or [Windows snowpack details](meshcore_mqtt_service_windows/README.md#snowpack-snowpack)
for sources, freshness rules, and limitations.
The Windows and Linux ZIP archives under `dist/` are built from the current service folders.
They contain source, launchers, setup scripts, tests, and documentation; local Python
environments, runtime databases, and bytecode caches are excluded. Run the included
setup/launcher after extraction to install the pinned dependencies.

## Flood alarm subscriptions

`!floodalarm` accepts the same city, state, ZIP, and GPS inputs as `!floodwarn`.
Its immediate acknowledgment is `@Alice Flood Alarm is set for requested location.`
Only `!floodalarm` starts monitoring. The service then saves a silent baseline,
checks every 20 minutes, and sends tagged same-channel replies when the flood-alert
types change, including when they clear. Configured radio spacing applies.

Monitoring stops four hours after the sender's last accepted `!floodalarm` call.
Each new accepted `!floodalarm` overwrites that user's previous location and resets
the full four-hour limit. `!floodwarn` is a one-shot lookup and never modifies
an alarm or its timer. Other commands do not renew the timer.
Subscriptions persist in each package's `runtime/bridge.sqlite3`; restarting does
not extend the deadline. The service must be running to check and send.

See the [Linux code guide](meshcore_mqtt_service/README.md#where-to-adjust-the-algorithm)
or [Windows code guide](meshcore_mqtt_service_windows/README.md#where-to-adjust-the-algorithm)
for the commented algorithm, timing constants, database fields, and error behavior.
