# MeshCore bot command and response reference

This reference describes the 16 shipped commands in [config.json](config.json), their radio inputs, response families, and administrator options. Linux and Windows use the same command behavior. Installed channel assignments and settings can differ from these defaults. For a shorter introduction, see the [MeshCore user guide](BOT_USER_GUIDE.md).

## Quick navigation

- [Sending commands and reading replies](#sending)
- [Coordinates, places, and names](#input)
- [All commands](#command-index)
- [Status](#cmd-status), [time](#cmd-time), [air quality](#cmd-aqi), [traffic](#cmd-traffic), [rivers](#cmd-rivers), [UV](#cmd-uv)
- [Heat alerts](#cmd-heatadv), [lightning](#cmd-lightning), [flood alerts](#cmd-floodwarn), [flood monitoring](#cmd-floodalarm), [snowpack](#cmd-snowpack)
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
| 15-second command transmission spacing | Long or queued replies can take several minutes. Spacing applies between radio transmissions, not just between complete answers. |
| 150-byte radio reply limit | Every part includes `@sender`. Unicode uses multiple bytes; a 150-byte limit is not a 150-character limit. |
| Part caps | Four parts by default; heat/flood/flood-alarm commands allow 12, lightning 64, GIS commands six. Excess text ends in `...`. |
| Message freshness | Messages older than 300 seconds or more than 60 seconds in the future are ignored. |
| Duplicate detection | Repeated packets do not run the same request again. |
| Channel assignments | A recognized command on an unassigned channel produces no response. |

Reply examples below are **body text** unless `@Alice` is shown. Newlines from a Python program are flattened into spaces before radio transmission. Splitting can occur within a word; there are no automatic numbered part labels. Live-provider examples are illustrative, not current observations. GIS examples are actual outputs from the checked local snapshot and can change after refresh.

<a id="input"></a>
## Coordinates, places, and names

| Input family | Accepted forms | Commands |
| --- | --- | --- |
| No arguments | Exact command only | `!status`, `!time` |
| Decimal coordinates | `38.5816 -121.4944` or `38.5816, -121.4944` | `!aqi`, `!rivers` |
| Route number | Digits from 1 through 999, such as `80` | `!traffic` |
| Location | GPS, five-digit US ZIP, ZIP+4, city, or city plus state | `!uv`, `!heatadv`, `!lightning`, `!floodwarn`, `!floodalarm`, `!snowpack` |
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
| [!floodwarn](#cmd-floodwarn) | One-time flood-alert lookup | `!floodwarn Sacramento` |
| [!floodalarm](#cmd-floodalarm) | Register temporary flood-change monitoring | `!floodalarm Sacramento` |
| [!snowpack](#cmd-snowpack) | Current snow depth and forecast new snowfall | `!snowpack Truckee` |
| [!trail](#cmd-trail) | Local trail details and policy searches | `!trail Bear Creek dogs` |
| [!rec](#cmd-rec) | Local recreation amenities | `!rec water near 37.90 -122.20` |
| [!peak](#cmd-peak) | Local peak elevation or coordinates | `!peak Wildcat Peak elevation` |
| [!park](#cmd-park) | Local park status and associations | `!park Pleasanton Ridge status` |
| [!boundary](#cmd-boundary) | Mapped area containment or overlap | `!boundary trail Bear Creek` |

<a id="cmd-status"></a>
## !status — local responder

**Syntax:** `!status` with no arguments. **Program:** [scripts/status.py](scripts/status.py).

```text
@Alice Local command service is running.
```

This is a local smoke response. It does not check the weather providers, dataset currency, every radio route, or delivery to other recipients. Additional text, such as `!status help`, does not match this command. There are no radio subcommands or per-request options.

<a id="cmd-time"></a>
## !time — host time

**Syntax:** `!time` with no arguments. **Program:** [scripts/time_now.py](scripts/time_now.py).

Illustrative response:

```text
@Alice Current time: 2026-10-14 14:30:00 PDT
```

The format is `Current time: YYYY-MM-DD HH:MM:SS ZONE`. This uses the host clock and the persistent [reply timezone](#timezone), not the location of the requesting radio. There is no radio timezone argument. Incorrect host time can also affect message-age acceptance and provider freshness checks.

<a id="cmd-aqi"></a>
## !aqi — air quality

**Syntax:** `!aqi LATITUDE LONGITUDE`. **Program:** [scripts/airnow_aqi.py](scripts/airnow_aqi.py). The bot host requires internet access and an `AIRNOW_API_KEY` environment setting.

```text
!aqi 37.7749 -122.4194
!aqi 37.7749, -122.4194
```

Output fields, before radio flattening and splitting:

```text
AQI: <integer>
PM2.5: <concentration and unit, or N/A>
Rating: <category>
Station: <monitor name>
Distance: <distance> km
Observed: <timestamp in the reply timezone>
Data status: Preliminary
```

Ratings include `Good`, `Moderate`, `Sensitive`, `Unhealthy`, `Very Unhealthy`, and `Hazardous`. The reading comes from a monitoring station, not a sensor at the submitted point. A missing concentration can be `N/A` even when AQI is available. No city, ZIP, pollutant selector, or custom radius is accepted over the radio.

Missing/invalid coordinates return a usage reply. A failed script returns `AirNow lookup unavailable. Check the service AIRNOW_API_KEY setting or try again later.` A subprocess timeout has the separate [timeout response](#errors).

<a id="cmd-traffic"></a>
## !traffic — highway restrictions

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
## !rivers — nearby river stations

**Syntax:** `!rivers LATITUDE LONGITUDE`. **Program:** [scripts/nearby_river_stations.py](scripts/nearby_river_stations.py). CDEC/NOAA data; internet required, no API key.

```text
!rivers 39.0 -121.0
```

The default search radius is **15 miles**, with nearest stations first. Response template:

```text
CDEC report: <issued time>. Within 15 mi: <ID> <station name> (<distance> mi): stage <value> ft at <reading time>; AS <value> ft, FS <value> ft.
```

`AS` means action stage; `FS` means minor flood stage. Missing values are `N/A`; an unparseable issuance time is `unknown report time`. Available timestamps use the shared reply zone. An empty search returns `No matching river stations found within 15 mi.` Provider failures return `River station lookup unavailable. Please try again later.`

Long lists can be truncated by the four-part default. This is a report lookup, not a water-level forecast or a subscription. There is no radio radius option: `!rivers 39 -121 30` is invalid. An administrator can adjust the fixed radius through the [standalone program arguments](#python-programs).

<a id="cmd-uv"></a>
## !uv — current ultraviolet index

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
## !heatadv — heat alerts

**Syntax:** `!heatadv LOCATION`. **Program:** [scripts/heat_adv.py](scripts/heat_adv.py). NWS point coverage and active alerts; internet required, no API key.

```text
!heatadv Sacramento
!heatadv 95814
!heatadv Reno NV
!heatadv 38.5816 -121.4944
```

Response bodies preserve the supplied location apart from repeated whitespace:

```text
There is no Heat Advisories for <location>
Advisory: Extreme Heat Warning for <location>
Advisory: Extreme Heat Watch for <location>
Heat Advisory for <location>
```

Every distinct applicable type is included in warning/watch/advisory order. Legacy Excessive Heat Warning/Watch names are mapped to Extreme Heat Warning/Watch. Expired, cancelled, test, and not-yet-effective alerts are excluded; an already effective watch can concern a future event. The no-advisories wording is the actual response contract.

Unverified NWS coverage, missing/incomplete data, or failed requests return explanatory error text rather than a no-alert assertion. The nonzero-exit fallback is `Heat alert lookup unavailable. Please try again later.` This is a one-time lookup; there are no radio thresholds, subscription flags, or forecast-day options.

<a id="cmd-lightning"></a>
## !lightning — 24-hour lightning potential

**Syntax:** `!lightning LOCATION`. **Program:** [scripts/lightning.py](scripts/lightning.py). NWS point alerts and forecast-grid weather, thunderstorm probability, and lightning activity levels; internet required, no API key.

```text
!lightning Sacramento
!lightning 95814
!lightning 38.5816, -121.4944
```

Response templates:

```text
Lightning Strike Warning for <location> at <time window> (<stated chance/level>)
No Lightning expected for <location> in the next 24h
```

Illustrative hazard response:

```text
Lightning Strike Warning for Sacramento at 2026-10-14 13:00 PDT-16:00 PDT (slight chance thunderstorms)
```

The window covers exactly 24 elapsed hours from the original request, including across daylight-saving changes. Ongoing intervals start at the request time, and later intervals are clipped at the endpoint. Multiple windows retain individual chance levels. Slight chance, positive thunderstorm probabilities, and dry-lightning indicators qualify. Missing probability is `chance not stated`; rain probability is not substituted for lightning probability.

Known hazards remain visible when an additional NWS input fails, with `additional NWS data unavailable`. A partial empty result produces an error rather than a false clear. Malformed responses can produce `Lightning lookup unavailable: invalid service response.` The nonzero-exit fallback is `Lightning lookup unavailable. Please try again later.`

`Lightning Strike Warning` is a program summary label, not a standalone official NWS lightning warning. Forecast intervals do not predict individual strike times. No radio radius, duration, timezone override, or ongoing monitoring option exists. The 64-part ceiling permits long forecast results; transmission can take considerable time.

<a id="cmd-floodwarn"></a>
## !floodwarn — one-time flood alerts

**Syntax:** `!floodwarn LOCATION`. **Program:** [scripts/flood_warn.py](scripts/flood_warn.py). NWS point alerts; internet required, no API key.

```text
!floodwarn Sacramento
!floodwarn Reno Nevada
!floodwarn 38.5816 -121.4944
```

Clear response: `no flooding events declared for Sacramento`.

When active, the supplied location precedes the applicable descriptions in this order:

| Alert | Response description |
| --- | --- |
| Flash Flood Warning 🟥 | Life-threatening flash flooding is imminent or occurring. Move to higher ground immediately. |
| Flood Warning 🟧 | Flooding is imminent or occurring. Take necessary precautions now. |
| Flood Advisory 🟨 | Minor flooding expected. May cause inconvenience but not typically life-threatening. |
| Flood Watch 🟦 | Conditions favorable for flooding. Stay alert and be ready to take action. |

A body is formatted as `<location>: <alert> <square> - <description>`, with each distinct type included once. The responder flattens and splits the result. Coastal/lakeshore alerts and general flood statements are outside this four-type lookup. Coverage and response validation must succeed before a no-events result is produced.

Invalid input uses the location usage response. Coverage/provider failures return explanatory text; malformed responses can return `Flood alert lookup unavailable: invalid service response.` The configured nonzero-exit fallback is `Flood alert lookup unavailable. Please try again later.` This command never creates, renews, or cancels a flood subscription.

<a id="cmd-floodalarm"></a>
## !floodalarm — temporary flood-change monitoring

**Syntax:** `!floodalarm LOCATION`. **Program:** [scripts/floodalarm.py](scripts/floodalarm.py), with persistent scheduling in [flood_alarm.py](flood_alarm.py) and [responder.py](responder.py).

```text
!floodalarm Sacramento
```

Accepted requests queue the acknowledgment:

```text
@Alice Flood Alarm is set for requested location.
```

The acknowledgment confirms registration, before remote location/coverage lookup. It is not an immediate all-clear or active-alert report. Use `!floodwarn` separately for an immediate lookup, observing the sender cooldown.

1. The first successful lookup becomes a silent baseline.
2. While the service runs, checks are due every **20 minutes**. Busy services can delay them.
3. A change in the set of the four supported flood-alert types produces the normal flood response on the original channel, tagged to the saved sender. This includes clearing alerts.
4. Monitoring expires **four hours** after the last accepted `!floodalarm` call. A repeat renews expiry and replaces that sender's saved location on that channel.
5. Repeating the same active location retains its baseline and scheduled check. A different location starts a fresh baseline.
6. A failed lookup preserves the last good result and produces one availability notice per failure episode. Subsequent scheduled checks retry. An error is never an all-clear.

An error notice starts `Flood Alarm for <location>: <error detail>`. A failed subprocess reading can include `Flood alert lookup unavailable. Will retry at the next check.` Notifications depend on the host, provider connection, and radio remaining available.

There is no shipped radio `cancel`, `stop`, interval, or duration subcommand. Monitoring expires automatically; `!floodalarm stop` is not a cancellation request. State survives restarts, but restarts do not extend expiry. Two nodes sharing a display name on the same channel share the subscription. Standalone Python execution reads a single structured snapshot and does **not** enroll monitoring.

<a id="cmd-snowpack"></a>
## !snowpack — snow depth and forecast snowfall

**Syntax:** `!snowpack LOCATION`, California only. **Program:** [scripts/snowpack.py](scripts/snowpack.py). CDEC hourly snow-depth stations and NWS snowfall forecast grid; internet required, no API key.

```text
!snowpack Truckee
!snowpack 96161
!snowpack 39.3279 -120.1833
```

Illustrative response:

```text
Snowpack: Current: 12in | Next 24h: 4in | Station: Snow Creek 2.3mi.
```

`Current` is observed depth at the nearest active hourly snow-depth station. `Next 24h` is forecast new snowfall at the requested location over the rolling 24 hours. It is not snow-water equivalent. The station distance is straight-line distance in miles. A stale/missing reading does not silently select a farther station.

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
- With a positive radius, matches inside it are listed nearest first. The default maximum explicit radius is 25 miles and default result cap is three. `+N more` reports omitted list entries; byte limits can further truncate text.
- Bare `LAT LON` also selects one nearest feature for these four commands. Only `near` accepts a third radius number.
- An attribute goes **after a name** or **before `near`**. There is no combined name-plus-near grammar, multiple-attribute selector, or sorting flag.
- `dogs`, `horses`, `bikes`, and the recreation amenity selectors filter for affirmative source values before proximity ranking. Other attributes, such as `elevation`, select the nearest feature and display that field; they do not filter by its value.
- Missing, negative, unknown, or conflicting grouped policy values fail an affirmative filter. Conditional source wording remains visible. A named lookup can still report `No` or `not recorded`.

Distances use the nearest part of the complete projected geometry, not its centroid. A containing polygon can be 0.00 mi away. These are map distances, not road/walking distances, routes, or estimates of access. The default calculation area is bounded by longitude -126 through -120 and latitude 0 through 84; this bounds the projection, not the actual data coverage. A closest result can therefore be distant from a location without nearby source features.

GIS input is limited to 150 characters. City names, ZIPs, addresses, and arbitrary command flags are not geocoded. Unrecognized suffix words can be interpreted as part of a feature name; use the exact attribute spellings below.

<a id="cmd-trail"></a>
## !trail — trail details

**Program:** [scripts/trail.py](scripts/trail.py). All queries are offline. [Shared syntax](#gis-syntax) applies.

Named example: `!trail Bear Creek`. Response:

```text
Trail: Bear Creek. Subcommands: dogs, horses, bikes, length, difficulty, gain, surface, shade, time, start, areas, description, info.
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
| <a id="trail-description"></a>`description` | Source trail narrative, limited by `description_characters`; zero yields `description omitted by settings`. |
| <a id="trail-info"></a>`info` | Full available trail summary, bounded by reply limits. |

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
| `!trail Bear Creek info` | Trail: Bear Creek; 5.41 mi; Moderate; gain 592 ft; surface Dirt; sun Full Shade; dogs No; horses Yes; bikes No. Estimated time 1.8 hr (3 mph; terrain excluded). Mapped start 37.92638,-122.16296. Overlaps: Watershed: Contra Costa. This trail traverses the southeast slopes of the Briones Reservoir. It is moderately steep in a few... |

### Proximity examples

```text
!trail dogs near 37.90 -122.20
Closest, map distance: Trail: Oursan (0.84 mi); dogs Yes.
```

```text
!trail dogs near 37.90 -122.20 5
Within 5 mi, map distance: Trail: Oursan (0.84 mi); dogs Yes; Trail: Old San Pablo Trail (0.97 mi); dogs Limited to Park Hours; Trail: Hampton (2.65 mi); dogs Yes; +11 more.
```

<a id="cmd-rec"></a>
## !rec — recreation amenities

**Program:** [scripts/rec.py](scripts/rec.py). All queries are offline. [Shared syntax](#gis-syntax) applies.

Named example: `!rec Briones Overlook Staging Area`. Response:

```text
Recreation: Briones Overlook Staging Area. Subcommands: type, parking, restrooms, water, picnic, fishing, boatlaunch, boatrental, playground, horsetrailers, location, info.
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
| <a id="rec-info"></a>`info` | Full available amenity summary, bounded by reply limits. |

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
| `!rec Briones Overlook Staging Area info` | Recreation: Briones Overlook Staging Area; type Staging Area; parking Lot; restroom Yes; water No; picnic No; fishing No; boat launch No; boat rental No; playground No; horse trailer parking Yes. |

### Proximity examples

```text
!rec water near 37.90 -122.20
Closest, map distance: Recreation: Tilden Steam Trains Park Entrance (1.82 mi); water Yes.
```

<a id="cmd-peak"></a>
## !peak — peak details

**Program:** [scripts/peak.py](scripts/peak.py). All queries are offline. [Shared syntax](#gis-syntax) applies.

Named example: `!peak Wildcat Peak`. Response:

```text
Peak: Wildcat Peak. Subcommands: elevation, location, info.
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
| `!peak Wildcat Peak info` | Peak: Wildcat Peak; elevation 1200 ft; 37.91919,-122.26230. |

### Proximity examples

```text
!peak elevation near 37.90 -122.20
Closest, map distance: Peak: Eureka Peak (1.54 mi); elevation 1640 ft.
```

Unnamed peak records are excluded by default. An administrator can enable them in `gis_settings.json`; proximity searches then include their generated identifiers.

<a id="cmd-park"></a>
## !park — park details and associated features

**Program:** [scripts/park.py](scripts/park.py). All queries are offline. [Shared syntax](#gis-syntax) applies.

Named example: `!park Pleasanton Ridge`. Response:

```text
Park: Pleasanton Ridge. Subcommands: status, agency, trails, recreation, info.
```

### Attribute index

[status](#park-status) | [agency](#park-agency) | [trails](#park-trails) | [recreation](#park-recreation) | [info](#park-info)

| Subcommand | Purpose and interpretation |
| --- | --- |
| <a id="park-status"></a>`status` | Recorded land status; values such as Landbank/Parkland do not establish public access or current opening hours. |
| <a id="park-agency"></a>`agency` | Recorded agency name; missing values are `not recorded`. |
| <a id="park-trails"></a>`trails` | Local trail geometries intersecting the park geometry. Intersection does not prove a connected or publicly accessible route. |
| <a id="park-recreation"></a>`recreation` | Local recreation points intersecting the park geometry, subject to result limits. |
| <a id="park-info"></a>`info` | Full park summary, source polygon record count, agency, trails, and recreation associations. |

### Attribute response examples

These response bodies were produced by the current local snapshots. `not recorded` is a valid response; it does not mean `No`.

| Radio message | Response body |
| --- | --- |
| `!park Pleasanton Ridge status` | Pleasanton Ridge: status Landbank/Parkland. |
| `!park Pleasanton Ridge agency` | Pleasanton Ridge: agency not recorded. |
| `!park Pleasanton Ridge trails` | Pleasanton Ridge: trails none in local data. |
| `!park Pleasanton Ridge recreation` | Pleasanton Ridge: recreation none in local data. |
| `!park Pleasanton Ridge info` | Park: Pleasanton Ridge [Landbank/Parkland]; 18 source polygon records; agency not recorded. Intersecting trails: none in local data. Recreation: none in local data. |

### Proximity examples

```text
!park near 37.90 -122.20
Closest, map distance: Park: Tilden (1.52 mi).
```

`!park` searches the configured park layers, including mapped recreation areas. It has no `dogs`, `open`, opening-hours, permit, or reservation subcommand. `!park status near LAT LON` displays the nearest result’s status; it does not select only open parks.


<a id="cmd-boundary"></a>
## !boundary — mapped areas and trail overlaps

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
Mapped areas: none in local data.

!boundary parks near 37.90 -122.20
Closest, map distance: Park: Tilden (1.52 mi).

!boundary trail Bear Creek
Trail overlaps: Watershed: Contra Costa.
```

Containment response entries use `inside` or `on boundary` followed by the mapped area summary. No containment result means only that no matching local polygon covers the coordinate; it is not an assertion that the location lies outside every real-world park. Polygon holes are respected.

<a id="gis-responses"></a>
## GIS response families and errors

| Response body or pattern | Meaning and next step |
| --- | --- |
| `Trail: <name>. Subcommands: ...` | A unique named feature was found. Select a listed field or `info`. Other named commands use their own category. |
| `<name>: <attribute> <value>.` | Focused response. Distinct source values can be joined with `/`. |
| `Closest, map distance: ...` | Exactly one closest qualifying feature; no radius was supplied. |
| `Within <N> mi, map distance: ...` | Explicit-radius search. Result and byte limits still apply. |
| `+N more` | Additional matching list entries were omitted by the result cap. This is not a pagination token. |
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

The table below records shipped defaults, not a guarantee about an operator's edited installation. Flood-alarm enrollment is handled by the service; its 45-second timeout applies to scheduled reading subprocesses.


| Command | Program | Input type | Timeout (seconds) | Maximum reply parts |
| --- | --- | --- | ---: | ---: |
| `!status` | [scripts/status.py](scripts/status.py) | `none` | 20 | 4 |
| `!time` | [scripts/time_now.py](scripts/time_now.py) | `none` | 20 | 4 |
| `!aqi` | [scripts/airnow_aqi.py](scripts/airnow_aqi.py) | `coordinates` | 60 | 4 |
| `!traffic` | [scripts/highway_info.py](scripts/highway_info.py) | `route_number` | 30 | 4 |
| `!rivers` | [scripts/nearby_river_stations.py](scripts/nearby_river_stations.py) | `coordinates` | 40 | 4 |
| `!uv` | [scripts/uv_index.py](scripts/uv_index.py) | `location` | 35 | 4 |
| `!heatadv` | [scripts/heat_adv.py](scripts/heat_adv.py) | `location` | 45 | 12 |
| `!floodwarn` | [scripts/flood_warn.py](scripts/flood_warn.py) | `location` | 45 | 12 |
| `!snowpack` | [scripts/snowpack.py](scripts/snowpack.py) | `location` | 65 | 4 |
| `!floodalarm` | [scripts/floodalarm.py](scripts/floodalarm.py) | `location` | 45 | 12 |
| `!lightning` | [scripts/lightning.py](scripts/lightning.py) | `location` | 60 | 64 |
| `!trail` | [scripts/trail.py](scripts/trail.py) | `gis_query` | 30 | 6 |
| `!rec` | [scripts/rec.py](scripts/rec.py) | `gis_query` | 30 | 6 |
| `!peak` | [scripts/peak.py](scripts/peak.py) | `gis_query` | 30 | 6 |
| `!park` | [scripts/park.py](scripts/park.py) | `gis_query` | 30 | 6 |
| `!boundary` | [scripts/boundary.py](scripts/boundary.py) | `gis_query` | 30 | 6 |

Global defaults are `script_timeout=20`, `max_output_bytes=65536`, `sender_cooldown=30`, `max_message_age=300`, `max_pending=50`, and `max_pending_per_channel=20`. Radio transmission spacing uses top-level `command_interval=15`. Increasing reply limits increases radio airtime. Flood check interval and expiry are `CHECK_INTERVAL` and `MAX_AGE` in `flood_alarm.py`, not per-request arguments.

### GIS settings

Each dedicated GIS program accepts `--settings PATH` for an alternate JSON file. By default, `gis_settings.json` beside the source configuration is loaded even when the runner uses an external `config.json`. Relative dataset paths resolve against the settings file. For an installed external file, set each GIS registration’s `args` to `["--settings", "/absolute/path/gis_settings.json"]`. Settings are read for each lookup; registration changes still require a service restart.

| Setting | Default | Purpose |
| --- | --- | --- |
| `data_directory` | `"../data/ebmud"` | Local EBMUD manifest and datasets; directory must be readable by the service account. |
| `maximum_radius_miles` | `25.0` | Maximum positive, explicitly supplied radius. No-radius queries still select exactly one nearest result. |
| `max_results` | `3` | Maximum listed matches or associations; valid range 1–20. |
| `max_reply_bytes` | `480` | UTF-8 GIS body limit before sender tags; valid range 200–2000. |
| `description_characters` | `100` | Source narrative limit; zero suppresses descriptions, maximum 500. |
| `include_unnamed_peaks` | `false` | Include unnamed peak records in local peak searches. |
| `projected_crs` | `"EPSG:32610"` | Projected CRS with metre units for spatial calculations. |
| `search_bounds` | `[-126.0, 0.0, -120.0, 84.0]` | [west, south, east, north] bounds accepted for query coordinates. |

Older `default_radius_miles` settings are ignored. Field aliases, layer selection, and affirmative values are explicit constants in the GIS helper modules. These settings do not automatically connect the California State Parks collection to the commands.

<a id="python-programs"></a>
## Direct Python invocation and options

Run these from the appropriate platform service folder using its configured Python environment. These are **terminal commands**, not MeshCore messages. Direct program output omits the `@sender` prefix and radio splitting. `--help` is only supported where the program uses an argument parser; it is not a universal radio or script option.

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
| `flood_warn.py` | `python scripts/flood_warn.py Sacramento` | Text output; a leading `--snapshot` selects structured monitor JSON. |
| `floodalarm.py` | `python scripts/floodalarm.py Sacramento` | Structured single reading with `events` and `text`, or `error`. Does not create a subscription. |
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
| Truncated text or `...` | A description, GIS byte limit, or radio part limit was reached. Request one GIS attribute instead of `info`; an administrator can adjust caps. |
| Unexpected GIS feature or no match | Check the exact mapped name, query coordinates, and dataset coverage. These commands search EBMUD-area references, not statewide data. |
| Flood-alarm acknowledgment with no immediate conditions | Expected: the first successful reading is a silent baseline. Use `!floodwarn` for immediate conditions. |
| No flood notification despite a new bulletin | Notifications compare alert-type sets, not bulletin wording/IDs; unchanged types do not trigger a reply. |
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
