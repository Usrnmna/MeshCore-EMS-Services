# Command implementations and evidence boundaries

## Runtime organization

Each of the 50 commands has its own `scripts/` program in both platform packages
and a direct `config.json` registration. Helpers share parsing, source access and
formatting; no registration selects a generic dispatcher using fixed arguments.
The existing responder owns channels, sender context, cooldowns, radio limits and
subscription scheduling. Dedicated programs support direct Python invocation.

| Commands/component | Shared implementation | Behavior and prerequisite |
| --- | --- | --- |
| Help and data status | `command_help`, `command_dependencies`, `data_status`, `data_reporting`, `dataset_paths` | Channel-filtered discovery and bounded, read-only installed generation/cache checks. |
| State Parks, entrance | `stateparks_lookup` | Exact units/points, verified collection schemas and explicit ambiguity. |
| Camp, parking, facility | `parks_sites`, `facility_lookup` | Exact source attributes, AND predicates before map-distance ranking; partial cross-collection coverage. |
| Trail endpoints/filters | `gis_data`, `gis_lookup`, `trail_queries` | Recorded endpoint roles/IDs; no inferred start/end ordering. |
| Gauge and gauges | `gauge_data`, `gauge_lookup`, existing `water_*` adapters | Exact station identity, series selection, live/snapshot provenance, freshness and quality. |
| Downstream, tributaries | `connectivity_lookup` | Read-only pinned routing database; supported reviewed links and one-hop branches. |
| Named waterway, basin parent, wateruse | `basin_plan_data`, `basin_plan_lookup` | Source-qualified object identity and recorded relationship tables. |
| Satellite catalog/frequency | `satellite_lookup` | Read-only catalog, evidence-based status, independent operations and no tracking import requirement. |
| Satellite pointing/passes | `satellite_pointing`, `satellite_terrain`, `satellite_passes` | Eligible local orbit plus datum-qualified local observer terrain; bounded solver, no acquisition. |
| Fire detail | `wildfire_lookup` | Field-specific source/time and independent perimeter evidence using existing adapters/cache. |
| Station metadata | `landslide_lookup`, `landslide_data` | Catalog evidence, complete instrument fields and telemetry-unverified status. |
| Geographic identification | `where_data`, `where_lookup` | Installed polygon containment with boundary/overlap/coverage qualification. |
| Weather | `weather_source`, `weather_lookup` | Bounded NWS point/product validation, query-time freshness and qualified cached fallback. |
| Briefing | `brief_sources`, `brief_lookup` | One resolved point, separate selected source results, no subscription ownership. |

Module names refer to Python files in either package's `scripts/` directory.
[Accepted radio forms](../meshcore_mqtt_service/COMMAND_REFERENCE.md#command-index),
[function references](../meshcore_mqtt_service/FUNCTION_REFERENCE.md), and
[terminal invocation](CLI_REFERENCE.md#dedicated-lookup-programs) provide the detailed contracts.

## Data selection and failures

Managed dataset receipts and selected generations remain authoritative. Custom data
roots use the existing settings and `MESHCORE_DATA_DIR`/runtime context. Explicit
removal blocks fallback to a bundled or stale alternate copy. Integrity failures,
incompatible dependency pins and bounded verification remain distinct from absence.
An installed inventory is not proof of live readings, complete geographic coverage,
valid transformation evidence or current provider availability.

The maintenance archive is shared with USGS tools. Supported publication kinds are
`static`, `observations`, `inventory`, `network`, `routing`, `link_review`,
`agency_review`, and `local_review`. Candidates must use the exact isolated pending
directory, preserve reserved manifest fields, and pass hash/alias checks. Validator
changes are rejected before pointer activation. `activate=False` seals a detached
candidate without replacing an active pointer. Runtime lookup commands do not publish.

## Satellite terrain qualification

`MESHCORE_SATELLITE_SETTINGS` selects an explicit settings file; otherwise the
service's `satellite-settings.json` is used when present. The settings object must
include `database`, the satellite catalog path resolved relative to that file.
`pointing.terrain_sources`
contains at most four local source entries with `id`, `path`, `sha256`, `bytes`,
`vertical_crs`, `units`, and nonempty `source` provenance. IDs contain 1–12 ASCII
letters, digits, underscores or hyphens. Paths resolve relative to the settings file.

Sources require an eligible single-band GeoTIFF with a horizontal CRS and matching
integrity evidence. Units are `m`, international `ft`, or `us_survey_ft`; those foot
definitions are not interchangeable. WGS84 ellipsoidal terrain uses EPSG:4979.
Orthometric heights require an explicit supported vertical CRS and available local
PROJ transformations/grids. Ballpark transformations and network grid acquisition
are disabled. NoData, incompatible/ambiguous sources or missing transformations
produce unavailable results. Source limits include 128 MiB per file, 100 million
pixels and 16 MiB decoded raster blocks. These are qualification bounds, not a
promise that every source within them is eligible.

Latitude/longitude locate the ground sample; they do not supply altitude. Antenna
AGL is added to the qualified ground height before orbital calculation. Elevation
angles are geometric and azimuth is measured clockwise from true north. Terrain
height is not a terrain-horizon or obstruction calculation. `!sat`/`!satfreq` do
not need Skyfield; pointing/pass queries require their orbital and GIS dependencies.

## Restricted reference isolation and paused modelling

Local B01–B11 reference support is separate from operational generations. The
`.reference-only` directory and `reference-catalog.json` mark restricted content;
`reference_policy` rejects these paths or purpose declarations in operational
consumers. `reference_catalog`, `reference_environment`, `reference_elevation_xml`
and `reference_elevation_baseline` retain source identity, XML/datum evidence,
explicit tile selection, ambiguity, NoData and native units.

The reference readers cover enrolled elevation tiles, datum-grid values, soils,
hydrography, watershed boundaries and land-cover products. Native-reference sampling
does not authorize precision conversion or model use. B09–B11 readers sample native containing pixels only; they do not use overviews
or resampling. B10 values are recorded impervious percentages, not runoff or
infiltration rates; zero does not mean zero runoff. B11 scores 1–100 are unitless
confidence, not calibrated probabilities or percentage accuracy. Zero is unavailable
with an unresolved-zero qualification; codes above 100 retain additional-interpretation
status without inventing a score. NoData is evaluated independently. Acquisition, enrollment
and operational activation remain separate from these readers.

W10 is paused. Its internal evidence/discovery/scenario/hazard/readiness helpers
remain separate from radio command registration; readiness does not enable a model.
No `!floodref` or `!rivertrend` command exists. Existing flood-alert/status/monitoring
features retain their established service behavior. W19A/B/C/E/F/G/H additional-source
investigations remain deferred and are not release dependencies for current commands.

## Verification and package boundaries

Run each package's complete offline test suite, including `tests/test_command_programs.py`.
Focused tests cover identity collisions, ambiguity, stale/missing evidence, quality
flags, custom roots, managed removal, integrity/generation failures, bounded replies,
direct invocation and service context. The archive regression suite exercises all
existing publication kinds, pointer isolation, detached candidates and tamper rejection.

Installer tests must copy the runtime `reference_policy` dependency into isolated
fixtures. GUI default-command tests compare identities and programs against the
selected platform configuration rather than a historical command count.
Documentation gates check command indices, tagged UTF-8 examples, focused signatures,
links and publication exclusions. Package collectors include runtime helpers while
excluding local downloaded data, private state and environments.

Host fixtures and package parity do not establish native deployment, hosted CI,
live-provider behavior, physical radio reception or representative large-dataset
performance. Native clean install/upgrade/removal and reboot checks remain separate
release qualification. Historical validation records retain their original revisions.
