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

Reference collections are installed independently of service binaries. A shared
`datasets.json` registry selects immutable per-collection generations. Acquisition,
validation and index construction occur in an unpublished candidate; only a
complete candidate can replace the registry selection. Previous directories and
dependency-pinned generations remain available. No dataset updater owns service
subscriptions or adds a scheduler. See [dataset lifecycle and recovery](DATA_PACKAGES.md).

Both platform packages contain the same service components:

| Component | File | Purpose |
| --- | --- | --- |
| MeshCore/MQTT bridge | `service.py` | Owns the selected serial, BLE, or TCP connection, publishes radio events, accepts restricted MQTT commands, and manages the durable event outbox. |
| Channel registry/setup | `channels.py`, `channel_setup.py` | Validates program assignments, verifies radio identities, controls MQTT export, and explicitly provisions empty slots. |
| Channel responder | `responder.py` | Validates channel commands, records requests, runs approved scripts, and sends rate-limited replies to the requesting channel. |
| Flood monitor | `flood_alarm.py` | Pins a verified location and categorical baseline, checks official alerts and optional conditions every five minutes, and expires subscriptions after four hours. |
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
| Water lookup programs | `scripts/waterway.py`, `basin.py`, `floodstatus.py` | Find named water features, basin context, supported current gauges, and source availability through the shared static index. |
| Wildfire programs and worker | Nine dedicated programs, `scripts/wildfire_refresh.py`, `wildfire_service.py` | Refresh shared source caches, query whole fire-weather zones or point smoke/fuel context, and manage guarded temporary subscriptions. |
| Landslide programs and monitor | `scripts/slidewarn.py`, `slidealarm.py`, `slideinfo.py`, `landslide_service.py` | Interpret relevant official point alerts, describe research-station metadata, and manage temporary California/Nevada subscriptions. |
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

Command replies contain one message of at most 150 UTF-8 bytes including the
sender tag. Primary warnings and uncertainty precede optional whole fields.
Details, paging and automatic continuations are unavailable. See the
[response policy and review inventory](../meshcore_mqtt_service/RESPONSE_FORMATTING.md).

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

## Location water status

Dedicated location entry points share `water_lookup`, `water_local` and
`water_sources`. A verified static spatial index references separately downloaded
statewide collections. Monitoring evaluates all supported upstream gauge links;
radio detail limits apply only to presentation. Online cache rows replace current values; subscription
baselines retain categorical state and official fingerprints, not level history.
The existing `flood_alarm.py` worker pins coordinates, verifies enrollment and
checks expiry/revision/channel guards before notifications. No new service is
introduced. [Source contracts and refresh](../meshcore_mqtt_service/WATER_GUIDE.md).

The water identifier review is a supplemental static relationship table, applied
at lookup time without changing inventory manifests or routing geometry.
`water_identifiers` corroborates unique NOAA catalog USGS IDs through the gauge
API. An explicit `water_refresh --noaa-identifiers` replaces the runtime review,
including unresolved results and source failures. See the
[NOAA station review](../meshcore_mqtt_service/WATER_STATION_REVIEW.md).

The sole agency-successor exception uses the documented
USGS-11462000 -> CDEC CDM -> NOAA YDMC1 chain. `water_agency_review` validates its
static source evidence during refresh; the live gauge reader enforces the reviewed
NOAA identity and checks that the current overlay still permits the link before
using cached data. The exception does not relax identity checks for other gauges.

The [NOAA map and operator-record audit](../meshcore_mqtt_service/WATER_STATION_REVIEW.md#further-map-and-operator-record-review)
retains static evidence for sixteen unresolved stations. Identifier refresh also
checks current map/candidate metadata; source failures and changed candidate
identities require review. These auxiliary records cannot authorize a link,
change routing or add historical readings. Existing exact and agency-successor
validation remains in effect.

The [source-access retry](../meshcore_mqtt_service/WATER_STATION_REVIEW.md#archived-source-and-onerain-access-retry)
recovered the USGS PDFs and OneRain inventory. Identifier refresh now checks the
public OneRain sites endpoint using transient cookies. Only static metadata is
retained; PDF evidence remains dated manual-review context, and no additional
station link or reading history is created.

`water_operator_records` supplies static local-agency evidence beneath the map
review. Its fixed manual-review dates and unresolved findings are distinct from
live retrieval outcomes. It has no network or observation-storage behavior and
cannot authorize or revoke a NOAA identity. Detailed citations and source
conflicts are in the [local-agency review](../meshcore_mqtt_service/WATER_STATION_REVIEW.md#additional-local-operating-agency-records).

`water_vertical_review` performs the separate live WAC/WAS interpretation-metadata
checks inside `water_identifiers.refresh`, including catalog-failure outcomes.
The five source checks compare allowlisted fields to a fixed manual baseline;
page hashes are provenance only. `water_refresh` prints changed fields and exits
1 after saving when metadata needs review. These auxiliary records cannot
supply identity or correction authority to `water_identifiers.apply` or reading
consumers. The same current review file is replaced without retaining measurement
history. See [automatic metadata checks](../meshcore_mqtt_service/WATER_STATION_REVIEW.md#automatic-wacwas-metadata-checks).

Flood-alarm delivery uses an in-memory per-channel notification queue inside
`FloodAlarms`. Its polling and delivery tasks share the existing service lifetime;
no new daemon or database table is introduced. Active notices sort by urgency,
severity, certainty and newest effective time. Each complete notification is
followed by a five-second minimum gap, while the existing shared radio limiter
remains authoritative. Guards after the radio wait validate source freshness,
alert version and subscription/channel state. Categorical baselines remain
persistent; pending notices are replaceable and are not replayed after restart
or uncertain sends. See [notification semantics](../meshcore_mqtt_service/WATER_GUIDE.md#independent-flood-alarm-notifications).
