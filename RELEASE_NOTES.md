# Release notes

## Current-source documentation: October 21, 2026

The source contains 31 dedicated commands with one tagged response of at most
150 UTF-8 bytes per request. [Command and subcommand examples](meshcore_mqtt_service/RESPONSE_EXAMPLES.md)
cover all fields, context categories, help and subscription controls. The
[response policy](meshcore_mqtt_service/RESPONSE_FORMATTING.md) records priority text and optional
fields. Full supported structured records remain available through local
JSON/snapshot modes. GitHub verification covers both service packages on
Windows/Linux with Python 3.11 and 3.13. Configuration describes planned checks;
local results and unverified deployment limits are recorded separately.

This documentation update does not rebuild or republish existing release artifacts.


Current source registers 31 commands. The [complete command/subcommand index](meshcore_mqtt_service/COMMAND_REFERENCE.md#subcommand-index)
and [terminal/maintenance reference](docs/CLI_REFERENCE.md) describe current
interfaces. Historical entries retain the behavior and validation of their named
source snapshots; those entries do not establish current artifacts or live operation.

## Five-second shared radio spacing

- Reduced `command_interval` from 15 to 5 seconds in both platform defaults.
  Flood-alert responses retain their five-second minimum pause without the
  former 15-second shared limit. All shared radio commands and reply chunks use
  the new interval; contention and transmission time can still add delay.
- Existing deployments require the same change in their active configuration
  and a service restart. Alert priority, descriptions and uncertainty are unchanged.

## Independent priority-ordered flood notifications

- Flood-alarm alerts now arrive separately with the exact standard descriptions,
  explicit lifecycle/outage states and urgency/severity/certainty/effective-time
  ordering. Unknown priority fields remain visible.
- Added a five-second minimum gap after complete responses; the existing shared
  radio interval (5 seconds by default) still applies. Polling continues during
  delivery, and superseded, expired or stopped notifications are suppressed.
- Preserved current-only data, persistent subscription ownership and the existing
  no-replay policy. Pending delivery metadata is replaceable and in memory.

## Concise flood warnings and full details

- Added `!floodwarn details LOCATION` for complete current bulletin text, source
  links and metadata; existing radio and subprocess limits remain in effect.
- Simplified default replies to the location, active alert, expiration and exact
  standard description, without the "point" suffix, duplicate headline or URL.
- Preserved explicit unknown states, coverage checks, current-only data and
  subscription ownership. Both packages include matching regression coverage.

## Automatic WAC/WAS metadata checks

- Added five-source elevation, logger-offset, equipment and datum checks to
  `--noaa-identifiers` refresh in both packages, including NOAA catalog failures.
- Changed fields and inaccessible or malformed sources are saved and printed;
  review-needed outcomes return exit code 1. Unchanged known uncertainty remains
  explicit without causing a recurring failure.
- Prioritized CDEC station-elevation metadata while retaining CW3E evidence,
  discrepancy flags and unknown datum/offset interpretation.
- Preserved fixed manual-review dates, current-only readings and unresolved
  identities. No correction or link can be authorized by these auxiliary checks.

## WAC/WAS vertical-reference audit

- Corroborated conflicting station elevations through official CW3E and CDEC
  inventories; no supported datum or numerical correction was established.
- Retained the reported logger offset as uninterpreted static metadata, with
  explicit unknown units, sign, target quantity and upstream application status.
- Preserved current-only readings, thresholds, routing and unresolved NOAA links;
  added regression coverage and detailed source citations.

## WAC official-record recovery

- Recovered CW3E WAC detail, sensor, logger and watershed records; retained the
  explicit CDEC WAS alias without adding unsupported legacy-USGS/NOAA links.
- Replaced obsolete access-failure evidence for two Warm Springs stations while
  preserving other review dates, unresolved identities and current-only readings.
- Documented conflicting elevations and unspecified logger-offset units without
  applying measurement corrections or inferring flood thresholds.

## Additional local NOAA station review

- Recorded local operating-agency evidence for all sixteen unresolved stations;
  no additional NOAA crosswalk was supported.
- Preserved operator leads, differing record periods and the Lambert Bridge/Talmage
  identifier conflict without changing accepted links or current-only readings.
- Identifier refresh carries fixed manual evidence; new regressions protect link
  authority, review dates, explicit uncertainty and measurement-free output.

## NOAA archived-source access retry

- Recovered three original USGS PDFs and Sonoma Water's OneRain site inventory;
  no additional NOAA-to-USGS crosswalk was supported.
- Added transient redirect cookies and a static OneRain metadata refresh, with
  explicit failures and non-authorizing alias candidates.
- Replaced obsolete access-failure labels with dated PDF checksums/page references;
  preserved current-only readings and sixteen unresolved station identities.

## Additional NOAA map and operator-record audit

- Reviewed all sixteen remaining identities using official map metadata and
  additional records; no new USGS-to-NOAA link was supported.
- Retained non-authorizing candidate evidence, including WSSC1, and added refresh
  flags for candidate changes, malformed maps and source failures.
- Preserved current-only readings, original data, supported links and routing.


## Complete upstream monitoring - unreleased

Condition subscriptions evaluate all reliably linked upstream gauges independently
of the radio display limit, with full-set categorical baselines and concise change
summaries. Schema-2 indexes preserve linked stations without coordinates. Rebuild
instructions and uncertainty rules are in the [water guide](meshcore_mqtt_service/WATER_GUIDE.md).

## Location water commands - unreleased

Adds paired `!waterway`, `!basin` and `!floodstatus` commands, plus pinned
`!floodalarm conditions`, `status` and `stop`. Current-only observations,
explicit derived relationships and source limitations are documented in the
[water guide](meshcore_mqtt_service/WATER_GUIDE.md). Existing `!rivers` behavior
is unchanged. Downloader/index setup remains separate from service installation.


## v0.9.5-beta - October 20, 2026

- Adds `!slidewarn`, `!slidealarm`, and `!slideinfo` for California and Nevada,
  with shared ZIP/city/GPS input, official NWS alert wording, and USGS station links.
- Includes checksummed California/Nevada boundaries, station metadata, paired
  tests, and the landslide guide. Both platform packages contain 28 commands.
- Preserves existing commands, settings, and channel assignments on upgrade.
  New commands require explicit channel assignment in existing installations.
- Updates package, installer, manifest, and Windows metadata to `v0.9.5-beta`
  (`Version 0.9.5 - Beta`; numeric Windows file version `0.9.5.0`).


## October 20, 2026 wildfire addition

- Adds nine dedicated wildfire commands with paired Linux/Windows programs.
- Includes 186 full California-associated NWS fire-weather zones with interstate
  geometry and checksummed provenance.
- Adds service-owned atomic source refresh, field provenance, explicit missing
  data, latest perimeter joins, forecasts, context feeds and temporary alarms.
- Preserves existing channel assignments on upgrade; new commands require opt-in.
- Adds `!smoke` point coverage and air-quality reporting with the compact response
  format, plus `!firedanger` public ERC/BI percentiles and optional FEMS fuel moisture.
- Adds regression coverage and the focused wildfire guide.

See [wildfire behavior and maintenance](meshcore_mqtt_service/WILDFIRE_GUIDE.md).

## v0.9.0-beta - October 11, 2026

- Adds focused GIS attributes and an explicit `info` mode. Policy and amenity
  filters run before proximity ranking; no-radius queries return only the
  closest matching feature. Explicit radii retain bounded result lists.
- Adds boundary category selection and command help. The old default radius
  setting is ignored; source snapshots and dedicated entry points are retained.

- Gives every bundled command its own Python entry point under `scripts/`,
  including `trail.py`, `rec.py`, `peak.py`, `park.py`, `boundary.py`, and
  `floodalarm.py`. Shared helpers remain reusable; alarm scheduling is unchanged.
- Retains the generic GIS CLI for compatibility and adds a regression check
  against missing or shared command programs. GIS settings are included in
  both service ZIPs and all three installer targets.

- Adds `!trail`, `!rec`, `!peak`, `!park`, and `!boundary` using local EBMUD data.
- Adds adjustable GIS settings, Shapely/pyproj dependencies, bounded replies,
  snapshot integrity checks, spatial relationships, and regression tests.
- Documents the manual deployment sequence while preserving transport, channel, credential, and timezone configuration.
- Provides a manual twelve-dataset refresh with independent counts/ID coverage, manifest checksums, README count updates, and failure recovery.
- Repairs six invalid polygons in three local datasets; preserves original response bytes and per-feature provenance. Raw refresh can reintroduce upstream defects.
- Rebuilds the Windows x64 installer, Linux x86_64 and Raspberry Pi ARM64
  installers, both service ZIPs, and the combined installer bundle from current
  source. Version filenames use `v0.9.0-beta`; SHA-256 files identify the rebuild.
- Complete installers include shared datasets and repair originals. Service ZIPs
  require the shared data directory separately. Existing installed definitions
  are preserved; older registrations and channel assignments require review.


## October 8, 2026 source and distribution snapshot

- Adds `!lightning`: NWS thunderstorm/dry-lightning potential in the next 24 hours,
  with all stated chance levels, including slight chance and positive percentages.
  Pacific display time follows PST/PDT; change the shared installed `responder.timezone`
  to another IANA zone without rebuilding. It persists across upgrades and applies
  to clock, AQI, river, and lightning timestamps across all service programs. Adds pinned `tzdata` support.
- Both service ZIPs and all three installers include the lightning command,
  dependencies, tests, and function documentation. There are eleven bundled
  commands. See [installation and timezone settings](INSTALL.md#lightning-command-and-timezone).

- Adds `!heatadv` to both service packages, alongside the other bundled commands. Accepts GPS, US ZIP/ZIP+4, and city/state input; bare cities default
  to California. Preserves supplied location text and the defined reply format.
- Reports every distinct active NWS heat warning, watch, and advisory. Confirms
  coverage first; failed, malformed, or incomplete lookups produce errors.
- Documents every maintained application function in component references and
  adds missing satellite-tool docstrings without changing executable behavior.
- Rebuilt service ZIPs and Windows x64/Linux x86_64/ARM64 installers include
  the command and function references. See [the installation guide](INSTALL.md#heat-command-source-update)
  for updating an existing service and setting explicit channel assignments.

## v0.3.0-beta

- Supports USB serial, BLE, and TCP connections; TCP defaults to port 5000.
- Uses shared connection settings for the bridge, CLI, and channel tools, with
  bounded connection cleanup and periodic TCP health checks.
- Includes multiple-channel assignments, private-channel controls, and external
  Python programs. Installer upgrades preserve the selected connection.
- Provides Windows x64 and Linux x86_64/ARM64 installers. Physical BLE/Wi-Fi
  operation and Bluetooth access under service accounts remain unverified.

## v0.2.0-alpha

### Online OS service installers

- Added Windows x64 setup and self-extracting Linux x86_64/Raspberry Pi ARM64
  installers, with automatic online Python/dependency installation and Skyfield.
- Included both platform sources, satellite tools, EBMUD/reference snapshots,
  tests and documentation; excluded local environments, credentials and runtime data.
- Added a saved-port service runner, Windows SCM host and Linux systemd unit,
  graceful shutdown, restart-on-failure, separate writable state and upgrade
  preservation. Existing interactive launchers remain available.
- Added five service-runner regression tests per package (114 tests total per
  service package) and three installer inventory/upgrade-preservation tests.
- See the [installation guide](INSTALL.md) for supported systems, installation,
  optional credentials, maintenance and validation limits. These are online
  installers; Python runtimes and dependency wheels are downloaded during setup.


This release updates both self-contained Linux and Windows service packages from
`v0.1.1-alpha`. It adds snowpack reports and persistent flood-alarm subscriptions,
plus standalone reference tools/data and workspace packaging improvements.

### New commands

- Added `!snowpack` for California GPS coordinates, ZIP codes, and city names.
  Replies include the sender tag, nearest CDEC hourly snow depth in inches,
  NWS snowfall forecast for the next rolling 24 hours, station name, and distance
  in miles. Missing or stale data is `unavailable`; a valid zero remains `0in`.
  Out-of-state locations are rejected.
- Added `!floodalarm` with the same location inputs as `!floodwarn`. An accepted
  request queues `@Alice Flood Alarm is set for requested location.` through a
  separate acknowledgment worker, before the weather lookup. Radio spacing and
  existing request validation still apply.
- Flood alarms save a silent first baseline, check every 20 minutes, and send
  same-channel tagged replies when the set of supported NWS flood-alert types
  changes, including when alerts clear. Bulletin wording or IDs alone do not
  trigger a notification.
- Each accepted `!floodalarm` replaces that sender's saved location and resets
  the four-hour monitoring limit. `!floodwarn` remains a one-shot lookup and
  never starts or renews an alarm. The service must remain running to monitor.

### Monitoring and responder changes

- Added `flood_alarm.py` and persistent `flood_subscriptions` records in each
  package's existing `runtime/bridge.sqlite3`, keyed by channel and sender name.
  Subscriptions survive restarts without extending their original expiry time.
- Added independent acknowledgment and monitoring workers, a structured
  `--snapshot` result in `scripts/flood_warn.py`, and stale-result/expiry checks
  after lookups and immediately before radio transmission.
- A new location starts a fresh baseline; renewing the same active location
  retains its baseline and scheduled check. Older messages cannot replace a
  newer requested location.
- Lookup failures retain the last good reading and produce one availability
  notice per failure episode. Interrupted or failed sends are logged without
  automatic replay. Existing flood-warning text and colored alert squares remain.
- Added `scripts/snowpack.py`, both command entries in `config.json`, and
  clearly commented flood-alarm timing and adjustment points. Both platform
  packages now expose nine commands; `!uv` and `!floodwarn` were already present
  in `v0.1.1-alpha`.

### Reference tools and data

- Added the standalone [satellite radio catalog](satellite_database/README.md):
  sourced SQLite records, capability-level status and provenance, known-retired
  satellite exclusions, orbital elements, offline cached refresh/lookup, and
  JSON/CSV exports in [data/satellites/](data/satellites/README.md).
  Optional Skyfield support calculates position and antenna direction. The
  catalog is separate from the MeshCore responder and installs no radio command
  or background schedule; source records do not prove reception or uplink access.
- Added [EBMUD GIS snapshots](data/ebmud/README.md) for trails, recreation points,
  peaks, reservoirs, watersheds, and park boundaries, with source metadata and
  checksums. These are local reference datasets; existing service commands do
  not consume them and they do not refresh automatically.

### Workspace and distribution changes

- Added [tools/package_services.py](tools/package_services.py) to build both
  installation ZIPs under `dist/`. It checks shared-code parity and configured
  script inclusion before replacing either package, then checks ZIP integrity.
- ZIPs contain platform source, configuration, launchers, setup/verification
  scripts, tests, and documentation. They exclude virtual environments, runtime
  databases, bytecode, historical backups, and the separate reference datasets.
- Removed the redundant `highway_info/` copy; the standalone highway program
  remains in each service's `scripts/` folder. Moved recovery backups to `archive/`.
- Removed obsolete Windows porting manifests/checker and Windows-only launch
  helpers from the Linux package. Removed its unused Windows virtual environment;
  Linux setup uses `.venv-linux/`. The Windows environment, service runtime data,
  and shared reference data were retained during cleanup.
- Added Linux `verify.sh`; both platform verification scripts discover every
  `test_*.py` suite and check dependencies. Updated workspace/platform guidance.

### Validation record

Recorded implementation validation comprises the following historical results;
no additional runtime test run is represented by this record:

- Service coverage increased from **66 tests in v0.1.1-alpha to 109 tests per
  package**, including 20 snowpack tests and 23 flood-alarm regression tests.
  Both packages passed on the Windows host; dependency checks also passed.
- Snowpack live city, ZIP, and GPS lookups returned California depths/forecasts;
  Nevada inputs were rejected. Flood-alarm timing used simulated time and mocked
  weather/radio data, alongside local subprocess and loopback MQTT checks.
- The satellite suite reported 26 tests with one optional Skyfield test skipped.
  Windows launcher file checks and Linux shell syntax/file checks passed.

Native Linux operation, a live four-hour alarm run, and physical radio delivery
were not established by those checks. A local send acceptance does not prove
remote reception. No service restart or hardware change was performed during
release documentation validation.

### Upgrade from v0.1.1-alpha

1. Stop the service and back up customized `config.json` and runtime data.
2. Replace the source with the `v0.2.0-alpha` package for the correct platform.
   Preserve the local runtime database if its history is needed; distribution
   ZIPs do not include it. The flood-subscription table is created by the responder.
3. Merge custom MQTT/channel/timing settings into the new configuration, retaining
   the `!snowpack` and `!floodalarm` entries and all existing command entries.
4. On a new computer, create a fresh environment with `bash setup.sh` on Linux or
   `setup.cmd` on Windows. The pinned service dependencies remain unchanged; the
   new commands need no additional API key. Keep `AIRNOW_API_KEY` for `!aqi`.
5. Run `bash verify.sh` on Linux or `verify.cmd` on Windows, then restart with
   `bash Start-Service.sh` or `Start-Service.exe` respectively.

This remains an alpha release. External lookups require internet/provider
availability. Snowpack is California-only, and city/ZIP inputs resolve to
representative points. Flood alarms compare alert types, not every bulletin
revision, and senders sharing a display name on the same channel share an alarm.
These reports do not replace official emergency notification systems.

## v0.1.1-alpha â€” September 20, 2026

This alpha release updates both service packages:

- `meshcore_mqtt_service/` for Linux
- `meshcore_mqtt_service_windows/` for Windows 10 x64

It replaces `v0.1.0-alpha`, which provided the MeshCore/MQTT bridge, channel
responder, and the `!status`, `!time`, `!aqi`, `!traffic`, and `!rivers`
commands.

### Highlights

#### Current UV index

The new `!uv` command reports the current UV index and risk category.

```text
!uv 38.5816, -121.4944
!uv 95814
!uv Sacramento
!uv Reno NV
```

- Accepts latitude/longitude, US ZIP and ZIP+4 codes, or a city with an optional state.
- Defaults city-only searches to California.
- Uses CurrentUVIndex.com for the current reading.
- Uses Open-Meteo/GeoNames to resolve city and ZIP input.
- Requires no UV API key or additional Python dependency.
- Reports the current reading only, with Low, Moderate, High, Very-High, or Extreme risk.

#### Active flood alerts

The new `!floodwarn` command summarizes active official National Weather Service
alerts at a resolved US point.

```text
!floodwarn 38.5816 -121.4944
!floodwarn 95814
!floodwarn Sacramento
!floodwarn Reno, Nevada
```

It reports these alert types in severity order:

- Flash Flood Warning ðŸŸ¥
- Flood Warning ðŸŸ§
- Flood Advisory ðŸŸ¨
- Flood Watch ðŸŸ¦

The command accepts the same location formats as `!uv`, needs no API key, combines
duplicate alerts of the same type, excludes expired/cancelled/test alerts, and returns
an explicit no-events response only after valid NWS coverage and alert responses.

### Responder improvements

- Added a reusable `location` input type for coordinate, ZIP, city, and state text.
- Added validated per-command `max_reply_parts` overrides.
- Set `!floodwarn` to a maximum of 12 reply parts so all four alert descriptions can
  fit while preserving the sender prefix and 150-byte part limit.
- Kept the four-part default for existing commands.
- Preserved exact command matching, fixed script paths, argument validation, sender
  cooldowns, duplicate suppression, timeouts, and same-channel replies.

### Linux and Windows parity

Both folders now contain matching copies of:

- `scripts/uv_index.py`
- `scripts/flood_warn.py`
- `tests/test_uv.py`
- `tests/test_floodwarn.py`
- Updated `responder.py`
- Updated `config.json`
- Updated platform documentation

The platform-specific MQTT ports, topic prefixes, virtual environments, launchers,
and runtime databases remain separate.

### Verification

- Automated coverage increased from **42 tests in v0.1.0-alpha** to **66 tests**.
- All 66 tests passed in each service folder using the installed Windows Python
  environments.
- The Windows `verify.cmd` command now includes the UV and flood-alert suites.
- Offline tests cover location parsing, source-response validation, risk boundaries,
  NWS alert filtering, failure handling, Unicode message splitting, and the
  command-specific 12-part limit.
- Live flood lookups were previously checked with city, ZIP, GPS, state abbreviation,
  and full-state-name inputs. An active Flash Flood Warning and Flood Watch were
  returned during that validation.

Native Linux execution, a live request to every external provider, and automatic
over-the-air delivery of the new replies have not all been verified. A locally
accepted radio send does not prove reception by a remote MeshCore node.

### Upgrade notes

1. Stop the running service.
2. Back up any customized `config.json` and runtime data required for retention.
3. Replace the old service source files with the `v0.1.1-alpha` folder for the
   correct platform.
4. Reapply custom MQTT, channel, timing, or command settings to the new
   `config.json`. Preserve the new `!uv` and `!floodwarn` entries.
5. Keep the existing `AIRNOW_API_KEY` environment setting if `!aqi` is used.
6. Run the platform verification command, then restart the service.

No dependency versions changed between these builds. Existing virtual environments
should remain compatible, although creating a fresh environment with the platform
setup script is recommended after moving the folder to another computer.

### Known limitations

- This remains an alpha release.
- The service runs in the foreground and requires interactive serial-device selection.
- `!uv` is subject to the public source's request allowance.
- City and ZIP searches use representative coordinates; use GPS coordinates for a
  precise point.
- `!floodwarn` covers the four listed flood alert types within NWS coverage. It is
  an information lookup and does not replace official emergency notification systems.
- External lookups require internet access and may fail when a provider is unavailable.

## California and Nevada landslide information

The source now contains 28 dedicated commands per platform. `!slidewarn`,
`!slidealarm`, and `!slideinfo` add California/Nevada alerts, temporary monitoring,
and USGS research-station information with the existing ZIP/city/GPS inputs.
Official NWS event names are retained; station data does not generate warnings.
[Setup, behavior, sources, and limits](meshcore_mqtt_service/LANDSLIDE_GUIDE.md).

### NOAA upstream station review

Both platforms include a source-cited 33-station NOAA identifier review and explicit refresh. Six additional gauges have published thresholds; ten have corroborated IDs without thresholds; seventeen remain unresolved. Original datasets and current-only retention remain unchanged. See [review evidence and refresh behavior](meshcore_mqtt_service/WATER_STATION_REVIEW.md).

### Additional NOAA agency-record review

The remaining 17 IDs now have USGS coverage and HADS cross-reference evidence. One published agency-successor chain links legacy USGS-11462000 through CDEC CDM to NOAA YDMC1, without published thresholds. Sixteen remain unresolved. Both packages preserve current-only values and withhold the successor when its source evidence changes. See [official evidence and refresh guards](meshcore_mqtt_service/WATER_STATION_REVIEW.md#additional-official-agency-review).
