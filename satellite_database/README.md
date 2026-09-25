# Satellite radio reference database

Build and maintain a local SQLite database of documented satellite radio services.
The same Python program runs on Windows and Linux. Database creation, lookup,
status evidence, and JSON/CSV export require only Python 3.11 or newer.
Skyfield is optional and only needed to calculate position and antenna direction.

The supplied database and exports are in [`../data/satellites/`](../data/satellites/README.md).
This is a standalone reference tool; no MQTT command, radio transmission, or
scheduled/background task is installed.

## Scope

| Scope key | Included capabilities |
| --- | --- |
| `two_way_voice` | Voice repeaters and linear transponders, including FM/NFM and SSB. |
| `two_way_data` | Packet links, APRS and digipeaters. |
| `downlink_audio` | One-way voice, recorded audio, musical identification and experiments. |
| `image_downlink` | SSTV, SSDV and digital image broadcasts. |
| `digital_television` | Digital television/video downlinks. |
| `telemetry` | Spacecraft health, educational/scientific measurements and experiments. |
| `weather_data` | Weather imagery and environmental observations, including non-amateur spacecraft. |
| `weather_alerts` | Weather warnings, forecasts, text and chart broadcasts. |
| `beacon` | CW, modulated and carrier beacons. |
| `data_downlink` | Other documented public-interest digital downlinks. |

A service may have several scope tags. A public uplink is not required.
Modulation, protocol, service category, frequencies, signal bandwidth,
transponder passband, baud rate and data rate are separate fields.
Missing source information stays null instead of being guessed.

**Known retired, decommissioned, re-entered, and future/not-yet-launched satellites
are excluded from the database and exports.** Retirement is checked using source
lifecycle labels and sourced operator exclusions in `operator_overrides.json`.
Existing entries are removed on refresh when retirement becomes known. A failed
repeater alone is never treated as retirement of the whole satellite.

Public databases can contain old or conflicting information. This program
processes every record returned by its configured catalog feeds, but cannot
guarantee that every operating satellite worldwide is documented. Scope admission
is intentionally conservative; unknown-service radios in the AMSAT catalog and
amateur bands, and public-interest signal descriptions, are marked for review.
Being included does not prove public uplink access or that a decoder is available.

## Quick start

Run these commands from the MC-EMS-Services folder. On Linux, use `python3`
if `python` does not select Python 3.11 or newer.

```console
python satellite_database/satellite_db.py refresh
python satellite_database/satellite_db.py summary
python satellite_database/satellite_db.py list --scope image_downlink
python satellite_database/satellite_db.py list --status active
python satellite_database/satellite_db.py show 25544
python satellite_database/satellite_db.py list --satellite RS-44 --json
```

Names, aliases, NORAD numbers and SatNOGS identifiers can be used for lookup.
`show` returns all supported recorded operations, their evidence and orbital data.
`list --status inactive` means supported operations with recent evidence of a
confirmed failure, not missing/nonexistent capabilities.

Offline lookup needs no network. Rebuild from saved source responses with:

```console
python satellite_database/satellite_db.py refresh --offline
python satellite_database/satellite_db.py export
```

Offline refresh preserves the original download times. It does not turn old
evidence into new evidence. Default source caching is 24 hours; CelesTrak is
never requested more often than its two-hour minimum through this cache.
Use `refresh --no-celestrak` to use SatNOGS orbital elements only.

Exit codes: **0** success; **1** error; **2** catalog updated with optional-source
warnings. If a required catalog fails or returns an invalid/empty response, the
existing database is preserved. Optional reception/orbit failures are reported
in `coverage.json`, and previously stored evidence/elements are retained with
their original dates. No automatic HTTP retries or redirects are used.
Do not run two writers against the same database/cache at the same time.

## Status means the state of an individual capability

The program never creates a matrix of imaginary services for every spacecraft.
Each operation originates in a real transmitter record or a sourced manual
addition. A beacon may be active while the same satellite's repeater is inactive.

| Effective status | Required evidence |
| --- | --- |
| `active` | Recent positive reception or explicit operation-specific evidence. |
| `inactive` | Explicit confirmed failure of that existing capability. |
| `scheduled_off` | Intentional shutdown supported by an operator schedule. |
| `unknown` | Missing, stale, conflicting or inconclusive evidence. |

The source's catalog `active`/`inactive` label is preserved separately as
`catalog_status`. An old database edit date is not a recent reception date.
A generic catalog `inactive` label cannot distinguish a failure from a scheduled
shutdown, so it does not create a confirmed-failure status.

AMSAT reception reports are mapped only to an unambiguous existing operation.
Reports that cannot be matched remain in `reception_reports` with a null
`operation_id`; `coverage.json` lists the unmatched labels. A "Not Heard" or
"Telemetry Only" report produces unknown status for the reported mode, never a
failure label or an invented beacon. Contradictory reports in the same time
interval produce unknown status. These are community reports, not verified RF
measurements made by this program.

By default, evidence expires after 30 days. The SQLite `operation_reference`
view evaluates age at query time, including during offline use. JSON and CSV are
dated snapshots: regenerate them with `export` or `refresh` before using their
status fields as current. A positive report does not guarantee uninterrupted
transmission now. `schedule` is null unless explicitly supplied.

## Adjust sources and parameters

- **`settings.json`:** URLs, file paths, timeouts, cache duration, status/orbit age
  limits, admission terms, scope labels and excluded lifecycle states. File paths
  are relative to the settings file. Apply changes with `refresh`.
- **`operator_overrides.json`:** sourced corrections, duplicate suppression,
  retired spacecraft, explicit report-label mappings and optional additions.
  The included NOAA HRIT/EMWIN and ISS HamTV corrections preserve the original
  conflicting SatNOGS data under `raw`. Review dates never advance automatically.
- **`catalog.py`:** short, labeled classification and field-normalization rules.
- **`reports.py`:** AMSAT report parsing and conservative capability matching.
- **`sources.py`:** downloads, cache validation and pagination.
- **`schema.sql`:** tables and the effective-status view.

The `uplink_availability` value is `unknown` when no uplink is documented;
an empty field is not proof that no uplink exists. A specified frequency initially
gets `documented_uplink_access_unknown`. Reviewed corrections/additions can set
`public_uplink` or `downlink_only` with a supporting source.

## Record a confirmed failure, recovery or planned shutdown

First obtain the exact `operation_id` using `list` or `show`. Create a JSON array
like the following, substituting an actual existing ID, evidence time and source.
This is a format example, not a real failure claim:

```json
[
  {
    "operation_id": "satnogs:REPLACE_WITH_EXISTING_TRANSMITTER_UUID",
    "status": "inactive",
    "observed_at": "2026-09-24T18:00:00Z",
    "source_url": "https://operator.example/status",
    "note": "Operator explicitly confirms this repeater has failed.",
    "evidence_kind": "confirmed_failure"
  }
]
```

```console
python satellite_database/satellite_db.py import-observations observations.json
```

Use `operator_schedule` for a scheduled-off observation, `operator_report` for
an operator's recovery notice, or `reception_report` for reception evidence.
Every record must have a nonfuture timestamp, source and explanation. The entire
file is validated before insertion. Observations of nonexistent capabilities
are rejected. Reimporting identical observations does not duplicate them.
Newer observations supersede older ones for status; history remains available
until the satellite is excluded as retired.

For a missing publicly documented spacecraft/service, add its identity to
`additional_satellites` and its actual capability to `additional_operations`
in the overrides file. Use an existing exported object as a field template.
Operation additions require `operation_id`, `satellite_id`, `name`, `source_url`,
`capability_evidence`, and a nonempty list of valid `scopes`. Keep unknown fields
null and use stable IDs such as `operator:mission:beacon`. Satellite additions
require `satellite_id`, `name`, `source_url`, and `lifecycle`; use `in orbit` only
when supported by the source. Unsupported additions fail before catalog changes.

## Optional position and direction

Install the optional dependency in your chosen Python environment:

```console
python -m pip install -r satellite_database/requirements-tracking.txt
python satellite_database/satellite_db.py position 25544 37.7749 -122.4194 --altitude 20
```

This example uses an explicitly supplied San Francisco location, not a detected
user location. The output includes satellite latitude/longitude/altitude, true
azimuth, elevation, range, geometric horizon visibility and orbital epoch.
The calculation is local and uses bundled timescale data; it makes no download.
Elements farther than the configured 14 days from the requested time are rejected.
For a specified UTC time, add `--at 2026-09-25T00:00:00Z`.

Positions change continuously, so the database stores orbital elements rather
than pretending a previously calculated direction stays current. Pass prediction,
rotator control, Doppler radio tuning and RF reception are not implemented.

## Reading the database from another program

The SQLite file is `data/satellites/satellites.sqlite3`. Useful tables:

| Table/view | Purpose |
| --- | --- |
| `satellites` | Names, aliases, NORAD IDs, lifecycle and original catalog records. |
| `operations` | One record per sourced capability/configuration; complete fields in `data_json`. |
| `operation_scopes` | Many-to-many operation/category mapping. |
| `operation_reference` | Query-time status, source labels, freshness evidence and radio details. |
| `observations` | Dated operation-specific status history. |
| `reception_reports` | Parsed AMSAT reports, including unresolved matches. |
| `operation_versions` | Changed capability records and their provenance. |
| `orbits` | TLE and CelesTrak OMM-compatible JSON elements with epochs. |
| `source_fetches` | Source URLs, acquisition times and SHA-256 checksums. |
| `refresh_runs` | Coverage and optional-source errors for each refresh. |

```sql
SELECT satellite_name, norad_id, operation_name, current_status,
       json_extract(data_json, '$.downlink_low_hz') AS downlink_hz,
       evidence_at, status_source
FROM operation_reference
WHERE operation_id IN (
  SELECT operation_id FROM operation_scopes WHERE scope = 'image_downlink'
);
```

SQLite is the primary database. `satellites.json` supplies nested records plus
orbits and observations. `operations.csv` is a flat, spreadsheet-friendly view
of the supported operations. All frequencies and bandwidths use Hz. A transponder
passband width is not the occupied bandwidth of one signal. CSV strings beginning
with spreadsheet formula characters are prefixed with an apostrophe.

## Sources, attribution and validation

- [SatNOGS API](https://db.satnogs.org/api/) and [database](https://db.satnogs.org/):
  capability records and fallback TLEs. Data is licensed CC BY-SA 4.0; retain
  attribution and applicable share-alike terms when redistributing derived data.
- [AMSAT database](https://satdb.amsat.org/) / [machine-readable files](https://github.com/palewire/amateur-satellite-database/tree/main/data):
  JE9PEL/KF0IA/SatNOGS catalog cross-references and aliases. These are partly
  derived from SatNOGS, so agreement is not independent confirmation.
- [AMSAT status](https://www.amsat.org/status/): individual reception reports.
- [CelesTrak GP formats](https://celestrak.org/NORAD/documentation/gp-data-formats.php)
  and [usage policy](https://celestrak.org/usage-policy.php): JSON orbital elements,
  supporting catalog numbers beyond the traditional TLE limit.
- [NOAA HRIT/EMWIN](https://ospo.noaa.gov/operations/goes/hrit/index.html),
  [NOAA retirement status](https://ospo.noaa.gov/operations/poes/status.html),
  [ARISS HamTV](https://www.ariss.org/hamtv-on-the-iss.html), and
  [AMSAT mission status](https://www.amsat.org/two-way-satellites/dead-satellites/):
  explicit, reviewable specification/retirement corrections.

Raw supplier responses in `data/satellites/raw/` are audit/download caches, not
the resulting catalog. They can contain out-of-scope and retired source entries;
those entries are filtered out of the database and exports. Retained checksums
make it possible to identify exactly which source response produced a result.

Run the behavioral tests:

```console
python -m unittest discover -s satellite_database -p "test_*.py"
```

Tests cover independent capability states, failure requirements, stale and
conflicting reports, retirement exclusion/pruning, update preservation, cache
integrity, pagination, scope classification and exports. Software tests and source
downloads do not demonstrate satellite reception.
