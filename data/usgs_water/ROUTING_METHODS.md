# Statewide downstream, tributary and basin relationships

The routing collection connects California monitoring stations to potentially
affected waterways and basins through published hydrography and explicit spatial
analysis. It contains **no observation values or level history**. Current stage
and discharge remain in the independently refreshed current-value snapshot.

## Geographic coverage and acquisition

The USGS `wmadata:nhdflowline_network` WFS supplies NHDPlusV2 network attributes and
geometry. The initial longitude/latitude envelope is west −125°, south 32°,
east −113.5°, north 42.5°. It covers California and adjacent border context.
An explicit `EPSG:4326` CQL bounding-box CRS is required; the service's native
CRS is NAD83 and an unqualified bounding box does not select the same records.
The output geometry is requested in longitude/latitude WGS84.

All reaches intersecting any published CalWater hydrologic-region polygon, plus
all published California station-reach seeds, initiate downstream closure. The
download follows outgoing published node connections beyond the envelope where
required. It retains branches rather than stopping at a state boundary or an
arbitrary distance. Adjacent non-California drainage is retained as border context;
unrelated routes originating only in that context are not closure seeds.

WFS queries retain exact before/after feature-count evidence and COMID-sorted
pages. Duplicate/out-of-order IDs, changed counts, incomplete pages, or failed
queries prevent publication. Source responses are retained losslessly with
receipts. Downloads request the geometry and the explicitly listed network
attributes needed for relationships; they do not claim to mirror every NHDPlus
attribute or every finer-resolution local stream dataset.
Resumed builds can retain additional cached source responses from interrupted
acquisition attempts. Final graph membership and closure scope are defined by
the database's `reaches` and `routing_scope_seeds` tables.

Missing published station seeds are queried directly by COMID. Outgoing-node
queries resolve possible border exits and source endpoints. A source terminal
flag does not prove an ocean outlet, an open gate, or the absence of flooding.
An unresolved endpoint remains explicit even after its source query completes.

## Relationship tables

The verified `routing.json` pointer selects a generation containing
`routing.sqlite`, GIS-ready `waterways.geojson.gz`, named waterway and basin
catalogs, and compressed CSV relationship exports. SQLite tables provide the
same relationships without requiring the large CSV files to be loaded into memory.

| Table | Interpretation |
| --- | --- |
| `flow_connections` | Immediate reach-to-reach connections from equal, nonzero published `TONODE` and `FROMNODE` keys. Direction/enabled conflicts, source terminals and coastline connections remain separate statuses. A saved connection is not necessarily traversable. |
| `tributary_connections` | Incoming branches at published-node confluences with at least two traversable incoming reaches. Both names and unnamed reaches remain. These are reach-level confluence relationships; a branch can be a tributary, braid, diversion return or artificial path. |
| `reach_calwater_overlaps` | Derived line/polygon intersections for each of the six CalWater levels, including a separate boundary-touch classification. |
| `station_downstream_reaches` | All possible directed downstream branches from each verified station seed, with minimum graph-hop counts. The source reach is labeled separately because the station's position within that reach is unresolved. |
| `station_downstream_basins` | Basin review candidates reached by joining downstream reaches to their CalWater overlaps. Contains minimum hops, connected reach counts, positive-length overlap counts, and an explicit non-inundation interpretation. |
| `station_routing_coverage` | Every inventory station, including missing station links, source-absent reaches, reachcode conflicts, disabled/uncertain directions, unresolved endpoints, tidal reaches and divergences. |
| `reach_regions` | Derived positive-length reach overlap with CalWater HUs, followed by published Water Board and plan attribution. Regional memberships may overlap. |
| `routing_scope_seeds` | CalWater-intersecting reaches and published California station seeds used to define the downstream-closure obligation. |
| `source_checks` | Outgoing nodes whose successor queries completed, including queries returning no successor. |
| `relationships/effective_station_reach_links.csv` | Original primary station addresses with separately labeled, supported supplemental addresses. The manifest pins the supplemental review generation. This CSV is provenance for the station seeds rather than an additional SQLite table. |

The original Basin Plan parent/tributary tables and the earlier flood pilot's
directed tables remain intact. The new statewide tables are a separate, versioned
extension. `network/` still holds station-to-reach identifiers and the pinned pilot
tables; **`routing/` holds the statewide directed and tributary network**.
Archived generations can contain superseded routing rules. Select current results
through `routing.json`; do not combine derived tables across generation folders.

The [supplemental station review](LINK_REVIEW_METHODS.md) can supply a missing
primary address when exact station identities, published COMID/reachcode pairs
and spatial consistency checks agree. It retains source conflicts, missing
addresses and static nonnetwork links separately. Only supported routing
supplements enter traversal. The original primary NLDI table is never rewritten.

## Direction, branches and cycles

Traversal uses connections whose source and target both have `enabled=1` and
`flowdir='With Digitized'`. Unknown or conflicting source direction is not inferred
from coordinate order, names, elevation samples or proximity. Zero or missing
node IDs never join unrelated waterways.

Traversal stops at `terminalfl=1` even when the terminal's node also connects to
another feature. `Coastline` features and connections into or out of them are
retained for source review but excluded from river-path traversal. This prevents
shoreline geometry from linking a river's reading to unrelated coastal basins.
A coastline station seed remains explicitly unsupported for river routing.

All eligible branches remain possible paths. Breadth-first traversal records
minimum hop counts, terminates safely through cycles and deduplicates reconverging
branches. Hop counts are graph structure, not travel time or distance. Divergence
and tidal attributes remain visible; the graph does not model present gate/pump
settings, tidal reversal, reservoir operation, backwater or changing discharge
distribution. Station COMID links with a conflicting published reachcode are
withheld for review.

The same-station-reach row represents the whole published segment. It does not
assert that every point on that segment is downstream of the gauge. No reading is
transferred unchanged to a receiving reach as an estimated local water level.

## CalWater and regional organization

HR, HU, HA, HSA, SPW and PW polygons remain separate. Source dataset keys and
object IDs identify polygons even where names or hierarchy codes repeat. Geometry
repairs apply only to derived analysis; original files remain unchanged. Repairs
and null geometries are recorded in `geometry_diagnostics.json`.

Line/polygon intersections use California Albers, `EPSG:3310`. Full containment
uses the line's projected length; partial overlaps use the actual intersection.
Zero-length point contacts remain distinct from positive-length overlap. Basin
fractions and flooded areas are not calculated from these lines. Hydrologic-region
names are resolved through unique published HU `hrc`/`hrname` pairs when available.

All nine Water Board regions have readable waterway tables, candidate-basin tables,
README files and catalogs. Attribution follows the published CalWater HU `rb`
and `hbpaname` fields after spatial intersection; it is not a new jurisdiction
boundary survey. A basin can span regional review categories. Nested basin levels
must not be summed as distinct affected areas.

## Current readings and offline queries

Refresh the current observations and inspect a station using the existing commands:

```text
python -m data.usgs_water.refresh --mode observations
python -m data.usgs_water.report --station USGS-11464000
```

The report recomputes observation freshness and adds statewide downstream context.
It displays at most 100 rows from each large routing table and reports omitted-row
counts and the complete database path. Inventory or station-network version
mismatches, including a changed supplemental review, produce an explicit
refresh-required result rather than a silent join.

For complete downstream results, resolve `routing.json`, open that generation's
database read-only, and use parameterized queries such as:

```sql
SELECT d.station_id, d.minimum_hops, r.reach_id, r.name, r.reachcode
FROM station_downstream_reaches AS d
JOIN reaches AS r USING (reach_id)
WHERE d.station_id = ?
ORDER BY d.minimum_hops, r.reach_id;

SELECT d.*, b.level, b.name, b.code
FROM station_downstream_basins AS d
JOIN basins AS b USING (basin_id)
WHERE d.station_id = ?;
```

Bind an agency-qualified ID, such as `USGS-11464000`, to `?`. Join current readings
using `monitoring_location_id = station_id`; series IDs, units, timestamps and
quality flags continue to describe the measurement at the source station.

To inspect incoming branches at a confluence, bind the receiving `reach_id`:

```sql
SELECT upstream_reach_id, upstream_name, downstream_reach_id,
       downstream_name, node_id, relationship, evidence_class
FROM tributary_connections
WHERE downstream_reach_id = ?;
```

For upstream tracing through intervening single-channel segments, traverse
`flow_connections` in reverse using only `status='published_node_connection'`.
Use a visited-reach set to terminate cycles. Reverse connectivity identifies
possible contributing paths; it does not establish a contribution amount or
reverse the actual flow direction.

## Refresh, preservation and validation

```text
python -m data.usgs_water.refresh --mode routing
python -m data.usgs_water.validate_routing --output data/usgs_water/routing_verification.json
```

For an offline rebuild after a routing-rule change, use
`python -m data.usgs_water.refresh --mode routing --reuse-routing-sources`.
This requires matching, checksum-verified inventory, station-network, CalWater
and acquisition settings. Original responses, acquired reach geometry, scope
checks and CalWater intersections are copied into a new generation; downstream,
tributary, station, regional and catalog tables are regenerated. Superseded
derived paths are not reused. A normal routing refresh retrieves new source data.
Supplemental seeds must already belong to the verified closure scope for source
reuse; a new seed outside that scope requires a full routing refresh.

`--mode all` also reviews unsupported station addresses before rebuilding routing
when a prior routing archive exists. Routing does not
need rebuilding for each new reading. Refresh it when the station inventory,
published network, CalWater sources or derivation code changes. Failed builds
retain the last published pointer. A pending build can be resumed with
`--mode routing --resume PATH_TO_PENDING_ROUTING_DIRECTORY`; cached source bytes
are verified before reuse and disposable derived database tables are rebuilt.

Validation checks all published node joins, direction/terminal/coastline gates, every station path's
closure and minimum hops, exact station-to-basin aggregation, regional coverage,
current-observation compatibility, and sampled geometric intersection lengths.
It also checks that the Russian River pilot's previously verified reachable
waterways remain present. These checks establish software and source consistency,
not hydraulic validity or flood-prediction skill.

**Potentially affected** means a connected waterway intersects the named basin.
It does not establish overflow, inundation extent, flood depth, arrival time or
impact on every location in that basin. Official threshold context, compatible
gauge datums and validated inundation/operational models are needed for those
conclusions. Missing data or an unresolved route is not evidence of no flood risk.
