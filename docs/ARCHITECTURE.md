# Service architecture and MQTT interface

This guide describes component responsibilities, connection settings, and message
handling for both platform packages. [Installation](../INSTALL.md) and the
[MeshCore user guide](../meshcore_mqtt_service/BOT_USER_GUIDE.md) cover initial setup
and channel use. The [documentation index](README.md) lists related references.

## Connection and reply flow

The following diagram describes the implemented service path. It does not establish
physical radio delivery. The bridge owns one companion connection; command programs
run on the attached computer.

```text
Remote MeshCore node
        | channel command over LoRa
        v
MeshCore Companion Node
        | one USB serial, BLE, or TCP connection
        v
service.py
    | decoded events, subject to channel export policy
    v
MQTT broker --> responder.py --> Dedicated scripts/*.py --> Provider API or local GIS
    |                |                    ^                          |
    |                |                    +------ lookup data -------+
    |                | tagged reply through serialized bridge command path
    |                v
    |           service.py --> Companion Node --> Originating MeshCore channel
    |
    +--> Permitted external subscribers
```

The responder receives channel events through MQTT, selects an allowed command,
and returns tagged reply parts through the bridge to the originating channel.
The broker may be bundled locally or configured externally. The flood monitor
runs within the responder and owns persistent subscriptions; a standalone lookup
cannot enroll one. See [monitoring behavior](../meshcore_mqtt_service/COMMAND_REFERENCE.md#cmd-floodalarm).

## Included programs and services

Both platform packages contain the same service components:

| Component | File | Purpose |
| --- | --- | --- |
| MeshCore/MQTT bridge | `service.py` | Owns the selected serial, BLE, or TCP connection, publishes radio events, accepts restricted MQTT commands, and manages the durable event outbox. |
| Channel registry/setup | `channels.py`, `channel_setup.py` | Validates program assignments, verifies radio identities, controls MQTT export, and explicitly provisions empty slots. |
| Channel responder | `responder.py` | Validates channel commands, records requests, runs approved scripts, and sends rate-limited replies to the requesting channel. |
| Flood monitor | `flood_alarm.py` | Stores subscriptions, schedules checks, compares alert types, and expires monitoring after four hours. |
| Installed service runner | `service_runner.py` | Runs unattended with a configured serial, BLE, or TCP connection, external settings, persistent state, and rotating logs. |
| Air quality lookup | `scripts/airnow_aqi.py` | Finds the nearest AirNow PM2.5 monitor and formats current AQI information. |
| Highway lookup | `scripts/highway_info.py` | Retrieves and compacts active Caltrans highway restrictions. |
| River lookup | `scripts/nearby_river_stations.py` | Finds nearby CDEC river-stage stations using NOAA station coordinates. |
| UV lookup | `scripts/uv_index.py` | Resolves coordinates, ZIP codes, or city/state text and reports the current UV index. |
| Lightning lookup | `scripts/lightning.py` | NWS lightning potential over the next 24h, with chance levels and adjustable display timezone. |
| Heat-alert lookup | `scripts/heat_adv.py` | Reports each active NWS extreme heat warning, watch, and heat advisory for a US location. |
| Flood-alert lookup | `scripts/flood_warn.py` | Resolves a US location and summarizes active NWS flash-flood warnings, flood warnings, advisories, and watches. |
| Snowpack lookup | `scripts/snowpack.py` | Nearest CDEC hourly snow depth, NWS next-24h snowfall, station name, and distance. |
| GIS command programs | `scripts/trail.py`, `rec.py`, `peak.py`, `park.py`, `boundary.py` | Dedicated offline entry points for trail, recreation, peak, park, and boundary queries. |
| GIS helpers | `scripts/gis_lookup.py`, `gis_data.py`, `gis_spatial.py` | Shared reply formatting, verified snapshot loading, and projected geometry. |
| Flood-alarm program | `scripts/floodalarm.py` | Structured readings for the persistent service monitor; standalone execution does not enroll subscriptions. |
| GIS settings | `gis_settings.json` | Data path, radius, projection, result count, and reply limits for local queries. |
| Shared data maintenance | `data/ebmud/refresh_geojson.py`, `repair_geojson.py` (workspace root) | Manually verify complete raw downloads or repair invalid polygons with original-byte provenance. |
| Local utilities | `scripts/status.py`, `scripts/time_now.py` | Report service status and current time in the shared timezone. |
| Configuration | `config.json` | Defines MQTT settings, channel registry, program assignments, commands, timeouts, cooldowns, and reply limits. |

## Default platform settings

| Setting | Linux folder | Windows folder |
| --- | --- | --- |
| MQTT address | `127.0.0.1:1883` | `127.0.0.1:1884` |
| Topic prefix | `meshcore/usb` | `meshcore/windows` |
| MQTT client ID | `meshcore-usb-bridge` | `meshcore-windows-bridge` |
| Python environment | `.venv-linux/` | `.venv/` |
| Runtime database | `runtime/bridge.sqlite3` | `runtime/bridge.sqlite3` |
| Default channel | `#autatestbot` | `#autatestbot` |
| Serial port selection | `auto` | `auto` |
| Serial speed | 115200 baud | 115200 baud |
| Reply timezone (`responder.timezone`) | `America/Los_Angeles` | `America/Los_Angeles` |
| GIS data path (relative to GIS settings file) | `../data/ebmud` | `../data/ebmud` |

Edit the appropriate folder's `config.json` to change channel definitions, program assignments, broker, topics, timeouts, cooldowns, reply limits, or command definitions. Restart the service after changing its configuration.

## MQTT interface

The service can be used as a MeshCore-to-MQTT bridge even when the automatic responder is disabled.

| Topic suffix | Purpose |
| --- | --- |
| `events/<event_name>` | Channel events permitted by `mqtt_export` and allowed node/device telemetry; raw/unclassified and unknown-channel traffic is suppressed with a registry. |
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

Long replies are split into four 150-byte messages by default. Per-command limits
allow 12 parts for flood alerts, 64 for lightning, and six for GIS; GIS command
output also has a default 480-byte UTF-8 limit before sender tags. See the
[command limits](../meshcore_mqtt_service/COMMAND_REFERENCE.md) for truncation and
reply behavior.

The service records requests before execution so sender names and request state survive restarts. It ignores duplicate, stale, future-dated, malformed, self-originated, and reply-like messages. Interrupted scripts and failed radio sends are recorded without automatic retransmission because execution or transmission may already have occurred.

A `sent` result means the local Companion Node accepted the message for transmission. It does not confirm reception by a remote node. Weather, air-quality, river, and highway reports are informational source data; the service does not replace official emergency alert delivery. `!floodwarn` summarizes active official NWS alerts at the resolved point.

## Transport configuration

USB serial autodetection is the default. One supported USB serial candidate must
be present, or `serial_port` must identify the intended device explicitly. BLE
requires operating-system pairing and a configured address. TCP requires a node
that exposes the MeshCore companion protocol; its default port is 5000. Only one
transport is active at a time.

The [Linux connection settings](../meshcore_mqtt_service/README.md#radio-connection-settings)
and [Windows connection settings](../meshcore_mqtt_service_windows/README.md#radio-connection-settings)
cover configuration examples, timeouts, Bluetooth permissions, service-account
requirements, trusted-network constraints, metadata, and recovery behavior.


## Wildfire data flow

The existing service session owns one wildfire refresh worker shared by channel
responders. Bounded child processes acquire source snapshots into
`runtime/wildfire.sqlite3`; independent dedicated programs query this cache.
`wildfire_service.py` stores subscriptions in the existing bridge database and
uses the shared guarded radio queue. No additional OS deployment unit is created.
The bundled full-zone seed initializes geographic coverage. The
[wildfire guide](../meshcore_mqtt_service/WILDFIRE_GUIDE.md#refresh-and-storage)
describes source separation, intervals, provenance, outage handling and the data-flow diagram.

Point commands `smoke.py` and `firedanger.py` use the same worker/cache. Full HMS
geometry and national NFDRS station summaries are independently refreshed;
optional FEMS fuel moisture uses service-account credentials and configured
station IDs. No additional service or subscription owner is introduced.

## California and Nevada landslide commands

Three dedicated programs share California/Nevada boundary and station catalog loading and NWS
point-alert parsing. `landslide_service.py` runs subscription checks within the
existing responder; no OS service is added. Point snapshots are cached on demand
in `runtime/landslide.sqlite3`; subscriptions persist in the existing bridge
SQLite database. Station metadata is bundled and checksummed. The shared
ZIP/city/GPS resolver supplies points; wildfire-zone geography is not used.
[Alert interpretation and lifecycle](../meshcore_mqtt_service/LANDSLIDE_GUIDE.md).
