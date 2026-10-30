# Channel message history

Optional channel recording provides the most recent 24 hours of messages
received by the service on one configured public or private MeshCore channel.
Contact/direct messages are excluded. Recording performs no command recognition,
alerting, message interpretation, or replies. Existing commands, scheduling,
subscriptions, and MQTT export retain their existing ownership and behavior.

## Configuration

Recording is disabled by default. Select an existing service channel by its
stable `responder.channels` ID:

```json
{"channel_history": {"enabled": true, "channel_id": "default", "channel": null}}
```

A channel used only for recording has a separate optional specification. It
does not become a required command-service channel:

```json
{
  "channel_history": {
    "enabled": true,
    "channel_id": "fall_events",
    "channel": {"name": "#falldetect", "type": "hashtag", "mqtt_export": false}
  }
}
```

Use `type: "public"` with the configured public channel name, `hashtag` for a
standard hashtag-derived key, or `private` with a `secret_env` reference such as
`MESHCORE_CHANNEL_KEY_FALL_EVENTS`. Private names may begin with `#`; the type
selects the key semantics. Store private keys in the existing restricted
`environment.json`, never in configuration or message metadata. `existing`
adopts and pins the observed key identity. An optional `slot` disambiguates
duplicate names. Recording-only IDs must not collide with service IDs and
require `mqtt_export: false`.

The companion must already have the channel configured. Recording neither
provisions channels nor opens a second radio connection. It uses sanitized
name/key evidence from existing channel discovery and channel-info events.
Existing service targets reuse their normal verification result. A failed core
identity check remains authoritative. Recording-only targets use passive
evidence; their attribution includes the observation time and is not a fresh
per-message radio verification. Configuration must remain stable between
observations. Without usable evidence, recording remains unavailable.

Settings take effect at the next service restart. A changed channel identity
requires a new history ID. Previously committed records retain their original
channel identity and expire normally. Disabling recording retains committed
records. No timer removes data while the service is stopped or disabled, but
every supported read still excludes expired records.

## Storage and reception semantics

The service owns `channel_history/channel_history.sqlite3` below its actual
runtime directory. Installed defaults are:

- Windows: `C:\ProgramData\MeshCore-EMS\runtime\channel_history\channel_history.sqlite3`
- Linux/Pi: `/var/lib/meshcore-ems/runtime/channel_history/channel_history.sqlite3`

Manual runs use the package runtime directory. This separate subdirectory is
excluded from mandatory operational-database configuration backups. Existing
install/repair/recovery operations do not open it as a prerequisite.

Retention uses UTC reception time on this computer: `now - 24 hours < received_at
<= now`. Exactly 24 hours old is expired. Original sender timestamps remain
separate and never determine retention. The worker prunes on startup and every
60 seconds while healthy/writable, including quiet periods. Read-time filtering
enforces the exact boundary between sweeps and while recording is unavailable.
Deletion is not secure byte erasure; SQLite free pages, sidecars, or consumer
copies may retain bytes.

UTC clock corrections larger than one second relative to monotonic elapsed
time are counted in diagnostics. Stored reception times are never rewritten.
A forward correction can expire records earlier; a backward correction hides
future-dated rows until the current UTC window includes them again.

Every independent SDK reception receives its own local ID. Replaying that same
envelope is idempotent; conflicting data under one ID is a history error.
Repeated text, timestamps, or SDK hashes do not identify duplicates. Source
identifiers are preserved when supplied but are not invented. The pinned SDK
usually supplies no structured channel sender or reliable upstream message ID.
Its decoded content is preserved, including unknown metadata; data discarded
before SDK delivery cannot be restored.

The history covers received events while the service runs. Companion-buffered
events delivered after startup get the new local reception time. Complete
recovery of messages sent while offline is not provided.

## Local Python reads

Put the installed platform package on `PYTHONPATH` and pass an absolute database
path. Reading has no radio or service-control side effects:

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path
from channel_history import read_recent_messages, read_message_page, list_recorded_channels

database = Path('/var/lib/meshcore-ems/runtime/channel_history/channel_history.sqlite3')
messages = read_recent_messages(database, channel_id='fall_events')
recent = read_recent_messages(
    database, channel_id='fall_events',
    start=datetime.now(timezone.utc) - timedelta(minutes=30),
)
page = read_message_page(database, channel_id='fall_events', page_size=200)
if page.next_cursor:
    older = read_message_page(database, channel_id='fall_events', cursor=page.next_cursor)
channels = list_recorded_channels(database)
```

`start` is inclusive and `end` exclusive. Aware datetimes are required; all
ranges are intersected with the current retention window. `sender` matches
only a supplied structured sender. `sender_prefix="Alice"` separately matches
the literal text prefix `Alice: `; it is not authenticated identity. Both
selectors together are invalid. Returned records are detached from storage;
reads never acknowledge, delete, migrate, or consume records.

The full-list API returns all matching records in ascending reception order.
Pages use newest-first `(received_at, event_id)` ordering with at most 200
records and a bounded response size. Continue with the same filters and cursor.
Each page is a fresh committed snapshot: expiration advances, and late commits
whose ordering position has passed require Refresh. No stable multi-page export
is promised. `HistoryUnavailable` distinguishes an inaccessible/missing or
incompatible store from a successful empty query.

The reader needs OS access to the database and its WAL sidecars. The supported
default consumer runs as the service account. Linux runtime directories are
private; group membership alone does not grant traversal. Do not make a
private-channel log world-readable or put the live WAL database on a network
share. All recorded channel IDs share one local database access boundary.

## Installer controls and viewer

Windows, Linux desktop, and Raspberry Pi desktop share the recording controls
in unified maintenance and standalone Service Setup. Apply recording settings
is explicit; unchecked preserves saved configuration. Existing-service targets
and recording-only definitions are separate. Key values never appear in Review.
Invalid optional settings/credentials are reported as Not applied without
vetoing otherwise valid reviewed core operations. Required/shared credentials
retain existing validation. A normal reviewed configuration change follows
the existing service restart policy; a recorder fault never initiates restart.

View recent messages uses saved settings and does not apply pending edits.
The read-only viewer offers current/previous channel IDs, UTC time ranges,
sender selectors, paging, and plain-text message details. It has no send,
edit, delete, acknowledge, export, or SQL-console action. Expired cached rows
and selected details are cleared. Empty history is not proof of recorder health.
The settings page displays the last viewer observation separately from pending
configuration, including service state, database availability, latest reception,
observation time, and a read-only database path with Copy path.

Protected reads use the normal OS authorization mechanism when necessary:
UAC on Windows and polkit on Linux/Pi. The Qt process stays unelevated.
History reads have their own process lifecycle and never occupy an installer
maintenance task. Closing the viewer or installer does not wait for stalled
optional I/O. Dataset-only mode remains a reference-dataset application.
Headless systems use the service and Python interface.
Discovery/open/query has a five-second supervised deadline; authorization has
a separate 120-second lifetime. Cancelled or expired authorization cannot start
a new read. Linux read-process groups own their discovery subprocesses; Windows
uses a read-only native service-state query without a discovery subprocess.

## Failure and overload behavior

Recording is secondary to existing service functionality. Admission never waits
for queue space, worker locks, storage, initialization, retries, or shutdown.
The daemon owns its SQLite connection and does not share the operational
database or radio lock. Resource limits are deliberately finite:

| Limit | Value |
| --- | --- |
| Pending plus in-flight records | 1,024 |
| Pending encoded bytes | 16 MiB |
| Individual snapshot | 64 KiB |
| History storage budget | 256 MiB including sidecars |
| Filesystem free-space reserve | 512 MiB |
| Writer batch | 32 records |
| Busy timeout / retry budget | 1 second / 5 seconds |
| Initialization/recovery attempts | At most once per 60 seconds |

Saturation rejects the newest observation; contention, oversized data, identity
failure, or storage failure creates a counted gap. Bodies are not truncated.
No spool or hidden queue bypasses these limits. No unexpired history or unrelated
file is deleted to make room. Best-effort `status.json` diagnostics in the history
directory contain counters and categories, never bodies or credentials, and
use no primary logging handler. Full disk or a crash can prevent diagnostics.

Queued means admitted, not committed. Service stop signals the daemon without
joining or waiting to flush. Committed rows survive restart; even normal restart
can lose uncommitted observations. Finite-resource recording cannot be both
lossless under unlimited failure and independent of primary operation. Resource
guards limit interference; zero CPU/disk overhead or immunity to host-wide OS
and hardware failures is not claimed.
