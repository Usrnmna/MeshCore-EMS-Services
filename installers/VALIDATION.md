# Installer and service validation

## Hosted GitHub Actions: October 26, 2026

The [Offline verification run](https://github.com/Usrnmna/MeshCore-EMS-Services/actions/runs/40421774997)
completed successfully with **all 10 jobs passing** for commit
[`79e2be47758347ff352de561f05ae84b9786561c`](https://github.com/Usrnmna/MeshCore-EMS-Services/commit/79e2be47758347ff352de561f05ae84b9786561c).

| Hosted scope | Result |
| --- | --- |
| Both service packages on Windows and Ubuntu, using Python 3.11 and 3.13: eight jobs | Passed |
| Documentation, installer tools, offscreen GUI widgets, data tools, and satellites on Windows and Ubuntu: two jobs | Passed |

The [Windows tooling job](https://github.com/Usrnmna/MeshCore-EMS-Services/actions/runs/40421774997/job/121917710024)
reported 120 tests with three skips; the
[Ubuntu tooling job](https://github.com/Usrnmna/MeshCore-EMS-Services/actions/runs/40421774997/job/121917709821)
reported 120 tests with eight skips. Each platform also passed the five offline
data and satellite suites: 20 Basin Plan, 22 flood-impact, 88 USGS Water, five
EBMUD, and 31 satellite tests. The six offscreen GUI widget tests ran on both
platforms, and the Windows short/long-path regression subcases were not skipped.

Conditional coverage remains explicit. Windows skipped the POSIX permission,
native Linux service-account permission, and optional Inno Setup fixture checks.
Ubuntu skipped the five Windows PowerShell checks, Windows ACL and junction
checks, and the native Linux service-account permission check. A successful job
does not establish that these conditional checks ran.

The associated [GitHub Actions dependency check](https://github.com/Usrnmna/MeshCore-EMS-Services/actions/runs/40421781294)
and [pip dependency check](https://github.com/Usrnmna/MeshCore-EMS-Services/actions/runs/40421781382)
also completed successfully for the same commit.

Hosted results establish the configured software checks for this revision. They
do not establish native Raspberry Pi/ARM64 execution, production service
installation or reboot recovery, physical USB/BLE/TCP radio behavior, RF or
recipient delivery, continuous four-hour monitoring, current provider availability,
complete fresh acquisition of every dataset, interactive desktop behavior, or
real GUI install/remove qualification. This workflow does not rebuild, sign, or
publish release artifacts; the Windows distributions remain unsigned. Earlier
native qualification retains its recorded source/artifact scope and is not
automatically extended to later builds. Later revisions require their own checks.

The dated records below describe evidence available at each checkpoint. This
hosted result supersedes their earlier pending-CI status without replacing their
artifact-specific evidence or deployment and hardware limitations.

## Compiled Windows dataset tools

Windows dataset packages include `Dataset.exe`, compiled from the maintained
PowerShell entry point using PS2EXE 1.0.18. Automated executable tests cover paths
with spaces, invocation from another working directory, native stdout/stderr,
child exit codes, candidate and purge arguments, invalid arguments, menu input,
missing runtime settings and source-invocation compatibility. Native Inno fixture
tests cover setup failure code 20, clean Installed Apps names, refused removal
and successful removal of the executable.

PS2EXE parameter-attribute validation can report an error with exit code zero;
action and candidate validation therefore run inside the script's error handler.
Console input uses `Console.ReadLine` to support redirected input as well as
interactive menu launches. Neither conversion nor menu operation changes dataset
activation, receipt validation, dependency protection or retention policy.

The release's `native-validation/windows/VERIFICATION.json` records the actual
compiled-tool lifecycle qualification. A passing result requires all eight
installed executables to reject unavailable updates while preserving registry
selection, complete receipt hashes and service-account reader results. It also
records readable Installed Apps names, shortcut targets, removal of known obsolete
launchers, dependency-blocked uninstall and all eight successful uninstallers.
Compiler snapshots record source and generated executable hashes. Final rebuilds
are compared with native-tested runtime sources; regenerated PE files can differ
in build metadata, so tested and final executable hashes remain distinct evidence.

Linux/Pi wrappers are unchanged by Windows compilation. Linux native lifecycle
evidence below remains applicable only when the final runtime-input comparison
passes. Rebuilt Linux/Pi archives also require checksum and extraction validation.
An ARM64 archive check on WSL does not establish native Raspberry Pi execution.

## Native dataset lifecycle qualification: October 21-22, 2026

Actual generated installers and their installed uninstallers were exercised in
isolated data roots. The Linux run used Ubuntu 24.04 x86_64 under WSL2. The Windows
run used Windows 10 Pro x64 with administrator elevation. Raspberry Pi native
execution was unavailable because no ARM64 test host was available.

| Native check | Ubuntu 24.04 WSL2 | Windows 10 x64 |
| --- | --- | --- |
| Eight independent dataset installers and receipt verification | Passed | Passed |
| Eight failed updates preserve registry, receipts and all selected file hashes | Passed | Passed |
| Failed installer repair preserves the selected maintenance runtime and data | Passed | Passed |
| Installed readers and service readiness under the service identity | Passed | Passed |
| Main service uninstaller preserves independent datasets | Passed | Passed |
| Prerequisite removal refused while dependent datasets remain | Passed | Passed |
| Eight independent uninstallers and modified/unowned/legacy data retention | Passed | Passed |

The four bundled collections used their actual packaged snapshots. Basin Plans,
flood reference, USGS Water and satellites imported isolated copies of existing
local archives. USGS installation validated its prerequisites and prepared its
managed spatial index. The original source directories were not used as uninstall
targets. These checks establish import, validation and activation behavior;
they do not establish complete fresh downloads from every upstream provider.

Failure injection used refused loopback proxy connections on Linux and a local
proxy returning HTTP 503 on Windows for the six network updaters. Unavailable or
invalid packaged manifests exercised the two curated collections. A refused
dependency-index connection tested actual installer repair
failure. The post-failure probes compared complete receipt-bound file hashes,
registry selection and functional reader results with the baseline. They executed
installed code using the installed interpreter under `meshcore-ems` or Windows
`LocalService`, with network access rejected during the reader checks. Parks,
Basin archive and flood-reference helper checks remain reference-tool checks;
they do not introduce additional MeshCore commands.

Native testing exposed and corrected three installation defects:

- Linux private virtual environments inherited permissions that prevented the
  service account from executing Python. Runtime files now grant the service
  group read/traverse access without write access, and installation performs the
  readiness check as that account before activating the release.
- Windows custom application directories could inherit private profile ACLs.
  Installation now grants `LocalService` read/execute access to application files.
- Windows PowerShell 5.1 rejected the null backup argument used during atomic
  runtime-settings replacement. Replacement now uses a unique backup path.
  Dataset setup also returns exit code 20 when preparation fails, retains helper
  output under the package's `logs` directory, and exits promptly when silent
  uninstall is refused.

An initial Windows USGS import stalled during prerequisite validation and was
terminated after its owned process tree was identified. The unchanged registry
and preserved legacy directory were recorded; the exact stall cause was not
established. The subsequent installer uses hidden helpers with output redirected
to persistent files. A preexisting invalid third-party Ubuntu APT repository
required a process-only override using official Ubuntu sources; system APT
configuration was not changed.

Focused regression checks passed: 21 service-installer tests on Windows with the
Linux-only case skipped; 10 dataset-installer tests, including native PowerShell
5.1 and a compiled Inno failure/refusal fixture; and 18 dataset-manager tests plus
the service-runtime permission test on native Ubuntu with no skips.

Test-created service registrations and temporary scheduled tasks were removed.
Retained configuration, failed candidates, modified content and legacy copies
remain under the isolated evidence directories. The Linux `meshcore-ems` account
is retained by the normal uninstaller policy. These checks do not claim reversal
of every package-manager dependency installed during qualification.

The release `VERIFICATION.json` records final artifact hashes and compares runtime
source/seed bytes with the exact native-tested payload manifests. Documentation
rebuilds can change installer hashes without changing the tested runtime inputs;
the native reports retain that distinction. Service-first installation order
remains covered by source/unit checks; the native sequence installed data first,
then installed, repaired and removed the main service.

Services were installed with `--no-start` or `/NOSTART=1` to avoid starting the
bridge during qualification. Readiness and offline
reader execution under the real service identities do not establish a running
radio bridge, reboot recovery, hardware access, live-provider availability or
over-the-air delivery. Windows builds remain unsigned. Earlier sections retain
their original source/build scope; this section supersedes their native-test
limitations only for the checks explicitly recorded here.

## Independent dataset packaging: October 21, 2026

Eight dataset packages use separate Windows x64, Linux x86_64 and Raspberry Pi
ARM64 installers. Service payload inventories exclude reference dataset bytes.
The [dataset lifecycle guide](../docs/DATA_PACKAGES.md) describes updates,
ownership-scoped removal and preserved local generations.

Completed software checks for this change:

| Suite | Result |
| --- | --- |
| Linux service source on Windows host | 484 passed |
| Windows service source | 484 passed |
| Dataset manager failure and recovery tests | 18 run; POSIX permission-bit case skipped on Windows |
| Dataset source adapters | 17 passed |
| Dataset packaging | Passed; separate targets, payload hashes and release versioning |
| Existing service installer/configuration regression | 19 passed |
| Flood-reference tools, including static-only validation | 22 passed |
| Satellite tools and managed generation access | 31 run; 1 optional Skyfield test skipped |

Real local EBMUD, Parks, wildfire, landslide, satellite, Basin Plan and static
flood datasets passed offline validation. USGS routing and its three review
validators passed against the existing local archive. Complete new USGS
acquisition and its generation-local index were not exercised against live
providers. Windows temporary-directory/pipe restrictions required permitted
runs outside the restricted sandbox; no production workaround was introduced.

PowerShell parsing, Bash syntax and binary-wheel dependency resolution were
checked for Windows x64 Python 3.13, Linux x64 Python 3.11, and Raspberry Pi ARM64
Python 3.11/3.13. Windows Inno Setup compilation and self-extracting archive
inspection are build evidence, not native installation/uninstallation evidence.
Actual administrator service/data installation in either order, reboot behavior,
Linux/Pi deployment, live-provider outages and physical radio delivery remain
target acceptance checks. Default Windows builds are unsigned.

## Version 0.9.6 - Beta rebuild: October 21, 2026

The local release identifier is `v0.9.6-beta`; Windows launcher, service-host,
and installer metadata use `0.9.6.0`. The release packages the current 31-command
source as separate Windows x64, Linux x86_64, and Raspberry Pi ARM64 online
installers, plus Linux and Windows standalone source ZIPs.

| Offline suite | Passed on Windows Python 3.13 |
| --- | ---: |
| Linux service source package | 475 |
| Windows service source package | 475 |
| Installer/configuration tools | 19 |
| Basin Plan tools | 20 |
| Flood-impact tools | 22 |
| Statewide USGS tools | 88 |
| EBMUD refresh tools | 5 |
| Satellite catalog | 27 |
| Total | 1,131 |

The documentation checker verifies 31 registrations per package, 618 tagged
response examples across the paired catalogs, 378 focused function signatures,
terminal options, local links/fragments, version badges, paired guides, and Git
publication exclusions. Generated water-data destinations require their documented
setup. Initial restricted runs encountered temporary-directory access failures;
the table records successful reruns with the required execution permissions.
The existing test environment includes system-site packages. Its `pip check`
reports an unrelated `folium-vectortilelayer==0.2.5` dependency on missing `folium`;
a clean-environment dependency validation is not claimed.

Artifact verification compares complete ZIP inventories and bytes with current
source, checks every embedded Linux payload file against its manifest and source,
and validates both Linux installer payload checksums with read-only `--check`
under Git Bash. Windows verification checks the compiler snapshot manifest,
source bytes, x64 launcher/service-host PE targets, binary version metadata,
launcher `--check`, service-host `--version`, and installer SHA-256.
The embedded Inno Setup archive is not independently extracted.

The release directory `dist/v0.9.6-beta/` contains all three separate installers,
both source ZIPs and individual checksums, installation and release guides,
this validation record, `TEST-RESULTS.txt`, `VERIFICATION.json` and its checksum,
`SHA256SUMS.txt` for the installers, and `RELEASE-ASSET-SHA256SUMS.txt` for the
complete release inventory. The asset inventory excludes itself. Exact hashes,
file counts, test results and inspection limits are recorded after the final
build in `VERIFICATION.json`. Current standalone ZIPs also remain under `dist/`.

No native Linux/ARM64 execution, OS-service installation or reboot recovery,
physical radio or recipient delivery, continuous monitoring, or live-provider
validation was performed. The Windows installer is unsigned and dependencies
are obtained online during installation. This is a local rebuild; no GitHub
release publication is asserted. Earlier entries below retain historical results.

## Current-source documentation verification: October 21, 2026

The current source contains **31 registered commands per platform**. The
[command reference](../meshcore_mqtt_service/COMMAND_REFERENCE.md#subcommand-index)
lists every command, GIS field/category, wildfire context category, location
query form and subscription control. The paired
[response catalogs](../meshcore_mqtt_service/RESPONSE_EXAMPLES.md) each contain
**309 offline formatter examples**, including help, closest/radius queries,
all field/category forms, monitoring controls and triggered notifications.
Each tagged response is checked against its stated UTF-8 byte count and 150-byte
limit. Synthetic provider values and fixed timestamps do not describe live conditions.

- Both complete service suites pass **475 tests each** on Windows Python 3.13,
  including dedicated command registrations, single-message formatting, and
  source/queue/subscription guards. Documented flood lifecycle responses and
  triggered flood/fire/landslide examples are compared with service callbacks.
- Additional offline suites pass: tools **19**, Basin Plan **20**, flood-impact
  **22**, statewide USGS **88**, EBMUD **5**, and satellite **27**: **1,131 total**.
- The documentation checker validates all command and terminal inventories,
  tagged examples, paired-guide parity, local links/fragments, 378 focused
  function signatures, badges, and publication exclusions. Generated water-data
  destinations are reported separately and require their documented setup.
- Current local EBMUD data produced 52 GIS lookup examples; 33 field-response
  rows and applicable named/proximity examples were refreshed in each command
  reference. Source reference-data bytes were unchanged.
- GitHub YAML structure, pinned action references, eight service matrix
  combinations, maintained dependency paths and 65 ignore/retention cases pass
  local checks. No tracked files are excluded by the ignore rules.

At this October 21 checkpoint, the configured Windows/Linux Python 3.11 and 3.13
hosted jobs had not yet run. Local tests used Python 3.13 with the declared
dependencies and existing system libraries. Native Linux/ARM64, local Python
3.11, service installation/reboot, physical radio and recipient delivery,
continuous four-hour monitoring, and current provider availability were outside
that checkpoint's verification. No acquisition, release rebuild, GitHub push or
GitBook publication was performed. The October 26 hosted record above supersedes
this earlier pending-CI status; the dated local evidence remains historical.



## Current-source documentation and offline checks: October 20, 2026

The current source registers **31 dedicated command programs per platform**.
The [complete radio subcommand index](../meshcore_mqtt_service/COMMAND_REFERENCE.md#subcommand-index)
and [terminal reference](../docs/CLI_REFERENCE.md) describe the registered
commands, selectors, alarm controls, collection tools, and satellite subcommands.
Earlier entries below record the command sets and artifacts checked at those times.

- Both platform service suites pass **392 tests each** on Windows Python 3.13,
  including command registrations and offline/loopback integration behavior.
- Additional offline suites pass: installer/configuration tools **19**, Basin Plan
  tools **20**, flood-impact pilot **22**, statewide USGS tools **88**, EBMUD
  refresh tools **5**, and satellite catalog **27**: **965 tests in total**.
- `python tools/check_documentation.py` checks all 31 command registrations,
  subcommand vocabulary, local Markdown paths/fragments, literal terminal options,
  346 paired water/wildfire function signatures, badges, guide parity, and Git
  publication rules. Ignored generated water-data links are reported separately
  and require the documented acquisition/index setup on a fresh clone.
- The installer-test fixture includes the existing flood worker's water-helper
  imports. Standalone package inventories include both focused function references.
- Existing application source and test changes were preserved. Reference dataset
  bytes were unchanged. No live provider acquisition was performed by these checks.

The GitHub workflow and Dependabot configuration were checked locally for YAML
structure, action pins, repository paths, and documented offline test commands.
GitHub-hosted Windows/Linux jobs had not yet run at this October 20 checkpoint;
the October 26 hosted record above provides the later result. Local verification
used an isolated environment with declared dependencies and access to existing system
libraries. Native Linux/ARM64, installed-service lifecycle, physical radio or
recipient delivery, and continuous four-hour monitoring were outside that
checkpoint's verification.
Release artifacts were not rebuilt or republished during this documentation pass;
the historical artifact results below do not validate a new distribution.

## Version 0.9.5 - Beta: October 20, 2026

The release identifier is `v0.9.5-beta`; Windows assembly/file metadata uses
`0.9.5.0`. Both platform source packages contain 28 dedicated command programs,
including `!slidewarn`, `!slidealarm`, and `!slideinfo` for California and Nevada.
Each standalone ZIP includes `VERSION.txt` and has a companion SHA-256 file.

- Full regression suites pass 331 tests per platform package on Windows Python
  3.13. The 37 landslide tests cover location resolution, both state boundaries,
  NWS alert lifecycle/failure handling, cache retention, subscription persistence,
  Nevada enrollment, and queue guards. Dedicated command registrations are tested.
- Nineteen installer tests cover separate installer outputs, metadata consistency, landslide asset inventories,
  upgrade settings, channel assignments, credentials, and runtime preservation.
- Live point lookups succeeded for Reno by city and ZIP, Las Vegas GPS, and the
  Nevada-side Tahoe point. One concurrent request reported the documented SQLite
  lock limit and succeeded on retry. These are point-in-time provider checks.

Release verification compares every standalone ZIP member with current source;
checks Linux installer inventory, embedded payload checksums, file hashes and
source bytes; and verifies the Windows compiler input snapshot, its payload
manifest, and x64 service wrapper. Inno Setup compiles that snapshot into the
Windows installer. Windows installer checks cover output version metadata,
compiler completion, and release SHA-256 integrity; they do not independently
extract the proprietary installer archive or perform an installation.

Both platforms include all landslide entry points/helpers, service integration,
California and Nevada polygons, the station catalog and hash manifest, tests,
and maintained user/technical guides. Runtime state, development environments,
credentials, and generated water downloads remain excluded. Operating-system
installers are distributed separately and checked against their checksum list;
copied guides are compared with final source. No combined installer ZIP is produced.
The machine-readable verification report is generated alongside release artifacts
as `dist/v0.9.5-beta/VERIFICATION.json` after building from the final source.

No service is installed or started by these checks. Native Linux/ARM64 execution,
SCM/systemd lifecycle, physical radio delivery, and continuous warning delivery
remain unverified. Windows executables are unsigned.


## October 20, 2026 wildfire validation

- Both platform source suites pass 294 tests each, including 30 wildfire and 25 point-environment tests
  and the dedicated-command registration check. Tests run on Windows; the
  Linux-package result is not native Linux runtime validation.
- Point-command tests cover smoke formatting omissions, plume holes/edges,
  stale/future/malformed observations, per-pollutant monitor selection, ERC
  percentile boundaries, independent warnings, KML validation and FEMS errors.
- Live HMS parsing returned 104 plume features plus dated product metadata;
  the national NFDRS station-summary join returned 946 records. Point CLI checks
  exercised nearby AirNow observations and Tahoe-area ERC/RAWS/warning output.
  These are October 20, 2026 provider checks, not permanent dataset counts.
- FEMS authenticated access was tested with fixtures only. Live account access,
  source quality-code interpretation, numerical smoke transport, and named-fire
  smoke attribution remain unverified or unimplemented as described in the guide.
- Fifteen installer tests pass, including preservation of an edited wildfire
  interval, existing channel assignments, runtime databases and credentials.
  Distribution inventory also excludes generated water downloads according to
  the existing root `.gitignore` policy while retaining curated inputs.
- Live source checks cover EGP/WFIGS incidents, year-to-date perimeters, all ten
  relevant NWS FWF offices, CAP alerts, RAWS, AQI, smoke, VIIRS/MODIS,
  ALERTCalifornia, AQI forecasts, SPC outlooks and seven-day fire potential.
  A successful empty SPC collection is checked through an independent count.
- GPS `39.25, -119.96`, ZIP `96161`, and city `Truckee` resolve to CAZ272 and
  return its cached fire-weather warning/watch status. Active-warning behavior
  is also tested with fixtures containing a null-geometry CAP warning.
- The bundled seed contains 186 complete California-associated zones and its
  checksum is verified before initialization. Tests check Nevada coverage in
  CAZ272 and inclusion of NVZ420.
- The optional all-years historical layer exceeds one refresh budget.
  Completed batches are staged and resumed; partial collections are never
  published. This is distinct from the bounded recent-observation history.
- Documentation file-link checks pass, and all 25 command anchors are present
  in each command reference.

Initial restricted test runs encountered Windows temporary-file permissions.
The complete suites passed with normal local filesystem/subprocess access and
the existing local MQTT dependencies. Package parity and distribution integrity
are checked during the rebuild. No live radio, recipient delivery, native
Linux host, installed Windows Service/systemd lifecycle, or evacuation workflow
has been validated by these software tests.

See the [wildfire guide](../meshcore_mqtt_service/WILDFIRE_GUIDE.md) for inputs,
source interpretation, refresh settings and deployment.

## October 11, 2026 GIS distribution validation

That rebuild used version `v0.9.0-beta`. The artifacts comprise Windows
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
