# Source-access retries and alternate official records

Dataset and generated-report paths below identify local acquisition outputs.
They require the corresponding collection, generation, or validation run
described in [water-data setup](../../docs/WATER_DATA_SETUP.md). Packaged
documentation contains the guides; historical generation paths may differ
from later acquisitions.

## Five-source retry and additional records

All five sources that failed in generation `20261020T065925Z_d164e82b` were
retried: the IID Brock and All-American Canal pages, Reclamation Havasu RISE
metadata, the Tulare LAFCO directory, and the Lake County hitch survey.
The initial retry recovered Havasu metadata. Both IID pages and the Tulare
directory returned HTTP 403; the Lake County request timed out.
The completed refresh recovered both Havasu and the original Lake County survey.
Results are recorded in the active source catalog (`LOCAL_REVIEW.md`):

| Retried source | Final result |
| --- | --- |
| Havasu RISE location 3515 | Verified metadata; recovered from timeout |
| Lake County 2024 hitch survey | Verified metadata; recovered after further timeout |
| IID Brock Reservoir page | HTTP 403; official contextual alternatives verified |
| IID All-American Canal page | HTTP 403; official contextual alternatives verified |
| Tulare LAFCO directory | HTTP 403; official administrative alternatives verified |

Four additional **source-to-source contextual relationships** are maintained:

| Original source | Additional official record | Supported context and limit |
| --- | --- | --- |
| IID Brock Reservoir | Reclamation's December 2020 conservation summary report | Completed-facility description: outlet pipelines return below Drop 2. No exact key for USGS 09527630, 09527660 or 09527700. |
| IID All-American Canal | Reclamation's Yuma Division record | Rockwood Heading is described as a return for Pilot Knob powerplant and wasteway. No exact key for inlet station 09526900. |
| Tulare LAFCO directory | DWR SGMA GSP submission 42 | A Deer Creek Storm Water District reference is attributed to LAFCO. This does not establish ownership or placement of USGS 355422119223201. |
| Havasu RISE | Existing Reclamation Parker Dam facility record | NID AZ10312 supplies facility context when RISE access is intermittent. It does not validate the displaced legacy USGS river address. |

There are eight maintained alternate-source relationships in total. Each
retains its original source status, alternate status, scope and limitations.
They do not assert document equivalence or station equivalence. No new
station metadata or routing relationship is supported by this investigation:
the existing 14 metadata links for 10 stations are preserved, and all 24
hydrography addresses remain unresolved.

### New records and failed alternatives

**Bureau of Reclamation.** [Warren H. Brock Reservoir Conservation Summary
Report](https://www.usbr.gov/lc/region/programs/strategies/agreements/BrockReport.pdf),
December 2020, printed page 5 / PDF page 11. Unlike the earlier 2007 proposed
action, this report describes completed facilities and operating status.
Only the outlet-route sentence and administrative operating-status sentence
are retained. No reservoir volumes, historical flows, costs or complete
report pages are saved. None of the three Brock-area USGS IDs occurs in the
extracted report text; this is an evidence gap, not proof that no agency
crosswalk exists elsewhere.

**Bureau of Reclamation.** [Colorado River Front Work and Levee System,
Yuma Division](https://www.usbr.gov/projects/index.php?id=439).
The existing source selection now also retains the Pilot Knob return-role
sentence. Its engineering narrative does not identify the inlet gauge.
The original [All-American Canal project description](https://www.usbr.gov/projects/index.php?id=514)
remains the other maintained Pilot Knob alternative.

**California DWR.** [SGMA GSP submission 42, references](https://sgma.water.ca.gov/portal/gsp/preview/42).
The retained reference associates Deer Creek Storm Water District with LAFCO
and a reference date of 2019-01-01. That date is not a gauge commissioning date
or verification of present district boundaries. The linked
[legacy LAFCO storm-water district map directory](https://lafco.co.tulare.ca.us/lafco/index.cfm/maps/districts/districts-storm-water/)
redirected to the current county host and returned HTTP 403. No map, station
ownership or hydrography address was inferred from the reference.

**Lake County Watershed Protection District.** The original
[2024 hitch survey](https://cleanwater.lakecountyca.gov/DocumentCenter/View/15453/2024-District-Clear-Lake-Hitch-Visual-Spawner-Surveys?bidId=)
timed out on retry. The county's
[main-host copy with the query parameter](https://www.lakecountyca.gov/DocumentCenter/View/15453/2024-District-Clear-Lake-Hitch-Visual-Spawner-Surveys?bidId=),
[main-host copy without the query parameter](https://www.lakecountyca.gov/DocumentCenter/View/15453/2024-District-Clear-Lake-Hitch-Visual-Spawner-Surveys),
and [alternate document 15294](https://www.lakecountyca.gov/DocumentCenter/View/15294/2024-District-CLH-Visual-Surveys?bidId=)
also timed out. Indexed text was not substituted for downloaded evidence.
The subsequent full refresh successfully retrieved and verified the original
survey URL; the failed alternate attempts remain documented separately.
The ecological survey site SCH_01 remains distinct from USGS 11449950.
The alternate URLs above are research leads, not successful maintained sources.

The maintained source rules now cover 34 URLs. New contextual references are
refetched and audited during normal local-review refreshes; prior generations
remain intact. Source-to-source rows always retain
`station_match_supported=False` and `routing_supported=False`.

### Validation of the completed retry

Generation `20261020T070741Z_494cfc66` verifies 31 of 34 configured sources,
including both new sources and all eight alternate-source associations.
The audit records three retrieval failures, zero encoding flags, zero
selection mismatches and zero current identical-body discrepancies.
All 88 USGS collection tests passed. Offline validation replayed source
associations, station decisions, regional exports and the saved audit.

All 14 prior station relationships are preserved with fresh retrieval
timestamps. No station relationship or routing edge was added. Observation
generation `20261020T043137Z_10d7f799` still contains the same 1,307 latest
readings; routing generation `20261020T053050Z_23024208` is unchanged.
No historical level or discharge data was saved. The
validation report (`local_review_verification.json`) records these checks and
their limits.

## Earlier investigation of three persistent failures

The three inaccessible source pages concern five unresolved stations: Pilot
Knob inlet (09526900), Brock inlet (09527630), Brock outlet (09527660),
All-American Canal below the Brock outlet (09527700), and Deer Creek at
Road 88 (355422119223201).

Four alternate official sources provide facility or administrative context.
**No additional station identity, hydrography address or downstream routing
relationship is supported by these four alternatives.** The metadata
relationships for other stations remain separate; the
[additional maps and records review](ADDITIONAL_AGENCY_REVIEW.md) records later
supported roles and identifiers. All 24 hydrography addresses in the local review
remain unresolved.

The active catalog (`LOCAL_REVIEW.md`) links the immutable source receipts and
`relationships/source_alternatives.csv`. That table associates each original
source with its reviewed alternate, exact URLs, retrieval status, interpretation
scope and limitations. It is a source relationship table, not a waterway topology
table. Each row has `station_match_supported=False` and
`routing_supported=False`. Original access failures are retained even when an
alternate is available.

## Brock Reservoir

The inaccessible IID facility page is supplemented by Reclamation's
[June 2007 Drop 2 Storage Reservoir Project Final Environmental Assessment](https://www.usbr.gov/lc/region/programs/drop2/envdocs/finalea/fea1.pdf),
PDF page 14, printed ES-3. The proposed action describes an outlet returning
stored water to the All-American Canal downstream of Drop 2.

This is **planning evidence**, not a surveyed current station address or proof
that a specific NHDPlus segment represents the completed works. The reviewed
document supplies no complete cross-reference for the three Brock-area USGS
station IDs. Inlet, outlet and downstream canal gauges therefore remain distinct.
The earlier Reclamation construction description remains in the source catalog.

The [IID operating agreement and attached operations plan](https://www.iid.com/home/showpublisheddocument/18149/637120057223030000)
was also located, but direct retrieval returned HTTP 403. Search-index text was
not substituted for a verified acquisition or used to authorize a relationship.

## Pilot Knob

Reclamation's [Boulder Canyon Project: All-American Canal System](https://www.usbr.gov/projects/index.php?id=514)
describes separate Pilot Knob powerplant and wasteway facilities and explains
the powerplant's return to the Colorado River. This provides an accessible
alternative to the unavailable IID All-American Canal page.

The project description does not identify USGS 09526900. A shared facility name
does not establish the exact inlet measurement point or its hydrography address.
The inlet gauge is not merged with the powerplant or wasteway; the narrative
return path is not inserted into the directed reach graph.

## Deer Creek at Road 88

The [California State Controller's 2024 Tulare County special-district directory](https://gcc.sco.ca.gov/Reports/SpecialDistricts/SpecialDistrictCounty.aspx?county=Tulare&year=2024)
confirms Deer Creek Storm Water District and its flood-control classification.
Only district identity and activity metadata are retained, not compensation
records. This replaces the missing administrative context of the inaccessible
Tulare County LAFCO directory.

The [Pixley Irrigation District 2012 Water Management Plan, hosted by Reclamation](https://www.usbr.gov/mp/watershare/docs/2012/pixle-wmp2012.pdf),
PDF page 22, identifies a Road 88 Dam outflow point and district outflow toward
Alpaugh or Atwell Island irrigation districts. The retained excerpts contain
only facility and destination labels; historical flow quantities are excluded.

Neither source identifies USGS 355422119223201. The older district facility
description does not prove equivalence to the later USGS gauge, establish gauge
ownership, or support downstream station links. The two districts, the
storm-water authority, the dam and the gauge are not conflated.

Tri-County Water Authority's [agency description](https://tcwater.org/about-us/)
also lists Deer Creek district representation in indexed material, but direct
retrieval returned HTTP 403. A
[county special-district application PDF](https://tularecounty.ca.gov/sites/clerkoftheboard/assets/Fillable-Special-District-Application.pdf)
returned HTTP 404. Neither failed retrieval authorizes an accepted link.

## Refresh, retention and verification

The original four alternate sources and their source-to-source associations are maintained
in `local_review_rules.json`. The existing `--mode local-review` command fetches
them alongside the original sources, verifies reviewed literal selections, and
rebuilds station decisions, regional exports, the alternate-source table and the
catalog. Source failures or changed wording set `context_available=False`;
original errors remain visible. Context availability does not bypass exact
station-key checks.

Station reports expose these rows as `alternate_source_context`, separate from
`metadata_links`. Upstream version mismatches suppress both. Earlier immutable
metadata generations are preserved. Full reports are processed in memory;
historical level/discharge measurements are not saved. Current observations,
tributary tables, routing and CalWater categories are unchanged.

The validation report (`local_review_verification.json`) records replay of the
station and source relationship tables, source availability, manifest hashes,
regional exports and current-only retention. See
[refresh commands and evidence limits](LOCAL_REVIEW_METHODS.md).

The alternate-source refresh retrieved all four alternatives. Its Modesto
selection mismatch was subsequently traced to local text corruption, as
documented below. Current retrieval counts are recorded in the validation
report. All ten previously accepted metadata links remain unchanged apart from
retrieval timestamps.

## Modesto La Grange selection mismatch

The [Modesto Irrigation District La Grange page](https://www.mid.org/water/water-resources/la-grange-diversion-dam/)
was rechecked on 2026-10-20 UTC. The response was 114,552 bytes with SHA-256
`dd106ca901bcc42d1321ac9dc04390aeb9671562eb956cd437fc77fab3680efa`.
This is identical to both the
earlier successful receipt (`local_review/20261020T062115Z_4fee573d/evidence/modesto_dam.json`)
and the
later failed-selection receipt (`local_review/20261020T062754Z_f6acc328/evidence/modesto_dam.json`).
**No agency wording change was observed.** The previous interpretation of the
mismatch as changed source wording was incorrect.

The literal in the later local rules file contained `District\u00e2\u20ac\u2122s`
instead of `District\u2019s` (Unicode escapes shown for unambiguous comparison).
Reading UTF-8 JSON using the Windows default code page during a local edit
caused this corruption. The verified literal was restored using the archive's
explicit UTF-8 JSON reader and writer. Comparison of the shared source rules
found this to be the only changed source definition; the four newly added
alternate sources remain intact. Both earlier immutable generations are preserved.

The live page describes MID and TID canal heads and the Tuolumne River path,
but contains none of the identifiers `11289000`, `2826002` or `2826006`.
It therefore supplies facility context only: USGS 11289000 remains unresolved
between the competing hydrography candidates. No station identity or routing
link is added. Canal names, tunnel descriptions and proximity are not
substitutes for a published station-to-reach cross-reference.

Regression checks exercise the maintained UTF-8 rule against UTF-8 HTML and
confirm that corrupted literals remain a failed selection rather than being
silently normalized. A fresh local-review generation republishes verified
evidence and regional decisions without requesting observation data.

A subsequent [audit of all source rules](SOURCE_RULE_AUDIT.md) checks for
additional encoding errors and identical-response selection discrepancies.
