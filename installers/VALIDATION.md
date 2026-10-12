# Installer and service validation

## October 11, 2026 GIS distribution validation

The current rebuild uses version `v0.9.0-beta`. The artifacts comprise Windows
x64, Linux x86_64, and Raspberry Pi ARM64 installers, both standalone service
ZIPs, and the combined installer ZIP. Generated SHA-256 files identify this
rebuild; matching version filenames alone do not establish artifact identity.

The latest service regression run used Windows Python 3.13 and passed 239 tests
per platform source package, including 26 GIS tests per package and dedicated
command-program registration checks. The installer configuration and packaging
suite was rerun for this rebuild: 14 tests passed. The preceding documentation changes were limited
to prose, ignore policies, and a service docstring; syntax-tree comparison
with docstrings excluded confirmed unchanged executable Python behavior.
The version update changes installer paths, labels, manifests, and Windows
assembly metadata (`0.9.0.0`); service command behavior remains unchanged.

GIS coverage includes focused attributes, explicit full information, affirmative
policy and amenity filters, closest-only searches without a radius, explicit
radius limits, ties, category-restricted boundaries, and responder argument
forwarding. Nine documented queries passed in each source package against the
local datasets (18 CLI invocations).

Documentation validation checks maintained links/anchors, JSON examples,
function-reference entries, command tables, channel imports, setting defaults,
and dataset counts and hashes. Maintained prose, Python comments/docstrings,
and shell/PowerShell/C#/installer comments were audited for impersonal technical
style. Historical validation below retains its original evidence boundaries.

Artifact validation compares service ZIP inventories and bytes with current
source, verifies Linux payload manifests and every included file, checks the
Windows compiler payload and x64 service wrapper, and validates the combined
bundle and SHA-256 files. Installers include all twelve EBMUD datasets, the source
manifest, maintenance programs, and repair originals. Standalone service ZIPs
include GIS programs/settings but require the shared data directory separately.

All four maintained ignore files exclude local build output and interrupted ZIP
writes while retaining command programs, tests, configuration templates,
documentation, GIS datasets and repair originals, and satellite reference data.
Tracked distribution artifacts remain tracked; ignore rules do not remove them.

These checks do not install or start an OS service. Native Linux execution,
physical radio delivery, and end-to-end installed-service operation remain
unverified for the GIS addition. The Windows installer is unsigned. Earlier
records below apply to their dated source and build states.

## Lightning command and configurable timezone

Checks on October 8, 2026 used Windows Python 3.13 with `tzdata==2026.5`:

| Check | Result |
| --- | --- |
| Linux service source package on Windows | 211 tests passed, including 28 lightning and 7 shared-timezone tests |
| Windows service source package on Windows | 211 tests passed, including 28 lightning and 7 shared-timezone tests |
| Installer configuration and packaging suite | 14 tests passed, including preservation of an operator's shared responder timezone on both platform upgrade paths |
| Maintained application function documentation | 410 definitions have docstrings and function-reference entries; test helpers excluded |
| Local maintained documentation links/anchors | 209 checked; generated distribution snapshots excluded |
| Root and standalone service ignore policies | 27 generated/local sample paths ignored; 16 maintained/example paths retained |

Lightning tests cover any stated chance, including slight chance and 1%, dry
thunderstorms/LAL 6, explicit lightning fire-weather text, negations and separate
preparedness instructions, original request timing, 24-hour boundaries, stale or
incomplete NWS data, Pacific spring/fall DST transitions, and manual timezone
overrides, and retention of known hazards during a partial NWS outage. A real responder subprocess exercises saved sender tags, incoming
channel selection, configuration arguments, request stdin, and message splitting.
Clock, AQI, and river timestamp checks exercise the same saved zone, including date
rollover; all child programs receive the shared setting. Installer configuration
tests exercise a shared timezone edit followed by another upgrade. Caltrans
undated/recurring schedules keep an explicit source-Pacific label.

Live NWS/geocoder lookups returned no-lightning text for Sacramento GPS, ZIP 95814,
and Reno with a full state name, and positive percentages/slight-chance forecast
windows for Miami FL, displayed in Pacific time. These were point-in-time provider
checks; alerts and dry-lightning scenarios were tested with fixtures. No physical
radio delivery, installed-service operation, or native Linux execution was tested
for this addition. The satellite code was unchanged; its earlier test record below
is not a new satellite validation run.

The service ZIPs and three installer targets were rebuilt from the October 8 source with
version `v0.3.0-beta`. Artifact checks compare complete manifests and packaged
bytes against source, verify archive integrity and SHA-256 files, and check the
staged x64 Windows service wrapper. These checks do not install/start a service
or establish native target behavior. The hashes identify this rebuild despite
the unchanged version filename.

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
