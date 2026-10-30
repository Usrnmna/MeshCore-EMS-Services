# Additional official maps and records for 24 unresolved stations

Dataset and generated-report paths below identify local acquisition outputs.
They require the corresponding collection, generation, or validation run
described in [water-data setup](../../docs/WATER_DATA_SETUP.md). Packaged
documentation contains the guides; historical generation paths may differ
from later acquisitions.

Review date: 2026-10-20 UTC. All 24 stations were checked against USGS inventory
pages and additional official records or map leads. Four new metadata
relationships are supported across three stations. The active local review
contains **14 relationships for 10 stations**, with **24 unresolved network
addresses**. Statewide routing remains **641 of 686** latest-reading stations.
Metadata links do not expand downstream or potentially affected basin tables.

## Supported additions

| USGS station | Relationship | Evidence and limit |
| --- | --- | --- |
| 11267350 Big Creek diversion | Diversion from Big Creek, a South Fork Merced tributary | USGS water-year 1998 station record, PDF page 333. Historical documented role; no current gate-operation assertion. |
| 11267350 Big Creek diversion | Diversion to Lewis Fork of the Fresno River | Same exact-ID station record. Descriptive receiving-waterway key, not a COMID or CalWater crosswalk. |
| 11289000 Modesto Canal | Gaged diversion to Modesto Canal | USGS OFR 85-401, schematic line 1 and its station key, PDF pages 48 and 50. The 1961-77 study does not choose between current competing segment addresses. |
| 11455276 Shag Slough | Report identifier SGG | USGS OFR 2023-1087 Table 1. Namespace `USGS_OFR_2023_1087`; no automatic equivalence with CDEC SGG. |

The Tuolumne schematic was visually inspected. Its numbered diversion arrow
agrees with the exact station key in the explanatory table. The Big Creek
record names both ends of the diversion but provides no representative current
hydrography identifier. These are dated descriptive roles, not new tributary
or flood-routing edges.

## Case-by-case findings

Each station number below links to its official inventory record. Inventory
pages were retrieved in memory; no historical observation query was made.
The records did not provide a new manuscript crosswalk through their links.
Absence from these checked records is an evidence gap, not proof that no
agency record or physical connection exists.

| Station | Additional record or map check | Decision |
| --- | --- | --- |
| [09427500 Lake Havasu](https://waterdata.usgs.gov/nwis/inventory/?site_no=09427500&agency_cd=USGS) | USGS WSP 2407 identifies the Lake Havasu station separately from Colorado River below Parker Dam. | Reservoir identity does not validate the displaced legacy river address or a dam-release route. |
| [09525000 Yuma Main Canal wasteway](https://waterdata.usgs.gov/nwis/inventory/?site_no=09525000&agency_cd=USGS) | WSP 2407 station inventory separately lists the Yuma wasteway and other lower Colorado wasteways. | No representative COMID; no Eleven Mile Wasteway merge. |
| [09526900 Pilot Knob inlet](https://waterdata.usgs.gov/nwis/inventory/?site_no=09526900&agency_cd=USGS) | WSP 2407 lists 09527000 for Pilot Knob powerplant and wasteway, a different station. | No transfer of that identity to inlet 09526900. |
| [09527630 Brock inlet](https://waterdata.usgs.gov/nwis/inventory/?site_no=09527630&agency_cd=USGS) | Reclamation planning map/context; additional IID operating-agreement PDF denied access. | Inlet remains separate from outlet and downstream canal gauge. |
| [09527660 Brock outlet](https://waterdata.usgs.gov/nwis/inventory/?site_no=09527660&agency_cd=USGS) | Same Brock planning and operating-record checks. | No current exact station-to-segment crosswalk. |
| [09527700 All-American Canal below outlet](https://waterdata.usgs.gov/nwis/inventory/?site_no=09527700&agency_cd=USGS) | Same Brock checks; proposed return below Drop 2 is insufficient to place this gauge. | No inferred station sequence or graph edge. |
| [11062399 Fontana Weir 2](https://waterdata.usgs.gov/nwis/inventory/?site_no=11062399&agency_cd=USGS) | Official inventory, refreshed Watermaster table and additional district agreement lead. | Existing facility link retained; agreement URL returned HTML rather than the indexed PDF. No new address. |
| [11062400 Fontana Weir 3](https://waterdata.usgs.gov/nwis/inventory/?site_no=11062400&agency_cd=USGS) | Same Fontana checks. | Existing identity retained; conflicting address unresolved. |
| [11062450 Fontana forebay return](https://waterdata.usgs.gov/nwis/inventory/?site_no=11062450&agency_cd=USGS) | Same Fontana checks. | Existing identity/return role retained; no current segment selected. |
| [11062700 Lytle diversion to powerhouse](https://waterdata.usgs.gov/nwis/inventory/?site_no=11062700&agency_cd=USGS) | Same Fontana checks; district agreement search lead names the diversion but retrieved page is not the document. | Existing Watermaster role retained; no tailrace address inherited. |
| [11062800 Fontana afterbay return](https://waterdata.usgs.gov/nwis/inventory/?site_no=11062800&agency_cd=USGS) | Same Fontana checks. | Existing identity/return role retained; no representative reach. |
| [11062820 Fontana afterbay diversion](https://waterdata.usgs.gov/nwis/inventory/?site_no=11062820&agency_cd=USGS) | Official inventory and refreshed 2024 Watermaster explanation. | Existing identity/diversion role retained; no additional keyed address found. |
| [11267350 Big Creek diversion](https://waterdata.usgs.gov/nwis/inventory/?site_no=11267350&agency_cd=USGS) | Exact-ID USGS 1998 station record; newer indexed manuscript URL returned 404. | Two historical roles added. BGF and rejected NHDPlus connection remain unconfirmed. |
| [11289000 Modesto Canal](https://waterdata.usgs.gov/nwis/inventory/?site_no=11289000&agency_cd=USGS) | USGS Tuolumne schematic and keyed explanation. | Historical diversion role added; COMIDs 2826002/2826006 remain unresolved. |
| [11312672 Victoria Canal](https://waterdata.usgs.gov/nwis/inventory/?site_no=11312672&agency_cd=USGS) | Official inventory and refreshed DWR Attachment B/CDEC record. | Existing VCU alias retained; no new exact hydrography address. |
| [11313200 Grant Line Canal](https://waterdata.usgs.gov/nwis/inventory/?site_no=11313200&agency_cd=USGS) | Official inventory and refreshed DWR old/current GLC records. | Historical 11313200 association does not transfer the current 11313240 gauge address. |
| [11449950 Schindler Creek](https://waterdata.usgs.gov/nwis/inventory/?site_no=11449950&agency_cd=USGS) | Additional Lake County watershed-plan map leads returned 404. Existing ecological-site record remains available. | No verified new station key; SCH_01 remains a different type of site. |
| [11455276 Shag Slough](https://waterdata.usgs.gov/nwis/inventory/?site_no=11455276&agency_cd=USGS) | USGS OFR 2023-1087 Table 1; SIR 2025-5035 Table 4 corroborates the report code. | Report-scoped SGG link added; no CDEC or directional tidal routing promotion. |
| [355422119223201 Deer Creek Road 88](https://waterdata.usgs.gov/nwis/inventory/?site_no=355422119223201&agency_cd=USGS) | Tulare County Road 88 scour-repair records denied access; Pixley facilities map remains context. | No supported gauge-to-dam equivalence or ownership link. |
| [375450121331701 Woodward Canal](https://waterdata.usgs.gov/nwis/inventory/?site_no=375450121331701&agency_cd=USGS) | Current USGS location record and DWR survey-area context. | Canal identity alone does not establish an OWI alias or directed reach. |
| [380015121315101 Connection Slough Swing Bridge](https://waterdata.usgs.gov/nwis/inventory/?site_no=380015121315101&agency_cd=USGS) | USGS DS 756, PDF page 19, lists Connection Slough near Middle River as 380000121340801. | Different complete ID; no merge. CDEC CSG remains a candidate. |
| [381807121413801 Nemeth Slough](https://waterdata.usgs.gov/nwis/inventory/?site_no=381807121413801&agency_cd=USGS) | USGS location record and OFR 2023-1087 Liberty Island instrument-map caption. | No exact map crosswalk for this newer gauge; failed CDEC lookup is not disconnection evidence. |
| [381934121403201 Liberty Island upstream Wildlands](https://waterdata.usgs.gov/nwis/inventory/?site_no=381934121403201&agency_cd=USGS) | OFR 2023-1087 Figure 66 identifies LICB station 382006121401601. | Different station; no project-membership, gauge-equivalence or routing link inferred. |
| [381946121402301 Liberty Island Wildlands marsh](https://waterdata.usgs.gov/nwis/inventory/?site_no=381946121402301&agency_cd=USGS) | Same exact-ID instrument-map caption. | Remains distinct from LICB and the upstream Wildlands gauge. |

## Sources, access results and retention

The four sources used in new maintained rules have full citations in
[SOURCES.md](SOURCES.md#additional-official-maps-and-station-records).
The generated catalog (`LOCAL_REVIEW.md`) links selected metadata receipts,
retrieval dates, original response hashes, decisions and relationships.

Additional research sources and leads:

- [USGS WSP 2407, lower Colorado accounting system](https://pubs.usgs.gov/wsp/2407/report.pdf):
  PDF pages 27-28 distinguish station identities. Older OCR contains errors;
  no new relationship or full table was retained.
- [USGS SIR 2025-5035](https://pubs.usgs.gov/sir/2025/5035/sir20255035.pdf):
  Table 4, PDF page 19, independently associates SGG with 11455276. Its heading
  says station identifier, not CDEC identifier. The smaller HTML OFR evidence
  selection is maintained for refresh rather than duplicating this report.
- [IID Brock operating-agreement PDF lead](https://www.iid.com/home/showpublisheddocument/18149/637120057223030000):
  HTTP 403; search text is not accepted evidence.
- [San Bernardino Valley district agreement lead](https://www.sbvmwd.com/home/showpublisheddocument/9336/637656795625530000):
  HTTP 200 HTML instead of the indexed PDF; no source-body station key verified.
- [Lake County March 2025 watershed-plan lead](https://www.lakecountyca.gov/DocumentCenter/View/15402/Lake-County-319-Watershed-Plan-Final-Draft-Version-20-03-11-25)
  and [December 2024 alternative](https://lcsd.lakecountyca.gov/DocumentCenter/View/13886/Lake-County-319-Watershed-Plan-Final-Draft-Version-12-12-17-24):
  both HTTP 404 in this review. Indexed maps cannot establish a match.
- [Tulare County scour-repair records, Location 4 Road 88 Deer Creek](https://tularecounty.ca.gov/rma/rma-at-work/request-for-proposals-for-engineering-services/fema-group-2-scour-repair-project/supplemental-documents-per-location-fema-group-2-scour-repair-project):
  HTTP 403; a repair-site name cannot establish station identity.
- [Indexed USGS 2012 Big Creek manuscript](https://wdr.water.usgs.gov/wy2012/pdfs/11267350.2012.pdf):
  HTTP 404. The accessible 1998 report supplies the accepted dated evidence.

Research-only access results above describe this investigation; they are not
part of the scheduled source-receipt audit. Maintained sources are explicitly
listed in `local_review_rules.json`. No source access failure, similar name,
nearby position or historical schematic overrides an agency rejection.

`source_vintage` and `temporal_scope` are exported on every local metadata link.
Historical roles remain dated on refresh; unchanged older links receive an
explicit metadata-only scope. Report identifiers use their own namespace.
Refresh rechecks exact metadata literals and full station IDs, runs the
source-rule audit and withholds links if the evidence or station signature
changes. See [refresh and verification](LOCAL_REVIEW_METHODS.md#refresh-and-verification).

Source documents were processed in memory. Only selected metadata was added
to the collection; no historical levels, discharge series or complete report
bodies were saved. The sole observation generation remains
`20261020T043137Z_10d7f799`, containing 1,307 latest readings. Original metadata
generations, regional organization, CalWater categories and tributary tables
remain intact.

## Validation

All 88 USGS collection tests passed, including dated-role export and uniform
CSV columns for older and newly dated relationships. Offline validation
replayed all decisions, relationships, regional exports and the automatic
source-rule audit. The previous 10 relationship contents remain unchanged,
apart from fresh source-retrieval timestamps.

Generation `20261020T065925Z_d164e82b` verified 27 of 32 configured sources.
The [subsequent five-source retry](SOURCE_ACCESS_REVIEW.md#five-source-retry-and-additional-records)
records later recovery and current access results; the following counts describe
this earlier generation.
The two IID pages and Tulare directory remain inaccessible; the Havasu RISE
and Lake County survey requests timed out in this refresh. These five failures
remain visible and do not support new links. All four newly configured sources
verified successfully. The audit reported zero encoding flags, selection
mismatches or current identical-body discrepancies.

The observation and routing pointers are unchanged. See the
machine-readable validation report (`local_review_verification.json`) for
generation identifiers, source status, counts and verification limits.
