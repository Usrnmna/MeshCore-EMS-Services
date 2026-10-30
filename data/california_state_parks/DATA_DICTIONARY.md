# California State Parks field dictionary

Dataset file paths below are relative to the selected California State Parks
collection. They require its reference data in a source checkout or the
[independent data package](../../docs/DATA_PACKAGES.md); the documentation
bundle itself does not contain those data files.

Fields below are copied from the downloaded ArcGIS layer schemas. Coded-value and subtype definitions remain authoritative in each layer JSON. Property names and values are preserved in GeoJSON; no inferred policy fields are added.

## Park boundaries

Schema: `metadata/park_boundaries/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| FID | FID | esriFieldTypeOID |  |
| UNITNAME | UNITNAME | esriFieldTypeString |  |
| GISID | GISID | esriFieldTypeString |  |
| SUBTYPE | SUBTYPE | esriFieldTypeString |  |
| UNITNBR | UNITNBR | esriFieldTypeString |  |
| Shape__Area | Shape__Area | esriFieldTypeDouble |  |
| Shape__Length | Shape__Length | esriFieldTypeDouble |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |

## Recreational routes

Schema: `metadata/routes/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| FID | FID | esriFieldTypeOID |  |
| ROUTENAME | ROUTENAME | esriFieldTypeString |  |
| GISID | GISID | esriFieldTypeString |  |
| ROUTECLASS | ROUTECLASS | esriFieldTypeString |  |
| UNITNBR | UNITNBR | esriFieldTypeString |  |
| UNITNAME | UNITNAME | esriFieldTypeString |  |
| ROUTECAT | ROUTECAT | esriFieldTypeString |  |
| ROUTETYPE | ROUTETYPE | esriFieldTypeString |  |
| SEGLNGTH | SEGLNGTH | esriFieldTypeInteger |  |
| SHARE | SHARE | esriFieldTypeString |  |
| Shape_Leng | Shape_Leng | esriFieldTypeDouble |  |
| Shape__Length | Shape__Length | esriFieldTypeDouble |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |
| ROUTEDES | ROUTEDES | esriFieldTypeString |  |
| TRAILDES | TRAILDES | esriFieldTypeString |  |

## Buildings

Schema: `metadata/buildings/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| FID | FID | esriFieldTypeOID |  |
| GISID | GISID | esriFieldTypeString |  |
| DETAIL | DETAIL | esriFieldTypeString |  |
| TYPE | TYPE | esriFieldTypeString |  |
| SUBCLASS | SUBCLASS | esriFieldTypeString |  |
| UNITNBR | UNITNBR | esriFieldTypeString |  |
| UNITNAME | UNITNAME | esriFieldTypeString |  |
| SHARE | SHARE | esriFieldTypeString |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |

## Structures

Schema: `metadata/structures/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| FID | FID | esriFieldTypeOID |  |
| GISID | GISID | esriFieldTypeString |  |
| DETAIL | DETAIL | esriFieldTypeString |  |
| UNITNAME | UNITNAME | esriFieldTypeString |  |
| TYPE | TYPE | esriFieldTypeString |  |
| SUBCLASS | SUBCLASS | esriFieldTypeString |  |
| UNITNBR | UNITNBR | esriFieldTypeString |  |
| SHARE | SHARE | esriFieldTypeString |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |

## Picnic grounds / day-use areas

Schema: `metadata/picnic_grounds/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| FID | FID | esriFieldTypeOID |  |
| GISID | GISID | esriFieldTypeString |  |
| DETAIL | DETAIL | esriFieldTypeString |  |
| TYPE | TYPE | esriFieldTypeString |  |
| SUBCLASS | SUBCLASS | esriFieldTypeString |  |
| UNITNBR | UNITNBR | esriFieldTypeString |  |
| UNITNAME | UNITNAME | esriFieldTypeString |  |
| SHARE | SHARE | esriFieldTypeString |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |

## Campgrounds

Schema: `metadata/campgrounds/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| FID | FID | esriFieldTypeOID |  |
| Campground | Campground | esriFieldTypeString |  |
| GISID | GISID | esriFieldTypeString |  |
| TYPE | TYPE | esriFieldTypeString |  |
| SUBTYPE | SUBTYPE | esriFieldTypeString |  |
| UNITNBR | UNITNBR | esriFieldTypeString |  |
| DETAIL | DETAIL | esriFieldTypeString |  |
| UNITNAME | UNITNAME | esriFieldTypeString |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |
| WHAT3WORD_ADDRESS | WHAT3WORD_ADDRESS | esriFieldTypeString |  |

## Parking

Schema: `metadata/parking/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| FID | FID | esriFieldTypeOID |  |
| NAME | NAME | esriFieldTypeString |  |
| GISID | GISID | esriFieldTypeString |  |
| TYPE | TYPE | esriFieldTypeString |  |
| SUBTYPE | SUBTYPE | esriFieldTypeString |  |
| UNITNBR | UNITNBR | esriFieldTypeString |  |
| USETYPE | USETYPE | esriFieldTypeString |  |
| UNITNAME | UNITNAME | esriFieldTypeString |  |
| TRAILHEAD | TRAILHEAD | esriFieldTypeString |  |
| SHARE | SHARE | esriFieldTypeString |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |

## Park entry points

Schema: `metadata/park_entry_points/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| OBJECTID | OBJECTID | esriFieldTypeOID |  |
| PARK_NAME | parkName | esriFieldTypeString |  |
| County | County | esriFieldTypeString |  |
| STREET_ADDRESS | StreetAdr | esriFieldTypeString |  |
| City | City | esriFieldTypeString |  |
| Zip | Zip | esriFieldTypeDouble |  |
| LAT | LAT | esriFieldTypeDouble |  |
| LON | LON | esriFieldTypeDouble |  |
| PARK_WEB_PG | ParkWebPg | esriFieldTypeString |  |
| MAP_TYPE_1 | mapType1 | esriFieldTypeString |  |
| MAP_LINK_1 | mapLink1 | esriFieldTypeString |  |
| MAP_TYPE_2 | mapType2 | esriFieldTypeString |  |
| MAP_LINK_2 | mapLink2 | esriFieldTypeString |  |
| UNIT_NBR | UnitNum | esriFieldTypeString |  |
| MGMT_STATUS | MgmtStat | esriFieldTypeString |  |
| GIS_Acres | GIS_Acres | esriFieldTypeDouble |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |
| GISID | GISID | esriFieldTypeString |  |
| WHAT3WORD_ADDRESS | WHAT3WORD_ADDRESS | esriFieldTypeString |  |

## Field divisions

Schema: `metadata/field_divisions/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| OBJECTID | OBJECTID | esriFieldTypeOID |  |
| field_division | Field Divison | esriFieldTypeString |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |
| created_user | created_user | esriFieldTypeString |  |
| created_date | created_date | esriFieldTypeDate |  |
| last_edited_user | last_edited_user | esriFieldTypeString |  |
| last_edited_date | last_edited_date | esriFieldTypeDate |  |
| Shape__Area | Shape__Area | esriFieldTypeDouble |  |
| Shape__Length | Shape__Length | esriFieldTypeDouble |  |

## Districts

Schema: `metadata/districts/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| OBJECTID | OBJECTID | esriFieldTypeOID |  |
| field_division | Field Divison | esriFieldTypeString |  |
| district | District | esriFieldTypeString |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |
| created_user | created_user | esriFieldTypeString |  |
| created_date | created_date | esriFieldTypeDate |  |
| last_edited_user | last_edited_user | esriFieldTypeString |  |
| last_edited_date | last_edited_date | esriFieldTypeDate |  |
| Shape__Area | Shape__Area | esriFieldTypeDouble |  |
| Shape__Length | Shape__Length | esriFieldTypeDouble |  |

## Sectors

Schema: `metadata/sectors/layer.json`

| Field | Alias | ArcGIS type | Domain |
| --- | --- | --- | --- |
| OBJECTID | OBJECTID | esriFieldTypeOID |  |
| field_division | Field Divison | esriFieldTypeString |  |
| district | District | esriFieldTypeString |  |
| sector | Sector | esriFieldTypeString |  |
| GlobalID | GlobalID | esriFieldTypeGlobalID |  |
| created_user | created_user | esriFieldTypeString |  |
| created_date | created_date | esriFieldTypeDate |  |
| last_edited_user | last_edited_user | esriFieldTypeString |  |
| last_edited_date | last_edited_date | esriFieldTypeDate |  |
| Shape__Area | Shape__Area | esriFieldTypeDouble |  |
| Shape__Length | Shape__Length | esriFieldTypeDouble |  |
