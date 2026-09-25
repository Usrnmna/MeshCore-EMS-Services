# Linux service release notes

## Unreleased - flood alarms

- Added `!floodalarm` with the same inputs as `!floodwarn` and an immediate tagged acknowledgment.
- Added SQLite subscriptions, silent initial baselines, 20-minute change checks, and a four-hour limit.
- Only `!floodalarm` starts or renews monitoring; each accepted call overwrites the saved location and resets the four-hour limit. `!floodwarn` leaves alarms unchanged.
- Added separate acknowledgment/monitor workers, stale-result guards, and a final expiry check before radio transmission.
- Added clearly labeled adjustment points and 23 regression tests; 109 tests passed in each package on Windows.
- Existing flood warning wording and command output are preserved. Restart the service after updating.

Validation uses simulated time and mocked weather/radio data plus real local
subprocess/MQTT tests. No live four-hour monitoring, native Linux execution,
physical radio transmission, or service restart was performed.


## Unreleased - snowpack

- Added `!snowpack` for California GPS coordinates, ZIP codes, and city names.
- Reports CDEC hourly snow depth, NWS next-24h snowfall, nearest station, and distance.
- Preserves same-channel `@sender` replies; unavailable/stale data never implies zero.
- Added 20 offline regression tests. Restart the service after updating.

Validation: all 86 tests passed in each package on the Windows host, and both
Python environments passed dependency checks. Live California city, ZIP, and GPS
lookups returned station depths and forecasts; Nevada city, ZIP, and GPS requests
were rejected. No service restart, radio transmission, or native Linux execution
was performed for this addition.

## v0.1.1-alpha — September 20, 2026

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
your MQTT/channel changes into the new `config.json`. Preserve the new `!uv` and
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

