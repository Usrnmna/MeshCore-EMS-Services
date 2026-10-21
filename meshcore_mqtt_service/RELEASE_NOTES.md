# Linux service release notes

## Current-source documentation: October 21, 2026

The source contains 31 dedicated commands with one tagged response of at most
150 UTF-8 bytes per request. [Command and subcommand examples](RESPONSE_EXAMPLES.md)
cover all fields, context categories, help and subscription controls. The
[response policy](RESPONSE_FORMATTING.md) records priority text and optional
fields. Full supported structured records remain available through local
JSON/snapshot modes. GitHub verification covers both service packages on
Windows/Linux with Python 3.11 and 3.13. Configuration describes planned checks;
local results and unverified deployment limits are recorded separately.

This documentation update does not rebuild or republish existing release artifacts.


## Concise single-message replies

- Command replies use at most one tagged 150-byte UTF-8 message. Details and
  paging routes are removed; no omission notices or continuation prompts appear.
- Highest-priority warnings, urgent actions and material uncertainty precede
  optional whole fields. Subscription events retain independent scheduling.
- Both platform packages include the shared formatter, regression tests and
  [manual field-review inventory](RESPONSE_FORMATTING.md).
- This policy supersedes the historical multipart/details behavior below.


Current source registers 31 commands. The [complete command/subcommand index](COMMAND_REFERENCE.md#subcommand-index)
and [terminal/maintenance reference](../docs/CLI_REFERENCE.md) describe current
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


## Complete upstream condition monitoring - unreleased

- Evaluates all reliably linked upstream gauges independently of radio display
  limits. Missing thresholds/readings and routing caveats remain explicit.
- Summarizes all changed gauges, with up to three priority details; retains only
  categorical subscription state and current source values.
- Requires rebuilding the local water index (schema 2) so supported stations
  without coordinates remain eligible. Existing point/expiry settings persist.

## Location water status and subscriptions - unreleased

- Adds dedicated `!waterway`, `!basin` and `!floodstatus` programs on both platforms.
- Adds pinned `!floodalarm conditions`, `status` and `stop`; enrollment verifies
  coverage before acknowledgment. Defaults are five-minute checks and four hours.
- Compares material official alert updates and labeled current-condition states,
  with explicit outage/recovery and no measured-level history.
- Uses separately downloaded statewide USGS/CalWater routing, a verified local
  index, NOAA observed gauge categories and current modeled point footprints.
- Adds current-only online caches, tests and source documentation. Existing
  unresolved matches remain explicit. `!rivers` is unchanged.
- Existing installations require opt-in channel assignment for new commands;
  no service restart, deployment, archive rebuild or data download is automatic.

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

- Adds seven dedicated wildfire commands with paired Linux/Windows programs.
- Includes 186 full California-associated NWS fire-weather zones with interstate
  geometry and checksummed provenance.
- Adds service-owned atomic source refresh, field provenance, explicit missing
  data, latest perimeter joins, forecasts, context feeds and temporary alarms.
- Preserves existing channel assignments on upgrade; new commands require opt-in.
- Adds regression coverage and the focused wildfire guide.


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

- Adds `!lightning` with eleven bundled commands in total: NWS thunderstorm and
  dry-lightning potential over the next 24 hours, preserving even slight chances
  and stated probabilities. Pacific time defaults to PST/PDT; the installed
  shared `responder.timezone` is manually adjustable without rebuilding and
  persists across upgrades for every MeshCore reply program.
- Adds pinned `tzdata` for reliable IANA timezone support on Windows. Rebuilt
  ZIPs/installers include source, configuration, tests, and function documentation.
  Existing configurations need explicit command/channel assignment and a restart.

- Added `!heatadv` for GPS coordinates, US ZIP codes, and city/state input, with
  California as the city default. Reports each active NWS heat warning, watch,
  and advisory using the defined reply format and supplied location text.
- Confirms NWS coverage before reporting no advisories; unavailable or invalid
  data produces an error. Includes paired command registration, offline tests,
  and usage documentation. Rebuilt ZIPs and installers include this change;
  merge the active command/channel configuration and restart after upgrading.

- Added [FUNCTION_REFERENCE.md](FUNCTION_REFERENCE.md) for every maintained
  service function, method, and nested callback; test helpers are excluded.

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
- See the [installation guide](../INSTALL.md) for supported systems, installation,
  optional credentials, maintenance and validation limits. These are online
  installers; Python runtimes and dependency wheels are downloaded during setup.


Updates the Linux service from `v0.1.1-alpha`.

### Changes since v0.1.1-alpha

- Added `!snowpack` for California GPS, ZIP, or city input, with tagged replies
  containing nearest CDEC hourly snow depth, NWS next-24h snowfall, station name,
  and distance. Depth/forecast values are in inches; stale or missing values are
  unavailable and out-of-state locations are rejected.
- Added `!floodalarm`: an immediate queued acknowledgment, a silent initial
  baseline, 20-minute checks, and same-channel notifications when supported NWS
  flood-alert types change or clear. Radio spacing can delay transmission.
- Each accepted `!floodalarm` replaces that sender's location and resets a
  four-hour limit. `!floodwarn` remains a one-shot lookup and never renews alarms.
  Bulletin text/ID changes alone do not trigger a notification.
- Added `flood_alarm.py`, SQLite subscriptions in `runtime/bridge.sqlite3`,
  separate acknowledgment/monitor workers, structured flood snapshots, and
  stale-result/expiry guards before sending. Restarts do not extend expiry.
  Lookup errors retain the last good baseline; failed sends are not replayed.
- Added `scripts/snowpack.py`, new configuration entries, 20 snowpack tests,
  23 flood-alarm tests, and commented algorithm adjustment points. Both service
  packages now include nine commands. Existing UV and flood-warning commands
  and flood-warning output are retained.
- Distribution ZIPs under `dist/` are built by the workspace packager with
  shared-code and ZIP integrity checks. They include tests/documentation and
  exclude local environments, runtime data, caches, and historical backups.

- Added `verify.sh` for full test discovery and dependency checks. Removed
  Windows-only launch helpers and the unused Windows virtual environment from
  this folder; Linux setup creates `.venv-linux/`.

### Upgrade from v0.1.1-alpha

Stop the service, back up customized `config.json` and runtime data, and replace
source files with this release. Merge custom MQTT/channel settings into the new
configuration, preserving `!snowpack`, `!floodalarm`, and existing command entries.
Retain the local runtime database if needed; the responder creates its new
subscription table automatically. Keep `AIRNOW_API_KEY` for `!aqi`.
The pinned dependencies are unchanged, and the new commands require no new key.
On a new machine, create a fresh environment rather than copying one.

```bash
bash setup.sh
bash verify.sh
bash Start-Service.sh
```

### Validation record and limitations

Previously recorded checks passed **109 tests per service package on Windows**,
up from 66 in `v0.1.1-alpha`, plus dependency checks. Snowpack live California
city/ZIP/GPS lookups and Nevada rejection were checked. Flood-alarm timing used
simulated time and mocked weather/radio data, alongside local subprocess and
loopback MQTT tests. These results were not rerun for this documentation update.

Native Linux execution, live four-hour monitoring, and physical radio delivery
remain unverified for these additions. The service must run to monitor, and
local send acceptance does not prove reception. This remains an alpha release;
external lookups depend on internet/providers and do not replace official alerts.

See the [project release notes](../RELEASE_NOTES.md) for shared implementation
details, the standalone satellite catalog, EBMUD reference data, workspace cleanup,
and validation limits. Those reference tools/data are separate from the service ZIP.

## v0.1.1-alpha â€” September 20, 2026

Compared with `v0.1.0-alpha`, this Linux service adds:

- `!uv` for the current UV index by coordinates, US ZIP, or city/state.
- `!floodwarn` for active NWS Flash Flood Warnings, Flood Warnings, Flood
  Advisories, and Flood Watches.
- Shared location parsing for coordinates, ZIP and ZIP+4 codes, and US city/state text.
- Per-command reply-part limits, with up to 12 parts for `!floodwarn` and four for
  existing commands.
- `scripts/uv_index.py`, `scripts/flood_warn.py`, `tests/test_uv.py`, and
  `tests/test_floodwarn.py`.
- Updated configuration and documentation for all seven included commands.

No new dependency or API key is required for UV or flood alerts. `!aqi` still
requires `AIRNOW_API_KEY`.

### Upgrade

Stop the service, back up custom settings, copy the new folder contents, and merge
existing MQTT/channel settings into the new `config.json`. Preserve the new `!uv` and
`!floodwarn` command entries. Then run:

```bash
bash setup.sh
.venv-linux/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv-linux/bin/python -m pip check
bash Start-Service.sh
```

All 66 tests passed against this folder using its installed Windows Python
environment. Native Linux execution and physical over-the-air delivery of the new
responses remain unverified.

See the [project release notes](../RELEASE_NOTES.md) for the full change summary,
validation details, and known limitations.


- Adds dedicated !smoke and !firedanger point commands, NOAA HMS observations, public NFDRS percentiles, optional FEMS fuel moisture, and source-age regression tests. See WILDFIRE_GUIDE.md.

## California and Nevada landslide commands

Added `!slidewarn`, `!slidealarm`, and `!slideinfo` with shared ZIP/city/GPS input,
California/Nevada boundary enforcement, NWS source-name preservation, temporary
channel-scoped subscriptions, and a checksummed USGS station catalog.
[Behavior, configuration, and verification limits](LANDSLIDE_GUIDE.md).

### NOAA upstream identifier review

- Added a refreshable, source-cited review of 33 gauges: 16 corroborated NOAA IDs, six with published thresholds, and 17 unresolved IDs.
- Preserve original inventories, current-only readings and categorical uncertainty; withhold conflicting or failed review links.
- Require a defined threshold for the current NOAA category, including minor threshold evidence for `no_flooding`.

### Additional NOAA agency records

- Investigated all 17 unresolved IDs using USGS coverage metadata, NOAA HADS and additional agency records. Added one documented USGS-11462000 -> CDEC CDM -> NOAA YDMC1 successor; 16 remain unresolved.
- The successor has no published flood thresholds and does not create current USGS readings or datum equivalence.
- Refresh verifies the pinned agency report and current CDEC/HADS identity chain; changed evidence withholds the link, including cached observation use.
