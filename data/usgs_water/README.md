# California USGS current water data

This repository distributes the download programs, curated configuration, tests
and documentation. Downloaded datasets, generation pointers, generated catalogs
and validation reports are local outputs excluded from Git. Follow the
[fresh-clone water-data setup](../../docs/WATER_DATA_SETUP.md) before using offline
queries. Links to generated catalogs and reports below become available after
the relevant download or validation command completes. Historical investigation
counts describe development evidence, not files included with the repository.

This offline collection inventories monitoring locations throughout California
and downloads the latest available **gage height (00065)** and **discharge
(00060)** values. It includes inactive locations and partner-agency records
published by USGS. A station inventory entry does not imply a working flood
gauge, a current observation, or an available flood map.

The collection covers the entire state. Russian River is an integration test
using the existing flood-reference collection, not a geographic download limit.
All nine Water Board review regions have readable station files, GeoJSON,
READMEs, and catalogs. The six CalWater hierarchy levels remain separate.

- [Current inventory and counts](INVENTORY.md)
- [Current observation snapshot](OBSERVATIONS.md)
- [Statewide waterway links](NETWORK.md)
- [Statewide downstream and tributary tables](ROUTING.md)
- [Supplemental station-link decisions and unresolved cases](LINK_REVIEW.md)
- [Supplemental address evidence and refresh procedure](LINK_REVIEW_METHODS.md)
- [Original-agency investigation of 37 unresolved stations](AGENCY_REVIEW.md)
- [Agency evidence, resolved static addresses and limitations](AGENCY_REVIEW_METHODS.md)
- [Local operating-agency investigation of the remaining 24 stations](LOCAL_REVIEW.md)
- [Local metadata relationships, evidence limits and refresh](LOCAL_REVIEW_METHODS.md)
- [Additional official maps and records: all 24 unresolved cases](ADDITIONAL_AGENCY_REVIEW.md)
- [Five-source access retries and alternate official records](SOURCE_ACCESS_REVIEW.md)
- [Automatic source-rule audit, diagnostics and offline replay](SOURCE_RULE_AUDIT.md)
- [Routing, potential basin connections and limitations](ROUTING_METHODS.md)
- [Relationship and interpretation methods](METHODS.md)
- [Agency citations and acquisition evidence](SOURCES.md)
- [Machine-readable validation results](verification.json)
- [Statewide routing validation results](routing_verification.json)
- [Station-link review validation results](link_review_verification.json)
- [Original-agency review validation results](agency_review_verification.json)
- [Local operating-agency validation results](local_review_verification.json)

## Current-value retention

Only one latest reported value per returned time series is retained. Refreshes
replace the prior measurement snapshot after successful publication and checksum
verification. Seven-day downloads, historical level series, trend histories,
and accumulated observation generations are not retained. An older last-known
value can remain the latest available source reading; its original timestamp
and explicit stale status distinguish it from a fresh reading.

Original current-response bytes, timestamps, quality flags, series definitions,
effective threshold information, units, station attributes, and provenance remain
available to explain the current readings. Inventory and network metadata retain
versioned generations. Existing Basin Plan, CalWater, EBMUD, and flood-reference
originals are not changed or deleted. Their independent retention policies remain
documented in their own guides.

## Refresh

Run from the repository root on Windows or Linux with Python 3.11 or later:

```text
python -m pip install -r data/usgs_water/requirements.txt
python -m data.usgs_water.refresh --mode all
python -m data.usgs_water.validate --output data/usgs_water/verification.json
python -m data.usgs_water.validate_routing --output data/usgs_water/routing_verification.json
```

Refresh schedules are independent; no background task or MeshCore command is
registered by these tools:

```text
python -m data.usgs_water.refresh --mode observations
python -m data.usgs_water.refresh --mode inventory
python -m data.usgs_water.refresh --mode network
python -m data.usgs_water.refresh --mode link-review
python -m data.usgs_water.refresh --mode agency-review
python -m data.usgs_water.refresh --mode local-review
python -m data.usgs_water.refresh --mode routing
```

`observations` performs two statewide paginated latest-value queries. Updating
it every 15 minutes is a suggested operating interval, subject to source latency
and API limits. Refresh inventory less frequently, such as daily or weekly, and
refresh network links after inventory changes. Both dependent products pin an
inventory version; validation reports a version mismatch rather than mixing them
silently. `all` updates inventory, observations, network, supplemental link review,
original-agency review, local operating-agency review, then routing when an earlier routing archive exists.
An initial installation builds primary routing first; run `link-review`,
`agency-review`, `local-review`, and rebuild routing afterward. Static
routing refreshes are separate from frequent current-value downloads.
An offline rebuild can reuse verified source geometry with
`--mode routing --reuse-routing-sources`; see the [routing methods](ROUTING_METHODS.md).

An optional `USGS_API_KEY` environment variable enables the USGS account's higher
request allowance. The key is sent in the `X-Api-Key` header and is not saved in
URLs or receipts. See [USGS key guidance](https://api.waterdata.usgs.gov/docs/ogcapi/keys/).
Anonymous throttling produces `rate_limit.json` with the source's retry time.
Resume the exact pending directory after that time:

```text
python -m data.usgs_water.refresh --mode observations --resume data/usgs_water/observations/.pending-GENERATION
python -m data.usgs_water.refresh --mode network --resume data/usgs_water/network/.pending-GENERATION
```

Replace `GENERATION` with the directory actually created. Resume verifies saved
URLs and hashes before reusing responses. It does not re-download cached pages or
change the pinned scope. Failed builds preserve the last usable pointer. Once a
measurement refresh succeeds, obsolete measurement generations and interrupted
measurement builds are removed. Metadata/network archives are preserved.

## Offline use

```text
python -m data.usgs_water.report --name "RUSSIAN"
python -m data.usgs_water.report --station USGS-11464000
python -m data.usgs_water.report --station USGS-11467002
```

Search uses published station names and retains agency-qualified string IDs and
leading zeroes. Named creeks, rivers, canals, reservoirs, and watershed attributes
remain in the source records and CalWater catalogs. Missing names are not invented.

The active paths are resolved through `inventory.json`, `observations.json`,
`network.json`, `link_review.json`, `agency_review.json`, and `routing.json`.
Each points to a checksummed manifest. Current readings are offered
as CSV and Parquet; station locations and original attributes are compressed
GeoJSON. Join values to stations with `monitoring_location_id = station_id`, and
join series definitions with `time_series_id`. Do not join by name alone.

Current readings for each region can be selected using the region's `stations.csv`;
measurements remain in one statewide table to avoid maintaining duplicate copies.
`series_conditions.csv` is a build-time assessment. The report command recalculates
freshness at read time; offline data does not stay current indefinitely.
Station reports also link current readings to statewide downstream waterways and
potential basin candidates. Full relationship results are available in the routing
SQLite database and CSV exports; the report labels its display limits.
Supplemental decisions retain conflicting candidates and distinguish static
nonnetwork addresses from routable links. The original primary NLDI table remains
available alongside the effective station table used for routing.
The original-agency review adds static feature relationships and explicit agency
exclusions. Its initial 13 additional addresses have no downstream topology;
they do not increase routing or predicted-flood coverage.

## Validation and limits

```text
python -m unittest discover -s data/usgs_water -p "test_*.py"
python -m data.usgs_water.validate --output data/usgs_water/verification.json
python -m data.usgs_water.validate_routing --output data/usgs_water/routing_verification.json
python -m data.usgs_water.validate_link_review --output data/usgs_water/link_review_verification.json
python -m data.usgs_water.validate_agency_review --output data/usgs_water/agency_review_verification.json
```

Validation checks original response hashes, statewide scope, current-only
retention, single-value series identities, regional catalogs, CalWater station
joins, statewide network lookup coverage, and Russian River reach consistency.
It also reruns the existing flood-reference topology and scenario checks.
The routing validator checks directed path closure, minimum hops, exact basin
aggregation, all nine regions, current-station coverage, sampled spatial overlaps,
and continuity with the Russian River pilot.
The supplemental validator verifies source receipts, replays every decision,
checks the effective routing overlay, and confirms that unresolved addresses
acquire no unsupported downstream links.
The agency validator also verifies original catalog selections, publisher
data-file checksums and static address decisions. Publisher metadata
discrepancies are recorded separately from checks on the station data.

Provisional and estimated values retain their flags. Multiple sensors remain
separate. Station altitude is not automatically a verified gage-zero elevation.
Stage values are not transferred between gauges or datums. Discharge does not
directly specify flood depth or footprint. Current readings can support official
threshold review, but these tools do not produce a new flood forecast, arrival
time estimate, or statewide inundation model.
