# NOAA identifier and threshold review

This review covers the 33 upstream gauges that lacked NOAA identifiers in the
Russian River validation at `38.61324 -122.83638`. The statewide monitoring and
routing scope remains unchanged. These are identifier links, not new tributary
routes or flood-extent relationships.

## Evidence and results

The [NOAA All Gauges Report](https://water.noaa.gov/resources/downloads/reports/nwps_all_gauges_report.csv) contained 12,929 rows
when retrieved at `2026-10-21T03:11:38.341911+00:00`. Each accepted unique USGS ID was
independently corroborated against the matching [NOAA gauge API](https://api.water.noaa.gov/nwps/v1/docs/).
The [NOAA service catalog](https://water.noaa.gov/about/data-and-web-services-catalog)
publishes the report. The [river gauge service definitions](https://mapservices.weather.noaa.gov/eventdriven/rest/services/water/riv_gauges/MapServer)
distinguish undefined thresholds, unavailable current data and flood categories.

- 16 exact NOAA/USGS identifier matches: six with published stage thresholds and ten with none published.
- One additional agency-successor relationship links legacy USGS-11462000 to CDEC CDM and NOAA YDMC1. Its thresholds are not published.
- 16 stations remain unresolved after the additional agency-record review. All 17 originally unresolved IDs remain absent from the exact NOAA catalog and HADS cross-reference searches.
- The existing HEAC1 / USGS-11464000 match remains separate and unchanged. Including it gives seven threshold-bearing gauges among the 34 linked pilot gauges. Threshold presence does not establish a fresh observation.

The [machine-readable relationship table](WATER_STATION_REVIEW.json) contains every
reviewed station, disposition, source URL, catalog checksum, retrieval date and
allowlisted static thresholds. Missing thresholds are JSON null, never zero.
Names or nearby coordinates do not authorize a match. Negative search results
apply to the retrieved catalog; they do not establish that no agency gauge exists.

### Published thresholds

Values below are static NOAA stage thresholds in feet, not current readings.
They must not be applied to USGS stages with an assumed common vertical datum.

| USGS station | NOAA gauge | Action | Minor flood | Moderate | Major |
| --- | --- | --- | --- | --- | --- |
| USGS-11462500 | [HOPC1](https://api.water.noaa.gov/nwps/v1/gauges/HOPC1) | Not published | 15 | 23 | 26 |
| USGS-11463500 | [GEYC1](https://api.water.noaa.gov/nwps/v1/gauges/GEYC1) | 38 | 39.7 | 46 | 50 |
| USGS-11463682 | [JIMC1](https://api.water.noaa.gov/nwps/v1/gauges/JIMC1) | 25 | 26.23 | 31 | 36 |
| USGS-11463900 | [RMKC1](https://api.water.noaa.gov/nwps/v1/gauges/RMKC1) | 13.5 | 14.76 | 19.5 | 25 |
| USGS-11463980 | [RRHC1](https://api.water.noaa.gov/nwps/v1/gauges/RRHC1) | 20.8 | 25.42 | 29.93 | 36.73 |
| USGS-11465200 | [DGYC1](https://api.water.noaa.gov/nwps/v1/gauges/DGYC1) | 10 | 15 | Not published | Not published |

### Complete station inventory

| USGS station and inventory name | NOAA ID | Review result |
| --- | --- | --- |
| USGS-11460940 — RUSSIAN R NR REDWOOD VALLEY CA | Unresolved | No exact catalog match |
| USGS-11461000 — RUSSIAN R NR UKIAH CA | [UKAC1](https://api.water.noaa.gov/nwps/v1/gauges/UKAC1) | Matched; thresholds not published |
| USGS-11461400 — EF RUSSIAN R TRIB NR POTTER VALLEY CA | Unresolved | No exact catalog match |
| USGS-11461500 — EF RUSSIAN R NR CALPELLA CA | [CXLC1](https://api.water.noaa.gov/nwps/v1/gauges/CXLC1) | Matched; thresholds not published |
| USGS-11462000 — EF RUSSIAN R NR UKIAH CA | [YDMC1](https://api.water.noaa.gov/nwps/v1/gauges/YDMC1) via CDM | Supported agency successor; thresholds not published |
| USGS-11462080 — RUSSIAN R NR TALMAGE CA | [TLMC1](https://api.water.noaa.gov/nwps/v1/gauges/TLMC1) | Matched; thresholds not published |
| USGS-11462125 — SLIDE C NR UKIAH CA | Unresolved | No exact catalog match |
| USGS-11462500 — RUSSIAN R NR HOPLAND CA | [HOPC1](https://api.water.noaa.gov/nwps/v1/gauges/HOPC1) | Matched; thresholds published |
| USGS-11462700 — FELIZ C NR HOPLAND CA | Unresolved | No exact catalog match |
| USGS-11462900 — CUMMISKY C NR CLOVERDALE CA | Unresolved | No exact catalog match |
| USGS-11463000 — RUSSIAN R NR CLOVERDALE CA | [CDLC1](https://api.water.noaa.gov/nwps/v1/gauges/CDLC1) | Matched; thresholds not published |
| USGS-11463160 — BIG SULPHUR C NR MIDDLETOWN CA | Unresolved | No exact catalog match |
| USGS-11463170 — BIG SULPHUR C A G RESORT NR CLOVERDALE CA | [CDAC1](https://api.water.noaa.gov/nwps/v1/gauges/CDAC1) | Matched; thresholds not published |
| USGS-11463200 — BIG SULPHUR C NR CLOVERDALE CA | [BSCC1](https://api.water.noaa.gov/nwps/v1/gauges/BSCC1) | Matched; thresholds not published |
| USGS-11463500 — RUSSIAN R A GEYSERVILLE CA | [GEYC1](https://api.water.noaa.gov/nwps/v1/gauges/GEYC1) | Matched; thresholds published |
| USGS-11463682 — RUSSIAN R A JIMTOWN CA | [JIMC1](https://api.water.noaa.gov/nwps/v1/gauges/JIMC1) | Matched; thresholds published |
| USGS-11463700 — SAUSAL C NR HEALDSBURG CA | Unresolved | No exact catalog match |
| USGS-11463900 — MAACAMA C NR KELLOGG CA | [RMKC1](https://api.water.noaa.gov/nwps/v1/gauges/RMKC1) | Matched; thresholds published |
| USGS-11463940 — FRANZ C NR KELLOGG CA | Unresolved | No exact catalog match |
| USGS-11463980 — RUSSIAN R A DIGGER BEND NR HEALDSBURG CA | [RRHC1](https://api.water.noaa.gov/nwps/v1/gauges/RRHC1) | Matched; thresholds published |
| USGS-11464050 — DRY C TRIB NR HOPLAND CA | Unresolved | No exact catalog match |
| USGS-11464400 — DRY C NR YORKVILLE CA | Unresolved | No exact catalog match |
| USGS-11464500 — DRY C NR CLOVERDALE CA | Unresolved | No exact catalog match |
| USGS-11464860 — WARM SPRINGS C NR ASTI CA | Unresolved | No exact catalog match |
| USGS-11464880 — WARM SPRINGS C NR SKAGGS SPRINGS CA | Unresolved | No exact catalog match |
| USGS-11465000 — DRY C BL WARM SPRINGS DAM NR GEYSERVILLE CA | [DRWC1](https://api.water.noaa.gov/nwps/v1/gauges/DRWC1) | Matched; thresholds not published |
| USGS-11465050 — DUTCHER C NR ASTI CA | Unresolved | No exact catalog match |
| USGS-11465150 — PENA C NR GEYSERVILLE CA | Unresolved | No exact catalog match |
| USGS-11465200 — DRY C NR GEYSERVILLE CA | [DGYC1](https://api.water.noaa.gov/nwps/v1/gauges/DGYC1) | Matched; thresholds published |
| USGS-11465240 — DRY C BLW LAMBERT BR NR GEYSERVILLE CA | [DCLC1](https://api.water.noaa.gov/nwps/v1/gauges/DCLC1) | Matched; thresholds not published |
| USGS-11465300 — MILL C NR HEALDSBURG CA | Unresolved | No exact catalog match |
| USGS-11465350 — DRY C NR MOUTH NR HEALDSBURG CA | [DRIC1](https://api.water.noaa.gov/nwps/v1/gauges/DRIC1) | Matched; thresholds not published |
| USGS-11465390 — RUSSIAN R NR WINDSOR CA | [WDSC1](https://api.water.noaa.gov/nwps/v1/gauges/WDSC1) | Matched; thresholds not published |

### Other official candidates examined

The following official NOAA records supplied an empty `usgsId`. Only YDMC1
received an independently documented agency-successor link. Similar names and
coordinates alone do not establish identity or succession for the others.

| NOAA candidate | Reason the candidate does not authorize a match |
| --- | --- |
| [YDMC1](https://api.water.noaa.gov/nwps/v1/gauges/YDMC1), East Fork Russian River below Coyote Dam | Agency report explicitly pairs 11462000 and CDM; CDEC and HADS corroborate CDM/YDMC1. Accepted as a successor, not an exact current USGS ID. |
| [FVSC1](https://api.water.noaa.gov/nwps/v1/gauges/FVSC1), Franz Creek at Franz Valley School Rd | No published API USGS ID; cannot equate it with USGS-11463940. |
| [DCOC1](https://api.water.noaa.gov/nwps/v1/gauges/DCOC1), Dry Creek at Cooley Ranch Road | No published API USGS ID; multiple Dry Creek stations remain distinguishable. |
| [WSDC1](https://api.water.noaa.gov/nwps/v1/gauges/WSDC1), Warm Springs Reservoir | Reservoir metadata does not establish identity with Warm Springs Creek stations. |

YDMC1 is covered by the narrowly scoped refresh rule below. The other candidate
notes authorize no additional links or alarms.

## Additional official agency review

The 17 remaining IDs were checked against the [NOAA HADS California USGS/NWSLI cross-reference](https://hads.ncep.noaa.gov/USGS/CA_USGS-HADS_SITES.txt)
and [USGS site series-catalog metadata](https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=11460940,11461400,11462000,11462125,11462700,11462900,11463160,11463700,11463940,11464050,11464400,11464500,11464860,11464880,11465050,11465150,11465300&seriesCatalogOutput=true&siteStatus=all).
HADS has no exact USGS-ID entry for any of the 17. Its [crosswalk description](https://hads.ncep.noaa.gov/USGS/)
limits coverage to data collection platforms processed by HADS; absence is not
proof that a station or another agency sensor does not exist. USGS catalog
coverage dates for stage/discharge and peak-flow series end before the review
for all 17. These are historical record periods, not downloaded measurements,
and do not by themselves establish current operating status.

### Supported agency-successor chain

1. The [Telemetered Water Monitoring Project report, table 2-2, PDF page 26 / printed page 13](https://www.rrfc.net/files/32a1f7e23/Telemetered%2BWater%2BMonitoring%2BProject%2BReport%2BPt%2B2%2BApril%2B2025.pdf#page=26) explicitly pairs station codes `11462000, CDM` for the East Fork Russian below Coyote Dam, with USACE as operator. The district-hosted April 2025 report is marked **DRAFT**; it supplies the explicit code cross-reference, corroborated by the current agency records below.
2. [CDEC CDM metadata](https://cdec.water.ca.gov/dynamicapp/staMeta?station_id=CDM) identifies the East Fork Russian below Coyote Dam, operator US Army Corps of Engineers, at latitude 39.197500 and longitude -123.186400.
3. [NOAA HADS Eureka station metadata](https://hads.ncep.noaa.gov/hsas/EKA_dcps.shtml) identifies the named outlet station `(CDM)` as `YDMC1`, GOES `CE902418`, owner code `CESPD1`.
4. The [NOAA YDMC1 gauge API](https://api.water.noaa.gov/nwps/v1/gauges/YDMC1) corroborates the reviewed name and CDEC position. Its USGS identifier remains blank. All four flood categories have missing stage/flow thresholds.

The [USGS 2011 station description](https://wdr.water.usgs.gov/wy2011/pdfs/11462000.2011.pdf)
locates legacy 11462000 at the Coyote Dam outlet. An [official USACE turbidity report](https://www.spn.usace.army.mil/Portals/68/docs/Lake%20Mendo/Appendix_A_Russian_River_Turbidity_Report.pdf)
also distinguishes USACE sampling near the legacy gauge. Neither proximity nor
the historic datum is used to establish equivalence of current measurements.
The accepted relationship is `matched_agency_successor`; the current source is
NOAA YDMC1. Legacy USGS latest readings remain stale in the installed current
snapshot. No threshold, datum conversion, rating curve or level history is inferred.

The county-hosted GSP record was inaccessible (HTTP 403); it was not used as
runtime proof. A final GSP link from the GSA resolves to a 142 MB PDF and was not
downloaded. The bounded 2.36 MB district-hosted report and current agency metadata
above form the retained evidence chain.

### Coverage metadata for all 17 investigated stations

End dates below are the latest dates in the retrieved USGS catalog for the
specified data class. A dash means no such series was returned. Peak-only
records are not current stage/discharge data and do not supply NOAA thresholds.

| Legacy USGS ID | Daily stage/discharge end | Unit-value stage/discharge end | Peak-record end | Agency review |
| --- | --- | --- | --- | --- |
| [USGS-11460940](https://waterdata.usgs.gov/monitoring-location/USGS-11460940/) | 1968-09-29 | — | 1977-12-14 | Unresolved; no supported crosswalk |
| [USGS-11461400](https://waterdata.usgs.gov/monitoring-location/USGS-11461400/) | 1961-09-29 | — | 1973-01-16 | Unresolved; no supported crosswalk |
| [USGS-11462000](https://waterdata.usgs.gov/monitoring-location/USGS-11462000/) | 2011-10-01 | 2011-10-02 | 2011-03-28 | CDM → YDMC1 successor |
| [USGS-11462125](https://waterdata.usgs.gov/monitoring-location/USGS-11462125/) | — | — | 1973-01-16 | Unresolved; no supported crosswalk |
| [USGS-11462700](https://waterdata.usgs.gov/monitoring-location/USGS-11462700/) | 1966-09-29 | — | 1966-01-04 | Unresolved; no supported crosswalk |
| [USGS-11462900](https://waterdata.usgs.gov/monitoring-location/USGS-11462900/) | — | — | 1962-03-26 | Unresolved; no supported crosswalk |
| [USGS-11463160](https://waterdata.usgs.gov/monitoring-location/USGS-11463160/) | 1979-09-29 | — | 1979-02-13 | Unresolved; no supported crosswalk |
| [USGS-11463700](https://waterdata.usgs.gov/monitoring-location/USGS-11463700/) | — | — | 1962-02-13 | Unresolved; no supported crosswalk |
| [USGS-11463940](https://waterdata.usgs.gov/monitoring-location/USGS-11463940/) | 1968-09-29 | — | 1976-02-29 | Unresolved; no supported crosswalk |
| [USGS-11464050](https://waterdata.usgs.gov/monitoring-location/USGS-11464050/) | 1969-09-29 | — | 1974-01-16 | Unresolved; no supported crosswalk |
| [USGS-11464400](https://waterdata.usgs.gov/monitoring-location/USGS-11464400/) | 1983-09-29 | — | 1983-01-26 | Unresolved; no supported crosswalk |
| [USGS-11464500](https://waterdata.usgs.gov/monitoring-location/USGS-11464500/) | 1980-09-29 | — | 1980-02-17 | Unresolved; no supported crosswalk |
| [USGS-11464860](https://waterdata.usgs.gov/monitoring-location/USGS-11464860/) | 1983-09-29 | — | 1983-01-26 | Unresolved; no supported crosswalk |
| [USGS-11464880](https://waterdata.usgs.gov/monitoring-location/USGS-11464880/) | — | — | 1962-02-13 | Unresolved; no supported crosswalk |
| [USGS-11465050](https://waterdata.usgs.gov/monitoring-location/USGS-11465050/) | 1973-03-13 | — | 1973-01-11 | Unresolved; no supported crosswalk |
| [USGS-11465150](https://waterdata.usgs.gov/monitoring-location/USGS-11465150/) | 1990-09-30 | — | 1990-01-13 | Unresolved; no supported crosswalk |
| [USGS-11465300](https://waterdata.usgs.gov/monitoring-location/USGS-11465300/) | — | — | 1962-02-13 | Unresolved; no supported crosswalk |

The [Water Board validation-site appendix](https://www.waterboards.ca.gov/waterrights/water_issues/programs/instream_flows/docs/draft_policy_2008/08_task3_apxf.pdf)
independently describes historical records for the Potter Valley tributary, Dry
Creek tributary, Franz Creek and Warm Springs Creek near Asti. It provides no
NOAA successor crosswalk. The nearby Franz Valley School Road, Cooley Ranch and
Lake Sonoma candidates therefore remain distinct from the unresolved legacy IDs.

### Refresh and source-change guards

`--noaa-identifiers` now rechecks this agency evidence as part of the same
33-station refresh. `agency_sources` records source URLs and SHA-256 hashes;
per-station `agency_review` retains allowlisted series dates, HADS candidates
and the decision. Report bytes and raw HTML/API payloads remain in memory only.
The report checksum pins the manually inspected code pair. Any changed report
requires manual review before acceptance. CDEC ID/operator/position and HADS
name/CDM/LID/GOES/operator must continue to match; missing/duplicate metadata,
source failures or a contradictory NOAA identity withhold the successor.

A new HADS candidate is retained for review rather than automatically promoted.
USGS historical coverage does not exclude a station from existing basin routing
or prevent later exact-ID recovery. Ordinary exact catalog/API matches still
take precedence; the agency exception applies only to 11462000/CDM/YDMC1.
Other blank or mismatched NOAA USGS IDs continue to fail identity verification.

Refresh replaces the current review and returns exit code 1 for agency-source
failures, while saving explicit withheld outcomes. A revoked successor cannot
continue through a still-valid current-observation cache. Every current fetch
also verifies the reviewed NOAA name, position and blank USGS field. No source
measurement is relabeled as a USGS observation. The full categorical monitoring
set and radio summaries identify agency-successor coverage separately.

## Further map and operator-record review

The remaining sixteen identities were checked against the [NOAA observed-gauge
map layer](https://mapservices.weather.noaa.gov/eventdriven/rest/services/water/riv_gauges/MapServer/0),
[USGS expanded station metadata](https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=11460940,11461400,11462125,11462700,11462900,11463160,11463700,11463940,11464050,11464400,11464500,11464860,11464880,11465050,11465150,11465300&siteOutput=expanded&siteStatus=all),
and the additional records below. The California map query returned 866 gauge
features. Only identifiers, names, waterbodies and coordinates were requested;
observed levels and forecasts were excluded. The map layer has no USGS identifier
field and cannot independently establish a USGS crosswalk.

**No additional NOAA-to-USGS link was supported. All sixteen remain unresolved.**
The previously supported CDM/YDMC1 successor and sixteen exact matches are unchanged.
This is a bounded evidence review, not a claim that no unexamined agency record
or current sensor exists.

### Operator records and distinct candidates

- [CW3E's Cooley Ranch station record](https://cw3e.ucsd.edu/metadata/sites/DAC)
  identifies CW3E/CDEC code DAC and a September 25, 2024 installation. Its NWS field
  is unfilled. [CDEC DAC metadata](https://cdec.water.ca.gov/dynamicapp/staMeta?station_id=DAC)
  identifies CW3E as operator at 38.789200, -123.155803.
  [NOAA HADS Monterey metadata](https://hads.ncep.noaa.gov/hsas/MTR_dcps.shtml)
  identifies the named Cooley Ranch station as DCOC1, GOES C8403F8A, owner UCSD01.
  These records corroborate the newer sensor, but do not explicitly pair it with
  USGS-11464400, even though the legacy Yorkville coordinates are very close.
  DCOC1 is not assigned to Yorkville, Cloverdale or the Dry Creek tributary.
- The same HADS metadata identifies **WSSC1**, Warm Springs Creek below Strawberry
  Creek, GOES C840491A, owner UCSD01. The [NOAA WSSC1 API](https://api.water.noaa.gov/nwps/v1/gauges/WSSC1)
  confirms that name and position, but supplies a blank USGS identifier. Neither
  the Asti nor Skaggs Springs legacy station is explicitly cross-referenced.
  A trial CDEC WSS metadata request returned no station fields and supplies no proof.
- [FVSC1 metadata](https://api.water.noaa.gov/nwps/v1/gauges/FVSC1) identifies Franz
  Valley School Road, with no USGS ID and a different position from legacy
  USGS-11463940. [WSDC1 metadata](https://api.water.noaa.gov/nwps/v1/gauges/WSDC1)
  identifies the Lake Sonoma reservoir, with no USGS ID. A reservoir is not
  equated with a creek gauge or its historic vertical datum.
- The [USGS 2003 discontinued-gauge inventory](https://pubs.usgs.gov/wdr/wdr-ca-03-2/WDR.CA.03.vol2.pdf)
  lists eleven of the sixteen legacy continuous-record stations. The
  [USGS 1970 surface-water index, published 1971](https://pubs.usgs.gov/circ/1971/0661/report.pdf)
  supplies partial-record context for the other five. Both PDFs were recovered through their official publication records during
  the source-access retry below. The relevant original table pages were visually
  checked. They remain historical context, not proof of present closure or
  acceptance evidence for a successor.
- [Sonoma Water's current-water-supply page](https://www.sonomawater.org/current-water-supply-levels)
  links its [OneRain stream-gauge map](https://sonoma.onerain.com/map/?sensor_class=25&show_thresholds=true&view=1476abfc-52ba-4423-8f6b-f2712d9593ed).
  The initial request returned a redirect loop; the cookie-aware retry below
  recovered the map and its public site inventory. CW3E's DAC record was available through the web reader; direct Python access
  encountered a certificate-chain failure. Certificate verification was not disabled.

### Decisions for each unresolved station

All rows retain their existing USGS identity and routing. Historical publication
classifications refer to those publications, not present operating status.

| USGS ID | Additional record/map finding | Decision |
| --- | --- | --- |
| 11460940 | Discontinued-record inventory; Russian River near Redwood Valley remains distinct from current mainstem gauges | No supported crosswalk |
| 11461400 | Discontinued tributary record; not the East Fork mainstem Calpella or Coyote Dam gauge | No supported crosswalk |
| 11462125 | Slide Creek partial-record entry in the historical index | No supported crosswalk |
| 11462700 | Feliz Creek discontinued-record entry | No supported crosswalk |
| 11462900 | Cummisky Creek historical partial-record entry; spelling variants do not supply NOAA identity | No supported crosswalk |
| 11463160 | Middletown discontinued-record entry; current Big Sulphur map sites CDAC1 and BSCC1 retain their other USGS identities | No supported crosswalk |
| 11463700 | Sausal Creek near Healdsburg historical partial-record entry | No supported crosswalk |
| 11463940 | Franz Creek discontinued-record entry; FVSC1 has a different mapped position and no USGS ID | Candidate retained, not linked |
| 11464050 | Dry Creek tributary discontinued-record entry; DCOC1 describes the main creek | Candidate retained, not linked |
| 11464400 | Yorkville discontinued-record entry; DAC/DCOC1 operator records describe a newer sensor near the legacy position without a legacy-ID pair | Candidate retained, not linked |
| 11464500 | Cloverdale discontinued-record entry; Cooley Ranch and Lake Sonoma remain distinct products | Candidates retained, not linked |
| 11464860 | Asti discontinued-record entry; WSSC1 is below Strawberry Creek without an explicit legacy-ID crosswalk | WSSC1 and reservoir candidate retained, not linked |
| 11464880 | Skaggs Springs historical partial-record entry; WSSC1 and reservoir metadata do not establish succession | Candidates retained, not linked |
| 11465050 | Dutcher Creek discontinued-record entry; nearby Dry Creek gauges do not establish identity | No supported crosswalk |
| 11465150 | Pena Creek discontinued-record entry; nearby mainstem Dry Creek gauges remain separate | No supported crosswalk |
| 11465300 | Mill Creek near Healdsburg historical partial-record entry; same-name streams elsewhere are not matches | No supported crosswalk |

### Persistent map-review metadata

`scripts/water_map_review.py` adds `map_record_review` to these sixteen rows and
`map_sources` to the existing relationship table. Each row records the check time,
USGS name/position/horizontal datum, historical reference and its access limitation,
plus curated candidate metadata. `link_authorized` is always false. The operational
`lid`, identity status, threshold status, reading availability and routing are
not changed by this auxiliary review. No new station or tributary link is created.

`--noaa-identifiers` repeats the USGS static-site, NOAA California-map and
OneRain site-inventory queries and checks the four distinct NOAA candidate APIs. Source SHA-256 hashes and URLs are
retained; raw payloads are discarded. Missing/duplicate/truncated map records,
invalid positions, API failures and missing station metadata remain explicit.
A changed candidate name, position or USGS identity produces `needs_review`,
not an automatic link. Auxiliary failures or changed identities cause refresh
exit code 1 after saving the review. Existing supported exact matches remain
subject to their original validation; auxiliary failures do not revoke them.
A future exact catalog/API match can recover normally despite this earlier
non-authorizing map review.

The publication notes retain fixed manual-review timestamps, original PDF
checksums and page references. Refresh does not refetch or claim to revalidate
those PDFs or the operator web pages; OneRain static-site metadata is refreshed. It replaces
only the latest metadata review and never stores historical water levels,
forecast series or subscription measurements. No additional radio-time requests
are introduced. Older installations receive these fields after the normal
`--noaa-identifiers` refresh; no spatial-index rebuild is required.

## Archived-source and OneRain access retry

The retry recovered all three previously inaccessible USGS PDFs. The alternate
[USGS publication metadata service for the 2003 inventory](https://pubs.usgs.gov/pubs-services/publication/wdrCA032)
links the official report index, while the [Circular 661 metadata record](https://pubs.usgs.gov/pubs-services/publication/cir661)
and [MF-613 metadata record](https://pubs.usgs.gov/pubs-services/publication/mf613)
link the original PDFs. Requests identifying the application succeeded. PDF bytes
were processed in memory; only bibliographic metadata, checksums and station
interpretations are retained. No archive of historical measurement values was created.

| Official source | Retrieved bytes | Reviewed locator | SHA-256 |
| --- | --- | --- | --- |
| [2003 California volume 2](https://pubs.usgs.gov/wdr/wdr-ca-03-2/WDR.CA.03.vol2.pdf#page=18) | 8,070,440 | PDF page 18, printed xvi; discontinued-gauge table, visually checked | `5aa7e0b01a15ddceb644db71729f19915396f7357e387f3fc640278fd6ec24fa` |
| [Circular 661](https://pubs.usgs.gov/circ/1971/0661/report.pdf#page=42) | 4,763,661 | PDF page 42, printed 38; record-period columns, visually checked | `0881d55be742e909af69cb650d3311dd9e2dd6f3ac78ce6248c7be906be4dcac` |
| [MF-613 explanatory pamphlet](https://pubs.usgs.gov/mf/0613/report.pdf#page=6) | 8,097,372 | PDF page 6; station identifiers and partial-record footnote, text checked | `7abc41b60ad6c686488002a15999ddf9dd247e261c4b5b0612f351537c0f1b2c` |

Manual review time: `2026-10-21T03:40:21+00:00`. The first table confirms the eleven
historical discontinued entries. Circular 661 distinguishes annual-peak and
low-flow records: Slide Creek has an annual-peak entry; Cummisky Creek has a
low-flow entry; Sausal, Warm Spring at Skaggs Springs and Mill Creek have both.
These are period descriptions, not level observations. MF-613 separately marks
Cummisky, Warm Spring and Mill Creek as partial-record stations. None supplies
an explicit successor relationship to a current NOAA gauge.

### Recovered OneRain map inventory

The [Sonoma Water-linked map](https://sonoma.onerain.com/map/?sensor_class=25&show_thresholds=true&view=1476abfc-52ba-4423-8f6b-f2712d9593ed)
and its [public sites GeoJSON](https://sonoma.onerain.com/export/map/geojson/?method=sites&view=1476abfc-52ba-4423-8f6b-f2712d9593ed)
were recovered with a temporary in-memory cookie jar. This endpoint is the map's
published `method=sites` request, identified in its JavaScript. The response
contained 118 site features; no exact alias for any of the sixteen unresolved
USGS IDs was present. This absence applies only to the retrieved public view.
Sensor-series, archive, graph and statistics endpoints were not requested.

| Site inventory entry | System / alias | Interpretation |
| --- | --- | --- |
| Franz Creek at Franz Valley School Rd | ALERT2 / 40210 | Corroborates the newer candidate location; no USGS-11463940 crosswalk |
| Dry Creek at Cooley Ranch RD | CDEC / DAC | Corroborates the operator record; no USGS-11464400 successor statement |
| WARM SPRINGS (USACE) | CDEC / WRS | Reservoir metadata remains distinct from the legacy creek gauges |
| Mill Creek at Reeves Canyon Rd | CDEC / MCR | Different site from Mill Creek near Healdsburg; no reassignment |
| BIG SULPHUR C NR CLOVERDALE CA | USGS / 11463200 | Existing other USGS identity, not Middletown 11463160 |

No additional NOAA-to-USGS link was supported. All sixteen unresolved identities,
existing accepted links, thresholds and routing remain unchanged.

### Refresh behavior and retention

The bounded metadata downloader now supports ordinary redirect cookies through
an ephemeral cookie jar. Cookies are not saved or reused between downloads, and
TLS verification remains enabled. Refresh requests the OneRain sites inventory
and retains only site identifiers, aliases, names, source systems and positions.
HTML, telemetry status, timestamps from the telemetry payload and any unexpected
measurement fields are discarded. The current source URL/hash and review time
remain available in `map_sources` and `map_record_review.onerain_review`.

A new exact USGS alias, duplicate/missing reviewed operator alias, changed name
or position, malformed inventory or source failure is explicitly flagged for
review. Even an exact OneRain alias cannot authorize a NOAA link without the
existing NOAA corroboration rules. These checks add no radio-time requests and
cannot revoke or substitute already supported current-source readings.
Historical-PDF review times stay fixed across refreshes so an old manual review
is never presented as a fresh PDF verification. The obsolete HTTP-403 label has
been replaced in both bundled and refreshed station records.

## Additional local operating-agency records

Manual review date: 2026-10-21 UTC. All sixteen unresolved identities were
compared against additional local records, regional operator inventories and
relevant USGS/NOAA identity metadata. **No additional NOAA link is supported.**
The review remains sixteen exact matches, one supported agency successor and
sixteen unresolved identities among the original 33 targets. The pilot's existing
inventory link remains separate from those 33 targets.

The strongest additional lead is Dry Creek near Yorkville: RRFC's Table 2-3
explicitly assigns legacy ID 11464400 to a CW3E reactivation recommendation.
However, it does not pair that ID with CW3E/CDEC DAC or NOAA DCOC1. Shared
operator, nearby coordinates and a reactivation proposal do not establish a
verified replacement chain. Feliz and Pena recommendations similarly do not
establish a NOAA identity or prove that proposed equipment is operating.

Two differences in historical coverage remain explicit. The city-hosted FEMA
study gives 1964-1976 for Redwood Valley, while the USGS discontinued-record
inventory gives 1963-1968. The RCD gives 1956-1976 for Franz Creek, compared with
1964-1968 in the USGS discontinued-record inventory. These publications may
refer to different record types; the periods are not normalized into one claim
or used as proof of closure. Existing series-catalog metadata remains intact.

A separate identifier/name conflict was visually verified in Sonoma Water's
Biological Assessment Table 4-10: 11462080 is labeled Dry Creek near Lambert
Bridge, whereas USGS identifies it as Russian River near Talmage. The original
publication is not edited, and this entry is excluded from crosswalk evidence.
Mainstem Dry Creek stations cannot substitute for tributary gauges.

### Per-station findings

Every row below remains unresolved for NOAA matching. Source numbers refer to
the records immediately below the table. A missing crosswalk in a regional
inventory is a coverage gap, not proof that no match exists elsewhere.

| USGS ID | Additional evidence and remaining gap | Records |
|---|---|---|
| 11460940 | Redwood Valley record periods differ; CW3E RVY/RVP are meteorological sites. | 3, 4, 2, 1 |
| 11461400 | No East Fork tributary crosswalk found; Cold Creek and mainstem sites are distinct. | 1, 2, 4 |
| 11462125 | No Slide Creek pairing found in the additional inventories or GSA annual report. | 1, 4, 2 |
| 11462700 | Former ID appears in reactivation recommendations; CLSI Feliz sites have no NOAA crosswalk. | 1, 3 |
| 11462900 | No Cummisky Creek pairing found in the reviewed regional records. | 1, 2, 4 |
| 11463160 | County guidance identifies BSCC1, whose explicit NOAA USGS ID is 11463200, not Middletown 11463160. | 9, 10, 1 |
| 11463700 | No Sausal Creek pairing found in the reviewed regional operator inventories. | 1, 2 |
| 11463940 | RCD cites the legacy Franz ID and nearby research sites, but no FVSC1 replacement chain; record periods differ. | 8, 1 |
| 11464050 | Yorkville reactivation concerns mainstem 11464400, not this Dry Creek tributary. | 1, 2 |
| 11464400 | Explicit CW3E reactivation lead; the legacy-ID to DAC/DCOC1 connection remains unverified. | 1, 2 |
| 11464500 | DAC/downstream gauges do not establish a Cloverdale successor; the Lambert Bridge table contains an ID conflict. | 2, 5, 6 |
| 11464860 | Recovered WAC/WAS metadata has no Asti predecessor link. | [WAC follow-up](#wac-detail-page-recovery) |
| 11464880 | Recovered WAC/WAS metadata has no Skaggs Springs predecessor link. | [WAC follow-up](#wac-detail-page-recovery) |
| 11465050 | Dutcher is listed as a tributary, not as one of the downstream mainstem gauges. | 5, 6, 1 |
| 11465150 | TU Pn01/Pn03 and proposed Pena sites have no explicit legacy-USGS/NOAA pairing. | 1, 5 |
| 11465300 | RCD documents CEMAR/TU local sites; CW3E MLL is on a different Mill Creek in Redwood Valley. | 7, 1, 2 |

### Additional source citations and access limits

PDFs were read in memory; no complete historical report or measurement series
was saved. PDF checksums and page references are retained with static evidence.
The initial CW3E WAC detail-page timeout was resolved by the
[WAC follow-up](#wac-detail-page-recovery). Recovered detail and equipment
metadata now supplement both Warm Springs rows. The GSA annual report supplied no exact occurrence of these sixteen
legacy IDs in its extracted text; it is not a comprehensive station registry.

1. [RRFC-hosted Telemetry Report Part Two (draft, January 2025)](https://www.rrfc.net/files/32a1f7e23/Telemetered%2BWater%2BMonitoring%2BProject%2BReport%2BPt%2B2%2BApril%2B2025.pdf). Tables 2-2 through 2-4, printed pages 13-19 (PDF pages 26-32).
2. [CW3E public operator site inventory](https://cw3e.ucsd.edu/metadata/sites/). Russian watershed site inventory: DAC, WAC, MLL, RVY, RVP and CLD.
3. [City of Ukiah-hosted Mendocino County Flood Insurance Study](https://cityofukiah.com/wp-content/uploads/2025/09/FIS-1.1.pdf). Table 11, printed page 52 (PDF page 57), revised September 19, 2025.
4. [Ukiah Valley GSA Water Year 2024 annual report](https://ukiahvalleygroundwater.org/wp-content/uploads/2026/02/1-052_WY2024.pdf). WY2024 annual report; full extracted-text identity search.
5. [Sonoma Water Biological Assessment (August 2023)](https://www.sonomawater.org/media/PDF/Environment/BiologicalOpinion/RRBA_Final_20230823_rev1_ADA%20V2%20kt%20OCR%20and%20Scanned.pdf). Tables 4-9 and 4-10, printed pages 4-70/4-71 (PDF pages 181/182); Table 4-10 visually checked.
6. [USGS Talmage station identity](https://waterdata.usgs.gov/monitoring-location/USGS-11462080/). Location name and agency identifier.
7. [Sonoma RCD Mill Creek Flow Availability Analysis](https://sonomarcd.org/wp-content/uploads/2021/07/MillCreekFlowAvailabilityAnalysis.pdf). Streamflow calibration discussion and Figure 35 (PDF pages 75-76).
8. [Sonoma RCD Maacama and Upper Mark West management plan](https://sonomarcd.org/wp-content/uploads/2017/06/Maacama-UpperMarkWest-IntegratedWshdMgmtPlan-FULL-3-25-15-1.pdf). Stream Flow Monitoring, printed page 58 (PDF page 60).
9. [Sonoma County Kincade Fire Rain Ready guidance](https://socoemergency.org/recover/2019-kincade-fire/rain-ready/). Stay Informed: Big Sulphur forecast-point link BSCC1.
10. [NOAA BSCC1 station metadata](https://api.water.noaa.gov/nwps/v1/gauges/BSCC1). Static identity: lid BSCC1, usgsId 11463200, Big Sulphur Creek near Cloverdale.

### Refresh and retention behavior

`scripts/water_operator_records.py` supplies fixed manual evidence under
`map_record_review.operator_record_review` for all sixteen rows. Each result
contains its finding, reason, source URLs, locators, available checksums,
`reviewed_at`, `link_authorized: false` and an explicit coverage limitation.
The timestamp is the manual review date, never the next refresh date. These
additional PDFs are not fetched on ordinary refresh and add no runtime dependency.

The existing `--noaa-identifiers` refresh continues to check current NOAA,
USGS, CDEC, HADS and OneRain evidence. Static local-record findings cannot
create links, suppress a later exact supported match, change routing, provide
thresholds or alter readings. Unresolved findings are not network failures.
Radio replies and categorical subscription baselines remain unchanged; no
historical numeric levels are retained. Original datasets remain untouched.

## WAC detail-page recovery

Manual follow-up: 2026-10-21 04:04 UTC. The canonical CW3E detail page was
retrieved successfully with certificate verification enabled through the Windows
TLS client. The trailing-slash variant returned HTTP 404, while the web reader
continued to time out. These are access-path differences, not evidence that the
station is absent. No TLS-validation bypass was used or added to the programs.

The [WAC station record](https://cw3e.ucsd.edu/metadata/sites/WAC) explicitly
identifies **CDEC WAS**, with an unpublished NWS field (`--`), installation on
July 15, 2026, and coordinates 38.702500/-123.090900. Its description places the
station below Strawberry Creek and upstream of Lake Sonoma. Alternate official
CW3E records corroborate the installation:

- [Pressure-transducer record](https://cw3e.ucsd.edu/metadata/sites/WAC/sensors/899):
  Ott Hydro PLS500, installed July 15, 2026.
- [Data-logger record](https://cw3e.ucsd.edu/metadata/sites/WAC/otherequipment/568):
  Sutron SatLink3 Lite, installed July 15, 2026. Its offset note does not specify
  units or datum and is not applied to any reading.
- [Russian watershed inventory](https://cw3e.ucsd.edu/metadata/fields/1/options/1):
  WAC appears with matching coordinates and installation date.

[CDEC WAS metadata](https://cdec.water.ca.gov/dynamicapp/staMeta?station_id=WAS)
names CW3E as operator at the same coordinates. Its reported elevation is 470 ft,
whereas CW3E reports 190 m. This discrepancy remains unresolved; neither figure
is treated as a verified gauge datum or used for conversion. No threshold is
inferred from the station elevation or equipment notes.

[NOAA WSSC1 metadata](https://api.water.noaa.gov/nwps/v1/gauges/WSSC1) has the same
name and coordinates but still publishes an empty USGS ID. None of the recovered
CW3E records identifies USGS 11464860 (near Asti) or 11464880 (near Skaggs Springs)
as a predecessor. Therefore **no additional NOAA link is authorized**, and all
sixteen reviewed identities remain unresolved. WAC-to-WAS is retained as explicit
operator metadata; WSSC1 remains a non-authorizing candidate.

The two Warm Springs evidence rows now carry the follow-up timestamp; the other
fourteen manual-review dates remain unchanged. Source URLs, locators and HTML
checksums are retained in the static review. Ordinary refresh copies this dated
evidence and continues existing live checks without downloading these HTML pages.
No new network dependency, observation history, calibration adjustment, threshold,
routing link or subscription behavior is introduced. Only selected static fields
are stored; raw source responses and reading series are discarded. The later
[vertical-reference review](#wacwas-elevation-and-logger-offset-review) retains
the reported offset as uninterpreted configuration evidence, not an executable
correction.

## WAC/WAS elevation and logger-offset review

Manual follow-up: 2026-10-21 04:13 UTC. Live official records do not support a
numerical correction to WAC/WAS elevations or readings. Both source elevations
are preserved with their original units and unknown vertical datums.

| Item | Verified source content | Interpretation |
|---|---|---|
| CW3E WAC station elevation | 190 m | Station metadata; no surveyed vertical reference identified |
| CDEC WAS station elevation | 470 ft | Corroborated by the active-station inventory; datum unspecified |
| CDEC WAS river-stage sensor | Sensor 1, feet | Units are established; NAVD88/NGVD29 is not established |
| CW3E logger note | `Offset 1.420000 applied 15 July 2026` | Units, sign convention, affected quantity and inclusion in published readings are unverified |

Using the unit definition 1 ft = 0.3048 m, 470 ft equals 143.256 m. The numerical
difference from 190 m is 46.744 m. This is an arithmetic comparison of reported
metadata, **not** a measured datum shift, gauge-zero correction or water-level
adjustment. Neither elevation establishes a flood threshold.

The [CW3E WAC detail](https://cw3e.ucsd.edu/metadata/sites/WAC) and live
[Satellite telemetry inventory](https://cw3e.ucsd.edu/metadata/fields/2/options/15)
both retain 190 m at 38.702500/-123.090900. Parallel Search surfaced an excerpt
with 159 m and slightly different coordinates, but direct retrieval of that
same official inventory did not corroborate it. The excerpt cannot authorize a
correction. This discrepancy is not evidence of a verified station relocation.

The [CW3E logger record](https://cw3e.ucsd.edu/metadata/sites/WAC/otherequipment/568)
reports an applied offset without explaining its units, sign or target. The
[pressure-transducer record](https://cw3e.ucsd.edu/metadata/sites/WAC/sensors/899)
has blank height/distance fields and no calibration-history entries. An empty
public record does not establish that calibration never occurred. The logger
note does not establish whether an adjustment is already included in CDEC
readings, so applying it again could introduce an unsupported second correction.

[CDEC WAS metadata](https://cdec.water.ca.gov/dynamicapp/staMeta?station_id=WAS)
and the [active-station inventory](https://cdec.water.ca.gov/reportapp/javareports?name=RealStations)
corroborate 470 ft. The [sensor definitions](https://cdec.water.ca.gov/misc/senslist.html)
distinguish generic river stage (sensor 1) from explicitly named NAVD88 (141)
and NGVD29 (144) products. Those datum labels cannot be assigned to WAS sensor 1
by inference. The [detailed river-stage station table](https://cdec.water.ca.gov/reportapp/javareports?name=RivStagesInfo)
has `DATUM 0` and `DATUM` columns but no exact WAS row in the retrieved report.
This is a coverage gap, not proof that no surveyed datum exists.

### Stored evidence and correction boundary

The two Warm Springs rows now contain `vertical_reference_review` under
`map_record_review.operator_record_review`. It separates reported station
elevations, arithmetic unit conversion, published sensor units and the raw logger
offset text. Unknown configuration and datum fields remain null;
`correction_authorized` is false and `applied_correction` is null. The offset and
its configuration date are static metadata relevant to interpreting values,
not a water-level observation or retained measurement history.

A correction requires station-specific operator evidence: a surveyed reference
point and vertical datum tying the elevation to gauge zero; offset units, sign,
affected quantity and effective configuration; whether the publisher already
applies the offset; and an explicit correction instruction for the source product.
No such complete instruction was located in the reviewed records. CDEC is the
preferred source for station-elevation metadata; this preference does not establish
a surveyed datum or correction authority. No reading, threshold, route or NOAA
match is changed. All sixteen identities remain unresolved.

Identifier refresh preserves this dated manual assessment and separately runs
the [automatic WAC/WAS metadata checks](#automatic-wacwas-metadata-checks).
Source URLs, locators and checksums remain available in the bundled and runtime
review. All manual-review dates remain fixed. No observation-series endpoint
was requested for this audit.

## Automatic WAC/WAS metadata checks

`python scripts/water_refresh.py --noaa-identifiers` also checks five official
metadata pages through `scripts/water_vertical_review.py`. The checks run even
when the NOAA catalog is unavailable. No additional command, dependency,
subscription or index rebuild is required. HTTPS certificate verification,
20-second request timeouts, an 8 MiB response limit and up to three concurrent
downloads use the existing agency metadata downloader.

| Official source | Checked fields and reviewed baseline |
| --- | --- |
| [CW3E WAC station](https://cw3e.ucsd.edu/metadata/sites/WAC) | WAC/CDEC WAS identifiers, unpublished NWS ID, coordinates, elevation 190 m and links to the reviewed logger/sensor |
| [CW3E logger 568](https://cw3e.ucsd.edu/metadata/sites/WAC/otherequipment/568) | Logger type/model, installation date, offset 1.420000 and application date July 15, 2026; additional or changed note wording requires review |
| [CW3E pressure sensor 899](https://cw3e.ucsd.edu/metadata/sites/WAC/sensors/899) | Sensor type/model, installation/deactivation fields, blank height/distance, absence of notes and calibration entries |
| [CDEC WAS station](https://cdec.water.ca.gov/dynamicapp/staMeta?station_id=WAS) | WAS identity, elevation 470 ft, generic river-stage sensor 1 and FEET units |
| [CDEC datum report](https://cdec.water.ca.gov/reportapp/javareports?name=RivStagesInfo) | Report schema/completeness and absence of an exact WAS entry; a new entry requires manual datum review |

The comparison baseline is the fixed manual review at
`2026-10-21T04:13:27+00:00`. Refresh does not automatically accept changed values
as a new baseline. It saves `wac_was_refresh_check` at the document root and a
`vertical_reference_check` in each of the two legacy Warm Springs candidate
rows. These records contain a separate `checked_at`, the baseline date, source
URLs and SHA-256 digests, allowlisted metadata, source statuses and changed field
names. The manual evidence remains under `map_record_review.operator_record_review`
when that map review is available; a catalog failure still retains the separate
live checks and their baseline timestamp.

`preferred_station_elevation` selects the current CDEC WAS elevation in feet
(470 ft in the reviewed baseline). The original CW3E value remains alongside it
and the discrepancy remains explicit. A changed CDEC value is labeled
`source_changed` and still requires review; selection does not silently accept a
new baseline. When the CDEC page is inaccessible, malformed or identifies another
station, the preferred value is null. It does not fall back to CW3E or a stale
successful retrieval. The datum remains unknown. CDEC stage units do not supply
the missing logger-offset units, and source priority never adjusts observations.

| Check status | Meaning and command behavior |
| --- | --- |
| `unchanged_uncertainty` | All five pages match the reviewed fields. The known elevation conflict and unknown offset interpretation persist. This result alone does not cause exit code 1. |
| `needs_review` | At least one source is `source_changed`, `invalid_metadata` or `source_unavailable`. The command prints affected sources/fields and returns 1 after saving the latest review. |

Whitespace, HTML entities, numeric precision and the supported UTF-8/Windows-1252
encodings are normalized. Whole-page checksums record provenance only: changing
session tokens or unrelated page content does not trigger a mismatch. Missing
or duplicate required fields, unknown units, incomplete pages and changed report
schemas cannot count as unchanged evidence. Header-only or unusually short datum
reports cannot establish absence. Equipment replacement links are flagged even
if the old detail page remains accessible.

Unknown offset notes are represented by a fingerprint and an unrecognized-note
flag; unrestricted notes and calibration rows are not persisted. The datum
report's historical peaks are discarded. A newly published datum row, logger
note or calibration entry is a review lead, not an automatic correction. These
checks cover the five cited pages; ancillary inventories and earlier PDF evidence
remain manual context, and unrelated page changes are outside the comparison.

On a flagged refresh, inspect the cited page and changed fields against the
dated manual evidence. A source-access failure should be retried without
changing the baseline. A substantive change requires a documented manual review
of the baseline, uncertainty and regression fixtures before acceptance. Do not
change the baseline solely to silence a failing check.

Each refresh replaces the current review atomically, including failures; there
is no fallback to previous successful source checks and no appended history.
`link_authorized` and `correction_authorized` remain false, `applied_correction`
remains null, and unverified datum/offset configuration stays null. Neither
identities nor measurements consume these checks as authorization. Current-only
readings, thresholds, routing and categorical subscription baselines are unchanged.

## Runtime integration and refresh

The bundled JSON is a small static review overlay. The original USGS station
identifier CSV, manifests, routing tables and readings remain unchanged. At
lookup time the overlay supplements only reviewed IDs; an original inventory
LID that conflicts with the reviewed LID causes the link to be withheld. Stations
outside this review retain their original identity handling. The overlay does
not change upstream eligibility or create a route.

From each installed platform package:

```console
python scripts/water_refresh.py --noaa-identifiers
```

The command replaces `runtime/water_station_review.json` atomically with all 33
results. It downloads the national static report once and checks each unique
exact match through the gauge API using three workers. It also rechecks the
17-station agency metadata review and the supported successor chain. The runtime review takes
precedence over the bundled review, including failed and unresolved checks.
No index rebuild is required for this overlay. `--index --noaa-identifiers` can
perform both operations after a wider dataset refresh.

Schema errors, unusually short national reports, duplicate IDs, shared LIDs,
API conflicts and source failures are explicit. Catalog failure withholds all
33 supplemental links; individual API failures withhold only affected links.
Failures/conflicts produce exit code 1 after saving the withheld outcomes. A
successful search with no exact match is a valid unresolved result, not a source
failure. A later successful explicit refresh can restore corroborated links.
An invalid runtime JSON does not silently fall back to the bundled snapshot.

The ordinary five-minute current-source cache checks exact NOAA/USGS identities,
or the narrowly verified CDM agency-successor chain described above. Freshness, service status, valid values and the threshold
for the reported category must be supported before that category is usable.
`no_flooding` requires a published minor-flood threshold. A missing moderate or
major threshold does not disable a supported action/minor category. The response
category is used directly; no local stage comparison or datum conversion occurs.

Structured conditions preserve `noaa_identity_status` and `threshold_status`
separately from current category and USGS reading usability. Thus a station may
have a corroborated identity but no thresholds, or published thresholds but a
stale/invalid/unavailable observation. Radio summaries remain bounded. Review
timestamps and static provenance remain available in the local structured result
and relationship table; numeric measurements never enter subscription baselines.

Review downloads discard observations, forecasts, historical crests and time
series before writing. Only static identity, threshold and interpretation evidence is retained; logger
configuration notes remain separate from observations and executable corrections.
The runtime review replaces its predecessor; current NOAA cache rows replace
prior values. No new reading history or observation acquisition schedule is added.

## Validation

Offline tests cover exact and conflicting identifiers, duplicate catalog rows,
same-name nonmatches, missing thresholds, source failures, replacement without
fallback, overlay conflicts, category threshold requirements and current-only
persistence. Live validation reuses the real statewide routing collection at the
pilot point. Native Linux and radio delivery require separate validation.

See the [water command guide](WATER_GUIDE.md) for configuration, retention and
subscription behavior.

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

The additional map-review regressions cover all sixteen unresolved rows,
identical-position nonmatches, changed candidate IDs/names/positions, malformed
or truncated maps, duplicate/missing USGS metadata, source failures and refresh
exit codes. Both live identifier refreshes completed successfully. Both pilot
lookups retained the same 34 upstream gauges for one-detail and three-detail
settings, with seven published thresholds, eleven linked gauges without
thresholds and sixteen unresolved identities. Auxiliary map evidence remained
absent from categorical subscription baselines. No additional accepted link,
new reading history or radio subscription was introduced.

Source-access retry regressions passed in both 371-test platform suites on a
Windows host. Coverage includes cookie-requiring redirects without cross-request
cookie persistence, OneRain field allowlisting, malformed/duplicate inventories,
changed aliases, non-authorizing exact alias leads and fixed historical-review
dates. Both live identifier refreshes succeeded with sixteen exact matches, one
agency successor and sixteen unresolved identities. Native Linux execution and
radio delivery were not exercised.


Additional local-record validation passed all 376 tests in each platform package
on a Windows host. Both live identifier refreshes succeeded with sixteen exact
matches, one agency successor and sixteen unresolved identities; all sixteen
manual operator reviews were retained. The new tests cover fixed manual dates,
explicit coverage differences and access limits, independent evidence objects,
non-authorizing refresh output, later exact-match recovery and exclusion of
fixture measurements. Package inventory, paired-file and documentation-link
checks passed. Native Linux execution and radio delivery were not exercised.


WAC recovery validation passed all 378 tests in each platform package on a
Windows host. Both live identifier refreshes succeeded with sixteen exact
matches, one agency successor and sixteen unresolved identities. Regression
coverage verifies that recovered operator aliases cannot authorize legacy links
or alter readings, station elevations and offset uncertainty remain explicit,
only static metadata is retained, and only the two Warm Springs manual-review
dates change. Paired artifacts, package inventory and local links were checked.
Native Linux execution and radio delivery were not exercised.


Vertical-reference audit validation passed all 380 tests in each platform package
on a Windows host. Both live identifier refreshes succeeded with sixteen exact
matches, one agency successor and sixteen unresolved identities. Tests verify
arithmetic unit conversion without an inferred datum, unknown offset semantics,
independent evidence objects, unchanged readings despite injected correction
claims, and exclusion of observation history. All ten cited sources and explicit
uncertainty fields survive refresh for both Warm Springs rows. Package inclusion,
paired artifacts and local links were verified. Native Linux execution and radio
delivery were not exercised.

Automatic WAC/WAS refresh validation passed all **392 tests per platform
package**, including command-program checks, on a Windows host. Twelve added
regression tests cover semantic source changes, supported encoding/formatting
normalization, malformed/duplicate/incomplete fields, access-failure replacement,
new calibration/datum evidence, catalog-failure integration, CLI exit behavior,
CDEC priority without fallback, fixed manual dates and non-authorizing output.
Both live refreshes retrieved all five metadata pages and reported
`unchanged_uncertainty`; the preferred CDEC value was 470 ft. The final identity
counts remained sixteen exact matches, one supported successor and sixteen
unresolved stations. An initial unrelated CDM connection reset was saved as a
failure; subsequent live refreshes restored its independently corroborated link.
Original datasets were unchanged. Native Linux execution and radio delivery
were not exercised.
