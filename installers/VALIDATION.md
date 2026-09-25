# v0.2.0-alpha installer validation

Validation performed on September 24, 2026, using a Windows x64 build host and
Ubuntu 24.04 x86_64 under WSL. No production service or radio was started.

| Check | Result |
| --- | --- |
| Windows setup compilation with Inno Setup 6.7.3 | Passed |
| Windows SCM host compilation as x64 .NET executable | Passed |
| Both Linux archive builds, SHA-256 integrity and payload manifests | Passed |
| Windows PowerShell and Linux shell syntax | Passed |
| Linux systemd unit schema (executable substituted for non-installed path) | Passed |
| Windows online preparation in isolated workspace directories | Passed: private Python 3.13.15 downloaded, checksum verified, dependencies installed, configuration/import check passed |
| Linux dependency installation in isolated workspace venv | Passed on Python 3.12.3; pip dependency check passed |
| Raspberry Pi baseline dependency resolution | Passed: Python 3.11 ARM64 wheels available; this is not execution on a Pi |
| Both service suites on Windows | 114 tests passed per package |
| Windows suite on freshly downloaded private runtime | 114 tests passed |
| Linux service suite on Ubuntu x86_64 under WSL | 114 tests passed |
| Satellite suite with Skyfield installed | 27 tests passed on Windows and Linux |
| Installer preservation/inventory tests | 3 tests passed on Windows and Linux |

The lifecycle tests cover saved-port selection, input validation, restricted
credential loading, graceful cancellation/cleanup, and propagation of a bridge
failure to the service manager. Existing tests use mocked radio/weather responses,
subprocesses, and loopback MQTT. Installer tests check that existing credentials,
configuration, runtime data, and refreshed satellite databases survive an upgrade.

Not performed: administrator installation/uninstallation into Windows SCM;
root installation into systemd; boot/reboot recovery; a real ARM64/Pi run; physical
USB serial selection, four-hour live monitoring, or over-the-air delivery.
Windows online preparation deliberately skipped service registration, ACL changes,
and starting the service. Linux dependency/testing work used a workspace venv.
The Windows setup executable is unsigned. SHA-256 checks detect changed artifacts
but do not establish publisher identity without a trusted checksum distribution.
