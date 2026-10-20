# Source citations and retrieval evidence

## USGS monitoring locations, series and current observations

**U.S. Geological Survey.** *Water Data for the Nation: California; modern Water
Data OGC APIs.* Accessed 2026-10-20 UTC. Individual receipts record precise
retrieval times rather than treating this documentation date as a data timestamp.

- [California Water Data for the Nation](https://waterdata.usgs.gov/state/california/)
- [OGC API documentation](https://api.waterdata.usgs.gov/docs/ogcapi/)
- [Monitoring-location collection](https://api.waterdata.usgs.gov/ogcapi/v1/collections/monitoring-locations?f=json)
- [Time-series metadata collection](https://api.waterdata.usgs.gov/ogcapi/v1/collections/time-series-metadata?f=json)
- [Latest continuous observations](https://api.waterdata.usgs.gov/ogcapi/v1/collections/latest-continuous?f=json)
- [Published parameter-code collection](https://api.waterdata.usgs.gov/ogcapi/v1/collections/parameter-codes?f=json)
- [Efficient query guidance](https://api.waterdata.usgs.gov/docs/ogcapi/efficiency/)
- [API keys and response rate-limit headers](https://api.waterdata.usgs.gov/docs/ogcapi/keys/)
- [Provisional-data statement](https://waterdata.usgs.gov/provisional-data-statement/)

The implementation uses the live schema's `time_series_id`, `approval_status`,
`parameter_code`, and `monitoring_location_id` names. Archived queryables and
parameter records provide field/code evidence. Parameter 00065 is gage height in
feet; 00060 is discharge in cubic feet per second. Statistic and computation
metadata determine a series' temporal meaning; a parameter label alone does not.

The USGS browser page is a discovery interface. Machine-readable APIs supply the
offline records; page scraping and browser-map extraction are not required.
No USGS historical continuous series or STAC rating files are retained by this
current-only collection. Applicable threshold and station/series metadata provide
interpretation context without maintaining historical levels.

## Published hydrography identifiers

**U.S. Geological Survey.** *Network Linked Data Index (NLDI), NWIS Surface Water
Sites linked-data source.* Accessed 2026-10-20 UTC.

- [NLDI API and source definitions](https://api.water.usgs.gov/nldi/docs)
- [NLDI linked-data sources](https://api.water.usgs.gov/nldi/linked-data)
- [Healdsburg station link](https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-11464000?f=json)
- [Guerneville station link](https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-11467002?f=json)

Every California stage/discharge station is queried by exact published identifier,
including inactive stations. Four workers perform independent requests with bounded
retries. Original 404 responses document missing links. Source names and network
identifiers are preserved; source-assigned connectivity is not a new hydraulic
validation. No nearest-name or nearest-coordinate assignment replaces a missing
published station link.

## Basin Plans, CalWater and existing flood references

**California State Water Resources Control Board and Regional Water Quality
Control Boards.** *Basin Plan Portal, regional and statewide hydrography-reference
tables, CalWater Watersheds 2.2.1.*

- [Basin Plan Portal](https://www.waterboards.ca.gov/resources/data_databases/basin_plan_portal.html)
- [CalWater source service](https://gispublic.waterboards.ca.gov/portalserver/rest/services/Hosted/CalWater/FeatureServer)
- [Existing complete local source inventory](../basin_plans/INVENTORY.md)
- [Published relationship keys and hierarchy evidence](../basin_plans/RELATIONSHIPS.md)

**NOAA National Weather Service and U.S. Geological Survey.** *Existing Russian
River flood-reference collection: NWPS gauges, NLDI/NHDPlus reach topology, and
CatFIM scenarios.* The USGS integration pins the existing generation rather than
altering its source data. Its [source citations](../flood_impacts/SOURCES.md)
describe the original agency endpoints, versions and interpretation limits.

EBMUD data remains a separate local reference collection; it is not used to infer
statewide USGS coverage. Existing Basin Plan, CalWater, EBMUD and flood-reference
bytes are preserved. Attribution and supplier notices remain applicable; derived
tables do not imply agency endorsement.

## Statewide directed hydrography extension

**U.S. Geological Survey.** *Water Mission Area geospatial services,
`wmadata:nhdflowline_network` (NHDPlusV2 network).* Accessed October 19, 2026
(Pacific time); individual receipts use UTC.

- [USGS WFS capabilities and declared CRS](https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=2.0.0&request=GetCapabilities)
- [USGS network feature schema](https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=2.0.0&request=DescribeFeatureType&typeNames=wmadata:nhdflowline_network)
- [Local routing methods and selected source attributes](ROUTING_METHODS.md)

The extension requests geometry, COMID, names, reachcodes, node/hydrosequence
keys, length, direction, enabled, divergence, terminal, tidal, feature-type and
VPU attributes. Original selected-field responses and count evidence are archived.
Published node-key joins are distinguished from derived reachability and CalWater
overlaps. The graph is not a newly calibrated hydraulic model. Regional source
provenance remains the pinned Basin Plan/CalWater archive cited above.

## Supplemental station-address investigation

Accessed 2026-10-20 UTC (October 19 Pacific time). Individual source receipts
record request URLs and precise retrieval times.

**California State Water Resources Control Board.** *California Stream Gages,
StreamGages_20210114 / StreamGages_v3c; Senate Bill 19 Stream Gaging Plan.*

- [State stream-gaging program and SB19 context](https://waterboards.ca.gov/waterrights/water_issues/programs/stream_gaging_plan/)
- [California Stream Gages item metadata and source description](https://gispublic.waterboards.ca.gov/portal/sharing/rest/content/items/32dfb85bd2744487affe6e3475190093?f=json)
- [Original station layer, schema and attribution](https://gispublic.waterboards.ca.gov/portalserver/rest/services/Hosted/StreamGages_20210114/FeatureServer/0)
- [SB19 linked-data catalog and original-item reference](https://sb19.linked-data.internetofwater.dev/collections/ca_gages?f=json)

The source describes an assessment originating in a fall 2020 snapshot, including
station points moved to NHD medium-resolution features for analysis. It defers to
originating agencies and is not an authoritative current station inventory.
`siteid` / `site_id`, `operator`, `comid_medres`, and `rchcd_medres` provide the
published identity and address keys. The SB19 service is a linked representation
of this catalog; agreement between the representations is not independent
hydraulic confirmation. Attribution and original item/service metadata are
preserved with the responses.

**U.S. Geological Survey and Internet of Water / Geoconnex contributors.**
*NLDI linked-data sources and Geoconnex reference gages.*

- [NLDI feature-source documentation](https://api.water.usgs.gov/docs/nldi/feature-sources/)
- [NLDI SB19 California gages source](https://api.water.usgs.gov/nldi/linked-data/ca_gages)
- [Geoconnex reference gages and collection metadata](https://reference.geoconnex.us/collections/gages?f=json)
- [Reference-feature access documentation](https://docs.geoconnex.us/access/reference/)
- [Reference-gage source repository and attribution](https://github.com/internetofwater/ref_gages)

Exact `provider_id` and `provider` checks distinguish USGS stations from other
operators. Reference-gage responses are preserved even when their hydrography
keys are null. Original supplier notices and attribution remain applicable.
Neither reference records nor names alone
establish downstream flow.

**U.S. Geological Survey.** *Hydrologic fabric pygeoapi,
`nhdflowline_nonnetwork` collection.*

- [Fabric API documentation](https://api.water.usgs.gov/docs/fabric-pygeoapi/)
- [Nonnetwork flowline collection](https://api.water.usgs.gov/fabric/pygeoapi/collections/nhdflowline_nonnetwork?f=json)

Exact COMID requests preserve original feature geometry, reachcode and flow
attributes for published candidates outside the saved routable network.
These records support static station-to-feature addresses only. Collection
`prev` and `next` links are pagination, not flow connections.

The [review methods](LINK_REVIEW_METHODS.md) document acceptance requirements,
uncertainty and spatial QA tolerances. The initial review preserves 214 source
receipts, 150 candidate rows and 15 original nonnetwork features; the
[validation report](link_review_verification.json) records verified counts.
No observation or historical level download is part of this investigation.

## Original-agency investigation of conflicting and missing addresses

**U.S. Geological Survey and U.S. Environmental Protection Agency.**
*NHDPlus Version 2.1 National Data, GageLoc content version 05.*
Retrieved 2026-10-20 UTC.

- [EPA National Data distribution page](https://www.epa.gov/waterdata/nhdplus-national-data)
- [Original GageLoc version 05 archive](https://dmap-data-commons-ow.s3.amazonaws.com/NHDPlusV21/Data/NationalData/NHDPlusV21_NationalData_GageLoc_05.7z)
- [USGS reference-fabric acquisition code identifying GageLoc and the EPA distribution](https://code.usgs.gov/wma/nhgf/reference-fabric/reference-hydrofabric/-/blob/2.1-pre/workspace/00_get_data.Rmd?ref_type=tags)

The original 7z archive is retained losslessly. Exact `SOURCE_FEA` station IDs,
`SOURCE_ORI`, `EventType`, `FLComID`, `REACHCODE`, and `EVENTDATE` support the
address review. The 20 matching records have event dates of 2014-12-04.
Their older source-assigned locations are checked against fresh USGS station
metadata and current USGS fabric features. A valid historical address is not
evidence of present hydraulic connectivity.

**Hayes, L., Chase, K.J., Wieczorek, M.E., and Jackson, S.E.**
*USGS Streamgages in the Conterminous United States Indexed to NHDPlus v2.1
Flowlines to Support Streamgage Watershed InforMation (SWIM), 2021.*
U.S. Geological Survey data release, DOI **10.5066/P9J5CK2Y**. The USGS landing
page lists publication on December 4, 2023; the enclosed metadata is dated 2021.
Retrieved 2026-10-20 UTC.

- [USGS release description, scope and attribution](https://www.usgs.gov/data/usgs-streamgages-conterminous-united-states-indexed-nhdplus-v21-flowlines-support-streamgage)
- [Persistent release DOI](https://doi.org/10.5066/P9J5CK2Y)
- [ScienceBase item metadata and publisher file checksums](https://www.sciencebase.gov/catalog/item/5ebe92af82ce476925e44b8f?format=json)
- [Original release archive](https://www.sciencebase.gov/catalog/file/get/5ebe92af82ce476925e44b8f)

The release retains reviewer comments for addresses excluded from the network.
The exact station selection preserves `QC_notes1`, `Rev_notes2`, `Ver_notes3`,
`QC_final`, sentinel values and all other original attributes. The collection
has long-record selection criteria; an absent station is not an agency finding
that no valid waterway address exists.

The downloaded DBF, SHP, SHX and PRJ files match the publisher's byte counts and
MD5 values. The enclosed XML metadata has the published byte count but a
different MD5. That publisher metadata discrepancy is retained explicitly in
[agency verification](agency_review_verification.json); the XML is not used
to decide station addresses. Raw-response SHA-256 receipts verify the exact
downloaded bytes independently. The original XML is preserved without repair.

**U.S. Geological Survey.** *Current monitoring-location metadata, NLDI NWIS
station addresses, and hydrologic fabric nonnetwork features.* Each of the
37 stations has an exact-ID metadata and NLDI recheck. Newly examined features
are requested by their published identifier, never by a nearest-point query.
The earlier USGS API and fabric citations above apply. Receipts preserve exact
URLs and retrieval times. No historical level or discharge series is acquired.

See [agency-review methods](AGENCY_REVIEW_METHODS.md) for the 13 static addresses,
24 remaining unresolved cases, source-vintage limits and refresh commands.

## Local operating-agency investigation

Retrieved 2026-10-20 UTC. The [station review and source catalog](LOCAL_REVIEW.md)
lists all 34 configured URLs, publishers, selected metadata, retrieval results and
station-specific findings. Sources with failed retrievals provide no accepted
relationship evidence.

**Santa Ana River Watermaster, published by San Bernardino Valley Municipal
Water District.** *2025 Supplemental Volumes* and *2024 Appendices.*

- [2025 Supplemental Volumes](https://www.sbvmwd.com/app/uploads/2025/12/2025-Supplemental-Volumes.pdf): PDF page 140, printed page 136, Table 4 identifies the Fontana weirs, lower-powerhouse inflow and afterbay return by complete USGS station number.
- [2024 Appendices](https://www.sbvmwd.com/app/uploads/2025/12/2024-Appendices.pdf): PDF page 117 explicitly identifies USGS 11062820 as diversions from Fontana Powerhouse Afterbay.

These published identities and operational roles support nine metadata
relationships for six stations. They do not resolve conflicting hydrography
addresses. Descriptive local facility keys are curated identifiers rather than
agency feature IDs.

**California Department of Water Resources.** *Evaluation of Salinity Patterns
and Effects of Tidal Flows and Temporary Barriers in South Delta Channels*
(2016), Attachment B; *California Data Exchange Center station metadata.*

- [South Delta report](https://water.ca.gov/-/media/DWR-Website/Web-Pages/Programs/State-Water-Project/Operations-And-Maintenance/Files/Bay-Delta/South-Delta-Temporary-Barriers-Project/Reports/Evaluation-of-Salinity-Patterns-and-Effects-of-Tidal-Flows-and-Temporary-Barriers-in-South-Delta-Cha.pdf): PDF page 172 identifies Victoria Canal USGS 11312672 as VCU; page 174 associates the older Grant Line station 11313200 with GLC.
- [Current VCU metadata](https://cdec.water.ca.gov/dynamicapp/staMeta?station_id=VCU).
- [Current GLC metadata](https://cdec.water.ca.gov/dynamicapp/staMeta?station_id=GLC): identifies USGS 11313240 and a relocation, so the older Grant Line alias is not applied to current records.

Additional contextual sources include the U.S. Bureau of Reclamation, Imperial
Irrigation District, Madera Irrigation District, Modesto Irrigation District,
Lake County, Tulare County, DWR bathymetry metadata and Wildlands' Liberty Island
project description. Their exact citations and retrieval gaps are retained in
the [source catalog](LOCAL_REVIEW.md). Facility descriptions without an exact
station cross-reference do not establish station identity or routing.

Only reviewed metadata excerpts are retained from these reports and pages.
Historical measurement columns and complete document bodies are excluded.
Receipts record source URLs, retrieval times and original response hashes where
available; discarded bodies cannot be rehashed offline. See
[local review methods and retention limits](LOCAL_REVIEW_METHODS.md).

Four additional official sources address contextual gaps left by the two IID
pages and the Tulare County directory: Reclamation's 2007 Drop 2 final EA,
Reclamation's All-American Canal project description, the State Controller's
Tulare County district classifications, and Pixley Irrigation District's 2012
water management plan hosted by Reclamation. The
[alternate-source investigation and full citations](SOURCE_ACCESS_REVIEW.md)
identify pages, source vintages, failed alternatives and interpretation limits.
These sources supply no new exact station or hydrography matches. The
source-to-source table preserves the original access failures.

## Additional official maps and station records

Retrieved 2026-10-20 UTC. The [24-station investigation](ADDITIONAL_AGENCY_REVIEW.md)
also lists contextual records, unavailable sources and rejected equivalences.
Four new sources are included in the maintained refresh rules:

- **USGS**, *Water Resources Data, California, Water Year 1998, Volume 3*,
  [station 11267350, printed page 311 / PDF page 333](https://pubs.usgs.gov/wdr/1998/ca-98/WRD-1998-vol3.pdf).
  The exact station heading and diversion remarks support historical roles from
  Big Creek to Lewis Fork of the Fresno River. Daily tables are not retained.
- **Mullen, J.R., and Nady, P., USGS**, *Water budgets for major streams in the
  Central Valley, California, 1961-77*, Open-File Report 85-401 (1985),
  [Tuolumne schematic and station key](https://pubs.usgs.gov/of/1985/0401/report.pdf),
  printed pages 50 and 52 / PDF pages 48 and 50. Line 1 explicitly identifies
  11289000 as the Modesto Canal diversion. The historical schematic does not
  choose a current NHDPlus segment.
- **USGS**, *Physics to fish: Understanding the factors that create and sustain
  native fish habitat in the San Francisco Estuary*, Open-File Report 2023-1087,
  [Table 1 and Figure 66](https://pubs.usgs.gov/publication/ofr20231087/full).
  Table 1 associates 11455276 with report identifier SGG. Figure 66 identifies
  Liberty Island Conservation Bank gauge 382006121401601, distinct from both
  unresolved Wildlands gauges. Only selected metadata literals are retained.
- **USGS**, [Data Series 756](https://pubs.usgs.gov/ds/756/pdf/ds756.pdf),
  station metadata table, PDF page 19. Connection Slough near Middle River is
  explicitly numbered 380000121340801, not the unresolved Swing Bridge station
  380015121315101. The retained name-and-ID excerpt supports this distinction
  only; sample counts and historical chemistry measurements are excluded.

## Five-source access retry

The [retry investigation](SOURCE_ACCESS_REVIEW.md#five-source-retry-and-additional-records)
records access attempts, failed alternate county URLs and four additional
contextual source-to-source relationships. Two new sources enter the maintained
refresh rules:

- **Bureau of Reclamation**, *Warren H. Brock Reservoir Conservation Summary
  Report*, December 2020,
  [printed page 5 / PDF page 11](https://www.usbr.gov/lc/region/programs/strategies/agreements/BrockReport.pdf).
  Completed-facility outlet and administrative operating-status metadata only;
  historical water volumes and costs are excluded.
- **California DWR**, [SGMA GSP submission 42, reference inventory](https://sgma.water.ca.gov/portal/gsp/preview/42).
  The Deer Creek Storm Water District/LAFCO attribution is retained as
  administrative context; no gauge ownership or current boundary is inferred.

The existing [Reclamation Yuma Division source](https://www.usbr.gov/projects/index.php?id=439)
now also retains the Pilot Knob return-role sentence. The existing
[Parker Dam facility record](https://www.usbr.gov/projects/index.php?id=207)
is linked as contextual fallback for intermittent RISE access. These records
provide no new accepted station or hydrography link. Original source URLs and
failed receipts remain distinct from the alternatives.

## Evidence locations

Each active pointer binds a manifest and its file hashes. Except for the
metadata-only local operating-agency selections described above, source responses are
stored under `raw/` with `.receipt.json` companions. Receipts contain exact request
URLs, HTTP response metadata, retrieval UTC timestamps, compressed-file hashes,
and original-body hashes. API keys are excluded. Metadata/network generations
retain source evidence; observation source evidence is replaced with the next
successful current snapshot rather than accumulated as level history.
