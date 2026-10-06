# Install MeshCore EMS v0.3.0-beta as an OS service

These **online installers** include the complete maintained workspace: both
platform source packages, all nine responder commands, tests and documentation,
the standalone satellite catalog, EBMUD GeoJSON, and the supplied satellite
database/source snapshots. They automatically obtain Python and dependencies
during installation, including Skyfield for satellite positioning. Local development
environments, service databases, credentials, recovery archives, and distribution
ZIPs are excluded. The catalog and GIS data remain reference tools, not new radio
commands or automatically scheduled refresh jobs.

## Choose an installer

| File | Target |
| --- | --- |
| `MeshCore-EMS-v0.3.0-beta-windows-x64-setup.exe` | Windows 10/11 x64 |
| `MeshCore-EMS-v0.3.0-beta-raspberry-pi-arm64.run` | Raspberry Pi OS **64-bit**, Bookworm or newer, with systemd |
| `MeshCore-EMS-v0.3.0-beta-linux-x86_64.run` | Debian 12+ or Ubuntu 24.04+, Intel/AMD 64-bit, with systemd |

Outputs are under `dist/v0.3.0-beta/`, alongside `SHA256SUMS.txt`.
All three installers and the guides are also in
`dist/MeshCore-EMS-v0.3.0-beta-installers.zip`, with a separate bundle checksum.
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
MeshCore-EMS-v0.3.0-beta-windows-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SERIALPORT=auto
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
`ProgramData\MeshCore-EMS\install.log` and the Inno Setup log in your temp folder.
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
MeshCore-EMS-v0.3.0-beta-windows-x64-setup.exe /VERYSILENT /TRANSPORT=tcp /TCPHOST=192.168.1.50 /TCPPORT=5000
MeshCore-EMS-v0.3.0-beta-windows-x64-setup.exe /VERYSILENT /TRANSPORT=ble /BLEADDRESS=AA:BB:CC:DD:EE:FF /NOSTART=1
```

Direct PowerShell setup exposes `-Transport`, `-SerialPort`, `-TcpHost`, `-TcpPort`,
and `-BleAddress`. Pairing is performed through the OS, not the installer.
The Windows service runs as `NT AUTHORITY\LocalService`; verify Bluetooth access
under that account before relying on unattended BLE operation.

Linux (use the ARM64 filename on Raspberry Pi):

```bash
sudo bash MeshCore-EMS-v0.3.0-beta-linux-x86_64.run --transport tcp --tcp-host 192.168.1.50 --tcp-port 5000
sudo bash MeshCore-EMS-v0.3.0-beta-linux-x86_64.run --transport ble --ble-address AA:BB:CC:DD:EE:FF --no-start
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
sudo bash MeshCore-EMS-v0.3.0-beta-raspberry-pi-arm64.run --port auto
# Intel/AMD:
sudo bash MeshCore-EMS-v0.3.0-beta-linux-x86_64.run --port auto
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
{"AIRNOW_API_KEY": "your-key"}
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
sudo -u meshcore-ems meshcore-satellites refresh
```

On Windows, use an administrator terminal:

```bat
"C:\Program Files\MeshCore-EMS\installers\windows\satellite-catalog.cmd" summary
```

Refreshing the satellite catalog is an explicit operation. Existing snapshots are
not overwritten during an upgrade. Installed snapshot age and source coverage
still limit their usefulness; inclusion is not proof of current RF reception.

## Build and validation

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
