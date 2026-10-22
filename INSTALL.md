# Install MeshCore EMS v0.9.6-beta as an OS service

After installation, use the [MeshCore user guide](meshcore_mqtt_service/BOT_USER_GUIDE.md) for channel commands and the [detailed command reference](meshcore_mqtt_service/COMMAND_REFERENCE.md#settings) for command settings, limits, and response formats. Equivalent [Windows user](meshcore_mqtt_service_windows/BOT_USER_GUIDE.md) and [command](meshcore_mqtt_service_windows/COMMAND_REFERENCE.md) guides are included in the Windows source package.

These **online service installers** include both platform source packages,
responder commands, tests, documentation and standalone satellite tools.
Reference datasets use [independent data installers](docs/DATA_PACKAGES.md),
with separate updates and uninstallers for each collection and platform.
The service installers automatically obtain Python and dependencies
during installation, including Skyfield for satellite positioning. Local development
environments, service databases, credentials, recovery archives, and distribution
ZIPs are excluded. The satellite catalog remains a standalone reference tool.
The maintained source includes all 31 commands and five local GIS
commands with focused subcommands. Install the EBMUD data package for GIS lookups. See
[GIS source deployment](#gis-source-deployment) for external settings and manual
updates. Neither GIS nor satellite refresh is scheduled automatically.

## Choose an installer

| File | Target |
| --- | --- |
| `MeshCore-EMS-v0.9.6-beta-windows-x64-setup.exe` | Windows 10/11 x64 |
| `MeshCore-EMS-v0.9.6-beta-raspberry-pi-arm64.run` | Raspberry Pi OS **64-bit**, Bookworm or newer, with systemd |
| `MeshCore-EMS-v0.9.6-beta-linux-x86_64.run` | Debian 12+ or Ubuntu 24.04+, Intel/AMD 64-bit, with systemd |

Outputs are under `dist/v0.9.6-beta/`, alongside `SHA256SUMS.txt`.
Each operating-system installer is distributed separately. Download only the
installer matching the target system; installation and validation guides are
available as separate files alongside the checksums.
The Linux packages are executable, self-extracting online installers; they install
the OS's native Python and dependency wheels for the target architecture. They
are not precompiled/frozen Python applications. Other Linux distributions and
32-bit Raspberry Pi OS are outside these installers' supported targets.

An internet connection and administrator/root permission are needed for installation.
Use a MeshCore Companion Node exposing the selected serial, BLE, or TCP interface.
For USB serial, connect it with its normal serial driver available.
Windows normally supplies USB CDC serial support; hardware needing a vendor-specific
driver must be recognized by Windows before automatic USB serial detection can find it. Setup does not
flash firmware or create channels on the radio. Configure the intended channels on
the node before starting; the default is `#autatestbot`. The separate setup utility
can explicitly provision empty radio slots. See the [multi-channel changes and
usage guide](meshcore_mqtt_service/MULTI_CHANNEL_GUIDE.md) for Public, hashtag, and
private channels, program assignments, and the deployment sequence.

## Windows x64

Installed Apps lists `MeshCore EMS Services`. Start menu entries share the
`MeshCore EMS` folder: Service guide, Service settings and Uninstall services.
Independent data packages appear under its `Datasets` subgroup with readable
collection names and a compiled `Dataset.exe` maintenance menu. See the
[dataset installation and recovery guide](docs/DATA_PACKAGES.md) for updates,
verification, rollback and separate removal.

Run the `.exe`, approve the administrator prompt, and choose the connection type.
The default preserves existing settings; a new installation uses USB serial `auto`.
Select USB serial with port `auto` to detect one USB device at every service start.
Enter a fixed COM port only when needed, such as when several USB serial devices
are attached. Optionally supply a channels JSON import file to define
several channels and program assignments. The channel-name field applies only to
a single-channel configuration and cannot be combined with an import. Setup
downloads a private CPython 3.13.15 runtime from the official
CPython NuGet package, checks its SHA-256, installs the pinned service dependencies
and Skyfield, validates configuration/imports, and registers `MeshCoreEMS`.
It uses the built-in .NET Framework Windows service host; no Python, pip, service
wrapper, or separate broker installation needs to be performed manually.

The service runs as **LocalService**, starts automatically with a delayed start,
and restarts after unexpected exits. Program files go under
`C:\Program Files\MeshCore-EMS`; writable settings/data go under
`C:\ProgramData\MeshCore-EMS`. Python is private to this application and does not
change the system Python or PATH. The installer is unsigned; it is not a signed
publisher release.

For unattended installation from an administrator terminal:

```bat
MeshCore-EMS-v0.9.6-beta-windows-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SERIALPORT=auto
```

Add `/NOSTART=1` to register without starting now (automatic startup remains enabled).
Add `/CHANNELSCONFIG="C:\Setup\channels.json"` to import a registry and assignments.
Private channel keys must exist in the protected `environment.json` before setup's
readiness check. For first installation, install defaults without starting, add
the keys, then rerun setup with the import and `/NOSTART=1`; verify radio channels
before starting. The linked multi-channel guide supplies the exact import format.
Use Windows Services to stop/start **MeshCore EMS Services**, or use administrator
PowerShell: `Restart-Service MeshCoreEMS`. Logs are `runtime\service.log` and
`runtime\wrapper.log` under ProgramData. Installation diagnostics are in
`ProgramData\MeshCore-EMS\install.log` and the Inno Setup log in the Windows temporary directory.
If dependency download/setup fails, fix the reported error and rerun the installer;
setup does not claim success for a failed dependency or service step.

The Start menu includes a settings shortcut; run the editor as administrator to
save changes. Uninstall through Windows Apps/Programs. ProgramData configuration,
credentials, reference data, and runtime databases are retained for recovery.

## TCP and Bluetooth LE setup options

Both installers configure the same connection settings used by the bridge,
local CLI commands, and channel setup tools. One transport is active at a time.
Omitting all connection options preserves existing settings during upgrades.
An explicit serial port selects serial; an IP selects TCP; a BLE address selects BLE.
Conflicting transport options are rejected. Changing transport clears the old
transport-specific fields. A fresh TCP selection defaults to port **5000**.

Windows wizard: select **Wi-Fi / TCP**, then enter the node IP and port; or select
**Bluetooth LE**, then enter its previously paired address. The default choice
preserves the installed connection. Unattended examples:

```bat
MeshCore-EMS-v0.9.6-beta-windows-x64-setup.exe /VERYSILENT /TRANSPORT=tcp /TCPHOST=192.168.1.50 /TCPPORT=5000
MeshCore-EMS-v0.9.6-beta-windows-x64-setup.exe /VERYSILENT /TRANSPORT=ble /BLEADDRESS=AA:BB:CC:DD:EE:FF /NOSTART=1
```

Direct PowerShell setup exposes `-Transport`, `-SerialPort`, `-TcpHost`, `-TcpPort`,
and `-BleAddress`. Pairing is performed through the OS, not the installer.
The Windows service runs as `NT AUTHORITY\LocalService`; verify Bluetooth access
under that account before relying on unattended BLE operation.

Linux (use the ARM64 filename on Raspberry Pi):

```bash
sudo bash MeshCore-EMS-v0.9.6-beta-linux-x86_64.run --transport tcp --tcp-host 192.168.1.50 --tcp-port 5000
sudo bash MeshCore-EMS-v0.9.6-beta-linux-x86_64.run --transport ble --ble-address AA:BB:CC:DD:EE:FF --no-start
```

For BLE, the Linux installer installs BlueZ and enables its service. Pair/trust
the node through `bluetoothctl` and verify D-Bus/Bluetooth access as `meshcore-ems`
before starting EMS. The service never chooses an arbitrary BLE device or prompts
for a PIN. A BLE adapter and compatible companion firmware are required.

TCP requires reachable companion firmware serving MeshCore TCP at the selected
IP/port; these settings do not configure node Wi-Fi. TCP is plain local-network
traffic, separate from the MQTT broker connection. Use a trusted LAN.
For JSON examples, timeouts, metadata, and reconnect behavior, see the
[connection guide](meshcore_mqtt_service/README.md#radio-connection-settings).
The offline readiness check validates settings/dependencies without opening a radio;
it cannot verify pairing, service-account Bluetooth access, or TCP reachability.

## Raspberry Pi ARM64 and Linux x86_64

Run the matching installer with Bash. Automatic USB serial detection is the default:

```bash
sudo bash MeshCore-EMS-v0.9.6-beta-raspberry-pi-arm64.run --port auto
# Intel/AMD:
sudo bash MeshCore-EMS-v0.9.6-beta-linux-x86_64.run --port auto
```

Use `--port auto` to rescan USB serial devices at each start. A new installation
defaults to serial `auto`. Omit connection options during an upgrade to preserve
the saved transport, endpoint, fixed serial port, and timeout.
For several attached USB serial devices, specify the intended `/dev/ttyACM*`,
`/dev/ttyUSB*`, or stable `/dev/serial/by-id/...` path. `--channels-config
/absolute/path/channels.json` imports a registry and program assignments. The
legacy `--channel NAME` override requires a single-channel configuration and cannot
be combined with the import. `--no-start` installs/enables without starting now.
For first installation with private channels, install defaults without starting,
populate the protected `environment.json`, then rerun with the import and
`--no-start`. Verify radio channels before starting.

Setup uses apt to install Python, venv/pip, certificates and build prerequisites,
then installs dependencies into a private virtual environment. It creates a
`meshcore-ems` system account with `dialout` access, installs a systemd unit,
enables startup at boot, and starts the service unless requested otherwise.

| Location | Contents |
| --- | --- |
| `/opt/meshcore-ems/releases/` | Installed workspace versions and virtual environments |
| `/opt/meshcore-ems/current` | Link to the selected installed version |
| `/etc/meshcore-ems/` | Config, optional credentials, satellite settings |
| `/var/lib/meshcore-ems/` | Runtime SQLite databases/logs and writable reference snapshots |

```bash
systemctl status meshcore-ems
journalctl -u meshcore-ems -f
sudo systemctl restart meshcore-ems
sudo bash /opt/meshcore-ems/current/installers/linux/uninstall.sh
```

Uninstall disables/removes the OS service and catalog shortcut while retaining
installed versions and data. OS dependencies are shared with other software and
are not removed. Upgrades preserve config, credentials and existing reference
snapshots, keep the previous installed program version, and do not reset flood
subscription expiry. Stop the service before manually restoring runtime data.

Inspect either Linux installer without installing or making system changes:

```bash
bash installer.run --check
bash installer.run --extract ./empty-directory
```

## Add programs without rebuilding the installer

Copy additional `.py` programs into `/etc/meshcore-ems/programs` on Linux or
`C:\ProgramData\MeshCore-EMS\programs` on Windows as administrator/root. These
protected directories survive upgrades. Register a command with
`"script": "programs/NAME.py"` and an explicit `channels` list in the active
configuration, validate it with `service_runner.py --check`, and restart the
service. No installer rebuild or reinstall is required. See the
[multi-channel guide](meshcore_mqtt_service/MULTI_CHANNEL_GUIDE.md#add-python-programs-after-installation)
for a commented program, exact paths, permissions, and check commands.

## Optional credentials and satellite tools

Edit `environment.json` in the installed configuration directory as administrator:

```json
{"AIRNOW_API_KEY": "REPLACE_WITH_AIRNOW_KEY"}
```

Among the lookup programs, only AirNow requires a key. Private MeshCore channels
also require shared keys named through `MESHCORE_CHANNEL_KEY_...` variables in this
file. Use 32 hexadecimal digits or Base64 encoding exactly 16 bytes; put only the
variable name in the channel's `secret_env` configuration. Optional external MQTT credentials use
`MESHCORE_MQTT_USERNAME` and `MESHCORE_MQTT_PASSWORD` in that same file. Restart
after changing settings. The bundled broker remains bound to localhost, using
the existing platform ports (Windows 1884; Linux 1883).

Each channel explicitly sets `mqtt_export`; use `false` for private text unless
export to MQTT is intended. The local runtime database still contains decrypted
requests/results. Linux installers restrict configuration JSON to
`root:meshcore-ems` mode `0640` and runtime files to the service account. Windows
restricts ProgramData settings/state to SYSTEM, Administrators, and LocalService,
with LocalService write access to runtime/data. Keep these restrictions when
editing or restoring files. Configuration/database backups precede installed
configuration changes; see the multi-channel guide for their locations and manual
rollback steps. Configuration and program-assignment edits require a restart.

Both installed and source-folder services support `serial_port: "auto"`. Detection
uses USB device metadata and selects exactly one supported serial candidate; zero
or multiple candidates produce a clear error instead of guessing. The actual
port is resolved again at every service start/restart, so a changed COM number
does not require editing an `auto` configuration. This is port discovery, not a
firmware identification scan. An explicit fixed port remains available. The
offline `service_runner.py --check` validates the setting without probing USB.
Linux handles SIGTERM and Windows sends a stop request so the bridge can close
SQLite, MQTT and radio resources. The service manager restarts a failed process.

Satellite lookup examples (run with permission to read the installed state):

```bash
sudo -u meshcore-ems meshcore-satellites summary
sudo /opt/meshcore-ems-data/satellites/dataset update
```

On Windows, use an administrator terminal:

```bat
"C:\Program Files\MeshCore-EMS\installers\windows\satellite-catalog.cmd" summary
```

Refreshing the satellite catalog is an explicit operation. Existing snapshots are
not overwritten during a service upgrade. Managed snapshots are updated only
through their independent dataset package. Installed snapshot age and source coverage
still limit their usefulness; inclusion is not proof of current RF reception.

## GIS source deployment

Current source contains 31 commands. The five GIS commands are `!trail`,
`!rec`, `!peak`, `!park`, and `!boundary`. Service installers and ZIPs include their
programs and settings. The independent EBMUD data installer supplies twelve
datasets and preserved polygon-repair originals. Manual source updates must update the deployed
application and its active configuration together.

A fresh deployment discovers the EBMUD data package through the persistent
dataset registry. Source checkouts without a registry entry retain the
`../data/ebmud` default. Explicit external GIS settings remain authoritative.
Service upgrades do not copy or overwrite reference data. Existing command definitions are preserved
on upgrade; merge any older GIS dispatcher definitions and the dedicated
`floodalarm.py` registration as described below. Commands newly added to an
existing channel registry start without channel assignments and require explicit
assignment before use. External GIS settings survive application replacement;
manual edits to the bundled settings template can be overwritten.

1. Stop the service and retain a recoverable copy of its program files, active
   configuration, GIS settings, and data before replacing them.
2. Deploy the matching platform's current `responder.py`, `scripts/gis_data.py`,
   `scripts/gis_spatial.py`, `scripts/gis_lookup.py`, the five dedicated programs
   `scripts/trail.py`, `rec.py`, `peak.py`, `park.py`, `boundary.py`,
   `scripts/floodalarm.py` for the alarm monitor, `gis_settings.json`, and
   `requirements.txt`. The updated responder recognizes `gis_query`; copying only
   the lookup scripts into an old release is insufficient.
3. Install the current platform requirements using the service interpreter below.
   Shapely and pyproj are required in that interpreter, including for name searches.
4. Supply the complete `data/ebmud` directory, including `sources.json`, its twelve
   referenced datasets, and preserved originals/repair metadata when using repaired
   snapshots. Keep maintenance scripts and the data README alongside it for manual
   refresh and repair. Stop maintenance during deployment; do not copy active locks
   or unresolved recovery directories into the destination.
5. Set `data_directory` in `gis_settings.json` to the deployed data directory.
   The default `../data/ebmud` is relative to the settings file, not to the runner's
   external `config.json`. An absolute path is recommended for installed services.
6. Merge the five definitions from the matching source `config.json` into the active
   `responder.commands`. For `!floodalarm`, set `script` to `scripts/floodalarm.py`
   with an empty `args` list; its subscription settings remain unchanged.
   Preserve existing connection, MQTT, credentials, timezone,
   and command settings. Assign explicit IDs from the installed channel registry.
7. Run the runner's offline configuration check from the
   [multi-channel guide](meshcore_mqtt_service/MULTI_CHANNEL_GUIDE.md#add-python-programs-after-installation),
   then exercise the GIS CLI below with the same settings and service account.
   The runner check alone does not establish dataset integrity or spatial results.
   Restart and verify replies on the permitted channels.

| Item | Linux installed default | Windows installed default |
| --- | --- | --- |
| Service folder | `/opt/meshcore-ems/current/meshcore_mqtt_service` | `C:\Program Files\MeshCore-EMS\meshcore_mqtt_service_windows` |
| Interpreter | `/opt/meshcore-ems/current/.venv/bin/python` | `C:\Program Files\MeshCore-EMS\python\python.exe` |
| Active config | `/etc/meshcore-ems/config.json` | `C:\ProgramData\MeshCore-EMS\config.json` |
| External GIS settings (manual setup) | `/etc/meshcore-ems/gis_settings.json` | `C:\ProgramData\MeshCore-EMS\gis_settings.json` |
| Writable GIS data | `/var/lib/meshcore-ems/data/ebmud` | `C:\ProgramData\MeshCore-EMS\data\ebmud` |

The current installer configuration utility does not create, relocate, or merge
`gis_settings.json`. For external GIS settings, copy the source template to the
chosen path and add `--settings` and that absolute path to **each** dedicated GIS
command's `args`. Point each registration to its own `scripts/COMMAND.py` file. For example:

```json
["--settings", "/etc/meshcore-ems/gis_settings.json"]
```

The equivalent Windows path in JSON is
`"C:\\ProgramData\\MeshCore-EMS\\gis_settings.json"`.
Keep settings readable by the service account and writable only by administrators.
The service needs read access to the datasets; the maintenance account needs write
access. Installer upgrades replace bundled application files. Retain external settings
and verify deployed command definitions and channel assignments after an upgrade.

Linux dependency installation and offline example, after copying files/settings:

```bash
sudo /opt/meshcore-ems/current/.venv/bin/python -m pip install -r /opt/meshcore-ems/current/meshcore_mqtt_service/requirements.txt
sudo -u meshcore-ems /opt/meshcore-ems/current/.venv/bin/python /opt/meshcore-ems/current/meshcore_mqtt_service/scripts/trail.py --settings /etc/meshcore-ems/gis_settings.json "Bear Creek"
```

Windows dependency installation and offline example, from administrator PowerShell:

```powershell
& 'C:\Program Files\MeshCore-EMS\python\python.exe' -m pip install -r 'C:\Program Files\MeshCore-EMS\meshcore_mqtt_service_windows\requirements.txt'
& 'C:\Program Files\MeshCore-EMS\python\python.exe' 'C:\Program Files\MeshCore-EMS\meshcore_mqtt_service_windows\scripts\trail.py' --settings 'C:\ProgramData\MeshCore-EMS\gis_settings.json' 'Bear Creek'
```

An administrator CLI result does not prove LocalService file access. Verify that
account's permissions before relying on unattended operation. Source-folder
deployments use their `.venv-linux` or `.venv` interpreter instead. See the
[Linux](meshcore_mqtt_service/README.md#local-gis-commands) and
[Windows](meshcore_mqtt_service_windows/README.md#local-gis-commands) guides for
syntax, tuning limits, snapshot checks, and interpretation. GIS subcommands
require the updated `gis_data.py`, `gis_lookup.py`, and `gis_spatial.py` helpers
in both source packages, plus the current responder for argument-free help.
Dedicated command registrations remain unchanged. Older `default_radius_miles`
settings are ignored and can be removed; no-radius queries now return only the
closest match. Explicit radii still use `maximum_radius_miles`. Data maintenance is
manual; [refresh and repair instructions](data/ebmud/README.md#manual-refresh)
apply to the deployed copy of the data directory. They do not rebuild artifacts.

## Lightning command and timezone

`!lightning` uses NWS point alerts and thunderstorm/dry-lightning forecasts for the
next 24 hours. It reports stated probabilities, including slight chance, rather
than observations of individual strikes. Coverage and complete usable input are
required for a no-lightning result. See the
[command guide](meshcore_mqtt_service/README.md#lightning-potential-lightning).

Set the one `responder.timezone` value in the active configuration to an IANA name,
such as `America/Los_Angeles`, and restart. The responder exports `MESHCORE_TIMEZONE`
to all programs; clock, AQI, river, and lightning output use that setting. The
installed configuration merger preserves it on upgrade. Provider text with its
own timezone is labeled separately. Install the current `requirements.txt` for
the pinned `tzdata` dependency. No per-command timezone setting is required.

## Heat command source update

`!heatadv` accepts US GPS, ZIP, or city/state locations, preserves supplied
location wording, and reports every active NWS extreme heat warning, watch, or
heat advisory. Failed or incomplete requests are not reported as no advisories.
The [heat guide](meshcore_mqtt_service/README.md#heat-alerts-heatadv) gives exact
responses, standalone usage, and coverage limitations.

The recorded October 8 build includes heat, lightning, and shared timezone support.
For an older deployment, deploy the matching current service source and requirements,
merge the corresponding command definitions, and restart after offline checks.
Existing registries leave newly merged installer commands disabled until channel IDs
are assigned. Preserve existing settings; replacing the active configuration with
the source template would discard deployment-specific values.

## Build and validation

Repository layout, source packaging, dependency references, and offline checks are
described in the [development guide](docs/DEVELOPMENT.md). The
[architecture guide](docs/ARCHITECTURE.md) covers component responsibilities and
MQTT topics; the [documentation index](docs/README.md) groups the remaining guides.

From the workspace, with Python and Inno Setup 6.7+ available on the Windows build host:

```console
python tools/build_installers.py --iscc PATH_TO_ISCC.exe
```

The builder compiles the x64 Windows SCM host using the .NET Framework compiler,
builds the Windows setup executable and both Linux self-extracting archives,
includes a per-file payload manifest, and writes release checksums. Use
`--linux-only` to build the two Linux installers without Windows tools.

Build, extraction, configuration and lifecycle tests do not prove a successful
administrator installation, native Raspberry Pi operation, serial driver support,
or radio delivery. A running service process does not prove that a remote node
received a response. See the build validation report shipped with the release
artifacts for the checks actually performed.

Upstream packaging references: [CPython NuGet packages](https://docs.python.org/3.13/using/windows.html#the-nuget-org-packages),
[Inno Setup](https://jrsoftware.org/isinfo.php), and
[systemd service units](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).


## Wildfire deployment

The nine wildfire commands are included in both service ZIPs and installers.
Install the independent wildfire data package for the checksummed full-zone seed.
Fresh configurations assign the commands
to the default channel. On upgrades, missing commands are added with empty
channel assignment lists when a registry already exists; select assignments
before restarting. Existing `responder.wildfire` values are preserved.

The running service owns background refresh and monitoring. Its writable state
contains `runtime/wildfire.sqlite3`; subscriptions use `runtime/bridge.sqlite3`.
No separate scheduler or OS service is required. Provider access uses public
HTTPS sources. Failed refreshes preserve previous data and report degraded
freshness; startup may need several passes to initialize every configured feed.

See [wildfire settings, refresh/export commands and sources](meshcore_mqtt_service/WILDFIRE_GUIDE.md).
Assign `!firealarm` only where monitoring is desired. A standalone execution
never creates a subscription. Existing flood-monitor behavior is unchanged.


Generated basin-plan, flood-impact and USGS-water downloads follow the existing
root `.gitignore` download-on-demand policy and are excluded from installer
payloads. Their maintained tools, documentation and curated inputs remain
included; locally acquired datasets are retained on disk. See [water-data setup](docs/WATER_DATA_SETUP.md).

The point commands `!smoke` and `!firedanger` require channel assignment on
upgrades. Public smoke/air-quality/ERC data need no new credentials. Optional
detailed FEMS fuel moisture requires service-account environment credentials
and configured station IDs; see [FEMS setup](meshcore_mqtt_service/WILDFIRE_GUIDE.md#optional-fems-fuel-moisture).

## Landslide command deployment

Both standalone service packages include `landslide_service.py`, dedicated
`slidewarn.py`, `slidealarm.py`, and `slideinfo.py` programs, shared helpers,
and shared data-discovery code. Install the independent landslide data package
for the checksummed reference files. Deploy the updated responder
and channel-state handling together. Existing installations preserve
`responder.landslide` settings and existing assignments; new commands are
unassigned on an existing channel registry. Assign the three commands to the
desired channel IDs, validate configuration, and restart. No additional API key,
OS service, or dependency is required beyond the current package requirements.
[Configuration and command guide](meshcore_mqtt_service/LANDSLIDE_GUIDE.md).

## Location water and flood command deployment

The maintained source registers 31 commands. Water additions are `!waterway`,
`!basin`, and `!floodstatus`; `!floodwarn` and `!floodalarm` use the same
location-pinned source helpers. Deploy the matching platform responder, flood
worker, all `scripts/water_*.py` helpers, dedicated command programs, curated
`WATER_STATION_REVIEW.json`, and the current requirements together. Keep channel
and transport settings and runtime state recoverable before replacing files.

Older installed registrations remain operator-managed. Merge current water
registrations from the matching source `config.json`, including `input: water_query`,
a dedicated script, the 90-second timeout, and one reply part. The responder enforces one
150-byte tagged response even if an older installed configuration specifies more parts. Preserve
existing assignments; commands added to an existing registry require explicit
permitted channel IDs. Configure the documented `responder.water` settings when
custom values are required, validate offline, and restart after changes.

For local geographic and gauge context, follow [water-data acquisition and index
setup](docs/WATER_DATA_SETUP.md). Downloaded water collections and runtime indexes
are excluded from installation payloads. Set an absolute
`responder.water.data_directory` for separately deployed data, then build schema-2
`runtime/water_index.sqlite3` with the service interpreter and account. The default
`../data` is relative to the package, not the active external configuration file.
Identifier review can be refreshed independently and does not rebuild geometry.

`!floodalarm LOCATION` enrolls official-alert monitoring; `conditions LOCATION`
adds supported categorical conditions, `status` inspects, and `stop` cancels.
Default checks occur every five minutes for four hours. Accepted enrollment pins
one resolved point and requires a successful official-alert baseline before
acknowledgment. Source availability, permissions, deadlines, and recipient delivery
remain separate validation boundaries. See [complete water behavior, retention,
and sources](meshcore_mqtt_service/WATER_GUIDE.md) and the
[terminal option index](docs/CLI_REFERENCE.md).
