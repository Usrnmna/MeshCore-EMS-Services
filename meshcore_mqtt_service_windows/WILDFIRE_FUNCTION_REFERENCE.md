# Wildfire, smoke, and fuel-danger implementation reference

[Usage, configuration, sources, and limitations](WILDFIRE_GUIDE.md) | [Service function index](FUNCTION_REFERENCE.md).

This focused reference lists source signatures, methods, and nested callbacks.
Descriptions retain important side effects and source constraints. Implementation
documentation does not establish live-provider, installed-service, or physical
radio validation. Persistent monitoring remains owned by the existing service.

<a id="wildfire_service-py"></a>
## wildfire_service.py

[Source](wildfire_service.py).

Service-owned wildfire refresh and persistent, channel-scoped subscriptions.

| Function signature | Purpose and behavior |
| --- | --- |
| `async refresh_loop(root, config)` | Run one bounded child refresh per service session; SQLite excludes other writers. |
| `changes(old, new, config)` | Compare against the last notified baseline; disappearance never implies containment. |
| `WildfireAlarms.__init__(self, db, channel, identity, config, read, notify, allowed, clock=time.time)` | Create persistent channel/sender subscriptions, validate settings, and disable identity-mismatched or unassigned records. |
| `WildfireAlarms.row(self, sender)` | Read one sender/channel subscription as a dictionary without changing the shared connection row factory. |
| `WildfireAlarms.remember(self, request, now)` | Reserve a revision at acceptance; off cancels even while an older lookup is pending. |
| `WildfireAlarms.current(self, reading)` | Recheck identity, expiry, assignment and revision after awaits and queued radio sends. |
| `async WildfireAlarms.control(self, request)` | Resolve and baseline an enrollment, or inspect/cancel it; readiness waits for acknowledgment. |
| `WildfireAlarms.control_current(self, request)` | Prevent a superseded on/off acknowledgment from leaving the radio queue. |
| `WildfireAlarms.acknowledge(self, request)` | Mark the matching enabled revision ready after acknowledgment transmission. |
| `async WildfireAlarms.check_one(self)` | Preserve the baseline on outage; emit one outage/recovery notice and meaningful changes. |
| `async WildfireAlarms.run(self)` | Check due subscriptions until cancellation; log failures and sleep when no work is due. |

<a id="scripts-wildfire_lookup-py"></a>
## scripts/wildfire_lookup.py

[Source](scripts/wildfire_lookup.py).

Shared wildfire queries; dedicated programs select their own command behavior.

| Function signature | Purpose and behavior |
| --- | --- |
| `parse_query(command, text)` | Validate radio syntax without HTTP, filesystem mutations, or shell interpretation. |
| `resolve_target(store, query)` | Resolve full zone polygons; place names represent the geocoder's selected point. |
| `identifier(value)` | Normalize IRWIN GUIDs; names and service-specific object IDs are never join keys. |
| `number(value, maximum=None)` | Keep missing/invalid source measurements unknown, including invalid percentages. |
| `incidents(store, source_features=None)` | Merge by IRWIN ID with explicit EGP-summary precedence and retained observations. |
| `incidents.observed(feature)` | Read the published perimeter timestamp with its documented fallback; return zero when no usable timestamp exists. |
| `historical_incidents(store)` | Return last-seen local observations for explicit detail lookup, never the current list. |
| `matches(incident, geometry, point=None, radius=None)` | Match full perimeters independently of origin, with a separate proximity mode. |
| `health(store, names, config, now)` | Describe acquisition freshness separately from source observation timestamps. |
| `report(command, text, store, config=None, now=None)` | Return structured results and source health; never enroll a subscription. |
| `moment(value)` | Render UTC observations in the shared configured reply timezone. |
| `context_line(category, feature)` | Provide source-specific, unit-labelled context without inventing a composite risk score. |
| `format_report(data, config=None)` | Return one focused result, prioritizing alerts and degraded-source status. |
| `monitor_snapshot(data)` | Exclude retrieval timestamps from comparisons; require complete fresh core feeds. |
| `main(command, argv=None)` | Run one dedicated command, optionally emitting JSON or explicitly refreshing local data. |

<a id="scripts-wildfire_refresh-py"></a>
## scripts/wildfire_refresh.py

[Source](scripts/wildfire_refresh.py).

Refresh validated wildfire snapshots; standalone execution never starts a scheduler.

| Function signature | Purpose and behavior |
| --- | --- |
| `seed(store)` | Initialize offline zones from a checksum-verified package snapshot. |
| `boundaries(client)` | Retrieve California and all intersecting candidate fire zones, retaining whole geometry. |
| `refresh(store, config, only=None, force=False, client=None)` | Refresh sources independently under one lease; failures retain successful snapshots. |
| `main(argv=None)` | Perform a bounded refresh, cache-status inspection, or GeoJSON export. |

<a id="scripts-wildfire_settings-py"></a>
## scripts/wildfire_settings.py

[Source](scripts/wildfire_settings.py).

Wildfire configuration shared by standalone programs and the service worker.

| Function signature | Purpose and behavior |
| --- | --- |
| `validate(settings)` | Merge defaults and reject settings that could cause unbounded work. |
| `load()` | Read service-provided settings or the package's standalone configuration. |
| `database_path()` | Resolve installed state independently from the application/source directory. |

<a id="scripts-wildfire_sources-py"></a>
## scripts/wildfire_sources.py

[Source](scripts/wildfire_sources.py).

Bounded public-source clients. Only complete, validated batches are returned.

| Function signature | Purpose and behavior |
| --- | --- |
| `timestamp(value)` | Convert ArcGIS epoch milliseconds or explicit-offset ISO timestamps to UTC seconds. |
| `Client.__init__(self, seconds=240, stage_dir=None)` | Initialize a shared monotonic refresh deadline and optional bounded-download staging directory. |
| `Client.staged_get(self, url, params, prefix, suffix)` | Resume large reference downloads across bounded passes; never publish partial data. |
| `Client.get(self, url, params=None, post=False)` | Fetch bounded HTTPS JSON within the shared deadline; reject errors and allow one retry for selected transient HTTP failures. |
| `Client.arcgis(self, url, where='1=1', bounds=None, resume=False)` | Fetch a stable ID inventory, then complete batches; reject missing/extra IDs. |
| `Client.source(self, name, bounds)` | Collect outlook leaf layers atomically, preserving day/type and layer URL. |
| `Client.alerts(self)` | Fetch all pages for the four-state region; cancelled/expired filtering is downstream. |

<a id="scripts-wildfire_spatial-py"></a>
## scripts/wildfire_spatial.py

[Source](scripts/wildfire_spatial.py).

Whole-zone geographic operations for California and interstate fire coverage.

| Function signature | Purpose and behavior |
| --- | --- |
| `checked_geometry(feature)` | Validate source coordinates; preserve repair provenance when repair is necessary. |
| `prepare_zones(features, california)` | Select area overlaps, retaining each complete official zone including neighboring states. |
| `scope(zones, radius_miles=100)` | Cover every supported proximity search, including centers at the outer zone edge. |
| `point_zones(zones, latitude, longitude)` | Include exact-boundary matches; callers must not arbitrarily pick one of several zones. |
| `distance_miles(geometry, latitude, longitude)` | Measure from the query location using a local azimuthal-equidistant projection. |

<a id="scripts-wildfire_store-py"></a>
## scripts/wildfire_store.py

[Source](scripts/wildfire_store.py).

Atomic source snapshots and spatial candidates; SQLite connections stay local.

| Function signature | Purpose and behavior |
| --- | --- |
| `encode(value)` | Serialize stable, finite JSON for provenance and change comparisons. |
| `Store.__init__(self, path, writable=False)` | Open a validated schema-1 cache; writable mode creates directories, WAL tables, bounds, history, and a refresh lease. |
| `Store.close(self)` | Close the SQLite connection. |
| `Store.__enter__(self)` | Return the cache for context-managed use. |
| `Store.__exit__(self, *args)` | Close the cache when leaving its context, including after exceptions. |
| `Store.status(self, source)` | Return one source status or an explicit not-initialized record. |
| `Store.statuses(self)` | Return recorded source status dictionaries ordered by source name. |
| `Store.features(self, source, bounds=None)` | Use an R-tree to narrow candidates; callers perform exact intersections. |
| `Store.replace(self, source, features, url, now=None, history_days=7)` | Validate a complete batch before atomically replacing one source. Prior successful snapshots survive errors. Changed observations are retained for bounded local history; geometry is never synthesized for point-only fires. |
| `Store.fail(self, source, error, now=None)` | Record a failed attempt without altering good data or its acquisition time. |
| `Store.lease(self, seconds=600)` | Exclude competing writers; expiry recovers a killed bounded refresh process. |

<a id="scripts-fire_environment-py"></a>
## scripts/fire_environment.py

[Source](scripts/fire_environment.py).

Point-based smoke and fuel-danger reports with independently qualified evidence.

| Function signature | Purpose and behavior |
| --- | --- |
| `numeric(value, maximum=None)` | Normalize measured numeric fields; negative sentinels and nonfinite values are unknown. |
| `recent(value, now, limit)` | Reject stale and materially future observations independently of retrieval age. |
| `observation_time(value)` | Treat malformed individual observation dates as unavailable rather than aborting a report. |
| `available(store, name, now, limit)` | A failed refresh cannot support a current-condition or absence claim. |
| `nearest(features, latitude, longitude, radius, eligible)` | Filter quality and time before ranking eligible full geometries by distance. |
| `aqi_category(value)` | Apply EPA AQI category ranges to published AQI, never to raw concentrations. |
| `air_quality(store, latitude, longitude, config, now)` | Select fresh monitors separately per pollutant; retain provenance in JSON. |
| `air_quality.eligible(p)` | Require a fresh pollutant observation with a usable concentration or AQI before nearest-station selection. |
| `smoke_report(store, latitude, longitude, config, now)` | Describe recent mapped smoke; absence of mapped smoke does not establish clean air. |
| `fuel_assessment(percentile)` | Describe historical energy potential without inventing an official danger rating. |
| `danger_report(store, latitude, longitude, config, now)` | Use public model-Y daily maxima; detailed FEMS values remain separately timestamped. |
| `report(command, text, store, config=None, now=None)` | Resolve ZIP/city/GPS to a point, without requiring a California zone match. |
| `format_report(data)` | Keep smoke replies free of a location header, Monitor line, and PM10 line. |
| `main(command, argv=None)` | Run a read-only command, with optional explicit bounded refresh and full JSON. |

<a id="scripts-fire_environment_sources-py"></a>
## scripts/fire_environment_sources.py

[Source](scripts/fire_environment_sources.py).

Observed smoke and fire-danger adapters; preserve provider times and metadata.

| Function signature | Purpose and behavior |
| --- | --- |
| `download(client, url, payload=None, authorization=None)` | Bound binary/XML and authenticated JSON requests without exposing credentials. |
| `parse_hms(raw, day)` | Parse dated NOAA KML polygons, including holes, and reject missing time metadata. |
| `hms(client, now=None)` | Use today's analysis; fall back one UTC day only when today's file is absent. |
| `nfdrs(client)` | Join public daily FEMS-derived ERC/BI summaries to national station geometry. |
| `fems(client, station_ids)` | Fetch optional hourly modeled fuel moisture for explicitly configured stations. |

<a id="scripts-fire_weather-py"></a>
## scripts/fire_weather.py

[Source](scripts/fire_weather.py).

NWS fire-weather product parsing and zone-based alert interpretation.

| Function signature | Purpose and behavior |
| --- | --- |
| `ugc_codes(header)` | Expand state-qualified and compressed UGC ranges; exclude the expiration token. |
| `parse_fwf(product)` | Retain raw text, discussion, zone sections, and named forecast periods. FWF office formats differ. Unrecognized/empty products fail explicitly; raw text remains available in successful records for manual interpretation. |
| `fetch_fwf(client, office)` | Follow the most recently issued FWF product, including amended/corrected issues. |
| `fire_alerts(features, codes, now=None)` | Match official fire-zone codes even when NWS supplies no polygon. |
| `compact_period(period)` | Select fire-relevant fields while retaining terrain labels and wind reference height. |

<a id="scripts-firezone-py"></a>
## scripts/firezone.py

[Source](scripts/firezone.py).

Dedicated !firezone command program; persistent monitoring belongs to the service.

| Function signature | Purpose and behavior |
| --- | --- |

<a id="scripts-fires-py"></a>
## scripts/fires.py

[Source](scripts/fires.py).

Dedicated !fires command program; persistent monitoring belongs to the service.

| Function signature | Purpose and behavior |
| --- | --- |

<a id="scripts-fire-py"></a>
## scripts/fire.py

[Source](scripts/fire.py).

Dedicated !fire command program; persistent monitoring belongs to the service.

| Function signature | Purpose and behavior |
| --- | --- |

<a id="scripts-firewx-py"></a>
## scripts/firewx.py

[Source](scripts/firewx.py).

Dedicated !firewx command program; persistent monitoring belongs to the service.

| Function signature | Purpose and behavior |
| --- | --- |

<a id="scripts-firewarn-py"></a>
## scripts/firewarn.py

[Source](scripts/firewarn.py).

Dedicated !firewarn command program; persistent monitoring belongs to the service.

| Function signature | Purpose and behavior |
| --- | --- |

<a id="scripts-firedata-py"></a>
## scripts/firedata.py

[Source](scripts/firedata.py).

Dedicated !firedata command program; persistent monitoring belongs to the service.

| Function signature | Purpose and behavior |
| --- | --- |

<a id="scripts-firealarm-py"></a>
## scripts/firealarm.py

[Source](scripts/firealarm.py).

Dedicated !firealarm command program; persistent monitoring belongs to the service.

| Function signature | Purpose and behavior |
| --- | --- |

<a id="scripts-smoke-py"></a>
## scripts/smoke.py

[Source](scripts/smoke.py).

Dedicated !smoke point lookup; scheduling remains service-owned.

| Function signature | Purpose and behavior |
| --- | --- |

<a id="scripts-firedanger-py"></a>
## scripts/firedanger.py

[Source](scripts/firedanger.py).

Dedicated !firedanger point lookup; scheduling remains service-owned.

| Function signature | Purpose and behavior |
| --- | --- |
