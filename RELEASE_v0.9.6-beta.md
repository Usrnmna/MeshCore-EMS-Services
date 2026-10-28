# MeshCore EMS v0.9.6-beta

Release packages refreshed October 27, 2026.

MeshCore EMS connects MeshCore channels to environmental information and monitoring services, with water commands, flood alerts, wildfire and landslide monitoring, and concise tagged replies.

## Choose one download

| Operating system | Unified installer package |
| --- | --- |
| Windows 10/11, 64-bit | `MeshCore-EMS-v0.9.6-beta-Windows-x64.zip` |
| Debian 12+ or Ubuntu 24.04+, x86_64 | `MeshCore-EMS-v0.9.6-beta-Linux-x86_64.tar.gz` |
| Raspberry Pi OS 64-bit, Bookworm or newer | `MeshCore-EMS-v0.9.6-beta-Raspberry-Pi-ARM64.tar.gz` |

Each archive contains the unified graphical **Installation and Maintenance** application, its service installer, all eight optional dataset installers, and installation guides. Service Setup remains available inside the archive as an independent fallback. Dataset selection and maintenance use the included tools.

## Install

1. Download the archive matching the operating system and extract the **entire** archive. Keep executables beside their supporting folders.
2. Open the extracted folder. On Windows, launch `dataset-manager/MeshCore-EMS-Dataset-Manager.exe`. On Linux or Raspberry Pi, open `1-Installation.desktop` and use the file manager's **Allow Launching** action if required.
3. Select the service and required datasets, confirm connections, credentials, channel assignments and startup settings, then review the operation, execute it and approve the operating-system authorization prompt.

A graphical desktop, internet access and administrator authorization are required. Linux/Pi require systemd and a working polkit session agent with `pkexec`. Runtime dependencies and some data are downloaded during installation. Companion radio channel preparation, physical connections and Bluetooth pairing remain separate device or operating-system steps. Detailed instructions are included in `START-HERE.md` and the archive's `docs/` folder.

## Included behavior and upgrades

- Each platform provides 31 dedicated MeshCore command programs. Tagged command replies fit at most 150 UTF-8 bytes; supported structured records remain available through local JSON and snapshot interfaces.
- Flood notifications retain independent lifecycle and uncertainty states, priority ordering and a five-second minimum gap. Shared command spacing defaults to five seconds; transmission and contention can add delay.
- Water collection programs and maintained configuration are included. Basin Plan, flood-impact and USGS downloads remain local; select their dataset components in the unified interface.
- Eight reference collections retain independent installers, uninstallers and update lifecycles. Updates validate a candidate before activation; failed acquisition retains the selected dataset. Main service installation and removal preserve independent datasets.
- Persistent scheduling and subscriptions remain service-owned. Standalone lookups do not create subscriptions. Windows dataset maintenance retains its compiled `Dataset.exe` console menu, scriptable actions and native setup/removal tools.

Upgrades preserve existing configuration and channel assignments. Assign new commands to the intended channels and restart the service. Existing configurations retain their radio spacing; `command_interval` must be set to `5` explicitly to adopt the current default. This rebuild also corrects Windows-generated installer metadata line endings so payload hashes match the actual bytes.

## Checksums and verification

`SHA256SUMS.txt` covers the three OS archives, these notes and `VERIFICATION.zip`. The verification ZIP contains the recorded build results, source provenance and detailed test evidence. These extra files are optional for installation.

The October 27 rebuild recorded 3,638 passed and 52 skipped test executions, with no failures or errors in the selected final runs. Packaged demo startup and archive inventories passed. Windows installers are unsigned. ARM64 builds and checks used QEMU emulation; physical Raspberry Pi operation remains unverified. Native privilege prompts, clean-system installation/removal, reboot, live providers, external MQTT and physical device/radio integration remain unverified for this rebuild. Optional ARM64 WebP/TIFF image-plugin dependencies also remain unqualified; details are in the verification ZIP.
