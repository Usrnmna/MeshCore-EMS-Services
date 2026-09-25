# Release notes

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

Both platform packages now include `!snowpack` for California GPS, ZIP, or city
input. Replies include the sender tag, nearest CDEC hourly snow depth in inches,
NWS next-24h snowfall in inches, station name, and distance in miles. Missing or
stale values are explicitly unavailable. Includes 20 regression tests per package.
Restart the service after updating. Both service ZIP archives have been rebuilt with the snowpack addition; local
Python environments, runtime databases, and bytecode caches are excluded.

Validation: all 86 tests passed in each package on the Windows host, and both
Python environments passed dependency checks. Live California city, ZIP, and GPS
lookups returned station depths and forecasts; Nevada city, ZIP, and GPS requests
were rejected. No service restart, radio transmission, or native Linux execution
was performed for this addition.

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

