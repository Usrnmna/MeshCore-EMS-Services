# Configurable Channel History Implementation Plan

Status: implementation completed in the working tree. Automated verification is
recorded in [Channel history verification](../../CHANNEL_HISTORY_VERIFICATION.md).
The native deployment/hardware acceptance matrix remains outstanding. No commit,
push, publication, service installation, or radio provisioning is included.

The detailed checklist below records the original acceptance specification.
The verification record is authoritative for executed tests; the original
scenario list does not imply native or hardware acceptance.

| Workstream | Execution status |
| --- | --- |
| Tasks 1–3: paired configuration, recorder, reads, receive/lifecycle integration | Implemented; Windows and Linux service suites pass. |
| Tasks 4–6: settings, protected reads, shared viewer | Implemented; installer, helper-process, and offscreen Qt checks pass. |
| Task 7: build inputs, capability metadata, guides | Implemented; source inventories, metadata, parity, and documentation checks pass. |
| Native acceptance matrix | Pending physical/native deployment testing; release binaries were not rebuilt. |

**Goal:** Make the last 24 hours of messages received on one configurable public or private MeshCore channel available to local Python programs and a read-only viewer, with installer GUI configuration on Windows, Linux, and Raspberry Pi.

**Architecture:** Observe channel events with a bounded nonblocking offer after normal routing, using an independent daemon writer and a separate optional runtime directory. Reuse existing identity evidence without additional radio calls; recording-only channel references remain outside required service bindings. Shared PyQt6 settings/viewer components isolate optional history outcomes from existing installer operations. Recording errors, saturation, and shutdown never impose a wait on primary functionality.

**Tech stack:** Existing Python runtime, standard-library sqlite3/threading/collections/subprocess with the existing asyncio service, pinned MeshCore 2.3.11, existing PyQt6 desktop framework, separate supervised history read processes, Windows UAC/Linux polkit workers, and unittest/offscreen Qt tests. Existing maintenance QThread behavior is preserved.

**Spec:** [Configurable channel message history design](../specs/2026-10-28-channel-history-design.md).

## Global constraints

- One selected existing-service or recording-only channel; public, hashtag, private, and existing key modes supported. Only `CHANNEL_MSG_RECV` is recorded; contact/direct messages are excluded.
- Retention is fixed at 86,400 seconds using local UTC reception time; the exact boundary is `now - 24 hours < received_at <= now`.
- Worker cleanup occurs before its first insert and every 60 seconds while healthy/writable, independently of traffic. Core startup/fetching never waits for it.
- Preserve received text and metadata; do not reuse responder content filters or deduplication hashes.
- Pending/in-flight history budgets: 1,024 records and 16 MiB; maximum snapshot: 64 KiB. Saturation rejects the new history observation immediately and counts the gap. No shared fetch gate, producer wait, spool, or per-message task is allowed.
- SQLite busy timeout: 1 second; busy retry budget: 5 seconds entirely in the worker. Storage budget: 256 MiB including WAL/sidecars; free-space reserve: 512 MiB; batches: at most 32 records with a yield between batches. Resource failure suspends history only.
- Recovery is attempted at most once every 60 seconds without accumulating workers. Admission/state locks use try-acquire; status is a last-published snapshot. Diagnostics use an independent history-only sink within its storage budget, never shared primary logging handlers/streams/locks. Import, configuration, optional identity, storage, and worker failures never become service/installer failures.
- Service stop signals a daemon worker without joining or adding a drain deadline. Committed data persists; uncommitted loss may occur even on normal restart. Admission is not a durability acknowledgement.
- Reuse existing core identity checks or sanitized passive discovery/CHANNEL_INFO observations; no recorder-induced radio calls or radio-lock acquisition. Keep required core validation unchanged.
- Use `service.RUNTIME / "channel_history" / "channel_history.sqlite3"`, outside the mandatory root-level runtime database backup scan. No installer step depends on opening/migrating/backing up this optional store.
- Absent configuration is disabled. Enabling recording does not change command assignments, MQTT export, channel provisioning, or service ownership.
- Absent/disabled history creates no worker/directory and does not import its optional module. Optional credential updates use separate request fields and cannot enter mandatory credential validation before acceptance; shared/core keys retain existing validation.
- Paired modules, tests, and guides must agree. Preserve platform-specific connection behavior.
- GUI targets are Windows x64, Linux x86_64, and Raspberry Pi ARM64. Unified maintenance and standalone Service Setup share recording controls and a read-only viewer; dataset-only mode keeps its existing scope.
- GUI settings distinguish existing service targets from recording-only references. History-only invalid edits change nothing; mixed operations report separately applied core fields and skipped history overrides. Existing core safety checks/atomicity remain mandatory. Read actions do not control services, mutate settings, provision radios, or write/delete history.
- Viewer pages contain at most 200 complete records and 2 MiB of serialized response data, with continuation rather than silent truncation. Reads reapply the 24-hour window; expired cached rows/details are removed.
- Manual Refresh and Load older use one separate history session per installer application, never its maintenance task. Read subprocesses have a 1-second SQLite busy timeout and a supervisor-enforced 5-second read deadline, including discovery/open; authorization has a separate 120-second request lifetime. Parent close never waits for history threads, child termination, or cleanup.
- Native read authorization is bounded to catalog/page requests for the installed database. Private text stays out of diagnostics, operation journals, and durable viewer caches.
- `channel-history-v1` gates only history settings/read support. Optional GUI failure cannot disable existing installer functions. Demo mode is entirely synthetic. Headless Pi operation uses the service/Python API.
- No new dependency or MeshCore command is required. No implementation-time commit or deployment is implied by this plan.

## Review focus

- Private channels and misleading direct-message text must not cross the configured channel boundary; privileged viewing must not accept arbitrary paths/SQL or leak bodies into diagnostics (Tasks 1, 3, and 5).
- Queue, writer, initialization, and diagnostic stalls must not delay existing commands/fetching/shutdown; history gaps are counted and committed versus admitted records remain distinct (Tasks 2 and 3).
- Exact cutoff, clock corrections, query ranges, page cursors, and cached viewer details must not make expired rows accessible (Tasks 2, 5, and 6).
- Repeat text, same-second sender timestamps, and repeated event IDs must distinguish independent receptions from internal retries (Task 2).
- Optional target/configuration failures, corrupt history, unsaved GUI edits, and unsupported history capability must not obstruct existing startup, install/repair/configure/recovery/removal, or dataset work (Tasks 1, 3, 4, and 7).

## Affected files

For every package-relative path below, apply equivalent changes in both
`meshcore_mqtt_service/` and `meshcore_mqtt_service_windows/`.

| Path | Responsibility |
| --- | --- |
| New `channel_history.py` | Optional settings, typed observations/status, bounded nonblocking offers, daemon writer, storage/retention, and independent reads. |
| `service.py` | Guarded optional observer after normal routing, passive binding evidence, and stop signal; preserve original fetch and shutdown flow. |
| `channels.py` | Backward-compatible sanitized slot-observer hook with no new queries or changes to required bindings/errors. |
| `service_runner.py` | Report optional history validation problems separately without changing core startup or `--check` outcomes. |
| `config.json` | Explicit disabled default; documented target selection remains an operator setting. |
| New `tests/test_channel_history.py` | Storage, retention, idempotency, reading, and worker lifecycle. |
| `tests/test_channel_bridge.py` | Actual bridge coroutine with fake SDK/radio and history enabled. |
| `tests/test_service_runner.py` | Validation and installed state-directory propagation. |
| New `CHANNEL_HISTORY.md`; existing `README.md`, `FUNCTION_REFERENCE.md`, `MULTI_CHANNEL_GUIDE.md` | API, configuration examples, limits, and navigation. |
| `installers/configure.py`; `tools/test_installers.py` | Preserve optional settings and isolate explicit history validation; prove required backup/recovery never opens history. |
| `tools/package_services.py`; `tools/test_repository_configuration.py` | Include and compare the new module/guide; protect runtime exclusion. |
| `docs/ARCHITECTURE.md`; `docs/README.md` | Accurate receive-flow summary and link to maintained guide. |

The following desktop files are shared by Windows, Linux, and Raspberry Pi;
do not create divergent platform copies of Qt controls or reader logic.

| Path | Responsibility |
| --- | --- |
| New `installers/desktop/history_widgets.py` | Reusable recording-settings widget, effective registry selection, and explicit override collection. |
| New `installers/desktop/history_window.py` | Shared read-only viewer, worker lifecycle, page navigation, plain-text detail, and cached-row expiration. |
| New `installers/desktop/history_backend.py` | Strict catalog/page requests, installed-path/capability resolution, bounded read execution, and conditional authorization. |
| New `installers/desktop/history_state.py` | Read-only Windows SCM observation without discovery subprocesses; Linux state queries stay in the owned read process group. |
| New `installers/desktop/history_process.py` | Independent read-session supervisor, process ownership, deadlines/cancellation, bounded results, and parent-exit isolation. |
| `installers/desktop/unified_window.py`; `service_window.py` | Place shared controls, open viewer, invalidate review on edits, and preserve pending fields on status refresh. |
| `installers/desktop/unified_backend.py`; `service_backend.py` | History settings validation/summary/application, preview, installed capability gates, and existing configuration/receipt lifecycle. |
| `installers/desktop/service_integrations.py` | Reuse generic change receipts; change code only if history receipt tests establish a missing contract. |
| `installers/desktop/authorization.py` | Explicit history dispatcher and protected response handling, separate from mutation operations. |
| `installers/desktop/service_main.py`; `installers/datasets/gui/main.py` | Fixed history-only worker dispatch before Qt imports in source/frozen applications; existing entry modes remain unchanged. |
| `tools/build_installers.py`; `build_dataset_gui.py`; `build_desktop_kit.py` | Capability metadata, frozen imports/source inventories, matched artifacts, and platform kits. |
| New `tools/test_history_backend.py`; `test_history_process.py`; `test_history_window.py`; `test_history_widgets.py` | Read schema/permissions/paging contracts, parent/child lifecycle isolation, and offscreen GUI behavior. |
| `tools/test_unified_backend.py`; `test_unified_window.py`; `test_desktop_service.py`; `test_desktop_service_window.py`; `test_desktop_authorization.py`; `test_unified_service.py` | Settings round trip, review invalidation, receipt recovery, retained state, read-only dispatch, and entry-point integration. |
| `tools/test_dataset_gui.py`; `test_desktop_kit.py`; `test_installers.py` | Frozen/demo build inputs, capabilities, and compatible kit inventory. |
| `docs/DESKTOP_INSTALLATION.md`; `docs/UNIFIED_INSTALLER.md`; `docs/DATASET_GUI.md` | Configuration/viewer workflow, platform authorization, and clear service-versus-dataset ownership. |
| `tools/test_history_state.py`; `tools/test_history_optional_isolation.py`; `docs/CHANNEL_HISTORY_VERIFICATION.md` | State-query ownership, optional installer failure isolation, and dated verification evidence. |

Implementation note: existing `installers/configure.py` already preserves
optional configuration and limits mandatory runtime backups to the top level.
Those behaviors are retained and tested without modifying that native owner.

Existing `channels.py` resolution and key validation are reused without changing
the accepted core registry schema or required-channel failure behavior. Its new
optional observation callback contains its own failures. `responder.py` behavior and command registrations
need no change. No history database or private channel configuration is committed.

## Task 1: Configuration and channel contract

**Interfaces:** Define `HistorySettings(enabled: bool, channel_id: str | None,
channel: Mapping[str, object] | None)`
and `validate_history_config(config: Mapping[str, object]) -> HistorySettings`
in each new `channel_history.py`. Constants and settings remain easy to inspect.

- [ ] Add tests for absent/disabled config, existing-service references, and optional recording-only public/hashtag/private/existing specifications. Cover unknown IDs, collisions with core IDs, unknown options, wrong types, optional missing keys, and responder-disabled operation without radio/database I/O.
- [ ] Run the new test module and confirm the new-interface tests fail before implementation.
- [x] Implement strict history-only validation: null channel selects an existing core ID; an inline channel is separate, noncolliding, and has mqtt_export false. Reuse field/key semantics without merging into the core registry or requiring optional keys in core startup checks. Contacts are not targets.
- [ ] Add disabled/null defaults. Test that absent/disabled settings import no optional module and create no worker or directory. Guard lazy optional imports and validation in manual startup, installed `--check`, and unrelated installer operations. History failure reports a separate warning/status while preserving core outcomes. Explicit invalid history edits are skipped/reported under Task 4; a valid core channel import may make old recording settings unavailable without being blocked.
- [ ] Define sanitized `ChannelObservation(index, name, identity, observed_at)` and `BindingEvidence` types inside optional history support. Add optional `observe_slots` callback support to `resolve_channels()` with its existing return behavior; emit the already-read slot list as plain immutable standard-library data and adapt it inside the guarded optional boundary. Contain callback failures, make no new radio queries, and never import history from core channels.py. Do not pass optional recording-only refs to core resolution or bind_state.
- [x] Run configuration, channel, service-runner, and installer tests. Compare core call counts/outcomes with the observer absent, healthy, and raising. Required core channel/key failures must still fail; optional history failures must not.

## Task 2: Persistent history and read interface

**Interfaces:** Implement `ChannelHistoryRecorder.__init__(db_path, *, settings)`,
`start()`, `observe_binding(observation)`, `offer_received(record, *, evidence)`,
`status()`, and `stop_nowait()` exactly as specified. All bridge-facing methods
are synchronous/nonblocking and do no disk I/O. Define `OfferResult`,
`HistoryStatus`, `ChannelMessage`, and
`HistoryUnavailable`. Implement `read_recent_messages(db_path, *, channel_id,
start=None, end=None, sender=None, sender_prefix=None)` returning detached records.

- [ ] Add deterministic storage tests using a temporary directory and an injected/internal UTC clock. Assert all of the following without wall-clock sleeps:

| Test | Required assertion |
| --- | --- |
| `test_exact_retention_boundary` | At frozen T, T-24h is absent, T-24h+1us is present, T is present, and T+1us is absent. |
| `test_sender_clock_does_not_control_retention` | Old, future, absent, and malformed sender timestamps do not change local-receipt expiration; original values remain in JSON. |
| `test_text_and_metadata_round_trip` | Unicode, NUL, whitespace, empty/missing text, binary metadata, unknown fields, every txt_type, and full attributes survive with documented encoding. |
| `test_distinct_receipts_and_retry` | Same text/timestamp/hash with two envelope IDs produces two rows; replay of the same envelope produces one row and preserves the original received time. A conflicting ID is a worker-side history error; no exception propagates into routing. Admission/commit/duplicate accounting remain distinct. |
| `test_idle_and_busy_cleanup` | Maintenance fires after 60 seconds with no new events and during a sustained queue; previous channel IDs are pruned too. |
| `test_restart_persists_and_prunes` | Reopen retains committed in-window rows, prunes expired rows before worker inserts, and resumes recording independently of core startup. Do not claim pending rows persisted. |
| `test_reader_is_nonconsuming` | Two reads return the same results, leave rows unchanged, and cannot create or migrate a missing/incompatible database. |
| `test_query_bounds_and_clock_changes` | Old queries cannot bypass retention; aware timezones normalize, naive times reject, exact start/end semantics hold, backward clock steps exclude future rows. |
| `test_sender_selectors` | Absent sender remains None; structured sender exact match and literal `Alice: ` prefix selection are distinct; percent/underscore characters are literal and both selectors together reject. |
| `test_concurrent_process_readers` | Separate processes can read consistent committed snapshots while a worker inserts and prunes; uncommitted records remain invisible. |
| `test_nonblocking_admission_limits` | At record/byte limits, held admission/state locks, and with oversized input, offer returns immediately with the correct counted rejection; no body truncation, tasks, extra queues, or waits occur. Queued result does not claim a commit. |
| `test_stop_does_not_join` | Stop returns before releasing an indefinitely blocked writer/init/diagnostic lock; a daemon worker cannot extend service process exit. Pending counts remain incomplete. Use a subprocess fixture to verify actual exit. |
| `test_failure_isolation_and_recovery` | Busy retries retain ID; disk/permission/corruption/init errors affect only history. Failure status is nonthrowing, recovery is at most once per 60 seconds, no replacement worker accumulates, and existing files remain intact. |
| `test_resource_and_reporting_bounds` | Byte/storage/free-space limits pause only history; no unexpired/unrelated files are deleted. Batches/counters/logging remain bounded; diagnostic I/O never executes in the producer thread or holds a primary logging handler/stream/lock. Existing logs complete with the history sink stalled. |
| `test_passive_identity` | Optional references resolve only from observed name/key evidence; missing/changed evidence or pins suspend only history. Persist evidence source/time, and never override a failed core per-message verification. |

- [ ] Run tests to confirm missing implementation failures.
- [x] Implement schema version 1 plus history-only identity pins, indexes, bounded detached snapshots, parameterized statements, and one daemon-thread-owned SQLite connection. Add record/byte budgets, drop-newest admission, try-acquire shared-state access, worker-only commit accounting/retries/retention, disk reserve and growth guards, and nonblocking stop/status. A queue's capacity-only put_nowait is insufficient if its mutex can block. No executor exit join or production commit-wait API is permitted.
- [x] Implement read-only queries with explicit channel selection and current-window intersection. Do not derive sender identity or strip the full text. Close read connections promptly; return all results without a silent cap.
- [x] Run `python -B -m unittest discover -s tests -p 'test_channel_history.py' -v` separately in both packages. Test fixtures release their synthetic blocking gates for cleanup; the production service must exit without waiting for such release. No unhandled optional exceptions are allowed.

## Task 3: Receive path and lifecycle integration

**Consumes:** Task 1 settings/evidence and Task 2 recorder API. **Produces:** an
optional observer with no recorder-to-primary control dependency.

- [ ] Extend fake-radio tests for core and recording-only public/hashtag/private channels. Include unrelated channels, contact events with identical text, raw logs, replies, every txt_type, stale sender timestamps, empty bodies, and repeats. Within healthy capacity, all identifiable target events are recorded; other classes/channels are absent.
- [ ] Add cases with `mqtt_export=false`, a disconnected MQTT client, and `responder.enabled=false`. Verify history continues, private text does not enter the MQTT outbox, and no additional radio session or command assignment appears.
- [ ] Hold commit/init/diagnostic completion indefinitely and verify both selected-channel and unrelated commands, MQTT decisions, and scheduled subscription work complete before releasing the gate. Capture UTC at the existing envelope entry point; never await history admission/commit or introduce a shared fetch gate.
- [ ] Compare the same startup/receive/shutdown fixture with history absent, disabled, healthy, saturated, invalid, missing-module, corrupt, disk-full, and stalled. Original return/exit values, command outputs, send/verify/fetch call counts/order, and existing test timeouts must match. Required core failures still fail normally.
- [ ] Stop with full/pending/in-flight history and blocked writer/init/diagnostics. Assert original callback cancellation/disconnect order and subprocess exit finish without joining the history thread or adding drain time. Report queued work as incomplete; do not expect normal restart to flush it.
- [ ] Test optional target absence, wrong optional key, observer exceptions, identity mismatch, and no passive evidence. None may add radio operations or fail core startup; no false verified row is created. A failed existing core message identity check remains authoritative.
- [x] Run these tests and confirm the new history assertions fail.
- [x] Integrate a guarded no-op-capable observer after original routing, with a contained final observation for MQTT-suppressed/noncommand events. Forward the existing envelope and identity result to offer_received; contain optional errors without overriding primary results/exceptions. Reuse sanitized discovery/CHANNEL_INFO observations and never change get_message, its command lock, or SDK fetching for history.
- [x] Start the daemon without waiting for initialization and use the dedicated history subdirectory under actual service.RUNTIME. During original cleanup, call stop_nowait and retain existing receive cancellation/disconnect semantics. Do not suppress, postpone, or await primary work on behalf of history.
- [x] Run `test_channel_history`, `test_channel_bridge`, `test_channels`, `test_service`, `test_radio_connection`, and `test_service_runner` in each package. Existing connection-lock, private-export, responder, and cancellation checks must remain passing.

## Task 4: Installer backend and shared recording controls

**Consumes:** Task 1 settings/validation and existing channel/credential schemas.
**Produces:** Equivalent configuration in unified and standalone GUI entry points,
using the existing service operation lifecycle on all three targets.

**Interfaces:** `HistorySettingsWidget.load(settings, registry, supported)`,
`set_registry(registry)`, `override() -> dict | None`, and a `changed` signal in
`installers/desktop/history_widgets.py`. `override()` returns None unless Apply
recording settings is selected; otherwise returns the enabled/ID/optional-channel
fields. Invalid fields raise `HistorySettingsError`, contained by the caller and
converted to a history-only Not applied result. Caller controllers place a valid
override under `settings["channel_history"]`. Backend results distinguish
`core_outcome` from `history_outcome` (`applied`, `preserved`, or `not_applied`,
with reason); this must not replace existing core result/exit-code semantics.
Recording-only key edits use request-only `history_credentials` and
`history_clear_credentials`, separate from existing core credential fields.

- [ ] Add backend tests: absent override preserves configuration; enabled/disabled and existing-service/recording-only public/private selections round-trip. Validate history independently against the reviewed core candidate without merging optional channels into its registry. A history-only invalid request changes nothing; mixed valid-core/invalid-history requests apply only reviewed valid core fields, retain prior history, and report the partial outcome. Required core key/registry failures still reject normally.
- [ ] Test otherwise-valid core channel removal and credential clearing when old history refers to them: allow the core change, report history unavailability, and preserve existing core credential protections. Invalid/missing optional history keys or modules must not change core startup, --check, preview, or apply results.
- [ ] Partition optional settings/key updates before every mandatory credential-validation/merge path, including request validation, configure_installed, apply_settings, validate_candidate, and deconfiguration checks. Test malformed/oversized/control-character history-only credential input: skip the entire optional bundle, preserve saved values, and complete the valid core operation. Spy that rejected optional values never reach core validators, child environments, or redaction helpers.
- [ ] Allow optional credential updates only for the selected private history reference and only when unused by both saved and proposed core registries. Test an optional update/clear of a shared key is skipped; the same key submitted through core controls retains mandatory validation. Test a safe saved string with invalid optional key encoding degrades only history. Invalid shared environment JSON, non-string/unsafe values, or genuinely invalid core keys retain existing failures; do not hide or rewrite them.
- [ ] Add compatibility tests: absent/broken `channel-history-v1` disables only history edits/reads. Existing install/repair/configure/start/stop/deconfigure/remove and dataset actions stay available. A reviewed install/repair may apply history only with a matching artifact; core artifact/config revision checks still invalidate stale Review. An optional check failure after Review skips only that override and reports the changed history outcome.
- [ ] Add repair/upgrade and receipt recovery tests: preserve saved history and committed files; restore unchanged interface-owned history fields; keep/report manual history conflicts without blocking unrelated recovery. Existing core receipt errors retain their original handling. Spy on required backups to ensure they never open, validate, migrate, or copy the optional subdirectory/database, including when it is locked, corrupt, or inaccessible.
- [ ] Add widget/controller tests: Apply defaults unchecked, disabled does not mean preserve, source selection separates existing-service IDs from recording-only definitions, names/types are visible, no contact entries, missing selections are not silently replaced, pending registry changes update choices, refresh preserves unsaved fields, and changes invalidate Review. Optional invalid fields must not lock out an otherwise valid core operation; Review shows Not applied and the reason.
- [ ] Inject optional widget/backend import, status, capability, and read failures. Both desktop windows and their existing controls must remain usable. A stalled viewer read uses a separate task/busy state and cannot disable maintenance buttons or replace its operation task. No mandatory settings summary opens history storage.
- [ ] Run `python -B -m unittest tools.test_history_widgets tools.test_unified_backend tools.test_unified_window tools.test_desktop_service tools.test_desktop_service_window tools.test_unified_service -v` and confirm the new contracts fail before implementation. Use the existing Qt environment; a skip is not GUI validation.
- [x] Extend settings allowlist, optional bundle partitioning, guarded summary/validation, reviewed candidate application, and native installer preservation. Only accepted optional settings/credentials enter the final atomic save; skipped fields never reach an older installed backend. Track history leaves through existing receipts while containing history-specific failures. Keep core atomicity, authorization, revision checks, backup/recovery, result semantics, and restart policy intact. Add capability gates only around history in both GUI paths and staged installer support. Do not invoke radio provisioning or widen credential output.
- [x] Implement the reusable widget with lazy optional imports in both entry points and one visible instance in embedded/unified mode. Connect dirty state/review invalidation, effective registry calculation, optional-source validation, saved-state display, and View recent messages. Keep standalone confirmation and unified Review/Execute behavior consistent with existing flows, including separate skipped-history reporting.
- [ ] Rerun settings/widget/backend tests and original no-history fixtures. Faults/overload never trigger service restarts; an explicit valid configuration change retains the existing restart policy. Viewer opening never applies pending settings or blocks existing installer operations.

## Task 5: Paged reader and bounded desktop read backend

**Consumes:** Task 2 store/read semantics and Task 4 installed support discovery.
**Produces:** History catalog and bounded pages usable without a GUI or any service
mutation. Add the same paging functions to both package modules.

**Interfaces:** `list_recorded_channels(db_path) -> list[RecordedChannel]` and
`read_message_page(db_path, *, channel_id, start=None, end=None, sender=None,
sender_prefix=None, page_size=200, cursor=None) -> HistoryPage`. Define the record
and page fields exactly as in the design. In `history_backend.py`, implement
`validate_history_request(request) -> dict`, `query_history(request, emit, cancel)
-> dict`, and `perform(request, emit, cancel) -> dict` with schema-1 history
catalog/page actions and no supplied filesystem or SQL paths.
In `history_process.py`, define `HistoryReadSession.start(request)`,
`cancel_nowait()`, and nonblocking status/result polling. The GUI owns only the
session handle; an unjoined daemon supervisor owns fixed-command helper processes
and file/authorization work. No callable accepting arbitrary programs is exposed.

- [ ] Extend paired `test_channel_history` with page-boundary tests: more than 200 rows, tied reception times, repeated text, cursor/filter mismatch, expired rows between pages, backdated late commits, and refresh to see newer messages. Assert all rows remain reachable without duplicate keys or silent truncation under the documented live-page semantics.
- [ ] Add tests for previous channel IDs after target changes, expired-only channel catalog entries, strict page-size/cursor limits, UTC serialization, 2 MiB response paging, and explicit rejection of a single oversized record without truncating/skipping it. The full-list Python API must remain uncapped.
- [ ] Add `tools/test_history_backend.py` tests for target mismatch, unknown actions/keys, arbitrary database/module paths, SQL/shell fields, malformed dates/cursors, oversized selectors, unavailable/uncreated/corrupt databases, and unsupported capability/schema. A missing database must never be created by a read.
- [ ] Add read-isolation tests that fail if catalog/page invokes service start/stop/configure, radio checks, dataset mutation, history cleanup, or a write connection. Simulate simultaneous writer inserts/deletes and ensure page reads remain read-only.
- [ ] Add authorization tests: direct access succeeds without elevation; permission denial triggers one structured OS request; other failures do not elevate; refusal/cancel never becomes an empty success. Assert target/path/module checks repeat in the worker and cannot follow an untrusted installed-file substitution. Inspect temporary response permissions and verify body text never reaches emit/events/diagnostic logs.
- [ ] Add `tools/test_history_process.py` subprocess tests that stall database open/read, installed-state discovery, native authorization launch, and result cleanup outside SQLite progress handling. Parent installer exit must complete before releasing the stalls, without joining a history thread or changing existing maintenance-close guards. Verify one session/worker set per application, bounded output, no replacement accumulation, and no Qt objects accessed after parent destruction.
- [ ] Test supervisor deadlines and process ownership: a read deadline is 5 seconds and cancellation gets at most a 1-second grace before terminating only the owned read child. Elevated supervision must work without permission for the GUI to kill root/administrator children. Detect parent loss through a live handle/pipe; reject authorization grants after parent loss/cancel or the 120-second request lifetime. Existing mutation workers must never use this termination policy.
- [x] Implement keyset paging, current-window intersection, and strict catalog/page request validation. Resolve the database and reader from trusted installed paths, enforce `channel-history-v1`, use bounded read deadlines, and serialize only documented response fields.
- [x] Implement fixed history-only helper dispatch before Qt imports in both application entry points. Ordinary and authorized supervisors own read children; blocking filesystem/SQL work runs only in those children. The parent uses bounded memory polling and cancel_nowait, never QThread/executor/Popen waits or a potentially waiting QProcess destructor. Protect the liveness/session channel, close safely on parent loss, and keep hidden Windows helpers from opening console windows.
- [ ] Add `kind: "history"` explicitly to authorization validation and dispatch. Reuse protected request/result sessions and UAC/polkit authorization with the separate history-only supervision policy; retain existing mutation cancellation semantics. Keep raw history out of generic maintenance results, receipts, and logs; perform no permission changes. Helpers retain session ownership until children release handles and transient output can be cleaned safely. Cleanup failure is reported without blocking the installer or claiming success.
- [ ] Run paired `test_channel_history` and `python -B -m unittest tools.test_history_backend tools.test_history_process tools.test_desktop_authorization -v`. Verify all prior authorization path-substitution tests still pass, late authorization performs no read, and cancellation/parent exit produce bounded helper lifetimes and no durable message cache under normal OS behavior.

## Task 6: Shared read-only viewer

**Consumes:** Task 5 catalog/page backend. **Produces:** `HistoryWindow(target,
parent=None, demo=False)` in `history_window.py`, opened by both GUI entry points.
Use the separate HistoryReadSession and nonblocking result polling, with an
injectable session for offscreen tests. No optional read uses the maintenance
QThread/task. No host discovery or native calls occur in demo mode.

- [ ] Add offscreen tests for current/previous channel selection, Last 24 hours/Last hour/custom ranges, mutually exclusive structured-sender/prefix filters, plain-text complete message detail, and missing metadata labels. Treat strings resembling HTML, shell commands, and URLs as inert text.
- [ ] Test 200-row paging and visible continuation, Refresh resetting the cursor, filtering without record mutation, selected-detail expiration, app-resume expiration, and stale marking after a failed refresh. Expired rows must not remain available through selection/copy or a cached older page.
- [ ] Test no-match, not-created, service-not-installed, update-required, authorization-refused, database-unavailable, and schema-error states separately. An empty log must not display a healthy/failed recorder inference.
- [ ] Test worker responsiveness, query cancellation/deadline, channel changes while a request is pending, late-result rejection, closing during UAC/polkit/SQL waits, and safe session ownership. Opening/closing the viewer must not start/stop recording, save pending configuration, or leak message text into logs. Stalled/failed reads never occupy the installer's maintenance task, disable its original controls, or prevent parent application exit. Repeated open/close while cancelling must not accumulate workers.
- [ ] Run `python -B -m unittest tools.test_history_window tools.test_unified_window tools.test_desktop_service_window -v` under `QT_QPA_PLATFORM=offscreen` and confirm new behavior fails before implementation.
- [x] Implement manual Refresh/Load older with one application-owned history session and a request-generation token. Keep only the current page/detail in memory, render body/metadata as plain text, reapply retention before display, and clear expired/stale-selection data appropriately. Close clears UI data and calls cancel_nowait without joining. No send/edit/delete/export/database-console actions are added.
- [x] Wire View recent messages into both GUI entry points using saved configuration and the shared target. Display service state, configuration state, database availability, and last reception independently; never label service-running as proof of recorder health. Keep dataset-only mode unchanged and provide synthetic demo fixtures.
- [x] Rerun viewer/controller tests and existing dataset-only/demo smoke tests. Confirm no private host discovery in demo and no functional difference between platform UI controllers.

## Task 7: Packaging, documentation, and platform acceptance

**Consumes:** Completed recorder, installer controls, bounded reader, and shared
viewer. **Produces:** Equivalent service/GUI artifacts and operational guides for
Windows x64, Linux x86_64, and Raspberry Pi ARM64.

- [ ] Add package-inventory assertions for `channel_history.py` and `CHANNEL_HISTORY.md`, paired-content equality, and exclusion of runtime history databases/sidecars/diagnostics. Verify use of the dedicated history subdirectory keeps mandatory operational database backups unchanged.
- [x] Add the module and guide to `COMMON` and shared comparisons in `tools/package_services.py`. Verify installer-source collection also includes them; do not alter artifacts in `dist/` merely to check inventory.
- [ ] Emit `channel-history-v1` from `tools/build_installers.py` only with the complete settings/recorder/reader implementation and validated history-only process/authorization lifecycle. Include shared history desktop modules/helper entry points in the source/provenance inventory and frozen hidden imports where discovery requires them. Update kit checks so GUI and installed/staged service capabilities agree.
- [ ] Extend GUI/kit build tests for both unified and standalone service entry points, synthetic history demo mode, default disabled settings, and absence of runtime databases, sidecars, credentials, or authorization-result files. Preserve dataset-only launch behavior.
- [ ] Write the paired guide from the design: existing-service versus optional recording-only channel examples, passive identity evidence/limitations, restart/provisioning distinction, Python import path and queries, exact retention, nullable sender/source IDs, duplicate semantics, service-account access, and coverage/failure limits. Describe drop-newest/contended/oversized gaps, resource guards, committed-versus-admitted status, best-effort diagnostics, and possible uncommitted loss on normal restart. Link it from package guides and the documentation index; correct the inaccurate MQTT receive-flow sentence in `docs/ARCHITECTURE.md`.
- [ ] Document installer controls, saved-versus-pending selection, separate core/history outcomes, optional skipped edits, unaffected existing operations on older installations, Review/Execute versus read-only viewer access, UAC/polkit behavior, page navigation, expiration, and no-data/error distinctions in the desktop/unified guides. Explain the dataset-only boundary in `docs/DATASET_GUI.md` and link to service history guidance.
- [ ] Run the non-interference matrix with history absent/disabled/healthy/full/contended/oversized/invalid/missing/corrupt/low-space and deliberately stalled initialization, storage, and diagnostics. Compare primary command results, MQTT policy, scheduling/subscriptions, fetch/verify calls, logging, service exit/stop behavior, installer results, and unrelated settings. Required core safety failures must still fail. Test both record and byte limits without releasing stalled dependencies until primary work finishes.
- [x] Validate Markdown links, changed-file whitespace, the paired file inventory, and configuration preservation tests. Use `package_files()` for a read-only inventory check rather than rebuilding releases.
- [x] Run both packages' `tests/test_command_programs.py` as a regression guard. No new MeshCore command is proposed; if one is later requested it needs a dedicated executable in each package's `scripts/` and corresponding registration.
- [x] Run `python -B -m unittest tools.test_history_backend tools.test_history_process tools.test_history_widgets tools.test_history_window tools.test_unified_backend tools.test_unified_window tools.test_desktop_service tools.test_desktop_service_window tools.test_desktop_authorization tools.test_unified_service tools.test_dataset_gui tools.test_desktop_kit tools.test_installers -v` in the normal pinned Qt/tooling environment. Run `python -B tools/check_documentation.py` and paired service suites. Treat missing dependencies or skipped Qt tests as limits, not passing GUI evidence.
- [ ] Complete the native acceptance matrix below without conflating offscreen/QEMU tests with native operation. Native builds and test artifacts are produced only during authorized implementation/release work, not by this design update.

| Target | Acceptance evidence |
| --- | --- |
| Windows x64 | Unified and standalone settings round trip; UAC allowed/declined; runtime ACL and WAL reads during recording; view access never stops service; upgrade retains selected private target and committed history; normal process exit with a stalled history thread. |
| Linux x86_64 | Both GUI entry points; polkit allowed/declined/unavailable; service-owned 0700 runtime read through authorized helper; schema/page reads and expiration during writes; repair/recovery preserves settings; systemd stop deadlines unchanged with a stalled recorder. |
| Raspberry Pi ARM64 | Native desktop versions of Linux checks, responsive paging while recording, shutdown/cancellation behavior, continued service operation with GUI closed, and measured command responsiveness during saturation and storage faults. |
| All targets | Synthetic public/private/control-channel cases, inaccessible/uncreated DB states, no hidden content logging, restart and cached-view expiration, unaffected core installer/dataset operations under optional history faults, independent parent exit with stalled read/authorization/cleanup, late-grant rejection, bounded helper lifetimes, isolated optional credential failures, bounded resource use and baseline latency comparison, and explicit distinction between configuration success and physical reception evidence. Zero shared-host overhead is not claimed. |

## Verification and execution limits

Pinned dependencies were prepared in the existing Windows environment and an
isolated Linux/WSL environment. Both package implementations, shared desktop
components, build inventories, and guides were updated. Automated verification
uses disposable SQLite databases, fake radios/brokers, fixture installer state,
process helpers, and offscreen Qt; it does not establish native authorization,
physical reception, deployed-service reboot behavior, or Raspberry Pi performance.

No new MeshCore command, deployment unit, device write, published release, commit,
or push was created. Release installers were not rebuilt. Native acceptance
still requires installation/repair, authorization allowed/declined, runtime
permissions, service lifecycle, and saturation measurements on actual targets.
Messages missed while offline are outside the history guarantee.
