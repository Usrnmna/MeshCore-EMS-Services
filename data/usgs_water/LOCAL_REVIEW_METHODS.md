# Local operating-agency evidence and unresolved stations

Dataset and generated-report paths below identify local acquisition outputs.
They require the corresponding collection, generation, or validation run
described in [water-data setup](../../docs/WATER_DATA_SETUP.md). Packaged
documentation contains the guides; historical generation paths may differ
from later acquisitions.

The local review catalog (`LOCAL_REVIEW.md`) investigates all 24 unresolved
addresses from the preceding original-agency review. Fourteen metadata relationships
are supported for ten stations: the original nine Fontana relationships and
Victoria Canal CDEC alias, three historical diversion roles for Big Creek and
Modesto Canal, and a report-scoped Shag Slough identifier. **No new
COMID or downstream routing link is established.** All 24 hydrography addresses
remain unresolved; statewide routing remains 641 of 686 stations with retained
latest readings.

## Relationship meaning

`relationships/station_local_links.csv` joins the complete USGS station ID to:

| Relationship | Interpretation |
| --- | --- |
| `measures_named_facility` | A Watermaster table explicitly associates the station ID with a named weir, powerhouse inflow, afterbay return or diversion. |
| `documents_return_to` | A published measurement role identifies a return to Lytle Creek; the row has no reach geometry or transit-time interpretation. |
| `documents_diversion_from` | The cited record identifies the source of a diversion, including Fontana Afterbay and the historical Big Creek role. |
| `published_station_alias` | DWR Attachment B explicitly maps USGS 11312672 to CDEC VCU. This is an identity cross-reference, not an additional independent measurement. |
| `documents_diversion_to` | A dated USGS record identifies the receiving waterway for the Big Creek or Modesto Canal diversion. |
| `published_report_station_identifier` | USGS OFR 2023-1087 maps 11455276 to SGG within that report; this does not establish a CDEC crosswalk. |

`CDEC` identifiers are agency-published codes. `curated_local_feature` and
`curated_named_waterway` identifiers are descriptive local catalog keys; they
are **not agency feature IDs, COMIDs, reachcodes or CalWater identifiers**.
Every row includes its source URL, source ID, excerpt IDs, retrieval time,
evidence class and `routing_supported=False`. These rows never seed the
statewide routing graph or expand affected-basin tables.

`source_vintage` identifies the report vintage where explicitly curated.
`temporal_scope` distinguishes historical documented roles, report identifiers
and other published metadata. None of these scopes asserts present operation.
Blank vintage means no separately curated date, not current evidence.
The [additional maps and records investigation](ADDITIONAL_AGENCY_REVIEW.md)
records all 24 cases, new supported links and unsuccessful source checks.

The separate `station_local_review.csv` preserves all 24 decisions, previous
agency status, missing evidence, candidate aliases and retrieval gaps.
Regional exports follow the inventory's existing Water Board assignments.
CalWater hierarchy categories and tributary relationship tables are unchanged.

## Important unresolved distinctions

- **Grant Line Canal:** DWR's 2016 Attachment B uses 11313200 with GLC.
  Current CDEC metadata explicitly identifies 11313240 and describes a 2005
  relocation. GLC is not assigned as a current alias of 11313200.
- **Fontana:** local table identities and diversion roles do not choose between
  conflicting NHDPlus addresses. The newer Watermaster role for 11062700 does
  not authorize transferring a legacy tailrace address to the present station.
- **Big Creek diversion:** the USGS 1998 record explicitly identifies transfer
  from Big Creek to Lewis Fork of the Fresno River. These historical roles do
  not validate CDEC BGF or override the rejected old hydrography connection.
- **Brock and Pilot Knob:** facility descriptions do not cross-reference the
  exact station IDs. Inlet, outlet, wasteway, powerplant and downstream canal
  records remain distinct. Reclamation alternatives supply outlet planning
  context and facility descriptions; IID retrieval gaps and unverified current
  segment placement remain explicit.
- **Delta marshes and sloughs:** similar names, coordinates and restoration
  project descriptions do not establish equivalent gauges or one-way tidal
  routing. CDEC SGG, CSG, LIR and LIY remain candidates/context where exact keys
  are absent; the accepted SGG identifier is scoped to the USGS report.
  A failed CDEC name lookup does not prove physical disconnection.
- **Schindler and Deer Creek:** ecological survey sites, authority
  directories and Pixley's older Road 88 Dam description are contextual leads,
  not station-to-hydrography crosswalks.
- **Lake Havasu:** Parker Dam and RISE reservoir metadata do not establish the
  station's network address or an automatic dam-release route.

## Source retention and evidence limits

The catalog links all 34 configured source URLs and receipts, including eight
contextual source-to-source associations for IID, Tulare and Havasu records.
The [alternate-source investigation](SOURCE_ACCESS_REVIEW.md) distinguishes
available contextual evidence from the unresolved station matches. Current
retrieval counts appear in the generated catalog and validation report.
Some contextual descriptions were visible during browser research, but failed
downloader receipts cannot authorize relationships.

`relationships/source_alternatives.csv` preserves original and alternate
source IDs, URLs, retrieval status, scope and limitations. Verified alternates
set `context_available=True`; failed or changed selections set it to false.
These context-only source references never become accepted station links.

Source reports may contain historical measurements. The downloader reads each
document into memory and retains only reviewed metadata literals. Selected
PDF page numbers are one-based. Full PDF pages, complete HTML bodies,
historical measurement columns, daily series and historical levels are never
written to this collection. Receipts record the requested URL, final URL when
available, HTTP status, UTC retrieval time, original response byte count and
SHA-256, and the exact retained excerpts. Failed retrievals may have no body
hash. All earlier source archives remain intact.

Offline validation checks the retained excerpts and published file hashes.
It cannot recompute a discarded full-document hash. This deliberate retention
limit is distinct from the lossless API responses in earlier collections.
The review neither downloads nor replaces current observation values.

## Refresh and verification

From the repository root:

```text
python -m pip install -r data/usgs_water/requirements.txt
python -m data.usgs_water.refresh --mode local-review
python -m data.usgs_water.validate_local_review --output data/usgs_water/local_review_verification.json
python -m data.usgs_water.report --station USGS-11312672
python -m unittest discover -s data/usgs_water -p "test_*.py"
```

`--mode all` runs local review after original-agency review and before routing.
`--mode local-review` performs no observation requests. The immutable generation
pins the upstream agency review, inventory and a copy of
`local_review_rules.json`. The maintained rules contain source URLs, literal
metadata selections, complete station IDs, reviewed station names/locations,
relationship semantics and the rationale for every case.

Source wording changes, failed requests and changed station names/locations
withhold dependent links. Newly unresolved stations without rules receive an
explicit `local_source_review_required` decision. No nearest-feature match is
performed. Rule changes require source review, followed by a new generation.
Previously published generations are preserved.

`selected_metadata_changed` means a reviewed literal did not match the received
document; it does not by itself establish an agency edit. Compare response hashes
and rule revisions before attributing the cause. The
[Modesto investigation](SOURCE_ACCESS_REVIEW.md#modesto-la-grange-selection-mismatch)
identified local encoding corruption with an unchanged source response.
Read and write rule JSON explicitly as UTF-8, using `archive.read_json` and
`archive.write_json` for scripted edits; do not rely on platform default encodings.
The [source-rule audit](SOURCE_RULE_AUDIT.md) covers every configured excerpt,
checks historical selection outcomes against response hashes, and documents the
distinction between encoding candidates, unavailable sources and actual
selection failures. It runs automatically before each local-review publication,
including `--mode all` and resumed builds. The generation manifest covers the
saved audit and its summary; console output and the catalog expose current flags.

An interrupted build can resume with `--resume` and its exact pending
directory. Resume reuses retained evidence for that build; a fresh run retries
failed sources. Reports suppress local relationships when inventory, network,
supplemental review or original-agency review versions no longer agree.

Validation replays every decision and relationship, checks all regional
exports and alternate-source rows, confirms no hydrography address was introduced, and verifies one
retained observation generation with at most one value per time series.
For generations containing an automatic audit, validation also replays the audit
against its pinned historical manifests.
See validation results (`local_review_verification.json`) and
[source citations](SOURCES.md).
