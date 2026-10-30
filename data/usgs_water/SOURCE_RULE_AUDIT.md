# Source-rule encoding and selection audit

Dataset and generated-report paths below identify local acquisition outputs.
They require the corresponding collection, generation, or validation run
described in [water-data setup](../../docs/WATER_DATA_SETUP.md). Packaged
documentation contains the guides; historical generation paths may differ
from later acquisitions.

The audit covers every configured local-review source, metadata excerpt,
and string value in `local_review_rules.json`. Current counts are recorded in
the generation-bound audit and active catalog. It includes
source descriptions, station rules, identifiers, findings and alternate-source
references. Published metadata generations are checked without rewriting them.

No additional encoding errors were identified in the maintained rules.
Reviewed Unicode punctuation, including curly apostrophes in the Modesto and
Brock excerpts, is preserved rather than treated as corruption. Historical inspection identifies the
already-corrected Modesto corruption; the
[Modesto investigation](SOURCE_ACCESS_REVIEW.md#modesto-la-grange-selection-mismatch)
documents the byte-identical source responses and differing local rules.

Every local-review refresh automatically records fresh source receipts and
per-source comparison results in a generation-bound `source_rule_audit.json`.
The active catalog (`LOCAL_REVIEW.md`) links the canonical audit, whose hash is
covered by the generation manifest. A
latest convenience copy (`source_rule_audit.json`) is replaced after publication.
Source access failures
remain distinct from literal mismatches. Unavailable documents cannot be
declared free of selection problems merely because their configured rules pass
encoding checks. The [alternate official sources](SOURCE_ACCESS_REVIEW.md)
remain contextual references rather than station matches.

The initial 2026-10-20 UTC audit verified 41 excerpts across 25 sources with no
selection mismatches. The remaining three excerpts belong to the two
inaccessible IID pages and the Tulare County directory. Comparison of all five
published local-review generations found only the previously corrected Modesto
rule corruption and its corresponding identical-body selection discrepancy.
Current refresh results and validation counts are recorded in the generated
audit and local-review verification (`local_review_verification.json`).

No source literals were loosened, punctuation substituted, station IDs inferred,
or uncertain matches promoted. Existing accepted metadata relationships and all
24 unresolved hydrography addresses remain intact. The audit neither requests
nor stores observation data; the current-only reading collection, routing and
tributary tables are unchanged.

## Automatic refresh and diagnostics

Both `--mode local-review` and the local-review stage of `--mode all` run the
audit before publication. Resumed local-review builds audit their retained
receipts before publication as well. No additional audit command is required.

Console output and the generated catalog show four distinct categories:

- Current encoding candidates, with JSON field paths and reasons.
- Sources whose selected literals did not match the retrieved document.
- Current failed selections that disagree with a previously verified selection
  from byte-identical response data.
- Retrieval failures, for which literal validity remains unverified.

Historical selection discrepancies are retained separately. A currently verified
source is not repeatedly flagged as a current failure merely because an earlier
generation contained a corrected rule, such as the Modesto case.

The audit flags candidates for review; it does not rewrite rules, loosen matching,
or create station/routing links. Existing acceptance rules continue to withhold
links dependent on failed retrievals or selections. Diagnostic findings do not
prevent publication of explicit unresolved decisions. Invalid UTF-8/JSON or an
audit execution/integrity error stops the local-review publication, retaining its
previous active pointer. In `--mode all`, already-completed upstream stages
retain their normal independent publication and current-only retention behavior.

## Reproduction and offline replay

From the repository root:

```text
python -m data.usgs_water.refresh --mode local-review
python -m data.usgs_water.validate_local_review --output data/usgs_water/local_review_verification.json
python -m unittest discover -s data/usgs_water -p "test_*.py"
```

Optional offline recomputation:

```text
python -m data.usgs_water.audit_source_rules --output data/usgs_water/source_rule_audit.json
```

The refresh performs the live metadata checks. The automatic audit itself is
offline and checks the pending generation's rule hash. The standalone command
requires maintained rules to match the active generation. It
decodes the maintained JSON strictly as UTF-8, scans string values for replacement
characters, unexpected controls and reversible UTF-8/Windows-code-page errors,
and compares outcomes for matching source URLs and original-response hashes.
Historical manifest pointers and hashes are pinned in each audit, so replay
continues to use the same comparison set after later refreshes. Historical files
are checked against their saved manifests. Local-review validation replays the
audit and checks its manifest summary; only the audit execution timestamp may
differ. Older generations without an embedded audit remain preserved.

Encoding flags are candidates for manual review, not automatic repair rules.
Legitimate accents and punctuation are preserved. A different selection result
for identical response bytes warrants investigation of the local rules or
extraction; it does not establish an agency wording change. Responses with
missing or different hashes cannot support that identical-body comparison.

The audit retains source IDs, URLs, statuses, hashes, excerpt counts and
historical comparison results. It does not retain full source pages or historical
measurements. Full-document hashes are acquisition evidence; discarded source
bodies cannot be independently rehashed offline. Historical manifests establish
local file consistency, not publisher signatures.

Regression checks cover ordinary accented text, curly punctuation, Windows and
Latin-1 misdecoding, replacement/control characters, HTML entities, whitespace
normalization, unchanged-body comparisons and deliberately different punctuation.
An unexpected character difference remains an explicit failed selection.
Integration checks cover automatic publication, a deliberately corrupted rule,
identical-body mismatch warnings, recovery without repeated current alerts,
audit-failure pointer preservation, invalid UTF-8, `--mode all`, and resume with
reused receipts. These checks use metadata fixtures without measurement history.
