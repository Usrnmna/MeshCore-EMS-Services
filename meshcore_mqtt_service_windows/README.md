# MeshCore command service for Windows x64

Documentation: [MeshCore user guide](BOT_USER_GUIDE.md) | [Detailed command reference](COMMAND_REFERENCE.md) | [Function implementation reference](FUNCTION_REFERENCE.md).

This is an independent Windows copy. It does not load code, configuration, Python
packages or runtime databases from the Linux service folder.

## OS service installers

Current distribution version: `v0.9.5-beta`.

Online installation packages support Windows x64,
Raspberry Pi ARM64, and Linux x86_64. They install Python/dependencies automatically,
include the complete workspace and reference data, and connect to the configured companion node
under Windows Services or systemd. See the [installation guide](../INSTALL.md).

Source-folder launchers support interactive operation. The current source has
28 commands, including the five [local GIS commands](#local-gis-commands).
The October 20, 2026 rebuild adds nine wildfire commands and their zone seed.
Installers include shared datasets. Service ZIPs include the wildfire and landslide reference seeds; EBMUD data remains a separate download.
See [deployment requirements](../INSTALL.md#gis-source-deployment).

## Multiple channels and program assignments

Use [MULTI_CHANNEL_GUIDE.md](MULTI_CHANNEL_GUIDE.md) for the complete change list,
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

`timeout` bounds connection establishment in seconds (default 30; range 1�300).
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
| `!traffic` | California route number 1–999 | Active Caltrans highway restrictions |
| `!rivers` | Latitude and longitude | CDEC/NOAA river stations within 15 miles |
| `!uv` | Coordinates, US ZIP, or city and state | Current UV index and risk category |
| `!lightning` | Coordinates, US ZIP, or city and state | NWS lightning potential in the next 24h, stated chance, adjustable timezone |
| `!trail` | Name + attribute, or attribute near coordinates [miles] | Trail details, policy filters, or explicit full info |
| `!rec` | Name + attribute, or attribute near coordinates [miles] | Recreation details and amenity filters |
| `!peak` | Name + attribute, or near coordinates [miles] | Peak elevation, location, or explicit full info |
| `!park` | Name + attribute, or near coordinates [miles] | Park status, agency, trails, and recreation |
| `!boundary` | Optional category + coordinates, near coordinates [miles], or trail NAME | Mapped containment, nearest areas, or trail overlap |
| `!firezone` | Zone ID, coordinates, ZIP or city/state | Fire-weather zone and current warning/watch status |
| `!fires` | Zone/location, optional page or near-distance query | Reported incidents and latest mapped perimeter timing |
| `!fire` | Exact incident ID or unambiguous name | Containment, source attribution and last-known status |
| `!firewx` | Zone/location, optional page | Zone fire-weather forecast and alerts |
| `!firewarn` | Zone/location | Red Flag Warnings and Fire Weather Watches |
| `!firedata` | Category and zone/location | Supporting observations, detections, outlooks and reference features |
| `!firealarm` | on location, status, off | Temporary wildfire-change monitoring |
| `!slidewarn` | ZIP, city, GPS | California NWS alerts mentioning landslide/debris-flow hazards |
| `!slidealarm` | on location, status, off | Temporary California and Nevada landslide-alert monitoring |
| `!slideinfo` | ZIP, city, GPS | Nearest eligible California USGS monitoring station |
| `!smoke` | ZIP, city/state, GPS | Point smoke coverage and nearby air quality |
| `!firedanger` | ZIP, city/state, GPS | Local ERC percentile, fuels and warnings |
| `!heatadv` | Coordinates, US ZIP, or city and state | Active NWS heat warnings, watches, and advisories |
| `!floodwarn` | Coordinates, US ZIP, or city and state | Active NWS flood alerts |
| `!floodalarm` | Coordinates, US ZIP, or city and state | Monitor flood-alert changes for four hours |
| `!snowpack` | California coordinates, ZIP, or city | Nearest-station snow depth and next-24h snowfall |

`!aqi` requires `AIRNOW_API_KEY`. The other included commands require no API
key. AQI, traffic, river, UV, heat-alert, flood-alert, and snowpack lookups require internet access.
Detailed input formats, sources, responses, and limitations are documented below.

## Start

Interactive source-folder operation requires 64-bit Python 3.11 or newer.

1. Open this folder and run **setup.cmd** once on a new computer.
2. Run **run.cmd** to start the bundled broker and radio responder.
3. Configure the radio connection. The default serial mode detects one attached
   USB device; BLE and TCP settings are described above.
4. Send `!status` or `!time` on **#autatestbot** from another MeshCore node.

Example reply: `@Alice Local command service is running.`

Setup creates this folder's `.venv`. To use another computer, copy the source folder
without `.venv`, `runtime` or `__pycache__`, and run setup.cmd to create its environment.
Virtual environments are not portable.
Setup requires internet access; normal operation uses the local broker and configured node.

The node must run companion firmware supporting the selected interface and have the configured channels
(default `#autatestbot`). Startup verifies channel names and keys and does not create
channels or fall back to Public. Use `channel_setup.py` explicitly for provisioning.
Serial, BLE and TCP selection are supported. USB serial detection is the default.

Keep the console open. Ctrl+C stops the application and its owned broker. The source
launcher runs in the foreground. Use the OS installer above for unattended Windows Service operation.
Administrator privileges are not normally needed. Launchers use Windows PowerShell
5.1 and do not change execution policy
permanently. On systems where organizational policy blocks scripts, that policy
still applies.

In serial mode with `serial_port: "auto"`, no detected USB serial device or multiple candidates
produces a clear error. Connect the intended Companion Node or set `serial_port`
to a specific device when several USB serial devices are attached. Detection uses
USB metadata, then the MeshCore connection verifies the selected device; it does
not guess which of several devices is the radio. A restart rescans the current
ports, including after COM or tty numbering changes.

## Independent settings

Only this folder's `config.json` controls this copy:

| Setting | Windows copy |
| --- | --- |
| MQTT host | 127.0.0.1 |
| MQTT port | 1884 |
| Topic prefix | meshcore/windows |
| MQTT client ID | meshcore-windows-bridge |
| Radio channel | #autatestbot |
| Serial port selection | auto |
| Python environment | .venv/ |
| Packet/request database | runtime/bridge.sqlite3 |
| CLI configuration/history | runtime/home/.config/meshcore/ |

Port 1884 and the separate topic prefix/client ID prevent collisions with the Linux
package's MQTT defaults.
Only one application can own a given USB COM device at a time. If running both copies,
use separate radios. Two bots listening on the same channel can each reply to a request.

## Windows commands

Run these in Command Prompt from this folder (or use a full path to run.cmd):

```bat
setup.cmd
run.cmd
run.cmd ports
run.cmd broker
run.cmd watch
run.cmd cli infos
verify.cmd
```

`run.cmd` defaults to bridge/responder mode. `broker` runs the local broker without
opening a radio connection. `watch` prints bridged MQTT events as JSON lines. Stop the bridge before
using `cli` to open the same radio separately. PowerShell users may invoke the same
files with `.\`, for example `.\run.cmd ports`.

If Python is not detected, provide its full path:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -PythonExe "C:\Path\To\Python\python.exe"
```

## Preset scripts and tagged responses

Edit the `responder.commands` map in this copy's config.json and restart:

```json
"commands": {
  "!status": {"script": "scripts/status.py", "args": [], "channels": ["default"]},
  "!time": {"script": "scripts/time_now.py", "args": [], "channels": ["default"]}
}
```

Matching is exact and case-sensitive after trimming outer whitespace. Scripts must
be existing .py files inside this folder or the configured external
`program_directory`; use `programs/NAME.py` for external programs. Arguments are fixed configuration values;
received text is never executed as a shell command. The script runs in this folder
using this copy's Python environment. Print the answer to stdout without an @ prefix.

The service saves the sender name from the channel message before executing the
script, then adds `@SENDERSUSERNAME` and sends through the MeshCore CLI's existing
connection on the same channel. Names containing spaces are preserved. Channel
names/displayed usernames are not authenticated user identities.

Scripts receive JSON on stdin with id, sender, phrase, channel_id, channel_name, channel_index
and sender_timestamp. Environment variables also provide MESHCORE_SENDER,
MESHCORE_CHANNEL, MESHCORE_CHANNEL_ID, MESHCORE_CHANNEL_INDEX, MESHCORE_PHRASE and MESHCORE_REQUEST_ID.

Newlines in stdout become spaces. Replies are split into at most four 150-byte parts
by default, each starting with @name. A command may set a higher limit;
`!heatadv`, `!floodwarn`, and `!floodalarm` allow 12 parts; `!lightning` allows 64 for forecast windows. Excess output ends with `...`. Scripts default to a
20-second timeout and 65536-byte output limit. Errors produce short tagged replies;
stderr diagnostics are saved locally. Scripts should finish in the foreground;
Windows timeout handling terminates the script process, not arbitrary detached children.

Duplicate suppression and sender names persist in SQLite. Defaults allow one request
per sender per channel every 30 seconds and reject stale messages older than five minutes, missing
names/timestamps, local-node echoes and @-prefixed replies. Keep radio clocks accurate.
Up to 50 requests can wait globally, with at most 20 per channel by default. Interrupted execution/sending is not automatically repeated,
since a side effect or transmission may already have happened. Radio acceptance is not
proof of remote receipt. Set responder.enabled to false to disable automatic replies.

## MQTT interface

The local broker listens only on this computer at 127.0.0.1:1884, with no password.
It starts and stops with the bridge unless an existing listener is reused. Running
broker in another console keeps MQTT available independently.

| Topic | Purpose |
| --- | --- |
| meshcore/windows/events/<event_name> | Radio payloads and metadata |
| meshcore/windows/events/bot_reply | Automatic reply accepted by the local radio |
| meshcore/windows/command | Non-retained JSON command requests |
| meshcore/windows/results/<id> | CLI command output/status |
| meshcore/windows/errors | Rejected command details |
| meshcore/windows/status | Retained online/offline status and last will |

Example request to meshcore/windows/command:

```json
{"id":"info-001","argv":["infos"]}
```

Supported MQTT commands: infos, ver, contacts, self_telemetry, clock, msg, chan. Use a
new ID for each intentional request. Retained requests are ignored. Commands and bot
reply parts share the configured 15-second spacing. Channel responder triggers come
from decoded radio events, not MQTT event replays. With a channel registry, only channels with `mqtt_export: true` export decoded
messages and replies with available metadata. Raw/unclassified and unknown-channel
traffic is suppressed; allowed node/device telemetry remains available.
Known secret fields are redacted; binary fields have explicit hex encoding.

The event outbox survives restarts and uses QoS 1. Consumers should deduplicate event
UUIDs. MQTT reconnects automatically; monitor disk usage during outages. Broker state
is in memory. Commands use live subscriptions and may be missed while offline. A detected radio disconnect stops the bridge; the installed service manager
restarts it. Source-folder launchers require a manual restart.

For an external broker set local_broker to false and edit mqtt. Authentication uses
MESHCORE_MQTT_USERNAME and MESHCORE_MQTT_PASSWORD. TLS uses tls=true with an optional
ca_file relative to this folder. Restrict command-topic publishing to trusted users.

## Verification

Run `verify.cmd` for automated tests and dependency checks. Tests cover script
execution, same-channel tagged replies, duplicate suppression, timeouts, output
limits, persistent state, flood-alarm scheduling, and unattended configuration.
They use sample provider data and a real loopback broker with simulated radio events.
These checks do not establish physical radio delivery or installation and reboot
behavior on target hardware.

The optional read-only check_live.py disables
the responder and requires one discovered COM device and a free configured broker port.
Run it with `.venv\Scripts\python.exe check_live.py` while the bridge is stopped.

Pinned dependencies are in [requirements.txt](requirements.txt). Review the internal
CLI adapter when changing dependencies. The tests and live check exit and stop their brokers;
the application is not left running after validation.

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

```powershell
$env:AIRNOW_API_KEY = "YOUR_AIRNOW_API_KEY"
.\Start-Service.exe
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
the configured tagged-message splitting and length limits.

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
long reports may be truncated with `...`.

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

Every reply part starts with the saved sender's @name and goes to the same channel.
Configured cooldowns, duplicate suppression and reply limits apply: at most four
150-byte parts by default, with excess output truncated using `...`. Long results
therefore favor the nearest stations. Increase max_reply_parts in config.json if
needed, accounting for the configured 15-second spacing between transmissions.

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

The reply bodies are:

```text
Lightning Strike Warning for <location> at <time window> (<stated chance/level>)
No Lightning expected for <location> in the next 24h
```

Illustrative reply: `Lightning Strike Warning for Sacramento at 2026-10-08 13:00 PDT-16:00 PDT (slight chance thunderstorms)`.
Multiple windows retain their individual chance levels. Every stated chance counts,
including slight chance and a numeric thunderstorm probability as low as 1%.
Qualitative coverage and numeric probability are both shown when NWS supplies both.
If an alert states no chance level, the reply says `chance not stated`; it does not
invent a percentage. Rain probability is not lightning probability.

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
`Lightning Strike Warning` is this program's summary label. It combines actual
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
the incoming channel, and allows up to 64 parts for changing chances/windows;
output beyond that limit is visibly truncated by the responder. These tunables
are in the script and the command's configuration entry.

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

The standalone program prints these exact reply bodies, depending on the result:

```text
There is no Heat Advisories for <location>
Advisory: Extreme Heat Warning for <location>
Advisory: Extreme Heat Watch for <location>
Heat Advisory for <location>
```

When multiple types apply, every distinct type is included in the listed order:
warning, watch, advisory. The script prints one line per type; the responder joins
lines with spaces, prefixes each message with `@<sender>`, and replies on the
requesting channel. Up to 12 parts preserve combined results and long location
names. This command performs one lookup per request.

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

## Flood alerts: !floodwarn

[One-time flood-alert responses](COMMAND_REFERENCE.md#cmd-floodwarn).

Send on a channel assigned to this command (default `#autatestbot`):

```text
!floodwarn 38.5816, -121.4944
!floodwarn 38.5816 -121.4944
!floodwarn 95814
!floodwarn Sacramento
!floodwarn Reno NV
!floodwarn Reno, Nevada
!floodwarn Albany New York
```

Cities default to California; a trailing full state name or two-letter abbreviation
(case-insensitive, with or without a comma) overrides it. US ZIP and ZIP+4 codes
work nationwide. Coordinates are latitude first. City/ZIP lookups use a representative
point, not the entire city or ZIP boundary; use GPS for a precise location. Exact city
names are required, and the largest same-name settlement in the state is selected.

When none of the four tracked alert types is active, the reply preserves the supplied
location (apart from extra whitespace):

```text
@Alice no flooding events declared for Sacramento
```

When alerts apply, the supplied location precedes one line per active type, with
repeated alerts of the same type combined. Types are ordered as follows:

- Flash Flood Warning 🟥 - Life-threatening flash flooding is imminent or occurring. Move to higher ground immediately.
- Flood Warning 🟧 - Flooding is imminent or occurring. Take necessary precautions now.
- Flood Advisory 🟨 - Minor flooding expected. May cause inconvenience but not typically life-threatening.
- Flood Watch 🟦 - Conditions favorable for flooding. Stay alert and be ready to take action.

The responder adds the saved sender's `@name` to every part, flattens newlines, and
returns the result on the same channel. This command allows up to **12 parts of 150
bytes** so all four descriptions fit even with a long sender name. `!floodalarm`
also allows 12 parts; other commands use the four-part default. The configured
15-second send spacing applies.

[FlashFloodWarn](https://www.flashfloodwarn.com/#about) identifies the National
Weather Service API as its alert source. This script calls that same official
[NWS API](https://www.weather.gov/documentation/services-web-api) directly using
`/points/{latitude},{longitude}` to verify coverage, then `/alerts/active?point=...`
for point/zone matching. It does not scrape FlashFloodWarn's national totals or
expired-warning archive. It reports the four types above; coastal/lakeshore alerts
and general flood statements are outside this command's scope. Expired, ended,
cancelled, test, and not-yet-effective messages are excluded. An already issued
watch is included even if the forecast flooding starts later.

No API key or additional Python dependency is required. City/ZIP resolution uses
[Open-Meteo](https://open-meteo.com/en/docs/geocoding-api) / GeoNames, as with `!uv`;
the free geocoder is for non-commercial use. The host needs internet access. Failed,
malformed, or incomplete responses produce an availability message, never a
no-events assertion. Coordinates outside NWS coverage produce a coverage error.
Each HTTP request has a 12-second timeout; the command has a 45-second overall limit.

Run directly from this folder:

```text
python scripts/flood_warn.py Sacramento
python scripts/flood_warn.py 95814
python scripts/flood_warn.py "Reno NV"
python scripts/flood_warn.py 38.5816 -121.4944
python -m unittest discover -s tests -p "test_floodwarn.py"
```

Keep `scripts/uv_index.py` alongside `scripts/flood_warn.py`; the flood lookup
uses its location parser.

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
@Alice Snowpack: Current: 12in | Next 24h: 4in | Station: Snow Creek 2.3mi.
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
65-second overall script timeout. Configured cooldowns and message splitting apply.

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

[Quick monitoring instructions](BOT_USER_GUIDE.md#monitoring) | [Subscription behavior and responses](COMMAND_REFERENCE.md#cmd-floodalarm).

```text
!floodalarm 38.5816, -121.4944
!floodalarm 95814
!floodalarm Sacramento
!floodalarm Reno NV
!floodalarm Reno Nevada
```

Uses the same location rules as `!floodwarn`, including the California default.
An accepted, syntactically valid request immediately queues this exact reply:

```text
@Alice Flood Alarm is set for requested location.
```

The acknowledgment has its own worker and does not wait for a weather lookup.
Configured sender cooldowns, duplicate/stale-message checks, channel selection, and
radio spacing apply; a busy radio can delay actual transmission. The
acknowledgment confirms registration. The subsequent lookup verifies the location.

### Monitoring rules

Only `!floodalarm` enrolls or renews one saved location per sender and channel.
The service acknowledges registration before checking the location. The following
flow describes service-managed checks, with lookups performed one at a time.
Slow requests, queued work, or radio spacing can delay checks and notifications.

```text
Accepted !floodalarm --> Save or renew subscription --> Acknowledge
                                   |
                                   v
                    First successful lookup: silent baseline
                                   |
                      Scheduled lookup every 20 minutes
                                   |
          +------------------------+-------------------------+
          |                        |                         |
     Types unchanged          Types changed              Lookup failed
          |                        |                         |
     Keep baseline       Tagged same-channel reply    One outage notice;
          |                        |                  retain last reading
          +------------------------+-------------------------+
                                   |
                      Next check while subscription is current

Four hours after last accepted enrollment/renewal --> Expire; stop checks
```

Comparison uses the set of four supported alert types, including when all types
clear. Bulletin IDs, issue times, and wording alone do not trigger notifications.
Failures retry at the next scheduled check; one availability notice is sent per
failure episode. Successful recovery is compared with the last good reading.
An error never establishes that no flood alerts exist.

Each accepted renewal resets the full four-hour deadline. A replacement location
starts a fresh baseline; renewal of the same active location retains its baseline
and scheduled check. Late messages cannot overwrite a newer call's location.
Checks and outgoing notifications recheck expiry and superseded-request validity.
`!floodwarn` performs one lookup without changing an alarm location or timer;
other commands do not renew the timer.

Subscriptions survive restarts in **`runtime/bridge.sqlite3`**, table
**`flood_subscriptions`**, using Python's built-in SQLite library. Stored fields
include channel, username, last requested location, last-heard time, enabled state,
next-check time, last successful alert types/time, and lookup error. Expired rows
retain their last location for review but are inactive. Restarting never extends
the four-hour deadline, and missed checks are not replayed in a burst.

The service must stay running and connected to perform checks/send notifications.
Interrupted or failed radio sends are logged and are not automatically replayed.
Usernames are MeshCore display names; two nodes using the same name on the same
channel share one subscription because identity uses the display name and channel.

### Where to adjust the algorithm

| File / function | What to review or change |
| --- | --- |
| [`flood_alarm.py`](flood_alarm.py), top constants | `CHECK_INTERVAL = 20 * 60`, `MAX_AGE = 4 * 60 * 60`, polling interval, acknowledgment text. |
| `FloodAlarms.remember()` | One row per sender/channel; enrollment, renewal, location replacement, older-message rejection. |
| `FloodAlarms.check_one()` | Initial baseline, scheduling, alert-type comparison, error handling, four-hour expiry. |
| `FloodAlarms.is_current()` | Reject an expired subscription or a result from a superseded request. |
| [`responder.py`](responder.py), `accept()` / `process_one()` / `run()` | Save/renew accepted alarm locations, acknowledge without HTTP, and start independent workers. |
| `Responder.read_flood_status()` / `send_flood_change()` | Bounded lookup subprocess, structured result validation, tagged notifications. |
| [`service.py`](service.py), `send_reply()` | Recheck alarm validity after waiting for the radio, before sending. |
| [`scripts/floodalarm.py`](scripts/floodalarm.py), `main()` | Dedicated JSON-reading subprocess for alarm checks; enrollment and timers remain in the service. |
| [`scripts/flood_warn.py`](scripts/flood_warn.py), `snapshot()` / `format_status()` | Shared NWS lookup, structured alert types, exact wording and colored squares. |

The source uses visible comments named `TIMING SETTINGS`, `ENROLLMENT`, `EXPIRY`,
`CHANGE DETECTION`, `OUTAGE`, and `ALARM EXPIRY` to identify the corresponding sections.
The monitor runs `scripts/floodalarm.py LOCATION` for JSON readings. Direct
execution reads one snapshot and does not create a subscription or print a false
enrollment acknowledgment. The compatible `flood_warn.py --snapshot` interface
remains available; normal `!floodwarn` and its direct CLI output remain text. There is no extra dependency or separate daemon.

Restart the service after updating the Python files and `config.json`.
Test with `python -m unittest discover -s tests -p "test_floodalarm.py"`, or run the full test suite.

The flood-alarm tests cover simulated timing, restart persistence, background
workers, and subprocess results. Simulated tests do not establish live four-hour
monitoring or radio delivery.

## Local GIS commands

[Quick GIS examples](BOT_USER_GUIDE.md#gis) | [Complete GIS query grammar](COMMAND_REFERENCE.md#gis-syntax).

The five GIS commands read the shared EBMUD snapshots without network requests.
Names are searched locally; city/ZIP geocoding and live closure reporting are
not provided. Coordinates are entered as latitude followed by longitude.

| Command | Example | Result |
| --- | --- | --- |
| `!trail` | `!trail Bear Creek dogs` | Only the recorded dog policy; `info` requests the full summary. |
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
October 11, 2026. The responder adds the sender's `@name` and splits long output
into radio messages on the requesting channel. No snapshot footer is appended.
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
Closest, map distance: Trail: Oursan (0.84 mi); dogs Yes.
```

**`!trail dogs near 37.90 -122.20 5`**

```text
Within 5 mi, map distance: Trail: Oursan (0.84 mi); dogs Yes; Trail: Old San Pablo Trail (0.97 mi); dogs Limited to Park Hours; Trail: Hampton (2.65 mi); dogs Yes; +11 more.
```

**`!rec water near 37.90 -122.20`**

```text
Closest, map distance: Recreation: Tilden Steam Trains Park Entrance (1.82 mi); water Yes.
```

**`!boundary parks near 37.90 -122.20`**

```text
Closest, map distance: Park: Tilden (1.52 mi).
```

For a full summary, use `!trail Bear Creek info`,
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
| `max_results` | 3 | Maximum listed results or associations; omitted matches are counted. |
| `max_reply_bytes` | 480 | UTF-8 output budget before sender prefixes; truncation retains any geometry-repair note. |
| `description_characters` | 100 | Maximum source description length; zero omits it. |
| `include_unnamed_peaks` | false | Include unnamed peak records with source-ID labels. |
| `projected_crs` | EPSG:32610 | Metric UTM zone 10N for spatial calculations. |
| `search_bounds` | [-126, 0, -120, 84] | Accepted coordinate extent, ordered west/south/east/north. Projection and bounds must be changed together for other regions. |

Command timeout (30 seconds), channel assignments, and reply parts (6) remain in
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
| Reply omits detail | Review `max_results`, `description_characters`, `max_reply_bytes`, and the command's `max_reply_parts` together. |

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
