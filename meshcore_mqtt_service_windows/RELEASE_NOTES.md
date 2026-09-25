# Windows service release notes

## v0.2.0-alpha

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

## v0.1.1-alpha — September 20, 2026

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
your MQTT/channel changes into the new `config.json`. Preserve the new `!uv` and
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

