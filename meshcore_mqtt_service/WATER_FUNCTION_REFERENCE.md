# Water and flood implementation reference

[Usage, configuration, sources, and limitations](WATER_GUIDE.md) | [Service function index](FUNCTION_REFERENCE.md).

This focused reference lists source signatures, methods, and nested callbacks.
Descriptions retain important side effects and source constraints. Implementation
documentation does not establish live-provider, installed-service, or physical
radio validation. Persistent monitoring remains owned by the existing service.

<a id="flood_alarm-py"></a>
## flood_alarm.py

[Source](flood_alarm.py).

Location-pinned flood subscriptions owned by the existing service/event loop.

| Function signature | Purpose and behavior |
| --- | --- |
| `FloodAlarms.__init__(self, db, channel, identity, config, read, notify, allowed, clock=time.time, monotonic=time.monotonic)` | Create persistent state and disable subscriptions whose channel identity or assignment changed. |
| `FloodAlarms.row(self, sender)` | Read one subscription without changing the shared connection's row factory. |
| `FloodAlarms.remember(self, request, now)` | Reserve ordered subscribe/stop revisions at acceptance; stop invalidates pending lookups immediately. |
| `FloodAlarms.current(self, reading)` | Recheck expiry, identity, revision and assignment after awaits and inside the radio queue. |
| `FloodAlarms.control_current(self, request)` | Suppress obsolete control acknowledgments while allowing status/help without enrollment. |
| `async FloodAlarms.control(self, request)` | Baseline an enrollment before acknowledgment; keep monitoring disabled on lookup failure. |
| `FloodAlarms.acknowledge(self, request)` | Permit scheduled checks only after the acknowledgment message has been sent. |
| `FloodAlarms.queue_notices(self, reading, notices, checked_at)` | Replace pending notices by sender/revision/key; queued state is current-only and in memory. |
| `FloodAlarms.reconcile_pending(self, reading, snapshot)` | Refresh queued evidence and follow replacement IDs even when content is unchanged. |
| `FloodAlarms.notice_valid(self, item)` | Reject obsolete source state, expired alerts and invalid subscriptions without network I/O. |
| `FloodAlarms.notification_current(self, reading)` | Guard each radio chunk after the shared send-slot wait, including source freshness. |
| `FloodAlarms.notification_fresh(self, item)` | Outage notices describe unknown state; other notices require a recent source check. |
| `async FloodAlarms.send_one(self)` | Send one independent response; the five-second gap begins after its single message finishes. |
| `async FloodAlarms.check_one(self)` | Check one due fixed point; retain baselines on failure and report outage/recovery once. |
| `async FloodAlarms.poll(self)` | Poll independently of notification delays and radio transmission waits. |
| `async FloodAlarms.deliver(self)` | Serialize independent responses on this channel without blocking polling. |
| `async FloodAlarms.run(self)` | Keep polling and paced delivery in the existing service's task lifetime. |

<a id="scripts-water_agency_review-py"></a>
## scripts/water_agency_review.py

[Source](scripts/water_agency_review.py).

Additional official metadata review for the 17 unresolved NOAA identities. Only one explicitly documented agency-successor chain is eligible. Historical USGS series dates describe coverage; no historical measurement values are read or retained. Names, coordinates and historical periods cannot create a link.

| Function signature | Purpose and behavior |
| --- | --- |
| `fetch_bytes(url)` | Bound downloads with in-memory redirect cookies; never persist cookies or payloads. |
| `MetadataCells.__init__(self, raw)` | Initialize table-cell extraction and feed UTF-8 or CP1252 agency HTML. |
| `MetadataCells.handle_starttag(self, tag, attrs)` | Start a table cell or preserve spacing within nested markup. |
| `MetadataCells.handle_endtag(self, tag)` | Commit normalized cell text at the closing td/th tag. |
| `MetadataCells.handle_data(self, data)` | Append source text while a table cell is active. |
| `parse_usgs(raw)` | Allowlist series coverage metadata, not daily/instantaneous/peak values. |
| `parse_hads(raw)` | Read the published USGS/NWSLI crosswalk, preserving non-unique candidates. |
| `verify_successor_metadata(report, cdec, hads)` | Verify the reviewed explicit crosswalk plus current CDM/HADS station metadata. The reviewed PDF table 2-2 (PDF page 26, printed page 13) explicitly pairs 11462000 and CDM. Its exact byte hash guards that manual interpretation. Coordinates corroborate this documented chain; they never discover a link. |
| `verify_successor_metadata.field(label)` | Require a unique metadata label and return the following cell, rejecting missing or ambiguous fields. |
| `api_matches(raw)` | Permit only the reviewed successor with a blank legacy USGS field, never a conflicting ID. |
| `enrich(document, gauge_fetch, download=fetch_bytes)` | Attach review evidence and the sole supported successor; failures withhold that link. |
| `enrich.acquire(item)` | Retrieve one agency source and return raw bytes, URL, and hash evidence, or an explicit unavailable result. |

<a id="scripts-water_changes-py"></a>
## scripts/water_changes.py

[Source](scripts/water_changes.py).

Categorical subscription comparison without storing historical measurement values.

| Function signature | Purpose and behavior |
| --- | --- |
| `changes(before, snapshot, now, structured=False)` | Retain last-known alert fingerprints through outages; compare material CAP updates and all gauge categories. Render readable counts and labelled station IDs with coverage and data-status qualifications. |

<a id="scripts-water_identifiers-py"></a>
## scripts/water_identifiers.py

[Source](scripts/water_identifiers.py).

Review exact NOAA/USGS identifiers without modifying the original inventory. The bundled table records the investigated stations. An explicit refresh replaces the runtime review, including failures; unsuccessful checks cannot revive an old match. Only static identity/threshold metadata is persisted, never observations.

| Function signature | Purpose and behavior |
| --- | --- |
| `threshold_value(value)` | Normalize missing/sentinel thresholds; zero is a valid published threshold. |
| `thresholds(categories)` | Keep only static stage/flow thresholds from known NOAA categories. |
| `threshold_status(categories)` | Distinguish published values, explicit missing values and absent source schema. |
| `download_catalog()` | Download a bounded national static report, with no historical level products. |
| `parse_catalog(raw)` | Reject schema changes, short national reports and conflicting identifier rows. |
| `review(targets, catalog_fetch=download_catalog, gauge_fetch=None)` | Corroborate each unique exact catalog ID with the independent gauge response. Names and proximity never authorize a match. Duplicate catalog entries, conflicting API identities and source failures retain explicit withheld rows. |
| `review.check(target)` | Evaluate one selected station against exact NOAA catalog/API identity and static threshold evidence; unsupported matches remain explicit. |
| `validate(document)` | Validate local review records before permitting supplemental identifier use. |
| `load()` | Prefer the latest explicit runtime review, including its unresolved outcomes. |
| `apply(station, rows)` | Overlay supported identities; never overwrite a conflicting original source ID. |
| `refresh()` | Replace the small runtime relationship table atomically; preserve original datasets. |

<a id="scripts-water_local-py"></a>
## scripts/water_local.py

[Source](scripts/water_local.py).

Read verified statewide collections using a separate spatial index; originals are read-only. The index contains bounding boxes and source pointers, never level measurements. Rebuild after inventory/routing changes. Observation refreshes are read directly.

| Function signature | Purpose and behavior |
| --- | --- |
| `reading_status(rows)` | Summarize current reading usability without retaining measurement values or ages. |
| `routing_caveats(coverage)` | Retain source graph limitations separately from eligibility of existing paths. |
| `read_json(path)` | Read UTF-8 JSON, using gzip decompression for .gz paths, and return the decoded document. |
| `checked_path(root, relative)` | Resolve a relative path inside the collection root and reject traversal outside it. |
| `verify_file(path, expected)` | Hash source bytes once during index building, or small current files during lookup. |
| `generation(root, kind, files=())` | Verify manifest and requested artifacts without repeatedly hashing unrelated archives. |
| `readonly(path)` | Open a read-only SQLite URI and return a connection with named row fields. |
| `signature(path)` | Return file size and nanosecond modification time for detecting source changes. |
| `build_index(config, output=None, collection=None)` | Atomically index verified static geometry and station identities; store no observations. An explicit collection selects a staged package. Relative routing pointers preserve the index when its complete generation moves. |
| `readings(root, now, max_age)` | Read the sole latest-value generation; never copy measurements into the spatial index. |
| `context(latitude, longitude, config, now, index_path=None)` | Resolve containing basins and nearby reaches; proximity is never an alarm-qualified link. |

<a id="scripts-water_lookup-py"></a>
## scripts/water_lookup.py

[Source](scripts/water_lookup.py).

Location-only water status and structured subscription snapshots.

| Function signature | Purpose and behavior |
| --- | --- |
| `parse_query(command, text)` | Validate bounded location syntax before any child/network work; controls never enroll. |
| `resolve(target, fetch=water_sources.get_json)` | Resolve exactly one US place; city/ZIP results represent a point, not the whole area. |
| `attempt(function, *args)` | Preserve partial source failures explicitly without suppressing other known conditions. |
| `snapshot(target, mode='conditions', config=None, now=None)` | Collect a bounded point snapshot; all observed values remain current-only. |
| `checked_snapshot(data, config, now=None)` | Reject malformed/stale subprocess output before activating persistent monitoring. |
| `compact(data)` | Keep only current alert fingerprints and categorical state for change detection, no levels. |
| `brief(text, limit=180)` | Collapse whitespace and shorten a source excerpt to the character limit with an explicit ellipsis. |
| `condition_summary(conditions)` | Count all linked gauge states without expanding the radio reply per station. |
| `format_alerts(data)` | Format verified official alerts, expiry, bounded headline/instruction excerpts, and source URLs; missing data never implies all-clear. |
| `format_status(command, data)` | Use explicit evidence labels and missing-data states in compact radio text. |
| `main(command, argv=None)` | Dedicated entry points call this once; direct alarm calls never create subscriptions. |
| `floodwarn_expiry(expires, fetched)` | Use the shared timezone; include a date when expiry is not on the lookup day. |
| `format_floodwarn(data)` | Select the highest-priority current flood event, preserving action and unknown status in one message. |

<a id="scripts-water_map_review-py"></a>
## scripts/water_map_review.py

[Source](scripts/water_map_review.py).

Non-authorizing map evidence for the sixteen unresolved NOAA identities. Map proximity and shared waterbody names never create a station link. Refresh retains static metadata only and flags changed candidate identities for review.

| Function signature | Purpose and behavior |
| --- | --- |
| `position(latitude, longitude)` | Reject malformed or nonfinite metadata coordinates before persisting them. |
| `parse_sites(raw)` | Retain exact USGS site identifiers, names and horizontal-position metadata. |
| `parse_map(raw)` | Reject truncated/error maps; allowlist static fields, excluding level values. |
| `candidate_metadata(lid, map_rows, gauge_fetch)` | Flag changed static identities without promoting even an exact new USGS ID. |
| `parse_onerain(raw)` | Read the public sites inventory, excluding telemetry, HTML and measurements. |
| `onerain_evidence(sid, candidate_lids, sites, available)` | Keep exact alias leads and reviewed operator aliases separate from accepted links. |
| `enrich(document, gauge_fetch, download=fetch_bytes)` | Replace auxiliary map evidence while leaving every operational identity untouched. Historical publication pages are manual context, not refreshed proof of current closure. NOAA map/API and USGS position metadata are checked live. |

<a id="scripts-water_notifications-py"></a>
## scripts/water_notifications.py

[Source](scripts/water_notifications.py).

Independent flood notifications with explicit CAP priority and uncertainty.  Priority is an application dispatch policy, not an official NWS ranking. Unknown fields use the highest scheduling tier without changing the published values.

| Function signature | Purpose and behavior |
| --- | --- |
| `normalized_priority(alert, field)` | Normalize CAP's deprecated Very Likely value; retain unknown source values. |
| `priority(notice)` | Order active notices by urgency, severity, certainty, newest effective time and ID. |
| `active_notice(alert, change)` | Keep only current alert metadata needed for delivery, never bulletin or gauge history. |
| `status_notice(text, available, alert_ids=None)` | Bind a source-status notice to expected availability and optional exact active IDs. |
| `official_notifications(before, snapshot, now)` | Create independent active/lifecycle notices; outages cannot claim alerts cleared. |
| `format_notification(notice, target, now)` | Repeat location for independent responses; standard descriptions apply only to active alerts. |

<a id="scripts-water_operator_records-py"></a>
## scripts/water_operator_records.py

[Source](scripts/water_operator_records.py).

Manually reviewed local-operator metadata; never an operational NOAA crosswalk. Publication dates and historical coverage are provenance, not water readings. Ordinary refresh copies this evidence without renewing its manual-review date.

| Function signature | Purpose and behavior |
| --- | --- |
| `evidence(station_id)` | Return independent static evidence; unknown IDs receive no review assertion. |

<a id="scripts-water_refresh-py"></a>
## scripts/water_refresh.py

[Source](scripts/water_refresh.py).

Refresh reviewed NOAA identities and/or the verified radio spatial index.

| Function signature | Purpose and behavior |
| --- | --- |
| `main()` | Parse explicit index/review refresh actions and return failure when review requires attention. |

<a id="scripts-water_settings-py"></a>
## scripts/water_settings.py

[Source](scripts/water_settings.py).

Location water-status settings shared by direct programs and the service.

| Function signature | Purpose and behavior |
| --- | --- |
| `validate(values)` | Validate local settings; radio requests cannot change paths, limits or source URLs. |
| `load()` | Read the active service environment or the standalone package configuration. |
| `data_root(config)` | Resolve the downloaded-data directory relative to the platform package when the setting is not absolute. |
| `collection(config)` | Pin the active managed USGS generation for one operation; preserve an explicit external data directory. |
| `runtime()` | Return the configured runtime directory or the package runtime default. |

<a id="scripts-water_sources-py"></a>
## scripts/water_sources.py

[Source](scripts/water_sources.py).

Bounded official point alerts and latest NOAA conditions, with current-only caching.

| Function signature | Purpose and behavior |
| --- | --- |
| `get_json(url, params=None)` | Fetch bounded JSON; stale HTTP caches and source errors cannot become valid conditions. |
| `cached(key, config, fetch, now=None, path=None)` | Replace one current record per product/target; errors never return old data as fresh. Fetchers must remove historical levels before returning. No raw gauge payload is persisted. Secure deletion and DELETE journals avoid accumulating obsolete levels. |
| `select_alerts(data, now)` | Keep actual effective flood CAP records, references and material-content fingerprints. |
| `alerts_at(lat, lon, config, now, fetch=get_json)` | Check NWS coverage before interpreting an empty point-matched alert response. |
| `alerts_at.retrieve()` | Verify point coverage and return actual NWS alerts with validated material fingerprints. |
| `gauge(lid, station_id, config, now, fetch=get_json)` | Use NOAA's own observation/category; never apply NOAA stage thresholds to USGS datums. |
| `gauge.retrieve()` | Validate NOAA identity and return the latest observed category, static thresholds, units, and datum metadata. |
| `arc_features(url, params, fetch)` | Fetch ArcGIS attributes; reject incomplete or malformed feature responses. |
| `model_at(lat, lon, config, now, fetch=get_json)` | Point-intersect current modeled footprints; missing features do not mean safe conditions. |
| `model_at.retrieve()` | Check the published NOAA domain and current-analysis intersection with explicit freshness/coverage status. |
| `rainfall_at(lat, lon, config, now, fetch=get_json)` | Expose the current 24-hour QPE pixel as point context, never as a basin-average total. |
| `rainfall_at.retrieve()` | Read optional point QPE context while retaining unknown valid time as a limitation. |

<a id="scripts-water_vertical_review-py"></a>
## scripts/water_vertical_review.py

[Source](scripts/water_vertical_review.py).

Check WAC/WAS interpretation metadata without correcting or storing readings. The fixed manual baseline remains unresolved. Live checks detect source drift; they cannot authorize a datum conversion, logger correction or NOAA identity.

| Function signature | Purpose and behavior |
| --- | --- |
| `PlainText.__init__(self, text)` | Initialize HTML entity decoding and collect the supplied metadata text. |
| `PlainText.handle_data(self, text)` | Append parsed text to the normalization buffer. |
| `normalized(text)` | Decode HTML entities and collapse metadata whitespace for comparison. |
| `one_after(cells, label)` | Require exactly one labeled field, including an explicitly empty value. |
| `numeric_units(value, units)` | Require the expected complete numeric/unit expression and return normalized decimal text. |
| `parse_metadata(key, raw)` | Allowlist interpretation fields; discard telemetry, raw notes and peak records. A newly published datum row or changed offset wording requires review rather than automatic interpretation. HTML checksums are provenance, not drift tests. |
| `parse_metadata.field(label)` | Require exactly one WAC metadata field and return its normalized text. |
| `enrich(document, download=fetch_bytes)` | Replace live checks for both legacy candidates, even on NOAA catalog failure. Source failures never fall back to a previous successful check. The manual baseline and its date remain fixed; only the separate live timestamp advances. |
| `enrich.check(item)` | Compare one official metadata source with the fixed manual baseline and report changes, access failures, or invalid schema. |

<a id="scripts-waterway-py"></a>
## scripts/waterway.py

[Source](scripts/waterway.py).

Dedicated !waterway location command; standalone execution creates no subscription.

| Function signature | Purpose and behavior |
| --- | --- |
| `main(argv=None)` | Execute this dedicated command once and return its status; no persistent subscription is enrolled. |

<a id="scripts-basin-py"></a>
## scripts/basin.py

[Source](scripts/basin.py).

Dedicated !basin location command; standalone execution creates no subscription.

| Function signature | Purpose and behavior |
| --- | --- |
| `main(argv=None)` | Execute this dedicated command once and return its status; no persistent subscription is enrolled. |

<a id="scripts-floodstatus-py"></a>
## scripts/floodstatus.py

[Source](scripts/floodstatus.py).

Dedicated !floodstatus location command; standalone execution creates no subscription.

| Function signature | Purpose and behavior |
| --- | --- |
| `main(argv=None)` | Execute this dedicated command once and return its status; no persistent subscription is enrolled. |

<a id="scripts-floodalarm-py"></a>
## scripts/floodalarm.py

[Source](scripts/floodalarm.py).

Dedicated !floodalarm location command; standalone execution creates no subscription.

| Function signature | Purpose and behavior |
| --- | --- |
| `main(argv=None)` | Execute this dedicated command once and return its status; no persistent subscription is enrolled. |
