# MeshCore command and subcommand response examples

These offline examples use synthetic provider records, bundled catalog references, fixed timestamps, and the actual command formatters. They are not current conditions or evidence of radio delivery. Each code block is one complete tagged message; byte counts include `@Alice `. Longer sender tags reduce optional fields.

All 31 registered commands, every GIS field and boundary category, all twelve firedata categories, closest/radius searches, available help forms, subscription controls, and representative triggered notices are included. Each scenario is independent; repeated status/stop examples belong to the immediately preceding enrollment. Trigger headings describe events rather than additional command syntax.

There are no details or paging routes. Focused fields and new lookups are independent requests. The [command reference](COMMAND_REFERENCE.md#subcommand-index) explains syntax; the [response policy and review inventory](RESPONSE_FORMATTING.md) records fields that may not fit. Source/coverage limitations and full structured data are described in the [water](WATER_GUIDE.md), [wildfire](WILDFIRE_GUIDE.md), and [landslide](LANDSLIDE_GUIDE.md) guides.

## Example groups

| Topic | Examples |
| --- | ---: |
| [General](#example-group-1) | 4 |
| [Air, roads and rivers](#example-group-2) | 9 |
| [Weather](#example-group-3) | 12 |
| [Water](#example-group-4) | 12 |
| [Wildfire](#example-group-5) | 24 |
| [Firedata](#example-group-6) | 36 |
| [Landslide](#example-group-7) | 9 |
| [Monitoring](#example-group-8) | 36 |
| [GIS main and near](#example-group-9) | 20 |
| [GIS trail fields](#example-group-10) | 39 |
| [GIS rec fields](#example-group-11) | 36 |
| [GIS peak fields](#example-group-12) | 9 |
| [GIS park fields](#example-group-13) | 15 |
| [Boundary categories](#example-group-14) | 16 |
| [Help](#example-group-15) | 23 |
| [Triggered subscription notifications](#example-group-16) | 9 |

<a id="example-group-1"></a>
<a id="main-commands"></a>
## General

<a id="example-status"></a>
### !status

40 UTF-8 bytes.

```text
@Alice Local command service is running.
```

<a id="example-time"></a>
### !time

44 UTF-8 bytes.

```text
@Alice Current time: 2026-10-21 12:00:00 PDT
```

### !time

44 UTF-8 bytes.

```text
@Alice Current time: 2026-10-21 13:00:00 PDT
```

### !time

44 UTF-8 bytes.

```text
@Alice Current time: 2026-10-21 14:00:00 PDT
```


<a id="example-group-2"></a>
## Air, roads and rivers

<a id="example-aqi"></a>
### !aqi 38.58 -121.49

93 UTF-8 bytes.

```text
@Alice AQI 42 Good; preliminary. | PM2.5 8.2 ug/m3 | 2026-10-21 11:00 PDT | Oak Monitor 1.2km
```

<a id="example-traffic"></a>
### !traffic 80

107 UTF-8 bytes.

```text
@Alice Route 80: closures reported. Chain controls. | Closed at Oak Pass. | roads.dot.ca.gov; times Pacific
```

<a id="example-rivers"></a>
### !rivers 38.58 -121.49

124 UTF-8 bytes.

```text
@Alice OAK: 21ft; flood threshold; point flooding unknown. | 2026-10-21 11:00 PDT | AS 15ft; FS 20ft | 1 station | Oak River
```

### !aqi 39.33,-120.18

99 UTF-8 bytes.

```text
@Alice AQI 75 Moderate; preliminary. | PM2.5 22.1 ug/m3 | 2026-10-21 11:00 PDT | Pine Monitor 2.2km
```

### !traffic 50

147 UTF-8 bytes.

```text
@Alice Route 50: restrictions reported. Chain controls. | Chains required from A to B except 4WD with snow tires. | roads.dot.ca.gov; times Pacific
```

### !rivers 39.33,-120.18

127 UTF-8 bytes.

```text
@Alice PINE: 16ft; action threshold; point flooding unknown. | 2026-10-21 11:00 PDT | AS 15ft; FS 20ft | 1 station | Pine River
```

### !aqi 39.53, -119.81

102 UTF-8 bytes.

```text
@Alice AQI 118 Sensitive; preliminary. | PM2.5 42.5 ug/m3 | 2026-10-21 11:00 PDT | Creek Monitor 3.2km
```

### !traffic 1

107 UTF-8 bytes.

```text
@Alice Route 1: restrictions reported. | One-way traffic at Creek Bridge. | roads.dot.ca.gov; times Pacific
```

### !rivers 39.53, -119.81

115 UTF-8 bytes.

```text
@Alice CRK: 8ft; gauge; point flooding unknown. | 2026-10-21 11:00 PDT | AS 15ft; FS 20ft | 1 station | Creek River
```


<a id="example-group-3"></a>
## Weather

<a id="example-uv"></a>
### !uv Sacramento CA

25 UTF-8 bytes.

```text
@Alice UV Index: 6.5 High
```

<a id="example-heatadv"></a>
### !heatadv Sacramento CA

64 UTF-8 bytes.

```text
@Alice NWS Extreme Heat Warning. | Heat Advisory | Sacramento CA
```

<a id="example-snowpack"></a>
### !snowpack Sacramento CA

78 UTF-8 bytes.

```text
@Alice Snow depth at station: 12in. | Next 24h snow: 4in | Snow & Creek 85.3mi
```

<a id="example-lightning"></a>
### !lightning Sacramento CA

116 UTF-8 bytes.

```text
@Alice NWS: slight chance thunderstorms (24h). | Oct 08 05:00 PDT-Oct 09 05:00 PDT | 1 hazard window | Sacramento CA
```

### !uv 96161

29 UTF-8 bytes.

```text
@Alice UV Index: 3.2 Moderate
```

### !heatadv 96161

33 UTF-8 bytes.

```text
@Alice NWS Heat Advisory. | 96161
```

### !snowpack 96161

78 UTF-8 bytes.

```text
@Alice Snow depth at station: 24in. | Next 24h snow: 8in | Snow & Creek 24.8mi
```

### !lightning 96161

101 UTF-8 bytes.

```text
@Alice NWS: chance thunderstorms (24h). | Oct 08 05:00 PDT-Oct 09 05:00 PDT | 1 hazard window | 96161
```

### !uv 39.53,-119.81

30 UTF-8 bytes.

```text
@Alice UV Index: 8.1 Very-High
```

### !heatadv 39.53,-119.81

46 UTF-8 bytes.

```text
@Alice NWS Extreme Heat Watch. | 39.53,-119.81
```

### !snowpack 39.53,-119.81

77 UTF-8 bytes.

```text
@Alice Snow depth at station: 6in. | Next 24h snow: 2in | Snow & Creek 38.0mi
```

### !lightning 39.53,-119.81

109 UTF-8 bytes.

```text
@Alice NWS: likely thunderstorms (24h). | Oct 08 05:00 PDT-Oct 09 05:00 PDT | 1 hazard window | 39.53,-119.81
```


<a id="example-group-4"></a>
## Water

<a id="example-floodwarn"></a>
### !floodwarn Sacramento CA

91 UTF-8 bytes.

```text
@Alice NWS FLASH FLOOD WARNING. Move to higher ground now. | Until 6 PM PDT | Sacramento CA
```

<a id="example-waterway"></a>
### !waterway Sacramento CA

68 UTF-8 bytes.

```text
@Alice Oak Creek 0.2mi; nearby only. | 1 reach found | Sacramento CA
```

<a id="example-basin"></a>
### !basin Sacramento CA

105 UTF-8 bytes.

```text
@Alice CalWater PW: Oak Watershed. | Basin boundary, not current flooding | 1 basin level | Sacramento CA
```

<a id="example-floodstatus"></a>
### !floodstatus Sacramento CA

122 UTF-8 bytes.

```text
@Alice Modeled inundation at point; not field-confirmed. | NWS: no flood alerts | Upstream gauges: minor=1 | Sacramento CA
```

### !floodwarn 96161

79 UTF-8 bytes.

```text
@Alice NWS FLOOD WARNING. Flooding imminent/occurring. | Until 6 PM PDT | 96161
```

### !waterway 96161

63 UTF-8 bytes.

```text
@Alice Pine Creek 0.3mi; nearby only. | 2 reaches found | 96161
```

### !basin 96161

98 UTF-8 bytes.

```text
@Alice CalWater PW: Pine Watershed. | Basin boundary, not current flooding | 1 basin level | 96161
```

### !floodstatus 96161

117 UTF-8 bytes.

```text
@Alice Modeled inundation at point; not field-confirmed. | NWS: no flood alerts | Upstream gauges: moderate=1 | 96161
```

### !floodwarn 39.53,-119.81

87 UTF-8 bytes.

```text
@Alice NWS Flood Watch. Flooding possible; stay alert. | Until 6 PM PDT | 39.53,-119.81
```

### !waterway 39.53,-119.81

73 UTF-8 bytes.

```text
@Alice Willow Creek 0.4mi; nearby only. | 3 reaches found | 39.53,-119.81
```

### !basin 39.53,-119.81

107 UTF-8 bytes.

```text
@Alice CalWater PW: Creek Watershed. | Basin boundary, not current flooding | 1 basin level | 39.53,-119.81
```

### !floodstatus 39.53,-119.81

122 UTF-8 bytes.

```text
@Alice Modeled inundation at point; not field-confirmed. | NWS: no flood alerts | Upstream gauges: major=1 | 39.53,-119.81
```


<a id="example-group-5"></a>
## Wildfire

<a id="example-firezone"></a>
### !firezone CAZ272

46 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning. | Tahoe Test Zone
```

<a id="example-firewarn"></a>
### !firewarn CAZ272

62 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning. | Until Oct 21 18:00 PDT | CAZ272
```

<a id="example-fires"></a>
### !fires CAZ272

77 UTF-8 bytes.

```text
@Alice Oak Fire: contained 35%. | 120 ac | 1 incident record | OAK-1 | CAZ272
```

<a id="example-fire"></a>
### !fire OAK-1

77 UTF-8 bytes.

```text
@Alice Oak Fire: contained 35%. | 120 ac | 1 incident record | OAK-1 | CAZ272
```

<a id="example-firewx"></a>
### !firewx CAZ272

103 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning. | Tonight | Min humidity: 15 percent. | Winds (20 ft): SW 10 mph. | CAZ272
```

### !fires near Truckee CA within 10

92 UTF-8 bytes.

```text
@Alice Oak Fire: contained 35%. | 0.50 mi map distance | 120 ac | 1 incident record | CAZ272
```

<a id="example-smoke"></a>
### !smoke Sacramento CA

126 UTF-8 bytes.

```text
@Alice Smoke: light mapped plume; surface exposure may differ. | PM2.5 AQI 42 Good | Oct 21 11:00 PDT | Origin not established
```

<a id="example-firedanger"></a>
### !firedanger Sacramento CA

104 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning. ERC excludes wind. | ERC 30, percentile 70 | Oct 21 11:00 PDT | Oak Station
```

### !firezone 96161

48 UTF-8 bytes.

```text
@Alice NWS Fire Weather Watch. | Tahoe Test Zone
```

### !firewarn 96161

64 UTF-8 bytes.

```text
@Alice NWS Fire Weather Watch. | Until Oct 21 18:00 PDT | CAZ272
```

### !fires 96161

79 UTF-8 bytes.

```text
@Alice Pine Fire: contained 60%. | 240 ac | 1 incident record | PINE-1 | CAZ272
```

### !fire Pine Fire

79 UTF-8 bytes.

```text
@Alice Pine Fire: contained 60%. | 240 ac | 1 incident record | PINE-1 | CAZ272
```

### !firewx 96161

105 UTF-8 bytes.

```text
@Alice NWS Fire Weather Watch. | Tonight | Min humidity: 15 percent. | Winds (20 ft): SW 10 mph. | CAZ272
```

### !fires near 96161 within 5

93 UTF-8 bytes.

```text
@Alice Pine Fire: contained 60%. | 1.00 mi map distance | 240 ac | 1 incident record | CAZ272
```

### !smoke 96161

131 UTF-8 bytes.

```text
@Alice Smoke: medium mapped plume; surface exposure may differ. | PM2.5 AQI 75 Moderate | Oct 21 11:00 PDT | Origin not established
```

### !firedanger 96161

107 UTF-8 bytes.

```text
@Alice NWS Fire Weather Watch. ERC excludes wind. | ERC 45, percentile 85 | Oct 21 11:00 PDT | Pine Station
```

### !firezone 39.53,-119.81

47 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning. | Nevada Test Zone
```

### !firewarn 39.53,-119.81

62 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning. | Until Oct 21 18:00 PDT | NVZ420
```

### !fires 39.53,-119.81

80 UTF-8 bytes.

```text
@Alice Creek Fire: contained 80%. | 80 ac | 1 incident record | CREEK-1 | NVZ420
```

### !fire {11111111-1111-4111-8111-111111111111}

80 UTF-8 bytes.

```text
@Alice Creek Fire: contained 80%. | 80 ac | 1 incident record | CREEK-1 | NVZ420
```

### !firewx 39.53,-119.81

103 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning. | Tonight | Min humidity: 15 percent. | Winds (20 ft): SW 10 mph. | NVZ420
```

### !fires near 39.53,-119.81 within 2

93 UTF-8 bytes.

```text
@Alice Creek Fire: contained 80%. | 1.50 mi map distance | 80 ac | 1 incident record | NVZ420
```

### !smoke 39.53,-119.81

128 UTF-8 bytes.

```text
@Alice Smoke: heavy mapped plume; surface exposure may differ. | PM2.5 AQI 118 Unhealthy for Sensitive Groups | Oct 21 11:00 PDT
```

### !firedanger 39.53,-119.81

106 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning. ERC excludes wind. | ERC 60, percentile 95 | Oct 21 11:00 PDT | Creek Station
```


<a id="example-group-6"></a>
## Firedata

<a id="example-firedata"></a>
### !firedata aqi CAZ272

79 UTF-8 bytes.

```text
@Alice 1 AQI observation. | Oak: PM2.5 AQI 42; valid Oct 21 11:00 PDT. | CAZ272
```

### !firedata aqi 96161

80 UTF-8 bytes.

```text
@Alice 1 AQI observation. | Pine: PM2.5 AQI 75; valid Oct 21 11:00 PDT. | CAZ272
```

### !firedata aqi Reno Nevada

82 UTF-8 bytes.

```text
@Alice 1 AQI observation. | Creek: PM2.5 AQI 118; valid Oct 21 11:00 PDT. | NVZ420
```

### !firedata aqi_today CAZ272

95 UTF-8 bytes.

```text
@Alice 1 AQI forecast for today. | Oak: max AQI 75 (Moderate); valid time unavailable. | CAZ272
```

### !firedata aqi_today 96161

96 UTF-8 bytes.

```text
@Alice 1 AQI forecast for today. | Pine: max AQI 85 (Moderate); valid time unavailable. | CAZ272
```

### !firedata aqi_today Reno Nevada

97 UTF-8 bytes.

```text
@Alice 1 AQI forecast for today. | Creek: max AQI 95 (Moderate); valid time unavailable. | NVZ420
```

### !firedata aqi_tomorrow CAZ272

98 UTF-8 bytes.

```text
@Alice 1 AQI forecast for tomorrow. | Oak: max AQI 60 (Moderate); valid time unavailable. | CAZ272
```

### !firedata aqi_tomorrow 96161

99 UTF-8 bytes.

```text
@Alice 1 AQI forecast for tomorrow. | Pine: max AQI 70 (Moderate); valid time unavailable. | CAZ272
```

### !firedata aqi_tomorrow Reno Nevada

100 UTF-8 bytes.

```text
@Alice 1 AQI forecast for tomorrow. | Creek: max AQI 80 (Moderate); valid time unavailable. | NVZ420
```

### !firedata cameras CAZ272

65 UTF-8 bytes.

```text
@Alice 1 camera. | Oak: online; https://example.com/cam1 | CAZ272
```

### !firedata cameras 96161

66 UTF-8 bytes.

```text
@Alice 1 camera. | Pine: online; https://example.com/cam2 | CAZ272
```

### !firedata cameras Reno Nevada

67 UTF-8 bytes.

```text
@Alice 1 camera. | Creek: online; https://example.com/cam3 | NVZ420
```

### !firedata history CAZ272

57 UTF-8 bytes.

```text
@Alice 1 historical fire. | Oak Fire; year: 2020 | CAZ272
```

### !firedata history 96161

58 UTF-8 bytes.

```text
@Alice 1 historical fire. | Pine Fire; year: 2021 | CAZ272
```

### !firedata history Reno Nevada

59 UTF-8 bytes.

```text
@Alice 1 historical fire. | Creek Fire; year: 2022 | NVZ420
```

### !firedata modis CAZ272

106 UTF-8 bytes.

```text
@Alice 1 MODIS detection. | Detected Oct 21 11:00 PDT; confidence 50; not a mapped fire boundary. | CAZ272
```

### !firedata modis 96161

106 UTF-8 bytes.

```text
@Alice 1 MODIS detection. | Detected Oct 21 11:00 PDT; confidence 70; not a mapped fire boundary. | CAZ272
```

### !firedata modis Reno Nevada

106 UTF-8 bytes.

```text
@Alice 1 MODIS detection. | Detected Oct 21 11:00 PDT; confidence 90; not a mapped fire boundary. | NVZ420
```

### !firedata potential CAZ272

141 UTF-8 bytes.

```text
@Alice 1 fire potential record. | Day 1, PSA N01: provider flag A; dryness code 2; provider validity flag Y; dated Oct 21 11:00 PDT. | CAZ272
```

### !firedata potential 96161

141 UTF-8 bytes.

```text
@Alice 1 fire potential record. | Day 1, PSA N01: provider flag A; dryness code 3; provider validity flag Y; dated Oct 21 11:00 PDT. | CAZ272
```

### !firedata potential Reno Nevada

141 UTF-8 bytes.

```text
@Alice 1 fire potential record. | Day 1, PSA N01: provider flag A; dryness code 4; provider validity flag Y; dated Oct 21 11:00 PDT. | NVZ420
```

### !firedata raws CAZ272

101 UTF-8 bytes.

```text
@Alice 1 RAWS observation. | Oak: RH 20%; wind 5 mph; gust 15 mph; observed Oct 21 11:00 PDT | CAZ272
```

### !firedata raws 96161

103 UTF-8 bytes.

```text
@Alice 1 RAWS observation. | Pine: RH 30%; wind 10 mph; gust 20 mph; observed Oct 21 11:00 PDT | CAZ272
```

### !firedata raws Reno Nevada

104 UTF-8 bytes.

```text
@Alice 1 RAWS observation. | Creek: RH 40%; wind 15 mph; gust 25 mph; observed Oct 21 11:00 PDT | NVZ420
```

### !firedata smoke CAZ272

86 UTF-8 bytes.

```text
@Alice 1 smoke forecast. | Light; valid Oct 21 11:00 PDT to Oct 21 18:00 PDT. | CAZ272
```

### !firedata smoke 96161

89 UTF-8 bytes.

```text
@Alice 1 smoke forecast. | Moderate; valid Oct 21 11:00 PDT to Oct 21 18:00 PDT. | CAZ272
```

### !firedata smoke Reno Nevada

86 UTF-8 bytes.

```text
@Alice 1 smoke forecast. | Heavy; valid Oct 21 11:00 PDT to Oct 21 18:00 PDT. | NVZ420
```

### !firedata spc CAZ272

48 UTF-8 bytes.

```text
@Alice 1 SPC outlook. | Day 1; Elevated | CAZ272
```

### !firedata spc 96161

48 UTF-8 bytes.

```text
@Alice 1 SPC outlook. | Day 1; Critical | CAZ272
```

### !firedata spc Reno Nevada

48 UTF-8 bytes.

```text
@Alice 1 SPC outlook. | Day 1; Elevated | NVZ420
```

### !firedata treatments CAZ272

77 UTF-8 bytes.

```text
@Alice 1 fuel treatment. | Oak Unit; treatment: Thinning; year: 2024 | CAZ272
```

### !firedata treatments 96161

78 UTF-8 bytes.

```text
@Alice 1 fuel treatment. | Pine Unit; treatment: Thinning; year: 2025 | CAZ272
```

### !firedata treatments Reno Nevada

79 UTF-8 bytes.

```text
@Alice 1 fuel treatment. | Creek Unit; treatment: Thinning; year: 2026 | NVZ420
```

### !firedata viirs CAZ272

107 UTF-8 bytes.

```text
@Alice 1 VIIRS detection. | Detected Oct 21 11:00 PDT; confidence low; not a mapped fire boundary. | CAZ272
```

### !firedata viirs 96161

111 UTF-8 bytes.

```text
@Alice 1 VIIRS detection. | Detected Oct 21 11:00 PDT; confidence nominal; not a mapped fire boundary. | CAZ272
```

### !firedata viirs Reno Nevada

108 UTF-8 bytes.

```text
@Alice 1 VIIRS detection. | Detected Oct 21 11:00 PDT; confidence high; not a mapped fire boundary. | NVZ420
```


<a id="example-group-7"></a>
## Landslide

<a id="example-slidewarn"></a>
### !slidewarn Pasadena CA

93 UTF-8 bytes.

```text
@Alice NWS Flash Flood Warning; landslide mention. | Until 2026-10-20 07:40 PDT | Pasadena CA
```

<a id="example-slideinfo"></a>
### !slideinfo Pasadena CA

75 UTF-8 bytes.

```text
@Alice OAK: telemetry unverified; not local coverage. | 4.9mi | Oak Station
```

### !slideinfo near Pasadena CA

75 UTF-8 bytes.

```text
@Alice OAK: telemetry unverified; not local coverage. | 4.9mi | Oak Station
```

### !slidewarn 89501-1234

86 UTF-8 bytes.

```text
@Alice NWS Flood Warning; landslide mention. | Until 2026-10-20 07:40 PDT | 89501-1234
```

### !slideinfo 89501-1234

77 UTF-8 bytes.

```text
@Alice PINE: telemetry unverified; not local coverage. | 5.9mi | Pine Station
```

### !slideinfo near 89501-1234

77 UTF-8 bytes.

```text
@Alice PINE: telemetry unverified; not local coverage. | 5.9mi | Pine Station
```

### !slidewarn 34.15,-118.14

87 UTF-8 bytes.

```text
@Alice NWS Flood Watch; landslide mention. | Until 2026-10-20 07:40 PDT | 34.15,-118.14
```

### !slideinfo 34.15,-118.14

79 UTF-8 bytes.

```text
@Alice CREEK: telemetry unverified; not local coverage. | 6.9mi | Creek Station
```

### !slideinfo near 34.15,-118.14

79 UTF-8 bytes.

```text
@Alice CREEK: telemetry unverified; not local coverage. | 6.9mi | Creek Station
```


<a id="example-group-8"></a>
## Monitoring

<a id="example-floodalarm"></a>
### !floodalarm Sacramento CA

81 UTF-8 bytes.

```text
@Alice Flood monitoring set; 4h. Stop: !floodalarm stop. | Sacramento CA | alerts
```

### !floodalarm status

68 UTF-8 bytes.

```text
@Alice Flood monitoring active. | 240m left | alerts | Sacramento CA
```

### !floodalarm stop

32 UTF-8 bytes.

```text
@Alice Flood monitoring stopped.
```

### !floodalarm conditions Sacramento CA

85 UTF-8 bytes.

```text
@Alice Flood monitoring set; 4h. Stop: !floodalarm stop. | Sacramento CA | conditions
```

### !floodalarm status

72 UTF-8 bytes.

```text
@Alice Flood monitoring active. | 240m left | conditions | Sacramento CA
```

### !floodalarm stop

32 UTF-8 bytes.

```text
@Alice Flood monitoring stopped.
```

<a id="example-firealarm"></a>
### !firealarm on CAZ272

106 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning; monitoring set. | 4h; stop: !firealarm off | CAZ272 | 1 incident; 1 NWS alert
```

### !firealarm status

55 UTF-8 bytes.

```text
@Alice Wildfire monitoring active. | 240m left | CAZ272
```

### !firealarm off

35 UTF-8 bytes.

```text
@Alice Wildfire monitoring stopped.
```

<a id="example-slidealarm"></a>
### !slidealarm on Pasadena CA

94 UTF-8 bytes.

```text
@Alice NWS Flash Flood Warning; landslide mention. | Monitoring set 4h | Stop: !slidealarm off
```

### !slidealarm status

61 UTF-8 bytes.

```text
@Alice Landslide monitoring active. | 240m left | Pasadena CA
```

### !slidealarm off

36 UTF-8 bytes.

```text
@Alice Landslide monitoring stopped.
```

### !floodalarm 96161

73 UTF-8 bytes.

```text
@Alice Flood monitoring set; 4h. Stop: !floodalarm stop. | 96161 | alerts
```

### !floodalarm status

60 UTF-8 bytes.

```text
@Alice Flood monitoring active. | 240m left | alerts | 96161
```

### !floodalarm stop

32 UTF-8 bytes.

```text
@Alice Flood monitoring stopped.
```

### !floodalarm conditions 96161

77 UTF-8 bytes.

```text
@Alice Flood monitoring set; 4h. Stop: !floodalarm stop. | 96161 | conditions
```

### !floodalarm status

64 UTF-8 bytes.

```text
@Alice Flood monitoring active. | 240m left | conditions | 96161
```

### !floodalarm stop

32 UTF-8 bytes.

```text
@Alice Flood monitoring stopped.
```

### !firealarm on 96161

106 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning; monitoring set. | 4h; stop: !firealarm off | CAZ272 | 1 incident; 1 NWS alert
```

### !firealarm status

55 UTF-8 bytes.

```text
@Alice Wildfire monitoring active. | 240m left | CAZ272
```

### !firealarm off

35 UTF-8 bytes.

```text
@Alice Wildfire monitoring stopped.
```

### !slidealarm on 91107

94 UTF-8 bytes.

```text
@Alice NWS Flash Flood Warning; landslide mention. | Monitoring set 4h | Stop: !slidealarm off
```

### !slidealarm status

55 UTF-8 bytes.

```text
@Alice Landslide monitoring active. | 240m left | 91107
```

### !slidealarm off

36 UTF-8 bytes.

```text
@Alice Landslide monitoring stopped.
```

### !floodalarm 39.53,-119.81

81 UTF-8 bytes.

```text
@Alice Flood monitoring set; 4h. Stop: !floodalarm stop. | 39.53,-119.81 | alerts
```

### !floodalarm status

68 UTF-8 bytes.

```text
@Alice Flood monitoring active. | 240m left | alerts | 39.53,-119.81
```

### !floodalarm stop

32 UTF-8 bytes.

```text
@Alice Flood monitoring stopped.
```

### !floodalarm conditions 39.53,-119.81

85 UTF-8 bytes.

```text
@Alice Flood monitoring set; 4h. Stop: !floodalarm stop. | 39.53,-119.81 | conditions
```

### !floodalarm status

72 UTF-8 bytes.

```text
@Alice Flood monitoring active. | 240m left | conditions | 39.53,-119.81
```

### !floodalarm stop

32 UTF-8 bytes.

```text
@Alice Flood monitoring stopped.
```

### !firealarm on Reno NV

106 UTF-8 bytes.

```text
@Alice NWS Red Flag Warning; monitoring set. | 4h; stop: !firealarm off | NVZ420 | 1 incident; 1 NWS alert
```

### !firealarm status

55 UTF-8 bytes.

```text
@Alice Wildfire monitoring active. | 240m left | NVZ420
```

### !firealarm off

35 UTF-8 bytes.

```text
@Alice Wildfire monitoring stopped.
```

### !slidealarm on 34.15,-118.14

94 UTF-8 bytes.

```text
@Alice NWS Flash Flood Warning; landslide mention. | Monitoring set 4h | Stop: !slidealarm off
```

### !slidealarm status

63 UTF-8 bytes.

```text
@Alice Landslide monitoring active. | 240m left | 34.15,-118.14
```

### !slidealarm off

36 UTF-8 bytes.

```text
@Alice Landslide monitoring stopped.
```


<a id="example-group-9"></a>
<a id="near-subcommands"></a>
## GIS main and near

<a id="example-trail"></a>
### !trail Oak Loop

23 UTF-8 bytes.

```text
@Alice Trail: Oak Loop.
```

### !trail 37.9,-122.2

54 UTF-8 bytes.

```text
@Alice Nearest trail: Oak Loop (0.00 mi map distance).
```

### !trail near 37.9105 -122.1895

56 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance).
```

### !trail near 37.9205,-122.1795 0.25

64 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance).
```

<a id="example-rec"></a>
### !rec Oak Gate

28 UTF-8 bytes.

```text
@Alice Recreation: Oak Gate.
```

### !rec 37.9,-122.2

59 UTF-8 bytes.

```text
@Alice Nearest recreation: Oak Gate (0.00 mi map distance).
```

### !rec near 37.9105 -122.1895

60 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance).
```

### !rec near 37.9205,-122.1795 0.25

68 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance).
```

<a id="example-peak"></a>
### !peak Oak Peak

22 UTF-8 bytes.

```text
@Alice Peak: Oak Peak.
```

### !peak 37.9,-122.2

53 UTF-8 bytes.

```text
@Alice Nearest peak: Oak Peak (0.00 mi map distance).
```

### !peak near 37.9105 -122.1895

54 UTF-8 bytes.

```text
@Alice Nearest peak: Pine Peak (0.04 mi map distance).
```

### !peak near 37.9205,-122.1795 0.25

63 UTF-8 bytes.

```text
@Alice Peaks within 0.25 mi: Creek Peak (0.04 mi map distance).
```

<a id="example-park"></a>
### !park Oak Park

22 UTF-8 bytes.

```text
@Alice Park: Oak Park.
```

### !park 37.9,-122.2

53 UTF-8 bytes.

```text
@Alice Nearest park: Oak Park (0.00 mi map distance).
```

### !park near 37.9105 -122.1895

54 UTF-8 bytes.

```text
@Alice Nearest park: Pine Park (0.00 mi map distance).
```

### !park near 37.9205,-122.1795 0.25

103 UTF-8 bytes.

```text
@Alice Parks within 0.25 mi: Creek Park (0.00 mi map distance) | Creek Rec Area (0.00 mi map distance).
```

<a id="example-boundary"></a>
### !boundary 37.9 -122.2

116 UTF-8 bytes.

```text
@Alice Inside mapped watershed: Oak Basin | Inside mapped reservoir: Oak Lake | Inside mapped park: Oak Park [Open].
```

### !boundary near 37.9105,-122.1895

60 UTF-8 bytes.

```text
@Alice Nearest watershed: Pine Basin (0.00 mi map distance).
```

### !boundary near 37.9205 -122.1795 0.25

123 UTF-8 bytes.

```text
@Alice Areas within 0.25 mi: Creek Basin [Watershed] (0.00 mi map distance) | Creek Lake [Reservoir] (0.00 mi map distance)
```

### !boundary trail Oak Loop

90 UTF-8 bytes.

```text
@Alice Trail overlaps: Watershed: Oak Basin | Reservoir: Oak Lake | Park: Oak Park [Open].
```


<a id="example-group-10"></a>
## GIS trail fields

### !trail Oak Loop dogs

26 UTF-8 bytes.

```text
@Alice Oak Loop: dogs Yes.
```

### !trail dogs near 37.9105 -122.1895

67 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | dogs Yes.
```

### !trail dogs near 37.9205,-122.1795 0.25

75 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | dogs Yes.
```

### !trail Oak Loop horses

28 UTF-8 bytes.

```text
@Alice Oak Loop: horses Yes.
```

### !trail horses near 37.9105 -122.1895

69 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | horses Yes.
```

### !trail horses near 37.9205,-122.1795 0.25

77 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | horses Yes.
```

### !trail Oak Loop bikes

27 UTF-8 bytes.

```text
@Alice Oak Loop: bikes Yes.
```

### !trail bikes near 37.9105 -122.1895

68 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | bikes Yes.
```

### !trail bikes near 37.9205,-122.1795 0.25

76 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | bikes Yes.
```

### !trail Oak Loop length

29 UTF-8 bytes.

```text
@Alice Oak Loop: length 2 mi.
```

### !trail length near 37.9105 -122.1895

70 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | length 3 mi.
```

### !trail length near 37.9205,-122.1795 0.25

78 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | length 4 mi.
```

### !trail Oak Loop difficulty

33 UTF-8 bytes.

```text
@Alice Oak Loop: difficulty Easy.
```

### !trail difficulty near 37.9105 -122.1895

78 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | difficulty Moderate.
```

### !trail difficulty near 37.9205,-122.1795 0.25

87 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | difficulty Strenuous.
```

### !trail Oak Loop gain

29 UTF-8 bytes.

```text
@Alice Oak Loop: gain 100 ft.
```

### !trail gain near 37.9105 -122.1895

70 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | gain 200 ft.
```

### !trail gain near 37.9205,-122.1795 0.25

78 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | gain 300 ft.
```

### !trail Oak Loop surface

30 UTF-8 bytes.

```text
@Alice Oak Loop: surface Dirt.
```

### !trail surface near 37.9105 -122.1895

71 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | surface Dirt.
```

### !trail surface near 37.9205,-122.1795 0.25

79 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | surface Dirt.
```

### !trail Oak Loop shade

29 UTF-8 bytes.

```text
@Alice Oak Loop: shade Shade.
```

### !trail shade near 37.9105 -122.1895

70 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | shade Mixed.
```

### !trail shade near 37.9205,-122.1795 0.25

76 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | shade Sun.
```

### !trail Oak Loop time

65 UTF-8 bytes.

```text
@Alice Oak Loop: estimated time 0.5 hr (3 mph; terrain excluded).
```

### !trail time near 37.9105 -122.1895

104 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | estimated time 1 hr (3 mph; terrain excluded).
```

### !trail time near 37.9205,-122.1795 0.25

114 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | estimated time 1.5 hr (3 mph; terrain excluded).
```

### !trail Oak Loop start

50 UTF-8 bytes.

```text
@Alice Oak Loop: mapped start 37.90000,-122.20000.
```

### !trail start near 37.9105 -122.1895

91 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | mapped start 37.91000,-122.19000.
```

### !trail start near 37.9205,-122.1795 0.25

99 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | mapped start 37.92000,-122.18000.
```

### !trail Oak Loop areas

93 UTF-8 bytes.

```text
@Alice Oak Loop: overlaps Watershed: Oak Basin | Reservoir: Oak Lake | Park: Oak Park [Open].
```

### !trail areas near 37.9105 -122.1895

141 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | overlaps Watershed: Pine Basin | Reservoir: Pine Lake | Park: Pine Park [Landbank].
```

### !trail areas near 37.9205,-122.1795 0.25

148 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | overlaps Watershed: Creek Basin | Reservoir: Creek Lake | Park: Creek Park [Open].
```

### !trail Oak Loop description

47 UTF-8 bytes.

```text
@Alice Oak Loop: description Oak woodland loop.
```

### !trail description near 37.9105 -122.1895

87 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | description Pine ridge views.
```

### !trail description near 37.9205,-122.1795 0.25

93 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | description Creekside path.
```

### !trail Oak Loop info

146 UTF-8 bytes.

```text
@Alice Trail: Oak Loop | 2 mi | Easy | gain 100 ft | surface Dirt | sun Shade | dogs Yes | horses Yes | bikes Yes | overlaps: Watershed: Oak Basin
```

### !trail info near 37.9105 -122.1895

150 UTF-8 bytes.

```text
@Alice Nearest trail: Pine Ridge (0.03 mi map distance) | 3 mi | Moderate | gain 200 ft | surface Dirt | sun Mixed | dogs Yes | horses Yes | bikes Yes
```

### !trail info near 37.9205,-122.1795 0.25

145 UTF-8 bytes.

```text
@Alice Trails within 0.25 mi: Creek Path (0.03 mi map distance) | 4 mi | Strenuous | gain 300 ft | surface Dirt | sun Sun | dogs Yes | horses Yes
```


<a id="example-group-11"></a>
## GIS rec fields

### !rec Oak Gate type

35 UTF-8 bytes.

```text
@Alice Oak Gate: type Staging Area.
```

### !rec type near 37.9105 -122.1895

80 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | type Staging Area.
```

### !rec type near 37.9205,-122.1795 0.25

88 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | type Staging Area.
```

### !rec Oak Gate parking

29 UTF-8 bytes.

```text
@Alice Oak Gate: parking Lot.
```

### !rec parking near 37.9105 -122.1895

78 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | parking Limited.
```

### !rec parking near 37.9205,-122.1795 0.25

82 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | parking Yes.
```

### !rec Oak Gate restrooms

31 UTF-8 bytes.

```text
@Alice Oak Gate: restrooms Yes.
```

### !rec restrooms near 37.9105 -122.1895

76 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | restrooms ADA.
```

### !rec restrooms near 37.9205,-122.1795 0.25

84 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | restrooms Yes.
```

### !rec Oak Gate water

27 UTF-8 bytes.

```text
@Alice Oak Gate: water Yes.
```

### !rec water near 37.9105 -122.1895

72 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | water Yes.
```

### !rec water near 37.9205,-122.1795 0.25

80 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | water Yes.
```

### !rec Oak Gate picnic

28 UTF-8 bytes.

```text
@Alice Oak Gate: picnic Yes.
```

### !rec picnic near 37.9105 -122.1895

73 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | picnic Yes.
```

### !rec picnic near 37.9205,-122.1795 0.25

81 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | picnic Yes.
```

### !rec Oak Gate fishing

29 UTF-8 bytes.

```text
@Alice Oak Gate: fishing Yes.
```

### !rec fishing near 37.9105 -122.1895

74 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | fishing Yes.
```

### !rec fishing near 37.9205,-122.1795 0.25

82 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | fishing Yes.
```

### !rec Oak Gate boatlaunch

32 UTF-8 bytes.

```text
@Alice Oak Gate: boatlaunch Yes.
```

### !rec boatlaunch near 37.9105 -122.1895

77 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | boatlaunch Yes.
```

### !rec boatlaunch near 37.9205,-122.1795 0.25

85 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | boatlaunch Yes.
```

### !rec Oak Gate boatrental

32 UTF-8 bytes.

```text
@Alice Oak Gate: boatrental Yes.
```

### !rec boatrental near 37.9105 -122.1895

77 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | boatrental Yes.
```

### !rec boatrental near 37.9205,-122.1795 0.25

85 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | boatrental Yes.
```

### !rec Oak Gate playground

32 UTF-8 bytes.

```text
@Alice Oak Gate: playground Yes.
```

### !rec playground near 37.9105 -122.1895

77 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | playground Yes.
```

### !rec playground near 37.9205,-122.1795 0.25

85 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | playground Yes.
```

### !rec Oak Gate horsetrailers

35 UTF-8 bytes.

```text
@Alice Oak Gate: horsetrailers Yes.
```

### !rec horsetrailers near 37.9105 -122.1895

80 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | horsetrailers Yes.
```

### !rec horsetrailers near 37.9205,-122.1795 0.25

88 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | horsetrailers Yes.
```

### !rec Oak Gate location

46 UTF-8 bytes.

```text
@Alice Oak Gate: location 37.90000,-122.20000.
```

### !rec location near 37.9105 -122.1895

91 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | location 37.91000,-122.19000.
```

### !rec location near 37.9205,-122.1795 0.25

99 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | location 37.92000,-122.18000.
```

### !rec Oak Gate info

150 UTF-8 bytes.

```text
@Alice Recreation: Oak Gate | type Staging Area | parking Lot | restroom Yes | water Yes | picnic Yes | fishing Yes | boat launch Yes | playground Yes
```

### !rec info near 37.9105 -122.1895

137 UTF-8 bytes.

```text
@Alice Nearest recreation: Pine Gate (0.04 mi map distance) | type Staging Area | parking Limited | restroom ADA | water Yes | picnic Yes
```

### !rec info near 37.9205,-122.1795 0.25

141 UTF-8 bytes.

```text
@Alice Recreation within 0.25 mi: Creek Gate (0.04 mi map distance) | type Staging Area | parking Yes | restroom Yes | water Yes | picnic Yes
```


<a id="example-group-12"></a>
## GIS peak fields

### !peak Oak Peak elevation

35 UTF-8 bytes.

```text
@Alice Oak Peak: elevation 1200 ft.
```

### !peak elevation near 37.9105 -122.1895

74 UTF-8 bytes.

```text
@Alice Nearest peak: Pine Peak (0.04 mi map distance) | elevation 1500 ft.
```

### !peak elevation near 37.9205,-122.1795 0.25

83 UTF-8 bytes.

```text
@Alice Peaks within 0.25 mi: Creek Peak (0.04 mi map distance) | elevation 1800 ft.
```

### !peak Oak Peak location

46 UTF-8 bytes.

```text
@Alice Oak Peak: location 37.90000,-122.20000.
```

### !peak location near 37.9105 -122.1895

85 UTF-8 bytes.

```text
@Alice Nearest peak: Pine Peak (0.04 mi map distance) | location 37.91000,-122.19000.
```

### !peak location near 37.9205,-122.1795 0.25

94 UTF-8 bytes.

```text
@Alice Peaks within 0.25 mi: Creek Peak (0.04 mi map distance) | location 37.92000,-122.18000.
```

### !peak Oak Peak info

64 UTF-8 bytes.

```text
@Alice Peak: Oak Peak | elevation 1200 ft | 37.90000,-122.20000.
```

### !peak info near 37.9105 -122.1895

96 UTF-8 bytes.

```text
@Alice Nearest peak: Pine Peak (0.04 mi map distance) | elevation 1500 ft | 37.91000,-122.19000.
```

### !peak info near 37.9205,-122.1795 0.25

105 UTF-8 bytes.

```text
@Alice Peaks within 0.25 mi: Creek Peak (0.04 mi map distance) | elevation 1800 ft | 37.92000,-122.18000.
```


<a id="example-group-13"></a>
## GIS park fields

### !park Oak Park status

29 UTF-8 bytes.

```text
@Alice Oak Park: status Open.
```

### !park status near 37.9105 -122.1895

72 UTF-8 bytes.

```text
@Alice Nearest park: Pine Park (0.00 mi map distance) | status Landbank.
```

### !park status near 37.9205,-122.1795 0.25

139 UTF-8 bytes.

```text
@Alice Parks within 0.25 mi: Creek Park (0.00 mi map distance) | status Open | Creek Rec Area (0.00 mi map distance) | status not recorded.
```

### !park Oak Park agency

37 UTF-8 bytes.

```text
@Alice Oak Park: agency Oak District.
```

### !park agency near 37.9105 -122.1895

77 UTF-8 bytes.

```text
@Alice Nearest park: Pine Park (0.00 mi map distance) | agency Pine District.
```

### !park agency near 37.9205,-122.1795 0.25

149 UTF-8 bytes.

```text
@Alice Parks within 0.25 mi: Creek Park (0.00 mi map distance) | agency Creek District | Creek Rec Area (0.00 mi map distance) | agency not recorded.
```

### !park Oak Park trails

33 UTF-8 bytes.

```text
@Alice Oak Park: trails Oak Loop.
```

### !park trails near 37.9105 -122.1895

74 UTF-8 bytes.

```text
@Alice Nearest park: Pine Park (0.00 mi map distance) | trails Pine Ridge.
```

### !park trails near 37.9205,-122.1795 0.25

143 UTF-8 bytes.

```text
@Alice Parks within 0.25 mi: Creek Park (0.00 mi map distance) | trails Creek Path | Creek Rec Area (0.00 mi map distance) | trails Creek Path.
```

### !park Oak Park recreation

37 UTF-8 bytes.

```text
@Alice Oak Park: recreation Oak Gate.
```

### !park recreation near 37.9105 -122.1895

77 UTF-8 bytes.

```text
@Alice Nearest park: Pine Park (0.00 mi map distance) | recreation Pine Gate.
```

### !park recreation near 37.9205,-122.1795 0.25

126 UTF-8 bytes.

```text
@Alice Parks within 0.25 mi: Creek Park (0.00 mi map distance) | recreation Creek Gate | Creek Rec Area (0.00 mi map distance)
```

### !park Oak Park info

106 UTF-8 bytes.

```text
@Alice Park: Oak Park [Open] | agency Oak District | Intersecting trails: Oak Loop | Recreation: Oak Gate.
```

### !park info near 37.9105 -122.1895

146 UTF-8 bytes.

```text
@Alice Nearest park: Pine Park [Landbank] (0.00 mi map distance) | agency Pine District | Intersecting trails: Pine Ridge | Recreation: Pine Gate.
```

### !park info near 37.9205,-122.1795 0.25

149 UTF-8 bytes.

```text
@Alice Parks within 0.25 mi: Creek Park [Open] (0.00 mi map distance) | agency Creek District | Intersecting trails: Creek Path | agency not recorded
```


<a id="example-group-14"></a>
## Boundary categories

### !boundary parks 37.9 -122.2

43 UTF-8 bytes.

```text
@Alice Inside mapped park: Oak Park [Open].
```

### !boundary parks near 37.9105,-122.1895

54 UTF-8 bytes.

```text
@Alice Nearest park: Pine Park (0.00 mi map distance).
```

### !boundary parks near 37.9205 -122.1795 0.25

70 UTF-8 bytes.

```text
@Alice Areas within 0.25 mi: Creek Park [Park] (0.00 mi map distance).
```

### !boundary parks trail Oak Loop

45 UTF-8 bytes.

```text
@Alice Trail overlaps: Park: Oak Park [Open].
```

### !boundary watersheds 37.9 -122.2

42 UTF-8 bytes.

```text
@Alice Inside mapped watershed: Oak Basin.
```

### !boundary watersheds near 37.9105,-122.1895

60 UTF-8 bytes.

```text
@Alice Nearest watershed: Pine Basin (0.00 mi map distance).
```

### !boundary watersheds near 37.9205 -122.1795 0.25

76 UTF-8 bytes.

```text
@Alice Areas within 0.25 mi: Creek Basin [Watershed] (0.00 mi map distance).
```

### !boundary watersheds trail Oak Loop

44 UTF-8 bytes.

```text
@Alice Trail overlaps: Watershed: Oak Basin.
```

### !boundary reservoirs 37.9 -122.2

41 UTF-8 bytes.

```text
@Alice Inside mapped reservoir: Oak Lake.
```

### !boundary reservoirs near 37.9105,-122.1895

59 UTF-8 bytes.

```text
@Alice Nearest reservoir: Pine Lake (0.00 mi map distance).
```

### !boundary reservoirs near 37.9205 -122.1795 0.25

75 UTF-8 bytes.

```text
@Alice Areas within 0.25 mi: Creek Lake [Reservoir] (0.00 mi map distance).
```

### !boundary reservoirs trail Oak Loop

43 UTF-8 bytes.

```text
@Alice Trail overlaps: Reservoir: Oak Lake.
```

### !boundary recreation 37.9 -122.2

51 UTF-8 bytes.

```text
@Alice Inside mapped recreation area: Oak Rec Area.
```

### !boundary recreation near 37.9105,-122.1895

69 UTF-8 bytes.

```text
@Alice Nearest recreation area: Pine Rec Area (0.00 mi map distance).
```

### !boundary recreation near 37.9205 -122.1795 0.25

85 UTF-8 bytes.

```text
@Alice Areas within 0.25 mi: Creek Rec Area [Recreation area] (0.00 mi map distance).
```

### !boundary recreation trail Oak Loop

53 UTF-8 bytes.

```text
@Alice Trail overlaps: Recreation area: Oak Rec Area.
```


<a id="example-group-15"></a>
## Help

### !trail help

74 UTF-8 bytes.

```text
@Alice !trail NAME [ATTRIBUTE] or near LAT LON [MILES]. See command guide.
```

### !rec help

72 UTF-8 bytes.

```text
@Alice !rec NAME [ATTRIBUTE] or near LAT LON [MILES]. See command guide.
```

### !peak help

73 UTF-8 bytes.

```text
@Alice !peak NAME [ATTRIBUTE] or near LAT LON [MILES]. See command guide.
```

### !park help

73 UTF-8 bytes.

```text
@Alice !park NAME [ATTRIBUTE] or near LAT LON [MILES]. See command guide.
```

### !boundary help

70 UTF-8 bytes.

```text
@Alice !boundary LAT LON or near LAT LON [MILES]. Map boundaries only.
```

### !firezone help

55 UTF-8 bytes.

```text
@Alice Use !firezone ZONE, ZIP, CITY STATE, or LAT LON.
```

### !fires help

52 UTF-8 bytes.

```text
@Alice Use !fires ZONE, ZIP, CITY STATE, or LAT LON.
```

### !fire help

49 UTF-8 bytes.

```text
@Alice Use !fire INCIDENT-ID or NAME from !fires.
```

### !firewx help

53 UTF-8 bytes.

```text
@Alice Use !firewx ZONE, ZIP, CITY STATE, or LAT LON.
```

### !firewarn help

55 UTF-8 bytes.

```text
@Alice Use !firewarn ZONE, ZIP, CITY STATE, or LAT LON.
```

### !firedata help

88 UTF-8 bytes.

```text
@Alice Use !firedata CATEGORY ZONE/LOCATION. Categories are listed in the command guide.
```

### !firealarm help

55 UTF-8 bytes.

```text
@Alice Use !firealarm on ZONE/LOCATION, status, or off.
```

### !smoke help

46 UTF-8 bytes.

```text
@Alice Use !smoke ZIP, CITY STATE, or LAT LON.
```

### !firedanger help

51 UTF-8 bytes.

```text
@Alice Use !firedanger ZIP, CITY STATE, or LAT LON.
```

### !waterway help

99 UTF-8 bytes.

```text
@Alice Use !waterway LOCATION. LOCATION: coordinates, ZIP, or city [state]; bare cities default CA.
```

### !basin help

96 UTF-8 bytes.

```text
@Alice Use !basin LOCATION. LOCATION: coordinates, ZIP, or city [state]; bare cities default CA.
```

### !floodstatus help

102 UTF-8 bytes.

```text
@Alice Use !floodstatus LOCATION. LOCATION: coordinates, ZIP, or city [state]; bare cities default CA.
```

### !floodwarn help

67 UTF-8 bytes.

```text
@Alice !floodwarn CITY [STATE], ZIP, or LAT LON. Default state: CA.
```

### !slidewarn help

150 UTF-8 bytes.

```text
@Alice Use !slidewarn LOCATION. LOCATION: ZIP, CITY [CA/NV], or LATITUDE LONGITUDE (comma optional); California and Nevada. Bare cities default to CA.
```

### !slideinfo help

150 UTF-8 bytes.

```text
@Alice Use !slideinfo LOCATION. LOCATION: ZIP, CITY [CA/NV], or LATITUDE LONGITUDE (comma optional); California and Nevada. Bare cities default to CA.
```

### !floodalarm help

129 UTF-8 bytes.

```text
@Alice Use !floodalarm LOCATION, conditions LOCATION, status, or stop. Coordinates, ZIP, or city [state]; bare cities default CA.
```

### !firealarm help

55 UTF-8 bytes.

```text
@Alice Use !firealarm on ZONE/LOCATION, status, or off.
```

### !slidealarm help

138 UTF-8 bytes.

```text
@Alice Use !slidealarm on LOCATION, status, or off. California/Nevada ZIP, city [CA/NV], or latitude longitude; bare cities default to CA.
```


<a id="example-group-16"></a>
## Triggered subscription notifications

These notices are captured from the service notification callbacks after acknowledged enrollment and synthetic source changes. They are independent of lookup replies and remain subject to subscription, evidence, queue, and expiry guards.

### !floodalarm — New flash warning

117 UTF-8 bytes.

```text
@Alice NWS FLASH FLOOD WARNING. Move to higher ground now. Priority unknown | NEW | Until 7:40 AM PDT | Sacramento CA
```

### !floodalarm — Major gauge threshold

117 UTF-8 bytes.

```text
@Alice 1 gauge: major flooding; not point flooding. | Example upstream gauge [ID A]; USGS unavailable | Sacramento CA
```

### !floodalarm — Alert unlisted

81 UTF-8 bytes.

```text
@Alice NWS Flash Flood Warning missing; cancellation unconfirmed. | Sacramento CA
```

### !firealarm — New Red Flag Warning

44 UTF-8 bytes.

```text
@Alice New/updated Red Flag Warning | CAZ001
```

### !firealarm — Containment updated

42 UTF-8 bytes.

```text
@Alice Test: containment now 20%. | CAZ001
```

### !firealarm — Alert unlisted

61 UTF-8 bytes.

```text
@Alice Red Flag Warning unlisted; status unconfirmed | CAZ001
```

### !slidealarm — New landslide mention

70 UTF-8 bytes.

```text
@Alice NWS Flash Flood Warning; landslide mention. | New | Pasadena CA
```

### !slidealarm — Qualified mention updated

79 UTF-8 bytes.

```text
@Alice NWS Flash Flood Warning; qualified mention only. | Updated | Pasadena CA
```

### !slidealarm — Alert unlisted

106 UTF-8 bytes.

```text
@Alice NWS alert unlisted; cancellation unconfirmed. Not an all-clear. | Flash Flood Warning | Pasadena CA
```
