# Windows service release notes

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


Updates the Windows 10 x64 service from `v0.1.1-alpha`.

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

- Updated `verify.cmd` to discover every test suite and check dependencies.
  Removed historical porting hash manifests and their one-time checker; retained
  the Windows launchers, local environment, and runtime data during cleanup.

### Upgrade from v0.1.1-alpha

Stop the service, back up customized `config.json` and runtime data, and replace
source files with this release. Merge custom MQTT/channel settings into the new
configuration, preserving `!snowpack`, `!floodalarm`, and existing command entries.
Retain the local runtime database if needed; the responder creates its new
subscription table automatically. Keep `AIRNOW_API_KEY` for `!aqi`.
The pinned dependencies are unchanged, and the new commands require no new key.
On a new computer, do not copy `.venv`, `runtime`, or `__pycache__`; create a local
environment using setup before verification and startup.

```bat
setup.cmd
verify.cmd
Start-Service.exe
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

Compared with `v0.1.0-alpha`, this Windows 10 x64 service adds:

- `!uv` for the current UV index by coordinates, US ZIP, or city/state.
- `!floodwarn` for active NWS Flash Flood Warnings, Flood Warnings, Flood
  Advisories, and Flood Watches.
- Shared location parsing for coordinates, ZIP and ZIP+4 codes, and US city/state text.
- Per-command reply-part limits, with up to 12 parts for `!floodwarn` and four for
  existing commands.
- `scripts\uv_index.py`, `scripts\flood_warn.py`, `tests/test_uv.py`, and
  `tests/test_floodwarn.py`.
- Updated `verify.cmd`, configuration, and documentation for all seven commands.

No new dependency or API key is required for UV or flood alerts. `!aqi` still
requires `AIRNOW_API_KEY`.

### Upgrade

Stop the service, back up custom settings, copy the new folder contents, and merge
existing MQTT/channel settings into the new `config.json`. Preserve the new `!uv` and
`!floodwarn` command entries. On another computer, do not copy `.venv`,
`runtime`, or `__pycache__`; run `setup.cmd` to create a local environment.

```bat
setup.cmd
verify.cmd
Start-Service.exe
```

The updated `verify.cmd` ran all 66 tests successfully and reported no broken
requirements on Windows 10 x64 with Python 3.13. Automatic over-the-air delivery of
the new responses remains unverified.

See the [project release notes](../RELEASE_NOTES.md) for the full change summary,
validation details, and known limitations.

