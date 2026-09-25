# Install MeshCore EMS v0.2.0-alpha as an OS service

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
| `MeshCore-EMS-v0.2.0-alpha-windows-x64-setup.exe` | Windows 10/11 x64 |
| `MeshCore-EMS-v0.2.0-alpha-raspberry-pi-arm64.run` | Raspberry Pi OS **64-bit**, Bookworm or newer, with systemd |
| `MeshCore-EMS-v0.2.0-alpha-linux-x86_64.run` | Debian 12+ or Ubuntu 24.04+, Intel/AMD 64-bit, with systemd |

Outputs are under `dist/v0.2.0-alpha/`, alongside `SHA256SUMS.txt`.
All three installers and the guides are also in
`dist/MeshCore-EMS-v0.2.0-alpha-installers.zip`, with a separate bundle checksum.
The Linux packages are executable, self-extracting online installers; they install
the OS's native Python and dependency wheels for the target architecture. They
are not precompiled/frozen Python applications. Other Linux distributions and
32-bit Raspberry Pi OS are outside these installers' supported targets.

An internet connection and administrator/root permission are needed for installation.
Connect a MeshCore USB Companion Node with its normal serial driver available.
Windows normally supplies USB CDC serial support; hardware needing a vendor-specific
driver must be recognized by Windows before selecting its COM port. Setup does not
flash firmware or create channels on the radio. Configure the intended channel on
the node first; the existing default is `#autatestbot`.

## Windows x64

Run the `.exe`, approve the administrator prompt, and enter the Companion's COM
port (for example `COM11`). Enter a channel only to override the current/default
channel. Setup downloads a private CPython 3.13.15 runtime from the official
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
MeshCore-EMS-v0.2.0-alpha-windows-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SERIALPORT=COM11
```

Add `/NOSTART=1` to register without starting now (automatic startup remains enabled).
Use Windows Services to stop/start **MeshCore EMS Services**, or use administrator
PowerShell: `Restart-Service MeshCoreEMS`. Logs are `runtime\service.log` and
`runtime\wrapper.log` under ProgramData. Installation diagnostics are in
`ProgramData\MeshCore-EMS\install.log` and the Inno Setup log in your temp folder.
If dependency download/setup fails, fix the reported error and rerun the installer;
setup does not claim success for a failed dependency or service step.

The Start menu includes a settings shortcut; run the editor as administrator to
save changes. Uninstall through Windows Apps/Programs. ProgramData configuration,
credentials, reference data, and runtime databases are retained for recovery.

## Raspberry Pi ARM64 and Linux x86_64

Run the matching installer with Bash. Prefer a stable `/dev/serial/by-id/` path:

```bash
sudo bash MeshCore-EMS-v0.2.0-alpha-raspberry-pi-arm64.run --port /dev/serial/by-id/YOUR_COMPANION
# Intel/AMD:
sudo bash MeshCore-EMS-v0.2.0-alpha-linux-x86_64.run --port /dev/ttyUSB0
```

With no `--port`, setup reuses an installed port or selects the only discovered
serial device; otherwise it asks in an interactive terminal. `--channel NAME`
overrides the channel. `--no-start` installs/enables without starting now.

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

## Optional credentials and satellite tools

Edit `environment.json` in the installed configuration directory as administrator:

```json
{"AIRNOW_API_KEY": "your-key"}
```

Only AirNow requires a key. Optional external MQTT credentials use
`MESHCORE_MQTT_USERNAME` and `MESHCORE_MQTT_PASSWORD` in that same file. Restart
after changing settings. The bundled broker remains bound to localhost, using
the existing platform ports (Windows 1884; Linux 1883).

The service runner uses a saved `serial_port`; the source-folder interactive
launchers still use the original device selector when that setting is absent.
Linux handles SIGTERM and Windows sends a stop request so the bridge can close
SQLite, MQTT and serial resources. The service manager restarts a failed process.

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
