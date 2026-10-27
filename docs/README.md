# Documentation index

The [project overview](../README.md) introduces capabilities and the channel
experience. This index groups detailed guidance by task. Linux and Windows
command guides describe the same command behavior; platform setup and paths differ.

## Setup and everyday use

| Task | Documentation |
| --- | --- |
| Install or upgrade an OS service | [Installation and upgrade guide](../INSTALL.md) |
| Send commands and interpret replies | [Linux quick user guide](../meshcore_mqtt_service/BOT_USER_GUIDE.md) · [Windows quick user guide](../meshcore_mqtt_service_windows/BOT_USER_GUIDE.md) |
| Find exact syntax, fields, errors, and examples | [Linux command reference](../meshcore_mqtt_service/COMMAND_REFERENCE.md) · [Windows command reference](../meshcore_mqtt_service_windows/COMMAND_REFERENCE.md) |
| Interpret concise replies and notification examples | [All command and subcommand response examples](../meshcore_mqtt_service/RESPONSE_EXAMPLES.md) · [Response priorities, byte limits, and conditional fields](../meshcore_mqtt_service/RESPONSE_FORMATTING.md) |
| Find every radio selector and terminal option | [Complete radio subcommand index](../meshcore_mqtt_service/COMMAND_REFERENCE.md#subcommand-index) · [All terminal commands, maintenance flags, and satellite subcommands](CLI_REFERENCE.md) |
| Query water conditions or manage flood monitoring | [Water guide](../meshcore_mqtt_service/WATER_GUIDE.md) · [NOAA station-identity and threshold evidence](../meshcore_mqtt_service/WATER_STATION_REVIEW.md) |
| Query wildfire, smoke, fuel danger, or landslide information | [Wildfire and smoke guide](../meshcore_mqtt_service/WILDFIRE_GUIDE.md) · [California/Nevada landslide guide](../meshcore_mqtt_service/LANDSLIDE_GUIDE.md) |
| Run or troubleshoot a platform package | [Linux setup and operation](../meshcore_mqtt_service/README.md) · [Windows setup and operation](../meshcore_mqtt_service_windows/README.md) |
| Assign channels, protect private keys, or add command programs | [Linux multi-channel guide](../meshcore_mqtt_service/MULTI_CHANNEL_GUIDE.md) · [Windows multi-channel guide](../meshcore_mqtt_service_windows/MULTI_CHANNEL_GUIDE.md) |

## Connections, implementation, and maintenance

| Topic | Documentation |
| --- | --- |
| System connections, component responsibilities, platform defaults, and MQTT | [Service architecture and MQTT interface](ARCHITECTURE.md) |
| Repository layout, ignore policy, packaging, and software checks | [Development, packaging, and verification](DEVELOPMENT.md) |
| Service and command functions | [Linux function reference](../meshcore_mqtt_service/FUNCTION_REFERENCE.md) · [Windows function reference](../meshcore_mqtt_service_windows/FUNCTION_REFERENCE.md) |
| Water and wildfire implementation details | [Water/flood function reference](../meshcore_mqtt_service/WATER_FUNCTION_REFERENCE.md) · [Wildfire/smoke/fuel function reference](../meshcore_mqtt_service/WILDFIRE_FUNCTION_REFERENCE.md) |
| Installer configuration and distribution functions | [Tool function reference](../tools/FUNCTION_REFERENCE.md) |
| Passing hosted CI, recorded software checks, and remaining deployment limits | [Installer and service validation](../installers/VALIDATION.md#hosted-github-actions-october-26-2026) |
| Version changes and migration | [Workspace release notes](../RELEASE_NOTES.md) · [Version 0.9.6 - Beta comparison](../RELEASE_v0.9.6-beta.md) · [Linux package notes](../meshcore_mqtt_service/RELEASE_NOTES.md) · [Windows package notes](../meshcore_mqtt_service_windows/RELEASE_NOTES.md) |
| Local historical recovery snapshots | [Recovery archive guidance](../archive/README.md) |

## Data and separate reference tools

[Independent dataset installers, updates, recovery and removal](DATA_PACKAGES.md)
cover the separate Windows, Linux and Raspberry Pi packages. Failed source
updates retain the active local dataset and its original freshness information.
The [editable PyQt6 dataset manager](DATASET_GUI.md) adds checkbox selection,
batch planning and manual GUI builds that reuse the existing dataset installers.

| Topic | Documentation |
| --- | --- |
| Wildfire commands, forecasts, alarms, point smoke/fuel context and interstate boundaries | [Wildfire guide](../meshcore_mqtt_service/WILDFIRE_GUIDE.md) · [Zone seed](../data/wildfire/README.md) |
| EBMUD snapshots used by the five GIS commands | [Loading, source freshness, refresh, and polygon repair](../data/ebmud/README.md) · [Maintenance function reference](../data/ebmud/FUNCTION_REFERENCE.md) |
| California State Parks reference collection | [Collection, acquisition evidence, loading, and reuse terms](../data/california_state_parks/README.md) · [Dataset and attribute dictionary](../data/california_state_parks/DATA_DICTIONARY.md) |
| California Basin Plan reference collection | [Download datasets after cloning](WATER_DATA_SETUP.md) · [Name search and organization](../data/basin_plans/ORGANIZATION.md) · [Tributary and other relationship tables](../data/basin_plans/RELATIONSHIPS.md) · [Acquisition, offline use, and refresh](../data/basin_plans/README.md) |
| Offline flood-impact reference pilot | [Setup and refresh](../data/flood_impacts/README.md) · [Regional, CalWater, and relationship methods](../data/flood_impacts/METHODS.md) · [Source citations](../data/flood_impacts/SOURCES.md) |
| Statewide USGS current water data | [Inventory, current-only retention and refresh](../data/usgs_water/README.md) · [Regional and CalWater relationships](../data/usgs_water/METHODS.md) · [Statewide downstream and tributary network](../data/usgs_water/ROUTING_METHODS.md) · [Local operating-agency review methods](../data/usgs_water/LOCAL_REVIEW_METHODS.md) · [Source citations](../data/usgs_water/SOURCES.md) |
| Additional station-link evidence and uncertainty | [Link-review methods](../data/usgs_water/LINK_REVIEW_METHODS.md) · [Original-agency review](../data/usgs_water/AGENCY_REVIEW_METHODS.md) · [Additional agency records](../data/usgs_water/ADDITIONAL_AGENCY_REVIEW.md) · [Access retries](../data/usgs_water/SOURCE_ACCESS_REVIEW.md) · [Source-rule audits](../data/usgs_water/SOURCE_RULE_AUDIT.md) |
| Satellite radio catalog and orbital tools | [Program usage, sources, status rules, and limitations](../satellite_database/README.md) · [Function reference](../satellite_database/FUNCTION_REFERENCE.md) · [Database and exports](../data/satellites/README.md) |

California State Parks and satellite resources are separate reference tools. Their
presence does not register additional MeshCore commands. Supplier receipts and
versioned distributions preserve historical evidence; maintained guides describe
the source tree and identify snapshot-specific results where applicable.
