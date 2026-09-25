# MeshCore command service for Windows x64

This is an independent Windows copy. It does not load code, configuration, Python
packages or runtime databases from the Linux service folder.

## OS service installers

Online installation packages support Windows x64,
Raspberry Pi ARM64, and Linux x86_64. They install Python/dependencies automatically,
include the complete workspace and reference data, and run with a saved serial port
under Windows Services or systemd. See the [installation guide](../INSTALL.md).

Source-folder launchers support interactive operation.

## Folder layout

- `service.py`, `responder.py`, `flood_alarm.py`: bridge and command handling.
- `config.json`: this installation's settings; `requirements.txt`: pinned dependencies.
- `scripts/`: command programs, also runnable directly.
- `tests/`: offline regression and loopback MQTT integration tests.
- `check_live.py`: optional USB diagnostic; run only while the service is stopped.
- `runtime/`: local request history and subscriptions; preserve during upgrades.

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
| `!floodalarm` | Coordinates, US ZIP, or city and state | Monitor flood-alert changes for four hours |
| `!snowpack` | California coordinates, ZIP, or city | Nearest-station snow depth and next-24h snowfall |

`!aqi` requires `AIRNOW_API_KEY`. The other included commands require no API
key. AQI, traffic, river, UV, flood-alert, and snowpack lookups require internet access.
Detailed input formats, sources, responses, and limitations are documented below.

## Start

Interactive source-folder operation requires 64-bit Python 3.11 or newer.

1. Open this folder and run **setup.cmd** once on a new computer.
2. Run **run.cmd** to start the bundled broker and radio responder.
3. In the MeshCore CLI **-S** selector, choose the discovered USB **COM** device.
   Use the arrow keys, Tab to OK, then Enter.
4. Send `!status` or `!time` on **#autatestbot** from another MeshCore node.

Example reply: `@Alice Local command service is running.`

Setup creates this folder's `.venv`. To use another computer, copy the source folder
without `.venv`, `runtime` or `__pycache__`, and run setup.cmd to create its environment.
Virtual environments are not portable.
Setup requires internet access; normal operation uses the local broker and USB node.

The node must run serial companion firmware and already have a channel named exactly
`#autatestbot`. The application discovers that channel's index; it does not create
channels or fall back to public channel 0. BLE selection is disabled. With the default
interactive configuration, the launcher prompts for a COM device on each start.

Keep the console open. Ctrl+C stops the application and its owned broker. The source
launcher runs in the foreground; its -S selector requires an interactive desktop
session. Use the OS installer above for unattended Windows Service operation.
Administrator privileges are not normally needed. Launchers use Windows PowerShell
5.1 and do not change execution policy
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
`!floodwarn` and `!floodalarm` allow 12 parts. Excess output ends with `...`. Scripts default to a
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

Send on the configured MeshCore channel (default `#autatestbot`):

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

1. **Only `!floodalarm` starts monitoring.** Each sender has one saved location per
   channel. A repeated `!floodalarm` renews the alarm and replaces its location.
2. After acknowledgment, take the first reading as a **silent baseline**. Check
   again every **20 minutes** while the service is running. Due lookups run one at
   a time; slow requests or a busy service can delay a check.
3. Compare the set of the four supported alert types. Notify the saved `@sender`
   on the same channel only when that set changes, including when all alerts clear.
   Changes to bulletin IDs, issue times, or wording alone do not trigger a reply.
4. Stop at **four hours since that sender's last accepted `!floodalarm` call**.
   Each new accepted `!floodalarm` overwrites that user's previous alarm location
   and resets the full four-hour limit, including when the location is unchanged.
   Checks and outgoing notifications recheck this deadline. `!floodwarn` remains
   a one-shot lookup: it never changes the alarm location or renews the timer.
5. A new location gets a fresh baseline so moving between towns is not interpreted
   as a change in flood conditions. Repeating the same location retains its baseline
   and scheduled check. Late messages cannot overwrite a newer call's location.
6. A failed lookup preserves the last successful reading. Send one availability
   notice per failure episode, then retry on the next scheduled check. A successful
   recovery is compared with the last good reading; an error never means no floods.

Subscriptions survive restarts in **`runtime/bridge.sqlite3`**, table
**`flood_subscriptions`**, using Python's built-in SQLite library. Stored fields
include channel, username, last requested location, last-heard time, enabled state,
next-check time, last successful alert types/time, and lookup error. Expired rows
retain their last location for review but are inactive. Restarting never extends
the four-hour deadline, and missed checks are not replayed in a burst.

The service must stay running and connected to perform checks/send notifications.
Interrupted or failed radio sends are logged and are not automatically replayed.
Usernames are MeshCore display names; two nodes using the same name on the same
channel share one subscription, just as replies use those display names.

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
| [`scripts/flood_warn.py`](scripts/flood_warn.py), `snapshot()` / `format_status()` | Shared NWS lookup, structured alert types, exact wording and colored squares. |

The source uses visible comments named `TWEAK HERE`, `ENROLLMENT`, `EXPIRY`,
`CHANGE DETECTION`, `OUTAGE`, and `ALARM EXPIRY` to make these sections easy to find.
The internal `--snapshot` option outputs JSON for the monitor; normal `!floodwarn`
and direct CLI output remain text. There is no extra dependency or separate daemon.

Restart the service after updating the Python files and `config.json`.
Test with `python -m unittest discover -s tests -p "test_floodalarm.py"`, or run the full test suite.

The flood-alarm tests cover simulated timing, restart persistence, background
workers, and subprocess results. Simulated tests do not establish live four-hour
monitoring or radio delivery.
