# MeshCore channel command service

Radio replies use one tagged message, with no details or paging. See the
[response policy and manual review inventory](RESPONSE_FORMATTING.md).

Detailed guides: [Water and flood](WATER_GUIDE.md) | [Wildfire and smoke](WILDFIRE_GUIDE.md) | [Landslides](LANDSLIDE_GUIDE.md).

Reply examples: [All commands and subcommands](RESPONSE_EXAMPLES.md) · [Response policy and conditional fields](RESPONSE_FORMATTING.md).

Documentation: [MeshCore user guide](BOT_USER_GUIDE.md) | [Detailed command reference](COMMAND_REFERENCE.md) | [Function implementation reference](FUNCTION_REFERENCE.md).

Messages on **#autatestbot** run preset local Python scripts and automatically return
stdout to the same channel, starting with **@SENDERSUSERNAME**.

Example:

```text
Alice sends on #autatestbot: !status
Service runs: scripts/status.py
Service replies on #autatestbot: @Alice Local command service is running.
```

The Linux computer running the service executes the scripts. The installed MeshCore
SDK owns one serial, BLE, or TCP connection selected in config.json. Replies use the
CLI channel-send helper on that same connection. MQTT commands and automatic replies share a
serialized, rate-limited command path. Radio events also publish to MQTT.

## OS service installers

Current distribution version: `v0.9.6-beta`.

Online installation packages support Windows x64,
Raspberry Pi ARM64, and Linux x86_64. They install Python/dependencies automatically,
include the complete workspace and reference data, and connect to the configured companion node
under Windows Services or systemd. See the [installation guide](../INSTALL.md).

Source-folder launchers support interactive operation. The current source has
31 commands, including the five [local GIS commands](#local-gis-commands).
The source includes nine wildfire commands, three landslide commands, and the
location-based water commands. Existing release artifacts retain the command set
recorded in their validation; rebuild from this source to include later changes.
Installers include shared datasets. Service ZIPs include the wildfire and landslide reference seeds; EBMUD data remains a separate download.
See [deployment requirements](../INSTALL.md#gis-source-deployment).

## Multiple channels and program assignments

Use [MULTI_CHANNEL_GUIDE.md](MULTI_CHANNEL_GUIDE.md) for the configuration procedures,
Public/hashtag/private channel examples, per-program assignments, private keys,
radio setup commands, MQTT export controls, migration, and file/function guide.
Every command has an explicit `channels` list; replies stay on its incoming channel.
Adding a channel does not automatically enable programs there. The guide also
explains how to add plain Python programs to an installed service without rebuilding
or rerunning the installer. Restart after edits.

## Folder layout

- `service.py`, `responder.py`, `flood_alarm.py`: bridge and command handling.
- `channels.py`, `channel_setup.py`: registry validation, identity checks, and explicit radio setup.
- `config.json`: this installation's settings; `requirements.txt`: pinned dependencies.
- `scripts/`: one executable Python program per command, with reusable helper modules.
- `scripts/floodalarm.py`: structured flood readings for the persistent alarm monitor; standalone use does not enroll a subscription.
- `gis_settings.json`: local GIS data path, radius, projection, and output limits.
- `scripts/gis_data.py`, `gis_spatial.py`, `gis_lookup.py`: verified data loading, spatial calculations, and GIS replies.
- `../data/ebmud/`: shared GeoJSON, source manifest, manual refresh/repair tools, and archived originals; provided separately for standalone packages.
- `tests/`: offline regression and loopback MQTT integration tests.
- `radio_connection.py`: connection validation, transport selection, and bounded cleanup.
- `check_live.py`: optional radio/MQTT diagnostic; run only while the service is stopped.
- `runtime/`: local request history and subscriptions; preserve during upgrades.

## Radio connection settings

The service, local `cli` commands, and `channel_setup.py` use the same
`connection` object in `config.json`. Select one transport for one companion node.
Stop the service before changing settings or running a separate radio tool, then
restart it. Existing configurations without `connection` keep USB serial behavior.

USB serial (default; retain the top-level `serial_port` and `baudrate` settings):

```json
"connection": {"type": "serial", "timeout": 30},
"serial_port": "auto",
"baudrate": 115200
```

Wi-Fi / TCP, using the node's local IP address:

```json
"connection": {"type": "tcp", "host": "192.168.1.50", "port": 5000, "timeout": 30}
```

`port` defaults to **5000** when omitted and accepts integers from 1 to 65535.
`host` accepts an IPv4 or IPv6 address, without a URL prefix or appended port.
The computer must be able to reach the node at that address. The firmware must
expose the MeshCore companion TCP protocol; board Wi-Fi capability alone is not
sufficient. These settings do not configure the node's Wi-Fi credentials.
TCP is a plain local-network connection, without TLS or node authentication.
Use it on a trusted LAN. MQTT host/port, TLS settings and topic names are separate
and remain unchanged when the radio transport changes.

Bluetooth LE:

```json
"connection": {"type": "ble", "address": "AA:BB:CC:DD:EE:FF", "timeout": 30}
```

Use the intended node's Bluetooth address, not its display name. A working BLE
adapter and compatible BLE companion firmware are required. Complete pairing,
including any node PIN prompt, through the OS before starting the service. The
service does not scan for an arbitrary node or prompt for a PIN. No PIN belongs
in this configuration; the pinned SDK's PIN option only requests OS pairing and
does not supply a passkey to the OS.

On Linux, install/start BlueZ (`sudo apt install bluez` and
`sudo systemctl enable --now bluetooth`), then use `bluetoothctl` to scan, pair,
and trust the intended address. The OS installer installs BlueZ when BLE is
selected. Verify Bluetooth/D-Bus access under the `meshcore-ems` service account.
On Windows, enable Bluetooth and pair through Windows settings. Verify access
under the installed `NT AUTHORITY\LocalService` account; success in an interactive
console does not establish background-service access. Close other applications
holding the node connection. BLE service-account access still requires testing
on the target computer and adapter.

`timeout` bounds connection establishment in seconds (default 30; range 1–300).
The bridge also bounds its initial device query. After a detected radio disconnect,
the installed service manager restarts the process and rechecks the channel
bindings. Source-folder launchers require a manual restart. There is no automatic
fallback to a different transport or node. Commands with uncertain transmission
outcomes are not replayed. TCP also sends a read-only device check every 30 seconds, with a 10-second
response timeout after acquiring the radio command lock. Failure stops the bridge
so the installed service manager reconnects. These local checks do not transmit RF;
queued radio operations can delay a check. The intervals are prominent constants
at the top of `service.py`.

MQTT event `device` metadata includes `type`. Serial keeps the original string
`device.port`; TCP uses numeric `port` plus `host`; BLE uses `address` and a null
`port`. Historical outbox records retain their original metadata. The `ports`
command continues to list USB serial devices only.

## Included commands

[Quick user guide](BOT_USER_GUIDE.md#start) | [Complete command, option, and response reference](COMMAND_REFERENCE.md#command-index).

| Command | Input | Service |
| --- | --- | --- |
| `!status` | None | Local service health |
| `!time` | None | Current time in the shared timezone |
| `!aqi` | Latitude and longitude | AirNow PM2.5 AQI and nearest monitor |
| `!traffic` | California route number 1â€“999 | Active Caltrans highway restrictions |
| `!rivers` | Latitude and longitude | CDEC/NOAA river stations within 15 miles |
| `!uv` | Coordinates, US ZIP, or city and state | Current UV index and risk category |
| `!lightning` | Coordinates, US ZIP, or city and state | NWS lightning potential in the next 24h, stated chance, adjustable timezone |
| `!trail` | Name + attribute, or attribute near coordinates [miles] | Trail details, policy filters, or explicit full info |
| `!rec` | Name + attribute, or attribute near coordinates [miles] | Recreation details and amenity filters |
| `!peak` | Name + attribute, or near coordinates [miles] | Peak elevation, location, or explicit full info |
| `!park` | Name + attribute, or near coordinates [miles] | Park status, agency, trails, and recreation |
| `!boundary` | Optional category + coordinates, near coordinates [miles], or trail NAME | Mapped containment, nearest areas, or trail overlap |
| `!firezone` | Zone ID, coordinates, ZIP or city/state | Fire-weather zone and current warning/watch status |
| `!fires` | Zone/location or near-distance query | Reported incidents and latest mapped perimeter timing |
| `!fire` | Exact incident ID or unambiguous name | Containment, source attribution and last-known status |
| `!firewx` | Zone/location | Zone fire-weather forecast and alerts |
| `!firewarn` | Zone/location | Red Flag Warnings and Fire Weather Watches |
| `!firedata` | Category and zone/location | Supporting observations, detections, outlooks and reference features |
| `!firealarm` | on location, status, off | Temporary wildfire-change monitoring |
| `!slidewarn` | ZIP, city, GPS | California NWS alerts mentioning landslide/debris-flow hazards |
| `!slidealarm` | on location, status, off | Temporary California and Nevada landslide-alert monitoring |
| `!slideinfo` | ZIP, city, GPS | Nearest eligible California USGS monitoring station |
| `!smoke` | ZIP, city/state, GPS | Point smoke coverage and nearby air quality |
| `!firedanger` | ZIP, city/state, GPS | Local ERC percentile, fuels and warnings |
| `!heatadv` | Coordinates, US ZIP, or city and state | Active NWS heat warnings, watches, and advisories |
| `!floodwarn` | LOCATION | Highest-priority NWS flood alert |
| `!floodalarm` | Location, conditions location, status, stop | Temporary point alerts and current-condition monitoring |
| `!waterway` | Coordinates, US ZIP, or city and state | Named waterways and selected current gauge values |
| `!basin` | Coordinates, US ZIP, or city and state | Containing CalWater categories and gauge context |
| `!floodstatus` | Coordinates, US ZIP, or city and state | Official and derived current point conditions |
| `!snowpack` | California coordinates, ZIP, or city | Nearest-station snow depth and next-24h snowfall |

`!aqi` requires `AIRNOW_API_KEY`. The other included commands require no API
key. AQI, traffic, river, UV, heat-alert, flood-alert, and snowpack lookups require internet access.
Detailed input formats, sources, responses, and limitations are documented below.

## Linux setup

Copy this folder to the computer that will connect to the companion node.
Python 3.11+ with venv and access to the selected radio interface are required. Configure the channels
on the node first (default **#autatestbot**); `channel_setup.py` can explicitly
provision missing channels in empty slots.

```bash
cd /path/to/meshcore_mqtt_service
bash setup.sh
bash run.sh
```

With the default `serial_port: "auto"`, attach one supported USB serial device.
The program detects its current port at each start, reads the node's channel list, and
resolves each configured channel to its verified name/key and actual slot. Missing
or ambiguous channels fail explicitly; startup never falls back to Public or
implicitly creates a channel.

Ctrl+C stops the service. Setup creates `.venv-linux` here; a copied Windows `.venv`
is not reused. Launchers work from any current directory. If serial access is denied,
configure the Linux service account's device permissions, commonly through the distribution's
`dialout` group, and sign in again. Use the separate `meshcore_mqtt_service_windows`
package on Windows. Scripts run on the bridge's host; no SSH is used.

In serial mode with `serial_port: "auto"`, no detected USB serial device or multiple candidates
produces a clear error. Connect the intended Companion Node or set `serial_port`
to a specific device when several USB serial devices are attached. Detection uses
USB metadata, then the MeshCore connection verifies the selected device; it does
not guess which of several devices is the radio. A restart rescans the current
ports, including after COM or tty numbering changes.

## Configure phrases and scripts

Edit the `responder` section of `config.json`, then restart:

```json
"commands": {
  "!status": {"script": "scripts/status.py", "args": [], "channels": ["default"]},
  "!time": {"script": "scripts/time_now.py", "args": [], "channels": ["default"]}
}
```

Included scripts provide status, shared-zone time, AQI, traffic, river, UV, heat-alert,
flood-alert, and snowpack results. Flood monitoring is handled by `!floodalarm`. Extend the map
with custom phrases/scripts. Matching is exact and case-sensitive after trimming
outer whitespace.
Substrings, extra arguments and unknown phrases do not execute anything. Only decoded
messages received on a channel assigned to that command trigger scripts; direct messages, raw
packet logs and MQTT event replays do not.

Scripts must be existing `.py` files within the bundled service folder or the
configured external `program_directory`, including after symlink resolution. Use
`programs/NAME.py` for external programs; see the multi-channel guide. Fixed arguments may be set in `args`. Received message text never becomes
a shell command or executable path. Scripts use the local virtual environment and
run with this folder as their working directory.

**Print the answer to stdout without the @name prefix.** The service adds the
prefix and fits one complete primary field plus optional whole fields within
150 UTF-8 bytes. Newlines remain meaningful whitespace. Replies have no paging,
continuation prompts or omission notices. Script errors and timeouts produce
short tagged explanations; stderr diagnostics are saved locally.

Scripts may read JSON context from stdin:

```python
import json
import sys
request = json.load(sys.stdin)
print(f"Request from {request['sender']} on {request['channel_name']}.")
```

Context includes `id`, `sender`, `phrase`, `channel_id`, `channel_name`, `channel_index` and
`sender_timestamp`. The equivalent environment variables are `MESHCORE_SENDER`,
`MESHCORE_CHANNEL`, `MESHCORE_CHANNEL_ID`, `MESHCORE_CHANNEL_INDEX`, `MESHCORE_PHRASE`, `MESHCORE_TIMEZONE` and
`MESHCORE_REQUEST_ID`. Run configured scripts in the foreground; Linux timeouts
terminate their process group.

## Sender tracking and duplicate handling

The companion protocol supplies channel text as `Sender Name: message`. The service
extracts and saves the displayed name before executing the script, in
`runtime/bridge.sqlite3`, table `bot_requests`. Each reply uses that saved name even
when another sender arrives meanwhile. Spaces are preserved: `@Alice Smith ...`.
A channel display name is not an authenticated identity or authorization credential.

Duplicate detection uses channel, original timestamp and text, independently of relay
path, and survives restarts. Defaults ignore messages older than five minutes, more
than a minute in the future, lacking a timestamp/name, from the local node's own
name, or whose command body starts with @. Keep sending nodes' clocks accurate.
Each sender may start one request per channel every 30 seconds. Up to 50 requests
can wait globally, with at most 20 per channel by default.

Queued requests survive restarts but expire when stale. Requests interrupted during
execution or sending are marked `interrupted` and are not automatically repeated,
because side effects or transmissions may already have happened. Failed sends are
recorded without automatic retry. `sent` means the local radio accepted the reply,
not that another node received it. Relevant limits are configurable under `responder`.

## Local MQTT and modes

The bundled broker starts with the bridge at **127.0.0.1:1883**, accepts local clients
without a password, and listens only on this computer. It stops with the bridge.
Run `broker` in another terminal to keep MQTT alive independently; the bridge reuses
an existing listener on that port. The source launcher runs in the foreground.
Use the OS installer above for unattended systemd operation. Both use automatic
USB serial detection by default, with an explicit fixed-port override available.

```bash
bash run.sh ports
bash run.sh bridge
bash run.sh broker
bash run.sh watch
bash run.sh cli infos
```

`watch` consumes
bridged MQTT events as JSON lines and can run beside the bridge. Stop the bridge
before opening another radio connection with `cli`. Set `responder.enabled` to false
to run the MQTT bridge without automatic channel replies.

| Default topic | Purpose |
| --- | --- |
| meshcore/usb/events/<event_name> | Radio payload, attributes, UTC receipt time, UUID and radio endpoint |
| meshcore/usb/events/bot_reply | Automatic reply accepted by the radio |
| meshcore/usb/command | Incoming non-retained JSON CLI request |
| meshcore/usb/results/<id> | CLI request output/status |
| meshcore/usb/errors | Rejected MQTT commands |
| meshcore/usb/status | Retained online/offline status and last will |

Payloads preserve available text, timestamps, channel, RSSI, SNR, paths and other
fields. Missing information is not invented. Bytes use an explicit hex object;
known secret fields are redacted. With a channel registry, only channels with `mqtt_export: true` export decoded
messages and replies; raw/unclassified and unknown-channel traffic is suppressed.

Example MQTT request:

```json
{"id":"info-001","argv":["infos"]}
```

Supported MQTT commands: infos, ver, contacts, self_telemetry, clock, msg and chan.
Use a distinct request ID for each intentional command. Stored IDs prevent repeated
execution after redelivery/restart. Retained commands are ignored. `command_interval`
spaces commands and automatic replies by 5 seconds by default. Restrict access
to the command topic to trusted broker users.

Events use a durable SQLite outbox and QoS 1; MQTT reconnects automatically. Consumers
should deduplicate event UUIDs. Broker sessions and retained messages are in memory.
Monitor disk space during broker outages. Commands use live subscriptions; offline
commands are not guaranteed to execute. A detected radio disconnection stops the bridge; the installed service manager
restarts it. Restart a source-folder launcher manually to reconnect.

For an external broker set `local_broker` to false and edit `mqtt`. Authentication
uses MESHCORE_MQTT_USERNAME and MESHCORE_MQTT_PASSWORD. TLS uses `tls: true`, usually
port 8883, with an optional `ca_file` relative to this folder. Each bridge needs a
unique client_id and topic prefix.

## Verification

```bash
bash verify.sh
```

For development checks on Windows, use the Python environment in the separate
Windows package: `../meshcore_mqtt_service_windows/.venv/Scripts/python.exe -m unittest discover -s tests`.
Tests run real local scripts and a real
loopback MQTT broker with simulated radio events. They verify sender retention,
same-channel replies through the installed CLI helper, duplicate suppression,
timeouts/failures, Unicode size limits and persistent request state.

Tests also cover the lookup scripts with sample provider data, flood-alarm timing
and persistence, and unattended service configuration. These checks do not establish
physical radio delivery or installation and reboot behavior on target hardware.
`check_live.py` provides an optional read-only radio/MQTT check: it disables the
responder, uses the configured radio connection and an unused local broker port, and
runs only MQTT infos.

Pinned dependencies are listed in [requirements.txt](requirements.txt). The adapter
uses internal async CLI interfaces; check compatibility when changing dependencies.
Interactive source-folder operation keeps code, dependencies, and runtime files
in this folder. Installed services use the paths in the [installation guide](../INSTALL.md).

## AirNow AQI command

[Inputs and response formats](COMMAND_REFERENCE.md#cmd-aqi).

Send either of these on **#autatestbot**:

```text
!aqi 37.7749 -122.4194
!aqi 37.7749, -122.4194
```

Coordinates are decimal **latitude, then longitude**. Both must be finite numbers;
latitude must be -90..90 and longitude -180..180. The literal angle brackets are not
part of the message. The bot executes its own `scripts/airnow_aqi.py` with those two
positional arguments and prefixes every reply part with the saved sender's @name.
Invalid/missing coordinates produce a tagged usage reply without executing a script.

Set the AirNow API key in the launching environment, then start/restart the service:

```bash
export AIRNOW_API_KEY="YOUR_AIRNOW_API_KEY"
bash Start-Service.sh
```

Get a key through [AirNow's API account page](https://docs.airnowapi.org/account/request/).
No API key is stored in these files. Each service folder contains its own
AirNow lookup script. The lookup requires internet access. Missing keys/API failures
produce a tagged availability message rather than exposing HTTP response contents
or credentials.

The !aqi configuration uses `input: "coordinates"` and a 60-second command-specific
script timeout. Other preset commands use exact matching and their configured timeout.
Only validated numeric coordinate arguments are appended to the Python invocation;
arbitrary command options or shell syntax are not accepted. The 30-second
per-sender cooldown applies, including after a malformed request.

The result reports nearest-monitor PM2.5 AQI, concentration when available, rating,
station, distance, observation time and preliminary-data status. It is a monitoring
station observation, not a measurement at the submitted GPS point. Long output uses
the shared single-message field budget.

## Caltrans traffic command

[Inputs and response formats](COMMAND_REFERENCE.md#cmd-traffic).

On **#autatestbot**, send a highway/route number:

```text
!traffic 80
!traffic 5
!traffic 101
```

Use digits only, from 1 to 999; omit prefixes such as I-, US or SR. The bot runs its
own `scripts/highway_info.py` with that number as a positional argument.

The response goes to the same channel with the sender's saved @name at the start of
every part. Active Caltrans California road restrictions retain the program's compact
format. When the report is clear, the response is exactly:

```text
@SENDERSUSERNAME No Traffic Restrictions Reported
```

No API key is needed; the computer requires internet access to Caltrans. Missing or
invalid arguments produce a tagged usage reply without running the script. Fetch
failures produce a tagged availability message, never a clear-road assertion.
The command uses `input: "route_number"` and a 30-second subprocess timeout.
Configured cooldowns, duplicate suppression, maximum reply length and part limits apply;
radio output retains priority fields within one tagged message. Full provider and
structured data remain available through the documented local interfaces.

## Nearby river stations command

[Inputs, radius, and response formats](COMMAND_REFERENCE.md#cmd-rivers).

Send either form on **#autatestbot**:

```text
!rivers 39.0000 -121.0000
!rivers 39.0000, -121.0000
```

Supply decimal latitude first, then longitude. The bot validates latitude -90..90
and longitude -180..180 and invokes its local `scripts/nearby_river_stations.py` as:

```text
nearby_river_stations.py --mesh-text --timeout 15 --latitude 39.0 --longitude -121.0
```

The submitted coordinates always override the program's standalone defaults. Both
service folders contain an independent copy of the script.
The command requires internet access to CDEC and NOAA, but no API key.

The search radius is **15 miles**. Matching CDEC river-stage stations are
returned nearest first, with station name/ID, distance, stage, report time, action
stage (AS) and minor flood stage (FS). Missing readings/thresholds show N/A. An empty
match produces an explicit no-matching-stations message; source/network errors
produce an availability message instead. This is a report lookup, not a prediction.

One tagged reply selects the nearest station in the highest reported threshold
category, or the nearest station when no threshold is exceeded. Issuance time,
thresholds and station name are optional fields. This describes a gauge report,
not flooding at the query point. Full station records remain in JSON output.

The `coordinate_style: "options"` configuration maps validated coordinates to
--latitude and --longitude; !aqi continues using positional arguments. The river
command has a 40-second subprocess timeout around its two 15-second HTTP requests.
To choose a different fixed radius, add `"--radius", "30"` to this command's args.
Additional flags sent over the radio are not accepted.

The program returns full JSON when run directly without --mesh-text, including
raw_report_line, all stage-history values, coordinates and thresholds. The compact
mesh format is enabled only through this command's configured --mesh-text argument.

## Current UV index: !uv

[Location syntax and response formats](COMMAND_REFERENCE.md#cmd-uv).

Send on a channel assigned to this command (default #autatestbot):

```text
!uv 38.5816, -121.4944
!uv 95814
!uv Sacramento
!uv Reno NV
!uv Reno, Nevada
```

Cities default to California. A trailing full state name or two-letter abbreviation
(case-insensitive, with or without a comma) overrides it. US ZIP codes, including
ZIP+4, work nationwide. GPS coordinates accept a comma or a space. City searches
prefer exact names, then the largest matching settlement; use GPS for precision.
Example reply: `@Alice UV Index: 6.5 High`.

Run directly with `python scripts/uv_index.py Sacramento` or
`python scripts/uv_index.py 38.5816 -121.4944`. No extra Python dependencies or UV
API key are required.

UV data: [CurrentUVIndex.com](https://currentuvindex.com/),
[API](https://currentuvindex.com/api), CC BY 4.0. Only `now.uvi` is reported.
Risk bands use the unrounded reading: below 3 Low, 3 to below 6 Moderate,
6 to below 8 High, 8 to below 11 Very-High, and 11+ Extreme.
The API allows 500 requests per public IP per day, resetting at 00:00 UTC.
Each request fetches a fresh reading; repeated requests count against that limit.
Location lookup uses [Open-Meteo](https://open-meteo.com/en/docs/geocoding-api)
and [GeoNames](https://www.geonames.org/). The free Open-Meteo endpoint is for
non-commercial use. Coordinates bypass location lookup.

Offline checks: `python -m unittest discover -s tests -p "test_uv.py"`.

## Lightning potential: !lightning

[Forecast responses and uncertainty](COMMAND_REFERENCE.md#cmd-lightning).

Send `!lightning Sacramento`, `!lightning 95814`, `!lightning 38.5816, -121.4944`,
or `!lightning Reno NV` on an assigned channel. Decimal GPS accepts comma or space
separation; ZIP+4 uses its first five digits. Cities without a state default to
California; other states require an abbreviation or full name after the city.
Replies preserve the supplied location, with whitespace normalized. Cities/ZIPs
resolve to a representative point, not their whole boundary.

Responses begin with an official NWS event when present, otherwise a forecast
chance or coverage label such as `NWS: slight chance thunderstorms (24h).` Known
hazards retain `Data incomplete.` if another input fails. Optional fields include
the overall span, other chance levels, window count and location. Forecast
probabilities describe thunder, not rain or individual strike predictions.

The lookup covers exactly 24 elapsed hours from the original responder request
timestamp (or invocation time for standalone use), even across daylight-saving
changes. Ongoing intervals start at the request time; later intervals keep their
NWS start time, and intervals are clipped at the 24-hour endpoint. Time windows
are forecast/alert periods, not predicted times of individual strikes.

### Shared persistent reply timezone

All MeshCore service programs receive the same saved timezone. In the active
`config.json`, set the single `responder.timezone` variable:

```json
"timezone": "America/Los_Angeles"
```

Pacific is the default, with PST/PDT labels and automatic daylight-saving handling.
Change the value to an IANA zone such as `America/Denver` or `America/New_York`,
then restart the service. No rebuild or reinstall is needed. The setting survives
restarts and installer upgrades. It applies to `!time`, AQI observation timestamps,
river issuance/reading timestamps, and lightning windows. GIS retrieval dates remain in the source manifest and are not appended to replies.
Caltrans's undated or recurring schedules retain an
explicit Pacific source-time label because they lack dates for reliable conversion.

Installed configuration is `/etc/meshcore-ems/config.json` on Linux or
`C:\ProgramData\MeshCore-EMS\config.json` on Windows. Source-folder operation uses
this folder's `config.json`. Existing settings without the field default to Pacific;
the installer saves the field during upgrade without replacing an operator's value.
The service validates the zone at startup and exports it as `MESHCORE_TIMEZONE` to
every child program, including external programs. Custom programs can read that
environment variable and use `zoneinfo.ZoneInfo` when formatting their timestamps.

[`scripts/time_settings.py`](scripts/time_settings.py) supplies the shared display
helpers and fallback `DEFAULT_TIMEZONE`. A standalone program uses `MESHCORE_TIMEZONE`
when set, otherwise Pacific; standalone lightning also accepts `--timezone`.
Bot requests always use the shared saved setting, even if old command args contain
a timezone override. UTC storage, MQTT timestamps, source timestamp interpretation,
and elapsed-time calculations stay unchanged. The separate satellite tools are
outside this MeshCore reply setting.

### NWS inputs and limits

[NWS does not issue standalone lightning warnings](https://www.weather.gov/gsp/gspPrepare_8).
The formatter distinguishes official events from forecast potential. It combines actual
point alerts with the [NWS forecast grid](https://weather-gov.github.io/api/gridpoints):
thunderstorm weather/coverage, dry-thunderstorm attributes, positive
`probabilityOfThunder`, and [lightning activity levels](https://forecast.weather.gov/glossary.php?word=LALs)
2-6. Level 6 includes dry lightning. Severe thunderstorm/tornado watches and
warnings count; other alerts, including fire-weather and special-weather products,
count when hazard text mentions lightning/thunderstorms. Wind/dryness alone does
not make a fire-weather alert qualify. Common negations and separate preparedness
instructions are excluded; free-text recognition is limited to the wording in the
source and cannot interpret every possible phrase.

`/points` verifies coverage and supplies the grid URL. `/alerts/active?point=...`
lets NWS match its polygons/zones. These endpoints do not require a radius, so no
five-mile circle is imposed. GPS is the most precise input. City/ZIP geocoding
uses Open-Meteo/GeoNames through the heat command's shared resolver.

The no-lightning reply requires valid alerts and a weather grid covering the full
24 hours, updated within 12 hours. Expired/cancelled/test alerts are excluded;
future-onset hazards within the window are included. Missing optional numeric
layers are normal, but missing weather coverage, stale/malformed data, network
failures, and unsupported locations cannot produce a clear reply. If one valid
source reports a hazard while the other fails, the warning is retained with
`additional NWS data unavailable`; an empty partial result produces an error.
This is a one-shot forecast lookup, not strike detection or continuous monitoring.

### Running and maintaining the command

```console
python -m pip install -r requirements.txt
python scripts/lightning.py Sacramento
python scripts/lightning.py --timezone America/Denver "Reno NV"
python -m unittest discover -s tests -p "test_lightning.py"
```

Internet access is required; no API key is needed. `tzdata` supplies IANA timezone
data on Windows and systems without it. Keep `lightning.py`, the current
`heat_adv.py`, `uv_index.py`, and `time_settings.py` together. Network calls allow 12 seconds each,
with a 60-second command timeout. The responder adds the sender tag, replies on
the incoming channel, and limits the response to one 150-byte tagged message.

See the [lightning function reference](FUNCTION_REFERENCE.md#scripts-lightning-py)
for every function and [installation instructions](../INSTALL.md#lightning-command-and-timezone)
for adding the command to an existing installation. Assign its channels explicitly
when preserving a custom channel registry.

## Heat alerts: !heatadv

[Alert responses and error handling](COMMAND_REFERENCE.md#cmd-heatadv).

The [heat function reference](FUNCTION_REFERENCE.md#scripts-heat-adv-py) explains
all seven lookup functions, their inputs, outputs, and failure behavior. The
[complete service function reference](FUNCTION_REFERENCE.md) also covers the
bridge, responder, channels, transport, service runner, and other lookup scripts.

Send on a channel assigned to this command (default `#autatestbot`):

```text
!heatadv 38.5816, -121.4944
!heatadv 38.5816 -121.4944
!heatadv 95814
!heatadv Sacramento
!heatadv Reno NV
!heatadv Reno, Nevada
!heatadv Albany New York
```

Cities without a state are looked up in California only. For another state, put
its two-letter abbreviation or full name after the town/city, with an optional
comma. ZIP+4 is accepted and resolved using its first five digits. Replies retain
the supplied location spelling and format, apart from collapsing extra whitespace.
A city or ZIP is checked at its representative coordinate; use GPS for a precise
point rather than a city/ZIP-wide result.

The response begins with `NWS Extreme Heat Warning.`, `NWS Extreme Heat Watch.`,
`NWS Heat Advisory.` or `No active NWS heat alerts.` Additional distinct alert
types and the location are whole optional fields in the same tagged message.

[`scripts/heat_adv.py`](scripts/heat_adv.py) uses the
[NWS API](https://www.weather.gov/documentation/services-web-api): first
`/points/{latitude},{longitude}` to verify coverage, then
`/alerts/active?point=LAT,LON&status=actual` for alerts applying to that point.
Expired, ended, cancelled, test, and not-yet-effective alerts are excluded.
An effective watch counts even when its heat event starts in the future.
Older `Excessive Heat Warning/Watch` names are accepted and displayed as
`Extreme Heat Warning/Watch`, matching the
[NWS naming change](https://www.weather.gov/news/250310-heat-hazard).
Network failures, malformed/incomplete replies, and unverified coverage produce
an error message, never the no-advisories reply.

City/ZIP coordinates come from [Open-Meteo](https://open-meteo.com/en/docs/geocoding-api)
/ GeoNames with exact city/state or ZIP matching. The free geocoder is for
non-commercial use. GPS bypasses geocoding. Internet access is required; no API key
or new Python dependency is needed. Requests have a 12-second timeout each;
`config.json` allows 45 seconds for the entire command. Timeouts, URLs, event
aliases, and reply templates are grouped at the top of `heat_adv.py`.

Run directly from this folder:

```console
python scripts/heat_adv.py Sacramento
python scripts/heat_adv.py 95814
python scripts/heat_adv.py "Reno NV"
python scripts/heat_adv.py "38.5816, -121.4944"
python -m unittest discover -s tests -p "test_heatadv.py"
```

Keep `scripts/uv_index.py` alongside `scripts/heat_adv.py`; it supplies the location
parser. To update an existing service, copy the script into its active `scripts/`
directory and merge the `!heatadv` entry from this package's `config.json` into the
active configuration. Set its `channels` list to the intended existing channel IDs
(`default` in the supplied configuration), then restart the service. Preserve the
other settings. Generated ZIPs/installers need rebuilding to include source edits;
editing this source folder does not update an already installed service.

## Location water status and official flood alerts

`!waterway LOCATION`, `!basin LOCATION` and `!floodstatus LOCATION` report named
waterways, containing CalWater categories and current source conditions. Local
statewide context requires separately downloaded datasets and a spatial index.
`!floodwarn LOCATION` returns the highest-priority NWS flood alert, with essential
action and optional expiration/location. Local `--json` retains current source records.

Locations accept GPS, US ZIP/ZIP+4 or exact city/state. Bare cities default to
California. Ambiguous names require coordinates. Representative city/ZIP points
are not complete area boundaries. Official, modeled and derived basin conditions
are labeled separately; unavailable data is not an all-clear.

[Setup, examples, current-only retention, configuration and source citations](WATER_GUIDE.md).

## Snowpack: !snowpack

[Snow responses and missing data](COMMAND_REFERENCE.md#cmd-snowpack).

Send on a MeshCore channel assigned to this command (default `#autatestbot`):

```text
!snowpack 39.3279, -120.1833
!snowpack 96161
!snowpack Truckee
!snowpack South Lake Tahoe CA
```

Coordinates with a space instead of a comma and ZIP+4 codes also work. City names
are matched in California; GPS and ZIP locations are checked against the NWS
California county coverage. No API key or additional Python dependency is needed.

Example format (illustrative values):

```text
@Alice Snow depth at station: 12in. | Next 24h snow: 4in | Snow Creek 2.3mi
```

The responder supplies the requesting sender's `@name` and sends the result to the
same channel. The standalone `scripts/snowpack.py` prints the body only.

- **Current:** latest valid hourly **snow depth**, in inches, from the nearest
  active hourly sensor-18 station in the [CDEC station directory](https://cdec.water.ca.gov/dynamicapp/staSearch?search=Search&sensor_chk=on&sensor=18&dur_chk=on&dur=H&active_chk=on&active=Y&display=sta).
  This is the snow on the ground at that station, not snow-water equivalent or a
  measurement at the user's coordinates. Station elevation and terrain can differ
  greatly from the requested location, especially in cities far from the mountains.
- **Next 24h:** forecast new snow at the **requested location**, using the
  [NWS numerical forecast grid](https://weather-gov.github.io/api/gridpoints).
  Sums snowfall-amount intervals covering the next rolling 24 hours and converts
  millimeters to inches. Boundary intervals are prorated by their overlap, assuming
  snow falls uniformly within each source interval (usually six hours); this is an
  estimate of the rolling total, not an hourly timing prediction.
- **Station:** nearest listed active hourly snow-depth station, with straight-line
  distance in miles. A stale/missing reading does not silently switch to a farther
  station. Stations are discovered live; manual monthly snow courses are excluded.
- **Availability:** readings and forecast updates must be at most 24 hours old.
  Negative, flagged, nonnumeric, missing, or future readings are excluded. CDEC
  timestamps omit UTC offsets, so freshness is conservatively required under both
  Pacific offsets (UTC-7 and UTC-8); this can omit the newest hour. Missing data,
  stale forecasts, or gaps/overlaps in the 24-hour forecast produce `unavailable`
  for the affected field, never a fabricated `0in`. A valid zero remains `0in`.
  Positive amounts below 0.05 inches are shown as `<0.1in`.

City/ZIP coordinates come from [Open-Meteo/GeoNames](https://open-meteo.com/en/docs/geocoding-api).
Internet access is required. Each request has a 10-second network timeout, with a
65-second overall script timeout. Configured cooldowns and the single-message limit apply.

```text
python scripts/snowpack.py "39.3279, -120.1833"
python scripts/snowpack.py 96161
python scripts/snowpack.py Truckee
python -m unittest discover -s tests -p "test_snowpack.py"
```

## ZIP package

The distribution ZIP includes this service folder, command scripts,
configuration, launchers, setup scripts, tests, and documentation. Local Python
environments, runtime databases, and generated bytecode caches are excluded.
After extraction, follow the setup/launcher instructions above to install the
pinned dependencies. Existing local runtime files are not included in the ZIP.

## Flood monitoring: !floodalarm

```text
!floodalarm Sacramento CA
!floodalarm conditions 38.61324 -122.83638
!floodalarm status
!floodalarm stop
```

The running service verifies and pins the location before confirming enrollment.
Official alerts are monitored by default; `conditions` adds all reliably linked upstream
gauge categories, current modeled footprint changes and data availability.
Default checks run every five minutes for four hours. Unchanged conditions are
quiet; material alert updates, expiry, outage and recovery remain distinct.
Renewal replaces the baseline and deadline; `stop` cancels the subscription.
Each active alert is a separate priority-ordered notification with its standard
description. Completed responses are separated by at least five seconds; the
shared radio interval also defaults to five seconds. Contention can extend gaps. Unknown source
states remain explicit, and pending obsolete alerts are suppressed.

Subscriptions persist across restarts without extending expiry. They are scoped
to sender display name and channel; identically named nodes share that scope.
Standalone Python calls cannot enroll subscriptions. The service and radio must
remain available; local send acceptance does not establish remote delivery.

[Subscription lifecycle, migration, limitations and maintenance](WATER_GUIDE.md).

## Local GIS commands

[Quick GIS examples](BOT_USER_GUIDE.md#gis) | [Complete GIS query grammar](COMMAND_REFERENCE.md#gis-syntax).

The five GIS commands read the shared EBMUD snapshots without network requests.
Names are searched locally; city/ZIP geocoding and live closure reporting are
not provided. Coordinates are entered as latitude followed by longitude.

| Command | Example | Result |
| --- | --- | --- |
| `!trail` | `!trail Bear Creek dogs` | Only the recorded dog policy; `info` requests a concise summary. |
| `!rec` | `!rec water near 37.90 -122.20` | Only the closest recreation feature with recorded drinking water. |
| `!peak` | `!peak Wildcat Peak elevation` | Only the stored elevation in feet. |
| `!park` | `!park Pleasanton Ridge status` | Only the recorded park status. |
| `!boundary` | `!boundary 37.90 -122.20` | Areas containing the point, including exact-boundary matches. |
| `!boundary` | `!boundary trail Bear Creek` | Park, recreation-area, reservoir, and watershed polygons intersecting a named trail. |

All five commands support `near LATITUDE LONGITUDE [MILES]`. Without miles,
exactly one closest matching feature is returned, with no implicit search radius
and no additional-result count. With miles, matching features within that radius
are listed nearest first, limited by `max_results`. The configured maximum radius
applies only to an explicit radius. Equal distances are ordered by name and then
category. Distances use full mapped geometry; a point inside a polygon has zero
distance. Null geometry is excluded from spatial searches.

The first four commands also accept bare coordinate pairs for closest-only
searches. `!boundary LAT LON` retains containment behavior and can return multiple
containing areas; `!boundary near LAT LON` returns only the nearest area.

Named queries use `!COMMAND NAME ATTRIBUTE`. Omit the attribute for a compact
identification and subcommand list; use `info` for the full description.
Proximity queries use `!COMMAND ATTRIBUTE near LAT LON [MILES]` when a field or
filter is required. A command without arguments, or with `help`, displays syntax.
Keywords are case-insensitive. The command name remains `!trail`, singular.
A name search prefers exact matches, ignoring case, punctuation, accents, and a
trailing `Trail`. Partial matches produce a selection list when ambiguous.

### GIS subcommands

Attribute references: [trail](COMMAND_REFERENCE.md#cmd-trail), [recreation](COMMAND_REFERENCE.md#cmd-rec), [peak](COMMAND_REFERENCE.md#cmd-peak), [park](COMMAND_REFERENCE.md#cmd-park), and [boundary categories](COMMAND_REFERENCE.md#cmd-boundary).

| Command | Subcommands | Information |
| --- | --- | --- |
| `!trail` | `dogs`, `horses`, `bikes` | Recorded access policies; these filter proximity searches for permitted use. |
| `!trail` | `length`, `difficulty`, `gain`, `surface`, `shade`, `time` | Recorded distance, difficulty, elevation gain, surface, exposure, or estimated duration. |
| `!trail` | `start`, `areas`, `description`, `info` | Mapped start, intersecting areas, bounded description, or full information. |
| `!rec` | `type`, `location`, `info` | Feature type, coordinates, or full information. |
| `!rec` | `parking`, `restrooms`, `water`, `picnic`, `fishing`, `boatlaunch`, `boatrental`, `playground`, `horsetrailers` | Recorded amenities; these filter proximity searches for availability. |
| `!peak` | `elevation`, `location`, `info` | Elevation in feet, coordinates, or full information. |
| `!park` | `status`, `agency`, `trails`, `recreation`, `info` | Recorded status, agency, intersecting trails/recreation, or full information. |
| `!boundary` | `parks`, `watersheds`, `reservoirs`, `recreation` | Restrict the searched polygon category; place the category before coordinates, `near`, or `trail NAME`. |

Examples of category selection are `!boundary parks 37.90 -122.20`,
`!boundary watersheds near 37.90 -122.20`, and
`!boundary reservoirs trail Bear Creek`. The `parks` category selects regional
and adjacent local park layers; `recreation` selects recreation-area polygons.
Without a category, all configured boundary layers are considered.

Policy and amenity filters are applied before ranking distance. Qualifying values
include `Yes`, the recorded bicycle value `Yes L`, dog access `Limited to Park
Hours`, parking `Lot`/`Limited`, restrooms `ADA`, and horse-trailer parking `phYes`.
Qualifications remain visible. Every grouped source record must qualify; negative,
missing, conflicting, or unrecognized values exclude that group from a filtered
search. A named attribute lookup still displays its recorded value or `not recorded`.
No qualifying feature produces an explicit no-match reply.

Other attributes select information without filtering. For example,
`!peak elevation near LAT LON` returns the nearest peak's elevation, while
`!rec water near LAT LON` returns the nearest recreation feature with recorded
drinking water. Adding miles allows multiple qualifying results. Only one
attribute/category is supported per query.

Distances are map/straight-line distances, not walking routes. Trail/park overlap
does not establish connectivity, public access, or ownership. Polygon holes are
excluded from containment. Unnamed peaks remain excluded by default.

Each command has a dedicated executable program in `scripts/`:

| Command | Python program | Standalone example from the service folder |
| --- | --- | --- |
| `!trail` | `scripts/trail.py` | `python scripts/trail.py Bear Creek` |
| `!rec` | `scripts/rec.py` | `python scripts/rec.py near 37.90 -122.20` |
| `!peak` | `scripts/peak.py` | `python scripts/peak.py Wildcat Peak` |
| `!park` | `scripts/park.py` | `python scripts/park.py Pleasanton Ridge` |
| `!boundary` | `scripts/boundary.py` | `python scripts/boundary.py trail Bear Creek` |

Names and coordinates are positional arguments. All five programs accept
`--settings PATH`. Shared `gis_data.py`, `gis_spatial.py`, and `gis_lookup.py`
retain data validation, geometry operations, and reply formatting. The older
`gis_lookup.py --kind KIND --query "QUERY"` interface remains compatible with
existing registrations, but current defaults use one program per command.

### GIS response examples

[Per-attribute examples](COMMAND_REFERENCE.md#cmd-trail) | [GIS result and error reference](COMMAND_REFERENCE.md#gis-responses).

The following reply bodies were verified against the bundled datasets on
October 11, 2026. The responder adds the sender's `@name` and fits one 150-byte message.
Dataset and settings changes can change these results.

**`!trail Bear Creek dogs`**

```text
Bear Creek: dogs No.
```

**`!rec Briones Overlook Staging Area parking`**

```text
Briones Overlook Staging Area: parking Lot.
```

**`!peak Wildcat Peak elevation`**

```text
Wildcat Peak: elevation 1200 ft.
```

**`!park Pleasanton Ridge status`**

```text
Pleasanton Ridge: status Landbank/Parkland.
```

**`!boundary trail Bear Creek`**

```text
Trail overlaps: Watershed: Contra Costa.
```

**`!trail dogs near 37.90 -122.20`**

```text
Nearest trail: Oursan (0.84 mi map distance) | dogs Yes.
```

**`!trail dogs near 37.90 -122.20 5`**

```text
Trails within 5 mi: Oursan (0.84 mi map distance) | dogs Yes | Old San Pablo Trail (0.97 mi map distance) | dogs Limited to Park Hours
```

**`!rec water near 37.90 -122.20`**

```text
Nearest recreation: Tilden Steam Trains Park Entrance (1.82 mi map distance) | water Yes.
```

**`!boundary parks near 37.90 -122.20`**

```text
Nearest park: Tilden (1.52 mi map distance).
```

For a concise summary, use `!trail Bear Creek info`,
`!rec Briones Overlook Staging Area info`, `!peak Wildcat Peak info`, or
`!park Pleasanton Ridge info`. Results stating `none in local data` describe the
available mapped records, not the absence of facilities in the real world.

### GIS settings and source installation

[Settings and limits](COMMAND_REFERENCE.md#settings) | [Direct Python invocation](COMMAND_REFERENCE.md#python-programs).

Edit [gis_settings.json](gis_settings.json):

| Setting | Default | Meaning |
| --- | --- | --- |
| `data_directory` | `../data/ebmud` | Shared data directory, relative to this settings file; an absolute path is also supported. |
| `maximum_radius_miles` | 25 | Maximum explicitly supplied radius; closest-only queries have no radius cutoff. |
| `max_results` | 3 | Maximum candidate results or associations before radio field selection. |
| `max_reply_bytes` | 480 | Legacy GIS setting; the shared radio limit is 150 bytes including sender tags. |
| `description_characters` | 100 | Maximum source description length; zero omits it. |
| `include_unnamed_peaks` | false | Include unnamed peak records with source-ID labels. |
| `projected_crs` | EPSG:32610 | Metric UTM zone 10N for spatial calculations. |
| `search_bounds` | [-126, 0, -120, 84] | Accepted coordinate extent, ordered west/south/east/north. Projection and bounds must be changed together for other regions. |

Command timeout (30 seconds), channel assignments, and reply parts (1) remain in
`config.json`. Each command uses `input: "gis_query"`, its dedicated Python
program, and an empty `args` list by default; the query is passed as one argument,
without a shell. Only explicitly assigned channels can invoke each command.
The source mapping and checksums remain in the shared `sources.json`.

Query text is limited to 150 printable characters. Explicit radii must be positive and
cannot exceed `maximum_radius_miles`. Older `default_radius_miles` fields are
ignored and can be removed; no default radius is used. Accepted integer ranges are 1-20 for
`max_results`, 200-2000 for `max_reply_bytes`, and 0-500 for
`description_characters`. A projected CRS with metre units is required.
Coordinate input uses latitude/longitude; GeoJSON storage uses longitude/latitude.

The default settings file is beside `config.json` in the service source folder,
even when the runner uses an external configuration. Select another file with
`--settings /absolute/path/gis_settings.json`. For a dedicated command, set
`args` to `["--settings", "/absolute/path/gis_settings.json"]`. Each lookup reloads
the GIS settings; command-registration edits require a service restart.

Install the updated dependencies with the service's Python interpreter:

```text
python -m pip install -r requirements.txt
python scripts/trail.py "Bear Creek dogs"
python scripts/boundary.py 37.90 -122.20
```

The GIS dependencies are pinned Shapely and pyproj. PROJ network downloads are
disabled. All commands use local data, including peak and trail-name searches.
For an existing installation, deploy the updated `responder.py`, all three GIS
helpers, the five dedicated command programs, `gis_settings.json`, and
`requirements.txt`; the updated responder
is required to recognize `gis_query`. Install the dependencies, merge the five
command registrations into the active configuration, and restart the service.
The [deployment guide](../INSTALL.md#gis-source-deployment) covers external
settings paths, service interpreters, and offline checks. Existing connection,
channel, credential, and timezone settings must be preserved. The configured
shared data directory must exist; standalone service folders require that data
to be provided separately. Rebuilt complete-workspace installers include the data.
Installer upgrades preserve existing command definitions; merge older dispatcher
registrations and explicitly assign newly added commands to permitted channels.

### GIS data integrity and interpretation

Required dataset hashes and counts are verified before use. The manifest is
checked again after lookup. Active refresh locks, retained refresh-recovery
directories, missing/corrupt datasets, or concurrent manifest changes cause an
unavailable/retry response rather than an empty geographic result. Only layers
required for the query are loaded. Refresh remains a manual operation.

GIS replies omit the snapshot date and trailing data disclaimer. Download dates
and provenance remain in `sources.json`; they are not feature-edit dates. The
local datasets do not represent live conditions or permission to enter. Unknown attributes remain `not recorded`; conditional
access wording, limited parking, accessible restrooms, and park `Landbank` status
are preserved. Primary trail attributes take precedence over supplementary
segments with the same normalized name. Segment lengths are not summed into an
inferred route. Same-name park polygon records are grouped for presentation;
all distinct source statuses are retained. The primary trail's stored `HOUR`
value is displayed as an estimate labeled 3 mph with terrain excluded; it is not
an independently calculated route duration.

For source-field or layer changes, review `LAYER_FIELDS`, `PARK_LAYERS`, and
`BOUNDARY_LAYERS` in `scripts/gis_data.py`. The `SUBCOMMANDS` and `BOUNDARY_FILTERS` constants in `gis_data.py` define
syntax and polygon categories. `ATTRIBUTE_FIELDS` and `FILTER_VALUES` in
`gis_lookup.py` define source fields and explicit qualifying values; its
formatting functions define labels and full summaries. Configuring a
new manifest source alone does not add it to command search categories. The
[function reference](FUNCTION_REFERENCE.md#scripts-gis-data-py) documents these
modules; update both platform copies together.

Invalid shapes are repaired only in memory during GIS calculations, with a
reply note. Explicitly repaired local snapshots retain their original files and
repair metadata in the shared data directory. Geometric validity does not
establish surveyed or legal boundary accuracy. Null geometry is skipped for
spatial operations; annotation label polygons are not treated as park boundaries.

Run `python -m unittest discover -s tests -p "test_gis*.py" -v` for GIS tests,
including subcommands, filtering, and closest-only behavior. Run
`python -m unittest discover -s tests -p test_command_programs.py -v` for
dedicated command-program registrations.
The full offline suite remains available through the platform verification script.
See [data maintenance](../data/ebmud/README.md#manual-refresh) for complete-download
verification and [polygon repair](../data/ebmud/README.md#local-polygon-repairs)
for preserved originals and repair provenance. Neither operation runs on startup.

| Symptom | Check |
| --- | --- |
| Local GIS data unavailable | Verify dependencies in the service interpreter, the data path, and manifest hashes/counts; inspect subprocess diagnostics in service logs. |
| Refresh or recovery pending | Confirm no maintenance process is running, inspect retained previous files, and complete recovery before removing a stale lock/recovery directory. |
| No matching feature | Check the mapped name or select from ambiguous matches; city/ZIP lookup is unsupported. |
| Radius or coordinate error | Review the configured radius limit, latitude/longitude order, and projection bounds. |
| Reply omits detail | Review the [field inventory](RESPONSE_FORMATTING.md); the radio budget is one message. |

Software tests do not establish physical radio delivery or native Linux behavior.


## California wildfire information

Seven commands provide whole interstate fire-weather zones, reported fires,
containment and perimeter timing, zone forecasts, fire-weather alerts, supporting
observations and temporary monitoring. Start with `!firezone Truckee`,
`!fires CAZ272` or `!firewx CAZ272`. The service maintains a local cache and
preserves the last good data on source failure. `!firealarm on CAZ272` enables
four-hour monitoring; `status` and `off` inspect or cancel it.

See [wildfire commands, datasets, configuration and maintenance](WILDFIRE_GUIDE.md).
The package includes the complete zone seed; live observations require network
access. Existing installations must assign the new commands to channels after
upgrading. Forecast zones are not evacuation zones, and an absent fire record
is not evidence that a fire has been extinguished.

Point wildfire lookups: !smoke LOCATION and !firedanger LOCATION accept ZIP,
city/state, or latitude/longitude. Smoke replies begin with Smoke: and omit
location, Monitor: and PM10: lines. ERC uses local historical percentiles;
detailed fuel moisture requires optional FEMS access. See the
[point-command guide](WILDFIRE_GUIDE.md#point-smoke-and-fuel-danger).

## California and Nevada landslide information

`!slidewarn LOCATION`, `!slidealarm on LOCATION` (with `status`/`off` controls),
and `!slideinfo LOCATION` accept ZIP, city/state, or latitude/longitude using the
shared location resolver. Resolved points must be inside California or Nevada. NWS alerts
retain official names; USGS station metadata does not establish current slope
conditions. [Commands, sources, subscriptions, configuration, and limits](LANDSLIDE_GUIDE.md).

The [NOAA station review](WATER_STATION_REVIEW.md) documents 33 upstream identifier
checks, supported threshold links and explicit unresolved matches. Refresh the
review with `python scripts/water_refresh.py --noaa-identifiers`. The agency
review includes the documented CDM/YDMC1 successor and keeps unresolved
identities separate from historical USGS coverage metadata.

The [map and operator-record audit](WATER_STATION_REVIEW.md#further-map-and-operator-record-review)
keeps sixteen station identities unresolved. Refresh retains static candidate
evidence and flags source or identity changes; map proximity never authorizes a link.

The [source-access retry](WATER_STATION_REVIEW.md#archived-source-and-onerain-access-retry)
recovered the historical reports and OneRain inventory. Refresh checks static
operator aliases without retaining historical levels or enabling unsupported links.
