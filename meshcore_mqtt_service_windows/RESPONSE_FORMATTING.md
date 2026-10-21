# Concise radio responses and manual review inventory

## Delivery policy

Each command request produces at most one tagged response, limited to 150 UTF-8
bytes including `@sender `. The shared formatter budgets the actual sender tag,
retains complete optional fields, and never cuts essential warning text mid-word.
Primary formatters put warning type, urgent action and material uncertainty first.
Identical whole fields are emitted once. Generic chain-control notices collapse
into the priority flag; location-specific restrictions and exceptions remain
whole optional fields. River replies state point-flooding uncertainty once. Gauge-change notices use
readable counts and categories, such as `1 gauge: major flooding`, with station
IDs labelled separately from names. Unknown thresholds, unusable readings and
lost coverage remain explicit; the highest-priority changed category is first.
Semicolons and pipes inside parentheses or brackets remain part of the same field.
Trail time estimates retain the complete speed and terrain qualifier or do not appear.
Counts use singular nouns only for one, including irregular plurals such as reaches.
The default standalone formatting budget reserves `@Reader `; standalone JSON
and snapshot modes retain their structured data where supported.

There are no `details` or `page N` command routes, continuation prompts, or radio
omission notices. Existing focused GIS field queries remain available. Each new
lookup is an independent request. Scheduled subscription events remain independent
notifications owned by the existing service; they are not pages of a lookup.
Flood notifications retain the existing queue, priority and five-second minimum
pause between completed notices. An alert disappearing before its known expiry
without cancellation evidence produces an uncertainty notice without a competing
`No active NWS flood alerts` notification. This rule also applies when the
disappearance is detected during source recovery.

The shipped `max_reply_parts` values are one. The responder enforces one response
regardless of older installed part-count settings. The reusable UTF-8 splitter
still supports explicit multipart calls for local callers/tests; command and
subscription delivery always select one. Optional URLs and fields are admitted
whole. Names can use a word-boundary ellipsis. If an external/custom program's
essential field cannot fit, the fallback is `Unable to return this result.`;
no partial warning or partial negation is transmitted.

GIS proximity replies use one heading, such as `Nearest trail:` or
`Trails within 2 mi:`, with `map distance` beside each distance. Mixed boundary
results retain their category in brackets. Focused `info near` replies retain
identity once, including recorded park status. Trail `info` replies exclude mapped
start coordinates; the independent `start` query remains available. Park `info`
replies exclude source polygon counts. These rules also apply to `info near`.
Boundary containment uses `Inside mapped park:` or `On mapped park boundary:`
(with the applicable category), retaining recorded status and the distinction
between polygon interiors and edges. Empty results describe local map data only.
Nearby-fire replies prioritize map distance instead of an incident identifier;
unknown containment and degraded-source qualifiers remain primary fields.
Landslide station names are admitted whole, including quoted titles and
parenthetical context; they are never shortened into an unfinished excerpt.
Both station lookup forms end at the name when it fits; no catalog label or
catalog-check date follows it. Firedata labels distinguish observations, forecasts,
cameras, treatments and outlooks. RAWS values retain units and valid zero readings.

## Manual review inventory

This inventory records presentation losses introduced by shortening, including
fields that can disappear only with a long sender tag or unusually long source
text. It is a source-derived review list, not an observation of live RF delivery.
Source parsing, coverage validation, cache freshness and structured snapshots
remain independent of presentation. A 150-byte reply cannot represent a complete
bulletin or every simultaneous condition. The entries below support later manual
selection of more useful fields without adding omission commentary to radio replies.

| Command or path | Retained priority | Information removed or conditional on available space |
| --- | --- | --- |
| Shared delivery and custom programs | One whole primary field; explicit failure fallback if it cannot fit | Automatic continuation, subsequent chunks, multipart counters, omission notices; custom outputs without bounded primary fields can yield only the fallback. |
| `!floodwarn` | Highest-priority official event; flash-flood higher-ground action; unavailable/unknown distinct from no active alerts | Additional alert bodies, full standard meanings, published headline/description/instruction, coordinates, source URLs and CAP metadata. Expiration, alert count and location are conditional. Full current records remain in local `--json` output. |
| `!floodalarm` notices | Each active event independently; flash action; unknown priority; cancellation, expiry and unconfirmed disappearance remain distinct | Full standard meanings and bulletin bodies. Change label, expiration and location may not fit. Source metadata remains in the current snapshot; categorical baselines do not gain full-text history. |
| `!floodalarm` enrollment/status | Enrollment/stop control; active state and data limitation | Full station inventories, saved point coordinates, category totals, routing caveat counts and detailed coverage list. Duration, mode and target are optional status fields. |
| Derived water notifications | Highest-priority changed gauge category or condition; coverage loss and not-point-flooding/not-all-clear qualification | Remaining gauge names, all category totals, source linkage detail and complete changed-station inventory. Station names, labelled IDs and associated USGS/agency-successor qualifiers are admitted together as whole optional fields; oversized names are omitted rather than excerpted. All categories still participate in baseline comparison. |
| `!floodstatus` | Official hazard/unknown status first; otherwise qualified model state | Detailed footprints, every gauge observation/category, all basin relationships and source metadata; gauge totals and target are optional. Local JSON retains the complete snapshot. |
| `!waterway` | Nearest reach and nearby-only qualification | Other reach names, gauge identities/readings, routing evidence and basin relationships. Reach count and target are optional. |
| `!basin` | Most-specific containing CalWater category/name | Other basin levels, codes, Water Board attribution and gauge context. Boundary qualifier, level count and target are optional. |
| `!traffic` | Closure/restriction state and chain-control flag | Full Caltrans regional narrative, multiple closures, schedules and long individual restriction blocks. Whole short blocks and source/timezone reference fit only when space permits. Critical closure/chain flags are selected before optional details. |
| `!rivers` | Highest-priority reported threshold exceedance, otherwise nearest station; gauge-only interpretation | Other stations, complete rolling observations/history, detailed station names and original report header. Issuance time, action/flood thresholds and result count are conditional. Structured JSON remains complete. |
| `!lightning` | Official event when present, otherwise forecast chance/coverage; incomplete-data qualifier | All individual forecast windows and interval-specific chance levels. Selected-window span, additional levels, alert/window counts and location are optional. No synthetic official Lightning Strike Warning label is used. |
| `!slidewarn` | Highest-severity matching official event and qualified landslide relevance; no-alert result is not an all-clear | Other alert summaries, full CAP text, instructions, links and office metadata. Expiration, count and target are optional. |
| `!slideinfo` | Station catalog identity; telemetry unverified and not local coverage | Instrument inventory, coordinates and fuller catalog descriptions. Catalog label and catalog-check date are removed from radio text. Distance and complete name are optional; the name is the final field when it fits, otherwise it is absent rather than excerpted. Structured station records retain catalog metadata. |
| `!slidealarm` | Initial alert relevance or qualified empty status; active monitoring/outage state; distinct update/lifecycle notices | Repeated initial bulletin details, location and expiration. Enrollment duration and stop hint are optional after initial hazard context. |
| `!fires` and `!fire` | First incident, containment or unconfirmed historical status; degraded-source qualifier | Other incidents, all perimeter details, source IDs/URLs and full timestamps. Acreage, record count and zone are conditional. Nearby-fire replies replace the display ID with map distance; other incident replies retain the optional display ID. Local JSON retains full IDs and records, and exact-ID lookup remains supported. |
| `!firezone` and `!firewarn` | Highest-priority fire-weather event or explicit unknown/no-active status | Other warning/watch bodies, every matching zone name and complete alert metadata. Zone labels, expiration and boundary context are optional. |
| `!firewx` | Highest-priority active warning and source limitation | Later forecast periods, extended discussion and long field groups. First-period fields retain terrain and wind-height qualifiers as a whole group or do not appear. Zone and period labels are conditional. |
| `!firedata` | Category/result count and degraded-source status | All records beyond the first; a long first context record can also exceed the budget. Full attributes, URLs and metadata remain in local JSON. |
| `!firealarm` | Enrollment/status and distinct incident/alert changes; unknown status on feed disappearance | Long incident names, full zone lists and repeated detail. Enrollment counts, zones and status duration are conditional. |
| `!smoke` | Mapped plume versus surface exposure distinction, incomplete detection or unknown satellite status | Plume age, direction/distance, geometry, ozone, PM concentration and detailed observation provenance. PM2.5 AQI/category, observation time and unknown origin text are conditional; no source fire is inferred. |
| `!firedanger` | Official warning or unknown local danger rating; ERC excludes wind | Full fuel assessment, fuel moisture, RAWS weather, wind/gust detail and source metadata. ERC/percentile, publication time, station name and warning-feed status are conditional. |
| `!aqi` | AQI/category and preliminary-data qualifier | Repeated labels and verbose station metadata. PM2.5 concentration, observation time, station/distance are conditional. |
| `!heatadv` | Highest-priority distinct heat alert or verified no-active result | Repeated location per alert and legacy Advisory prefixes. Additional distinct alert types and location are conditional. |
| `!snowpack` | Station snow depth, explicitly unknown/unavailable when necessary | Verbose introductory wording. Next-24-hour snowfall, station name and distance are conditional. |
| GIS commands (`!trail`, `!rec`, `!peak`, `!park`, `!boundary`) | Feature identity or requested field; geometry-repair qualification | Default subcommand menus, oversized descriptions, secondary attributes and list entries. Trail info removes mapped-start coordinates; the focused start query retains them. Park info removes source polygon counts; grouping still uses every source record. Trail time and its speed/terrain qualification are admitted together; the entire time field can be absent while shorter attributes remain. Focused field queries remain; no `+N more` notice is emitted. |
| `!status`, `!time`, `!uv` | Existing short result, subject to shared delivery budget | No dedicated formatter redesign; unusually long output follows the shared whole-field/fallback policy. |

## Review procedure and evidence

The [command response examples](RESPONSE_EXAMPLES.md) show all 31 commands and
all GIS field/category forms, closest/radius queries, help, alarm controls,
and triggered subscription notifications
with exact tagged byte counts. Notification examples are captured after baseline
acknowledgment and feed changes through actual service polling and queue callbacks. Near-query regression coverage
includes closest-only and radius searches, filtering before ranking, qualified
access policies, nearby-fire radius exclusion, and station catalog uncertainty.
The wording cleanup removes duplicate generic statements only; conditional
fields and presentation losses remain recorded in the inventory above.

For each proposed revision, compare short and maximum-length sender tags, Unicode
names, simultaneous warnings, outages and source uncertainty. Evaluate whether
the chosen primary field remains useful and whether optional timestamps and
location should take precedence over other measurements. Retain negation, units,
source qualifiers and warning actions together; do not make a partial datum look
complete. The offline regression suites cover byte limits, single-message delivery,
warning preservation, no paging, triggered flood/fire/landslide notifications with long and Unicode sender tags,
independent notification lifecycle guards and
paired command registration. Tests do not establish native Linux operation or
live MeshCore recipient delivery.
