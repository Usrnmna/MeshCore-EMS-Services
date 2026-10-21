# California Basin Plan offline data

[Documentation index](../../docs/README.md) | [Terminal commands and all maintenance options](../../docs/CLI_REFERENCE.md).

This repository distributes the download programs, curated configuration, tests
and documentation. Downloaded datasets, generation pointers, generated catalogs
and validation reports are local outputs excluded from Git. Follow the
[fresh-clone water-data setup](../../docs/WATER_DATA_SETUP.md) before using offline
queries. Links to generated catalogs and reports below become available after
the relevant download or validation command completes. Historical investigation
counts describe development evidence, not files included with the repository.

For gauge measurements, verified source-network connections, and scenario-based
CalWater overlays, see the separate [flood-impact reference pilot](../flood_impacts/README.md).
It preserves the original archive and existing tributary relationship tables.

This directory collects the public California Basin Plan Mapping Project (BPMP)
library for offline inspection and data processing. The collection includes all
published regional feature layers and tables, the queryable statewide layers and
tables, original regional file geodatabases, item resources, source metadata, and
the portal's directly linked PDF documentation.

Start with the [regional review folders](REVIEW.md) for readable dataset filenames,
a README and CSV catalog for every region and plan, and separate CalWater levels.
Each region also has searchable geographic names and a separate tributary/parent
relationship table. [Relationship tables](RELATIONSHIPS.md) connect waterbodies
to beneficial uses, reachcodes, grouped features, CalWater hierarchy, and source
provenance, retaining missing and ambiguous matches.
The [organization guide](ORGANIZATION.md) explains names, catalogs, and offline rebuilding.
The [complete source inventory](INVENTORY.md) links every original archived dataset
and native geodatabase. [sources.json](sources.json) selects the active snapshot and
its corresponding review generation.
The [native geodatabase inventory](NATIVE_INVENTORY.md) separately lists the tables
and feature classes stored in the original ZIPs, including count comparisons with
the service exports. Its report identifies the snapshot that was inspected.

## Regional organization

| Regional Water Board | Directory within each snapshot and review generation |
| --- | --- |
| 1 — North Coast | `regions/01_north_coast/` |
| 2 — San Francisco Bay | `regions/02_san_francisco_bay/` |
| 3 — Central Coast | `regions/03_central_coast/` |
| 4 — Los Angeles | `regions/04_los_angeles/` |
| 5 — Central Valley: Sacramento and San Joaquin River Basins | `regions/05_central_valley/sacramento_san_joaquin/` |
| 5 — Central Valley: Tulare Lake Basin | `regions/05_central_valley/tulare/` |
| 6 — Lahontan | `regions/06_lahontan/` |
| 7 — Colorado River Basin | `regions/07_colorado_river/` |
| 8 — Santa Ana | `regions/08_santa_ana/` |
| 9 — San Diego | `regions/09_san_diego/` |
| Statewide representations | `statewide/` |
| CalWater hydrologic boundaries referenced by the web map | `hydrologic_boundaries/calwater_2_2_1/` |
| Viewer, web map, and story resources | `supporting/` |

Regional Water Board areas are the primary organizational categories. Individual
basin and waterbody names remain in their original attribute fields. Central
Valley retains the two separately published plan extracts. Regional records are
not combined with statewide records or deduplicated across source products.
CalWater retains its six published boundary levels: hydrologic region, unit,
area, subarea, SPW, and PW. These hydrologic classifications are separate from the
nine Regional Water Board categories; no geographic clipping or reassignment is
applied to force one boundary system into the other.

```text
basin_plans/
  README.md
  INVENTORY.md                 Complete active-snapshot index
  REVIEW.md                    Readable regional navigation
  ORGANIZATION.md              Dataset names and catalog conventions
  sources.json                 Active snapshot and review generation pointers
  refresh.py                   Explicit online acquisition/update
  reference.py                 Offline reading and verification
  organize.py                  Offline review generation and verification
  names.py                     Search named waterways, watersheds, and tributary links
  relationships.py             Key-based relationship tables and membership indexes
  organized/<generation>/
    README.md                  Combined navigation and dataset list
    catalog.csv                All exported datasets, one row per source layer/table
    resources.csv              All portal items and original native archive links
    names.csv                  Published geographic names, roles, and source IDs
    waterway_links.csv          Separate parent-waterbody/tributary relationship table
    relationships/             Additional relationship tables and dataset provenance
    organization.json          Generated-file checksums and source manifest identity
    regions/<region>/
      README.md                Regional explanation and source links
      catalog.csv              Regional dataset names, fields, counts, and provenance
      resources.csv            Regional portal items and native archive links
      names.csv                Regional geographic name index
      waterway_links.csv       Regional parent/tributary associations
      relationships/           Regional key-based tables and complete record membership
      waterbodies/             Readable line, area, and published grouped copies
      designations/            Beneficial-use table copies
      references/              Hydrography reference table copies
    statewide/                 Separate statewide products with the same purpose groups
    hydrologic_boundaries/calwater_2_2_1/
      <numbered-level>/        Six levels, each with README, catalogs, and boundary data
    supporting/                Catalog and links to archived application resources
  snapshots/<generation>/
    manifest.json              Files, hashes, sources, counts, relationships
    INVENTORY.md               Generation-specific regional index
    metadata/                  Group membership and service-folder evidence
    documentation/             Portal HTML and directly linked PDFs
    regions/<region>/
      native/<item-id>.zip      Original published geodatabase
      metadata/items/          Item descriptions, terms, XML, resources
      services/<item-id>/
        service.json
        <layer-id>_<name>/
          metadata.json        Field types, domains, relationships, CRS
          features.geojson.gz  Complete spatial layer, when applicable
          rows.json.gz         Complete nonspatial table, when applicable
          raw/                 Original query responses, gzip-wrapped
          dataset.json         Per-dataset acquisition and integrity record
    statewide/                 Same service/layer organization
    supporting/                App, web map, and story configuration/resources
```

Item IDs distinguish independently published sources. Human-readable region and
layer directory names, source titles, and inventory links support manual review.
The same naming scheme is used on Windows and Linux.
Central Valley has a combined regional catalog and separate folders and catalogs
for its two plans. Review copies are independent files with the same bytes as
the archived exports; original native ZIPs, raw responses, and metadata remain
in the immutable snapshot and are linked from the catalogs.

## Read the data offline

Python 3.11 or newer is sufficient; the acquisition and reader programs use only
the standard library. Compressed GeoJSON can be decompressed with a gzip-capable
archive utility or read with Python's `gzip` module. The native ZIPs contain Esri
file geodatabases for GIS software with a compatible reader.

Large regional layers should be processed one response batch at a time:

```python
from data.basin_plans.reference import load_manifest, iter_records

manifest = load_manifest()
for dataset in manifest["datasets"]:
    print(dataset["category"], dataset["name"], dataset["record_count"])

bay_uses = next(
    entry for entry in manifest["datasets"]
    if entry["category"] == "regions/02_san_francisco_bay"
    and entry["name"] == "WB_BenUses"
)
for row in iter_records(bay_uses["key"]):
    print(row)
```

Spatial iteration returns GeoJSON features; table iteration returns attribute
dictionaries. Iteration verifies stored batch checksums and object IDs. Full
membership validation requires exhausting the iterator. No reader operation
contacts the network or silently downloads missing files.

Beneficial-use designations are relational data. Preserve the waterbody layers,
`WB_BenUses`/`BeneficialUses`, reachcode tables, and their metadata together.
Relationship keys and field capitalization differ between sources; inspect each
layer's `relationships` and `fields` rather than joining on names alone. Values
such as reachcodes remain strings when the source declares them as strings.

## Acquire or update the complete collection

From the repository root:

```powershell
python data/basin_plans/refresh.py
```

The refresh enumerates every page of the Basin Plan GIS Library group and the
dedicated `Basin_Plan` service folder. It includes the portal's Story Map item,
every listed regional service and native archive, and all layers and tables in
each discovered service. Nested operational web-map layers are followed to their
source services, including the CalWater boundary hierarchy. There is no spatial
filter or selected-region option.
The scope is the published BPMP collection, not all unrelated Water Boards GIS
services or the underlying private enterprise database.

Downloads use three workers by default; `--workers 1` through `--workers 4`
controls concurrency. Network settings, batch size, and regional categorization
are near the top of [refresh.py](refresh.py). Source discovery handles newly
listed items; an unfamiliar title is retained under `supporting/` for category
review rather than discarded.

Each spatial layer is requested with all attributes and WGS 84 coordinates, with
available Z coordinates and without coordinate simplification. GeoJSON cannot
represent measured M coordinates; original native geodatabases retain their
published dimensional information and internal structures. GeoJSON and a native
archive are separate source products and may have different vintages.

Each layer/table is downloaded by object-ID batches below its response limit.
Counts and complete ID lists are checked before and after acquisition; duplicate,
missing, unexpected, or truncated records reject the dataset. Raw response bytes
are preserved inside gzip files. Each receipt records the request, retrieval
time, raw checksum, stored checksum, and size. ZIP integrity is checked before
acceptance. HTTP/ArcGIS errors are reported as failures, not saved as valid data.

The acquisition writes `snapshots/.pending-<generation>/` first. Failed runs leave
their data and failure report there, and leave the previous `sources.json`
unchanged. After acquisition succeeds, the refresh also builds readable dataset
copies, regional READMEs and catalogs, and the CalWater hierarchy. Copy checksums
must match before publication. After both stages succeed, the generation directory
is renamed and the active archive and review pointers are replaced together in
`sources.json`. Older published snapshots and review generations remain available.
Removing older snapshots is a separate manual storage-management decision.

To resume an interrupted generation:

```powershell
python data/basin_plans/refresh.py --resume GENERATION_ID
```

Use the identifier printed by the failed run. Verified batches with the same
source URL and request parameters are reused. Counts and IDs are rechecked.
Reused bytes retain their earlier retrieval timestamps; a resumed generation can
span multiple acquisition times. A new refresh without `--resume` downloads a new
generation. If a forced termination leaves `.refresh.lock`, confirm that the
recorded process is no longer running before removing that lock.

Counts and ID sets cannot prove that attributes remained unchanged during a
multi-request download. The archive is a documented retrieval snapshot, not a
transactionally consistent database backup. Retrieval time, item-modification
time, and the source's actual data vintage are distinct.

## Verify locally

```powershell
python data/basin_plans/reference.py
python data/basin_plans/reference.py --records
python data/basin_plans/organize.py --verify
python -m unittest discover -s data/basin_plans -p 'test_*.py' -v
```

The first command verifies every indexed file's size and SHA-256 hash. The second
also checks every archived record against its object-ID evidence. Tests cover
batch completeness, truncation, errors, corruption, source-membership changes,
category assignment, path containment, and preservation of the active pointer
after failure. These checks establish download integrity; they do not establish
geometric validity, survey accuracy, or current regulatory applicability. No
automatic geometry repair changes the source data.
The organization verifier checks generated file hashes, complete dataset coverage,
byte-identical review copies, and local README/catalog links. The tests additionally
cover duplicate filenames, unfamiliar datasets, CalWater separation, stale-layer
removal from new generations, and organization failures before publication.

The optional native inventory uses `pyogrio` and its GDAL OpenFileGDB reader:

```powershell
python -m pip install pyogrio
python data/basin_plans/native_inventory.py
```

This reads all geodatabases directly inside their ZIP files and regenerates
`NATIVE_INVENTORY.md` and `native_inventory.json` outside the immutable snapshot.
Run it after a refresh when a new native-format review report is needed.

## Sources and interpretation

- [Basin Plan Portal](https://www.waterboards.ca.gov/resources/data_databases/basin_plan_portal.html)
- [Basin Plan GIS Library](https://gispublic.waterboards.ca.gov/portal/home/group.html?id=2de374bd11d9468d8e8919bdaf060016)
- [Statewide service](https://gispublic.waterboards.ca.gov/portalserver/rest/services/Basin_Plan/California_Basin_Plan_Beneficial_Uses/MapServer)
- [Current Basin Plan Beneficial Use Viewer](https://gispublic.waterboards.ca.gov/portal/home/item.html?id=7aa10136ab584ae0b963ace8797e5433)
- [ArcGIS layer query API](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/)

The portal's older Web AppBuilder viewer is marked deprecated in its item
metadata. The archive retains its published configuration and the replacement
viewer resources as source evidence; these files do not constitute an offline
copy of the interactive ArcGIS application or its external basemaps.

BPMP describes beneficial-use designations and mapped waterbody segments. It is
informational, subject to revision, and not a substitute for the applicable Basin
Plan. Published missing/incomplete-waterbody documentation is archived with the
collection. Beneficial-use designations do not establish current water quality,
drinking-water safety, recreation access, or live advisories.

This is a separate reference collection. Existing EBMUD datasets and MeshCore
command registrations are unchanged. Refresh is manual; no scheduled task or
service-startup download is installed.

The [statewide USGS current-water collection](../usgs_water/README.md) adds named
monitoring locations, current stage/discharge values, CalWater point membership,
and published station-to-reach links. It references the original Basin Plan keys
and archives without modifying them. Derived relationships remain separate from
published waterbody designations and tributary attributions.
