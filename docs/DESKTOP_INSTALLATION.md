# Desktop installation and removal

The desktop kit opens **Installation and Maintenance**, extending the PyQt6
Dataset Manager with one reviewed operation for datasets, services, shipped Python
programs and local integrations. Native package identities, maintenance runtimes,
installers and uninstallers remain independent. **Service Setup** remains available
as an independent fallback. The default configuration uses the bundled MQTT broker.

Use the kit matching Windows x64, Linux x86_64, or Raspberry Pi ARM64. A graphical
desktop, internet connection and administrator authorization are required. Kits
are online installers, including when some reference data is included. Native
Linux desktop authorization requires a working polkit session agent and `pkexec`.
Headless systems retain the separate [terminal installation path](../INSTALL.md).

## Select the current archive

The [v0.9.8-beta local release guide](../RELEASE_v0.9.8-beta.md) lists the Windows
x64 ZIP, Linux x86_64 tar archive, and Raspberry Pi ARM64 tar archive. Each OS kit
contains both desktop applications, its service installer, and eight independent
dataset installers. Local assembly does not establish publication or native
acceptance; inspect the [release verification record](RELEASE_v0.9.8-beta_VERIFICATION.md).

## Install from a desktop

1. Download the matching kit and extract the **whole** archive through the file
   manager. Keep each executable beside its `_internal` directory. Windows uses a
   ZIP; Linux/Pi use a tar archive that retains executable permissions.
2. Connect the MeshCore companion. USB serial with one supported device is the
   simplest default. Configure matching radio channels beforehand. BLE pairing
   remains an operating-system action; TCP requires an already configured node.
3. On Windows, open `dataset-manager/MeshCore-EMS-Dataset-Manager.exe`. On Linux
   x86_64 or Raspberry Pi ARM64, open `1-Installation.desktop`; a file manager may require
   **Allow Launching** through its graphical trust control. If a file manager
   supplies a URI rather than a local launcher filename, open the native
   executable inside `dataset-manager` directly instead. Adjacent installer
   folders and the standard shared data location are selected automatically.
4. In **Components**, select **Install / update / repair service package** and
   the required optional datasets. Confirm **Connections / credentials** and
   graphical channel references and application assignments. Choose the desired
   startup policy and whether to start after validation. Blank credential fields
   and unspecified settings preserve installed values.
5. Choose **Review selected operation**, inspect dependencies, retention and
   startup effects, then **Execute reviewed operation** and approve native
   authorization. Datasets precede service installation and configuration.
   A fresh service remains inactive and manual until the reviewed policy is applied.
6. Inspect status, **Diagnostics**, and **Recovery history**. Send `!status` from
   another node on an assigned channel. A running service alone does not prove
   radio reception. Test a dataset-backed command if that feature was selected.

The basic path uses one graphical application and one reviewed operation.
Protected discovery and native tools can require additional operating-system
authorization prompts. Typed terminal commands, Python installation, pip and
virtual-environment creation are not end-user steps. Vendor serial drivers,
Bluetooth pairing and physical device preparation can require additional actions.
No installer flashes firmware or changes node Wi-Fi.

Water prerequisites are selected automatically. Optional California State Parks
and satellite references are not required for ordinary channel commands. See
[dataset capabilities and lifecycle](DATA_PACKAGES.md) for collection details.

## Stop, remove or retain components

Reopen **Installation and Maintenance** to inspect status, stop/start the service,
inspect diagnostics, change settings or uninstall services. Uninstall retains service
configuration, credentials, runtime databases, backups and recovery material.
Shared operating-system dependencies and unrelated software remain installed.

Choose **Uninstall selected maintenance packages; retain datasets** for
non-destructive package removal. Active and rollback data and registry entries
remain discoverable; reinstall matching tools before further maintenance. Select
**Remove selected managed datasets and maintenance packages** only when those
datasets are explicitly intended for removal. Consumers stop first; unselected
dependents block removal. Modified, unowned and legacy files may remain. No purge
operation is offered. Older tools require repair with current artifacts before
coordinated maintenance; the interface does not claim to lock legacy installers.

**Disabled** changes service startup policy and stops the service. **Stop /
disconnect** releases connections without changing saved settings. **Deconfigure**
restores only unchanged interface-owned local settings, retains conflicting edits,
credentials and custom source files, and leaves the service stopped. It does not
reset devices. Dataset update/rollback and custom-program registration are
explicit reviewed operations. Recovery history records completed and unstarted
steps; cancellation never promises whole-operation rollback.

For an interrupted operation, inspect **Recovery history**, then use **Recover
interrupted maintenance**. Recovery requires evidence that the owner, participants
and potential native tools have exited. If a current dataset operation also left
a registry lock, select its package and **Recover a reviewed interrupted dataset
operation**. Unknown or legacy lock evidence remains blocked for administrator
investigation; data and recovery evidence are never discarded automatically.

See [ownership, integration and recovery contracts](UNIFIED_INSTALLER.md) for
backend capabilities, retained state and validation boundaries.

The applications can be reopened for maintenance. Deleting the extracted kit
removes its portable GUIs only; it does not uninstall services or datasets. Keep
the kit until maintenance no longer needs its applications and installers.

## Compatibility and verification limits

GUI dependencies use PyQt6 6.7.1, Qt 6.7.3 and SIP 13.10.0. Both Linux
architectures have `manylinux_2_28` PyQt6/Qt6 wheels, avoiding the glibc 2.39
baseline of newer ARM64 Qt wheels. Debian 12 and Raspberry Pi OS Bookworm use a
newer glibc than that wheel baseline. Python and PyInstaller build dependencies
still require native qualification: an application built against a newer host
glibc is not automatically portable to an older supported distribution.
Build Linux/Pi releases on the oldest supported native distribution or another
explicitly qualified build environment.
Kit assembly rejects Linux/Pi GUI builds recorded against glibc newer than 2.36,
or without a known glibc baseline. This prevents a newer-host validation build
from being packaged as a Debian 12/Bookworm-compatible desktop kit. Bundled ELF
dependencies and native desktop behavior still require qualification.

Official wheel metadata: [PyQt6 6.7.1](https://pypi.org/project/PyQt6/6.7.1/#files),
[Qt 6.7.3](https://pypi.org/project/PyQt6-Qt6/6.7.3/#files), and
[SIP 13.10.0](https://pypi.org/project/PyQt6-sip/13.10.0/#files).

Native graphical authorization, file-manager launch behavior, clean-host
installation/removal, reboot, BLE service-account access and physical radio
integration require validation on the target platform. Offscreen Qt, mocked
workers, WSL and archive inspection do not establish those behaviors.

## Developer packaging

These commands are build instructions, not end-user installation steps. Use a
native GUI build environment with `installers/datasets/gui/requirements-build.txt`
installed. PyInstaller does not cross-compile. Existing output directories are
never overwritten.

```text
python tools/build_dataset_gui.py --output dist/desktop-build/dataset
python tools/build_dataset_gui.py --service --output dist/desktop-build/service
python tools/build_installers.py
python tools/build_data_installers.py
python tools/build_desktop_kit.py --output dist/desktop-kits/NEW-TARGET-KIT --dataset-gui dist/desktop-build/dataset/MeshCore-EMS-Dataset-Manager --service-gui dist/desktop-build/service/MeshCore-EMS-Service-Setup
```

Use the native environment's Python and appropriate platform toolchain. Finish
source and documentation edits before building. GUI build inventories bind compiled
workers and bundled files to their source. Installer provenance sidecars bind
artifact hashes to all current build inputs. Kit assembly checks both inventories,
rejects stale/missing provenance, verifies target-specific installer checksums,
and writes a complete kit inventory and archive checksum. These local checks
establish byte integrity and freshness, not publisher authenticity.

## Channel recording and viewing

[Channel history configuration and access](../meshcore_mqtt_service/CHANNEL_HISTORY.md)
covers the shared Windows/Linux/Raspberry Pi installer controls and read-only
viewer. Recording is an optional service feature; dataset-only mode retains its
reference-data scope. Reads do not start/stop services or apply pending edits.
