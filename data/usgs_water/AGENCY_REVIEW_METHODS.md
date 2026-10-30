# Original-agency address review

Dataset and generated-report paths below identify local acquisition outputs.
They require the corresponding collection, generation, or validation run
described in [water-data setup](../../docs/WATER_DATA_SETUP.md). Packaged
documentation contains the guides; historical generation paths may differ
from later acquisitions.

The agency-review catalog (`AGENCY_REVIEW.md`) investigates the 11 conflicting
addresses and 26 stations without corroborated addresses from the initial
supplemental review. It resolves **13 static feature addresses**: six conflicts
and seven previously uncorroborated cases. These features have no usable
downstream topology. Routing coverage remains **641 of 686 stations** with
latest readings; 45 still lack routing.

## Evidence and decision requirements

Each of the 37 stations receives a fresh exact-ID USGS monitoring-location
metadata request and a fresh exact-ID NLDI request. The investigation also
examines the complete original EPA/USGS NHDPlus GageLoc version 05 archive and
the USGS SWIM streamgage-address release. Source citations, dates, URLs and
checksums are retained in [source documentation](SOURCES.md) and raw receipts.
These are address and station-description products; no historical measurements
are downloaded.

GageLoc supplies 20 exact station records, with event dates of December 4, 2014.
Its **`FLComID` identifies the flowline**. The separate `COMID` field identifies
the event and is zero in these records; it must not be used for the flowline
join. `SOURCE_FEA`, `SOURCE_ORI`, `REACHCODE`, and `EventType` establish the
station identity and address namespace.

SWIM supplies 17 exact station records. All 17 were excluded from that release's
routable network. The retained reviewer notes distinguish uninitialized canals
and diversions from explicitly wrong locations or connections. SWIM has a
long-record streamgage selection criterion; absence from it does not establish
that a station lacks valid hydrography.

A supported static address requires:

1. An unambiguous original-agency GageLoc station identity and positive FLComID.
2. An exact 14-digit reachcode match to the original USGS nonnetwork feature.
3. Current USGS station geometry within the existing 250 m review tolerance.
   Distance checks an already published identifier; it does not select a reach.
4. For a previously conflicting station, agreement between GageLoc and the
   internally consistent SB19 COMID/reachcode pair.
5. No USGS reviewer statement explicitly rejecting that old location or channel.

The 250 m threshold is a review tolerance at medium hydrography resolution.
It is not a positional accuracy claim. Ypsilanti Canal and Colgan Creek near
Sebastopol are near that threshold (approximately 247 m and 241 m), so their
recorded offsets remain material limitations.

Nonnetwork addresses remain **static relationships only**. An agency note
excluding a canal from network routing can coexist with a supported static
feature identity. Direction, operational connectivity and current channel
configuration are not established by a historical address.

## Resolved conflicts

| Station | Static USGS feature | Interpretation |
| --- | --- | --- |
| USGS-11065000 — Lytle Creek at Colton | 22557940 | The USGS review explicitly identifies the uninitialized flood-control channel. Its feature-type label remains the source's `Pipeline`. |
| USGS-11121900 — Gibraltar Dam diversion weir | 17611471 | Diversion pipeline; no transfer of readings to the Santa Ynez River release route. |
| USGS-11452800 — Cache Creek overflow weir | 948021158 | Off-network channel at the settling-basin outlet. |
| USGS-11453000 — Yolo Bypass near Woodland | 15035157 | Off-network bypass channel; no substitution of a Sacramento River segment. |
| USGS-11465690 — Colgan Creek near Santa Rosa | 8273311 | Colgan Creek Flood Control Channel. |
| USGS-11465700 — Colgan Creek near Sebastopol | 8273653 | Colgan Creek Flood Control Channel; positional offset remains explicit. |

The seven additional static addresses are PVID F-Canal, D23 and C-Canal spills;
Walapai and Ypsilanti canals; and the two Coachella Canal stations. All source
feature IDs and station-specific offsets are in the catalog's relationship CSV.

## Remaining cases

The 24 unresolved cases remain individually listed with source evidence.
The subsequent local operating-agency investigation (`LOCAL_REVIEW.md`) adds
fourteen metadata relationships for ten stations without resolving their
hydrography addresses or changing the decisions below:

- **Four conflicting agency/catalog addresses:** three Fontana surface-diversion
  or forebay stations and Modesto Canal. GageLoc identifies a different
  nonnetwork feature from SB19. The Modesto reviewer notes discuss competing
  segments; an abbreviated segment reference is not promoted to an exact key.
- **Two explicitly rejected legacy locations:** Yuma Main Canal Wasteway and
  Big Creek diversion. USGS notes identify the wrong channel or wrong
  connections. The nearby network addresses are withheld.
- **One positional mismatch:** Lake Havasu's legacy Colorado River flowline is
  approximately 2.28 km from the current station point. A reservoir reading is
  not assigned to that river segment.
- **Three documented network limitations:** the Fontana powerhouse, afterbay
  spill and diversion stations lack representative NHDPlus features according
  to the retained USGS review.
- **Fourteen without an address in the checked agency releases:** Victoria
  Canal, Pilot Knob inlet, Brock Reservoir inlet/outlet, All-American Canal
  below Drop 2 outlet, Grant Line Canal, Schindler Creek, Shag Slough, Deer
  Creek at Road 88, Woodward Canal, Connection Slough, Nemeth Slough and the
  two Liberty Island marsh stations. Agency station identities are confirmed;
  no exact agency address was found in these releases. Victoria's earlier
  contradictory Water Board and SB19 candidates remain unresolved.

The original supplemental decisions and all contradictory candidates remain
unchanged. The newer agency review records the supported static interpretation
separately; historical source tables must not be treated as the latest verdict.

## Files, refresh and validation

`agency_review.json` selects an immutable metadata generation containing:

- `relationships/station_agency_review.csv`: every investigation and reason.
- `relationships/supported_static_station_features.csv`: the 13 supported links.
- `relationships/agency_address_candidates.csv`: original GageLoc keys, event
  dates, checked feature keys and positional offsets, including rejected ones.
- `swim_selected.json` and `gageloc_selected.json`: exact original agency rows,
  including reviewer notes and sentinel values.
- `nonnetwork_features.geojson.gz`: preserved original USGS feature geometries.
- Regional decision CSVs, original archives, station metadata and source receipts.

The collection pins the inventory, primary network, supplemental review and
routing geometry used for checks. Station reports show both original
supplemental and newer agency decisions, and reject stale cross-version joins.
It does not modify the statewide flow or tributary tables.

```text
python -m pip install -r data/usgs_water/requirements.txt
python -m data.usgs_water.refresh --mode agency-review
python -m data.usgs_water.validate_agency_review --output data/usgs_water/agency_review_verification.json
python -m data.usgs_water.report --station USGS-11065000
```

The refresh retains previously investigated station IDs and includes new
conflicting or uncorroborated cases. `--mode all` runs agency review after
supplemental review when that collection exists. Standalone `link-review`
refreshes require a subsequent `agency-review` refresh before its conclusions
are joined to current reports. Pending agency builds support `--resume`.

The validator checks complete original agency record selections, published SWIM
file checksums, receipt hashes, every decision replay, static feature exports,
current-series uniqueness and single-generation observation retention.
All four SWIM data files match publisher checksums. The enclosed XML's published
checksum differs from the downloaded XML and is recorded as a metadata
discrepancy; it does not affect the verified DBF used for address decisions.
Validation establishes source consistency, not flood-prediction skill.

The 7z reader is supplied by `py7zr` in the requirements file. A workspace-local
installation in `.dependencies/` is also supported; standard installed packages
take precedence. That directory contains runtime dependencies and is excluded
from version control.
