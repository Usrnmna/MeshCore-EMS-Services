# MeshCore bot command and response reference

See [tagged response examples and near searches](RESPONSE_EXAMPLES.md) for offline formatting previews.

Radio replies use one tagged message, with no details or paging. See the
[response policy and manual review inventory](RESPONSE_FORMATTING.md).

This reference describes the 31 shipped commands in [config.json](config.json), their radio inputs, response families, and administrator options. Linux and Windows use the same command behavior. Installed channel assignments and settings can differ from these defaults. For a shorter introduction, see the [MeshCore user guide](BOT_USER_GUIDE.md).

## Quick navigation

[Complete subcommand index](#subcommand-index) | [Terminal and maintenance commands](../docs/CLI_REFERENCE.md)


- [Sending commands and reading replies](#sending)
- [Coordinates, places, and names](#input)
- [All commands](#command-index)
- [Status](#cmd-status), [time](#cmd-time), [air quality](#cmd-aqi), [traffic](#cmd-traffic), [rivers](#cmd-rivers), [UV](#cmd-uv)
- [Waterways](#cmd-waterway), [basins](#cmd-basin), [current flood status](#cmd-floodstatus)
- [Heat alerts](#cmd-heatadv), [lightning](#cmd-lightning), [flood alerts](#cmd-floodwarn), [flood monitoring](#cmd-floodalarm), [snowpack](#cmd-snowpack)
- [Landslide alerts](#cmd-slidewarn), [landslide monitoring](#cmd-slidealarm), [landslide stations](#cmd-slideinfo)
- [GIS query rules](#gis-syntax), [trail attributes](#cmd-trail), [recreation amenities](#cmd-rec), [peak details](#cmd-peak), [park details](#cmd-park), [boundaries](#cmd-boundary)
- [GIS response and error reference](#gis-responses)
- [Administrator settings](#settings), [standalone Python programs](#python-programs), [troubleshooting](#troubleshooting), [source and verification](#verification)

<a id="sending"></a>
## Sending commands and reading replies

Send one command as an ordinary channel message on a channel assigned to the bot. The shipped channel is `#autatestbot`; the local operator can assign a different channel. Direct messages are not a command interface for this service.

```text
!status
```

The service replies on the same channel and prefixes every reply part with the saved sender display name, for example `@Alice`. Do not type the name prefix or quote an entire command in the radio message. Command words are case-sensitive: use `!trail`, not `!Trail`. The shipped configuration has no `!trails` alias and no global `!help` command. Each GIS command accepts `help`; other commands use the syntax documented below.

Defaults that affect visible behavior:

| Setting or rule | Result |
| --- | --- |
| 30-second sender cooldown per channel | Additional requests during cooldown can be ignored, including after a malformed request. Wait before retrying. |
| 5-second command transmission spacing | Long or queued replies can take several minutes. Spacing applies between radio transmissions, not just between complete answers. |
| 150-byte radio reply limit | Every part includes `@sender`. Unicode uses multiple bytes; a 150-byte limit is not a 150-character limit. |
| Reply cap | One 150-byte message including sender tag; no paging, continuation or omission notices. |
| Message freshness | Messages older than 300 seconds or more than 60 seconds in the future are ignored. |
| Duplicate detection | Repeated packets do not run the same request again. |
| Channel assignments | A recognized command on an unassigned channel produces no response. |

Reply examples below are **body text** unless `@Alice` is shown. Each lookup
returns one message of at most 150 UTF-8 bytes including its sender tag. Essential
warning and uncertainty text takes priority; optional fields are admitted whole.
Names can be shortened at word boundaries. Synthetic provider examples are not
current observations; local GIS examples reflect the checked snapshot. The
[complete tagged response catalog](RESPONSE_EXAMPLES.md) covers commands,
fields, categories, proximity searches, help, controls, and triggered notices.

<a id="input"></a>
## Coordinates, places, and names

| Input family | Accepted forms | Commands |
| --- | --- | --- |
| No arguments | Exact command only | `!status`, `!time` |
| Decimal coordinates | `38.5816 -121.4944` or `38.5816, -121.4944` | `!aqi`, `!rivers` |
| Route number | Digits from 1 through 999, such as `80` | `!traffic` |
| Weather/environment point | GPS, five-digit US ZIP, ZIP+4, city, or city plus state | `!uv`, `!heatadv`, `!lightning`, `!snowpack`, `!smoke`, `!firedanger` |
| Water point | GPS, US ZIP/ZIP+4, or an exact city name with optional state; ambiguous matches require clarification | `!waterway`, `!basin`, `!floodstatus`, `!floodwarn`, `!floodalarm` |
| California/Nevada point | Supported GPS, ZIP, or city/state inside either state | `!slidewarn`, `!slidealarm`, `!slideinfo` |
| Fire-weather zone or location | Whole NWS fire-weather zone ID or a supported resolved point | `!firezone`, `!fires`, `!firewx`, `!firewarn`, `!firedata`, `!firealarm` |
| Incident identity | Exact stored incident ID or unambiguous incident name | `!fire` |
| GIS query | A mapped feature name, coordinates, or the documented attribute/category grammar | `!trail`, `!rec`, `!peak`, `!park`, `!boundary` |

Coordinates use **latitude first, longitude second**; longitude is normally negative in California. Global bounds are latitude -90 through 90 and longitude -180 through 180. Degrees/minutes/seconds, map URLs, and phone GPS-sharing links are not accepted coordinate syntax.

Location commands default bare cities to California. Use `Reno NV`, `Reno, Nevada`, or `Albany New York` for another state. ZIP+4 uses its first five digits. City/ZIP lookup represents one resolved point, not the entire city or postal area. `!snowpack` is California-only. The GIS commands do not geocode cities, ZIP codes, or addresses; names must occur in their local feature datasets.

Radio requests cannot supply arbitrary terminal flags such as `--radius`, `--timezone`, or `--settings`. Those are administrator options where supported. Optional notation in this guide, such as `[MILES]`, describes syntax: do not send the brackets or placeholder words.

<a id="command-index"></a>
## All commands

| Command | Purpose | Minimal example |
| --- | --- | --- |
| [!status](#cmd-status) | Check the local command responder | `!status` |
| [!time](#cmd-time) | Read the bot host's clock in the configured zone | `!time` |
| [!aqi](#cmd-aqi) | Nearest available PM2.5 monitor observation | `!aqi 37.7749 -122.4194` |
| [!traffic](#cmd-traffic) | California highway restrictions | `!traffic 80` |
| [!rivers](#cmd-rivers) | Nearby river-stage reports | `!rivers 39.0 -121.0` |
| [!uv](#cmd-uv) | Current UV index | `!uv Sacramento` |
| [!heatadv](#cmd-heatadv) | Active NWS heat alerts | `!heatadv Sacramento` |
| [!lightning](#cmd-lightning) | NWS lightning/thunderstorm potential for 24 hours | `!lightning Sacramento` |
| [!waterway](#cmd-waterway) | Named waterways and current gauge context | `!waterway 38.61 -122.83` |
| [!basin](#cmd-basin) | Containing CalWater categories | `!basin 38.61 -122.83` |
| [!floodstatus](#cmd-floodstatus) | Official and derived current point status | `!floodstatus 95814` |
| [!floodwarn](#cmd-floodwarn) | One-time flood-alert lookup | `!floodwarn Sacramento` |
| [!floodalarm](#cmd-floodalarm) | Register temporary flood-change monitoring | `!floodalarm Sacramento` |
| [!snowpack](#cmd-snowpack) | Current snow depth and forecast new snowfall | `!snowpack Truckee` |
| [!trail](#cmd-trail) | Local trail details and policy searches | `!trail Bear Creek dogs` |
| [!rec](#cmd-rec) | Local recreation amenities | `!rec water near 37.90 -122.20` |
| [!peak](#cmd-peak) | Local peak elevation or coordinates | `!peak Wildcat Peak elevation` |
| [!park](#cmd-park) | Local park status and associations | `!park Pleasanton Ridge status` |
| [!boundary](#cmd-boundary) | Mapped area containment or overlap | `!boundary trail Bear Creek` |
| [!firezone](#cmd-firezone) | Interstate fire-weather zones and warning status | `!firezone CAZ272` |
| [!fires](#cmd-fires) | Current reported incidents and mapped boundaries | `!fires CAZ272` |
| [!fire](#cmd-fire) | Incident containment and source detail | `!fire INCIDENT-ID` |
| [!firewx](#cmd-firewx) | Zone fire-weather forecast | `!firewx CAZ272` |
| [!firewarn](#cmd-firewarn) | Red Flag Warnings and Fire Weather Watches | `!firewarn CAZ272` |
| [!firedata](#cmd-firedata) | Supporting observations and outlooks | `!firedata raws CAZ272` |
| [!firealarm](#cmd-firealarm) | Temporary wildfire change monitoring | `!firealarm on CAZ272` |
| [!slidewarn](#cmd-slidewarn) | California/Nevada alerts mentioning landslide hazards | `!slidewarn 91107` |
| [!slidealarm](#cmd-slidealarm) | Temporary California/Nevada alert monitoring | `!slidealarm on Pasadena` |
| [!slideinfo](#cmd-slideinfo) | Nearest eligible USGS station | `!slideinfo 34.15,-118.14` |
| [!smoke](#cmd-smoke) | Point smoke coverage and nearby air quality | `!smoke 96150` |
| [!firedanger](#cmd-firedanger) | Local ERC percentile, fuels and warning context | `!firedanger Reno NV` |

<a id="subcommand-index"></a>
## Subcommand and option index

This index lists the complete radio vocabulary in the maintained parsers. Each
linked section explains outputs, interpretation, failures, and configuration.
`LOCATION` means a supported location input, `NAME` a local dataset name, and
`ZONE` an NWS fire-weather zone ID. Placeholder brackets are omitted from messages.
Terminal flags such as `--json` belong to direct Python invocation, not radio text.

### GIS fields, categories, and query forms

| Command | Named fields or category words | Explanation |
| --- | --- | --- |
| `!trail` | `dogs`, `horses`, `bikes`, `length`, `difficulty`, `gain`, `surface`, `shade`, `time`, `start`, `areas`, `description`, `info` | [All trail fields and responses](#cmd-trail). |
| `!rec` | `type`, `parking`, `restrooms`, `water`, `picnic`, `fishing`, `boatlaunch`, `boatrental`, `playground`, `horsetrailers`, `location`, `info` | [All rec fields and responses](#cmd-rec). |
| `!peak` | `elevation`, `location`, `info` | [All peak fields and responses](#cmd-peak). |
| `!park` | `status`, `agency`, `trails`, `recreation`, `info` | [All park fields and responses](#cmd-park). |
| `!boundary` | `parks`, `watersheds`, `reservoirs`, `recreation` | [All boundary fields and responses](#cmd-boundary). |

- `!COMMAND NAME` identifies a feature; `help` lists syntax. `NAME FIELD`
  returns one field and `NAME info` requests a concise summary.
- `!COMMAND near LATITUDE LONGITUDE [MILES]` ranks matching features. Without
  miles, only the closest result is returned. An explicit radius is bounded by
  the configured maximum, which defaults to 25 miles.
- `!COMMAND FIELD near LATITUDE LONGITUDE [MILES]` selects a field. Supported
  affirmative policy/amenity fields also filter eligibility before ranking;
  see [filter vocabulary](#gis-syntax).
- `!boundary [CATEGORY] LATITUDE LONGITUDE` tests containment;
  `[CATEGORY] near LATITUDE LONGITUDE [MILES]` finds mapped areas;
  `[CATEGORY] trail NAME` reports area overlaps for a stored trail.
- Each of the five GIS commands accepts `help`; an argument-free command also
  returns syntax through the responder. Names, fields, and GIS keywords are
  case-insensitive. GIS commands do not resolve city names or street addresses.

### Wildfire, smoke, and fuel-danger forms

| Command | Accepted forms | Explanation |
| --- | --- | --- |
| `!firezone` | `ZONE` or `LOCATION`; `help` | Whole-zone identity and cached fire-weather alert status. |
| `!fires` | `ZONE` or `LOCATION`; `near LOCATION within MILES`; `help` | Incident origins and latest mapped perimeters; distance searches use a point. |
| `!fire` | `INCIDENT-ID` or an unambiguous incident name; `help` | One incident, reported containment, perimeter provenance, or labelled retained history. |
| `!firewx` | `ZONE` or `LOCATION`; `help` | Zone forecast periods and active warning/watch context. |
| `!firewarn` | `ZONE` or `LOCATION`; `help` | Red Flag Warning and Fire Weather Watch products. |
| `!firedata` | `CATEGORY ZONE` or `CATEGORY LOCATION`; `help` | A selected supplementary product, with its own source freshness. |
| `!firealarm` | `on ZONE`, `on LOCATION`, `status`, `off`, `help` | Service-owned temporary enrollment, inspection, or cancellation. |
| `!smoke` | `LOCATION`; `help` | Point HMS smoke and nearby air quality; no zone IDs or paging. |
| `!firedanger` | `LOCATION`; `help` | Eligible nearby ERC/BI context and optional configured fuel moisture; no zone IDs or paging. |

The twelve `!firedata` categories are: `aqi`, `aqi_today`, `aqi_tomorrow`, `cameras`, `history`, `modis`, `potential`, `raws`, `smoke`, `spc`, `treatments`, `viirs`.
The [wildfire source/category table](WILDFIRE_GUIDE.md#sources-and-supplementary-categories)
explains each product. Optional categories must be initialized explicitly or enabled
for refresh. Distance searches must satisfy the configured
radius limit. See [wildfire radio syntax](WILDFIRE_GUIDE.md#radio-commands) and
[point smoke and fuel danger](WILDFIRE_GUIDE.md#point-smoke-and-fuel-danger).

### Water and flood forms

| Command | Accepted forms | Explanation |
| --- | --- | --- |
| `!waterway` | `LOCATION`, `help` | Named reaches, supported upstream-basin relationships, and current gauge context. |
| `!basin` | `LOCATION`, `help` | Containing CalWater hierarchy and Water Board attribution. |
| `!floodstatus` | `LOCATION`, `help` | Official alerts, modeled point footprint, current gauges, and explicit coverage gaps. |
| `!floodwarn` | `LOCATION`, `help` | Highest-priority official alert; no enrollment or renewal. |
| `!floodalarm` | `LOCATION`, `conditions LOCATION`, `status`, `stop`, `help` | Official-alert subscription by default; conditions mode adds supported categorical gauge/model/coverage changes. |

Water queries accept coordinates, US ZIP/ZIP+4, or exact city names with optional
state; bare cities default to California. River names are not location aliases.
Only accepted enrollment renews the four-hour default duration. `status` never
renews it and `stop` invalidates pending checks/notifications. The default check
interval is five minutes. See [water commands and subscription lifecycle](WATER_GUIDE.md).

### Landslide forms

| Command | Accepted forms | Explanation |
| --- | --- | --- |
| `!slidewarn` | `LOCATION`, `help` | Official California/Nevada point alerts explicitly mentioning landslide hazards. |
| `!slidealarm` | `on LOCATION`, `status`, `off`, `help` | Service-owned temporary alert monitoring. |
| `!slideinfo` | `LOCATION`, `near LOCATION`, `help` | Nearest eligible reviewed USGS station metadata; no numeric telemetry. |

Landslide locations must resolve inside California or Nevada. The reviewed station
catalog is Californian, including when the request is in Nevada. See the
[landslide guide](LANDSLIDE_GUIDE.md) for intervals, expiry, cache behavior, and coverage.

### Commands without subcommands

`!status` and `!time` accept no arguments. `!aqi` and `!rivers` take coordinates;
`!traffic` takes an integer route number from 1 to 999. `!uv`, `!heatadv`,
`!lightning`, and `!snowpack` take the locations documented in their sections.
These commands have no radio field selector, paging, or subscription control.
There is no global `!help` command. Unknown commands are ignored; command words
remain lowercase and argument validation is command-specific.

<a id="cmd-status"></a>
## !status --> local responder

[Tagged response examples](RESPONSE_EXAMPLES.md#example-status).

**Syntax:** `!status` with no arguments. **Program:** [scripts/status.py](scripts/status.py).

```text
@Alice Local command service is running.
```

This is a local smoke response. It does not check the weather providers, dataset currency, every radio route, or delivery to other recipients. Additional text, such as `!status help`, does not match this command. There are no radio subcommands or per-request options.

<a id="cmd-time"></a>
## !time --> host time

[Tagged response examples](RESPONSE_EXAMPLES.md#example-time).

**Syntax:** `!time` with no arguments. **Program:** [scripts/time_now.py](scripts/time_now.py).

Illustrative response:

```text
@Alice Current time: 2026-10-14 14:30:00 PDT
```

The format is `Current time: YYYY-MM-DD HH:MM:SS ZONE`. This uses the host clock and the persistent [reply timezone](#timezone), not the location of the requesting radio. There is no radio timezone argument. Incorrect host time can also affect message-age acceptance and provider freshness checks.

<a id="cmd-aqi"></a>
## !aqi --> air quality

[Tagged response examples](RESPONSE_EXAMPLES.md#example-aqi).

**Syntax:** `!aqi LATITUDE LONGITUDE`. **Program:** [scripts/airnow_aqi.py](scripts/airnow_aqi.py). The bot host requires internet access and an `AIRNOW_API_KEY` environment setting.

```text
!aqi 37.7749 -122.4194
!aqi 37.7749, -122.4194
```

The primary field is `AQI <integer> <category>; preliminary.` Optional whole
fields include PM2.5 concentration, observation time, station name and distance.

Ratings include `Good`, `Moderate`, `Sensitive`, `Unhealthy`, `Very Unhealthy`, and `Hazardous`. The reading comes from a monitoring station, not a sensor at the submitted point. A missing concentration can be `N/A` even when AQI is available. No city, ZIP, pollutant selector, or custom radius is accepted over the radio.

Missing/invalid coordinates return a usage reply. A failed script returns `AirNow lookup unavailable. Check the service AIRNOW_API_KEY setting or try again later.` A subprocess timeout has the separate [timeout response](#errors).

<a id="cmd-traffic"></a>
## !traffic --> highway restrictions

[Tagged response examples](RESPONSE_EXAMPLES.md#example-traffic).

**Syntax:** `!traffic ROUTE_NUMBER`, 1–999. **Program:** [scripts/highway_info.py](scripts/highway_info.py). Source: Caltrans California highway reports; internet required, no API key.

```text
!traffic 80
!traffic 5
!traffic 101
```

An active report contains compact provider restriction text, affected locations, and any applicable timing. Its wording varies with the source. A clear report returns exactly:

```text
No Traffic Restrictions Reported
```

Invalid syntax returns `Use !traffic ROUTE_NUMBER (1-999), for example !traffic 80.` Omit `I-`, `US`, `SR`, directions, and city names. Fetch failures return `Caltrans traffic lookup unavailable. Please try again later.` Missing information is not interpreted as a clear road. This command does not estimate traffic speed or travel time. Undated or recurring source schedules retain an explicit Pacific source-time label.

<a id="cmd-rivers"></a>
## !rivers --> nearby river stations

[Tagged response examples](RESPONSE_EXAMPLES.md#example-rivers).

**Syntax:** `!rivers LATITUDE LONGITUDE`. **Program:** [scripts/nearby_river_stations.py](scripts/nearby_river_stations.py). CDEC/NOAA data; internet required, no API key.

```text
!rivers 39.0 -121.0
```

The default search radius is **15 miles**, with nearest stations first. Response template:

```text
ABC: 21ft; flood threshold; point flooding unknown. | 2026-10-21 11:00 PDT | AS 15ft; FS 20ft | 1 station | Example River
```

`AS` means action stage; `FS` means minor flood stage. Missing values are `N/A`; an unparseable issuance time is `unknown report time`. Available timestamps use the shared reply zone. An empty search returns `No matching river stations found within 15 mi.` Provider failures return `River station lookup unavailable. Please try again later.`

Radio output prioritizes a reported threshold exceedance, otherwise the nearest station. Other stations and secondary fields may not fit; standalone JSON retains the complete result. This is a report lookup, not a water-level forecast or a subscription. There is no radio radius option: `!rivers 39 -121 30` is invalid. An administrator can adjust the fixed radius through the [standalone program arguments](#python-programs).

<a id="cmd-uv"></a>
## !uv --> current ultraviolet index

[Tagged response examples](RESPONSE_EXAMPLES.md#example-uv).

**Syntax:** `!uv LOCATION`. **Program:** [scripts/uv_index.py](scripts/uv_index.py). Uses CurrentUVIndex.com and location lookup when needed; internet required, no API key.

```text
!uv Sacramento
!uv 95814
!uv Reno NV
!uv 38.5816 -121.4944
```

Illustrative response: `UV Index: 6.5 High`. Categories are `Low` below 3, `Moderate` from 3 to below 6, `High` from 6 to below 8, `Very-High` from 8 to below 11, and `Extreme` at 11 or above.

This reports the current reading, without a forecast or date selector. Empty/malformed input returns `Use !uv LATITUDE LONGITUDE, ZIP, or CITY [STATE].` Unknown locations or provider errors can return explanatory text. Malformed provider data can return `UV lookup unavailable: invalid service response.` A nonzero subprocess exit uses the configured `UV lookup unavailable. Please try again later.` fallback.

<a id="cmd-heatadv"></a>
## !heatadv --> heat alerts

[Tagged response examples](RESPONSE_EXAMPLES.md#example-heatadv).

**Syntax:** `!heatadv LOCATION`. **Program:** [scripts/heat_adv.py](scripts/heat_adv.py). NWS point coverage and active alerts; internet required, no API key.

```text
!heatadv Sacramento
!heatadv 95814
!heatadv Reno NV
!heatadv 38.5816 -121.4944
```

Primary response fields are:

```text
No active NWS heat alerts.
NWS Extreme Heat Warning.
NWS Extreme Heat Watch.
NWS Heat Advisory.
```

The highest-priority type appears first. Other distinct types and location are optional fields. Legacy Excessive Heat Warning/Watch names are mapped to Extreme Heat Warning/Watch. Expired, cancelled, test, and not-yet-effective alerts are excluded; an already effective watch can concern a future event.

Unverified NWS coverage, missing/incomplete data, or failed requests return explanatory error text rather than a no-alert assertion. The nonzero-exit fallback is `Heat alert lookup unavailable. Please try again later.` This is a one-time lookup; there are no radio thresholds, subscription flags, or forecast-day options.

<a id="cmd-lightning"></a>
## !lightning --> 24-hour lightning potential

[Tagged response examples](RESPONSE_EXAMPLES.md#example-lightning).

**Syntax:** `!lightning LOCATION`. **Program:** [scripts/lightning.py](scripts/lightning.py). NWS point alerts and forecast-grid weather, thunderstorm probability, and lightning activity levels; internet required, no API key.

```text
!lightning Sacramento
!lightning 95814
!lightning 38.5816, -121.4944
```

A hazard response begins with an official NWS event when present, otherwise a
forecast label such as `NWS: slight chance thunderstorms (24h).` Optional fields
include the overall span, additional chance levels, alert/window counts and
location. `Data incomplete.` remains part of the primary field when another
source fails. A verified empty result retains the no-lightning forecast reply.

The lookup covers 24 elapsed hours, including daylight-saving changes. Returned
spans describe forecast/alert periods, not individual strike predictions. No
synthetic official lightning warning is asserted. Rain probability is not used
as thunderstorm probability. Each lookup produces one tagged message.

<a id="cmd-waterway"></a>
## !waterway - location waterway status

[Tagged response examples](RESPONSE_EXAMPLES.md#example-waterway).

**Syntax:** `!waterway LOCATION`. **Program:** [scripts/waterway.py](scripts/waterway.py).
Returns named nearby reaches and selected USGS/NOAA gauge observations, with age,
quality and upstream basin context versus nearby-only labels. Proximity does not
establish a downstream connection. Missing routing remains explicit.

<a id="cmd-basin"></a>
## !basin - containing watersheds

[Tagged response examples](RESPONSE_EXAMPLES.md#example-basin).

**Syntax:** `!basin LOCATION`. **Program:** [scripts/basin.py](scripts/basin.py).
Reports containing CalWater categories separately from Water Board regional
attribution, plus selected upstream/nearby gauge context. This does not declare
an entire basin flooded. Undated QPE is point context, not basin-average rainfall.

<a id="cmd-floodstatus"></a>
## !floodstatus - current point conditions

[Tagged response examples](RESPONSE_EXAMPLES.md#example-floodstatus).

**Syntax:** `!floodstatus LOCATION`. **Program:** [scripts/floodstatus.py](scripts/floodstatus.py).
Combines official NWS point alerts, current modeled inundation coverage, CalWater
basins and selected gauge observations. Official, modeled and derived conditions
remain separate. An absent model polygon or stale observation is not an all-clear.

<a id="cmd-floodwarn"></a>
## !floodwarn - one-time official flood alerts

[Tagged response examples](RESPONSE_EXAMPLES.md#example-floodwarn).

**Syntax:** `!floodwarn LOCATION`, `!floodwarn help`.
**Program:** [scripts/flood_warn.py](scripts/flood_warn.py).

The reply selects the highest-priority active NWS flood event, preserves urgent
action, and admits optional alert count, expiration and location as complete
fields. No details or paging subcommand is available. Local `--json` execution
retains structured current bulletin records.

Only actual, effective Flash Flood Warning, Flood Warning, Flood Advisory and
Flood Watch products are included after NWS coverage verification. A successful
empty lookup says `No active NWS flood alerts. | Sacramento` Unavailable, stale,
invalid or unverified coverage says `Sacramento: NWS alerts unavailable; status
unknown.` Neither response claims absence of flooding. City/ZIP alerts still
apply to the resolved location, not an entire municipality or ZIP boundary.
Coastal/lakeshore products and general flood statements are outside this filter.
The command never creates, renews or cancels a subscription.

[Exact descriptions and hypothetical response examples](WATER_GUIDE.md#concise-flood-alerts).

<a id="cmd-floodalarm"></a>
## !floodalarm - location subscriptions

[Tagged response examples](RESPONSE_EXAMPLES.md#example-floodalarm).

**Program:** [scripts/floodalarm.py](scripts/floodalarm.py); scheduling and persistence
remain in [flood_alarm.py](flood_alarm.py) within the running service.

```text
!floodalarm Sacramento CA
!floodalarm conditions 38.61324 -122.83638
!floodalarm status
!floodalarm stop
```

Enrollment resolves one point and verifies official-alert coverage before the
acknowledgment. Ambiguous places require coordinates; monitoring does not start.
The first form monitors official alert changes. `conditions` also monitors
supported linked gauge categories, modeled footprint states and availability.
The default check interval is five minutes and expiry is four hours from acceptance.
A repeat replaces the subscription and baseline; `status` does not renew it.
`stop` cancels pending and active work for that sender/channel. Material official
updates, expiry and unconfirmed feed disappearance are distinguished. Outages
never clear alerts and unchanged conditions remain quiet.

After acknowledgment, each initial active alert and subsequent new/updated alert
is sent independently with its standard description. Delivery uses urgency,
severity, certainty and effective time, followed by deterministic ties. Unknown
priority fields are flagged. A minimum five-second gap separates completed
responses; the shared transmitter interval is also five seconds. Radio contention can extend gaps.
Polling continues during delivery, and queued notices are revalidated before
each chunk. [Priority, timing, uncertainty and delivery limits](WATER_GUIDE.md#independent-flood-alarm-notifications).
[Hypothetical updates, cancellations, expirations and recovery responses](WATER_GUIDE.md#hypothetical-lifecycle-and-recovery-examples)
illustrate queue replacement and suppression.

All five commands accept GPS, US ZIP/ZIP+4 or exact city/state; bare cities default
to California. Geographic names select a representative point, not a whole city
or ZIP boundary. Statewide local context requires downloaded datasets and a built
spatial index. Radio summaries are bounded; condition monitoring evaluates all reliably
linked upstream gauges. Full-set counts and explicit missing/uncertain states
remain visible; display limits never restrict monitoring.
Standalone execution returns a snapshot only; `--json` or `--snapshot` selects
structured output and cannot enroll monitoring. The service pins coordinates,
preserves expiry across restarts and sends tagged replies on the original channel.

[Water setup, interpretation, retention, settings and source citations](WATER_GUIDE.md).

<a id="cmd-snowpack"></a>
## !snowpack --> snow depth and forecast snowfall

[Tagged response examples](RESPONSE_EXAMPLES.md#example-snowpack).

**Syntax:** `!snowpack LOCATION`, California only. **Program:** [scripts/snowpack.py](scripts/snowpack.py). CDEC hourly snow-depth stations and NWS snowfall forecast grid; internet required, no API key.

```text
!snowpack Truckee
!snowpack 96161
!snowpack 39.3279 -120.1833
```

Illustrative response:

```text
Snow depth at station: 12in. | Next 24h snow: 4in | Snow Creek 2.3mi
```

`Snow depth at station` is observed depth at the nearest active hourly snow-depth station. `Next 24h snow` is forecast new snowfall at the requested location over the rolling 24 hours. It is not snow-water equivalent. The station distance is straight-line distance in miles. A stale/missing reading does not silently select a farther station.

Missing, stale, negative, or unusable values are `unavailable` for the affected field; valid zero is `0in`, and positive values below 0.05 inches appear as `<0.1in`. Forecast interval contributions are prorated at the requested window boundaries. Different elevations and terrain can make station depth unrepresentative of the submitted point.

Coverage, resolution, or provider errors can return explanatory text. The configured nonzero-exit fallback is `Snowpack lookup unavailable. Please try again later.` No station selector, radius, date, or forecast-duration option is accepted over the radio.

<a id="gis-syntax"></a>
## Shared GIS query rules

The five GIS commands query **local EBMUD-area datasets**, including their supplied surrounding park layers. They are not a statewide park search. The separately downloaded California State Parks data and satellite catalog are local reference collections and are not registered as MeshCore commands.

For `!trail`, `!rec`, `!peak`, and `!park`:

```text
!COMMAND help
!COMMAND NAME
!COMMAND NAME ATTRIBUTE
!COMMAND NAME info
!COMMAND near LAT LON
!COMMAND near LAT LON MILES
!COMMAND ATTRIBUTE near LAT LON
!COMMAND ATTRIBUTE near LAT LON MILES
```

- An argument-free GIS command behaves like `help`.
- A name alone returns compact identification and subcommand choices. `info` requests the longer summary.
- Names are case/accent/punctuation normalized. Exact normalized matches take priority; otherwise partial matches are searched. Ambiguous names return choices rather than selecting arbitrarily.
- Without miles, `near` returns **exactly one closest qualifying feature**, regardless of the old default-radius value. Ties use name, then category, for stable ordering.
- With a positive radius, matches inside it are listed nearest first. The default maximum explicit radius is 25 miles and default result cap is three. The single-message budget selects complete fields without omission notices.
- Bare `LAT LON` also selects one nearest feature for these four commands. Only `near` accepts a third radius number.
- An attribute goes **after a name** or **before `near`**. There is no combined name-plus-near grammar, multiple-attribute selector, or sorting flag.
- `dogs`, `horses`, `bikes`, and the recreation amenity selectors filter for affirmative source values before proximity ranking. Other attributes, such as `elevation`, select the nearest feature and display that field; they do not filter by its value.
- Missing, negative, unknown, or conflicting grouped policy values fail an affirmative filter. Conditional source wording remains visible. A named lookup can still report `No` or `not recorded`.

Distances use the nearest part of the complete projected geometry, not its centroid. A containing polygon can be 0.00 mi away. These are map distances, not road/walking distances, routes, or estimates of access. The default calculation area is bounded by longitude -126 through -120 and latitude 0 through 84; this bounds the projection, not the actual data coverage. A closest result can therefore be distant from a location without nearby source features.

GIS input is limited to 150 characters. City names, ZIPs, addresses, and arbitrary command flags are not geocoded. Unrecognized suffix words can be interpreted as part of a feature name; use the exact attribute spellings below.

<a id="cmd-trail"></a>
## !trail --> trail details

[Tagged response examples](RESPONSE_EXAMPLES.md#example-trail).

**Program:** [scripts/trail.py](scripts/trail.py). All queries are offline. [Shared syntax](#gis-syntax) applies.

Named example: `!trail Bear Creek`. Response:

```text
Trail: Bear Creek.
```

### Attribute index

[dogs](#trail-dogs) | [horses](#trail-horses) | [bikes](#trail-bikes) | [length](#trail-length) | [difficulty](#trail-difficulty) | [gain](#trail-gain) | [surface](#trail-surface) | [shade](#trail-shade) | [time](#trail-time) | [start](#trail-start) | [areas](#trail-areas) | [description](#trail-description) | [info](#trail-info)

| Subcommand | Purpose and interpretation |
| --- | --- |
| <a id="trail-dogs"></a>`dogs` | Recorded dog policy; also an affirmative proximity filter. Conditional permission is retained. |
| <a id="trail-horses"></a>`horses` | Recorded horse policy; also an affirmative proximity filter. |
| <a id="trail-bikes"></a>`bikes` | Recorded bicycle policy; also an affirmative proximity filter. Source qualifications are not expanded into inferred rules. |
| <a id="trail-length"></a>`length` | Primary trail length in miles. Supplementary segment data returns `segment data; total not inferred` rather than a guessed total. |
| <a id="trail-difficulty"></a>`difficulty` | Recorded difficulty; source `Difficult` is displayed as `Strenuous`. |
| <a id="trail-gain"></a>`gain` | Recorded elevation gain in feet; missing values are `not recorded`. |
| <a id="trail-surface"></a>`surface` | Recorded trail surface; distinct values can be slash-separated. |
| <a id="trail-shade"></a>`shade` | Recorded sun/shade exposure. |
| <a id="trail-time"></a>`time` | Source estimated hours for primary trails, labeled 3 mph and terrain excluded; it is not a personalized duration. |
| <a id="trail-start"></a>`start` | Mapped START endpoint as latitude,longitude. This is not necessarily a parking location or recommended entrance. |
| <a id="trail-areas"></a>`areas` | Intersecting mapped parks, recreation areas, reservoirs, and watersheds, subject to result limits. |
| <a id="trail-description"></a>`description` | Source trail narrative, limited by `description_characters`; zero yields `Description disabled by settings.`. |
| <a id="trail-info"></a>`info` | Trail attributes and area associations, bounded by reply limits; mapped start coordinates use the separate `start` query. |

### Attribute response examples

These response bodies were produced by the current local snapshots. `not recorded` is a valid response; it does not mean `No`.

| Radio message | Response body |
| --- | --- |
| `!trail Bear Creek dogs` | Bear Creek: dogs No. |
| `!trail Bear Creek horses` | Bear Creek: horses Yes. |
| `!trail Bear Creek bikes` | Bear Creek: bikes No. |
| `!trail Bear Creek length` | Bear Creek: length 5.41 mi. |
| `!trail Bear Creek difficulty` | Bear Creek: difficulty Moderate. |
| `!trail Bear Creek gain` | Bear Creek: gain 592 ft. |
| `!trail Bear Creek surface` | Bear Creek: surface Dirt. |
| `!trail Bear Creek shade` | Bear Creek: shade Full Shade. |
| `!trail Bear Creek time` | Bear Creek: estimated time 1.8 hr (3 mph; terrain excluded). |
| `!trail Bear Creek start` | Bear Creek: mapped start 37.92638,-122.16296. |
| `!trail Bear Creek areas` | Bear Creek: overlaps Watershed: Contra Costa. |
| `!trail Bear Creek description` | Bear Creek: description This trail traverses the southeast slopes of the Briones Reservoir. It is moderately steep in a few... |
| `!trail Bear Creek info` | Trail: Bear Creek \| 5.41 mi \| Moderate \| gain 592 ft \| surface Dirt \| sun Full Shade \| dogs No \| horses Yes \| bikes No |

### Proximity examples

```text
!trail dogs near 37.90 -122.20
Nearest trail: Oursan (0.84 mi map distance) | dogs Yes.
```

```text
!trail dogs near 37.90 -122.20 5
Trails within 5 mi: Oursan (0.84 mi map distance) | dogs Yes | Old San Pablo Trail (0.97 mi map distance) | dogs Limited to Park Hours
```

<a id="cmd-rec"></a>
## !rec --> recreation amenities

[Tagged response examples](RESPONSE_EXAMPLES.md#example-rec).

**Program:** [scripts/rec.py](scripts/rec.py). All queries are offline. [Shared syntax](#gis-syntax) applies.

Named example: `!rec Briones Overlook Staging Area`. Response:

```text
Recreation: Briones Overlook Staging Area.
```

### Attribute index

[type](#rec-type) | [parking](#rec-parking) | [restrooms](#rec-restrooms) | [water](#rec-water) | [picnic](#rec-picnic) | [fishing](#rec-fishing) | [boatlaunch](#rec-boatlaunch) | [boatrental](#rec-boatrental) | [playground](#rec-playground) | [horsetrailers](#rec-horsetrailers) | [location](#rec-location) | [info](#rec-info)

| Subcommand | Purpose and interpretation |
| --- | --- |
| <a id="rec-type"></a>`type` | Recorded recreation feature type; displays the value without filtering by category. |
| <a id="rec-parking"></a>`parking` | Recorded parking availability or type; also an affirmative proximity filter. |
| <a id="rec-restrooms"></a>`restrooms` | Recorded restrooms; also an affirmative proximity filter. Source ADA qualification is retained. |
| <a id="rec-water"></a>`water` | Recorded drinking-water availability; also an affirmative proximity filter. Availability in a snapshot does not confirm present operation. |
| <a id="rec-picnic"></a>`picnic` | Recorded picnic-area availability; also an affirmative proximity filter. |
| <a id="rec-fishing"></a>`fishing` | Recorded fishing availability; also an affirmative proximity filter. No license, season, or current-access determination is made. |
| <a id="rec-boatlaunch"></a>`boatlaunch` | Recorded boat-launch availability; also an affirmative proximity filter. |
| <a id="rec-boatrental"></a>`boatrental` | Recorded boat-rental availability; also an affirmative proximity filter. |
| <a id="rec-playground"></a>`playground` | Recorded playground availability; also an affirmative proximity filter. |
| <a id="rec-horsetrailers"></a>`horsetrailers` | Recorded horse-trailer parking; also an affirmative proximity filter. `phYes` is displayed as `Yes`. |
| <a id="rec-location"></a>`location` | Mapped point coordinates, latitude then longitude, to five decimal places. Missing geometry is `not recorded`. |
| <a id="rec-info"></a>`info` | Available amenity summary; optional fields must fit one tagged message. |

### Attribute response examples

These response bodies were produced by the current local snapshots. `not recorded` is a valid response; it does not mean `No`.

| Radio message | Response body |
| --- | --- |
| `!rec Briones Overlook Staging Area type` | Briones Overlook Staging Area: type Staging Area. |
| `!rec Briones Overlook Staging Area parking` | Briones Overlook Staging Area: parking Lot. |
| `!rec Briones Overlook Staging Area restrooms` | Briones Overlook Staging Area: restrooms Yes. |
| `!rec Briones Overlook Staging Area water` | Briones Overlook Staging Area: water No. |
| `!rec Briones Overlook Staging Area picnic` | Briones Overlook Staging Area: picnic No. |
| `!rec Briones Overlook Staging Area fishing` | Briones Overlook Staging Area: fishing No. |
| `!rec Briones Overlook Staging Area boatlaunch` | Briones Overlook Staging Area: boatlaunch No. |
| `!rec Briones Overlook Staging Area boatrental` | Briones Overlook Staging Area: boatrental No. |
| `!rec Briones Overlook Staging Area playground` | Briones Overlook Staging Area: playground No. |
| `!rec Briones Overlook Staging Area horsetrailers` | Briones Overlook Staging Area: horsetrailers Yes. |
| `!rec Briones Overlook Staging Area location` | Briones Overlook Staging Area: location 37.91326,-122.20248. |
| `!rec Briones Overlook Staging Area info` | Recreation: Briones Overlook Staging Area \| type Staging Area \| parking Lot \| restroom Yes \| water No \| picnic No \| fishing No \| boat launch No |

### Proximity examples

```text
!rec water near 37.90 -122.20
Nearest recreation: Tilden Steam Trains Park Entrance (1.82 mi map distance) | water Yes.
```

<a id="cmd-peak"></a>
## !peak --> peak details

[Tagged response examples](RESPONSE_EXAMPLES.md#example-peak).

**Program:** [scripts/peak.py](scripts/peak.py). All queries are offline. [Shared syntax](#gis-syntax) applies.

Named example: `!peak Wildcat Peak`. Response:

```text
Peak: Wildcat Peak.
```

### Attribute index

[elevation](#peak-elevation) | [location](#peak-location) | [info](#peak-info)

| Subcommand | Purpose and interpretation |
| --- | --- |
| <a id="peak-elevation"></a>`elevation` | Recorded elevation in feet; does not filter for a minimum height. |
| <a id="peak-location"></a>`location` | Mapped coordinates, latitude then longitude, to five decimal places. |
| <a id="peak-info"></a>`info` | Full peak summary, including coordinates when available. |

### Attribute response examples

These response bodies were produced by the current local snapshots. `not recorded` is a valid response; it does not mean `No`.

| Radio message | Response body |
| --- | --- |
| `!peak Wildcat Peak elevation` | Wildcat Peak: elevation 1200 ft. |
| `!peak Wildcat Peak location` | Wildcat Peak: location 37.91919,-122.26230. |
| `!peak Wildcat Peak info` | Peak: Wildcat Peak \| elevation 1200 ft \| 37.91919,-122.26230. |

### Proximity examples

```text
!peak elevation near 37.90 -122.20
Nearest peak: Eureka Peak (1.54 mi map distance) | elevation 1640 ft.
```

Unnamed peak records are excluded by default. An administrator can enable them in `gis_settings.json`; proximity searches then include their generated identifiers.

<a id="cmd-park"></a>
## !park --> park details and associated features

[Tagged response examples](RESPONSE_EXAMPLES.md#example-park).

**Program:** [scripts/park.py](scripts/park.py). All queries are offline. [Shared syntax](#gis-syntax) applies.

Named example: `!park Pleasanton Ridge`. Response:

```text
Park: Pleasanton Ridge.
```

### Attribute index

[status](#park-status) | [agency](#park-agency) | [trails](#park-trails) | [recreation](#park-recreation) | [info](#park-info)

| Subcommand | Purpose and interpretation |
| --- | --- |
| <a id="park-status"></a>`status` | Recorded land status; values such as Landbank/Parkland do not establish public access or current opening hours. |
| <a id="park-agency"></a>`agency` | Recorded agency name; missing values are `not recorded`. |
| <a id="park-trails"></a>`trails` | Local trail geometries intersecting the park geometry. Intersection does not prove a connected or publicly accessible route. |
| <a id="park-recreation"></a>`recreation` | Local recreation points intersecting the park geometry, subject to result limits. |
| <a id="park-info"></a>`info` | Park status, agency, trails, and recreation associations; source polygon counts are excluded. |

### Attribute response examples

These response bodies were produced by the current local snapshots. `not recorded` is a valid response; it does not mean `No`.

| Radio message | Response body |
| --- | --- |
| `!park Pleasanton Ridge status` | Pleasanton Ridge: status Landbank/Parkland. |
| `!park Pleasanton Ridge agency` | Pleasanton Ridge: agency not recorded. |
| `!park Pleasanton Ridge trails` | Pleasanton Ridge: trails none in local data. |
| `!park Pleasanton Ridge recreation` | Pleasanton Ridge: recreation none in local data. |
| `!park Pleasanton Ridge info` | Park: Pleasanton Ridge [Landbank/Parkland] \| agency not recorded \| Intersecting trails: none in local data \| Recreation: none in local data. |

### Proximity examples

```text
!park near 37.90 -122.20
Nearest park: Tilden (1.52 mi map distance).
```

`!park` searches the configured park layers, including mapped recreation areas. It has no `dogs`, `open`, opening-hours, permit, or reservation subcommand. `!park status near LAT LON` displays the nearest result’s status; it does not select only open parks.


<a id="cmd-boundary"></a>
## !boundary --> mapped areas and trail overlaps

[Tagged response examples](RESPONSE_EXAMPLES.md#example-boundary).

**Program:** [scripts/boundary.py](scripts/boundary.py). This command has category prefixes instead of named-feature attribute suffixes.

```text
!boundary help
!boundary LAT LON
!boundary CATEGORY LAT LON
!boundary near LAT LON [MILES]
!boundary CATEGORY near LAT LON [MILES]
!boundary trail TRAIL_NAME
!boundary CATEGORY trail TRAIL_NAME
```

### Category index

| Prefix | Included areas |
| --- | --- |
| <a id="boundary-parks"></a>`parks` | EBRPD park layers and adjacent local parks; excludes the separate recreation-area polygon layer. |
| <a id="boundary-watersheds"></a>`watersheds` | Watershed boundary polygons. |
| <a id="boundary-reservoirs"></a>`reservoirs` | Reservoir polygons. |
| <a id="boundary-recreation"></a>`recreation` | Recreation-area polygons, distinct from `!rec` facility points. |
| No prefix | All configured boundary layers above. |

A coordinate query uses containment and can return several containing/edge-touching areas, limited by `max_results`. A `near` query without miles returns one closest area, even if several overlap. Adding miles lists areas within that distance. A trail-name query lists polygon intersections, not turn-by-turn directions. `!boundary Bear Creek` and `!boundary NAME info` are unsupported.

Examples:

```text
!boundary 37.90 -122.20
No containing areas in local map data.

!boundary parks near 37.90 -122.20
Nearest park: Tilden (1.52 mi map distance).

!boundary trail Bear Creek
Trail overlaps: Watershed: Contra Costa.
```

Containment entries use labels such as `Inside mapped park: NAME [STATUS]` and `On mapped park boundary: NAME [STATUS]`. The category and recorded park status remain visible. No containment result means only that no matching local polygon covers the coordinate; it is not an assertion that the location lies outside every real-world park. Polygon holes are respected.

<a id="gis-responses"></a>
## GIS response families and errors

| Response body or pattern | Meaning and next step |
| --- | --- |
| `Trail: <name>.` | Feature identification; the category changes with the command. |
| `<name>: <attribute> <value>.` | Focused response. Distinct source values can be joined with `/`. |
| `Nearest trail: ... (distance mi map distance)` | Exactly one closest qualifying feature; no radius was supplied. |
| `Trails within <N> mi: ... (distance mi map distance)` | Explicit-radius search. Result and byte limits still apply. |
| `not recorded` | The local source does not supply the requested attribute; it is not an affirmative or negative policy. |
| `none in local data` | No local spatial association/area/list entry was found. |
| `No matching trail in local data: <name>.` | No exact or partial feature-name match. The command kind changes with the query. |
| `No matching trail for dogs within 5 mi in local data.` | No group passed the dog-policy filter and radius test. This is not a data-load failure. |
| `Multiple matches; enter a full name: ...` | The query was ambiguous. Select a fuller name from the choices. |
| `GIS lookup could not complete: Radius must not exceed 25 miles.` | The requested radius exceeds the current configured maximum. |
| `GIS lookup could not complete: Location is outside the configured GIS search area.` | Coordinates are globally valid but outside the configured calculation bounds. |
| `GIS lookup could not complete: Unknown !trail subcommand: <word>. Use !trail help.` | An unknown attribute was placed before `near`. |
| `Geometry repaired for calculation.` | A geometry required repair in memory for this calculation. This note is retained when applicable. |
| `...` | A description or complete reply reached its configured text limit. |

Malformed query syntax can be rejected by the responder before running Python, or by the command program with `GIS lookup could not complete:`. Examples include `Use near LATITUDE LONGITUDE [RADIUS_MILES].`, `Coordinates and radius must be numbers.`, `Coordinates and radius must be finite.`, `Radius must be positive.`, and the 150-character limit. There is no trailing `Snapshot ...` footer.

A nonzero GIS program exit produces the configured radio response `Local GIS data unavailable. Check snapshots, dependencies, or refresh state.` Direct CLI output can instead show `Local GIS data unavailable; check the datasets, dependencies, or refresh state.` Technical diagnostics go to stderr/service logs. Integrity, dependency, or refresh failures must not be interpreted as empty geographic results.

### Exact affirmative-filter vocabulary

The following source values qualify after stripping surrounding whitespace and case-folding. All grouped records must qualify; missing or conflicting values exclude the group.

| Filter | Accepted source values |
| --- | --- |
| Trail `dogs` | `yes`, `limited to park hours` |
| Trail `horses` | `yes` |
| Trail `bikes` | `yes`, `yes l` |
| Recreation `parking` | `yes`, `lot`, `limited` |
| Recreation `restrooms` | `yes`, `ada` |
| Recreation `water`, `picnic`, `fishing`, `boatlaunch`, `boatrental`, `playground` | `yes` |
| Recreation `horsetrailers` | `phyes`, `yes` |

These values describe the stored source vocabulary, not an interpretation of current legal access or opening conditions. Mappings are maintained in `ATTRIBUTE_FIELDS` and `FILTER_VALUES` in [scripts/gis_lookup.py](scripts/gis_lookup.py).

<a id="settings"></a>
## Administrator settings and deployment options

Radio users do not edit these settings through commands. Read the [installation guide](../INSTALL.md) for OS-service paths and the [multi-channel guide](MULTI_CHANNEL_GUIDE.md) for permissions and channel assignments.

<a id="timezone"></a>
### One persistent reply timezone

Set `responder.timezone` in the active `config.json`, then restart. The default is `America/Los_Angeles`, with automatic PST/PDT handling. Other IANA zones, such as `America/Denver`, are supported. This is one setting shared by all MeshCore programs; there is no radio timezone flag.

| Deployment | Active config |
| --- | --- |
| Linux OS service | `/etc/meshcore-ems/config.json` |
| Windows OS service | `C:\ProgramData\MeshCore-EMS\config.json` |
| Source-folder launch | The platform package's `config.json` |

It controls the host-clock reply, AQI observation times, river report/reading times, and lightning windows. Installer upgrades preserve an existing value. Child programs receive `MESHCORE_TIMEZONE`; custom programs must use it when formatting timestamps. UTC storage, MQTT timestamps, source interpretation, and elapsed timers are unchanged. Undated/recurring Caltrans schedules retain their source-Pacific label. Separate satellite tools do not use this MeshCore setting.

### Command registration and limits

Each shipped command has its own executable Python entry point in `scripts/`. `responder.commands` selects `script`, fixed `args`, input type, channel IDs, and optional `timeout`, `max_reply_parts`, and `error_reply`. Empty channel assignments disable a command on the radio. Registration changes require a restart.

The table below records shipped defaults, not a guarantee about an operator's edited installation. Flood-alarm enrollment is handled by the service; scheduled reading subprocesses have a 90-second timeout.


| Command | Program | Input type | Timeout (seconds) | Maximum reply parts |
| --- | --- | --- | ---: | ---: |
| `!status` | [scripts/status.py](scripts/status.py) | `none` | 20 | 1 |
| `!time` | [scripts/time_now.py](scripts/time_now.py) | `none` | 20 | 1 |
| `!aqi` | [scripts/airnow_aqi.py](scripts/airnow_aqi.py) | `coordinates` | 60 | 1 |
| `!traffic` | [scripts/highway_info.py](scripts/highway_info.py) | `route_number` | 30 | 1 |
| `!rivers` | [scripts/nearby_river_stations.py](scripts/nearby_river_stations.py) | `coordinates` | 40 | 1 |
| `!uv` | [scripts/uv_index.py](scripts/uv_index.py) | `location` | 35 | 1 |
| `!heatadv` | [scripts/heat_adv.py](scripts/heat_adv.py) | `location` | 45 | 1 |
| `!floodwarn` | [scripts/flood_warn.py](scripts/flood_warn.py) | `water_query` | 90 | 1 |
| `!snowpack` | [scripts/snowpack.py](scripts/snowpack.py) | `location` | 65 | 1 |
| `!floodalarm` | [scripts/floodalarm.py](scripts/floodalarm.py) | `water_query` | 90 | 1 |
| `!lightning` | [scripts/lightning.py](scripts/lightning.py) | `location` | 60 | 1 |
| `!trail` | [scripts/trail.py](scripts/trail.py) | `gis_query` | 30 | 1 |
| `!rec` | [scripts/rec.py](scripts/rec.py) | `gis_query` | 30 | 1 |
| `!peak` | [scripts/peak.py](scripts/peak.py) | `gis_query` | 30 | 1 |
| `!park` | [scripts/park.py](scripts/park.py) | `gis_query` | 30 | 1 |
| `!boundary` | [scripts/boundary.py](scripts/boundary.py) | `gis_query` | 30 | 1 |
| `!firezone` | [scripts/firezone.py](scripts/firezone.py) | `fire_query` | 45 | 1 |
| `!fires` | [scripts/fires.py](scripts/fires.py) | `fire_query` | 45 | 1 |
| `!fire` | [scripts/fire.py](scripts/fire.py) | `fire_query` | 45 | 1 |
| `!firewx` | [scripts/firewx.py](scripts/firewx.py) | `fire_query` | 45 | 1 |
| `!firewarn` | [scripts/firewarn.py](scripts/firewarn.py) | `fire_query` | 45 | 1 |
| `!firedata` | [scripts/firedata.py](scripts/firedata.py) | `fire_query` | 45 | 1 |
| `!firealarm` | [scripts/firealarm.py](scripts/firealarm.py) | `fire_query` | 45 | 1 |
| `!smoke` | [scripts/smoke.py](scripts/smoke.py) | `fire_query` | 45 | 1 |
| `!firedanger` | [scripts/firedanger.py](scripts/firedanger.py) | `fire_query` | 45 | 1 |
| `!slidewarn` | [scripts/slidewarn.py](scripts/slidewarn.py) | `slide_query` | 45 | 1 |
| `!slidealarm` | [scripts/slidealarm.py](scripts/slidealarm.py) | `slide_query` | 45 | 1 |
| `!slideinfo` | [scripts/slideinfo.py](scripts/slideinfo.py) | `slide_query` | 45 | 1 |
| `!waterway` | [scripts/waterway.py](scripts/waterway.py) | `water_query` | 90 | 1 |
| `!basin` | [scripts/basin.py](scripts/basin.py) | `water_query` | 90 | 1 |
| `!floodstatus` | [scripts/floodstatus.py](scripts/floodstatus.py) | `water_query` | 90 | 1 |

Global defaults are `script_timeout=20`, `max_output_bytes=65536`, `sender_cooldown=30`, `max_message_age=300`, `max_pending=50`, and `max_pending_per_channel=20`. Radio transmission spacing uses top-level `command_interval=5`. Older part-limit settings do not enable automatic continuation. Flood check interval and expiry are `CHECK_INTERVAL` and `MAX_AGE` in `flood_alarm.py`, not per-request arguments.

### GIS settings

Each dedicated GIS program accepts `--settings PATH` for an alternate JSON file. By default, `gis_settings.json` beside the source configuration is loaded even when the runner uses an external `config.json`. Relative dataset paths resolve against the settings file. For an installed external file, set each GIS registration’s `args` to `["--settings", "/absolute/path/gis_settings.json"]`. Settings are read for each lookup; registration changes still require a service restart.

| Setting | Default | Purpose |
| --- | --- | --- |
| `data_directory` | `"../data/ebmud"` | Local EBMUD manifest and datasets; directory must be readable by the service account. |
| `maximum_radius_miles` | `25.0` | Maximum positive, explicitly supplied radius. No-radius queries still select exactly one nearest result. |
| `max_results` | `3` | Maximum listed matches or associations; valid range 1–20. |
| `max_reply_bytes` | `480` | Legacy GIS setting; radio delivery always uses the shared 150-byte tagged budget. |
| `description_characters` | `100` | Source narrative limit; zero suppresses descriptions, maximum 500. |
| `include_unnamed_peaks` | `false` | Include unnamed peak records in local peak searches. |
| `projected_crs` | `"EPSG:32610"` | Projected CRS with metre units for spatial calculations. |
| `search_bounds` | `[-126.0, 0.0, -120.0, 84.0]` | [west, south, east, north] bounds accepted for query coordinates. |

Older `default_radius_miles` settings are ignored. Field aliases, layer selection, and affirmative values are explicit constants in the GIS helper modules. These settings do not automatically connect the California State Parks collection to the commands.

<a id="python-programs"></a>
## Direct Python invocation and options

Run these from the appropriate platform service folder using its configured Python environment. These are **terminal commands**, not MeshCore messages. Direct program output omits the `@sender` prefix and radio sender tagging. `--help` is only supported where the program uses an argument parser; it is not a universal radio or script option.

| Program | Direct example | Options and result |
| --- | --- | --- |
| `status.py` | `python scripts/status.py` | Prints the fixed smoke-response body. |
| `time_now.py` | `python scripts/time_now.py` | Prints the host clock using `MESHCORE_TIMEZONE`, otherwise Pacific. |
| `airnow_aqi.py` | `python scripts/airnow_aqi.py 37.7749 -122.4194` | Two positional coordinates; requires `AIRNOW_API_KEY`. |
| `highway_info.py` | `python scripts/highway_info.py 80` | Positional route number. Omitting it invokes the interactive CLI prompt; the responder always supplies it. |
| `nearby_river_stations.py` | `python scripts/nearby_river_stations.py --latitude 39 --longitude -121 --radius 15 --timeout 15 --mesh-text` | `--latitude`, `--longitude`, `--radius` in miles, `--timeout` in seconds, and `--mesh-text`. Without `--mesh-text`, outputs JSON with richer report/history data. |
| `uv_index.py` | `python scripts/uv_index.py "Reno NV"` | Location text or coordinates; prints a UV response or error. |
| `heat_adv.py` | `python scripts/heat_adv.py Sacramento` | Location text or coordinates; prints heat response lines or an error. |
| `lightning.py` | `python scripts/lightning.py --timezone America/Denver "Reno NV"` | Optional leading `--timezone ZONE` for standalone use only. Service requests override it with the shared zone. |
| `flood_warn.py` | `python scripts/flood_warn.py Sacramento` | Location-pinned official-alert text; `--snapshot` or `--json` returns structured output. |
| `floodalarm.py` | `python scripts/floodalarm.py Sacramento` | Text snapshot; add `--snapshot` for structured point, official alerts and categorical conditions. Does not create a subscription. |
| `waterway.py`, `basin.py`, `floodstatus.py` | `python scripts/floodstatus.py --json 38.61 -122.83` | Same location grammar as radio commands; `--json`/`--snapshot` exposes the complete bounded snapshot. |
| `snowpack.py` | `python scripts/snowpack.py Truckee` | California location; prints snow summary or error. |
| Dedicated GIS programs | `python scripts/trail.py "Bear Creek dogs"` | `trail.py`, `rec.py`, `peak.py`, `park.py`, `boundary.py` select their own behavior. Optional `--settings PATH`; positional query follows radio grammar, without the command word. |
| GIS shared helper compatibility | `python scripts/gis_lookup.py --kind trail --query "Bear Creek dogs"` | `--kind`, `--query`, and optional `--settings`. The bundled radio registrations use dedicated programs instead. |

For implementation-level function signatures, use [FUNCTION_REFERENCE.md](FUNCTION_REFERENCE.md). The [EBMUD data guide](../data/ebmud/README.md) documents manual refresh/repair. The [California State Parks reference](../data/california_state_parks/README.md) has a separate local loader and source provenance. These paths require a complete workspace; standalone service ZIPs contain only their platform package. The [satellite catalog](../satellite_database/README.md) is a separate CLI and has no shipped bot command.

<a id="errors"></a>
<a id="troubleshooting"></a>
## Troubleshooting and general failure responses

| Symptom or response | Interpretation and action |
| --- | --- |
| No reply | Check the command spelling, assigned channel, bot availability, sender cooldown, message age, and radio reachability. Unknown commands and unassigned channels are ignored. |
| A tagged `Use ...` response | The command was recognized but its arguments failed validation. Correct the syntax and wait for cooldown before retrying. |
| `The requested script timed out or exceeded its output limit.` | The subprocess exceeded its time or captured-output budget. This response can replace a command-specific availability fallback. |
| `The requested script failed.` | Generic fallback when a failed command has no configured `error_reply`. Detailed diagnostics stay in service logs. |
| `The script returned no text.` | Successful execution produced no printable output. |
| Provider-specific coverage or lookup error | The location or data source could not support a result. Do not treat it as a clear-weather, open-road, or no-hazard assertion. |
| Missing optional fields or a shortened name | One tagged message must fit 150 UTF-8 bytes. Request an independent focused GIS field; use supported local JSON for full structured data. Raising legacy part limits does not enable continuation. |
| Unexpected GIS feature or no match | Check the exact mapped name, query coordinates, and dataset coverage. These commands search EBMUD-area references, not statewide data. |
| Flood subscription not started | Check location ambiguity or NWS coverage failure; resend with coordinates. `status` shows active monitoring. |
| No flood notification despite a new bulletin | Only material changes to current location-matched alerts trigger updates. Check subscription status, source availability, radio spacing and expiry; unchanged alerts remain silent. |
| Clock or forecast times appear shifted | Confirm the host clock and persistent `responder.timezone`; no user radio override exists. |

Recognized malformed requests can consume the sender cooldown. Repeated commands do not force a response. Long results and queued transmissions can delay replies. A locally accepted send does not prove reception by another radio.

<a id="verification"></a>
## Source coverage and verification

This guide was checked against the paired `config.json` files, command parsers, formatters, GIS settings, and local snapshots. The 52 GIS example bodies used while preparing this reference matched across both platform packages. Weather values and timestamps shown here are illustrative; no live-provider or physical-radio claim is made by this documentation check.

The GIS examples use only local EBMUD data. California State Parks repair provenance and flagged area changes remain in its separate data guide. Snapshot information can differ from current access policies, facility operation, and surveyed boundaries.

Relevant developer checks, from either platform folder:

```console
python -m unittest discover -s tests -p "test_command_programs.py" -v
python -m unittest discover -s tests -p "test_gis*.py" -v
```

The [platform README](README.md) supplies installation and provider-specific details. The [user guide](BOT_USER_GUIDE.md) supplies short radio examples. These maintained source guides are included in future package inventories; updating them does not rebuild existing installer or ZIP artifacts.


<a id="cmd-firezone"></a>
## !firezone - Interstate fire-weather zones and warning status

[Tagged response examples](RESPONSE_EXAMPLES.md#example-firezone).

**Example:** `!firezone CAZ272`. **Program:** [scripts/firezone.py](scripts/firezone.py).

See the [wildfire guide](WILDFIRE_GUIDE.md#radio-commands) for syntax, source interpretation, concise response priorities, and errors. Locations accept zone IDs, coordinates, ZIP codes, or city/state. Missing or stale data is distinguished from a successful empty result.

<a id="cmd-fires"></a>
## !fires - Current reported incidents and mapped boundaries

[Tagged response examples](RESPONSE_EXAMPLES.md#example-fires).

**Example:** `!fires CAZ272`. **Program:** [scripts/fires.py](scripts/fires.py).

See the [wildfire guide](WILDFIRE_GUIDE.md#radio-commands) for syntax, source interpretation, concise response priorities, and errors. Locations accept zone IDs, coordinates, ZIP codes, or city/state. Missing or stale data is distinguished from a successful empty result.

<a id="cmd-fire"></a>
## !fire - Incident containment and source detail

[Tagged response examples](RESPONSE_EXAMPLES.md#example-fire).

**Example:** `!fire INCIDENT-ID`. **Program:** [scripts/fire.py](scripts/fire.py).

See the [wildfire guide](WILDFIRE_GUIDE.md#radio-commands) for syntax, source interpretation, concise response priorities, and errors. Use an exact incident identifier or unambiguous name from `!fires`. Last-known records are explicitly labelled; disappearance never means extinguishment.

<a id="cmd-firewx"></a>
## !firewx - Zone fire-weather forecast

[Tagged response examples](RESPONSE_EXAMPLES.md#example-firewx).

**Example:** `!firewx CAZ272`. **Program:** [scripts/firewx.py](scripts/firewx.py).

See the [wildfire guide](WILDFIRE_GUIDE.md#radio-commands) for syntax, source interpretation, concise response priorities, and errors. Locations accept zone IDs, coordinates, ZIP codes, or city/state. Missing or stale data is distinguished from a successful empty result.

<a id="cmd-firewarn"></a>
## !firewarn - Red Flag Warnings and Fire Weather Watches

[Tagged response examples](RESPONSE_EXAMPLES.md#example-firewarn).

**Example:** `!firewarn CAZ272`. **Program:** [scripts/firewarn.py](scripts/firewarn.py).

See the [wildfire guide](WILDFIRE_GUIDE.md#radio-commands) for syntax, source interpretation, concise response priorities, and errors. Locations accept zone IDs, coordinates, ZIP codes, or city/state. Missing or stale data is distinguished from a successful empty result.

<a id="cmd-firedata"></a>
## !firedata - Supporting observations and outlooks

[Tagged response examples](RESPONSE_EXAMPLES.md#example-firedata).

**Example:** `!firedata raws CAZ272`. **Program:** [scripts/firedata.py](scripts/firedata.py).

See the [wildfire guide](WILDFIRE_GUIDE.md#radio-commands) for syntax, source interpretation, concise response priorities, and errors. Categories include RAWS, AQI, smoke, satellite detections, cameras, outlooks, treatments and history; optional feeds require administrator enablement or an explicit refresh.

<a id="cmd-firealarm"></a>
## !firealarm - Temporary wildfire change monitoring

[Tagged response examples](RESPONSE_EXAMPLES.md#example-firealarm).

**Example:** `!firealarm on CAZ272`. **Program:** [scripts/firealarm.py](scripts/firealarm.py).

See the [wildfire guide](WILDFIRE_GUIDE.md#radio-commands) for syntax, source interpretation, concise response priorities, and errors. Only the running service enrolls subscriptions. Use `status` or `off` to inspect/cancel; the default lifetime is four hours.

<a id="cmd-smoke"></a>
## !smoke - Point smoke and air quality

[Tagged response examples](RESPONSE_EXAMPLES.md#example-smoke).

**Examples:** `!smoke 96150`, `!smoke South Lake Tahoe CA`, `!smoke 39.25, -119.96`.
**Program:** [scripts/smoke.py](scripts/smoke.py).

Replies start with `Smoke:` and omit the location header, `Monitor:` and `PM10:`
lines. Mapped smoke versus surface exposure and missing-data uncertainty take
priority. PM2.5 AQI/category and observation time may fit. Local JSON retains
geometry, nearest-edge distance, available ozone, PM concentrations, monitor
metadata, and unknown source-fire attribution. Missing coverage is not clean air.
See [smoke behavior and data limits](WILDFIRE_GUIDE.md#smoke-response).

<a id="cmd-firedanger"></a>
## !firedanger - Point fuel-energy potential

[Tagged response examples](RESPONSE_EXAMPLES.md#example-firedanger).

**Examples:** `!firedanger 96150`, `!firedanger Reno NV`, `!firedanger 39.25 -119.96`.
**Program:** [scripts/firedanger.py](scripts/firedanger.py).

Summarizes the highest-priority official warning or qualified local ERC context.
ERC, percentile, source time, and station name are optional radio fields; local
JSON retains the available trend, Burning Index, fuels, and weather context.
Detailed fuel moisture requires optional FEMS access. Percentile descriptions
are not official fire-danger ratings or ignition probabilities. Both new commands
accept locations rather than zone IDs and do not enroll monitoring.
See [fire-danger interpretation](WILDFIRE_GUIDE.md#fire-danger-response) and
[optional FEMS setup](WILDFIRE_GUIDE.md#optional-fems-fuel-moisture).

<a id="cmd-slidewarn"></a>
## !slidewarn: California and Nevada landslide-related alerts

[Tagged response examples](RESPONSE_EXAMPLES.md#example-slidewarn).

`!slidewarn LOCATION` accepts California/Nevada ZIP, city/state, or decimal latitude/longitude. Bare cities default to California; use `Reno NV` or `Las Vegas Nevada` for Nevada cities.
Examples: `!slidewarn 91107`, `!slidewarn Pasadena`, `!slidewarn 34.15, -118.14`.
Returns effective actual NWS products with explicit landslide/debris-flow wording,
including watches, retaining original event names, source times, and instructions.
Precautionary/qualified mentions are labelled. A fresh empty result is not an
all-clear; failed, malformed, or incomplete data reports unavailable. The highest-priority alert is summarized. Optional expiration and target fields
may fit; local `--json` retains all matching records and source links.

<a id="cmd-slidealarm"></a>
## !slidealarm: temporary California/Nevada alert monitoring

[Tagged response examples](RESPONSE_EXAMPLES.md#example-slidealarm).

`!slidealarm on LOCATION` starts or replaces a sender/channel subscription after
fresh data is available. Defaults: checks every five minutes, expiry after four
hours. `!slidealarm status` does not renew; `!slidealarm off` cancels pending and
active monitoring. Subsequent checks use the original resolved GPS point.
New/content-updated alerts, expiry, cancellation when supplied, and feed
removals generate notifications. Outages retain the last baseline and produce
one outage/recovery notification. Standalone Python calls never enroll.

<a id="cmd-slideinfo"></a>
## !slideinfo: California monitoring station information

[Tagged response examples](RESPONSE_EXAMPLES.md#example-slideinfo).

`!slideinfo LOCATION` (optional `near LOCATION`) returns the nearest eligible
station from the reviewed USGS California catalog. Distance is geodesic and does
not imply local warning coverage. Radio replies prioritize the station ID and
telemetry/coverage uncertainty, followed by distance and the complete station name
when space permits. Nothing follows the station name. Catalog metadata and source
links remain available in local `--json` output. Highway 50 is discontinued and
excluded from ranking. Nevada locations are accepted; the reviewed source lists
no Nevada stations, so these queries also rank California stations.

All three programs have dedicated executables, `--json` output, a 45-second timeout,
and one reply message. Alarm `--snapshot` is the service's structured interface.
Settings are under `responder.landslide`; no new API key or OS service is required.
See the [landslide guide](LANDSLIDE_GUIDE.md) for source selection, cache semantics,
subscription lifecycle, geographic limits, and upgrade/channel assignment steps.
