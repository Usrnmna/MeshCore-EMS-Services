# California State Parks field dictionary

Fields below are copied from the downloaded ArcGIS layer schemas. Coded-value and subtype definitions remain authoritative in each layer JSON. Property names and values are preserved in GeoJSON; no inferred policy fields are added.

## Park boundaries

Schema: [`park_boundaries/layer.json`](metadata/park_boundaries/layer.json)

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

Schema: [`routes/layer.json`](metadata/routes/layer.json)

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

Schema: [`buildings/layer.json`](metadata/buildings/layer.json)

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

Schema: [`structures/layer.json`](metadata/structures/layer.json)

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

Schema: [`picnic_grounds/layer.json`](metadata/picnic_grounds/layer.json)

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

Schema: [`campgrounds/layer.json`](metadata/campgrounds/layer.json)

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

Schema: [`parking/layer.json`](metadata/parking/layer.json)

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

Schema: [`park_entry_points/layer.json`](metadata/park_entry_points/layer.json)

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

Schema: [`field_divisions/layer.json`](metadata/field_divisions/layer.json)

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

Schema: [`districts/layer.json`](metadata/districts/layer.json)

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

Schema: [`sectors/layer.json`](metadata/sectors/layer.json)

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
