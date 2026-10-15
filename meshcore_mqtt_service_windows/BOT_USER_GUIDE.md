# MeshCore bot: quick user guide

Send a command in the MeshCore channel assigned to the bot. The default channel is `#autatestbot`; a local installation can use another channel. Replies appear in that same channel with the sender's name, such as `@Alice`.

Quick links: [First message](#start) · [Weather and local conditions](#conditions) · [Flood monitoring](#monitoring) · [Trails and recreation](#gis) · [No reply or incomplete reply](#help).

For every subcommand, response type, error, and administrator option, see the [detailed command reference](COMMAND_REFERENCE.md#command-index). Installation information is in the [README](README.md).

<a id="start"></a>
## First message

Send this as an ordinary channel message:

```text
!status
```

An available bot responds with `@Alice Local command service is running.` The name depends on the sender. Send `!time` to read the bot's clock.

- Use lowercase command words and include the `!`.
- Send one command per message. Do not add quotes around the message or an `@bot` prefix.
- Wait at least 30 seconds between requests on the same channel. Busy channels and long replies can take longer.
- Use the assigned channel; direct messages are not supported by this service.
- Replace sample locations with the desired location. Do not type placeholder brackets such as `[MILES]`.

<a id="conditions"></a>
## Weather and local conditions

| Purpose | Example to send | What comes back |
| --- | --- | --- |
| Current UV index | `!uv Sacramento` | UV number and risk category. |
| Heat alerts | `!heatadv Sacramento` | Active heat alerts, no active heat alert, or a lookup error. |
| Lightning potential | `!lightning Sacramento` | NWS thunderstorm/lightning potential for the next 24 hours. This is a forecast, not a strike detector. |
| Current flood alerts | `!floodwarn Sacramento` | Active flood alert types, no active flood alert, or a lookup error. |
| Snow conditions | `!snowpack Truckee` | Nearby California snow depth and forecast snowfall; missing inputs are identified. |
| Air quality | `!aqi 37.7749 -122.4194` | Nearest available PM2.5 monitor's AQI, rating, distance, and observation time. |
| River stages | `!rivers 39.0 -121.0` | Reporting river stations within 15 miles, stage, and available alert thresholds. |
| Highway restrictions | `!traffic 80` | Caltrans restrictions for the numbered California route, or no reported restrictions. |

For UV, heat, lightning, flood, and snow commands, a location can be a city, ZIP code, or decimal GPS coordinates:

```text
!uv Reno NV
!heatadv 95814
!lightning 38.5816 -121.4944
```

Bare city names default to California. Snowpack coverage is California-only. Air quality and river commands require coordinates: **latitude first, longitude second**. California longitudes are negative. Traffic takes a route number such as `80`, without `I-` or `Highway`.

An unavailable-data response does not mean conditions are clear. Observation times and forecast periods matter. [Detailed weather responses](COMMAND_REFERENCE.md#cmd-uv) and [location formats](COMMAND_REFERENCE.md#input) describe the limits.

<a id="monitoring"></a>
## Temporary flood monitoring

```text
!floodalarm Sacramento
```

The service acknowledges a temporary subscription, checks approximately every 20 minutes, and expires it four hours after the last subscription request. The first successful check establishes a silent baseline. Later messages report changes in the set of flood alert types; changes in bulletin wording alone do not trigger a notification.

Send the same command again to renew the subscription, or supply a different location to replace it for that sender and channel. There is no cancellation subcommand. Use `!floodwarn Sacramento` for an immediate conditions lookup. [Full monitoring behavior](COMMAND_REFERENCE.md#cmd-floodalarm).

<a id="gis"></a>
## Trails, recreation, peaks, parks, and boundaries

These five commands use local EBMUD-area map datasets. They do not search every California park. The separate California State Parks data collection is not connected to the bot commands.

| Purpose | Example to send | Example reply body from local data |
| --- | --- | --- |
| Trail dog policy | `!trail Bear Creek dogs` | `Bear Creek: dogs No.` |
| Recreation amenities | `!rec water near 37.90 -122.20` | Closest qualifying recreation feature with recorded drinking water, including map distance. |
| Peak elevation | `!peak Wildcat Peak elevation` | Mapped elevation for Wildcat Peak. |
| Park details | `!park Pleasanton Ridge status` | Recorded status for Pleasanton Ridge. |
| Areas crossed by a trail | `!boundary trail Bear Creek` | `Trail overlaps: Watershed: Contra Costa.` |

Use the singular `!trail`; `!trails` is not registered. Feature names are case-insensitive. A partial name can work; if several names match, the bot asks for a fuller name. Names must exist in the local datasets.

### Ask for one detail or a full summary

```text
!trail Bear Creek
!trail Bear Creek dogs
!trail Bear Creek info
```

A name alone identifies the feature and lists available subcommands. A field such as `dogs` returns only that detail. `info` requests a fuller summary, which may be split or shortened for radio delivery.

Common fields:

- Trails: `dogs`, `horses`, `bikes`, `length`, `difficulty`, `gain`, `surface`, `shade`, `time`, `start`, `areas`, `description`, `info`.
- Recreation: `type`, `parking`, `restrooms`, `water`, `picnic`, `fishing`, `boatlaunch`, `boatrental`, `playground`, `horsetrailers`, `location`, `info`.
- Peaks: `elevation`, `location`, `info`.
- Parks: `status`, `agency`, `trails`, `recreation`, `info`.
- Boundaries: optional category `parks`, `watersheds`, `reservoirs`, or `recreation` before coordinates, `near`, or `trail NAME`.

[Linked subcommand reference](COMMAND_REFERENCE.md#gis-syntax).

### Find the closest feature or search a radius

```text
!trail near 37.90 -122.20
!trail dogs near 37.90 -122.20
!trail dogs near 37.90 -122.20 5
```

Without a radius, `near` returns **only the closest matching feature**. Adding `5` requests matches within five miles; default list limits can omit additional matches. The default maximum radius is 25 miles. The `dogs` filter selects trails whose recorded policy permits dogs; qualifying restrictions such as park hours remain in the response.

The same pattern works for recreation amenities, peaks, parks, and boundaries:

```text
!rec restrooms near 37.90 -122.20
!peak near 37.90 -122.20
!park near 37.90 -122.20 5
!boundary parks near 37.90 -122.20
```

Distances are straight map distances to the mapped feature, not walking or driving routes. A nearby polygon or trail is not necessarily an accessible entrance. `!boundary 37.90 -122.20` instead asks which mapped areas contain that point. Local policy and boundary records can differ from current conditions. [Distance and filter rules](COMMAND_REFERENCE.md#gis-syntax).

<a id="help"></a>
## Help, missing replies, and shortened answers

Send `!trail help`, `!rec help`, `!peak help`, `!park help`, or `!boundary help` for GIS syntax. There is no global `!help` command.

If no reply arrives, check spelling and channel assignment, allow time for queued radio traffic, and wait through the sender cooldown before retrying. Unknown commands are ignored. `!status` checks whether the local responder is available; reception still depends on the radio path.

Long answers arrive in several tagged messages. An ending `...` means text was shortened. For GIS results, request a single field to reduce reply length. `not recorded` means the dataset lacks a value; it does not mean an amenity is unavailable or a policy prohibits access.

[All response and failure types](COMMAND_REFERENCE.md#troubleshooting) · [All 16 commands](COMMAND_REFERENCE.md#command-index) · [Platform README](README.md).
