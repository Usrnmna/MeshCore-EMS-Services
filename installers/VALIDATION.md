# Installer and service validation

## Documentation and heat-command rebuild checks

Checks on October 7, 2026 used Windows Python 3.13:

| Check | Result |
| --- | --- |
| Linux service source package on Windows | 176 tests passed |
| Windows service source package on Windows | 176 tests passed |
| Installer configuration and packaging suite | 13 tests passed |
| Satellite suite | 26 passed; 1 optional Skyfield test skipped because Skyfield is absent in this test environment |
| Application function documentation | 372 definitions covered, including methods and nested callbacks; test helpers excluded |
| Added satellite docstrings | 20 additions; executable syntax trees unchanged |
| Local documentation links and anchors | 169 checked |
| Ignore policy | 12 generated/local paths excluded; 13 source/reference paths retained |

The service ZIP inventory includes each package's `FUNCTION_REFERENCE.md` and
`!heatadv` source/tests/configuration. Installer inventories include those files
plus the satellite and packaging function references. Build outputs retain version
`v0.3.0-beta`; their SHA-256 files identify this particular rebuild. Artifact
validation must compare payload manifests and file bytes with the current source,
check the service ZIPs and combined bundle, and verify the x64 Windows service
wrapper. Building or inspecting these artifacts does not install or start a service.

## Heat command source validation

The `!heatadv` implementation was checked on October 6, 2026, using Windows
Python 3.13. Each platform source package passed 176 tests, including 18 heat
command tests; the installer suite passed 13 tests. Real subprocess tests cover
sender tags, origin-channel replies, and all three heat alert types. Live city,
ZIP, GPS, state-abbreviation, and full-state-name lookups exercised advisory and
no-advisory replies. Warning/watch combinations and error cases used fixtures.
These checks did not rebuild installers or verify native Linux execution,
installed-service activation, or physical radio delivery for this addition.

The earlier transport validation below describes its own dated source/build;
it is not evidence that `!heatadv` was included in those installer artifacts.

## Transport and multi-channel validation

Validation for serial/BLE/TCP connections, multiple channels, and external programs was
performed on October 4, 2026. No installed production service or radio was started.

| Check | Result |
| --- | --- |
| Windows package on Windows Python 3.13 | 158 tests passed |
| Linux package on Ubuntu 24.04 x86_64 under WSL | 158 tests passed |
| Installer migration/preservation tests on Windows | 13 tests passed |
| Installer migration/preservation tests on Ubuntu under WSL | 13 tests passed |
| Windows service environment dependency check | Passed |
| Changed Python formatting | Black 25.1.0, 100-column formatting; syntax-tree equivalence checked |

Transport tests cover selected-interface validation, default TCP port 5000,
legacy serial configurations, upgrade preservation and explicit transport
switches, bounded connect/cancellation cleanup, serial DTR fallback, and shared
bridge/CLI/channel-tool settings. A real loopback TCP server exercises the pinned
MeshCore SDK with a fragmented companion handshake and remote disconnect.
A simulated silent TCP link verifies that a failed periodic device check ends
the bridge for service-manager recovery. BLE transport selection is simulated;
no physical Bluetooth adapter or node was used.

Tests also cover USB serial autodetection and port renumbering without hardware,
missing/ambiguous-device errors, fixed overrides, mixed public/private assignments,
origin-channel replies, private
MQTT export suppression, serialized radio operations, graceful shutdown with
pending callbacks, name/key checks, empty-slot provisioning, atomic SQLite
migration and retry, independent alarms, and duplicate handling after slot moves.
Custom-program tests execute real temporary Python scripts and verify context,
key exclusion, containment after symlink resolution, and upgrade preservation.
Radio responses and external weather services are simulated. MQTT integration
uses a real local broker on loopback; this does not establish radio delivery.

The build procedure compiles the Windows setup executable and service host,
creates both Linux installer payloads, and writes integrity manifests and SHA-256
checksums. Artifact verification is separate from installing the OS services.

Not performed: production Windows SCM or Linux systemd install/uninstall;
boot/reboot recovery; a real ARM64/Pi execution; physical radio channel creation,
USB/BLE/Wi-Fi operation, Bluetooth pairing/service-account permissions,
over-the-air reception, or long-duration flood monitoring. The
Windows installer is unsigned. Custom programs require operator review and must
run with the dependencies available in the installed Python environment.
