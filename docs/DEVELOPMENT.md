# Development, packaging, and verification

This guide covers repository maintenance and source distribution. For deployment,
use the [installation guide](../INSTALL.md). For component responsibilities and
MQTT topics, use the [architecture guide](ARCHITECTURE.md). The
[documentation index](README.md) links all maintained topic guides.

## Workspace organization

| Location | Contents |
| --- | --- |
| `meshcore_mqtt_service/` | Linux service, shell launchers, command scripts, and `tests/`. |
| `meshcore_mqtt_service_windows/` | Windows service, Windows launchers, command scripts, and `tests/`. |
| `satellite_database/` | Independent satellite catalog program, settings, schema, and tests. |
| `data/` | Maintained EBMUD/State Parks references, satellite exports, wildfire seed, and download-on-demand water collection tools; water generations remain local. |
| [`tools/package_services.py`](../tools/package_services.py) | Builds both distribution ZIPs from current source and checks shared-code parity. |
| `dist/` | Generated installation ZIPs; rebuild after source changes. |
| [`archive/`](../archive/README.md) | Local historical recovery backups, excluded from version control. |

The service folders are the maintained installation sources. Shared command code
is deliberately present in both so either package can run independently. Update
both copies together; retain platform-specific serial selection and MQTT defaults.
Every shipped command has its own executable Python program in `scripts/`;
shared helper modules are permitted. The rule is recorded in [AGENTS.md](../AGENTS.md)
and checked by each package's `tests/test_command_programs.py`.
When copies differ, compare contents and modification history and reconcile the
newer implementation before packaging. The packager rejects divergent shared code.

The highway lookup runs directly from either service package without starting
MQTT or the radio:

```console
python meshcore_mqtt_service/scripts/highway_info.py 80
```

Windows setup creates `.venv/` in the Windows service folder; Linux setup creates
`.venv-linux/` in the Linux folder. Shared reference data lives under `data/`.

Build fresh packages from the workspace root with:

```console
python tools/package_services.py
```

This replaces the two ZIPs under `dist/` and excludes environments, runtime state,
bytecode, and historical backups. The ZIPs include their own tests and documentation.

## Workspace ignore policy

Build independent dataset artifacts with `python tools/build_data_installers.py`.
The optional [dataset GUI build](DATASET_GUI.md#manually-package-the-gui) uses
`tools/build_dataset_gui.py` and reuses those artifacts without recompiling them.
The [dataset guide](DATA_PACKAGES.md#build-and-validation) documents inventories,
platform targets and failure-injection tests. Dataset reference bytes are excluded
from the main service ZIPs/installers. Managed generations, activation registries
and maintenance locks are local state excluded from Git.

The root `.gitignore` excludes local environments, service runtime state, Python
bytecode/tool caches, coverage reports, build/distribution directories, credentials,
recovery backups, interrupted archive/export writes, and GIS refresh staging/locks.
All four ignore files exclude managed `.datasets/` generations, `datasets.json`
activation registries, registry temporary writes, and `.datasets.lock` maintenance
locks, including standalone service and satellite copies. Environment `.example`
and `.template` files remain publishable. Source Python,
configuration templates, tests, function references, reference SQLite/JSON/CSV data,
and retained raw source receipts remain trackable. Ignore rules do not remove
files that Git already tracks, including previously committed distribution files.

The root [Git attributes](../.gitattributes) define LF endings for maintained
source, documentation, and editable Qt Designer forms. Windows command and
PowerShell scripts use CRLF endings. File encodings remain unchanged. Reference
datasets and supplier receipts
under `data/` bypass line-ending conversion to preserve manifest-recorded bytes;
maintained collection Python and top-level Markdown guides retain text handling.
Supplier whitespace is retained and exempt from whitespace linting; authored
Python and Markdown files continue to receive whitespace checks.
CSV and JSONL files outside protected reference-data directories use LF endings;
SQLite `.db` files, compressed archives, wheels, and Python extensions retain
binary bytes. Managed `.datasets/` generations bypass text conversion, including
archived source copies.

Immutable Basin Plan, flood-reference and USGS generation directories override
the text exceptions, including archived `build_code/*.py` and README copies.
Every manifest-covered file retains its original bytes. Do not renormalize
these generations. SQLite routing databases and other binary GIS formats have
binary attributes; `.sqlite` and `.sqlite3` journal/WAL/SHM files are ignored.
Pending generations at any depth in these collections are ignored, while
completed water-data generations, raw receipts, observation snapshots, relationship
tables, generated catalogs, pointers, source audits and validation reports remain
local and are excluded from Git. Maintained programs, tests, guides,
`pilot.json` and `local_review_rules.json` remain eligible for tracking.

The water-data collections use download-on-demand distribution; no Git LFS
configuration or dataset upload is required. The
[fresh-clone setup guide](WATER_DATA_SETUP.md) documents acquisition order.
Ignore rules preserve existing local files and do not rewrite repository history.
Byte-preserving attributes remain available for local archive handling.

Generated `dist/` artifacts remain local build outputs. Removing an artifact from
Git tracking does not remove its local copy or rewrite historical commits.

## Python function documentation

Every maintained application function, including methods and nested callbacks,
is described in the component references. Test helpers are excluded.

- [Linux service and commands](../meshcore_mqtt_service/FUNCTION_REFERENCE.md)
- [Windows service and commands](../meshcore_mqtt_service_windows/FUNCTION_REFERENCE.md)
- [Satellite catalog, sources, and exports](../satellite_database/FUNCTION_REFERENCE.md)
- [Installer configuration and packaging tools](../tools/FUNCTION_REFERENCE.md)
- [GIS refresh and polygon-repair utilities](../data/ebmud/FUNCTION_REFERENCE.md)

## Development and verification

Run `bash verify.sh` from the Linux service folder after setup, or `verify.cmd`
from the Windows service folder. Both discover all tests in `tests/` automatically.
Run the satellite suite with `python -m unittest discover -s satellite_database`
from the workspace root.

Both service folders include tests for:

- Command parsing and input validation.
- Script execution, timeouts, failures, and output limits.
- Sender retention and same-channel tagged replies.
- Duplicate suppression and persistent request state.
- AQI, traffic, river, UV, heat, lightning, flood-alert, and snowpack formatting with sample source responses.
- Shared reply timezone, DST boundaries, and preserved timezone configuration.
- Local GIS aliases, ambiguity, spatial relationships, snapshot integrity, and subprocess replies.
- Complete-download verification for manual GeoJSON refresh, using offline fixtures.
- A real loopback MQTT broker with simulated radio events.
- Flood-alarm timing, expiry, renewal, background workers, and restart persistence.
- Installed service configuration and unattended startup behavior.

Automated tests use sample provider data and simulated radio events. They do not
establish physical radio delivery, live four-hour monitoring, or installation and
reboot behavior on target hardware. Follow the platform README for optional
radio/MQTT diagnostics and the [installer validation guide](../installers/VALIDATION.md)
for installation checks.

## Dependencies

The service packages use MeshCore CLI, MeshCore, Paho MQTT, pyserial, aMQTT, tzdata for configurable IANA timezones, and Shapely/pyproj for local GIS calculations.
Dependency pins are maintained in the [Linux requirements](../meshcore_mqtt_service/requirements.txt)
and [Windows requirements](../meshcore_mqtt_service_windows/requirements.txt).

Do not commit API keys, MQTT passwords, virtual environments, runtime databases, or generated cache files to a public repository.

See the [command reference](../meshcore_mqtt_service/COMMAND_REFERENCE.md) for exact replies, coverage, and failures. Restart the service after configuration changes.

## Installer builds and documentation inventory

```console
python tools/build_installers.py
python -m unittest discover -s tools -p "test_installers.py"
```

Run these commands from the repository root. Installer builds require the toolchain
specified in the [build instructions](../INSTALL.md#build-and-validation). Building
an installer does not install or start a service. Source selection is maintained
in `tools/build_installers.py`; standalone service ZIP selection is maintained in
`tools/package_services.py`. Complete-workspace installers include `docs/` so the
root README's topic links remain available after installation. Standalone service
ZIPs contain the platform documentation and require shared GIS data separately.

Rebuild distribution artifacts after the final included source or documentation
edit when delivering updated packages. Existing versioned artifacts and their
validation records describe the source snapshot used for that build; a repository
documentation edit does not update those artifacts.

## Documentation maintenance

The root README introduces capabilities and the end-user workflow. Platform
READMEs document setup, operation, provider constraints, and tuning. Command
references own exact syntax and response contracts; function references describe
implementation entry points. Data guides own acquisition, loading, provenance,
freshness, licensing, and repair procedures.

Retain technical constraints and evidence boundaries when editing prose. Keep
paired service guidance aligned, preserve exact response examples, and verify
relative links and heading anchors after moving material. Archived distributions
and unmodified supplier receipts retain their historical content.

### README artwork and badges

The [README banner](assets/readme-hero.svg) and local SVG badges are maintained
under `docs/assets/` and included by the complete-workspace installer inventory.
The banner's channel exchange is illustrative. Equivalent text examples and
capability descriptions remain in the README for accessibility.

The version badge follows `VERSION` in `tools/build_installers.py`; the command
badge follows both platform configurations. The offline-GIS badge identifies
EBMUD-area coverage. Update these assets when the corresponding facts change.
These labels describe source capabilities and the distribution version; they do
not represent live CI results or hardware validation.


## Wildfire maintenance and verification

Run `python tools/prepare_wildfire_data.py` to update and mirror the complete
NWS boundary seed. Review `data/wildfire/manifest.json` and polygon changes.
Dynamic observations belong to package runtime directories and are excluded
from distributions. Both standalone ZIPs include their wildfire seed and guide.

Run `python -m unittest discover -s tests -p test_wildfire.py` and
`python -m unittest discover -s tests -p test_command_programs.py` from each
platform package, followed by the complete package suites. Run installer tests
from the repository root with `python -m unittest discover -s tools -p test_installers.py`.
Rebuild service ZIPs and installers after final documentation changes. The
[wildfire guide](../meshcore_mqtt_service/WILDFIRE_GUIDE.md) records source and deployment limits.


Generated basin-plan, flood-impact and USGS-water downloads follow the existing
root `.gitignore` download-on-demand policy and are excluded from installer
payloads. Their maintained tools, documentation and curated inputs remain
included; locally acquired datasets are retained on disk. See [water-data setup](WATER_DATA_SETUP.md).

For point smoke/fuel-danger changes, run `test_fire_environment.py` in both
packages. Live public-source checks do not validate authenticated FEMS access.
See [source and configuration details](../meshcore_mqtt_service/WILDFIRE_GUIDE.md#point-smoke-and-fuel-danger).

## Landslide verification and reference updates

Run `tests/test_landslide.py`, `tests/test_command_programs.py`, and full unittest
discovery in both platform packages. Preserve byte parity for landslide source,
tests, guide, and `data/landslide/` references. Review source station coordinates,
metadata, and California/Nevada boundary changes before updating manifests and hashes.
Keep the documented Castro Peak coordinate correction and discontinued Highway 50
exclusion explicit. [Reference provenance and limits](../meshcore_mqtt_service/LANDSLIDE_GUIDE.md#usgs-station-catalog-and-provenance).

## Water maintenance and offline checks

The [terminal command reference](CLI_REFERENCE.md) lists every executable collection
program, refresh mode, validator, satellite subcommand, and command-program option.
The [water setup guide](WATER_DATA_SETUP.md) defines acquisition order, current-only
USGS retention, static index rebuilds, independent NOAA identifier review, and source
failure handling. Runtime caches, review overlays, sidecars, and downloaded
collections are local state; curated review rules and small source evidence tables
remain maintained inputs.

From the repository root, run these offline gates with the declared dependencies:

```console
python tools/check_documentation.py
python -m unittest discover -s tools -p "test_*.py"
python -m unittest discover -s data/basin_plans -p "test_*.py"
python -m unittest discover -s data/flood_impacts -p "test_*.py"
python -m unittest discover -s data/usgs_water -p "test_*.py"
python -m unittest discover -s data/ebmud -p "test_*.py"
python -m unittest discover -s satellite_database -p "test_*.py"
```

Run full `tests/` discovery separately in each service package. The documentation
checker compares registrations, GIS fields, wildfire categories, subscription
controls, terminal flags, local links, paired guides, source-derived function
indexes, badge counts, and Git publication rules. It also verifies all 309 tagged
[response examples](../meshcore_mqtt_service/RESPONSE_EXAMPLES.md) per package,
including exact UTF-8 byte counts and command/field/category/control coverage. Links to deliberately ignored
water catalogs are recognized as generated destinations, not asserted to be
present after a fresh clone. Their setup instructions remain linked.

## GitHub configuration and dependency review

`.github/workflows/ci.yml` defines offline Linux/Windows checks for both packages,
plus documentation, installer configuration, GUI widget, data-tool, and satellite
tests on both operating systems. The service matrix selects Python 3.11 and 3.13 on both
operating systems; the documentation/tools matrix uses Python 3.13. Its dependency
installation includes the pinned dataset maintenance and GUI runtime requirements.
Qt widget tests run with the offscreen platform plugin; Linux preparation installs
the EGL, OpenGL, and keyboard runtime libraries required by Qt.
Windows compiler installation and tooling tests both use Windows PowerShell 5.1.
An explicit PS2EXE 1.0.18 import precedes the tooling suite, and the Python exit
code is propagated to the job. The compiler exercises the dataset maintenance
entry point; tests requiring a local Inno Setup compiler or
a native Linux service account remain conditional.
Actions use verified commit pins for checkout v7.0.1 and setup-python v7.1.0;
checkout credentials are not persisted, and workflow permissions are read-only.
Checks run on pushes, pull requests, and manual dispatch. This workflow performs
no provider acquisition, radio operation, OS-service installation, deployment,
or release publication. Local verification does not establish hosted success;
GitHub Actions results must be checked for each published revision.

`.github/dependabot.yml` covers GitHub Actions and all maintained pip requirement
directories, including `installers/datasets/gui/requirements.txt` and its
`requirements-build.txt` packaging dependencies. Cross-directory dependency
grouping keeps each shared dependency's service, dataset, and GUI requirement
changes in review together when constraints permit. Updates require review and
verification. No automatic merge or release process is configured.

Official references: [checkout](https://github.com/actions/checkout),
[Python setup](https://github.com/actions/setup-python), and
[Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).

GitBook can import the maintained Markdown through an explicitly configured Git
Sync. No hosted site or synchronization is configured by these local updates.
Existing content must be imported from Git into an empty target; applying a
starter template or choosing the reverse initial synchronization can replace
repository documentation. [Documentation index](README.md).

Local `.env.example` and `.env.*.example` templates remain trackable. Credential
backups matching `environment.json.*` are excluded except named distributable
examples/templates. Root-level logs and all rotated `*.log.*` variants remain
local; nested reference receipts and test fixtures are not blanket-ignored.
