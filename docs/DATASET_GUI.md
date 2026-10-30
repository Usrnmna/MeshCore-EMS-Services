# Editable dataset manager

Packaged desktop operation is described in the
[graphical installation and removal guide](DESKTOP_INSTALLATION.md).
The source and build commands below are developer procedures.

The default launch opens unified Installation and Maintenance, reusing the
Dataset Manager foundation. See [ownership and recovery](UNIFIED_INSTALLER.md).
The independent dataset interface remains available through `--datasets-only`;
the form-specific instructions below describe that interface.

The PyQt6 dataset manager provides checkbox selection, installation planning,
conservative removal, progress and logs for all eight reference collections.
Its ordinary Qt Widgets form is editable in Qt Creator. The interface uses the
existing dataset installers, maintenance launchers and native uninstallers.
Current backend capabilities are required for coordinated operations. Legacy
artifacts require an explicit current-artifact repair before those operations.
A GUI build does not install datasets or acquire provider data.

## Start from source

Python 3.11–3.13, a graphical desktop and the pinned GUI dependencies are required.
The GUI environment is separate from service and dataset maintenance environments.
Run these commands from the repository root.

Windows PowerShell:

```powershell
python -m venv .venv-dataset-gui
.\.venv-dataset-gui\Scripts\python.exe -m pip install -r installers/datasets/gui/requirements-build.txt
.\.venv-dataset-gui\Scripts\python.exe installers/datasets/gui/main.py --demo
```

Linux x86_64 or Raspberry Pi ARM64 with a desktop:

```sh
python3 -m venv .venv-dataset-gui
.venv-dataset-gui/bin/python -m pip install -r installers/datasets/gui/requirements-build.txt
.venv-dataset-gui/bin/python installers/datasets/gui/main.py --demo
```

`requirements.txt` is sufficient for running and editing; `requirements-build.txt`
also installs the executable packager. A compatible Qt wheel, system graphics
libraries and a desktop display are required on Linux/Pi. This is not a headless
Raspberry Pi interface. Native GUI availability must be checked on the target.
The desktop build pins PyQt6 6.7.1 and Qt 6.7.3, whose Linux x86_64 and ARM64
wheels use a glibc 2.28 baseline. This retains the Debian 12/Bookworm service
targets without requiring a newer operating system. Wheel metadata establishes
the binary baseline; desktop graphics, authorization and physical Raspberry Pi
operation still require native qualification. Python version alone is
insufficient to establish compatibility.

Demo mode generates states and operations in memory. It performs no native package
discovery, downloads, installation, deletion or privileged execution. Saving a log
is an explicit file export. Close the demo and omit `--demo` for real status:

```powershell
.\.venv-dataset-gui\Scripts\python.exe installers/datasets/gui/main.py --datasets-only --installers dist/v0.9.8-beta/datasets
```

Use `--root ABSOLUTE_PATH` to select a nondefault data root. The two editable path
fields also select the data root and existing installer directory. The source
launcher defaults to `dist/v0.9.8-beta`; the packaged executable defaults
to its own directory and discovers adjacent installer folders. Both can be changed in the GUI.
The native tools path and the package's recorded data root appear in row details.

## Select, review and execute

1. Select the data root and installer folder, then refresh status.
2. Check collection rows for selected-only operations, or choose an all-missing
   or uninstall-all action. The action produces a plan without changing data.
3. Read the Plan tab. It lists prerequisites, execution order, exact commands,
   artifact checksums, skipped items and blockers.
4. Resolve blockers. A batch with any blocker cannot execute.
5. Choose **Execute Reviewed Plan** and confirm the displayed collection list.
6. Review the Live log and Results tabs, then refresh status. **Save Log / Results**
   exports the current visible log and per-item results.

Status and planning run as the desktop user when files are readable. Executing a
reviewed plan requests native authorization for a separate worker: Windows UAC
or a Linux/Pi desktop polkit authentication agent. The Qt window remains in the
desktop session. Passwords are handled by the operating system's authorization
dialog. Missing authorization support or cancellation is reported without
claiming installation success. Stop EMS through the separate Service Setup
window before removing datasets; removal is blocked while a consumer is active
or its stopped state cannot be established.

### Meaning of each action

| Action | Behavior |
| --- | --- |
| Install Selected | Install selected missing data, set up absent tools, or explicitly repair incomplete tools with the matching existing installer; include missing prerequisites. Valid tools and data are skipped. |
| Uninstall Selected | Run the selected native uninstallers in reverse dependency order. Dependents outside the selection block removal. |
| Install All Missing Source Packages | Set up collections with no installed maintenance package. Existing setup also acquires or verifies initial data; tools-only setup is not supported. Damaged packages are reported separately. |
| Install All Missing Datasets | Use installed maintenance tools to acquire missing/incomplete data, or run setup when tools are absent. Include missing prerequisites. |
| Uninstall All Dataset Packages and Their Managed Data | Remove installed packages and active managed data in reverse dependency order, subject to all existing dependency and ownership protections. |

“Source package” means the existing collection's maintenance package. It does not
mean an independently installable provider, GIS layer or individual file. No new
subdataset lifecycle is introduced. Repeated installation verifies existing valid
data and does not update or downgrade it. Updates and rollback remain available
through the existing maintenance commands.

### Status and recovery

Package status uses the Windows machine uninstall record and `runtime.json`, or
Linux/Pi's published `current` runtime and `data-root.txt`. Payload identity,
private interpreter, manager and launcher files must be available. A directory
alone is not an installed package. Package readiness checks these records and
files; the actual operation's exit code and resulting records establish execution
success. It does not perform a package dependency repair or `pip check` during
status discovery.

Data status uses `datasets.json` and the existing recursive receipt/hash verifier.
Hashing large archives may take time; the window remains responsive. “Valid” means
the active managed generation matches its validation receipt, including pinned
prerequisite bytes. It does not mean observations are current or providers are
reachable. Existing source freshness rules still apply.

- **Missing:** no active managed data or no package registration.
- **Incomplete:** an acquisition failed without active data. Inspect its candidate
  identifier in row details. Install retries safely in a new candidate; explicit
  resume remains available through the existing CLI.
- **Unmanaged:** a legacy directory or selection has no verified receipt. An
  explicit installation may validate/import it while retaining the original.
- **Broken:** invalid records, altered active data or missing runtime files.
  **Install Selected** can repair tools using setup. Broken active data blocks
  installation; inspect the existing `verify`, `update`, `rollback` and resume
  commands described in `docs/DATA_PACKAGES.md` before choosing recovery.
- **Other root:** the selected root differs from the package's recorded root.
  Select the recorded root. The GUI does not migrate installations between roots.

An unreadable global activation registry aborts discovery. A failed update is
reported separately from still-valid active data. Uninstalled packages may retain
logs, modified files or unpublished candidates; those are not reported as installed
merely because their directories exist.

### Failure, cancellation and concurrency

The GUI rechecks package/data state and artifact hashes after confirmation. A
changed plan requires fresh review. Each zero exit code is followed by verification
of the expected package and data state. Failure stops remaining operations and
reports every unstarted item; completed packages are not automatically rolled back.

Cancellation takes effect **between packages**. The current installer/uninstaller
and its post-operation verification finish before the next item is skipped. The
application never terminates a process during activation. Closing is deferred while
a worker is active. The progress bar counts completed package operations; the log
shows acquisition details without inventing a download percentage.

GUI batches share `<native-tools-base>/.gui-manager.lock` across data roots. Existing
backend `.datasets.lock` protection remains authoritative during dataset mutations.
Do not run standalone setup or removal concurrently with a GUI batch: older native
wrappers do not share the GUI's batch lock during runtime provisioning. Interrupted
locks require inspection of their recorded PID and active processes before manual
removal; the GUI never steals locks.

Windows setup helper logs are followed from the existing package `logs` directory.
Maintenance and Linux/Pi output is streamed from the child process. The visible
log retains the latest 5,000 text blocks; native Windows logs remain on disk.
No purge option is enabled. Modified, unowned and legacy files retain the existing
uninstaller's protections. Dataset consumers must be stopped before removal.

## Edit the window in Qt Creator

Open `installers/datasets/gui/main_window.ui` in Qt Creator. Its integrated Qt
Widgets Designer opens the form in Design mode. The form uses standard widgets,
layouts and descriptive object names; no custom Designer plugin is required.

The `.ui` file is the maintained layout. PyQt6 loads it at runtime using
`uic.loadUi`; generated Python UI code is unnecessary. Save layout changes and
restart the source application to preview them. Retain object names used by
`window.py`, or update the corresponding controller references when renaming them.
Dataset rows are populated at runtime inside the Designer-editable `datasetTree`.

| File | Editing responsibility |
| --- | --- |
| `main_window.ui` | Window geometry, layouts, buttons, labels, tree and output tabs |
| `window.py` | Button connections, confirmation, background tasks and presentation |
| `catalog.py` | Display labels and descriptions; dependencies come from the existing manager |
| `discovery.py` | Native package records, installed-state checks and demo states |
| `planning.py` | Selection rules, dependency ordering and native command arguments |
| `execution.py` | Sequential child execution, logs, locking and cancellation boundaries |
| `main.py` | Command-line defaults and application startup |
| `tools/build_dataset_gui.py` | GUI packaging and optional reuse of existing installers |

To add a collection, first implement its existing native package/lifecycle support,
then add its display metadata and extend relevant tests. Do not add a checkbox for
a source that the backend cannot independently install.

For Qt Creator's project view, use **File → New Project → Import Project → Import
Existing Project** if available, selecting this checkout. Configure a custom run
executable as the virtual environment's Python with arguments
`installers/datasets/gui/main.py --demo` and the checkout as working directory.
Menu labels vary by Qt Creator version; opening the `.ui` directly is sufficient
for visual editing. No C++ compiler or CMake project is required for this GUI.
For a manual build inside Qt Creator, configure a custom build step with the same
environment Python as its executable, `tools/build_dataset_gui.py --output PATH`
as its arguments, and the checkout as its working directory. Use a new output
directory for each build. Visual form editing does not itself package an executable.

## Manually package the GUI

UI editing, UI loading and executable packaging are separate steps. Build only on
the intended target platform: Windows x64, Linux x86_64 or Raspberry Pi ARM64.
PyInstaller does not cross-compile these distributions. The output is a portable
directory and ZIP containing the GUI executable, its runtime resources, editable
form, source snapshot, build metadata and instructions. Extract the complete ZIP;
the executable depends on its adjacent `_internal` directory.

Windows:

```powershell
.\.venv-dataset-gui\Scripts\python.exe tools/build_dataset_gui.py
```

Linux/Pi:

```sh
.venv-dataset-gui/bin/python tools/build_dataset_gui.py
```

The default output is `dist/dataset-manager/<native-target>/`. Existing output
directories are not overwritten; use `--output PATH` for a new build directory.
Build dependencies are recorded in `BUILD.json` so the environment can be recreated.
On Windows the builder restricts its DLL-search PATH to the selected Python and
Windows directories. Qt hooks supply the Qt libraries; unrelated applications'
DLLs must not enter the bundle merely because their directories appear on PATH.

To make a single distributable directory containing the GUI and the **already
built** dataset installers for that target:

```powershell
.\.venv-dataset-gui\Scripts\python.exe tools/build_dataset_gui.py --installers dist/v0.9.8-beta/datasets --output dist/dataset-manager/windows-bundle
```

Use the Linux/Pi environment's Python for the same command on its native target.
The builder verifies `SHA256SUMS.txt`, copies the eight matching artifacts without
recompiling them, and writes a target-specific checksum list. Other OS installers
are excluded. With no `--installers` option, choose an external installer folder in
the GUI. Only artifacts needed by the planned setup operations must be present.
Keep one version of each collection per selected folder; ambiguous versions are
blocked rather than guessed. Checksums detect changed bytes; use a trusted local
release directory as the artifact source.

The GUI ZIP needs no separate system installation or uninstaller. Removing its
extracted directory removes the GUI only. Dataset installation remains owned by
the existing native package installers. Inno Setup and PS2EXE are therefore not
required to build the GUI. Rebuilding dataset installers is necessary only when
their own source/payload changes; see `installers/datasets/BUILD.md` in the main
checkout. Existing compiled dataset artifacts are not rewritten by this work.

## Verification

Run offline logic tests with the ordinary project Python, and widget tests with
the GUI environment's Python:

```powershell
python -m unittest discover -s tools -p test_dataset_gui.py -v
.\.venv-dataset-gui\Scripts\python.exe -m unittest discover -s tools -p test_dataset_gui_window.py -v
python -m unittest discover -s tools -p test_dataset_manager.py -v
python -m unittest discover -s tools -p test_dataset_adapters.py -v
python -m unittest discover -s tools -p test_data_installers.py -v
```

Linux/Pi use `.venv-dataset-gui/bin/python` for widget tests. The widget suite uses
Qt's offscreen platform and writes a preview under `.build/`. A source or packaged
demo startup check can also be run with `--demo --smoke-test`; set
`QT_QPA_PLATFORM=offscreen` when no visible window is desired. The smoke check only
checks the form and generated synthetic state, then exits. Unified maintenance
and Service Setup also exercise recording controls and the history viewer against
temporary fixtures. Optional `--smoke-report PATH` writes the structured result
and requires `--demo --smoke-test`. These checks do not discover or modify installed
services, access real history, or request native authorization.

The [October 26 hosted verification record](../installers/VALIDATION.md#hosted-github-actions-october-26-2026)
includes all six offscreen widget tests on both Windows and Ubuntu, alongside
the GUI core and dataset-manager suites.

Automated fixtures establish planning, state interpretation, cancellation and
failure reporting without using real provider data. They do not establish native
installation privileges, interactive desktop behavior on Linux/Pi, provider access,
or physical Raspberry Pi operation. The GUI's real install/remove actions must be
qualified separately on disposable native test hosts.

Design references: [Qt Creator form editing](https://doc.qt.io/qtcreator/creator-using-qt-designer.html),
[Qt worker threads](https://doc.qt.io/qt-6/qthread.html), and
[PyInstaller packaging](https://pyinstaller.org/en/stable/usage.html).

## Channel recording and viewing

[Channel history configuration and access](../meshcore_mqtt_service/CHANNEL_HISTORY.md)
covers the shared Windows/Linux/Raspberry Pi installer controls and read-only
viewer. Recording is an optional service feature; dataset-only mode retains its
reference-data scope. Reads do not start/stop services or apply pending edits.
