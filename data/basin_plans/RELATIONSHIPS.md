# Basin Plan relationship tables

The separate [flood-impact reference pilot](../flood_impacts/README.md) adds
USGS-directed reach connections, NOAA gauge links and stage scenarios, and derived
CalWater intersections. Its [methodology](../flood_impacts/METHODS.md) distinguishes
published tributary associations from hydraulic connectivity. All tables below
remain intact and independently refreshable.

The [regional review index](REVIEW.md) links the combined collection and each
region/plan. Relationship tables are regenerated with every refresh and offline
organization build. They supplement byte-identical source exports; they do not
change source attributes, geometry, native ZIPs, or raw response evidence.

## Available tables

| Table within a review category | Relationship and evidence |
| --- | --- |
| `waterway_links.csv` | Published parent-waterbody/tributary associations, retaining methods, exclusions, comment flags, and `Main`/`Trib` labels |
| `relationships/beneficial_uses.csv` | Waterbody key groups to designation rows through published `wbf_id` fields |
| `relationships/hydrography_reachcodes.csv` | Waterbody key groups to hydrography records through `wb_refkey`/`WBREFKEY` |
| `relationships/segment_groups.csv` | Individual line/area records to the corresponding published grouped layer through the composite `wbf_id` and `wb_refkey` |
| `relationships/calwater_hierarchy.csv` | Immediate hydrologic parents and direct SPW/PW-to-hydrologic-unit relationships through documented codes |
| `relationships/dataset_provenance.csv` | Every dataset to its category, region, published plan/source title, source URL, snapshot, and retrieval timestamps |

The tributary table remains separate from all five additional tables. Parent
and child category catalogs repeat relevant relationship rows for navigation.
They do not create additional source records. Table paths are relative to the
directory containing the CSV, including links to complete membership indexes.

## Tributary and parent associations

`waterway_links.csv` groups source records by their exact published waterbody and
GNIS names, parent name, plan/type context, tributary method, exclusions, comment
flag, and `wbid_t` label. It retains unnamed child features and up to five example
source object IDs. `names.py --links --records` exports all child records in the
selected groups, preserving the complete source attributes and available geometry.

Candidate parents are identified by published waterbody names, falling back to
GNIS names only when no waterbody-name candidates exist. Comparisons ignore case
and repeated whitespace, remain within the same service/category and compatible
plan context, and retain every candidate. Candidate groups may represent multiple
segments or separate grouped/ungrouped products. `one_candidate_group` does not
assert a unique physical waterway; `multiple_candidate_groups` and
`unresolved_parent_name` remain explicit for manual review.

The source assignment is retained even when the parent is absent from exported
names. Tributary methods and exclusions are evidence, not instructions to infer
additional connections. A parent relationship may describe plan attribution and
does not establish the immediately downstream feature. Geometry proximity, line
endpoint snapping, direction of digitization, and name similarity are not used
to manufacture a complete river-flow network.

## Key-based tables and full membership

Beneficial-use, reachcode, and segment/grouped relationships are scoped to one
published service and category. String keys retain leading zeros and type;
numeric `7` and numeric `7.0` compare as the same numeric ID, while string `"7"`
remains distinct. `WBREFKEY` is recognized as a published spelling of the
reference-key field. Original field names and values remain in source metadata
and compressed membership files.
Import identifier and reachcode columns as text when using spreadsheet applications
so their automatic number formatting does not hide leading zeros.

Each CSV row describes a key group with source and target datasets, exact field
names, JSON-encoded key values, record counts, example IDs/names, evidence, and
status. Multiple source segments can share a waterbody key, and a waterbody can
have multiple designations or reachcodes. The tables avoid multiplying every
source segment by every matching target row. These legitimate many-to-many
relationships remain traversable through complete membership indexes.

Every source dataset has a gzip-compressed CSV under its category's
`relationships/record_keys/` directory. Its path is linked by relationship rows.
It retains every object ID, published relationship keys, available waterbody/GNIS
names, plan name, beneficial-use code/name, and reachcode. Samples in relationship
tables are limited to five IDs; membership indexes are not sampled. Original
exports provide the full attributes and geometry for those dataset-scoped IDs.

Example: read every target designation record belonging to a selected relationship:

```python
import csv
import json
from pathlib import Path
from data.basin_plans.relationships import read_members

root = Path("data/basin_plans")
pointer = json.loads((root / "sources.json").read_text(encoding="utf-8"))
review = root / pointer["organization_path"]
table = review / "regions/02_san_francisco_bay/relationships/beneficial_uses.csv"
with table.open(encoding="utf-8-sig", newline="") as stream:
    relation = next(row for row in csv.DictReader(stream)
                    if row["status"] == "matched_key_group")
for member in read_members(table.parent / relation["target_members_path"],
                           relation["target_fields"], relation["target_key_json"]):
    print(member["object_id_json"], member["bu_code"], member["bu_name"])
```

`read_members` streams the specified membership index. Run `organize.py --verify`
before using these files when integrity validation is required. The original
record reader performs source checksum and ID validation during iteration.

## Missing and ambiguous relationships

| Status | Interpretation |
| --- | --- |
| `matched_key_group` | Exact source and target key values exist; multiplicity may be expected |
| `missing_source_fields`, `missing_target_fields`, `missing_both_fields` | Required fields are absent from an exported schema; no join was fabricated |
| `missing_key_no_join` | At least one component is null or blank; matching nulls do not establish a relationship |
| `unmatched_source_key`, `unmatched_target_key` | A nonempty key exists on only one side |
| `ambiguous_target_records` | A segment/grouped key matches more than one grouped record |
| `verified_code_parent` | A decoded CalWater parent code matches exactly one published parent record |
| `unmatched_parent_code`, `ambiguous_parent_code`, `invalid_or_missing_code` | CalWater parent membership cannot be resolved uniquely |

Some statewide designation metadata names `WBF_ID` without exporting it. Those
relationships remain schema-level missing-key rows; matching on waterbody names
or object IDs is not substituted. A missing-key row is diagnostic, not an edge.
Grouped-layer links through shared fields are generated cross-references, even
where the service does not declare an ArcGIS relationship object. Unfamiliar
future layer names remain in the full dataset/name catalogs; specialized join
mappings require review before additional relationships are asserted.

## CalWater code verification

CalWater composite codes concatenate region, board, unit, area, subarea, and
planning-watershed components. HA and HSA occupy one digit each; SPW and PW occupy
two each. The implementation derives parents by removing those documented suffixes
and then checks the result against actual archived parent records. This preserves
two-digit hydrologic regions such as 10. Unit-to-region links use the published
`hrc` field directly. The source data dictionary is reproduced in the
[NOAA CalWater documentation, PDF page 84](https://repository.library.noaa.gov/view/noaa/3943/noaa_3943_DS1.pdf#page=84).

Immediate parents are generated across all six levels. SPW and PW additionally
link directly to hydrologic units. Missing and duplicate parent codes are retained
as exceptions. These are hierarchy-code relationships, not geometric containment
tests or flow-direction assertions. CalWater hydrologic regions remain separate
from Regional Water Board jurisdictions.

## Derived spatial relationships

Waterway-to-CalWater polygon overlaps are not generated by the current organizer.
Such tables require an explicit geometry analysis and should identify their method,
coordinate system, intersection measure, boundary-touch handling, source geometry
validity, and source snapshot. Null geometries must remain exceptions. Spatial
overlap would describe intersection, not tributary direction or legal jurisdiction.

The separate [USGS relationship collection](../usgs_water/METHODS.md) implements
statewide station-point membership in all six CalWater categories and published
NLDI station-to-reach links. Its Basin Plan candidates use exact reachcodes and
retain source dataset and waterbody reference keys. These derived tables do not
replace the organizer's beneficial-use, segment-group, hierarchy, provenance or
parent/tributary tables. The existing flood collection's directed
`flow_connections.csv` remains a separate preserved relationship table.

The [statewide downstream extension](../usgs_water/ROUTING_METHODS.md) adds
immediate node connections, confluence branches, station-to-downstream-reach
relationships and derived reach-to-CalWater overlaps. All six CalWater levels
remain separate. Its potentially affected basin candidates are not flooded-area
polygons and do not replace published beneficial-use or hierarchy relationships.
