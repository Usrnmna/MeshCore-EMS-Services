# Supplemental station addresses and unresolved routing

Dataset and generated-report paths below identify local acquisition outputs.
They require the corresponding collection, generation, or validation run
described in [water-data setup](../../docs/WATER_DATA_SETUP.md). Packaged
documentation contains the guides; historical generation paths may differ
from later acquisitions.

The supplemental review investigates stations with latest readings but no usable
primary NLDI river address. The first review contains 54 stations. It supports
nine additional routing links and five static nonnetwork feature addresses.
The remaining cases retain contradictory, missing, or coastal source evidence.
The station review catalog (`LINK_REVIEW.md`) contains individual decisions and
all published address candidates.
The later [original-agency investigation](AGENCY_REVIEW_METHODS.md) examines
the 11 conflicting and 26 uncorroborated cases, adding 13 supported static
addresses while preserving the initial decisions as source-review history.
For the preserved current-reading snapshot, routing coverage increased from
632 to 641 of 686 stations. The nine additions contributed 987 station-to-reach
relationships and 230 station-to-CalWater-basin candidate relationships.
These are repeated station associations, not counts of new physical waterways
or distinct flooded basins. The validation results (`link_review_verification.json`)
identify the exact observation and routing generations.

## Sources and evidence strength

The review rechecks the exact agency-qualified identifier in USGS NLDI and queries
Geoconnex reference gages by exact `provider_id`. It also retrieves station records
from the Water Board's California Stream Gages layer and its SB19 linked-data
representation. Original responses, source metadata, object-ID enumeration and
retrieval receipts are retained. The [source citations](SOURCES.md) identify each
service.

The Water Board describes the catalog as originating in a fall 2020 snapshot.
Its station points were moved to NHD medium-resolution features for analysis;
the catalog defers to the originating agency where records disagree. Accordingly,
supplemental links are labeled as published secondary addresses. Agreement between
the Water Board and SB19 representations is a consistency check between related
products, not independent confirmation of present physical conditions.

The USGS `nhdflowline_nonnetwork` collection provides geometry and identifiers
for features outside the routable network. It supplies no downstream topology
for these addresses. Its `prev` and `next` links navigate collection records;
they are **not upstream or downstream relationships**.

## Promotion requirements

Supplemental routing requires all of the following:

1. The primary NLDI address is missing. An existing coastline address is retained,
   and an existing conflicting primary address is never overwritten.
2. The Water Board and SB19 records identify the exact USGS station, including
   agency/operator, provider, leading-zero station ID and published station URL.
   Multiple matching records remain ambiguous.
3. Both representations publish the same nonzero COMID and reachcode.
   A contradictory nonempty reference-gage COMID or reachcode blocks promotion.
4. That pair matches the pinned USGS network feature. Its flow direction is
   `With Digitized`, it is enabled, and it is not a coastline feature.
5. Spatial checks place the current USGS station within 250 m of the assigned
   segment and the Water Board's published snapped point within 10 m.
   These are conservative review tolerances, not hydraulic confidence estimates.

Distances check a previously published address. They never select a nearest
stream, resolve a missing identifier, or substitute a name match. A newly
available primary NLDI address is flagged for a primary-network refresh.

A consistent address verified against the USGS **nonnetwork** collection can
be saved as a static feature relationship. It is never passed to downstream
traversal. Missing geometry, contradictory reachcodes, shifted locations, source
absence and uncertain flow direction remain explicit.

## Relationship outputs and interpretation

| File | Contents |
| --- | --- |
| `station_link_review.csv` | One decision per investigated station, with exact IDs, reasons, spatial offsets, evidence class and source links. |
| `published_address_candidates.csv` | Every retrieved published address, including null keys and conflicting candidates, with checks against network/nonnetwork identifiers. |
| `supplemental_routing_links.csv` | Only addresses meeting the routing requirements. |
| `supported_nonnetwork_addresses.csv` | Supported static station-to-feature links without downstream-flow claims. |
| `nonnetwork_features.geojson.gz` | Original USGS nonnetwork features used to examine published candidates. |
| Routing `effective_station_reach_links.csv` | Primary station links plus the supported supplemental addresses used for that routing generation. |

The primary network archive is preserved. The routing manifest pins a separate
`link_review.json` generation, and the effective station table records supplemental
evidence. Reports display both the original primary link and the supplemental
decision; a source-version mismatch produces an explicit refresh requirement.

In the initial review, 11 stations have conflicting catalog addresses, three
retain coastline addresses, and 26 have no corroborated published address.
Five additional static addresses remain unroutable. These 45 cases must not be
treated as disconnected from all flood hazards. The reference-gage source did
not supply a new usable river address for them.

River routing still stops at published terminals and excludes coastlines.
Tidal paths, pipelines, diversions and controlled channels retain the limitations
described in [routing methods](ROUTING_METHODS.md). Supplemental identifiers do
not establish flow allocation, gate settings, backwater, flood extent or travel
time.

## Refresh and current-only retention

```text
python -m data.usgs_water.refresh --mode link-review
python -m data.usgs_water.refresh --mode agency-review
python -m data.usgs_water.refresh --mode routing --reuse-routing-sources
python -m data.usgs_water.validate_link_review --output data/usgs_water/link_review_verification.json
python -m data.usgs_water.validate_routing --output data/usgs_water/routing_verification.json
```

The first command queries current unsupported stations and retains previously
reviewed station IDs so accepted supplements do not disappear merely because a
station temporarily lacks a latest reading. A full `--mode all` refresh includes
link review and original-agency review before routing when a prior routing
archive exists. For an initial installation, first build routing, then run both
reviews and rebuild routing.

Reusing routing sources requires matching acquisition inputs and supplemental
seeds within the already verified closure scope. Otherwise run a full
`--mode routing` refresh. The refresh regenerates regional and CalWater tables.
Failed queries do not become evidence of source absence or publish partial results.

Review generations contain identifiers, geometry, interpretation metadata and
source evidence only. They contain **no water-level or discharge measurements**.
The observation collection still retains one latest reading per series and
replaces obsolete measurement generations. Source catalog period-of-record
metadata describes station availability; it is not a stored level history.
