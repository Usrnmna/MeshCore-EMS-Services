# Building independent dataset installers

For the optional checkbox interface, see the [editable dataset GUI and manual
build guide](../../docs/DATASET_GUI.md). Its separate builder reuses existing
compiled dataset installers; it does not invoke this dataset build pipeline.

`tools/build_data_installers.py` creates one installer per collection and target.
The eight collections produce 24 separate artifacts; the main service installer
is not included in any dataset package.

| Target | Artifact suffix | Installed maintenance directory |
| --- | --- | --- |
| Windows x64 | `windows-x64-setup.exe` | `%ProgramFiles%\MeshCore-EMS-Data\<dataset>` |
| Linux x86_64 | `linux-x86_64.run` | `/opt/meshcore-ems-data/<dataset>` |
| Raspberry Pi ARM64 | `raspberry-pi-arm64.run` | `/opt/meshcore-ems-data/<dataset>` |

The dataset identifiers are `ebmud`, `basin_plans`, `flood_impacts`, `usgs_water`,
`wildfire`, `landslide`, `california_state_parks`, and `satellites`.
Each Windows package has its own stable Inno Setup `AppId` and executable
uninstaller. Each Linux/Pi package installs an executable `uninstall` script.

## Build commands

Run from the repository root with Python 3.11 or newer:

```powershell
Install-Module ps2exe -RequiredVersion 1.0.18 -Scope CurrentUser
python tools/build_data_installers.py
python tools/build_data_installers.py --dataset ebmud
python tools/build_data_installers.py --dataset ebmud --version v1.0.0
python tools/build_data_installers.py --linux-only
python -m unittest discover -s tools -p test_data_installers.py -v
```

Windows compilation requires Windows PowerShell 5.1, PS2EXE 1.0.18 and Inno Setup
6.7 or newer. The pinned PS2EXE version supplies executable-relative `ScriptRoot`
support; the builder fails if that version is unavailable. PS2EXE is required
only on the build host. Inno Setup's default location is
`.build/inno/ISCC.exe`; `--iscc PATH` selects another compiler. Builds create
isolated snapshots under `.build/data-installers-*` and write artifacts and
`SHA256SUMS.txt` to `dist/v0.9.8-beta/datasets/`. No service installation,
dataset refresh, or publishing occurs during a build. Rebuild after the last
change to any included maintenance source or reference seed.
`--version` permits an individual collection to receive a new release independently
of the service or other datasets; its output directory and package receipts use
that version.

The builder compiles `windows/dataset.ps1` once into `windows-tool/Dataset.exe`
within the isolated build directory, then supplies that executable to all eight
Windows installers. `windows-tool/BUILD.json` records the PS2EXE version and
source, compiler-script and executable hashes. The executable stays outside the
shared source payload and is not added to Linux/Pi archives. Builds retain
console output and real child exit codes; neither `-noConsole` nor output
suppression is enabled. This is executable packaging of inspectable PowerShell,
not source encryption or a replacement for the private Python dependencies.

Windows package names use readable collection labels. Shortcuts reside under
`MeshCore EMS/Datasets/<name>`. Upgrades retain stable AppIds and installation
paths, replace the old root `dataset.cmd`, and remove only the known obsolete
default shortcuts. Operator-created shortcuts are not enumerated or deleted.

Windows builds are unsigned by default. `--sign-tool 'NAME=COMMAND'` supplies an
Inno Setup signing command and enables signing for both setup and its generated
uninstaller. The command must use an available signing certificate and the Inno
Setup signing placeholders. Successful unsigned compilation does not establish
publisher identity or certificate validation.
The embedded `Dataset.exe` is unsigned by default as well; the Inno signing
option signs setup and its uninstaller, not the maintenance executable.

## Payload boundaries

The builder enumerates maintenance Python source and curated settings explicitly.
It includes the manager, adapters, collection maintenance tools, satellite
catalog source, and command helpers needed for validation and spatial indexing.
It excludes downloaded Basin Plan, flood, and USGS generations, local databases,
environment directories, main-service installers, and private operator state.

EBMUD, California State Parks, wildfire, and landslide packages carry their
published reference seeds, including source metadata and original files.
California State Parks includes native archives because its reference manifest
verifies them. Seed files retain their original bytes. Only shell scripts are
normalized to LF line endings. `PAYLOAD-MANIFEST.json` inventories packaged
file hashes, and `DATA-PACKAGE.json` records collection/release identity.

These are online installers: dependency bootstrap requires network access even
when a reference seed is bundled. Water collections and the initial satellite
catalog also require source acquisition. A build does not attest to source
availability, source freshness, or successful native OS installation.

## Runtime and removal

Windows downloads the checksum-pinned CPython 3.13.15 x64 NuGet runtime and
creates a private virtual environment. Linux/Pi uses Python 3.11-3.13 and
creates a private virtual environment; Debian-family systems can provision
Python/venv using apt when absent. Direct and transitive Python dependencies
are pinned in `requirements.txt`, and installers require binary wheels.
Each installation builds a new environment without modifying the selected
environment. Dependency failures never invoke data acquisition or deletion.

Default dataset roots are `%ProgramData%\MeshCore-EMS\data` and
`/var/lib/meshcore-ems/data`. Linux installation accepts `--root ABSOLUTE_PATH`;
Windows accepts `/DATAROOT="ABSOLUTE_PATH"`. Subsequent runs retain the saved
root when no override is supplied. Dataset storage must remain outside the
maintenance directory.

Installed maintenance examples:

```powershell
& 'C:\Program Files\MeshCore-EMS-Data\ebmud\Dataset.exe' status
& 'C:\Program Files\MeshCore-EMS-Data\ebmud\Dataset.exe' update
& 'C:\Program Files\MeshCore-EMS-Data\ebmud\Dataset.exe' verify
& 'C:\Program Files\MeshCore-EMS-Data\ebmud\Dataset.exe' rollback
```

```sh
sudo /opt/meshcore-ems-data/ebmud/dataset update
sudo /opt/meshcore-ems-data/ebmud/dataset verify
sudo /opt/meshcore-ems-data/ebmud/uninstall
```

The manager accepts a candidate identifier with `--resume` for interrupted
acquisition; the Windows wrapper exposes it as `-Resume`. Failed updates keep
the selected local generation unchanged. Data removal is delegated to the
manager's dependency and ownership checks. Tools are removed only after those
checks succeed. Default removal preserves modified and unowned local data.
Explicit purge uses Linux `uninstall --purge` or the Windows executable
uninstaller's `/PURGE=1` switch; purge remains constrained to receipt-owned
generations and does not bypass dependency checks.

## Artifact inspection and target qualification

### ARM64 desktop image plugins

The pinned Qt 6.7.3 ARM64 wheel's WebP/TIFF plugins reference older codec SONAMEs
that are absent from Bookworm. The desktop builder uses
`tools/build_arm64_image_plugins.py` to rebuild only those two plugins from the
checksum-pinned Qt 6.7.3 source and matching ARM64 SDK. The Qt/PyQt runtime pins
remain unchanged. Rebuilt plugins link to Bookworm's WebP and TIFF libraries;
their codec dependencies and redistribution notices accompany the application.
No compatibility symlink substitutes one library ABI for another.

An isolated ARM64 Debian 12 build environment requires `build-essential`,
`cmake`, `ninja-build`, `pkg-config`, `p7zip-full`, `binutils`, `patchelf`,
`libgl-dev`, `libegl-dev`, `libwebp-dev=1.2.4-0.2+deb12u1`, and
`libtiff-dev=4.5.0-6+deb12u4`. The existing native desktop build commands prepare
and reuse the checked plugin output. Download hashes, source locations, library
versions, and copied-file hashes are recorded with the GUI's build evidence.
The ARM64 preparation does not run for Windows or Linux x86_64 builds.

Release verification must decode fixed WebP and TIFF images through the actual
frozen applications and check dimensions and pixels. A supported-format listing
or dependency filename alone does not prove decoding. On ARM64, loaded plugin
and codec paths must belong to the extracted application. Run the final kit in
a clean Bookworm runtime without relying on its compiler/SDK environment.
QEMU execution provides emulation evidence, not physical Raspberry Pi validation.

### Installer payloads

Linux/Pi artifacts support inspection without administrator privileges or
installation:

```sh
bash MeshCore-EMS-Data-ebmud-v0.9.8-beta-linux-x86_64.run --check
bash MeshCore-EMS-Data-ebmud-v0.9.8-beta-linux-x86_64.run --extract empty-directory
```

Automated tests cover the separate artifact matrix, payload integrity,
download-only boundaries, seed isolation, and original-byte preservation.
Release qualification also requires Windows compilation, PowerShell/Bash syntax
checks, and compatible wheel resolution. Native lifecycle evidence is recorded in
[installer validation](../VALIDATION.md), including the Windows and Ubuntu WSL
test environments, service-account checks, injected failures and removal scope.
Archive inspection and cross-platform dependency resolution alone do not establish
native execution. Raspberry Pi qualification remains unavailable without an ARM64
test host.
