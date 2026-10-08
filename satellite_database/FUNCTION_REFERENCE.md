# Satellite Python function reference

See [the catalog guide](README.md) for commands, source policy, and data limitations.

This reference covers functions defined in maintained application files, including
methods and nested callbacks. Test helpers, imported library functions, and generated
files are excluded. Signatures show inputs and defaults; explanations describe the
work and important effects. Update this reference and source docstrings together
when a function changes. These descriptions are source documentation, not evidence
that a live service, device, or provider was tested.

## Modules

- [catalog.py](#catalog-py)
- [reports.py](#reports-py)
- [satellite_db.py](#satellite-db-py)
- [sources.py](#sources-py)

<a id="catalog-py"></a>

## catalog.py

[Source](catalog.py)

Readable scope rules and normalization; no satellite-wide status inference.

| Function signature | Purpose and behavior |
| --- | --- |
| `has_term(text, term)` | Match whole terms so APT does not accidentally match 'adapter'. |
| `has_any(text, terms)` | Return whether text contains any supplied whole term, case-insensitively; no external I/O. |
| `positive_number(value)` | Convert a value to a positive finite float, or return None for invalid, zero, or negative input. |
| `amateur_frequency(value)` | Discovery hint only, never proof that an uplink is public or permitted. |
| `classify(tx, in_amsat, settings)` | Return scope tags plus an admission reason, or a reason for exclusion. |
| `normalize_operation(tx, sat_key, scopes, reason, source_url, fetched_at)` | Preserve source values and leave unreported parameters null. |
| `frequency_band(hz)` | Map a frequency in Hz to HF, VHF, UHF, SHF, or EHF; return None for missing input or a label outside those bands. |
| `tle_epoch(line)` | Use the element epoch, not the time someone downloaded the element set. |

<a id="reports-py"></a>

## reports.py

[Source](reports.py)

Read AMSAT reception reports as text; never execute downloaded JavaScript.

| Function signature | Purpose and behavior |
| --- | --- |
| `parse_amsat_reports(document)` | Extract timestamped tooltip reports, including negative/ambiguous reports. |
| `match_operation(report, satellites, operations, mappings)` | Only unambiguous existing capabilities receive a status observation. |

<a id="satellite-db-py"></a>

## satellite_db.py

[Source](satellite_db.py)

Build, inspect and export a sourced satellite radio reference database. Python 3.11+ standard library. Optional Skyfield is only used by 'position'. See settings.json for sources/tuning and operator_overrides.json for corrections.

| Function signature | Purpose and behavior |
| --- | --- |
| `dumps(value)` | Serialize a JSON-compatible value with sorted keys and Unicode preserved; return the string without writing a file. |
| `read_json(path)` | Read a UTF-8 JSON file, allowing a BOM, and return the decoded value; propagate file and JSON errors. |
| `settings_from(path)` | Load settings, resolve database/cache/export paths relative to the settings file, and reject nonpositive tuning values. |
| `connect(settings, create=False)` | Open the configured SQLite database with row objects and foreign keys enabled; the caller must close it. Without create, reject a missing database. With create, initialize schema version 1 or reject an unsupported version. Create the parent directory if needed; schema initialization writes to disk. |
| `receipt_time(reader, url)` | Return fetched_at from the latest recorded receipt for a URL; raise StopIteration if the reader has no matching receipt. |
| `as_norad(value)` | Convert a value with int() and return a positive NORAD identifier, or None for invalid or nonpositive input. |
| `build_catalog(satellite_rows, transmitters, amsat_rows, settings, fetched_at)` | Join by stable SatNOGS ID, then NORAD ID. Never join different craft by name. |
| `apply_overrides(satellites, operations, overrides, settings)` | Explicit additions require identity, capabilities and sources; no fake modes. |
| `retirement_reason(satellite, settings, overrides)` | Retirement is a spacecraft fact, never inferred from one failed radio. |
| `prune_satellite(db, sat_id)` | Remove retired spacecraft and dependent reference entries in one transaction. |
| `validate_observation(observation, operation_ids)` | A failure label requires a real capability, a date, source and explanation. |
| `save_observation(db, observation)` | Copy an already validated observation, normalize its time to UTC, and insert it idempotently using a content hash. The caller owns the transaction and commit. |
| `fetch_orbits(reader, satellites, settings, warnings, use_celestrak)` | Store elements, not a misleading permanently saved 'current position'. |
| `refresh(settings, args)` | Read required feeds, apply corrections and retirement policy, and commit the resulting catalog and evidence to SQLite. Use cached responses in offline mode; required-feed or override failures stop before catalog mutation. Optional report/orbit failures become warnings. Write cache files, exports, coverage data, and a printed JSON report. Return 0 without warnings or 2 when optional-source warnings remain. |
| `operation_rows(db, settings, satellite=None, scope=None, status=None)` | Freshness is calculated in SQL each time; JSON/CSV exports are snapshots. |
| `find_satellites(db, query)` | Return matching satellite IDs from names, aliases, stable IDs, or NORAD IDs, preferring exact over substring matches; raise ValueError when none match. |
| `atomic_json(path, value)` | Write a JSON value as indented UTF-8 through an adjacent .tmp file, then replace the destination; the parent directory must exist. |
| `export_database(db, settings)` | Write satellites.json, operations.csv, and coverage.json snapshots from SQLite into the configured export directory. Evaluate operation freshness at export time, escape spreadsheet formula prefixes, and replace each output through a temporary file. Create the directory if needed; do not fetch sources or modify the database. |
| `position(db, settings, args)` | Print a Skyfield orbital prediction and observer pointing from stored elements and the requested coordinates/time. Require one satellite match, valid observer coordinates/altitude, and elements within the configured age limit. Return None; raise ValueError for unsupported inputs, missing Skyfield, stale elements, or propagation failure. No refresh or radio operation occurs. |
| `main(argv=None)` | Parse CLI arguments, dispatch the selected catalog command, print results/errors, and close any opened database. Refresh, observation import, summary, and export can write local data; list, show, and position read the catalog. Return 0 on success, 1 for handled errors, or refresh status 2 for optional-source warnings. Argparse handles invalid command syntax separately. |

<a id="sources-py"></a>

## sources.py

[Source](sources.py)

Small, cached HTTP reader. No credentials, background jobs, or radio traffic.

| Function signature | Purpose and behavior |
| --- | --- |
| `utc_now()` | Return the current timezone-aware UTC time as an ISO-8601 string. |
| `parse_time(value)` | Read an ISO UTC timestamp; missing/invalid timestamps remain unknown. |
| `NoRedirect.redirect_request(self, req, fp, code, msg, headers, newurl)` | Reject an HTTP redirect with HTTPError so an operator reviews the configured source URL before following it. |
| `SourceReader.__init__(self, directory, settings, offline=False)` | Create the cache directory and retain settings/offline mode; initialize acquisition receipts without fetching data. |
| `SourceReader.read(self, url, cache_hours=None)` | Return (body_bytes, metadata) for an HTTPS URL from a checksum-verified cache or bounded download. Offline mode requires a cached response. Online cache age uses cache_hours or the configured default. Successful downloads replace the body through a temporary file and write metadata; every successful read records a receipt. Network, redirect, size, and integrity failures propagate to the caller. |
| `SourceReader.records(self, url, required_field)` | Accept a JSON list or paginated results; never silently truncate a feed. |
