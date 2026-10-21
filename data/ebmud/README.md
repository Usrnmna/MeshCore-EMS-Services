# EBMUD local GIS references

[Documentation index](../../docs/README.md) | [Terminal commands and all maintenance options](../../docs/CLI_REFERENCE.md).

These files are shared reference data for programs within MC-EMS-Services.
Basic JSON reading requires no network connection, account, API key, or GIS
library. Service spatial queries require Shapely and pyproj; permanent polygon
repair requires Shapely. Current counts for the twelve datasets appear below.
See the [utility function reference](FUNCTION_REFERENCE.md) for maintenance APIs.

| File | Contents |
| --- | --- |
| [trails.geojson](trails.geojson) | 39 trail features, including geometry and all published attributes. |
| [recreation_points.geojson](recreation_points.geojson) | 42 recreation points, including geometry and all published attributes. |
| [trail_endpoints.geojson](trail_endpoints.geojson) | 78 trail start/end points from `EBMUDtrails2D_ENDS/MapServer/0`. |
| [peaks.geojson](peaks.geojson) | 90 peak points from `peaks/MapServer/0`, including unnamed peaks. |
| [additional_trails.geojson](additional_trails.geojson) | 89 additional trail features from `trailsMoreLight/MapServer/0`. |
| [boundaries/reservoir_annotations.geojson](boundaries/reservoir_annotations.geojson) | 6 reservoir annotation records from boundary layer 0; null geometry is retained. |
| [boundaries/reservoirs.geojson](boundaries/reservoirs.geojson) | 6 reservoir polygons from boundary layer 2. |
| [boundaries/recreation_areas.geojson](boundaries/recreation_areas.geojson) | 2 recreation-area polygons from boundary layer 3. |
| [boundaries/watershed_boundary.geojson](boundaries/watershed_boundary.geojson) | 5 watershed-boundary features from boundary layer 4. |
| [boundaries/ebrpd.geojson](boundaries/ebrpd.geojson) | 324 regional park features from boundary layer 5. |
| [boundaries/ebrpd_display_2_jan_14.geojson](boundaries/ebrpd_display_2_jan_14.geojson) | 16 regional park display features from boundary layer 6. |
| [boundaries/adjacent_local_parks_jan_14.geojson](boundaries/adjacent_local_parks_jan_14.geojson) | 4 adjacent local park features from boundary layer 7. |
| [boundaries/service_metadata.json](boundaries/service_metadata.json) | Raw boundary service metadata, including layer names, IDs, and default visibility. This is ArcGIS metadata, not GeoJSON. |
| [sources.json](sources.json) | Original download URLs, retrieval times in UTC, feature counts, byte counts, and SHA-256 checksums. Dataset paths are relative to this directory. |

Unrepaired GeoJSON files preserve the raw response bytes from EBMUD. Three
polygon datasets have local geometry repairs documented below; their original
raw responses are preserved separately. No features or attributes were removed. Coordinates use WGS 84 (EPSG:4326)
in **longitude, latitude** order. Feature counts describe this snapshot and
may change when refreshed; trail features are not necessarily unique named trails.

The boundary service is a collection of layers, so each queryable layer is
saved separately. Layers 6 and 7 are included even though the webapp hides them
by default. Boundary layer 1 (`Default`) is a map-only annotation sublayer;
its parent, layer 0, supplies the queryable annotation records. There is no
separate layer-1 GeoJSON file. Each dataset has one local reference file.

Reservoir annotation features may have `geometry: null` in EBMUD responses.
Such records are retained unchanged; current counts appear in the manifest. Programs doing spatial calculations should skip
features with null geometry. Annotation GeoJSON does not reproduce the full
ArcGIS label rendering.

## Read the local files

The stable project-relative paths are:

```text
data/ebmud/trails.geojson
data/ebmud/recreation_points.geojson
data/ebmud/trail_endpoints.geojson
data/ebmud/peaks.geojson
data/ebmud/additional_trails.geojson
data/ebmud/boundaries/reservoir_annotations.geojson
data/ebmud/boundaries/reservoirs.geojson
data/ebmud/boundaries/recreation_areas.geojson
data/ebmud/boundaries/watershed_boundary.geojson
data/ebmud/boundaries/ebrpd.geojson
data/ebmud/boundaries/ebrpd_display_2_jan_14.geojson
data/ebmud/boundaries/adjacent_local_parks_jan_14.geojson
data/ebmud/boundaries/service_metadata.json
data/ebmud/sources.json
```

For a Python program saved directly in the project root:

```python
import json
from pathlib import Path

# Set this relative to the program's location, not the terminal's current folder.
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIRECTORY = PROJECT_ROOT / "data" / "ebmud"

# Dataset keys and relative filenames are listed in sources.json.
MANIFEST_FILE = DATA_DIRECTORY / "sources.json"
manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))


def load_dataset(dataset_name):
    """Read one local GeoJSON snapshot by its sources.json dataset key."""
    relative_path = manifest["datasets"][dataset_name]["path"]
    local_file = DATA_DIRECTORY / relative_path
    return json.loads(local_file.read_text(encoding="utf-8"))


# Only datasets required by the program need to be loaded; no network calls are made.
trails = load_dataset("trails")
recreation_points = load_dataset("recreation_points")
trail_endpoints = load_dataset("trail_endpoints")
peaks = load_dataset("peaks")
additional_trails = load_dataset("additional_trails")
reservoir_annotations = load_dataset("reservoir_annotations")
reservoirs = load_dataset("reservoirs")
recreation_areas = load_dataset("recreation_areas")
watershed_boundary = load_dataset("watershed_boundary")
ebrpd = load_dataset("ebrpd")
ebrpd_display = load_dataset("ebrpd_display_2_jan_14")
adjacent_local_parks = load_dataset("adjacent_local_parks_jan_14")

for trail in trails["features"]:
    attributes = trail["properties"]
    print(attributes.get("TRAIL_NAME"), attributes.get("DIFFICULTY"))

# Preserve annotation records on disk, but skip missing geometry when mapping.
for annotation in reservoir_annotations["features"]:
    if annotation["geometry"] is None:
        continue
    print(annotation["properties"].get("TEXTSTRING"))
```

For a program inside either platform package's `scripts/` directory, set
`PROJECT_ROOT = Path(__file__).resolve().parents[2]` instead. For a program
directly inside either platform package, use `parents[1]`.

The `!trail`, `!rec`, `!peak`, `!park`, and `!boundary` commands read these
datasets through each platform package's local GIS modules. The data directory
is configured in that package's `gis_settings.json`. Named attributes return
focused information; `info` requests full details. Filtered `near` queries select
qualifying features before distance ranking, and an omitted radius returns only
the closest match. These query changes do not modify the reference files. Complete
workspace installers rebuilt on October 11, 2026 include these datasets, the
GIS commands, polygon repairs, and preserved originals. Rebuilding does not refresh
remote data; retrieval dates remain in the manifest. Standalone service source ZIPs
exclude this shared directory. A program using these files needs a data path
that matches its installation layout.

## Useful attributes

- Trails: `TRAIL_NAME`, `TRAIL_NAME_1`, `TRAIL_DESC`, `DIFFICULTY`,
  `LENGTH_MIL`, `DISTANCE`, `HOUR`, `ELEVATION_GAIN`, `SUN_SHADE`,
  `SURFACE`, `HIKERS`, `HORSES`, `DOGS`, and `BIKES`.
- Recreation points: `LABEL`, `TYPE`, `PARKING`, `RESTROOM`,
  `DRINKING_WATER`, `PICNIC_AREA`, `FISHING`, `BOAT_LAUNCH`,
  `BOAT_RENTAL`, `PLAYGROUND`, and `PHOTO_NAME`.
- Trail endpoints: `TRAIL_NAME`, `TRAIL_NAME_1`, and `END_POINT`.
- Peaks: `PEAK_NAME` and `ELEVATION`.
- Additional trails: `TRAIL_NAME`, `TRAIL_TYPE`, `TRAIL_START`, `TRAIL_END`,
  `LENGTH_MILES`, `DIFFICULTY`, `DOG`, `HORSE`, `BICYCLE`, and `SUNEXPO`.
  These field names differ from the main trail dataset.
- Boundary layers: annotation text uses `TEXTSTRING`; reservoir descriptions
  use `COMMENT_`; recreation areas and regional parks use `NAME`; watershed
  features use `COUNTY`; adjacent local parks use `SITE_NAME` and `AGNCY_NAME`.

Each feature contains `properties` (attributes) and `geometry` (coordinates,
or null for annotation records without geometry).
Photos and trail-profile images are not embedded in these GeoJSON files.

## Sources and freshness

Source application: [EBMUD East Bay Watershed Trails](https://webapps.ebmud.com/trailmap/).

- [Trail layer](https://gis.ebmud.com/arcgiswa/rest/services/FWEBW/EBMUDtrails2D/MapServer/0)
- [Recreation point layer](https://gis.ebmud.com/arcgiswa/rest/services/FWEBW/RecPoints/MapServer/0)
- [Trail endpoint layer](https://gis.ebmud.com/arcgiswa/rest/services/FWEBW/EBMUDtrails2D_ENDS/MapServer/0)
- [Peak layer](https://gis.ebmud.com/arcgiswa/rest/services/FWEBW/peaks/MapServer/0)
- [Additional trail layer](https://gis.ebmud.com/arcgiswa/rest/services/FWEBW/trailsMoreLight/MapServer/0)
- [Boundary service and sublayers](https://gis.ebmud.com/arcgiswa/rest/services/FWEBW/EBMUDTrails_Boundary/MapServer)

The manifest's `datasets` entries are GeoJSON references. Its `service_resources`
section records the boundary metadata file and the non-queryable sublayer.

These are manually downloaded snapshots, not live trail-condition or closure
feeds. `sources.json` records download time, not the date EBMUD last updated
each feature. Local reads never refresh the data automatically.

## Manual refresh

Python 3.11 or newer is sufficient; no third-party packages are required.
From the project root:

```text
python data/ebmud/refresh_geojson.py
```

The script resolves its data directory relative to its own location and can
also be invoked by absolute path from another working directory. It is never
run automatically by service startup or by importing the module.

Download and verify without replacing the reference files:

```text
python data/ebmud/refresh_geojson.py --check
```

Sources and local filenames are configured in `sources.json` under `datasets`.
All 12 current entries are processed. Network settings are grouped at the top of
[refresh_geojson.py](refresh_geojson.py):

| Setting | Default | Purpose |
| --- | --- | --- |
| `REQUEST_TIMEOUT_SECONDS` | 60 | Timeout per HTTP request. |
| `REQUEST_ATTEMPTS` | 3 | Maximum attempts for network failures. |
| `RETRY_DELAY_SECONDS` | 2 | Delay between failed network attempts. |
| `MAX_RESPONSE_BYTES` | 104857600 (100 MiB) | Upper bound per response. |
| `DATA_DIRECTORY` | Script directory | Manifest, datasets, README, lock, and recovery directory root. |

Source URLs must request all fields, all records (`where=1%3D1`), geometry,
WGS 84 (`outSR=4326`), and GeoJSON. New dataset entries require an existing
local GeoJSON file and exactly one matching count row in the table above.

For each dataset, the script verifies the returned feature count against an
independent count query and compares unique feature IDs with the complete
object-ID lists retrieved before and after the download. ArcGIS errors,
truncation, duplicate or missing IDs, and changing record membership cause
failure before local replacement. Truncated responses are rejected rather
than merged, preserving the raw-response format; exceeding the server record
limit requires a future pagination change. These checks cannot rule out remote
attribute changes that occur without changing record membership.

After all downloads pass, the script stages the raw responses, updated manifest,
and README count rows. The manifest records retrieval times, counts, sizes,
SHA-256 checksums, geometry types, and null-geometry counts. Unrelated manifest
fields remain unchanged. Boundary `service_resources` metadata is not refreshed;
its existing retrieval time and checksum continue to describe its saved file.

Replacement errors trigger restoration of previously replaced files. An abrupt
process termination or power loss can leave a mixed generation: `.refresh-*`
directories retain previous files under `previous/` for manual recovery. A
`.refresh.lock` file prevents overlapping runs. After interruption, confirm that
no refresh process is running, inspect any recovery directory, restore previous
files if necessary, and remove the stale lock before retrying. Programs should
avoid reading the datasets during replacement because the multi-file update is
not atomic. Failed runs return a nonzero exit status.

The script does not build or modify installers.

Offline verification:

```text
python -m unittest discover -s data/ebmud -p test_refresh_geojson.py -v
```

## Local polygon repairs

The following repair record describes the locally repaired snapshot; after a
refresh, `sources.json` is authoritative for whether those repairs are still applied.

Six invalid polygon geometries were repaired with `shapely.make_valid`:

| Dataset | Feature IDs |
| --- | --- |
| `watershed_boundary` | 1 |
| `ebrpd` | 249, 178, 190, 72 |
| `ebrpd_display_2_jan_14` | 10 |

The original affected responses are stored in `originals/`, keyed by SHA-256.
Each affected manifest entry contains `geometry_repair` with original path,
checksum, byte count, per-feature validity reasons, method/library versions,
and processing timestamp. Retrieval timestamps retain their original meaning.
Only invalid geometry was changed; feature IDs, counts, properties, valid
geometries, and nulls were preserved. File checksums and byte counts describe the
current repaired files. All repaired results remained polygonal and nonempty.
This verifies geometric validity, not surveyed or legal boundary accuracy.

The repair can be repeated manually with the service interpreter after installing
its requirements (`shapely==2.1.1`). Run from the workspace root:

```text
python data/ebmud/repair_geojson.py
```

A raw refresh may reintroduce invalid upstream polygons. It clears obsolete
`geometry_repair` metadata for replaced snapshots and retains archived originals.
Run the repair again afterward when permanent local repairs are required. GIS
queries also repair invalid shapes in memory, without writing source files.

Repair verifies manifest byte counts/checksums before processing. Invalid
non-polygon geometry, an empty result, or a non-polygon repair result stops the
operation for manual review. Valid geometries and nulls are unchanged. The tool
uses the same `.refresh.lock` and staged replacement/recovery mechanism as refresh.
A second run against valid snapshots makes no replacements. The CLI has no
dataset-selection or tuning flags; the Python `repair(directory=...)` function
supports an explicit data directory. Refresh sources remain in `sources.json`.

## Maintenance workflow and provenance

The maintenance path is manual. A refresh retrieves upstream geometry, while a
subsequent optional repair derives local polygon geometry and retains its originals.

```text
ArcGIS sources --> refresh_geojson.py --check --> Verify downloads only
       |
       +--> refresh_geojson.py --> Stage and verify complete downloads
                                           |
                                  Replace local snapshots and manifest
                                           |
                         Optional repair_geojson.py with Shapely
                                           |
                       Preserve originals; record repair provenance
                                           |
                        GIS commands read verified local snapshots
```

A later raw refresh can restore upstream geometry defects. Download checks and
geometric validity do not establish current access or legal boundary accuracy.

1. Use the deployed data directory, not an unrelated workspace copy. Allow GIS
   requests to finish or stop the service during maintenance.
2. Run `refresh_geojson.py --check` when download verification alone is needed;
   run `refresh_geojson.py` to replace all snapshots after complete verification.
3. Run `repair_geojson.py` with Shapely installed when permanent valid polygon
   snapshots are required. Refresh validation checks completeness and structure;
   it does not validate polygon topology.
4. Inspect manifest counts, timestamps, checksums, and any `geometry_repair`
   records. Run a local GIS command using the intended settings before resuming
   service operation. Keep archived originals with the repaired datasets.

| Manifest field | Meaning |
| --- | --- |
| `source_url`, `path` | Upstream raw query and local path relative to this directory. |
| `retrieved_at_utc` | Download time, independent of source feature-edit or repair time. |
| `feature_count`, `geometry_types`, `null_geometry_count` | Current dataset inventory. |
| `byte_count`, `sha256` | Integrity of the currently referenced local file, including any explicit repairs. |
| `geometry_repair` | Repair time, algorithm/library versions, original path/hash/size, and repaired feature IDs/reasons/types. Present only for explicitly repaired snapshots. |
| `service_resources` | Separately retained boundary metadata and map-only layer information; not refreshed by the GeoJSON utility. |

The basic loader above demonstrates direct JSON access. Applications requiring
the service's integrity and refresh checks should use its `Snapshot` loader and
call `verify_unchanged()` before returning a result; its supported layer mapping
excludes annotation-only records. See the
[Linux GIS functions](../../meshcore_mqtt_service/FUNCTION_REFERENCE.md#scripts-gis-data-py)
or [Windows GIS functions](../../meshcore_mqtt_service_windows/FUNCTION_REFERENCE.md#scripts-gis-data-py).
