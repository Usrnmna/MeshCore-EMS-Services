# MeshCore channel command service

**Current release:** [v0.1.1-alpha](RELEASE_NOTES.md)

Messages on **#autatestbot** run preset local Python scripts and automatically return
stdout to the same channel, starting with **@SENDERSUSERNAME**.

Example:

```text
Alice sends on #autatestbot: !status
Service runs: scripts/status.py
Service replies on #autatestbot: @Alice Local command service is running.
```

The Linux computer running the service executes the scripts. The installed MeshCore
CLI owns one USB connection selected through **-S**. Replies use its channel-send
function on that same connection. MQTT commands and automatic replies share a
serialized, rate-limited command path. All radio events still publish to MQTT.

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

## Linux setup

Copy this folder to the computer attached to the USB serial companion node.
Python 3.11+ with venv and serial-device access are required. The node must already
contain a channel named exactly **#autatestbot**.

```bash
cd /your/path/meshcore_mqtt_service
bash setup.sh
bash run.sh
```

Choose the discovered `/dev/ttyACM*` or `/dev/ttyUSB*` device in the -S selector.
Use arrow keys, Tab to OK, then Enter. The program reads the node's channel list and
resolves #autatestbot to its actual index. It fails explicitly if absent or duplicated;
it never falls back to public channel 0 or implicitly creates a channel.

Ctrl+C stops the service. Setup creates `.venv-linux` here; a copied Windows `.venv`
is not reused. Launchers work from any current directory. If serial access is denied,
configure your Linux user's device permissions, commonly through the distribution's
`dialout` group, and sign in again. Use the separate `meshcore_mqtt_service_windows`
package on Windows. Scripts run on the bridge's host; no SSH is used.

## Configure phrases and scripts

Edit the `responder` section of `config.json`, then restart:

```json
"commands": {
  "!status": {"script": "scripts/status.py", "args": []},
  "!time": {"script": "scripts/time_now.py", "args": []}
}
```

Included scripts provide status, UTC time, AQI, traffic, river, UV, and flood-alert
results. Extend the map with your own phrases/scripts. Matching is exact and
case-sensitive after trimming outer whitespace.
Substrings, extra arguments and unknown phrases do not execute anything. Only decoded
messages received on the configured channel trigger scripts; direct messages, raw
packet logs and MQTT event replays do not.

Scripts must be existing `.py` files inside this folder, including after symlink
resolution. Fixed arguments may be set in `args`. Received message text never becomes
a shell command or executable path. Scripts use the local virtual environment and
run with this folder as their working directory.

**Print the answer to stdout without the @name prefix.** The service adds the prefix
and turns newlines into spaces. Long answers become at most four 150-byte messages by
default, each starting with @name. A command may set a higher limit; `!floodwarn`
allows 12 parts. Excess output is truncated with `...`. Empty output,
script errors and timeouts produce short tagged explanations. Stderr diagnostics
are saved locally, not broadcast.

Scripts may read JSON context from stdin:

```python
import json
import sys
request = json.load(sys.stdin)
print(f"Request from {request['sender']} on {request['channel_name']}.")
```

Context includes `id`, `sender`, `phrase`, `channel_name`, `channel_index` and
`sender_timestamp`. The equivalent environment variables are `MESHCORE_SENDER`,
`MESHCORE_CHANNEL`, `MESHCORE_CHANNEL_INDEX`, `MESHCORE_PHRASE` and
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
Each sender may start one request per 30 seconds. Up to 50 requests can wait.

Queued requests survive restarts but expire when stale. Requests interrupted during
execution or sending are marked `interrupted` and are not automatically repeated,
because side effects or transmissions may already have happened. Failed sends are
recorded without automatic retry. `sent` means the local radio accepted the reply,
not that another node received it. Relevant limits are configurable under `responder`.

## Local MQTT and modes

The bundled broker starts with the bridge at **127.0.0.1:1883**, accepts local clients
without a password, and listens only on this computer. It stops with the bridge.
Run `broker` in another terminal to keep MQTT alive independently; the bridge reuses
an existing listener on that port. This is a foreground application, not an OS boot
service, and radio startup uses an interactive selector.

```bash
bash run.sh ports
bash run.sh bridge
bash run.sh broker
bash run.sh watch
bash run.sh cli infos
```

`watch` consumes
bridged MQTT events as JSON lines and can run beside the bridge. Stop the bridge
before opening another USB connection with `cli`. Set `responder.enabled` to false
to run only the original bridge functionality.

| Default topic | Purpose |
| --- | --- |
| meshcore/usb/events/<event_name> | Radio payload, attributes, UTC receipt time, UUID and serial port |
| meshcore/usb/events/bot_reply | Automatic reply accepted by the radio |
| meshcore/usb/command | Incoming non-retained JSON CLI request |
| meshcore/usb/results/<id> | CLI request output/status |
| meshcore/usb/errors | Rejected MQTT commands |
| meshcore/usb/status | Retained online/offline status and last will |

Payloads preserve available text, timestamps, channel, RSSI, SNR, paths and other
fields. Missing information is not invented. Bytes use an explicit hex object;
known secret fields are redacted. Raw packets and decoded messages are separate.

Example MQTT request:

```json
{"id":"info-001","argv":["infos"]}
```

Supported MQTT commands: infos, ver, contacts, self_telemetry, clock, msg and chan.
Use a distinct request ID for each intentional command. Stored IDs prevent repeated
execution after redelivery/restart. Retained commands are ignored. `command_interval`
spaces commands and automatic reply parts by 15 seconds by default. Restrict access
to the command topic to trusted broker users.

Events use a durable SQLite outbox and QoS 1; MQTT reconnects automatically. Consumers
should deduplicate event UUIDs. Broker sessions and retained messages are in memory.
Monitor disk space during broker outages. Commands use live subscriptions; offline
commands are not guaranteed to execute. USB disconnection stops the bridge; restart
and select the device again with -S.

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

All 109 tests passed in this folder on Windows after workspace cleanup,
including flood-alarm and snowpack regression tests. Native Linux execution and automatic
over-the-air reply delivery have not yet been verified. `check_live.py` remains an
optional read-only USB/MQTT check: it explicitly disables the responder, requires
one discovered serial device and an unused broker port, and runs only MQTT infos.

Pinned dependencies: meshcore-cli 1.6.4, MeshCore 2.3.11, Paho MQTT 2.1.0 and aMQTT
0.12.1. The adapter uses internal async CLI interfaces; check compatibility before
upgrading them. All code, scripts, dependencies and runtime files stay in this folder.


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

```bash
export AIRNOW_API_KEY="YOUR_AIRNOW_API_KEY"
bash Start-Service.sh
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
python -m unittest discover -s tests -p "test_floodwarn.py"
```

Restart the service using its existing launcher to load the command. Keep
`scripts/uv_index.py` alongside `scripts/flood_warn.py`; its existing location
parser is reused. No firmware changes or device flashing are required.

Validation for this addition: all 66 tests passed in each service folder on the
Windows host. Live city, ZIP, GPS, abbreviated-state, and full-state lookups passed;
Athens, Ohio returned a Flash Flood Warning and Flood Watch during verification.
An unsupported point returned a coverage error. Native Linux execution and
physical MeshCore radio delivery remain unverified; no hardware was flashed.

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
65-second overall script timeout. Existing cooldowns and message splitting apply.
Restart the running service to load the new command configuration.

```text
python scripts/snowpack.py "39.3279, -120.1833"
python scripts/snowpack.py 96161
python scripts/snowpack.py Truckee
python -m unittest discover -s tests -p "test_snowpack.py"
```

Validation: all 86 tests passed in each package on the Windows host, and both
Python environments passed dependency checks. Live California city, ZIP, and GPS
lookups returned station depths and forecasts; Nevada city, ZIP, and GPS requests
were rejected. No service restart, radio transmission, or native Linux execution
was performed for this addition.

## ZIP package

The distribution ZIP includes this service folder, current snowpack code,
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
Existing sender cooldowns, duplicate/stale-message checks, channel selection, and
radio spacing still apply; a busy radio can delay actual transmission. The
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
Both packages passed **109 tests on the Windows host**, including simulated time,
restart persistence, background workers, subprocess JSON, and existing MQTT tests.
The four-hour behavior was tested with a simulated clock. No live four-hour run,
native Linux run, radio transmission, firmware change, or service restart was done.
