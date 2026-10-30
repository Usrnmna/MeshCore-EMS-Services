# Version 0.9.8 - Beta

Release identifier: `v0.9.8-beta`. Windows numeric file version: `0.9.8.0`.
Preparation date: October 29, 2026 UTC. This is a local release preparation;
publication, tagging, and upload are separate actions.

MC-EMS-Services provides 31 dedicated MeshCore commands on Linux, Raspberry Pi
ARM64, and Windows x64. This release combines graphical installation and
maintenance, independent reference-data packages, and optional channel history
with the existing bridge, responder, and service-owned subscriptions.

## Changes in this release

- Optional recording retains received messages from one configured public,
  hashtag, private, or existing channel within a rolling 24-hour UTC reception
  window. Recording is disabled by default and excludes direct messages.
- A read-only desktop viewer and local Python API expose committed history,
  with channel selection, UTC time ranges, sender filters, paging, and explicit
  unavailable states. Opening the viewer does not apply pending settings or
  start or stop the service.
- Recording uses separate SQLite storage and bounded nonblocking admission.
  Recorder faults and unavailable optional settings are isolated from core
  routing and maintenance. Overload, storage failures, or uncommitted observations
  at shutdown can leave gaps; recording is not a lossless delivery archive.
- Installation and Maintenance coordinates reviewed service, dataset, settings,
  and custom-program operations. Service Setup and dataset-only maintenance
  remain available independently. Native authorization and recovery controls
  retain each package's ownership and lifecycle.
- Eight reference collections retain separate installers, updates, rollback,
  and removal. Service upgrades preserve data selections, settings, credentials,
  custom programs, and runtime state. Dataset removal remains explicit.
- Current documentation and package metadata use `v0.9.8-beta`. Historical
  release and validation records retain their original versions and scope.

The command count, dedicated Python entry points, one-message reply policy,
single companion connection, and service ownership of scheduling and subscriptions
remain unchanged. Recording introduces no command or operating-system service.

## Local distribution

Final release directory: `dist/github-release-v0.9.8-beta-20261029/`.

| OS archive | Target |
| --- | --- |
| `MC-EMS-Services-v0.9.8-beta-windows-x64.zip` | Windows 10/11 x64 |
| `MC-EMS-Services-v0.9.8-beta-linux-x86_64.tar.gz` | Debian 12+ or Ubuntu 24.04+ x86_64 |
| `MC-EMS-Services-v0.9.8-beta-raspberry-pi-arm64.tar.gz` | Raspberry Pi OS 64-bit, Bookworm or newer |

Each OS archive contains the matching native Installation and Maintenance
application, separate Service Setup application, service installer, and eight
dataset installers. Extract the complete archive and preserve the executable's
adjacent `_internal` directory. Linux/Pi tar archives preserve executable modes.

`RELEASE_NOTES.md`, `SHA256SUMS.txt`, and `VERIFICATION.zip` accompany the three
OS archives. The checksums identify delivered bytes; they do not establish
publisher authenticity. The [release verification record](docs/RELEASE_v0.9.8-beta_VERIFICATION.md)
identifies actual built artifacts, checks, environments, and remaining limits.

Service and dataset build outputs are kept under `dist/v0.9.8-beta/`.
Standalone service ZIPs contain platform source, launchers, tests, and guides;
reference datasets require independent installation. Maintained reference seeds
in a full source checkout do not make standalone packages complete data bundles.

## Installation and upgrade

Start with the [desktop installation guide](docs/DESKTOP_INSTALLATION.md) or the
[terminal installation guide](INSTALL.md). Install the reference collections
needed by the selected commands. Water collections follow their documented
dependency order. Installers require network access even when a reference seed
is included, because private Python environments and dependencies are provisioned
on the target.

Existing channel assignments and connection settings remain preserved. Commands
newly added to an existing registry require explicit assignments. A companion
must already expose the chosen USB serial, BLE, or TCP interface and matching
channels. BLE pairing remains an operating-system action.

Enable recording only when required, then review and apply the settings and
restart the service. Private keys remain in protected credential storage.
Committed history survives restart and expires by reception time; periods when
the service is unavailable are not reconstructed. See
[channel history configuration and access](meshcore_mqtt_service/CHANNEL_HISTORY.md).

## Verification limits

Local source tests, mocked failure cases, offscreen Qt checks, WSL execution,
QEMU ARM64 execution, archive inspection, and dependency checks establish only
their recorded scope. They do not establish physical radio delivery, native
Windows UAC or Linux/Pi polkit interaction, clean-host lifecycle and reboot,
BLE access under service accounts, or physical Raspberry Pi operation.

Windows binaries are unsigned unless the artifact record explicitly reports
signing. Provider availability and current observations remain independent of
offline tests. Optional channel history remains subject to finite storage,
queue, clock, and host-resource limits.

The [current release verification](docs/RELEASE_v0.9.8-beta_VERIFICATION.md),
[earlier installer results](installers/VALIDATION.md), and
[channel-history implementation record](docs/CHANNEL_HISTORY_VERIFICATION.md)
separate current evidence from earlier tested snapshots.
