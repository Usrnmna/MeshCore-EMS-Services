# Channel history implementation verification

Implementation verification date: October 29, 2026 UTC. This record describes
the local channel-history implementation pass before v0.9.8-beta release
preparation. That pass produced no commit, push, deployment, or published
installer. The [v0.9.8-beta release verification](RELEASE_v0.9.8-beta_VERIFICATION.md)
records the later source and artifact checks.

## Implemented scope

Both platform packages contain the same optional recorder, SQLite schema and
Python read interface. Service callbacks offer received channel events after
normal routing. One configurable public, hashtag, private, or existing channel
is supported; direct messages are excluded. Retention uses local UTC reception
time and a rolling 86,400-second window. Committed records survive restart.

The shared desktop implementation includes recording settings, isolated optional
validation, a read-only viewer, bounded read helpers, and native authorization
integration. Build inventories include the recorder, guide, desktop helpers,
bundled preview schema, and `channel-history-v1` capability. No new command,
subscription owner, radio connection, or operating-system service is introduced.

The [operational guide](../meshcore_mqtt_service/CHANNEL_HISTORY.md) describes
configuration, channel identity, reception timestamps, retention, local reads,
installer controls, and failure behavior. The [architecture guide](ARCHITECTURE.md)
places the recorder within the existing service connection and routing flow.

## Automated evidence

| Environment and suite | Result |
| --- | --- |
| Windows Python 3.13, Linux package service suite | 517 tests; OK |
| Windows Python 3.13, Windows package service suite | 517 tests; OK |
| Ubuntu 24.04 WSL / Python 3.12, Linux package service suite | 517 tests; OK |
| Windows, full installer/tooling suite | 381 tests; OK, 29 skipped |
| Windows, final settings/viewer follow-up | 22 tests; OK |
| Linux/WSL, full installer/tooling baseline | 370 tests; OK, 49 skipped |
| Linux/WSL, final planned installer/GUI suite | 240 tests; OK, 8 skipped |
| Windows / Linux, final desktop packaging checks | 13 tests each; OK (1 Windows skip) |

The full Linux tooling baseline preceded the final helper-ownership and UI
corrections; the final planned run verifies those changes. The Windows UI
follow-up also verifies the final handling of unused private-key input after
changing source or disabling recording. Skipped cases do not establish target
acceptance. Documentation checks pass for 78 Markdown files and 1,515 local
links/fragments; paired source/guide/test equality, runtime exclusion, Python
syntax, and changed-file whitespace checks also pass.

Service suites run with `python -B -m unittest discover -s tests` from each
package. They include the existing command-program registration checks and all
prior service tests. Tooling runs with `python -B -m unittest discover -s tools`
from the repository root. The final planned installer run uses:

```text
python -B -m unittest tools.test_history_backend tools.test_history_process
  tools.test_history_state tools.test_history_widgets tools.test_history_window
  tools.test_history_optional_isolation tools.test_unified_backend
  tools.test_unified_window tools.test_desktop_service
  tools.test_desktop_service_window tools.test_desktop_authorization
  tools.test_unified_service tools.test_dataset_gui tools.test_desktop_kit
  tools.test_installers -v
```

The command is shown across lines for readability; module names form one command.
Qt checks use `QT_QPA_PLATFORM=offscreen`. Temporary fixtures replace installed
services, radios, brokers, and native authorization launches. Actual helper
processes, pipes, protected result sessions, and SQLite databases are exercised.

## Failure-isolation coverage

- Actual bridge callbacks retain command replies, private-channel MQTT policy,
  serialized radio access, and bounded cancellation with missing recorder code,
  initialization errors, denied permissions, corrupt storage, disk-budget
  failure, queue saturation, observer exceptions, and a stalled writer.
- Recording-only capture works with the responder disabled and MQTT disconnected.
  Empty bodies, text types, Unicode/NUL content, stale sender timestamps,
  supplied metadata, and legitimate repeated text are preserved. Replaying the
  same captured event ID is idempotent; conflicting content is not overwritten.
- Injected UTC clocks test the exact 24-hour boundary, quiet-period expiration,
  restart pruning, backward/forward clock changes, and independently expired
  cached viewer rows. Identity pins, committed restart persistence, concurrent
  process reads, sender selectors, complete-record byte limits, and keyset
  continuation are covered.
- Stalled initialization, diagnostics, read/open, authorization, and cleanup do
  not require the parent to join optional work. Request writes are nonblocking;
  late replies/grants are rejected. Linux read groups contain discovery
  descendants; Windows state observation uses read-only SCM APIs. Existing
  mutation-worker cancellation policy remains unchanged.
- Invalid optional settings/keys, missing validators, malformed optional receipt
  entries, and changes in optional availability after Review do not veto valid
  core changes. Rejected history-only edits are no-ops with explicit outcomes.
  Core validation, artifact/revision checks, protected-path checks, and required
  receipt failures retain their established behavior.
- GUI tests cover saved versus pending settings, source changes, literal message
  rendering, UTC time controls, paging, expiry, cancellation, stale-response
  rejection, catalog reload, and independent maintenance controls. Synthetic
  viewer/settings rendering was inspected locally. Native dialogs were not used.
- Packaging checks cover module/guide inclusion and exclusion of optional runtime
  databases from required configuration backups. Documentation links, paired
  content, Python syntax, and changed-file whitespace are checked separately.

## Remaining native acceptance

Actual Windows UAC and Linux/Pi polkit allowed/declined flows, installed-service
ACLs and account ownership, native installation/repair/uninstall/reboot, frozen
GUI bundles, physical Raspberry Pi ARM64 behavior, live radio reception, and
hardware latency/resource measurements remain unverified. Linux evidence uses
WSL x86_64; it is not a physical Raspberry Pi or native desktop deployment.
That implementation-verification pass did not rebuild or replace release binaries.

The isolation guarantee covers the tested application paths and bounded resource
policy. It does not establish zero shared-host CPU/disk overhead or immunity to
host-wide operating-system or hardware failures. Overload and storage failure
can create history gaps; even a normal restart can lose uncommitted observations.
Received messages are not reconstructed from periods when the service was offline.
