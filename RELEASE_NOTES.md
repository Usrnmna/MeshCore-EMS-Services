# Release notes

## v0.2.0-alpha

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

These are previously recorded implementation results, not a new runtime test
run performed for this release-note update:

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
remote reception. No service restart or hardware change is part of this update.

### Upgrade from v0.1.1-alpha

1. Stop the service and back up customized `config.json` and runtime data.
2. Replace the source with the `v0.2.0-alpha` package for the correct platform.
   Preserve your local runtime database if its history is needed; distribution
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

## v0.1.1-alpha — September 20, 2026

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

- Flash Flood Warning 🟥
- Flood Warning 🟧
- Flood Advisory 🟨
- Flood Watch 🟦

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
2. Back up any customized `config.json` and runtime data you want to retain.
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

