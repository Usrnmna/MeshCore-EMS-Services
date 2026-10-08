# Service Python function reference

See [the service guide](README.md) for setup and commands.
The heat command is documented under [scripts/heat_adv.py](#scripts-heat-adv-py).

This reference covers functions defined in maintained application files, including
methods and nested callbacks. Test helpers, imported library functions, and generated
files are excluded. Signatures show inputs and defaults; explanations describe the
work and important effects. Update this reference and source docstrings together
when a function changes. These descriptions are source documentation, not evidence
that a live service, device, or provider was tested.

## Modules

- [channel_setup.py](#channel-setup-py)
- [channels.py](#channels-py)
- [check_live.py](#check-live-py)
- [flood_alarm.py](#flood-alarm-py)
- [radio_connection.py](#radio-connection-py)
- [responder.py](#responder-py)
- [service.py](#service-py)
- [service_runner.py](#service-runner-py)
- [scripts/airnow_aqi.py](#scripts-airnow-aqi-py)
- [scripts/flood_warn.py](#scripts-flood-warn-py)
- [scripts/heat_adv.py](#scripts-heat-adv-py)
- [scripts/highway_info.py](#scripts-highway-info-py)
- [scripts/nearby_river_stations.py](#scripts-nearby-river-stations-py)
- [scripts/snowpack.py](#scripts-snowpack-py)
- [scripts/status.py](#scripts-status-py)
- [scripts/time_now.py](#scripts-time-now-py)
- [scripts/uv_index.py](#scripts-uv-index-py)

<a id="channel-setup-py"></a>

## channel_setup.py

[Source](channel_setup.py)

List/check radio channels or explicitly provision one configured channel. Stop the service before using the serial port. Listing never prints keys. Normal bridge startup does not call the provisioning operation.

| Function signature | Purpose and behavior |
| --- | --- |
| `async provision(mc, channel_id, config)` | Create in an empty slot, or accept an exact existing match. Never overwrite. |
| `async run(config, action, channel_id=None)` | Open the configured radio for one operator action; always disconnect. |
| `main(argv=None)` | Load settings/secrets and dispatch list, check, or explicit radio provisioning. |

<a id="channels-py"></a>

## channels.py

[Source](channels.py)

Channel registry, key validation, radio identity checks and state migration. No radio writes occur here. Provisioning is an explicit channel_setup.py action. Secrets stay in the radio/environment; only their SHA-256 identity is persisted.

| Function signature | Purpose and behavior |
| --- | --- |
| `migrate_config(config)` | Convert a legacy responder in place; never expand an existing registry. |
| `validate_channels(config)` | Validate structure offline; secret presence is checked before radio use. |
| `decode_key(value)` | Accept a 16-byte key in hex or standard base64 without echoing bad input. |
| `expected_key(spec)` | Return the required wire key, or None to pin an existing radio channel. |
| `radio_key(payload)` | Read the SDK's binary (or hex) key field; reject incomplete radio replies. |
| `identity(payload)` | Return a one-way key fingerprint used internally for identity comparisons. |
| `async discover(mc)` | Read slots until the companion reports its first unsupported index. |
| `async resolve_channels(mc, config)` | Bind every configured ID to one verified radio slot. Never write/fallback. |
| `async verify_binding(mc, binding)` | Recheck name AND key immediately before accepting/sending channel work. |
| `bind_state(db, bindings)` | Pin identity across restarts and back up SQLite before first schema migration. |
| `_migrate_state(db, bindings, tables)` | Update schema, legacy context and identity pins inside bind_state's transaction. Legacy rows match by unambiguous display name once. Later starts use the stable ID and reject name/key changes. Removed channels retain history but lose queued work and active alarms. This helper never commits independently. |
| `channel_config(config, channel_id, binding=None)` | Give each worker a view of its channel, sharing current command assignments. |
| `export_allowed(kind, payload, bindings)` | Unknown channels and unclassified packet logs never bypass export controls. |

<a id="check-live-py"></a>

## check_live.py

[Source](check_live.py)

Read-only end-to-end check. Uses the configured serial, BLE, or TCP connection. Requires an idle compatible companion radio and unused configured localhost port (1884 by default). Opens the configured radio interface and localhost sockets and writes runtime state. Sends no over-the-air messages.

| Function signature | Purpose and behavior |
| --- | --- |
| `async check()` | Start a local broker and radio session, issue read-only infos, verify MQTT results, and clean up connections. |
| `check.receive(c, u, msg)` | Collect MQTT event topics/status/results and signal waiting diagnostic steps. |

<a id="flood-alarm-py"></a>

## flood_alarm.py

[Source](flood_alarm.py)

Persistent flood subscriptions. SQLite stays on the event-loop thread. ALGORITHM MAP: remember = enrollment/renewal; check_one = comparison; is_current = stale-result/expiry guard; run = scheduler. No background OS service.

| Function signature | Purpose and behavior |
| --- | --- |
| `FloodAlarms.__init__(self, db, channel, read_status, notify, clock=time.time, allowed=lambda: True)` | Reuse runtime/bridge.sqlite3; callbacks perform bounded lookup and tagged send. |
| `FloodAlarms.row(self, sender)` | Return one subscription as a dict without changing the shared DB row factory. |
| `FloodAlarms.remember(self, request, now)` | Start/update one user's alarm; each !floodalarm replaces location and resets expiry. |
| `FloodAlarms.acknowledge(self, request)` | Allow the first lookup only AFTER the reply was sent; ignore superseded requests. |
| `FloodAlarms.is_current(self, reading)` | Recheck after HTTP and inside the radio queue: no expired/old-location notifications. |
| `async FloodAlarms.check_one(self)` | Read one due subscription; silently save baseline, then report type-set changes only. |
| `async FloodAlarms.run(self)` | One bounded lookup at a time, alongside the independent immediate-reply worker. |

<a id="radio-connection-py"></a>

## radio_connection.py

[Source](radio_connection.py)

Connection settings and bounded MeshCore sessions shared by all radio tools.

| Function signature | Purpose and behavior |
| --- | --- |
| `connection_settings(config, platform=None)` | Validate without device I/O; legacy settings continue to select USB serial. Serial port and baudrate remain top-level settings for backwards compatibility. Only the active transport's fields are accepted inside the connection object. BLE pairing belongs to the OS; a service must not wait for interactive prompts. |
| `device_metadata(endpoint)` | Keep device.port compatible for serial consumers; add transport identity. |
| `async close_radio(mc, transport)` | Release SDK and partially opened transports, even after a failed handshake. |
| `async radio_session(config)` | Open exactly one selected node and always close it on failure, stop, or exit. Retain the SDK instance before connecting so cancellation during connection cannot orphan a socket/BLE client. The service manager owns reconnection: every restarted session rechecks channels and never replays uncertain sends. |
| `validate_serial_port(port, platform=None)` | Accept automatic USB detection or one platform-valid fixed port; no device I/O. |
| `select_serial_port(port='auto', platform=None)` | Return a fixed port or the sole currently attached USB serial device. Rescan for every connection attempt so COM/tty renumbering is harmless. Enumeration only: never probe unrelated serial devices or pick the first of several candidates. The MeshCore handshake still verifies the selected radio. |

<a id="responder-py"></a>

## responder.py

[Source](responder.py)

Configured channel phrase -> local Python script -> tagged channel response. Read parse_message() for input handling, run_script() for child execution, and Responder.process_one() for queue state and replies. Settings: config.json. Functions that commit SQLite or launch a child process say so in their docstrings.

| Function signature | Purpose and behavior |
| --- | --- |
| `validate_config(config, root)` | Validate enabled responder settings and script paths; return None or raise before processing messages. |
| `match_command(phrase, commands)` | Return (command, arguments, input_error), or None for unknown text; validate inputs without running scripts. |
| `script_path(root, relative, program_directory=None)` | Resolve a bundled script or an administrator-installed programs/*.py file. program_directory is a trusted absolute folder from local configuration. Radio messages cannot select file paths. Resolve symlinks before checking containment so neither ../ nor a symlink can escape the selected folder. |
| `parse_message(payload, channel, own_name, config, now)` | Return validated sender/channel/request context, or None for stale, self, reply, or unrelated messages. |
| `reply_parts(sender, output, limit=150, max_parts=4)` | Return tagged UTF-8-safe pieces within the byte/part limits; collapse whitespace and mark truncation. |
| `async run_script(root, spec, request, config)` | Run the configured Python file with args/context, bounded stdout/stderr and timeout; return (reply, diagnostic). |
| `async run_script.read_bounded(stream)` | Read one child output stream as UTF-8 and raise if its independent byte limit is exceeded. |
| `async run_script.communicate()` | Send request JSON on stdin and collect stdout, stderr, and child exit status concurrently. |
| `Responder.__init__(self, root, db, config, channel, own_name, send, verify=None)` | Create the request table and mark unfinished running/sending requests interrupted; commits to SQLite. |
| `Responder.allowed(self, command)` | Check this worker's channel against the program's explicit assignment list. |
| `Responder.accept(self, payload, now=None)` | Validate and queue one message unless duplicate, cooling down, or full; return whether it was accepted. |
| `Responder.update(self, request_id, state, response=None, detail=None)` | Commit request state and diagnostics, retaining the prior response when response is None. |
| `async Responder.process_one(self, alarm_only=None)` | Process the oldest queued request, expire stale work, run its script and send replies; return False if empty. |
| `async Responder.read_flood_status(self, location)` | Bounded JSON subprocess: API failures cannot be mistaken for a cleared flood status. |
| `async Responder.send_flood_change(self, reading, output)` | Tag changes just like !floodwarn; guard again after waiting for the radio's send slot. |
| `async Responder.run_requests(self, alarm_only=False)` | Drain this worker's queue without blocking the alarm scheduler or acknowledgment worker. |
| `async Responder.run(self)` | All workers stop with the service; radio sends still use the existing shared rate limiter. |

<a id="service-py"></a>

## service.py

[Source](service.py)

Serial, BLE, or TCP MeshCore connection, MQTT event delivery, and channel-command orchestration. Start reading at main() -> run_mode() -> radio_mode() -> bridge_loop(). Operator settings live in config.json; see README.md for configuration guidance. This module opens serial/network connections and writes runtime/bridge.sqlite3.

| Function signature | Purpose and behavior |
| --- | --- |
| `normalize(value)` | Preserve packet data including binary fields; omit secret key material. |
| `envelope(kind, payload, port=None, attributes=None)` | Wrap a payload in a timestamped, uniquely identified MQTT event; normalize binary and secret fields. |
| `Store.__init__(self, path)` | Open SQLite and create the durable event outbox and MQTT request-ID tables; writes to disk. |
| `Store.put(self, topic, body)` | Serialize one event to JSON and commit it to the pending MQTT outbox. |
| `Store.claim(self, request_id)` | Persist a request ID and return True only for its first appearance, preventing duplicate execution. |
| `Store.next(self)` | Return the oldest pending (row_id, topic, JSON_body), or None; does not remove it. |
| `Store.ack(self, row_id)` | Delete and commit a published outbox row after broker acknowledgement. |
| `validate_request(raw)` | Validate raw MQTT JSON against allowed CLI commands; return (id, argv) or raise ValueError. |
| `make_mqtt(config, incoming, watch=False)` | Start the MQTT client's background loop; subscribe to commands or watch events on connection. |
| `make_mqtt.on_connect(c, userdata, flags, reason, properties)` | Subscribe after broker connection and publish retained online status for the bridge. |
| `make_mqtt.on_message(c, userdata, message)` | Reject retained bridge commands and enqueue incoming messages; log and discard queue overflow. |
| `async publish_outbox(client, store)` | Continuously publish queued events at QoS 1; delete rows only after acknowledgement, retaining failures. |
| `async bridge_loop(mc, cli, config, port)` | Own the connected radio/MQTT session, persist events, run the responder, and serialize radio actions. |
| `async bridge_loop.get_message()` | Put SDK background fetches under the same lock as verification and sends. MeshCore 2.3.11 otherwise issues get_msg outside our command lock. Its global ERROR replies cannot identify which concurrent command failed. |
| `async bridge_loop.execute(action)` | Run one radio action under the shared lock, honoring command timeout and spacing in seconds. |
| `async bridge_loop.send_reply(index, text, *, guard=None)` | Recheck the channel name, send a tagged reply, and persist its result as a BOT_REPLY event. |
| `async bridge_loop.send_reply.action()` | Verify the target channel still matches, ask the radio to send, and record acceptance; not recipient delivery. |
| `async bridge_loop.verify(index)` | Serialize read-only identity checks with sends; fail on a bounded timeout. |
| `async bridge_loop.run_bots()` | Run one isolated worker set per channel, sharing the radio limiter and DB. |
| `async bridge_loop.process_event(event)` | Persist each radio event and offer decoded channel messages to the responder queue. |
| `async bridge_loop.receive(event)` | Track SDK callbacks so service stop cancels reads waiting for the radio lock. |
| `async bridge_loop.action()` | Validate a registered destination immediately before the MQTT send. |
| `supported_serial_port(port)` | Return whether this package accepts the discovered serial-port name. |
| `prepare_cli()` | Import the upstream CLI with package-local runtime settings; return its command helpers. |
| `async radio_mode(config, command=None)` | Run the bridge or one command on the selected transport; always disconnect. |
| `async watch(config)` | Print MQTT event messages as JSON lines until cancelled; never opens a serial connection. |
| `async start_local_broker(port=1883)` | Start and return an anonymous broker bound to localhost; the caller must shut it down. |
| `async run_mode(config, mode, command=None)` | Start/reuse the local broker when required, dispatch a mode, and stop any broker created here. |
| `main()` | Parse mode/config options, create runtime storage, validate settings, and start the selected mode. |

<a id="service-runner-py"></a>

## service_runner.py

[Source](service_runner.py)

Unattended entry point used by Windows SCM and Linux systemd installers.

| Function signature | Purpose and behavior |
| --- | --- |
| `load_environment(path)` | Read optional credentials without accepting interpreter/path overrides. |
| `async supervise(config, stop_file=None, *, install_signals=True)` | Cancel the bridge on SIGTERM or SCM stop; allow its finally blocks to run. |
| `async supervise.wait_for_stop()` | Watch the SCM stop file or process signal without blocking other workers. |
| `main(argv=None)` | Validate installed paths/secrets, optionally check offline, then supervise the service. |

<a id="scripts-airnow-aqi-py"></a>

## scripts/airnow_aqi.py

[Source](scripts/airnow_aqi.py)

Find the nearest AirNow monitoring site and report its PM2.5 AQI. Set AIRNOW_API_KEY in the environment, then pass latitude and longitude: python airnow_aqi.py 37.7749 -122.4194 Request a free AirNow API key at https://docs.airnowapi.org/account/request/. AirNow observations are preliminary and subject to change.

| Function signature | Purpose and behavior |
| --- | --- |
| `validate_coordinates(latitude: float, longitude: float) -> None` | Reject latitude outside -90..90 or longitude outside -180..180; return None on success. |
| `parse_arguments() -> tuple[float, float]` | Read two positional decimal-degree coordinates; invalid input exits through argparse. |
| `haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float` | Return great-circle distance in kilometers between two latitude/longitude pairs. |
| `bounding_boxes(latitude: float, longitude: float, radius_km: float) -> list[str]` | Return west,south,east,north boxes, splitting at the date line. |
| `api_get(bbox: str) -> list[dict[str, Any]]` | Query the AirNow PM25 endpoint for a west,south,east,north box; return rows or raise a key-safe error. |
| `_number(item: dict[str, Any], *names: str) -> float \| None` | Return the first numeric value among alternative source field names, or None if none can be parsed. |
| `parse_observation(item: dict[str, Any], latitude: float, longitude: float) -> Observation \| None` | Convert a usable PM2.5 row into an Observation; return None for unsupported or missing readings. |
| `find_nearest_observation(latitude: float, longitude: float) -> Observation` | Expand search boxes until any usable readings exist; return the nearest in that first populated box. |
| `one_word_rating(aqi: int, category_number: int \| None=None) -> str` | Map AirNow category, or fallback AQI thresholds, to reply wording; some labels contain spaces. |
| `main() -> int` | Read coordinates/key, print the observation, and return 0; print expected errors to stderr and return 1. |

<a id="scripts-flood-warn-py"></a>

## scripts/flood_warn.py

[Source](scripts/flood_warn.py)

Flood alerts from the NWS API used by https://www.flashfloodwarn.com/. Uses the standard library; city/ZIP coordinates come from Open-Meteo/GeoNames. Run: python scripts/flood_warn.py Sacramento (or ZIP or LATITUDE LONGITUDE).

| Function signature | Purpose and behavior |
| --- | --- |
| `parse_location(text)` | Reuse UV's shared input parser and relabel usage errors for !floodwarn; performs no HTTP requests. |
| `get_json(url, params=None)` | Fetch JSON/GeoJSON; distinguish NWS coverage, rate-limit, and availability errors. |
| `resolve_location(parsed)` | Return GPS coordinates or geocode an exact US city/ZIP; reject missing and invalid matches. |
| `timestamp(value)` | Parse an ISO timestamp with an explicit time zone; raise RuntimeError for invalid or naive times. |
| `active_types(data, now=None)` | Return distinct active flood types in configured order after validating the NWS collection, status, message type, timestamps, and pagination. NWS point matching includes zone alerts with null geometry; malformed data raises an error. |
| `snapshot(text)` | Return comparable alert types plus reply text; failures raise, never become a clear reading. |
| `format_status(text, events)` | Return the no-flood-events sentence or location followed by one line per active event, using the configured emoji and descriptions; no I/O. |
| `lookup(text)` | Perform one location lookup through snapshot(text) and return its reply text; propagate lookup errors without changing alarm subscriptions. |
| `main(argv=None)` | Print UTF-8 alert/usage/error text for location arguments; return 0 so the responder forwards the text. |

<a id="scripts-heat-adv-py"></a>

## scripts/heat_adv.py

[Source](scripts/heat_adv.py)

Look up active NWS heat alerts for GPS coordinates, a US ZIP, or a city/state. Uses only the standard library and the adjacent uv_index.py location parser. Run: python scripts/heat_adv.py Sacramento (or ZIP or LATITUDE LONGITUDE).

| Function signature | Purpose and behavior |
| --- | --- |
| `parse_location(text)` | Return `(kind, value, state)` for validated decimal GPS, US ZIP/ZIP+4, or city/state text. Reuse `uv_index.parse_location`; a bare city means California. No network access. Invalid syntax raises `ValueError` with `!heatadv` usage. |
| `get_json(url, params=None)` | URL-encode optional query parameters and return decoded JSON with the configured User-Agent and 12-second timeout. HTTP 404 from `/points/` raises a coverage `ValueError`; rate limits, network failures, and invalid JSON raise readable `RuntimeError` messages. |
| `resolve_location(parsed)` | Accept the parsed tuple and return `(latitude, longitude)`. GPS bypasses HTTP. City/ZIP input queries Open-Meteo and requires an exact US city/state or ZIP match; choose the largest population among matches. Reject missing matches and nonfinite/out-of-range coordinates. |
| `timestamp(value)` | Convert an ISO-8601 string containing an explicit timezone into a timezone-aware `datetime`; reject missing, malformed, or naive values with `RuntimeError`. |
| `active_types(data, now=None)` | Accept an NWS FeatureCollection and optional timezone-aware `now` (default: current UTC); return distinct supported event names ordered Warning, Watch, Advisory. Normalize legacy Excessive Heat names. Exclude non-Actual, cancelled, future-effective, expired, and ended alerts; include effective future-onset watches. Reject malformed or paginated/incomplete data instead of returning a false clear. |
| `lookup(text)` | Normalize whitespace in supplied location text, resolve its coordinates, verify NWS `/points/` coverage, and request active point alerts. Return the exact no-advisories reply or one requested-format line per active type, preserving supplied location spelling. Errors propagate to `main`; no subscriptions or radio I/O occur here. |
| `main(argv=None)` | Read supplied arguments or `sys.argv`, remove an optional leading `!heatadv`, and print UTF-8 reply/error text. Return 0 for handled success and failure so the responder forwards the message. The responder adds sender tags, joins newlines, and enforces the configured 45-second command timeout. |

<a id="scripts-highway-info-py"></a>

## scripts/highway_info.py

[Source](scripts/highway_info.py)

Print current Caltrans highway information for a highway number.

| Function signature | Purpose and behavior |
| --- | --- |
| `HighwayReportParser.__init__(self) -> None` | Initialize report capture state and its text buffer. |
| `HighwayReportParser.handle_starttag(self, tag: str, attrs: list[tuple[str, str \| None]]) -> None` | Stop at the report's next horizontal rule; preserve line boundaries for block tags. |
| `HighwayReportParser.handle_endtag(self, tag: str) -> None` | Add a line break when a captured heading or paragraph ends. |
| `HighwayReportParser.handle_data(self, data: str) -> None` | Begin capture at REPORT_MARKER and collect text until the report ends. |
| `HighwayReportParser.text(self) -> str` | Return cleaned report lines from the captured HTML text. |
| `is_clear_status(text: str) -> bool` | Return True when a subsection explicitly reports no road issues. |
| `traffic_conditions_only(report: str) -> str` | Return active condition text without report, highway, or area headings. |
| `compact_24_hour_time(match: re.Match[str]) -> str` | Convert a Caltrans 24-hour time such as 2300 hrs to 11P. |
| `compact_ampm_time(match: re.Match[str]) -> str` | Convert a time such as 8:00 PM to 8P. |
| `compact_and_wrap(text: str) -> str` | Abbreviate wording and wrap each subsection as a separate text block. |
| `highway_number(value: str) -> int` | Validate a command-line or prompted highway number. |
| `fetch_highway_info(number: int) -> str` | Fetch one Caltrans route page, extract active conditions, and return compact text; raise on missing report. |
| `main() -> int` | Read or prompt for a route, print the report, and return 0; return 1 for retrieval or 2 for prompted input errors. |

<a id="scripts-nearby-river-stations-py"></a>

## scripts/nearby_river_stations.py

[Source](scripts/nearby_river_stations.py)

Find CDEC river-stage stations near a latitude/longitude. The public CDEC RR8 report supplies the fixed-width river-stage rows. NOAA's NWPS API supplies coordinates for the same five-character station identifiers. Only the Python standard library is required.

| Function signature | Purpose and behavior |
| --- | --- |
| `_PreExtractor.__init__(self) -> None` | Initialize the first-PRE-block parser and its text buffer. |
| `_PreExtractor.handle_starttag(self, tag: str, attrs: list[tuple[str, str \| None]]) -> None` | Start collecting the first preformatted report block when its opening tag appears. |
| `_PreExtractor.handle_endtag(self, tag: str) -> None` | Stop collection after the first closing pre tag. |
| `_PreExtractor.handle_data(self, data: str) -> None` | Append text only while inside the selected report block. |
| `_PreExtractor.text(self) -> str` | Return the collected report text without fetching or changing external state. |
| `_get_text(url: str, timeout: float) -> str` | Download and decode one source response; raise RuntimeError on a network timeout or failure. |
| `_get_json(url: str, params: dict[str, Any], timeout: float) -> dict[str, Any]` | URL-encode parameters, fetch text, and return decoded JSON; raise on malformed JSON. |
| `_extract_report_text(html: str) -> str` | Extract and normalize the CDEC PRE block; reject pages that lack the expected report. |
| `_reading(value: str) -> float \| None` | Parse one river-stage field in feet; blank, plus-marker, or invalid data becomes None. |
| `parse_cdec_report(report_text: str) -> dict[str, Any]` | Parse the CDEC fixed-width report into station records. |
| `haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float` | Return great-circle distance using mean Earth radius 3,958.761 miles. |
| `_bounding_box(latitude: float, longitude: float, radius_miles: float) -> dict[str, Any]` | Build NOAA's bounding-box query in decimal degrees from a search radius in miles. |
| `find_nearby_river_stations(latitude: float, longitude: float, radius_miles: float=DEFAULT_RADIUS_MILES, timeout: float=HTTP_TIMEOUT_SECONDS) -> list[dict[str, Any]]` | Return RR8 river stations within radius_miles of latitude/longitude. |
| `_parse_args() -> argparse.Namespace` | Read coordinates, radius in miles, HTTP timeout in seconds, and optional compact output mode. |
| `format_mesh_report(stations: list[dict[str, Any]], radius: float) -> str` | Summarize nearest-first station readings without inventing missing values. |
| `format_mesh_report.stage(value)` | Format a stage as feet or N/A without converting missing readings to zero. |
| `main() -> int` | Fetch nearby stations and print JSON or mesh text; return 1 with JSON error text on expected failures. |

<a id="scripts-snowpack-py"></a>

## scripts/snowpack.py

[Source](scripts/snowpack.py)

California snow depth (CDEC sensor 18) and next-24h snowfall (NWS). Standard-library CLI; the MeshCore responder supplies the @sender prefix.

| Function signature | Purpose and behavior |
| --- | --- |
| `get_text(url, params=None)` | Fetch UTF-8 text with a byte cap and per-request timeout; raise coverage or availability errors. |
| `get_json(url, params=None)` | Decode a fetched JSON response; translate malformed data into an availability error. |
| `parse_location(text)` | Reuse the shared location syntax and reject explicitly non-California city/state input. |
| `number(value)` | Return whether value is a finite int/float, excluding booleans and missing readings. |
| `resolve_location(parsed)` | Return GPS directly or geocode a California city/ZIP; reject invalid coordinate results. |
| `StationTable.__init__(self)` | Initialize CDEC table, row, and cell buffers. |
| `StationTable.handle_starttag(self, tag, attrs)` | Enter the station_table and start collecting its rows and cells. |
| `StationTable.handle_data(self, data)` | Append text to the active station-table cell. |
| `StationTable.handle_endtag(self, tag)` | Finish cells/rows and stop collecting at the end of the table. |
| `parse_stations(html)` | Return validated station id/name/coordinates from CDEC HTML; reject incomplete directories. |
| `distance_miles(lat, lon, station)` | Return great-circle miles between the user coordinates and one parsed station. |
| `current_depth(data, station_id, now)` | Return the newest unflagged, fresh hourly sensor-18 depth in inches, or None; zero is valid. |
| `timestamp(text)` | Parse an ISO timestamp with an explicit offset; raise ValueError if the time zone is absent. |
| `interval(text)` | Convert an ISO start/end or start/duration interval into (start, end); reject nonpositive spans. |
| `snowfall_24h(data, now)` | Integrate period totals over [now, now+24h), prorating boundary bins. |
| `inches(value)` | Format inches compactly, preserve small positive amounts, and label None as unavailable. |
| `lookup(text, now=None)` | Verify California coverage, choose the closest station, and combine depth with the user's 24h forecast. |
| `main(argv=None)` | Print a UTF-8 result or useful error for location arguments; return 0 so the responder forwards the text. |

<a id="scripts-status-py"></a>

## scripts/status.py

[Source](scripts/status.py)

Local smoke reply only; this does not test the data providers or radio delivery. Edit RESPONSE_TEXT to change the !status wording; the responder adds @sender.

This script executes at module level and defines no Python functions.


<a id="scripts-time-now-py"></a>

## scripts/time_now.py

[Source](scripts/time_now.py)

Print host-clock UTC time for !time; the responder adds @sender. Edit TIME_FORMAT for wording/layout. timezone.utc controls the time basis.

This script executes at module level and defines no Python functions.


<a id="scripts-uv-index-py"></a>

## scripts/uv_index.py

[Source](scripts/uv_index.py)

Current UV Index CLI. UV data: https://currentuvindex.com (CC BY 4.0). Location data: Open-Meteo / GeoNames. Uses only the Python standard library.

| Function signature | Purpose and behavior |
| --- | --- |
| `parse_location(text)` | Return (kind, value, state) for GPS, US ZIP, or city text; raise ValueError on bad input. No network access. |
| `get_json(url, params)` | Fetch one JSON response with a per-request timeout; convert HTTP/decoding failures into readable errors. |
| `resolve_location(parsed)` | Return (latitude, longitude); use GPS directly or geocode a US ZIP/city with state filtering. |
| `risk_level(uvi)` | Validate a nonnegative finite UV reading and return its category; thresholds are category definitions. |
| `lookup(text)` | Resolve location, request the current UV reading, and return one reply string; raise on unavailable data. |
| `main(argv=None)` | Read location arguments and print a reply or useful lookup error; return 0 so the responder sends that text. |
