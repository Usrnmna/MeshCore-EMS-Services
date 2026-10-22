# Version 0.9.6 - Beta

Release identifier: `v0.9.6-beta`. Build date: October 21, 2026.

This distribution packages the current source with 31 dedicated MeshCore command
programs in each platform package. It includes the water commands, flood alert
lifecycle handling, wildfire and landslide monitoring, and concise tagged replies
documented in the [command reference](meshcore_mqtt_service/COMMAND_REFERENCE.md)
and [response examples](meshcore_mqtt_service/RESPONSE_EXAMPLES.md).

## Included behavior and upgrade considerations

- Command replies fit one tagged message of at most 150 UTF-8 bytes. Priority
  information and material uncertainty precede optional fields. Full supported
  structured records remain available through local JSON and snapshot interfaces.
- Flood notifications retain independent lifecycle and uncertainty states, with
  priority ordering and a five-second minimum gap. Shared radio command spacing
  defaults to five seconds; contention and transmission time can add delay.
- Water collection programs and maintained configuration are included. Generated
  Basin Plan, flood-impact and USGS downloads remain local and require the
  [independent dataset installers](docs/DATA_PACKAGES.md).
- All eight reference collections have separate Windows x64, Linux x86_64 and
  Raspberry Pi ARM64 installers and uninstallers. Updates validate an isolated
  candidate before activation; failed acquisition retains the selected local
  dataset. Main service installation and removal preserve independent datasets.
- Persistent subscriptions remain service-owned. Standalone command invocation
  does not create a subscription.
- Windows dataset maintenance uses a PS2EXE-compiled `Dataset.exe` with a console
  menu and scriptable actions. Readable dataset names and grouped Start menu
  shortcuts simplify access; package IDs, data paths and preservation rules remain
  unchanged. Setup and removal retain their native Inno Setup executables.

Upgrades preserve existing configuration and channel assignments. Assign any
newly available commands to the intended channels and restart the service.
Existing configurations retain their radio spacing; set `command_interval` to
`5` explicitly to use the current default. Refer to the
[installation guide](INSTALL.md) and platform release notes for configuration details.

## Packages and installers

| Artifact | Target |
| --- | --- |
| `meshcore_mqtt_service.zip` | Linux source package, including Raspberry Pi ARM64 |
| `meshcore_mqtt_service_windows.zip` | Windows source package |
| `MeshCore-EMS-v0.9.6-beta-windows-x64-setup.exe` | Windows 10/11 x64 |
| `MeshCore-EMS-v0.9.6-beta-linux-x86_64.run` | Debian 12+ or Ubuntu 24.04+ x86_64 with systemd |
| `MeshCore-EMS-v0.9.6-beta-raspberry-pi-arm64.run` | Raspberry Pi OS 64-bit, Bookworm or newer, with systemd |

The three online installers are distributed separately under `dist/v0.9.6-beta/`.
The 24 independent data installers are under its `datasets/` directory, with a
separate `SHA256SUMS.txt`. The dataset guide identifies required collections,
dependency order, custom data roots, update/rollback commands and removal rules.
Both source ZIPs and their individual SHA-256 files are also copied there for a
self-contained release inventory; current ZIPs remain available under `dist/`.
No combined installer archive is produced. Each source package contains
`VERSION.txt`; Windows assembly and file versions use `0.9.6.0`.

`SHA256SUMS.txt` covers the three installers. `RELEASE-ASSET-SHA256SUMS.txt`
covers the release artifacts, documentation, and verification record, excluding
the checksum inventory itself. `VERIFICATION.json` records actual test results,
artifact hashes, source comparisons, and verification limits. Its companion
`VERIFICATION.json.sha256` identifies that report.

Installers obtain runtime dependencies online. Standalone source packages need
shared reference data separately for local GIS queries. Runtime state, private
configuration, environments and generated water downloads are excluded.

## Verification boundaries

The [validation record](installers/VALIDATION.md) distinguishes offline tests,
artifact inspection and actual Windows/Ubuntu WSL lifecycle checks. Its native
qualification section records installed service-account reads after failed data
updates and ownership-aware removal. No Raspberry Pi host was available. Services
were installed without starting the radio bridge; reboot recovery, physical radio
delivery and current provider availability remain unverified. The Windows
installer is unsigned. This local rebuild does not publish a GitHub release.
