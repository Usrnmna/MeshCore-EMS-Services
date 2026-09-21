# MeshCore command service for Windows 10 Pro x64

This is an independent Windows copy. It does not load code, configuration, Python
packages or runtime databases from the original Linux service folder.

## Included commands

| Command | Input | Service |
| --- | --- | --- |
| `!status` | None | Local service health |
| `!time` | None | Current UTC time |
| `!aqi` | Latitude and longitude | AirNow PM2.5 AQI and nearest monitor |
| `!traffic` | California route number 1–999 | Active Caltrans highway restrictions |
| `!rivers` | Latitude and longitude | CDEC/NOAA river stations within 15 miles |
| `!uv` | Coordinates, US ZIP, or city and state | Current UV index and risk category |
| `!floodwarn` | Coordinates, US ZIP, or city and state | Active NWS flood alerts |

`!aqi` requires `AIRNOW_API_KEY`. The other included commands require no API
key. AQI, traffic, river, UV, and flood-alert lookups require internet access.
Detailed input formats, sources, responses, and limitations are documented below.

## Start

64-bit Python 3.11 or newer must be installed. This copy was tested with Python
3.13.0 (AMD64) and Windows 10 build 19045.

1. Open this folder and run **setup.cmd** once on a new computer.
2. Run **run.cmd** to start the bundled broker and radio responder.
3. In the MeshCore CLI **-S** selector, choose the discovered USB **COM** device.
   Use the arrow keys, Tab to OK, then Enter.
4. Send `!status` or `!time` on **#autatestbot** from another MeshCore node.

Example reply: `@Alice Local command service is running.`

This copy already has its own `.venv` installed on the current computer. On another
computer copy the source folder without `.venv`, `runtime` or `__pycache__`, and run
setup.cmd to create a fresh environment. Virtual environments are not portable.
Setup requires internet access; normal operation uses the local broker and USB node.

The node must run serial companion firmware and already have a channel named exactly
`#autatestbot`. The application discovers that channel's index; it does not create
channels or fall back to public channel 0. BLE selection is disabled. No COM number
is hard-coded or saved.

Keep the console open. Ctrl+C stops the application and its owned broker. This is a
standalone foreground application, not a registered Windows Service; the -S selector
requires an interactive desktop session. Administrator privileges are not normally
needed. Launchers use Windows PowerShell 5.1 and do not change execution policy
permanently. On systems where organizational policy blocks scripts, that policy
still applies.

## Independent settings

Only this folder's `config.json` controls this copy:

| Setting | Windows copy |
| --- | --- |
| MQTT host | 127.0.0.1 |
| MQTT port | 1884 |
| Topic prefix | meshcore/windows |
| MQTT client ID | meshcore-windows-bridge |
| Radio channel | #autatestbot |
| Python environment | .venv/ |
| Packet/request database | runtime/bridge.sqlite3 |
| CLI configuration/history | runtime/home/.config/meshcore/ |

Port 1884 and the separate topic prefix/client ID prevent collisions with the original
copy's MQTT defaults. The original config.json and files were left unchanged.
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
opening USB. `watch` prints bridged MQTT events as JSON lines. Stop the bridge before
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
  "!status": {"script": "scripts/status.py", "args": []},
  "!time": {"script": "scripts/time_now.py", "args": []}
}
```

Matching is exact and case-sensitive after trimming outer whitespace. Scripts must
be existing .py files inside this folder. Arguments are fixed configuration values;
received text is never executed as a shell command. The script runs in this folder
using this copy's Python environment. Print the answer to stdout without an @ prefix.

The service saves the sender name from the channel message before executing the
script, then adds `@SENDERSUSERNAME` and sends through the MeshCore CLI's existing
connection on the same channel. Names containing spaces are preserved. Channel
names/displayed usernames are not authenticated user identities.

Scripts receive JSON on stdin with id, sender, phrase, channel_name, channel_index
and sender_timestamp. Environment variables also provide MESHCORE_SENDER,
MESHCORE_CHANNEL, MESHCORE_CHANNEL_INDEX, MESHCORE_PHRASE and MESHCORE_REQUEST_ID.

Newlines in stdout become spaces. Replies are split into at most four 150-byte parts
by default, each starting with @name. A command may set a higher limit;
`!floodwarn` allows 12 parts. Excess output ends with `...`. Scripts default to a
20-second timeout and 65536-byte output limit. Errors produce short tagged replies;
stderr diagnostics are saved locally. Scripts should finish in the foreground;
Windows timeout handling terminates the script process, not arbitrary detached children.

Duplicate suppression and sender names persist in SQLite. Defaults allow one request
per sender every 30 seconds and reject stale messages older than five minutes, missing
names/timestamps, local-node echoes and @-prefixed replies. Keep radio clocks accurate.
Up to 50 requests can wait. Interrupted execution/sending is not automatically repeated,
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
from decoded radio events, not MQTT event replays. Both private and channel packet
events still publish with available timestamps, text, RSSI, SNR, paths and other data.
Known secret fields are redacted; binary fields have explicit hex encoding.

The event outbox survives restarts and uses QoS 1. Consumers should deduplicate event
UUIDs. MQTT reconnects automatically; monitor disk usage during outages. Broker state
is in memory. Commands use live subscriptions and may be missed while offline. USB
disconnect stops the bridge; restart it to select a COM device again.

For an external broker set local_broker to false and edit mqtt. Authentication uses
MESHCORE_MQTT_USERNAME and MESHCORE_MQTT_PASSWORD. TLS uses tls=true with an optional
ca_file relative to this folder. Restrict command-topic publishing to trusted users.

## Validation

- All 66 automated tests passed in this copy during the latest documentation update.
- The installed environment uses Windows 10 build 19045 x64 / Python 3.13.0 x64.
- setup.ps1 and run.ps1 were exercised with Windows PowerShell 5.1.
- Dependency checks passed in this folder's independent virtual environment.
- Real loopback broker tests covered script execution and same-channel tagged replies
  through the installed CLI helper with simulated radio events.
- A live read-only test connected to COM11, published radio events to the new MQTT
  namespace, and executed/returned an MQTT infos request.
- Automatic over-the-air tagged reply delivery was not tested.

Run verify.cmd to repeat automated tests. The optional read-only check_live.py disables
the responder and requires one discovered COM device and a free configured broker port.
Run it with `.venv\Scripts\python.exe check_live.py` while the bridge is stopped.

source_integrity.json and verify_original.py record/check the original folder's hashes.
They are development evidence only; normal operation never accesses the original folder.
Pinned dependencies are in requirements.txt. Review the internal CLI adapter before
upgrading MeshCore CLI versions. The tests and live check exit and stop their brokers;
the application is not left running after validation.


## AirNow AQI command

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

Set your AirNow key in the launching environment, then start/restart the service:

```powershell
$env:AIRNOW_API_KEY = "YOUR_AIRNOW_API_KEY"
.\Start-Service.exe
```

Get a key through [AirNow's API account page](https://docs.airnowapi.org/account/request/).
No API key is stored in these files. The original standalone AirNow source file is
unchanged. Each service folder contains its own independent adapted copy. The lookup
requires internet access. Missing keys/API failures produce a tagged availability
message rather than exposing HTTP response contents or credentials.

The !aqi configuration uses `input: "coordinates"` and a 60-second command-specific
script timeout. Other preset commands keep exact matching and their existing timeout.
Only validated numeric coordinate arguments are appended to the Python invocation;
arbitrary command options or shell syntax are not accepted. The inherited 30-second
per-sender cooldown still applies, including after a malformed request.

The result reports nearest-monitor PM2.5 AQI, concentration when available, rating,
station, distance, observation time and preliminary-data status. It is a monitoring
station observation, not a measurement at the submitted GPS point. Long output uses
the existing tagged-message splitting and length limits.

Both copies passed 29 offline/local tests after this change, including execution of
the AirNow script in a subprocess with sample API data. No live AirNow lookup or
new over-the-air AQI reply has been verified. Earlier original-file hash manifests
are historical snapshots and predate these explicitly requested AQI changes.


## Caltrans traffic command

On **#autatestbot**, send a highway/route number:

```text
!traffic 80
!traffic 5
!traffic 101
```

Use digits only, from 1 to 999; omit prefixes such as I-, US or SR. The bot runs its
own `scripts/highway_info.py` with that number as a positional argument. The source
program in the project's separate highway_info folder remains unchanged.

The response goes to the same channel with the sender's saved @name at the start of
every part. Active Caltrans California road restrictions retain the program's compact
format. When the report is clear, the response is exactly:

```text
@SENDERSUSERNAME No Traffic Restrictions Reported
```

No API key is needed; the computer requires internet access to Caltrans. Missing or
invalid arguments produce a tagged usage reply without running the script. Fetch
failures produce a tagged availability message, never a clear-road assertion.
The command uses `input: "route_number"` and a 30-second subprocess timeout. Existing
cooldowns, duplicate suppression, maximum reply length and part limits still apply;
long reports may be truncated with `...`.

Restart the running service with the same Start-Service launcher to load the new
command. Both folder test suites passed 35 tests on the current Windows host. Traffic
tests run the actual Python program against sample HTTP reports, covering clear
reports, active restrictions and network failures. Live Caltrans retrieval, native
Linux execution and over-the-air traffic replies have not been verified for this update.


## Nearby river stations command

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
service folders own a copy; the original standalone program remains unchanged.
The command requires internet access to CDEC and NOAA, but no API key.

The existing **15-mile radius** is retained. Matching CDEC river-stage stations are
returned nearest first, with station name/ID, distance, stage, report time, action
stage (AS) and minor flood stage (FS). Missing readings/thresholds show N/A. An empty
match produces an explicit no-matching-stations message; source/network errors
produce an availability message instead. This is a report lookup, not a prediction.

Every reply part starts with the saved sender's @name and goes to the same channel.
Existing cooldowns, duplicate suppression and reply limits apply: at most four
150-byte parts by default, with excess output truncated using `...`. Long results
therefore favor the nearest stations. Increase max_reply_parts in config.json if
needed, accounting for the existing 15-second spacing between transmissions.

The new `coordinate_style: "options"` configuration maps validated coordinates to
--latitude and --longitude; !aqi continues using positional arguments. The river
command has a 40-second subprocess timeout around its two 15-second HTTP requests.
To choose a different fixed radius, add `"--radius", "30"` to this command's args.
Additional flags sent over the radio are not accepted.

The program still returns full JSON when run directly without --mesh-text, including
raw_report_line, all stage-history values, coordinates and thresholds. The compact
mesh format is enabled only through this command's configured --mesh-text argument.

Restart the service using its existing Start-Service launcher to load !rivers.
Both copies passed 42 tests on the current Windows host, including real subprocess
execution with sample CDEC/NOAA responses, GPS forwarding, missing readings, empty
results and failures. Live source retrieval, native Linux execution and over-the-air
river replies have not been verified for this update.

## Current UV index: !uv

Send on the configured channel (default #autatestbot):

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
API key are required. Restart the service to load the new command configuration.

UV data: [CurrentUVIndex.com](https://currentuvindex.com/),
[API](https://currentuvindex.com/api), CC BY 4.0. Only `now.uvi` is reported.
Risk bands use the unrounded reading: below 3 Low, 3 to below 6 Moderate,
6 to below 8 High, 8 to below 11 Very-High, and 11+ Extreme.
The API allows 500 requests per public IP per day, resetting at 00:00 UTC.
Each request fetches a fresh reading; repeated requests count against that limit.
Location lookup uses [Open-Meteo](https://open-meteo.com/en/docs/geocoding-api)
and [GeoNames](https://www.geonames.org/). The free Open-Meteo endpoint is for
non-commercial use. Coordinates bypass location lookup.

Offline checks: `python -m unittest test_uv`.


## Flood alerts: !floodwarn

Send on the configured channel (default `#autatestbot`):

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
bytes** so all four descriptions fit even with a long sender name. Other commands
retain their existing four-part default. The existing 15-second send spacing applies.

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
python -m unittest test_floodwarn
```

Restart the service using its existing launcher to load the command. Keep
`scripts/uv_index.py` alongside `scripts/flood_warn.py`; its existing location
parser is reused. No firmware changes or device flashing are required.

Validation for this addition: all 66 tests passed in each service folder on the
Windows host. Live city, ZIP, GPS, abbreviated-state, and full-state lookups passed;
Athens, Ohio returned a Flash Flood Warning and Flood Watch during verification.
An unsupported point returned a coverage error. Native Linux execution and
physical MeshCore radio delivery remain unverified; no hardware was flashed.
