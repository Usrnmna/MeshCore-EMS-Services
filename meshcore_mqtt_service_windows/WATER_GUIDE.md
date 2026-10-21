# Location water status and flood subscriptions

These commands report conditions for a location supplied in the request. The
existing service owns subscriptions, scheduling, channel permissions and tagged
radio delivery. Each lookup has a dedicated Python entry point on both platforms.

## Commands

[Tagged command, control, and notification examples](RESPONSE_EXAMPLES.md)
complement the syntax below. [Radio response priorities](RESPONSE_FORMATTING.md)
identify conditional fields; local JSON retains supported structured source data.

| Request | Result |
| --- | --- |
| `!waterway LOCATION` | Nearest reach and nearby-only relationship. |
| `!basin LOCATION` | Most-specific containing CalWater category. |
| `!floodstatus LOCATION` | Official alert or qualified modeled-footprint status. |
| `!floodwarn LOCATION` | Highest-priority NWS flood alert; no subscription change. |
| `!floodalarm LOCATION` | Subscribe to official flood-alert changes at the resolved point. |
| `!floodalarm conditions LOCATION` | Also subscribe to supported current gauge-category, model and data-availability changes. |
| `!floodalarm status` | Show the saved point, mode, remaining duration and known coverage limitations. |
| `!floodalarm stop` | Disable that sender's subscription on the receiving channel. |

`LOCATION` accepts latitude/longitude, a US ZIP or ZIP+4, or an exact city name
with an optional state. Bare city names default to California. City and ZIP
results represent one point, not their complete boundaries. Multiple matching
places require a clarified state or coordinates; floodwarn uses a short clarification prompt. Names are
not silently resolved by population. These commands do not accept a river name
as a substitute for a location. `!rivers` selects a station summary independently.

```text
!waterway 38.61324 -122.83638
!basin 38.61324 -122.83638
!floodstatus Sacramento CA
!floodwarn 95814
!floodalarm conditions 38.61324 -122.83638
!floodalarm status
!floodalarm stop
```

No examples above imply active warnings or measured levels. Each lookup sends
one tagged message of at most 150 UTF-8 bytes. There are no details or paging
subcommands. Full current source records remain available through local
`--json` execution. The [response policy and review inventory](RESPONSE_FORMATTING.md)
describes selection priorities and records fields for manual review.

## Concise flood alerts

`!floodwarn LOCATION` selects the highest-priority active flood event. Essential
warning text precedes optional expiration, additional-alert count and location.
Fields are included whole when the sender tag leaves enough space. No omission
notices or continuation prompts are transmitted.

| Alert | Essential response |
| --- | --- |
| Flash Flood Warning | NWS FLASH FLOOD WARNING. Move to higher ground now. |
| Flood Warning | NWS FLOOD WARNING. Flooding imminent/occurring. |
| Flood Advisory | NWS Flood Advisory. Minor flooding expected. |
| Flood Watch | NWS Flood Watch. Flooding possible; stay alert. |

Hypothetical examples, not live alerts:

```text
NWS FLASH FLOOD WARNING. Move to higher ground now. | Until 6 PM PDT | Sacramento
No active NWS flood alerts. | Sacramento
NWS alerts unavailable; status unknown. | Sacramento
```

A verified empty NWS response is not proof that flooding is absent. Stale,
malformed or inaccessible sources cannot produce the no-alert response.
Expiration times use `responder.timezone`. Current allowlisted bulletin text
remains in the replaceable source snapshot; categorical subscription baselines
retain fingerprints rather than bulletin text or numeric readings. Scheduling
and enrollment remain separate from one-shot lookup formatting.

## Interpreting relationships and coverage

| Label | Evidence and limitation |
| --- | --- |
| `OFFICIAL NWS` | Active actual NWS point/zone products after point-coverage verification. No returned product is not an all-clear. |
| `UPSTREAM BASIN CONTEXT` | A supported station route reaches a segment with positive-length overlap in the point's CalWater planning watershed, or super planning watershed fallback. This is a derived graph plus spatial relationship, not proof that water flows through or inundates the exact point. |
| `NEARBY ONLY` | Geometric proximity. No downstream connection or local flood trigger is inferred. |
| `MODELED NOAA point footprint` | The submitted point intersects a fresh current-analysis inundation feature within the published domain. This is modeled, not field-confirmed flooding. |
| `outside_published_domain` | The point is outside the public model domain returned by NOAA. It is not a dry-location assertion. |
| `no_current_footprint_returned_not_all_clear` | No intersecting current feature was returned. This does not verify model freshness, absence of flooding or coverage of every tributary. |

CalWater hydrologic region, hydrologic unit, hydrologic area, hydrologic subarea,
super planning watershed and planning watershed remain separate categories.
Water Board regions such as North Coast, San Francisco Bay and Central Coast
remain separate attribution. A missing polygon or name is reported explicitly;
unnamed reaches retain source identifiers. Existing unresolved station matches
are not repaired by nearest-neighbor guesses. Routing status remains available
in text and structured output.

The statewide inventory and routing database supply candidates. Condition
monitoring evaluates **every reliably linked upstream gauge** independently of
`max_results`, distance, display order or availability of a numeric observation.
The display defaults to three gauges/reaches; this limit affects presentation only.
Radio replies summarize counts for the complete monitoring set and show bounded
details. Structured `conditions` contains each monitored station's identifier,
name, NOAA category, USGS reading-usability state and routing caveats. Additional
numeric readings remain available in the original current USGS collection.

Eligibility requires positive-length overlap in a containing planning watershed
(or super planning watershed fallback) and a supported directed source path.
Accepted routing statuses are `paths_to_source_terminals`,
`paths_with_unresolved_endpoints`, and `no_source_terminal_reached`: each records
existing traversable source edges, even when the entire downstream network is
incomplete. Duplicate joins and reconverging branches produce one gauge check.
Missing/conflicting addresses, unsupported directions, boundary-only contacts
and proximity-only associations never qualify as upstream alarms. Unverified
positive-overlap links are listed separately in `routing_exclusions` with reasons.
A supported linked station without coordinates still qualifies; it cannot be
selected through proximity alone. A missing inventory identity remains excluded.

Source-verified connectivity is a derived basin association, not a hydraulic
prediction at the point. Unresolved endpoints, potential divergences and tidal
reaches remain explicit per-gauge caveats. NOAA identity must still match before
its category can be used. Missing NOAA identities remain `threshold_unavailable`;
failed/contradictory source responses remain unavailable. Every linked station's
current USGS usability is tracked separately, including stale, invalid, future,
unexpected-unit or missing readings. No missing value or threshold becomes zero.

Subscriptions compare the complete per-gauge categorical baseline. Notifications
count all changed/lost gauges and name at most three, prioritizing major,
moderate, minor and action categories before unavailable or unchanged-category
coverage changes. Omitted detail is counted explicitly. `status` summarizes all
gauges rather than printing one row per station. A deployment expanding an older
three-gauge baseline reports the additional coverage on its next successful
check; the saved point and expiry remain unchanged.

USGS stage and discharge retain source units, age, approval status and qualifiers.
Stale, invalid, future-dated or missing values are explicit. NOAA gauge identity
must match the inventory or corroborated review-overlay LID and the response's USGS ID. Categories
come from NOAA's own latest observation. NOAA stage thresholds are never applied
to a USGS stage with an assumed common datum. A NOAA `no_flooding` gauge category
does not establish safety at the requested location. The corresponding category
threshold must be defined; `no_flooding` requires a published minor threshold.
Identifier-review outcomes and live threshold availability remain separate
categorical fields in structured conditions. See the [33-station NOAA review](WATER_STATION_REVIEW.md)
for supported links, explicit unresolved results and source evidence.

The last-24-hour QPE pixel is optional point context in inches. This service's
identify response does not establish a valid time, so the value is labeled
undated and excluded from alarm triggers. It is not a basin mean. Basin-average
rainfall, soil wetness, forecasts, flood depths and arrival times are not supplied
by these commands. Tributary connectivity alone cannot determine them.

## Subscription lifecycle

Only an explicit `!floodalarm` enrollment starts monitoring. Location resolution
and a successful official-alert baseline precede acknowledgment. An ambiguous
location or unavailable NWS coverage prevents enrollment. Conditions mode may
start with explicitly partial local/model coverage. Coordinates are pinned to
six decimal places and reused on subsequent checks; a geocoder change cannot
move an active subscription.

The default interval is five minutes and the default duration is four hours
from acceptance. Host scheduling, provider delays and radio spacing can delay
checks and delivery. A repeat enrollment replaces the point/mode and establishes
a fresh baseline and deadline. `status` and other lookup commands do not renew
the deadline. `stop` invalidates pending lookups and queued notifications before
the radio send guard runs. After acknowledgment, initial active alerts (or a
verified no-alert result) are queued as independent responses. Scheduled checks
begin only after acknowledgment parts are sent. No daemon or separate OS service
is added.

Official changes include new alerts, material bulletin updates, referenced
replacement alerts, cancellation, expiration and disappearance from a successful
feed response. Unconfirmed disappearance is labeled accordingly. Conditions mode
also compares categorical gauge states, current modeled footprint states and
coverage changes. Unchanged conditions remain quiet. A source outage produces an
availability notice; failures retain official fingerprints, never clear alerts,
and recovery is reported. No gauge trend is calculated from stored history.

Subscriptions persist in `runtime/bridge.sqlite3`, table
`flood_location_subscriptions`. Expiry does not extend across restarts. Existing
legacy subscriptions migrate once with their original four-hour deadline, then
verify and pin their location on the first successful check. Channel identity,
assignment, sender, request revision and expiry are checked before delivery.
Two nodes with the same display name on the same channel share a subscription.
Replies go to the originating configured channel and are not private direct
messages. Local send acceptance does not prove recipient delivery. Failed or
uncertain sends are not replayed automatically.

## Independent flood-alarm notifications

After enrollment acknowledgment, each active NWS alert is sent as an independent
notification. Essential event, flash-flood action and unknown priority take
precedence. Change type (`NEW`, `UPDATED`, `ACTIVE`), expiration and saved location
are optional whole fields. Unchanged polls remain silent. These subscription
events are independent notices, not automatic continuation pages of a lookup.

Hypothetical notification, not a live alert:

```text
NWS FLASH FLOOD WARNING. Move to higher ground now. | NEW | Until 6 PM PDT | Sacramento
```

All eligible alerts are queued individually; there is no three-alert display
limit for subscriptions. Responses are sent sequentially on the subscribing
channel, with a **minimum five-second pause after the preceding complete response
finishes**. Each response is one tagged message of at most 150 UTF-8 bytes.
`NOTIFICATION_PAUSE_SECONDS` in `flood_alarm.py` is 5.0. The existing shared
`command_interval` is **5 seconds in both shipped configurations**, matching the
notification pause. The two waits overlap rather than adding to ten seconds.
The shared interval applies to all channels, MQTT commands and automatic reply
chunks, not only flood alerts. Radio contention, verification and transmission
time can still extend the gap beyond five seconds.

Existing installations must set top-level `command_interval` to `5` in their
active `config.json` and restart the service; updating source does not modify a
separate installed configuration.

The queue uses this lexicographic priority policy for active alerts:

| Comparison order | Higher priority first |
| --- | --- |
| Urgency | Immediate, Expected, Future, Past |
| Severity | Extreme, Severe, Moderate, Minor |
| Certainty | Observed, Likely, Possible, Unlikely |
| Effective time | Newest already-effective information first |
| Ties | Existing flood-event order, then alert ID; subscriber key makes remaining ties deterministic |

This is an application dispatch policy, not an official NWS ranking. CAP's
`effective` time concerns the information's validity and differs from hazard
onset. Future-effective, expired or invalid-time records cannot enter the active
notification queue. `Very Likely` is normalized to `Likely` for comparison.
Missing, unknown or unsupported categorical priority values use the highest
scheduling tier for that field and append `Priority unknown.`; stored source
values are not promoted to known severity, urgency or certainty. See the
[CAP 1.2 definitions](https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.html)
and [CAP guidance on unknown values](https://docs.oasis-open.org/emergency-adopt/cap-elements/v1.0/cap-elements-v1.0.html).

[Hypothetical lifecycle and recovery examples](#hypothetical-lifecycle-and-recovery-examples)
show independent responses and queue replacement or suppression.

Standard alert descriptions appear only on active-alert notices, never on
cancellations, expirations or unknown states. After source recovery, active alerts
are restated individually before the recovery notice. A transition to an empty
feed can produce individual cancellation/expiration notices followed by one
verified no-active-alerts notice. Active alerts take priority over lifecycle,
source-status and separately labeled derived condition notices.

Polling and delivery are separate asynchronous workers inside the existing
service. Polling can replace or remove queued records while delivery waits. A
newly detected higher-priority alert moves ahead of unsent lower-priority alerts;
it does not interrupt a response already being transmitted unless that response
becomes invalid. Each notification's guard checks subscription revision, channel,
expiry, alert version and current source validity after the radio-slot wait.
Stopping, renewing, relocating or disabling a subscription invalidates its queued
responses. Pending cancellations and no-alert notices are also removed if later
source state contradicts them. Source outages suppress queued active alerts.

Checks use the latest validated snapshot, not a new network request per packet.
Normal polling and provider cache intervals bound change detection. If queued
evidence ages past the configured cache limit, transmission waits and requests a
fresh poll. Polling continues through the five-second pauses and radio waits.

Subscriptions and current categorical baselines persist in `bridge.sqlite3`.
The replaceable delivery queue is in memory, retains only current notification
metadata and categorical context, and is not replayed after a restart. Baselines
are committed before delivery, preserving the existing no-replay policy for
failed or uncertain sends. Consequently, a shutdown can discard unsent notices;
local radio acceptance still does not prove recipient delivery. No gauge-level
history, new database table or separate service is introduced.

A configuration regression checks that the
shared radio interval matches the five-second notification pause. Offline regressions cover priority fields and
unknown values, concise event/action text, independent tagged responses, five-second
spacing after completion, replacement/cancellation, stale evidence, stop and
subscription expiry, concurrent polling, failed sends and shutdown. Native Linux
execution and live radio/recipient delivery were not exercised.

Ten regressions in
[the documented notification tests](tests/test_flood_documented_examples.py)
compare all nine lifecycle/recovery example responses directly with the shipped
guide. They exercise the subscription queue with synthetic provider snapshots,
an in-memory database and controlled clocks, including five-second pacing,
same-ID and referenced-ID updates, cancellation/expiry suppression, unconfirmed
disappearance, outage/recovery uncertainty, contradicted empty-feed notices and
alert replacement during a radio wait. No provider requests or radio transmissions
are performed by these tests.

### Gauge category changes

```text
1 gauge: major flooding; not point flooding. | Example upstream gauge [ID A]; USGS unavailable | Sacramento CA
```

Counts describe changed gauges in the selected category. The highest-priority
category appears first; all gauges still participate in change detection.
Station names and labelled IDs remain distinct. Gauge categories and derived
upstream relationships do not establish flooding at the requested point.
Unknown thresholds, stale or unavailable data, and lost coverage remain explicit.
Loss of coverage retains `not an all-clear`. Station names and their source-status
qualifiers are included together when the message budget permits.

### Hypothetical lifecycle and recovery examples

**All alerts, locations and times in this section are hypothetical, not live
warnings or observations.** Each code block represents one independent response;
examples under different headings are separate scenarios. When multiple responses
are queued, a minimum five-second pause follows each completed response. The
pause begins after its tagged radio message; radio contention, verification
and transmission time can extend the gap. Active alerts retain the priority
ordering described above.

#### Material update replaces a queued version

```text
NWS FLOOD WARNING. | UPDATED | Until 9 PM PDT | Sacramento
```

If an earlier version is still queued, the material update replaces it and the
obsolete version is suppressed. Published replacement references can connect a
new alert ID to its predecessor; matching names alone do not establish that
relationship. An already-transmitted version cannot be retracted. Unchanged
polls do not repeat the notification.

#### Confirmed cancellation removes a queued active alert

```text
NWS Flood Warning cancelled by NWS. Not an all-clear. | Sacramento
```

A validated cancellation removes the queued active notification for that alert.
The cancellation notice omits the active-alert description. Cancellation of one
alert does not establish that other alerts or flooding are absent.

#### Expiration suppresses an active notification

```text
NWS Flood Warning expired. Not an all-clear. | Sacramento
```

An alert that expires while waiting cannot be transmitted as active. Its active
notification is suppressed by the expiry guard; the expiration notice follows a
successful source check, rather than being inferred from an unavailable feed.

If cancellation or expiration leaves a verified empty feed, a separate response
can follow the lifecycle notice after the five-second minimum pause:

```text
No active NWS flood alerts. Monitoring continues. | Sacramento
```

A newly detected active alert suppresses this queued no-alert notice before it
can make a contradicted claim. A verified empty feed is not proof of no flooding.

#### Disappearance remains explicitly unconfirmed

```text
NWS Flood Warning missing; cancellation unconfirmed. | Sacramento
```

When a successful feed response no longer lists the alert before its known expiry
and provides no cancellation or replacement evidence, the queued active version
is suppressed. Disappearance alone is not reported as confirmed cancellation.
This transition does not generate a `No active NWS flood alerts` notification,
even if other alerts were explicitly cancelled or expired. If the disappearance
is detected during source recovery, the recovery notice reports only
`NWS monitoring restored.` alongside the separate uncertainty notice.

#### Outage suppresses active notices; recovery restates current alerts

```text
NWS alerts unavailable; status unknown. | Sacramento
```

Unavailable or stale official evidence cannot clear existing alerts. Queued
active notices are suppressed during the outage. Once valid current data returns,
each still-active alert is restated independently in priority order, for example:

```text
NWS FLOOD WARNING. Priority unknown. | ACTIVE | Until 9 PM PDT | Sacramento
```

Here, a priority field remains missing or unknown despite source recovery. The
standard description is retained and the uncertainty is explicit. After all
current active-alert responses, separated by the five-second minimum pauses,
the recovery response follows:

```text
NWS monitoring restored. | Sacramento
```

If recovery instead verifies no active alerts, the recovery response is:

```text
NWS monitoring restored. No active NWS flood alerts. | Sacramento
```

#### Queue checks apply before each radio chunk

Each chunk is checked against the latest validated snapshot after the radio-slot
wait; this is not a new network lookup for every packet. Newly contradicted
cancellation and no-alert notices are suppressed. Stopping, renewing, relocating
or disabling a subscription invalidates its queued responses. A higher-priority
alert moves ahead of unsent lower-priority alerts but does not interrupt a valid
response already in progress. If a queued response becomes invalid, it is suppressed. Transmitted notices
cannot be retracted.

## Data setup, refresh and retention

```text
Verified local collections --> Explicit static-index build --> Static spatial index
                                                                    |
NWS / NOAA / USGS --> On-demand current-only cache -------------------+
                                                                    v
                                                         Dedicated lookup programs
                                                                    |
                                           +------------------------+----------------+
                                           v                                         v
                                  Requested channel reply              Service-owned flood monitor
                                                                                     |
                                                                     Guarded change notification
```

The static index and online current-value cache have separate lifecycles. The
flood monitor stores categorical baselines and source fingerprints for change
comparison; it does not retain a gauge-level time series.


Install dependencies and download the statewide collections using the repository
[water data setup guide](../docs/WATER_DATA_SETUP.md). In a standalone service ZIP,
obtain the repository's downloader programs separately and set
`responder.water.data_directory` to the absolute downloaded `data` directory.
The default `../data` is relative to the platform package directory, not the
process working directory. Downloaded datasets are not embedded in service ZIPs.

After successful inventory/routing acquisition, run from the selected package:

```console
python scripts/water_refresh.py --index --noaa-identifiers
python scripts/floodstatus.py --json 38.61324 -122.83638
```

An explicit data root can be supplied for indexing:

```console
python scripts/water_refresh.py --index --data-directory /absolute/path/to/data
```

Set the same path in configuration for subsequent lookups. Index construction
verifies manifest checksums, source versions and routing dependencies. It reads
original geometry and writes a separate atomic `runtime/water_index.sqlite3`
containing bounds, station identifiers (including records without coordinates)
and provenance pointers. Schema version 2 replaces the former display-only index;
existing installations must rerun the index command after updating the programs. It does not
modify the source datasets or store observations. Missing, changed or mismatched
index sources fail with a rebuild instruction. Build a separate index in each
installed platform package that will run the service.

After inventory, network, link-review or routing changes, finish the dependency
refresh sequence and rerun `water_refresh.py --index`. The supplemental NOAA identifier review can be refreshed independently with
`python scripts/water_refresh.py --noaa-identifiers`; it needs no index rebuild.
This replaces `runtime/water_station_review.json`, including failed or unresolved
checks, and leaves original inventory identifiers unchanged.
Observation-only refreshes
are read directly and do not require rebuilding the index. From the repository
root, `python -m data.usgs_water.refresh --mode observations` replaces the USGS
latest-value snapshot under the existing current-only retention policy.
The command service does not start a statewide download or install a download
schedule. Local status can use downloaded geometry/readings offline with explicit
age and missing online-source status. New subscriptions require verified NWS
coverage; online products need internet access or a still-valid short cache.

Online requests refresh on demand, including subscription checks. The cache
`runtime/water_current.sqlite3` replaces one current record per source and target.
It strips historical crests and time-series payloads before persistence, uses
secure deletion, and prunes unused entries after 24 hours on successful writes
with a 1,000-entry bound. Errors replace cached bodies rather than presenting old
values as fresh. Source retrieval time is distinct from observation valid time.
Static category thresholds and datum metadata are retained because they explain
the current value. Subscription baselines contain only alert fingerprints and
categorical conditions, not level history. Numeric water replies are transmitted
but omitted from `bot_requests.response`; existing transport queues may still
hold pending radio messages. Original downloaded source evidence is preserved.

## Configuration and implementation

Settings are under `responder.water` in each package's `config.json`:

| Setting | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Enable location water lookups and monitoring. |
| `data_directory` | `../data` | Downloaded collection root. |
| `cache_seconds` | `300` | Shared current-source response cache lifetime. |
| `subscription_interval` | `300` | Seconds between due checks per subscription. |
| `subscription_hours` | `4` | Enrollment duration. |
| `reading_max_age` | `21600` | Maximum observation age in seconds; source timestamps still displayed. |
| `model_max_age` | `10800` | Maximum age of an explicitly UTC-labeled model update. |
| `nearby_radius_miles` | `15` | Nearby-only candidate radius. |
| `max_results` | `3` | Displayed gauge/reach details only; 1-5. No monitoring coverage limit. |
| `noaa_enabled` | `true` | Fetch NOAA gauge/model/QPE context; NWS official alerts remain separate. |

Changing configuration requires restarting the installed service. Existing
subscriptions retain their saved expiry; new timing applies to later scheduling
or enrollment. Each HTTP request has a 12-second timeout and an 8 MiB limit;
commands and snapshot children have a 90-second overall limit. The snapshot
child output limit is 2 MiB. Gauge fetches are deduplicated and share the existing
five-worker pool and current-source cache. No per-gauge count cap is applied. A
whole-child timeout reports monitoring unavailable and preserves the previous
baseline; it never commits a truncated monitoring set as complete. Individual
source failures retain explicit unavailable states while other results remain usable.

`water_agency_review.py` verifies additional agency evidence and the documented
CDM successor chain; `water_identifiers.py` owns the NOAA review overlay and explicit refresh;
`water_local.py` owns indexed source reads; `water_sources.py` owns bounded
official-source fetches and current-only caching; `water_lookup.py` owns location
resolution, snapshots and presentation; `water_changes.py` compares categorical
states. `flood_alarm.py` owns persistent enrollment and scheduling within the
existing service. Dedicated command entry points call these helpers directly.

## Implementation reference

[Water lookup, source/cache, identifier-review, index, and subscription functions](WATER_FUNCTION_REFERENCE.md)
include complete signatures, methods, and nested callback descriptions.

## Sources and validation

Source schemas and selection were checked during implementation on
2026-10-20/21 (Pacific/UTC). Availability and regional coverage can change.

| Source | Use |
| --- | --- |
| [NOAA water data and web services catalog](https://water.noaa.gov/about/data-and-web-services-catalog) | Product discovery and observed/current versus forecast distinctions. |
| [NWS API documentation](https://www.weather.gov/documentation/services-web-api) | `/points/{lat},{lon}` coverage and `/alerts/active?point=...` actual flood products. |
| [NWPS API documentation](https://api.water.noaa.gov/nwps/v1/docs/) and [gauge endpoint example](https://api.water.noaa.gov/nwps/v1/gauges/HEAC1) | Latest observed gauge category/value, USGS identity, static thresholds and datums. |
| [NOAA All Gauges Report](https://water.noaa.gov/resources/downloads/reports/nwps_all_gauges_report.csv) | Unique exact USGS ID discovery, independently corroborated through the gauge API; [complete review](WATER_STATION_REVIEW.md). |
| [Current-analysis inundation layer](https://maps.water.noaa.gov/server/rest/services/nwm/ana_inundation_extent/FeatureServer/0) | Point intersection and explicitly UTC-labeled `update_time`; not forecast maximum inundation. |
| [Public inundation domain](https://maps.water.noaa.gov/server/rest/services/reference/static_public_fim_domain/MapServer/0) | Published model-domain check. |
| [RFC QPE service](https://mapservices.weather.noaa.gov/raster/rest/services/obs/rfc_qpe/MapServer) | Last-24-hour image layer 28, approximate 4 km grid, inches; undated pixel context only. |
| [Open-Meteo geocoding documentation](https://open-meteo.com/en/docs/geocoding-api) | US city/ZIP coordinates based on GeoNames; provider terms apply. |
| [USGS collection provenance](../data/usgs_water/SOURCES.md), [routing interpretation](../data/usgs_water/README.md), [Basin Plan relationships](../data/basin_plans/RELATIONSHIPS.md) | Preserved station IDs, current-only readings, reviewed routing links and CalWater categories. |

Some repository-relative source links require the full repository rather than
a standalone service ZIP. Source URLs also accompany structured cache records
and original dataset manifests.

Offline tests cover ambiguity, current-only caching, identity conflicts, stale
readings, model gaps, upstream-versus-nearby geometry, subscription expiry,
cancellation, restart state, partial outages, recovery and channel guards. Tests
also cover gauges beyond the display limit, missing coordinates, duplicate paths,
excluded conflicts, changing link coverage and bounded summaries of large changes.
Run `python -m unittest discover -s tests` and
`python -m unittest discover -s tests -p test_command_programs.py` in each package.
A live Russian River lookup checked real collection joins and explicit partial
coverage. Neither fixture tests nor a live lookup establish radio delivery,
four-hour operation, flood-depth accuracy or statewide model availability.

Expansion validation on the installed Russian River pilot collection evaluated
34 supported upstream gauges with both one-detail and three-detail display
settings. The initial check had one usable NOAA category and 33 missing NOAA
identifiers. The subsequent [official identifier review](WATER_STATION_REVIEW.md)
corroborated 16 additional links: six with published thresholds and ten without.
A further agency review established the CDM/YDMC1 successor for legacy
USGS-11462000, without thresholds; sixteen remain unresolved. Including the original HEAC1 link, seven pilot
gauges have published thresholds; this is not a claim of seven usable current
readings. USGS usability and routing caveats remain separate. These counts
refer to the pilot's linked inventory, not statewide live coverage. Existing
schema-2 indexes remain usable because the review is applied during lookup.

Source-access retry validation passed 371 tests in each platform package
on a Windows host. Both live pilot lookups retained all 34 supported upstream
gauges with either one or three displayed details: seven current NOAA categories
were usable, eleven linked gauges had no published thresholds, and sixteen
identities remained unresolved. The new CDM/YDMC1 link was labeled as an agency
successor; the legacy USGS reading remained stale. USGS readings separately
remained 16 stale, one invalid and 17 unavailable. Categorical baselines contained
no numeric readings or historical coverage periods. Tests also verified immediate
revocation after missing evidence and cache revalidation if NOAA later publishes
an exact USGS identifier. No radio messages or subscriptions were created; native
Linux was not exercised.

The [additional agency-record review](WATER_STATION_REVIEW.md#additional-official-agency-review)
adds one explicitly labeled agency successor while preserving the sixteen
unresolved identities. Refresh the review after upgrading with
`python scripts/water_refresh.py --noaa-identifiers`. No index rebuild is needed.
An older runtime review continues to withhold the new successor until refreshed.
The refresh reads USGS coverage metadata only, never historical measurement values.

The [further map and operator-record review](WATER_STATION_REVIEW.md#further-map-and-operator-record-review)
retains all sixteen unresolved identities and four distinct NOAA candidates,
including WSSC1. These candidates do not authorize links. The identifier refresh
now retains static USGS/map metadata and flags changed candidate identities or
source failures for manual review. It stores no historical levels and adds no
radio-time queries; existing supported matches and routing remain unchanged.

The additional map-review regressions cover all sixteen unresolved rows,
identical-position nonmatches, changed candidate IDs/names/positions, malformed
or truncated maps, duplicate/missing USGS metadata, source failures and refresh
exit codes. Both live identifier refreshes completed successfully. Both pilot
lookups retained the same 34 upstream gauges for one-detail and three-detail
settings, with seven published thresholds, eleven linked gauges without
thresholds and sixteen unresolved identities. Auxiliary map evidence remained
absent from categorical subscription baselines. No additional accepted link,
new reading history or radio subscription was introduced.

The [archived-source and OneRain retry](WATER_STATION_REVIEW.md#archived-source-and-onerain-access-retry)
recovered the original historical tables and the public site inventory. No new
NOAA link was supported. Refresh now checks OneRain static aliases with transient
cookies, while fixed PDF review dates preserve the distinction between manual
historical evidence and current metadata. No historical level series are retained.

Source-access retry regressions passed in both 371-test platform suites on a
Windows host. Coverage includes cookie-requiring redirects without cross-request
cookie persistence, OneRain field allowlisting, malformed/duplicate inventories,
changed aliases, non-authorizing exact alias leads and fixed historical-review
dates. Both live identifier refreshes succeeded with sixteen exact matches, one
agency successor and sixteen unresolved identities. Native Linux execution and
radio delivery were not exercised.


The [additional local agency review](WATER_STATION_REVIEW.md#additional-local-operating-agency-records)
retains dated evidence for all sixteen unresolved stations, including operator
reactivation leads, differing historical coverage periods and a source ID/name
conflict. No additional NOAA link is supported. Identifier refresh preserves
these static findings without renewing the manual-review date or storing level
history. Live exact-identity evidence remains authoritative.


The [WAC detail-page recovery](WATER_STATION_REVIEW.md#wac-detail-page-recovery)
confirmed the explicit CW3E WAC/CDEC WAS alias and installation metadata through
alternate official records. No legacy-USGS/NOAA link was established. The two
Warm Springs manual-review dates were updated; other dates and current readings
remain unchanged. Elevation and logger-offset uncertainty is retained without
applying a correction or inferring thresholds.


The [WAC/WAS vertical-reference review](WATER_STATION_REVIEW.md#wacwas-elevation-and-logger-offset-review)
retains both reported elevations and the logger offset as static interpretation
metadata. CDEC sensor units do not establish logger-offset units or a vertical
datum. No numerical correction is supported or applied; current readings,
thresholds and NOAA identity decisions remain unchanged.

The [automatic WAC/WAS checks](WATER_STATION_REVIEW.md#automatic-wacwas-metadata-checks)
run with `python scripts/water_refresh.py --noaa-identifiers`. Five official
metadata pages are compared with the dated manual baseline. Changed elevations,
logger notes, equipment references, stage units or datum evidence are flagged;
missing, malformed and inaccessible sources remain explicit. The command saves
its latest result and exits 1 when review is needed. Unchanged known uncertainty
is retained without a recurring failure. No logger correction, NOAA link or
measurement history is created.

CDEC has priority for WAC/WAS station-elevation metadata. The CW3E value and
conflict remain visible; an unavailable or wrong-station CDEC record leaves the
preferred value unavailable. This preference does not establish a datum or
logger-offset interpretation and does not change current readings.
