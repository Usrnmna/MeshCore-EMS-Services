# Flood-reference sources and attribution

Dataset and generated-report paths below identify local acquisition outputs.
They require the corresponding collection, generation, or validation run
described in [water-data setup](../../docs/WATER_DATA_SETUP.md). Packaged
documentation contains the guides; historical generation paths may differ
from later acquisitions.

Initial acquisition: **2026-10-20 UTC (2026-10-19 Pacific)**. Exact request URLs,
headers, retrieval timestamps, byte counts, and hashes are in each generation's
`raw/*.receipt.json`. The regional `relationships/dataset_provenance.csv` provides
a flat catalog. Retrieval time differs from observation time and source vintage.

## NOAA stage-based CatFIM

**NOAA/National Weather Service, National Water Center.** *Experimental Stage-Based
Categorical Flood Inundation Mapping (CatFIM).* Acquired pilot attributes report
FIM version **6.2** and model version **4.9.20.1**.

- [Official FeatureServer and service description](https://maps.water.noaa.gov/server/rest/services/fim_libs/static_stage_based_catfim/FeatureServer)
- [Site coverage layer](https://maps.water.noaa.gov/server/rest/services/fim_libs/static_stage_based_catfim/FeatureServer/0)
- [NWS flood-inundation operations and documentation](https://www.weather.gov/owp/operations)
- [NOAA FIM educational resources](https://water.noaa.gov/about/FIMResourceInfo.html)

The service describes experimental HAND-derived maps for thresholds and one-foot
intervals, generally extending five miles upstream/downstream of each gauge along
consistent stream order. Maps are static between product updates. They do not
cover the full 80-km routing query. Source attribution names the National Water
Model, NOAA/NWS National Water Center, Advanced Hydrologic Prediction Service, and
National River Layer Database; full metadata is retained.

Layers 2, 3, 5, 6, 8, 9, 11, 12, and 13 are exported for `heac1` and `guec1`.
All 16 returned polygons belong to Healdsburg. Guerneville reports a NOAA VDatum
failure and `mapped=no`; no replacement footprint is invented. The separate
coverage inventory selects site rows whose `states` field includes `CA`.

## NOAA NWPS measurements and station metadata

**NOAA/National Weather Service.** *National Water Prediction Service (NWPS), gauge
metadata and stage/flow series.* Provider attribution remains in raw records,
including USGS and USACE contributions where supplied.

- [NWPS API](https://api.water.noaa.gov/nwps/v1/gauges)
- [Healdsburg metadata](https://api.water.noaa.gov/nwps/v1/gauges/HEAC1)
- [Healdsburg observations and forecasts](https://api.water.noaa.gov/nwps/v1/gauges/HEAC1/stageflow)
- [Guerneville metadata](https://api.water.noaa.gov/nwps/v1/gauges/GUEC1)
- [Guerneville observations and forecasts](https://api.water.noaa.gov/nwps/v1/gauges/GUEC1/stageflow)
- [Official water-data service catalog](https://water.noaa.gov/about/data-and-web-services-catalog)

This is the NWPS source family already used by the nearby-river lookup. The
reference pipeline adds archived series, datum metadata, and independent refreshes.
Published units and timestamps remain intact. Source `no_flooding` categories are
not treated as proof of a dry downstream basin.

## USGS NLDI and NHDPlusV2 network

**U.S. Geological Survey.** *Network Linked Data Index (NLDI)* and
*wmadata NHDPlusV2 flowline network*.

- [NLDI documentation](https://api.water.usgs.gov/docs/nldi/)
- [Navigation definitions and indexing limitations](https://api.water.usgs.gov/docs/nldi/navigation/)
- [Healdsburg indexed site](https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-11464000)
- [Guerneville indexed site](https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-11467002)
- [USGS WFS capabilities](https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=2.0.0&request=GetCapabilities)
- [NHDPlusV2 data-model guide, EPA publication](https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P10198U6.TXT)
- [USGS node and divergence attribute definitions](https://www.usgs.gov/national-hydrography/value-added-attributes-vaas)

NLDI selects the downstream-with-diversions reach set. WFS supplies named flowlines
and FROMNODE/TONODE attributes for that exact COMID set. The stored network label
identifies NHDPlusV2; IDs must not silently join to another hydrography version.
Catchment-based NLDI indexing can include the portion of the starting reach above
the gauge. Node topology does not establish current operator controls.

## California Basin Plan and CalWater archive

**California State Water Resources Control Board and Regional Water Quality
Control Boards.** *Basin Plan Portal; regional hydrography references; CalWater
Watersheds 2.2.1.*

- [Original Basin Plan portal](https://www.waterboards.ca.gov/resources/data_databases/basin_plan_portal.html)
- [CalWater source service](https://gispublic.waterboards.ca.gov/portalserver/rest/services/Hosted/CalWater/FeatureServer)
- Complete local source inventory (`../basin_plans/INVENTORY.md`)
- [Relationship methodology and keys](../basin_plans/RELATIONSHIPS.md)
- [Existing preservation and refresh documentation](../basin_plans/README.md)

The initial pilot pins Basin Plan snapshot `20261019T073417Z_c776769a`. Its pointer,
manifest hash, dataset keys, source URLs/export hashes, retrieval dates, and
selection envelope are in `inputs/basin_provenance.json`. Original archives are
verified without modification. Intersections and candidate joins are labeled as
derived. EBMUD geometry is not substituted for statewide hydrography or flood maps.

## Attribution and interpretation

Statewide USGS monitoring locations, current gage-height/discharge observations,
and NLDI station links are documented in the separate
[USGS source register](../usgs_water/SOURCES.md). That collection preserves this
pilot's pinned source references and relationship tables. Its latest-value
retention policy does not alter existing flood-reference archives.

Agency attribution and supplied metadata are retained. This collection makes no
blanket license claim for third-party inputs; retain source notices and consult
agency terms when redistributing. Generated intersections are local derived
products, without agency endorsement or independent agency validation.
