# Satellite reference data

The [satellite catalog program](../../satellite_database/README.md) stores its
database, exports, and source cache in this directory.

- **`satellites.sqlite3`**: primary database for local programs and SQL queries.
- **`satellites.json`**: readable snapshot with satellites, supported operations,
  source references, orbital elements and status observations.
- **`operations.csv`**: spreadsheet-friendly operation list.
- **`coverage.json`**: counts, source timestamps/checksums, unmatched reports,
  classification-review counts and source warnings.
- **`raw/`**: original downloaded source responses and checksum metadata.

Known retired/decommissioned/re-entered satellites and unlaunched entries are
excluded from the database and exports. Failed operations of retained satellites
remain available when actually supported by the spacecraft. Source download
caches may contain excluded entries because they preserve unmodified responses.

Status evidence is dated. Use SQLite's `operation_reference` view for status
freshness evaluated at lookup time, or regenerate the exports before relying on
their status labels. `unknown` is not the same as `inactive`. Recent positive
reception is evidence of operation at that time, not guaranteed transmission now.

See the [program instructions](../../satellite_database/README.md) for commands,
adjustable settings, sources, licensing, schema, status rules and limitations.
