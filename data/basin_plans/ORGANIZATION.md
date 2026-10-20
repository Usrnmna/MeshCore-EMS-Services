# Regional dataset organization

The [regional review index](REVIEW.md) is the entry point for manual inspection.
Every Regional Water Board has a README, a dataset `catalog.csv`, and a source
`resources.csv`. Central Valley also has separate directories and catalogs for
the Sacramento and San Joaquin River Basins and the Tulare Lake Basin.

The hierarchy is **Regional Water Board → published Basin Plan → dataset purpose**.
Regions with one published extract place dataset-purpose folders directly below
the region. Individual basin, river, lake, waterbody, and subtype names remain in
their original attributes. They are not reassigned from county names or clipped
to inferred geographic boundaries.

## Readable dataset names

Each regional plan uses the following names when the source publishes these layers.
Files remain gzip-compressed and byte-identical to their archived exports.

| Published name | Readable file | Meaning |
| --- | --- | --- |
| `BasinPlanLines` | `waterbodies/line_segments.geojson.gz` | Individual waterbody line features |
| `BasinPlanPolys` | `waterbodies/areas.geojson.gz` | Individual waterbody polygon features |
| `BPLinesDiss` | `waterbodies/grouped_lines.geojson.gz` | Published dissolved line features |
| `BPPolysDiss` | `waterbodies/grouped_areas.geojson.gz` | Published dissolved polygon features |
| `WB_BenUses` | `designations/beneficial_uses.json.gz` | Beneficial-use designation records |
| `ReachcodeTable` | `references/hydrography_references.json.gz` | Waterbody-to-hydrography references |

Grouped features are the source's dissolved products. Original exports undergo no
geometry processing, deduplication, field renaming, string conversion, or record merging.
Separate [relationship tables](RELATIONSHIPS.md) describe scoped key matches and
published parent/tributary associations without changing those exports.
Statewide products remain under `statewide/`, with separate beneficial-use line
and area filenames and their own designation and reference tables. Their records
overlap regional products and must not be summed as unique waterbodies.

## Separate CalWater hierarchy

CalWater 2.2.1 is organized under `hydrologic_boundaries/calwater_2_2_1/`.
Each numbered level has its own README, catalogs, and `boundaries.geojson.gz`.

| Folder | Published classification |
| --- | --- |
| `01_hydrologic_regions/` | Hydrologic regions |
| `02_hydrologic_units/` | Hydrologic units |
| `03_hydrologic_areas/` | Hydrologic areas |
| `04_hydrologic_subareas/` | Hydrologic subareas |
| `05_super_planning_watersheds/` | Super planning watersheds (SPW) |
| `06_planning_watersheds/` | Planning watersheds (PW) |

These hydrologic categories are distinct from the nine Regional Water Board
jurisdictions. The broad-to-fine hierarchy is retained without forcing it into
regional folders. Source codes and names remain available in the exported fields.

## Catalogs and manual review

`catalog.csv` contains one row per exported source layer or table within its
scope. The combined catalog lists each dataset once; parent and child catalogs
repeat rows for navigation, without creating additional data copies. CSV files
use UTF-8 with a byte-order mark for spreadsheet compatibility.

Catalog columns include readable and original names, category, description,
geometry and record counts, relative data and metadata paths, source service URL,
source title, retrieval timestamps, object-ID field, available review fields,
declared relationship keys, SHA-256, size, and review notes. All local paths are
relative to the directory containing the catalog. Metadata links preserve the
complete source definitions, domains, aliases, and relationship descriptions.

Available review fields are selected from the actual metadata, including
waterbody names, types and subtypes, plan names, beneficial-use codes, reference
keys, and CalWater hierarchy codes and names where present. A missing field is
not synthesized. A declared relationship key absent from the exported schema is
flagged in `review_notes`; for example, some statewide relationships reference
`WBF_ID` without exporting that field. IDs are scoped by source service and plan,
not treated as globally unique. Retrieval time does not establish source vintage.

`resources.csv` lists published portal items, item metadata, archived item-file
directories, and original geodatabase ZIPs where present. Native ZIPs, raw query
responses, documentation, and application resources remain in the source archive;
the review directory links to them instead of duplicating or transforming them.
Supporting applications have a separate resource category and are not offline
copies of the hosted interactive applications.

Manual annotations should be stored outside `organized/` and `snapshots/`, with
`dataset_key` and `snapshot_id` identifying the reviewed source. Editing review
copies does not change the original archive, but causes verification to fail.

## Find streams, creeks, rivers, and watersheds by name

Every review category has a `names.csv` index. The combined index covers all
published geographic name fields selected in [names.py](names.py): waterbody names,
GNIS names, parent-waterbody names, and the available CalWater hierarchy names.
Original spelling is retained. Name search ignores case and repeated whitespace;
it does not invent aliases, fuzzy matches, or names for unnamed features.

```powershell
python data/basin_plans/names.py "San Pablo Creek" --region 2
python data/basin_plans/names.py "Russian River" --region "North Coast"
python data/basin_plans/names.py "Lower Dunn Creek" --category calwater
python data/basin_plans/names.py "San Pablo Creek" --exact --name-field wb_name
```

Each match reports the exact name, source name field and role, category, plan/type
context, source dataset, matching record count, up to five example object IDs,
and paths to data and metadata. `--region` selects regional extracts, while
`--category statewide` selects statewide representations. `--limit 0` displays
all name matches; the default displays 20 and explicitly reports truncation.

The same name can appear in several regions, source representations, or fields.
Each remains a separate index entry. A `parent_wb` match identifies a parent
relationship and does not assert that a tributary feature itself has that name.
Use `--name-field wb_name` or `--name-field gnis_name` to restrict the match role.
Source type/subtype fields are retained; classifying every feature as a stream,
creek, or river from name spelling alone is not attempted.

To export every matching original feature or table row with its dataset and
object ID, use `--records`. Output is JSON Lines, one wrapper per source record;
spatial wrappers contain the original GeoJSON feature and its geometry.

```powershell
python data/basin_plans/names.py "San Pablo Creek" --region 2 --exact --name-field wb_name --records > san_pablo_records.jsonl
```

`--records` exports all matches and does not apply the display limit. A record
matching more than one selected name field is emitted once within its dataset.
Separate datasets remain separate even when they represent the same waterbody.
Selected source batches are verified while streaming, including complete ID
membership when the export is exhausted. Missing geometry remains null.

Blank names and placeholder-only records are counted in `catalog.csv` and
`name_coverage.json`. Literal placeholders such as `undefined` remain searchable
but are flagged. The hydrologic-region layer has codes without a geographic name
field; names available in other CalWater levels remain indexed in their own fields.

## Find tributary and parent relationships

The separate `waterway_links.csv` table is maintained in the combined review and
every region/plan. It preserves `parent_wb`, `trib_method`, `trib_exclusion`,
`tribcomm_flag`, and `wbid_t` where published, with complete source provenance.

```powershell
python data/basin_plans/names.py "Petaluma River" --region 2 --links --direction children
python data/basin_plans/names.py "Small Creek" --links --direction parents
python data/basin_plans/names.py "Petaluma River" --region 2 --links --direction children --records > petaluma_associations.jsonl
```

`children` finds source features assigned to the named parent; `parents` finds
parent associations for a named child. `both` is the default. Unnamed child
features remain accessible through the named parent and their object IDs.
Candidate parent records use exact normalized published names within the same
service, category, and compatible plan context. Multiple candidates and unresolved
names remain explicit. These are published associations, not a verified complete
network of immediate downstream connections. See the [relationship guide](RELATIONSHIPS.md).

## Refresh and offline rebuilding

Normal acquisition automatically regenerates the organization:

```powershell
python data/basin_plans/refresh.py
```

To build a new review generation from the current local snapshot without network
access, or to check the selected review generation:

```powershell
python data/basin_plans/organize.py
python data/basin_plans/organize.py --verify
```

Both programs accept `--directory PATH` for another archive root. Naming maps and
CalWater levels are maintained near the top of [organize.py](organize.py).
Newly discovered layers with unfamiliar names are retained under `unclassified/`
within their source category and flagged for review. Conflicting readable names
receive a deterministic suffix derived from the source dataset key, preventing
overwriting on case-insensitive filesystems. Original names and keys remain in
the catalog. An empty category retains its README and catalog header and is
explicitly described as empty.

Each build writes a new `organized/<snapshot-id>_<generation-id>/` directory.
Independent copies avoid hard links or symbolic links that could allow a manual
edit to change original source bytes. This uses additional disk space equal to
the compressed exported datasets, name/relationship tables, compressed membership
indexes, catalogs, and documentation. Name and relationship indexes stream verified
source batches and retain every object ID in their source membership indexes.

Refresh stages acquisition and organization before changing the active pointer.
`sources.json` selects both generations in one atomic replacement and records
the checksums of their manifests. Failed acquisition or organization leaves the
previous pointer intact. Incomplete work remains in `.pending-*` directories;
an organization-only retry creates a fresh generation. Older successful review
generations are retained, including any manual edits, and are never merged into
new output. A newly removed source layer therefore cannot remain as a stale file
in the active review generation.

`REVIEW.md` and `INVENTORY.md` are convenience indexes updated after selection.
If an interruption occurs after pointer publication, `sources.json` remains the
authoritative selector; a new offline organization run repairs the review index.
Removing older snapshot or review generations is a separate storage-management
decision. Review links depend on retaining their corresponding source snapshot.

The organizer and refresh share `.refresh.lock` to prevent concurrent publication.
If forced termination leaves the lock, confirm that its recorded process has
stopped before removing it. Verification checks generated-file hashes, exact
dataset coverage, original/copy equality, and local catalog and README targets.
The source archive's full integrity check remains:

```powershell
python data/basin_plans/reference.py
```
