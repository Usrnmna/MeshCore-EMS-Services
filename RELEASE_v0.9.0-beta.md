# Version 0.9.0-Beta

Version 0.9.0-Beta expands the Linux and Windows MeshCore EMS services with offline GIS queries, additional weather commands, a shared reply timezone, and dedicated Python programs for every bundled command. Both service packages now provide **16 commands**.

This comparison uses the original documented Version 0.3.0-Beta release as its baseline. Later source and installer snapshots reused the `v0.3.0-beta` version, so some installations may already include the heat-alert, lightning, or timezone features below.

## Highlights

- Five offline GIS commands for trails, recreation facilities, peaks, parks, and boundaries.
- Focused subcommands for individual attributes and policy or amenity searches.
- Closest-only results when `near` is supplied without a radius.
- NWS heat-alert and lightning-potential commands.
- One persistent timezone setting for MeshCore reply timestamps.
- Dedicated executable Python entry points for all 16 commands.
- Manual GeoJSON refresh, completeness checks, and polygon-repair provenance.
- Rebuilt Windows x64, Linux x86_64, and Raspberry Pi ARM64 installers.

## Added commands

| Command | Function | Example |
| --- | --- | --- |
| `!trail` | Trail policies, length, difficulty, terrain, and related areas | `!trail Bear Creek dogs` |
| `!rec` | Recreation facilities, amenities, and locations | `!rec water near 37.90 -122.20` |
| `!peak` | Peak elevations and coordinates | `!peak Wildcat Peak elevation` |
| `!park` | Park status, managing agency, and associated features | `!park Pleasanton Ridge status` |
| `!boundary` | Mapped containment, nearby areas, and trail overlaps | `!boundary parks near 37.90 -122.20` |
| `!heatadv` | Active NWS extreme heat warnings, watches, and heat advisories | `!heatadv Sacramento` |
| `!lightning` | NWS thunderstorm and lightning potential over the next 24 hours | `!lightning Sacramento` |

The existing `!status`, `!time`, `!aqi`, `!traffic`, `!rivers`, `!uv`, `!floodwarn`, `!snowpack`, and `!floodalarm` commands remain available.

## Offline GIS queries

The GIS commands use the bundled EBMUD reference datasets without an API key or network request. Named queries support focused attributes, while `info` requests the full summary.

```text
!trail Bear Creek dogs
!trail Bear Creek info
!trail dogs near 37.90 -122.20
!trail dogs near 37.90 -122.20 5
!rec Briones Overlook Staging Area parking
!peak Wildcat Peak elevation
!park Pleasanton Ridge status
!boundary trail Bear Creek
```

### Focused subcommands

| Command | Available attributes |
| --- | --- |
| `!trail` | `dogs`, `horses`, `bikes`, `length`, `difficulty`, `gain`, `surface`, `shade`, `time`, `start`, `areas`, `description`, `info` |
| `!rec` | `type`, `parking`, `restrooms`, `water`, `picnic`, `fishing`, `boatlaunch`, `boatrental`, `playground`, `horsetrailers`, `location`, `info` |
| `!peak` | `elevation`, `location`, `info` |
| `!park` | `status`, `agency`, `trails`, `recreation`, `info` |
| `!boundary` | Category prefixes: `parks`, `watersheds`, `reservoirs`, `recreation` |

A bare command displays usage guidance. A named feature without an attribute returns compact identification and the available choices.

### Proximity behavior

- **Without miles:** `near LAT LON` returns exactly one closest matching feature, without an implicit search radius.
- **With miles:** `near LAT LON MILES` returns qualifying features within that radius, nearest first, subject to configured result and reply limits.
- Policy and amenity filters run before distance ranking. Missing, unknown, or conflicting values do not qualify as affirmative matches. Conditional source wording is retained.
- Boundary coordinate queries report containment; boundary `near` queries follow the closest-only or explicit-radius rules.
- Distances describe mapped geometry, not walking routes or travel times.

GIS replies omit the trailing `Snapshot ...` text. Retrieval dates and provenance remain in the source manifest.

## Weather and timezone additions

### Heat alerts: `!heatadv`

The heat command checks active NWS alerts for GPS coordinates, a US ZIP/ZIP+4 code, or a city and state. City names without a state default to California. Supplied location text is preserved, with repeated whitespace normalized.

```text
!heatadv Sacramento
!heatadv 95814
!heatadv 38.5816 -121.4944
!heatadv Reno NV
```

Supported response bodies are:

```text
There is no Heat Advisories for <location>
Advisory: Extreme Heat Warning for <location>
Advisory: Extreme Heat Watch for <location>
Heat Advisory for <location>
```

- Reports every distinct applicable type in warning, watch, advisory order.
- Recognizes legacy `Excessive Heat Warning/Watch` source names and displays them as `Extreme Heat Warning/Watch`.
- Excludes expired, ended, cancelled, test, and not-yet-effective alerts. An effective watch can describe a future heat event.
- Verifies NWS point coverage before returning results. Missing coverage, network errors, or malformed/incomplete responses cannot produce a false no-advisories reply.
- Performs one lookup per request; it does not create a subscription.

The responder adds the sender tag and returns results on the requesting channel. Internet access is required; no API key is needed. City and ZIP searches represent a resolved point rather than the entire named area.

### Lightning potential: `!lightning`

The lightning command combines NWS point alerts and forecast-grid information for the next **24 elapsed hours**, measured from the original request timestamp. It accepts the same GPS, ZIP, and city/state inputs as the heat command.

```text
!lightning Sacramento
!lightning 95814
!lightning 38.5816, -121.4944
!lightning Reno NV
```

Response bodies follow these formats:

```text
Lightning Strike Warning for <location> at <time window> (<stated chance/level>)
No Lightning expected for <location> in the next 24h
```

- Includes slight-chance thunderstorms, positive stated thunderstorm probabilities, and dry-lightning indicators.
- Preserves the chance or activity level supplied by NWS. An alert without a stated chance reports `chance not stated`; rain probability is not treated as lightning probability.
- Retains separate forecast windows and their chance levels, clipped to the requested 24-hour period.
- Uses the saved reply timezone, including daylight-saving transitions. Windows describe forecast or alert periods, not predicted times of individual strikes.
- Retains known hazards during a partial provider outage; incomplete information must not produce a false clear result.

`Lightning Strike Warning` is the program's summary label, not a standalone official NWS lightning-warning product. Internet access is required; no API key is needed. The command is a one-shot lookup and does not schedule ongoing monitoring.

### Shared persistent reply timezone

A single `responder.timezone` setting controls MeshCore reply timestamp formatting. The default is `America/Los_Angeles`, with automatic PST/PDT handling. Other IANA zones, such as `America/Denver` or `America/New_York`, can be selected.

Set the field inside the existing `responder` object in the active configuration:

```json
"timezone": "America/Los_Angeles"
```

| Deployment | Active configuration |
| --- | --- |
| Linux OS service | `/etc/meshcore-ems/config.json` |
| Windows OS service | `C:\ProgramData\MeshCore-EMS\config.json` |
| Source-folder operation | The platform package's `config.json` |

The shared setting applies to `!time`, AQI observation times, river issuance and reading times, and lightning forecast windows. It survives restarts and installer upgrades; changing it requires a service restart, with no recompilation or reinstall.

- Existing configurations without the field default to Pacific time. Upgrade configuration preserves an existing custom value.
- Startup validates the timezone. The pinned `tzdata` dependency supplies IANA timezone data, including on Windows.
- Every child program receives `MESHCORE_TIMEZONE`; external programs can use it with `zoneinfo.ZoneInfo`. Shared formatting helpers are provided in `scripts/time_settings.py`.
- MeshCore requests use the shared saved zone rather than per-command timezone overrides. Standalone lightning invocation also supports `--timezone`.
- UTC storage, MQTT timestamps, source timestamp interpretation, and elapsed-time calculations retain their existing semantics. Caltrans undated or recurring schedules retain an explicit Pacific source-time label, and the separate satellite tools remain outside this setting.

## Data maintenance and geometry repairs

- The 12 local GeoJSON datasets contain 701 features, with source URLs, feature counts, and SHA-256 hashes recorded in the manifest.
- A manually invoked refresh program verifies complete feature-ID and count coverage, updates manifest hashes and README counts, and supports recovery from failed updates.
- Six invalid polygons across three datasets were repaired. Original responses and per-feature repair metadata remain available.
- GIS settings expose the data location, projected coordinate system, explicit-radius limit, result count, and reply-size limits.
- Refresh and repair operations remain manual. A fresh upstream download can reintroduce invalid geometry.

## Program organization and documentation

Every bundled command has a dedicated executable Python program in each platform package's `scripts/` directory. Shared helpers provide reusable parsing, data access, formatting, and geometry operations. Registrations point to the dedicated programs instead of selecting commands through a generic dispatcher.

The dedicated `floodalarm.py` program supplies structured readings; persistent subscription scheduling and acknowledgments remain owned by the service. Direct script invocation does not create a subscription.

Documentation includes command syntax, response examples, settings, source loading, maintenance procedures, and function references. Maintained documentation and comments use impersonal technical wording. Ignore policies cover generated artifacts, caches, credentials, runtime state, and interrupted writes while retaining source and reference data.

USB serial, BLE, TCP, multi-channel routing, private-channel controls, and external operator programs were already available in Version 0.3.0-Beta and remain supported.

## Distribution assets

| Asset | Purpose |
| --- | --- |
| `MeshCore-EMS-v0.9.0-beta-windows-x64-setup.exe` | Windows 10/11 x64 online installer |
| `MeshCore-EMS-v0.9.0-beta-linux-x86_64.run` | Linux x86_64 online installer |
| `MeshCore-EMS-v0.9.0-beta-raspberry-pi-arm64.run` | Raspberry Pi 64-bit online installer |
| `MeshCore-EMS-v0.9.0-beta-installers.zip` | All three installers, installation guide, validation record, and checksums |
| `meshcore_mqtt_service.zip` | Linux service source package |
| `meshcore_mqtt_service_windows.zip` | Windows service source package |

Complete installers include the shared datasets and preserved repair originals. The smaller service ZIPs require `data/ebmud` separately. Installers download Python and dependencies during installation; GIS queries operate offline afterward. SHA-256 files accompany the installer artifacts and combined bundle. Windows assembly file versions are `0.9.0.0`.

## Upgrade from Version 0.3.0-Beta

1. Stop the service and back up active configuration, credentials, runtime state, external programs, GIS settings, and locally maintained data.
2. Install the matching Version 0.9.0-Beta package, or deploy the updated source and pinned dependencies together.
3. Review command registrations. Existing definitions are preserved during upgrades; older dispatcher registrations must be merged with the dedicated-program definitions. New commands added to an existing channel registry require explicit channel assignments.
4. Confirm GIS data paths. Bundled GIS settings use `../data/ebmud` relative to the settings file. External settings require `--settings` in each GIS command registration.
5. Remove obsolete `default_radius_miles` settings if present. They are ignored; an omitted radius returns only the closest match. Explicit radii remain governed by `maximum_radius_miles`.
6. Run configuration and platform verification checks, confirm file access under the service account, then restart and verify permitted-channel replies.

Preserve transport, MQTT, channel, credential, and timezone settings. External GIS settings should be retained separately because installer upgrades replace bundled application files.

## Validation and limitations

Recorded validation for this release includes:

- **239 tests passed per platform source package on Windows**, including 26 GIS tests per package.
- **14 installer configuration and packaging tests passed.**
- Service ZIP contents matched current source; Linux payload inventories and hashes, the staged Windows compiler payload and x64 service host, combined bundle integrity, and artifact checksums passed verification.
- Documentation checks covered 19 maintained Markdown files, 292 links and anchors, 26 JSON examples, and 501 function entries.

These results do not establish native Linux execution, installed-service operation, or physical radio delivery for the GIS additions. The Windows installer is unsigned. Reference data represents saved source information; valid geometry does not establish current access rules, legal boundary accuracy, or trail conditions. Weather responses remain subject to provider availability and do not replace official emergency notifications.
