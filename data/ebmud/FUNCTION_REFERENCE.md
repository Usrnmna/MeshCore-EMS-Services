# EBMUD maintenance function reference

See [data maintenance instructions](README.md) for manual refresh, complete-download
checks, repair provenance, and recovery. These utilities are separate from service
query execution. Importing them does not perform a refresh or repair. Function
descriptions document source behavior, not live upstream availability.

## Modules

- [refresh_geojson.py](#refresh-geojson-py)
- [repair_geojson.py](#repair-geojson-py)

<a id="refresh-geojson-py"></a>

## refresh_geojson.py

[Source](refresh_geojson.py)

| Function signature | Purpose and behavior |
| --- | --- |
| `read_json(raw)` | Decode JSON and reject ArcGIS errors, including errors sent with HTTP 200. |
| `fetch(url)` | Download bounded response bytes with retries for network failures only. |
| `query_url(source_url, **parameters)` | Build independent verification queries against the configured layer. |
| `validate_source(source_url)` | Require a complete WGS 84 GeoJSON query rather than a filtered snapshot. |
| `feature_ids(source_url)` | Obtain the full object-ID set independently of feature response limits. |
| `download_dataset(entry)` | Preserve raw bytes only when count and exact ID coverage prove completeness. ID checks before and after downloading detect membership changes. They do not provide a transactionally consistent snapshot of remote attribute edits. Null geometry is valid and remains unchanged. |
| `update_readme(text, datasets)` | Update the count at the start of each existing dataset table row. |
| `install_files(directory, files)` | Stage every file, then replace files individually with exception rollback. A process or power interruption can leave a mixed generation. The retained .refresh-* directory contains the previous files for manual recovery. |
| `refresh(directory=DATA_DIRECTORY, check_only=False)` | Validate all configured datasets before updating snapshots and metadata. An exclusive lock prevents overlapping runs. Existing service_resources metadata remains unchanged because this utility refreshes GeoJSON only. |
| `main()` | Expose manual refresh and download-only verification from any working directory. |

<a id="repair-geojson-py"></a>

## repair_geojson.py

[Source](repair_geojson.py)

| Function signature | Purpose and behavior |
| --- | --- |
| `repair(directory=DATA_DIRECTORY)` | Repair invalid polygons with GEOS make_valid; abort on non-polygon results. Original affected files are retained under originals/ by their SHA-256. Counts, properties, feature IDs, valid geometries, and nulls are preserved. A repair establishes geometric validity, not surveyed boundary accuracy. |

