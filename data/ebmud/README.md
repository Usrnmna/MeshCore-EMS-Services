# EBMUD local GIS references

These files are shared reference data for programs within MC-EMS-Services.
Reading them requires no network connection, account, API key, or GIS library.

| File | Contents |
| --- | --- |
| [trails.geojson](trails.geojson) | 39 trail features, including geometry and all published attributes. |
| [recreation_points.geojson](recreation_points.geojson) | 42 recreation points, including geometry and all published attributes. |
| [trail_endpoints.geojson](trail_endpoints.geojson) | 78 trail start/end points from `EBMUDtrails2D_ENDS/MapServer/0`. |
| [peaks.geojson](peaks.geojson) | 90 peak points from `peaks/MapServer/0`, including unnamed peaks. |
| [additional_trails.geojson](additional_trails.geojson) | 89 additional trail features from `trailsMoreLight/MapServer/0`. |
| [boundaries/reservoir_annotations.geojson](boundaries/reservoir_annotations.geojson) | 6 reservoir annotation records from boundary layer 0; one has null geometry. |
| [boundaries/reservoirs.geojson](boundaries/reservoirs.geojson) | 6 reservoir polygons from boundary layer 2. |
| [boundaries/recreation_areas.geojson](boundaries/recreation_areas.geojson) | 2 recreation-area polygons from boundary layer 3. |
| [boundaries/watershed_boundary.geojson](boundaries/watershed_boundary.geojson) | 5 watershed-boundary features from boundary layer 4. |
| [boundaries/ebrpd.geojson](boundaries/ebrpd.geojson) | 324 regional park features from boundary layer 5. |
| [boundaries/ebrpd_display_2_jan_14.geojson](boundaries/ebrpd_display_2_jan_14.geojson) | 16 regional park display features from boundary layer 6. |
| [boundaries/adjacent_local_parks_jan_14.geojson](boundaries/adjacent_local_parks_jan_14.geojson) | 4 adjacent local park features from boundary layer 7. |
| [boundaries/service_metadata.json](boundaries/service_metadata.json) | Raw boundary service metadata, including layer names, IDs, and default visibility. This is ArcGIS metadata, not GeoJSON. |
| [sources.json](sources.json) | Original download URLs, retrieval times in UTC, feature counts, byte counts, and SHA-256 checksums. Dataset paths are relative to this directory. |

All GeoJSON files preserve the raw response bytes from EBMUD. They have not
been reformatted, simplified, or filtered. Coordinates use WGS 84 (EPSG:4326)
in **longitude, latitude** order. Feature counts describe this snapshot and
may change when refreshed; trail features are not necessarily unique named trails.

The boundary service is a collection of layers, so each queryable layer is
saved separately. Layers 6 and 7 are included even though the webapp hides them
by default. Boundary layer 1 (`Default`) is a map-only annotation sublayer;
its parent, layer 0, supplies the queryable annotation records. There is no
separate layer-1 GeoJSON file. The repeated trail-endpoints URL is stored once.

One reservoir annotation feature has `geometry: null` in EBMUD's response.
It is retained unchanged. Programs doing spatial calculations should skip
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


# Load only the datasets your program needs; no network calls are made.
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

The existing service commands do not yet consume these datasets. The shared
directory is available to both packages while they are inside this project.
When distributing a platform package on its own with a future GIS feature,
include the datasets in that package and adjust its data path accordingly.

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
or null for the annotation record noted above).
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

To refresh, retrieve each `datasets` entry's `source_url` in `sources.json`, check that it returns
a GeoJSON `FeatureCollection`, and compare the downloaded feature count with
the layer's `/query?where=1%3D1&returnCountOnly=true&f=json` result. Do not replace
a complete snapshot with a truncated response; fetch all pages if the service's
record limit is exceeded. Update the manifest's timestamps, counts, byte sizes,
and checksums and the counts in this README when replacing the files.
Refresh `service_resources.boundaries.source_url` separately as ordinary JSON
metadata, updating its retrieval time, byte count, and checksum. Check its layer
list for changes in available layers or query capabilities.
