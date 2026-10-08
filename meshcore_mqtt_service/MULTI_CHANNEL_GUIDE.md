# Multiple MeshCore channels and program assignments

Both service packages support several channels on one Companion Node over serial, BLE, or TCP. Each
command has an explicit list of channels on which it may run. Public, public
hashtag, and private shared-key channels are supported. Replies stay on the channel
where the request arrived; selecting several channels does not broadcast a result
to all of them. Linux and Windows retain their separate configuration, MQTT
defaults, Python environments, and runtime state.

## What changed

| Change | Operator-visible behavior |
| --- | --- |
| Automatic USB port detection | `serial_port: "auto"` detects the single supported USB serial device at each start, including after a port-number change. Explicit fixed ports remain available. |
| Channel registry | `responder.channels` maps stable local IDs to radio channel names, types, optional slots, and MQTT export choices. |
| Program assignments | Every `responder.commands` entry lists its permitted channel IDs. An empty list disables that command everywhere. |
| Setup utility | `channel_setup.py` lists radio slots, checks configured channels, or explicitly provisions one channel in an empty slot. |
| Identity checks | The service verifies the channel name and key before accepting requests, executing queued work, and sending replies. A mismatch does not fall back to Public. |
| Persistent channel state | Requests, duplicate detection, cooldowns, and flood subscriptions use channel IDs. SQLite pins each ID to its name and key identity across restarts. |
| Shared radio and bounded queues | Channel workers share the radio transmission limiter. Per-channel queue limits prevent one channel from filling the entire pending queue. |
| Private-channel controls | Keys are referenced through secret environment variables; each channel explicitly controls decoded-message and reply export to MQTT. |
| Installation and migration | Both installers import registries and assignments, preserve existing assignments, validate settings, and back up existing configuration and databases. |
| Operator programs | Installations keep additional Python programs in a protected external directory. Add or update programs and command definitions without rebuilding or reinstalling the installer. |
| Reviewable source | Channel policy, provisioning, responder routing, and installer migration have separate functions and explanatory comments. The file/function map below identifies their responsibilities. |

## Configuration format

Edit the active `config.json`, not an unused source copy. Installed locations are
listed below. Keep the existing MQTT, timing, and command-script settings. Replace
the old `responder.channel_name` with a `responder.channels` object and add
`channels` to **every** command entry.

| Channel field | Meaning |
| --- | --- |
| Object key, such as `operations` | Stable local ID: 1-64 letters, digits, underscores, or hyphens. Commands reference this ID, not the display name or slot number. |
| `name` | Exact radio channel name; printable text, no surrounding whitespace, at most 32 UTF-8 bytes. |
| `type: "public"` | Uses the standard MeshCore Public key. Normally named `Public`; the name still must match the radio. |
| `type: "hashtag"` | Name begins with `#`; derives its key from the name. Anyone knowing that name can derive the key. |
| `type: "private"` | Uses the shared 16-byte key supplied by `secret_env`. A name beginning with `#` is allowed and retains the supplied private key. |
| `type: "existing"` | Adopts an already configured radio channel. No key is supplied or derived; the first successful service binding pins the actual name and key identity. The setup check verifies its name/slot; persisted key pins are checked at service startup. This type cannot be provisioned. |
| `slot` | Optional integer from 0 to 255 identifying a radio slot. Actual available slots depend on the connected firmware. Specified slots must be unique. Without a slot, exactly one radio channel must match the name. |
| `secret_env` | Required only for `private`. Names must start with `MESHCORE_CHANNEL_KEY_`, followed by uppercase letters, digits, or underscores. Store the secret value outside `config.json`. |
| `mqtt_export` | Required `true` or `false`; controls decoded channel events and automatic reply text exported to MQTT. Use `false` for private traffic unless export is intentional. |

Every command's `channels` value must be a list of unique registered IDs. There is
no wildcard or implicit assignment. Adding a channel does not enable any commands
there. Assignments attach to command phrases, so `!floodwarn` and `!floodalarm` can
use different channels even though they share the flood lookup script.

### Example: Public, community, and private operations

The following is a complete **installer import file**, for example
`channels.json`. It is an overlay, not a replacement for the service's entire
`config.json`. It supplies assignments for all ten bundled commands and preserves
their scripts, arguments, input validation, timeouts, and reply settings.

```json
{
  "channels": {
    "public": {"name": "Public", "type": "public", "mqtt_export": true},
    "community": {"name": "#ourcommunity", "type": "hashtag", "mqtt_export": true},
    "operations": {
      "name": "Operations",
      "type": "private",
      "secret_env": "MESHCORE_CHANNEL_KEY_OPERATIONS",
      "mqtt_export": false
    }
  },
  "command_channels": {
    "!status": ["operations"],
    "!time": ["public", "community", "operations"],
    "!aqi": ["community", "operations"],
    "!traffic": ["community", "operations"],
    "!rivers": ["community", "operations"],
    "!uv": ["community", "operations"],
    "!heatadv": ["community", "operations"],
    "!floodwarn": ["community", "operations"],
    "!floodalarm": ["operations"],
    "!snowpack": []
  }
}
```

For manual editing, copy the example's `channels` object into
`config.json` under `responder.channels`. Copy each assignment into the matching
existing command, for example:

```json
"!time": {
  "script": "scripts/time_now.py",
  "args": [],
  "channels": ["public", "community", "operations"]
}
```

Do not insert `command_channels` into `config.json`; it is only the installer
import format. Keep all other command fields. The installer rejects unknown
command names. Omitted import assignments retain existing values, so list every
command explicitly when replacing a registry, including custom commands. References
to IDs missing from the replacement registry cause validation to fail.

In this example, `!time` works on any of the three channels and answers only the
sender's channel. `!status` works only on Operations. `!snowpack` is disabled. A
command received on a channel where it is not assigned does not execute a script.

## Private keys and local data

Put the actual Operations key in the active `environment.json`:

```json
{
  "MESHCORE_CHANNEL_KEY_OPERATIONS": "REPLACE_WITH_THE_ACTUAL_SHARED_KEY"
}
```

The placeholder above is intentionally invalid. Use either 32 hexadecimal digits
or standard Base64 encoding of exactly 16 bytes. Obtain the key from the channel's
operator and configure the same key on participating nodes. Keep existing AirNow
and MQTT credentials in this file. Neither the installer import nor `config.json`
accepts an inline channel key. Never commit secret files or runtime databases.

Installed services load this file through `service_runner.py --environment`.
For source-folder interactive launchers, set the named environment variable in the
launching process; they do not automatically load `environment.json`. The setup
utility can explicitly load that file with `--environment`.

Windows installation restricts the ProgramData directory to SYSTEM,
Administrators, and LocalService; LocalService can modify runtime and data
directories. Linux installed JSON files use `root:meshcore-ems` ownership and mode
`0640`; runtime directories/files use `0700`/`0600`, and dated installation backups
are restricted to root. Preserve these permissions when editing/restoring files.
Source-folder operators must separately restrict their secret files, runtime
directory, and backups to the service account and administrators.

Channel keys are omitted from setup listings, redacted from known event secret
fields, and removed from command-script environment variables. This does not make
arbitrary local scripts a sandbox: scripts still run as the service account.
The local database contains decrypted requests and results, even when
`mqtt_export` is false. Protect the machine, account, logs, databases, and backups.

With a registry configured, the bridge suppresses unknown-channel traffic and
unclassified/raw packet logs from MQTT so they cannot bypass channel export choices.
Allowed node/device telemetry remains available. On restart, queued MQTT events
are checked against the current export policy. Legacy channel events without a
stable channel ID and unclassified old events are discarded rather than guessed
from potentially reused slot numbers. Messages already delivered to an
MQTT consumer cannot be recalled. Treat MQTT access as separate from radio channel
access: radio encryption does not protect a broker's decoded copies.

## Installation and setup sequence

1. Stop the bridge before using the radio setup utility; only one process can own
   the radio connection. Also close other MeshCore applications using that connection.
2. Back up the active configuration, secret file, and consistent runtime database.
3. Save the registry and every program's assignments. For private channels, create
   the protected secret file before running a readiness check.
4. Select serial, TCP, or BLE in `connection` (see [README.md](README.md#radio-connection-settings)).
   For serial, keep `serial_port: "auto"` to detect the single attached USB serial device.
   With multiple USB serial devices, select the intended device explicitly, such
   as `COM7`, `/dev/ttyUSB0`, or `/dev/serial/by-id/...`. The setup utility uses
   the same connection settings as the service and does not use an interactive selector.
5. Run `list`, then `check`. If a channel is missing, configure it with the MeshCore
   application or explicitly run `provision CHANNEL_ID` for each missing channel.
6. Run `check` again, start the service, and verify commands on separate radios.

On a first private-channel installation, install the default configuration with
`--no-start` (Linux) or `/NOSTART=1` (Windows), populate the protected
`environment.json`, then import the registry on a second installer run, again with
startup disabled. This lets the installer validate private keys before starting.
The installers themselves do not program the radio. If the radio already has the
correct channels, provisioning is unnecessary.

Linux import example:

```bash
sudo bash MeshCore-EMS-v0.3.0-beta-linux-x86_64.run --port auto --channels-config /absolute/path/channels.json --no-start
```

Use the corresponding ARM64 installer on Raspberry Pi. Windows setup provides an
optional channels-JSON path field. An administrator can also use:

```bat
MeshCore-EMS-v0.3.0-beta-windows-x64-setup.exe /SERIALPORT=auto /CHANNELSCONFIG="C:\Setup\channels.json" /NOSTART=1
```

The old `--channel` / `/CHANNEL` option is only for a single-channel configuration;
it cannot be combined with a channels import. Once an ID has been bound in the
runtime database, changing that channel's name or key requires a new ID as described
below. Use the registry import for that change.

### USB port selection

When `connection.type` is `serial`, the top-level `serial_port` setting defaults to `"auto"`. On every service start
or restart, the service scans supported serial device names and USB metadata
(a USB vendor ID or USB hardware identifier). Exactly one candidate is selected. If none
or several are found, startup reports an error rather than guessing. Connect the
Companion Node with its driver available, or set an explicit port when the host
has several USB serial devices. Detection does not identify MeshCore firmware
among arbitrary USB devices; the selected device must be the intended Companion.

Moving the device to a different USB socket or receiving a new COM number is
handled on the next start with `auto`. A detected radio disconnection stops the bridge;
restart it to rescan (the installed service manager restarts failed processes).
A fixed setting such as `"serial_port": "COM7"` or
`"serial_port": "/dev/serial/by-id/YOUR_COMPANION"` intentionally skips automatic
selection. New installations default to serial `auto`. Omit connection options
during an upgrade to preserve the existing transport and endpoint.

The offline `service_runner.py --check` checks the setting syntax without
discovering or opening a device. `channel_setup.py list/check/provision` resolves
the same setting when it connects to the radio.

### Installed Linux service

Run from a terminal with sudo access. Substitute the intended IDs and paths.
Options must appear **before** `list`, `check`, or `provision`.

```bash
sudo systemctl stop meshcore-ems
sudo -u meshcore-ems /opt/meshcore-ems/current/.venv/bin/python /opt/meshcore-ems/current/meshcore_mqtt_service/channel_setup.py --config /etc/meshcore-ems/config.json --environment /etc/meshcore-ems/environment.json list
sudo -u meshcore-ems /opt/meshcore-ems/current/.venv/bin/python /opt/meshcore-ems/current/meshcore_mqtt_service/channel_setup.py --config /etc/meshcore-ems/config.json --environment /etc/meshcore-ems/environment.json provision operations
sudo -u meshcore-ems /opt/meshcore-ems/current/.venv/bin/python /opt/meshcore-ems/current/meshcore_mqtt_service/channel_setup.py --config /etc/meshcore-ems/config.json --environment /etc/meshcore-ems/environment.json check
sudo systemctl start meshcore-ems
```

### Installed Windows service

Run in administrator PowerShell. Adjust the installation path if customized.

```powershell
Stop-Service MeshCoreEMS
$channelPython = 'C:\Program Files\MeshCore-EMS\python\python.exe'
$channelSetup = 'C:\Program Files\MeshCore-EMS\meshcore_mqtt_service_windows\channel_setup.py'
$channelConfig = 'C:\ProgramData\MeshCore-EMS\config.json'
$channelEnvironment = 'C:\ProgramData\MeshCore-EMS\environment.json'
& $channelPython $channelSetup --config $channelConfig --environment $channelEnvironment list
& $channelPython $channelSetup --config $channelConfig --environment $channelEnvironment provision operations
& $channelPython $channelSetup --config $channelConfig --environment $channelEnvironment check
Start-Service MeshCoreEMS
```

### Source-folder operation

After the platform's normal setup, stop the interactive bridge with Ctrl+C. From
its service folder, use the appropriate Python executable:

```bash
.venv-linux/bin/python channel_setup.py --config config.json --environment environment.json list
.venv-linux/bin/python channel_setup.py --config config.json --environment environment.json check
```

```powershell
.\.venv\Scripts\python.exe channel_setup.py --config config.json --environment environment.json list
.\.venv\Scripts\python.exe channel_setup.py --config config.json --environment environment.json check
```

Use `provision operations` in place of `check` only when creation is intended.
Restart the normal launcher after setting secret environment variables. All
configuration and assignment changes require a service restart; there is no live
configuration reload.

### Setup command limits

`list` prints slot numbers, names, and whether each slot is empty, never keys.
`check` verifies the registry against the radio without writing radio settings.
It does not open the running service's database or compare historical identity
pins; startup performs that additional check.

`provision` accepts `public`, `hashtag`, or `private` entries. It accepts an exact
existing match, otherwise writes only a slot whose name is empty and whose key is
all zero bytes. It never overwrites an occupied slot. With no explicit `slot`, it
uses an existing matching name or the first empty slot. Ambiguity, a full radio,
or a mismatch causes an error. Inspect/free slots explicitly with the MeshCore
application if necessary, then retry. A successful write is read back for
verification. Normal bridge startup only reads and verifies radio settings.

## Queues, alarms, and identity changes

`max_pending` remains the global queue bound. Optional
`responder.max_pending_per_channel` defaults to `min(20, max_pending)` and must be
a positive integer. With the default global bound of 50, one channel can queue at
most 20 pending requests. Sender cooldowns and duplicate suppression are scoped to
the channel ID. All channels and MQTT commands share `command_interval` radio
spacing, so load on one channel can still delay another channel's transmission.

Flood subscriptions belong to a sender and channel ID. The same sender can keep
independent locations on two channels where `!floodalarm` is enabled. Renewal,
four-hour expiry, silent baseline, and 20-minute check timing retain their existing
meaning. Requests and outgoing notifications recheck program assignments; removing
an assignment prevents later work from being sent on that channel. A restart does
not extend subscription deadlines. Re-enroll deliberately after changing channel
identity.

The `channel_bindings` table stores each stable ID with the channel's display name
and a SHA-256 key identity hash, not the key itself. To move the same channel to a
different radio slot, keep its ID, name, and key and update any explicit `slot`.
Restart and check the mapping. To replace a name or key, choose a **new ID**, update
command assignments, restart, and ask users to enroll alarms on the new channel.
Do not edit identity pins to redirect old requests or subscriptions. A missing
channel, duplicate name without a unique slot, changed key, or removed assignment
never redirects a reply to Public.

## Upgrades, backups, and rollback

A legacy `responder.channel_name` is migrated to ID `default`, type `existing`,
with `mqtt_export: true`; existing commands are assigned to `default`. This keeps
the prior single-channel behavior and export choice. Review export before moving
private traffic onto the service. Loading legacy source configuration migrates it
in memory; installer configuration writes the migrated JSON to disk. Save the
new schema explicitly when editing a source installation.

An installed upgrade preserves current assignments. Newly added programs remain
disabled (`channels: []`) when a registry already exists until the operator assigns
them. The installer writes dated snapshots under the state directory's `backups/`
and retains `config.before-install.json` in the configuration directory. The first
channel-state migration also creates `runtime/bridge.before-channels.sqlite3`
when an existing database needs migration. Legacy requests/subscriptions migrate
only when the old channel name has an unambiguous mapping; unresolved queued work
expires and unresolved subscriptions are disabled.

Installed state directories are `/var/lib/meshcore-ems` on Linux and
`C:\ProgramData\MeshCore-EMS` on Windows. Source installations keep state under
their service folder's `runtime/` directory. Keep a separate protected backup of
`environment.json`; the dated configuration/database snapshot does not include
this credential file.

For rollback, stop the service, preserve the current state for diagnosis, restore
the matching earlier program version, configuration, credentials, and consistent
database snapshot, then start and verify. Restore database state as a unit, taking
SQLite journal/WAL files into account; do not copy an open database file. Do not
mix an old configuration with a database pinned to replacement channel identities.
Provisioning changes on a radio require separate manual review; restoring host
files does not undo radio configuration. Backups support recovery, but do not
constitute a verified automatic rollback across host and radio changes.

## Code and file guide for manual review

Each service package contains its own copy of the following files. Changes to
shared code and this guide must be kept equivalent in both packages.

| File / function | Responsibility, state, and limits |
| --- | --- |
| `channels.py` - `migrate_config`, `validate_channels` | Convert legacy settings in memory and validate IDs, types, slots, export choices, assignments, and queue limits. No radio writes. |
| `channels.py` - `decode_key`, `expected_key` | Parse a 16-byte key or derive/select a public key. Error text does not echo the supplied key. |
| `channels.py` - `discover`, `resolve_channels` | Read available radio slots and match every configured ID to exactly one verified name/key. No fallback or provisioning. |
| `channels.py` - `verify_binding` | Read the bound slot again and reject name/key changes before work crosses the radio boundary. |
| `channels.py` - `bind_state` | Back up/migrate existing SQLite state and persist name/key identity pins. Writes host state, never the radio. |
| `channels.py` - `channel_config`, `export_allowed` | Supply a worker's channel context and decide whether a classified event may enter the MQTT outbox. |
| `channel_setup.py` - `main`, `run` | Load explicit config/secret paths, open the configured radio connection for the selected action, print results, and disconnect. |
| `channel_setup.py` - `provision` | Explicitly write one empty slot and verify it. Uses the set-channel protocol frame so a private `#` name retains its supplied key. |
| `responder.py` - `allowed`, `accept`, `process_one` | Enforce command assignments at admission/execution, persist channel-aware requests, enforce queue limits, and reject obsolete work. |
| `responder.py` - `run_script`, `send_flood_change` | Supply script context without channel key environment variables; keep alarm responses on their enrolled channel. |
| `service.py` - `bridge_loop`, nested `receive`, `verify`, `send_reply` | Connect radio bindings to channel workers, check identity, apply MQTT export, and serialize sends through the shared radio limiter. |
| `radio_connection.py` - `connection_settings`, `radio_session`, `select_serial_port` | Validate `auto`/fixed-port syntax without device I/O, then enumerate supported USB serial candidates when connecting. Select exactly one or fail clearly; never probe several devices to guess. |
| `service_runner.py` - `load_environment`, `main` | Load allowlisted secrets, validate installed configuration/key formats, and run the unattended service. `--check` does not contact the radio. |
| `config.json` | Channel registry, per-command assignments, and queue policy alongside existing settings. Contains secret variable names, not secret values. |
| `tests/test_channels.py` | Simulated channel policy, routing, provisioning, identity, export, and migration checks; see the current tests for exact coverage. |
| Workspace `installers/configure.py` | Import registry/assignments, preserve operator choices, and snapshot existing config/SQLite state before writing installed settings. |
| Workspace `installers/linux/install.sh`, `installers/windows/install.ps1`, `installers/windows/setup.iss` | Expose import options, restrict installed files, and integrate configuration with OS-service installation. |
| Workspace `tools/package_services.py` | Include the additional files and check paired package parity before packaging. |

Custom scripts receive `channel_id` in their stdin JSON and
`MESHCORE_CHANNEL_ID` in the environment, alongside the existing display name,
slot index, sender, phrase, and request ID. Use the stable ID for channel-specific
behavior. Scripts return reply text on stdout; they do not choose another
destination by changing that text or context.

## Add Python programs after installation

You can add new Python functions or programs to an installed service without
recompiling, rebuilding, or rerunning the installer. Put the functions in a `.py`
file with an entry point, then register that file as a command. The service runs
the program in its existing Python runtime when an allowed channel requests it.

Installed `responder.program_directory` points to an absolute directory:

| Platform | Operator program directory |
| --- | --- |
| Linux / Raspberry Pi | `/etc/meshcore-ems/programs` |
| Windows | `C:\ProgramData\MeshCore-EMS\programs` |

Installers preserve this directory across upgrades. Linux's default directory is
owned by `root:meshcore-ems`, with mode `0750`; program files should use mode
`0640` with that ownership. Windows inherits the protected ProgramData ACL, so
administrators can edit programs and LocalService can read them. Keep this
directory read-only to the service account. Source-folder deployments can set
their own absolute `responder.program_directory` and equivalent permissions.

1. Stop the service before replacing a program or editing its command definition.
2. As administrator/root, save this example as `channel_note.py` inside the
   operator program directory. Give it the ownership and permissions above.
3. Add the command definition below to the active `responder.commands` object,
   using channel IDs from your registry.
4. Run the installed runner's offline check, then start the service and test the
   command from a permitted channel.

```python
"""Return a brief local note for the channel that requested it."""
import json
import sys


def make_note(channel_id):
    """Build reply text from a stable local channel ID; perform no radio writes."""
    return f"Local information service for {channel_id}."


def main():
    """Read the responder's request context and print the untagged reply body."""
    request = json.load(sys.stdin)
    print(make_note(request["channel_id"]))


if __name__ == "__main__":
    main()
```

Example command entry (merge it into the existing command map):

```json
"!note": {
  "script": "programs/channel_note.py",
  "args": [],
  "channels": ["community", "operations"],
  "timeout": 10
}
```

The `programs/` prefix resolves under `responder.program_directory`; it is not
the Python file's absolute path. Existing `scripts/...` definitions continue to
use bundled scripts. Paths must remain within the selected program root after
resolution. Avoid symlinks to files outside that root. Optional fixed `args` are
trusted configuration; received text never becomes shell code. Omit `input` for
an exact command with no user arguments, as in this example. Existing supported
input modes remain available for programs that accept validated arguments.

The script prints only its reply body. The responder supplies the sender's
`@name`, splits long output, applies timeout/output limits, and replies only to
the originating channel. A script that only defines functions and never calls
them produces no reply body; the entry point above demonstrates how to call a
new function. Scripts use the service folder as their working directory, so use
`Path(__file__).resolve().parent` when loading a file kept beside your program.

Linux offline check:

```bash
sudo -u meshcore-ems /opt/meshcore-ems/current/.venv/bin/python /opt/meshcore-ems/current/meshcore_mqtt_service/service_runner.py --config /etc/meshcore-ems/config.json --state-dir /var/lib/meshcore-ems/runtime --environment /etc/meshcore-ems/environment.json --check
sudo systemctl start meshcore-ems
```

Windows offline check, from administrator PowerShell:

```powershell
& 'C:\Program Files\MeshCore-EMS\python\python.exe' 'C:\Program Files\MeshCore-EMS\meshcore_mqtt_service_windows\service_runner.py' --config 'C:\ProgramData\MeshCore-EMS\config.json' --state-dir 'C:\ProgramData\MeshCore-EMS\runtime' --environment 'C:\ProgramData\MeshCore-EMS\environment.json' --check
Start-Service MeshCoreEMS
```

The offline check validates configuration, paths, and custom-program Python syntax;
it does not execute the
custom program or establish that its behavior is correct. Test that program
separately and then test its channel response. The example uses only Python's
standard library. Additional dependencies are not automatically installed from
custom program files; if needed, deliberately manage them in the installed
runtime and retain a record for later upgrades. Editing files does not provide
live configuration reload: restart after edits.

## Verification procedure

Run `bash verify.sh` in the Linux package or `verify.cmd` in the Windows package
after setup. These discover the test files automatically. From the workspace,
run `python tools/package_services.py` to check package parity and build fresh
source ZIPs. Changes to the packaged service itself require rebuilding its
distribution; see the workspace installation guide for build commands. Adding
operator programs under `program_directory` does not require that rebuild.

Before deployment, use `channel_setup.py ... check` against the intended radio,
then verify with separate receiving radios:

1. Send an allowed command on Public, a hashtag channel, and a private channel.
   Confirm each answer appears only on the originating channel.
2. Send a command where its assignment is absent and confirm no script/reply runs.
3. Subscribe the same displayed sender on two enabled channels; verify independent
   locations, renewal, expiration, and restart recovery.
4. Inspect MQTT with test traffic and confirm exported channels are visible while
   private `mqtt_export: false` channel text and raw/unclassified traffic are absent.
5. In a controlled test setup, change a slot's key or name and confirm the service
   refuses to accept/send under the stale identity; restore it before resuming.
6. Exercise installation upgrade, service restart, and backup recovery on each
   target platform with a copied test configuration and database.

Automated tests and successful local radio transmission do not establish recipient
delivery, native Linux installation, physical radio behavior, or uninterrupted
four-hour alarm operation. Record those observations separately when performed.
