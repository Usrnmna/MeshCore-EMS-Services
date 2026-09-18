# MeshCore channel command service

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
`dialout` group, and sign in again. Windows remains supported with `setup.ps1` and
`run.ps1`, selecting a COM device. Scripts run on the bridge's host; no SSH is used.

## Configure phrases and scripts

Edit the `responder` section of `config.json`, then restart:

```json
"commands": {
  "!status": {"script": "scripts/status.py", "args": []},
  "!time": {"script": "scripts/time_now.py", "args": []}
}
```

Included scripts report service status and UTC time. Extend the map with your own
phrases/scripts. Matching is exact and case-sensitive after trimming outer whitespace.
Substrings, extra arguments and unknown phrases do not execute anything. Only decoded
messages received on the configured channel trigger scripts; direct messages, raw
packet logs and MQTT event replays do not.

Scripts must be existing `.py` files inside this folder, including after symlink
resolution. Fixed arguments may be set in `args`. Received message text never becomes
a shell command or executable path. Scripts use the local virtual environment and
run with this folder as their working directory.

**Print the answer to stdout without the @name prefix.** The service adds the prefix
and turns newlines into spaces. Long answers become at most four 150-byte messages,
each starting with @name. Excess output is truncated with `...`. Empty output,
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

On Windows use `.\run.ps1` followed by the same mode/arguments. `watch` consumes
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
.venv-linux/bin/python -m unittest -v test_service.py test_responder.py test_mqtt_integration.py test_aqi.py test_traffic.py test_rivers.py
.venv-linux/bin/python -m pip check
```

On Windows use `.venv/Scripts/python.exe`. Tests run real local scripts and a real
loopback MQTT broker with simulated radio events. They verify sender retention,
same-channel replies through the installed CLI helper, duplicate suppression,
timeouts/failures, Unicode size limits and persistent request state.

The revised responder was tested on Windows. Native Linux execution and automatic
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
