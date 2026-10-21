# California State Parks local GIS references

[Documentation index](../../docs/README.md) | [Terminal commands and all maintenance options](../../docs/CLI_REFERENCE.md).

Local snapshots from the [California State Parks GIS Data page](https://www.parks.ca.gov/?page_id=29682) are available for Python programs in this project. Attribution: California State Parks, Department of Parks and Recreation.

The collection contains **11 dataset types and 56,650 features**, with 31 distinct published downloads plus 11 assembled GeoJSON collections. Park-boundary geometry repairs are recorded separately; downloaded source archives and raw service-response pages are preserved. No MeshCore command registration or installer artifact was changed for this acquisition.

## Dataset inventory

| Dataset key | Features | Geometry | Contents |
| --- | ---: | --- | --- |
| [`park_boundaries`](geojson/park_boundaries.geojson) | 461 | MultiPolygon, Polygon | Park unit boundaries; names, unit numbers, and classification. |
| [`routes`](geojson/routes.geojson) | 13,139 | LineString, MultiLineString | Route segments, names, categories, classes, types, and source length fields. |
| [`buildings`](geojson/buildings.geojson) | 3,246 | Point | Building reference points and classification attributes. |
| [`structures`](geojson/structures.geojson) | 35,067 | Point | Structure reference points and classification attributes. |
| [`picnic_grounds`](geojson/picnic_grounds.geojson) | 1,466 | Point | Picnic/day-use reference points and classifications. |
| [`campgrounds`](geojson/campgrounds.geojson) | 531 | Point | Campground points, names, classifications, and what3words addresses. |
| [`parking`](geojson/parking.geojson) | 2,359 | Point | Parking points, names, use types, and trailhead attributes. |
| [`park_entry_points`](geojson/park_entry_points.geojson) | 288 | Point | Park entrances, addresses, management status, website/map links, and coordinates. |
| [`field_divisions`](geojson/field_divisions.geojson) | 4 | Polygon | Administrative division polygons. |
| [`districts`](geojson/districts.geojson) | 21 | Polygon | Administrative district polygons and division relationships. |
| [`sectors`](geojson/sectors.geojson) | 68 | Polygon, MultiPolygon | Administrative sector polygons and district/division relationships. |

## Files and provenance

- `geojson/`: complete service exports assembled into one FeatureCollection per dataset, in EPSG:4326 longitude/latitude order. These are the recommended Python lookup references.
- `raw/`: 11 Shapefile archives, nine file-geodatabase archives, and 11 KML/KMZ downloads. The administrative file geodatabase contains all three administrative layers and is stored once. ZIP contents retain their original filenames and sidecar files.
- `raw_geojson/`: unmodified GeoJSON response bodies from the service queries. Each page was requested by an explicit object-ID batch using read-only ArcGIS query POST requests.
- `originals/`: the original assembled park-boundary GeoJSON, preserved byte-for-byte before repair.
- `metadata/`: ArcGIS item descriptions, layer schemas, domains, coordinate systems, service inventories, and before/after count and ID responses.
- [`sources.json`](sources.json): dataset paths, URLs, timestamps, counts, SHA-256 values, raw-file relationships, and integrity entries for every acquired reference file.
- `source/`: the original GIS page including its complete terms, the download inventory, catalog/export receipts, and validation reports.
- [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md): source field names, aliases, types, and available field domains. Detailed subtype definitions remain in the layer JSON.
- [`reference.py`](reference.py): standard-library-only local loading and integrity checks. Importing it performs no network request.

The public gallery also contains viewer/application items. They are catalog interfaces, not additional feature datasets; their entries are retained in `metadata/gallery_search.json`. Basemap tiles and individual external park webpages or map documents referenced inside attributes are not mirrored.

## Verification and source differences

Every GeoJSON page was checked against its requested object IDs. Aggregate IDs and counts were checked against the service before and after download, and editing metadata remained unchanged during each layer export. All 11 Shapefile layers and all 11 layers in the file geodatabases match those counts. Every ZIP passed its integrity check.

Some published KML/KMZ exports differ from the current service data:

| Dataset | GeoJSON / Shapefile / file geodatabase | Published KML placemarks |
| --- | ---: | ---: |
| Park boundaries | 461 | 462 |
| Buildings | 3,246 | 3,240 |
| Structures | 35,067 | 34,993 |
| Picnic grounds / day-use areas | 1,466 | 1,457 |
| Sectors | 68 | 67 |

These are observed source-format differences, not missing GeoJSON pages. Original KML/KMZ files remain unchanged and should not be combined as if they represented the same snapshot. The source page describes 67 sectors; the service, Shapefile, and file geodatabase contain 68. Counts refer to features or KML placemarks, not necessarily distinct parks or facilities.

Shapely validation identified **48 invalid park-boundary polygon features** in the source export. They were repaired in the local `geojson/park_boundaries.geojson` with `shapely.make_valid` using the default linework method. All **461 park-boundary geometries are now valid and nonempty**. All 413 previously valid geometries, feature IDs, attributes, order, and counts remain unchanged. No parts were discarded, and all repaired outputs remain Polygon or MultiPolygon. The original assembled file is retained under `originals/`; raw service pages and native archives remain unchanged.

The original defects appear in [`source/geometry_validation.json`](source/geometry_validation.json); per-feature repair reasons, types, area diagnostics, library versions, and original hashes appear in [`source/park_boundaries_repair.json`](source/park_boundaries_repair.json). Area diagnostics use square degrees and are not acreage measurements. **23 repaired features change the planar filled-area diagnostic by more than 1%**; the largest change is a 26.4% decrease for Bodie SHP feature 9483. Nested shells and self-intersections make the original interior ambiguous. These features are flagged in the repair report for map review before boundary-sensitive decisions. Topological validity does not verify the intended filled area. The manifest and loader point to the repaired local copy. Original acquisition receipts describe the pre-repair export; `geometry_repair` records the subsequent derivation. All eleven current GeoJSON collections have valid, nonempty, non-null geometries under the recorded checks. A future download can reintroduce defects. Geometric validity does not establish current public access, ownership, or legal boundary accuracy.

Native park/route/facility files use EPSG:3857; native administrative files use EPSG:3310. The GeoJSON exports are two-dimensional EPSG:4326 service query results. Native route archives retain the source Z/M dimensions; GeoJSON copies are not substitutes for those dimensions. Length/area attributes retain source units and are not recalculated when the service returns geographic coordinates. Consult layer metadata before interpreting units or coded attributes.

## Load data locally with Python

From a Python program at the repository root:

```python
from data.california_state_parks.reference import load_dataset, load_manifest

parks = load_dataset("park_boundaries")
routes = load_dataset("routes")
datasets = load_manifest()["datasets"]

for feature in parks["features"]:
    print(feature["properties"].get("UNITNAME"))
```

The loader locates data relative to its own module and verifies byte size, SHA-256, feature counts, and unique object IDs. A different snapshot directory can be selected with `load_dataset("routes", data_directory=absolute_path)`. Missing or changed files raise exceptions; no remote fallback occurs.

For an existing platform command program under either `scripts/` directory, resolve the project root using `Path(__file__).resolve().parents[2]` and read `data/california_state_parks/sources.json`. For a program directly inside a platform package, use `.parents[1]`. Standalone service ZIPs do not contain this shared directory. A plain JSON loading example is:

```python
from pathlib import Path
import json

project_root = Path(__file__).resolve().parents[2]  # Program in a platform scripts/ directory.
data_root = project_root / "data" / "california_state_parks"
manifest = json.loads((data_root / "sources.json").read_bytes())
dataset = manifest["datasets"]["park_entry_points"]
entry_points = json.loads((data_root / dataset["path"]).read_bytes())
```

Plain JSON reading does not perform integrity checks; use the loader or run the verification command first. Optional GeoPandas can load GeoJSON with `geopandas.read_file(path)`. Native Shapefile and file-geodatabase archives require a compatible GIS reader; preserve all sidecar files if extracting them.

```console
python data/california_state_parks/reference.py
```

This verifies all indexed files and loads each dataset. It does not refresh data or validate current provider conditions. Downloads are manually acquired snapshots; the acquisition does not add a scheduled refresh or radio command.

## Attribution and reuse terms

The original terms are preserved in [`source/gis_data_page.html`](source/gis_data_page.html). CSP requires attribution, restricts sale and alteration, describes free personal/public-sector distribution, and requires prior permission for commercial use. Source warranty, currency, and liability disclaimers also apply. Consult the original terms and contact `geodata@parks.ca.gov` where approval is required. The repository license does not replace the data terms.

## Loader function reference

| Function | Behavior |
| --- | --- |
| `load_manifest(data_directory=DATA_DIRECTORY)` | Reads local source metadata. |
| `load_dataset(name, data_directory=DATA_DIRECTORY)` | Returns verified GeoJSON; raises on missing data, hash/size mismatch, or inconsistent counts/IDs. Geometry is unchanged. |
| `verify_files(data_directory=DATA_DIRECTORY)` | Verifies every manifest-indexed reference file and returns the file count. No network activity. |
