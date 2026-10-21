# Offline flood-impact reference

[Documentation index](../../docs/README.md) | [Terminal commands and all maintenance options](../../docs/CLI_REFERENCE.md).

This repository distributes the download programs, curated configuration, tests
and documentation. Downloaded datasets, generation pointers, generated catalogs
and validation reports are local outputs excluded from Git. Follow the
[fresh-clone water-data setup](../../docs/WATER_DATA_SETUP.md) before using offline
queries. Links to generated catalogs and reports below become available after
the relevant download or validation command completes. Historical investigation
counts describe development evidence, not files included with the repository.

This collection connects named waterways, monitoring gauges, published downstream
flow connections, stage-based inundation scenarios, and the portions of CalWater
basins intersected by those scenarios. CSV relationships support manual review;
compressed GeoJSON supports offline GIS inspection.

The initial pilot covers the Russian River near Healdsburg and downstream toward
Guerneville in the **North Coast** region. The complete statewide Basin Plan
collection remains in [its existing regional organization](../basin_plans/REVIEW.md).
Flood analysis outside this pilot is explicitly **not yet assessed**.

[Active regional catalog and CalWater categories](REVIEW.md) ·
[Methods and table definitions](METHODS.md) · [Sources and citations](SOURCES.md)

Saved examples: [23-foot Healdsburg what-if report](example_minor_stage_report.json)
and [latest verification evidence](verification.json). Both identify their source
generations and evaluation times; they are not automatically refreshed reports.

## Available evidence

- Two NOAA/USGS gauges linked to published NHDPlusV2 reaches.
- 38 acquired reaches, 38 directed connections, and one source-terminal row.
- 16 NOAA experimental static scenarios for Healdsburg: 20 through 34 feet,
  plus the 30.8-foot record scenario.
- 241 reach/CalWater intersections, 329 gauge/reach/basin relationships, and
  240 scenario/basin portions across six separately organized CalWater levels.
- 34 exact-reachcode candidate links to published Basin Plan reference rows.
- Independent cached observation and forecast series, with raw values, units,
  valid times, issue times, and source receipts.

These counts describe the initial verified pilot; the active manifest records
subsequent generations. NOAA's CatFIM catalog marks Guerneville's maps unavailable
because of a datum-conversion failure. That gap remains explicit. The stage
library describes hypothetical conditions, not a current flood perimeter.
[Source description](SOURCES.md#noaa-stage-based-catfim)

## Setup and use

Python 3.11 or later, Shapely 2, and pyproj 3 are required. The tools run from the
repository on Windows or Linux. They do not change the paired MeshCore services
or register a radio command.

```console
python -m pip install -r data/flood_impacts/requirements.txt
python data/flood_impacts/report.py --verify
python data/flood_impacts/validate.py
python data/flood_impacts/report.py --gauge HEAC1
python data/flood_impacts/report.py --gauge GUEC1
```

The report lists scenario IDs. Review a selected **what-if** condition:

```console
python data/flood_impacts/report.py --gauge HEAC1 --scenario HEAC1_d8d5066cd04e
```

This initial scenario represents the published 23-foot minor threshold. IDs include
the gauge, layer, stage, units, category, and model versions; use the report's
current IDs after a source update. `--output report.json` saves the report.
`--at 2026-10-20T04:01:00Z` evaluates cached data at an explicit historical UTC time;
it does not retrieve a historical forecast.
Cached series may include later corrections, so this option does not establish
which information was available to an operator at that historical time.

## Refresh and offline rebuild

```console
python data/flood_impacts/refresh.py
python data/flood_impacts/refresh.py --mode observations
python data/flood_impacts/refresh.py --mode static
python data/flood_impacts/refresh.py --mode static --offline
python -m unittest data.flood_impacts.test_flood_impacts -v
```

The default refresh acquires static sources and then observations. Observation-only
refreshes avoid redownloading maps. Static refreshes read the current verified
Basin Plan archive for CalWater and reach-reference records. Offline rebuilding
uses preserved inputs from the last flood generation, without silently selecting
a newer Basin Plan snapshot. Refresh observations after a static rebuild to bind
subsequent reports to that generation.

`pilot.json` contains stations, region, plan label, route distance, coordinate
system, and freshness limits. Use `--config` and `--directory` for another pilot
so its pointers and catalogs remain separate. Stations in one configuration must
belong to its declared review region. Region and plan labels are configuration
metadata; CalWater drainage geometry remains a separate classification.

Each refresh creates immutable `static/<generation>/` or
`observations/<generation>/` directories. Atomic pointers select complete
generations. Earlier generations, source attributes, receipts, and checksums remain
available. Failures leave `.pending-*` evidence and preserve the active pointer.
Re-run after resolving the failure; pending directories are not complete data.
There is no automatic pruning.

`report.py --verify` checks artifact hashes. `validate.py` additionally checks raw
response receipts, published node joins, NLDI route agreement, CSV/GeoJSON area
agreement, and containment within source scenarios. `--output verification.json`
saves its evidence report. These checks do not validate hydraulic predictions.

## Interpretation limits

The separate [California USGS collection](../usgs_water/README.md) inventories
stations statewide and retains current stage/discharge snapshots. Its statewide
station-to-reach links and CalWater membership tables extend beyond this pilot.
It pins the pilot's existing tributary, downstream-basin and scenario relationships
without changing their originals. Russian River serves as an integration check;
the USGS download scope is the entire state. USGS measurements do not automatically
establish CatFIM datum compatibility or enlarge the verified inundation coverage.
The USGS collection replaces prior readings on refresh and retains no level history.

The [statewide routing extension](../usgs_water/ROUTING_METHODS.md) now supplies
directed reach connections, confluence/tributary tables and derived potential
CalWater basin links for California. These are separate from this pilot's
scenario-specific inundation intersections. Statewide connectivity does not expand
the validated flood-scenario library.

Connected downstream reaches identify where to investigate. They do not establish
flood arrival time, depth, overtopping, or flooding of an entire watershed.
Scenario/basin polygons are actual intersections of published footprints and
CalWater polygons, including portions outside a simple downstream route.

Stage comparisons require the same gauge, published datum and zero, supported
units, and sufficiently fresh measurements. They return bracketing reference
scenarios without interpolation. Values outside the library, missing data, datum
changes, and stale forecasts remain unassessed. Reports recompute freshness when
opened offline; an old successful retrieval does not remain current indefinitely.

`structure_connections.csv` is empty because no verified operator inventory has
been acquired. Aqueduct breach/overtopping, gates, pumps, reservoir operations,
travel-time models, depth estimates, and asset exposure are **not implemented
assessments**. Operator records and applicable hydraulic scenarios are needed for
those uses. No buffer or single-gauge elevation extrapolation replaces an
inundation model. [Extension requirements](METHODS.md#extension-boundaries)
