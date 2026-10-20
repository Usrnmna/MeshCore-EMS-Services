# Current observations and waterway relationships

## Acquisition and preservation

The monitoring-location query uses published `state_code=06` without an active-site,
agency, site-type, or watershed restriction. Every returned page is retained.
USGS partner identifiers such as `CA001-...` remain distinct from `USGS-...`.

The time-series metadata collection has no state filter. The downloader enumerates
parameter 00060 and 00065 metadata nationally, then selects exact California
monitoring-location IDs. Original national metadata pages are retained as evidence;
the normalized series table contains the California subset. Daily and annual
metadata are distinguishable from `Points` / `Instantaneous` series. Metadata does
not constitute a historical level download.

The latest-continuous collection is queried statewide for each parameter. All
returned sensors are preserved, including alternatives and stale last-known values.
Normalized values remain source strings; units, approval status, qualifiers,
statistic IDs, source feature IDs, and modification timestamps remain attached.
No missing value is replaced by zero. Negative stages and zero flow are valid
numeric possibilities. Nonfinite and sentinel values remain unusable.

OGC pagination follows exact `next` links. Duplicate source IDs, pagination loops,
unexpected collections, inconsistent page counts, and incomplete advertised totals
fail the build. Results reflect the source during retrieval, not a transactional
snapshot of a continuously changing API. Raw gzip files losslessly preserve the
HTTP response body; receipts contain the URL, retrieval time, headers and hashes.

## Tables and join meanings

| Table | Meaning and limitations |
| --- | --- |
| `station_time_series.csv` | Exact agency-qualified station to published series ID; primary, computation, statistic, sensor, parent-series and availability metadata remain distinct. |
| `station_region_plan.csv` | Derived station-point intersection with CalWater HU polygons, followed by published `rb` and `hbpaname` attribution. Multiple and unresolved matches remain explicit. This is regional review attribution, not a new jurisdiction survey. |
| `station_calwater_membership.csv` | Derived point membership separately for HR, HU, HA, HSA, SPW and PW. A containing polygon is not the complete contributing drainage area. |
| `station_identifiers.csv` | Published agency and station-number identities, plus previously verified NWPS aliases. Unverified NWPS and CDEC aliases remain unresolved; no name-only join. |
| `station_reach_links.csv` in the **network** generation | Published NLDI identifier, COMID, reachcode, measure and mainstem URI for every California station with stage/discharge metadata. Other inventory locations have an explicit not-queried status. A 404 is source absence; transport errors fail publication. |
| `station_basin_plan_candidates.csv` | Exact reachcode candidates across all statewide and regional Basin Plan reach tables. Segment extent, network vintage and many-to-many waterbody relationships require review. |
| `station_link_coverage.csv` | Every inventory station remains represented, including missing NLDI links and missing Basin Plan candidates. |
| `station_contributing_areas.csv` | Published drainage/contributing-area attributes and USGS HUC. No upstream polygon is fabricated; HUC is not a CalWater code. |
| `station_measurement_coverage.csv` | Latest reading counts for both parameters for every inventory station. Zero means no value returned, not absence of flood risk. |
| `measurement_series_links.csv` | Current measurement series to metadata, including explicit missing metadata. |
| `measurement_lineage.csv` | Verified NWPS/USGS station aliases. A relayed observation is not independent evidence. Forecasts are separate from observations. |
| `station_current_thresholds.csv` | Source thresholds effective at evaluation time. Named flood references remain separate from operating limits; ambiguous periods require review. The full source metadata remains archived. |
| `dataset_provenance.csv` | Dataset, statewide scope, source URL, retrieval timestamp and receipt path. Station-level region and plan relationships provide finer attribution. |
| `flow_connections.csv` in the **network** generation | Preserved original Russian River pilot topology. The separate **routing** generation extends directed and tributary tables statewide; see [routing methods](ROUTING_METHODS.md). |

The inventory generation's `relationships/flood_reference/` directory preserves
all previously implemented flood-reference relationship tables. Its initial
`station_reach_links.csv` contains the pinned pilot links; use the independently
refreshed **network generation** for statewide links.
The **routing generation** adds statewide immediate connections, confluences,
downstream paths and potential basin candidates while preserving those earlier
tables. Current values join by station ID and remain outside the routing archive.
The separate [supplemental link review](LINK_REVIEW_METHODS.md) records supported
secondary addresses and all unresolved candidates. Routing uses its verified
`effective_station_reach_links.csv` overlay; the primary network table and its
Basin Plan reachcode candidates retain their original scope. Supplemental basin
connections are explicitly derived through routing and CalWater overlaps.
The [local operating-agency review](LOCAL_REVIEW_METHODS.md) retains exact
station-to-facility identities, published aliases and diversion/return roles
in `station_local_links.csv`, separately from hydrography routing. All rows
have `routing_supported=False`; unresolved addresses and source failures
remain in `station_local_review.csv`.

The [original-agency review](AGENCY_REVIEW_METHODS.md) adds a separate
`supported_static_station_features.csv` table. Those off-network feature
addresses are not routing seeds. Station reports join the newer decisions by
exact agency-qualified ID and retain earlier contradictory source candidates.

`basin_relationship_references.json` identifies the original Basin Plan relationship
tables and hashes. Those include beneficial-use keys, reachcodes, grouped segments,
verified CalWater hierarchy codes, dataset provenance, and published waterbody
parent/tributary attributions. NLDI reach candidates connect to those records via
the source dataset key and waterbody reference key. Parent attributions remain
distinct from immediate directed hydraulic connections.

## Geometry and regional organization

Station geometry is the source's returned longitude/latitude point geometry.
All six CalWater levels are tested independently, retaining source dataset keys
and object IDs rather than treating codes as universally unique. Prepared polygon
intersections include boundary touches and retain all matches. Invalid polygons
are repaired only in derived memory; the diagnostic file identifies such repairs.
Original geometries remain unchanged in the pinned Basin Plan snapshot.

North Coast, San Francisco Bay, Central Coast, Los Angeles, Central Valley,
Lahontan, Colorado River, Santa Ana and San Diego each receive review folders.
Unassigned stations remain in an additional folder. Regional totals can overlap.
CalWater's ten hydrologic regions are not equated to the nine Water Boards. The
published HU plan attribution preserves distinctions such as the Central Valley's
Sacramento/San Joaquin and Tulare areas.

## Russian River integration validation

The pilot checks USGS-11464000 (Healdsburg / HEAC1) and USGS-11467002
(Guerneville / GUEC1) against their published series metadata, NLDI reach identifiers,
CalWater memberships, and existing flood-reference relationships. Guerneville's
stage station is not assigned another station's discharge when none is returned.

The existing downstream basin and inundation scenario tables remain usable as
reference evidence. Current USGS stage is not automatically converted to a
CatFIM scenario: matching station identity and similar numbers do not establish
vertical-datum equivalence. Published stage datum/zero, applicable scenario,
freshness and hydraulic assumptions must all be verified for such use.

No level history is retained for hindcasting, trend calculation, forecast-error
training or independent flood-event validation. Validation results establish
source and relationship consistency only.
