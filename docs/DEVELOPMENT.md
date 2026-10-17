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
| `data/` | EBMUD reference layers and satellite database, exports, and offline source cache. |
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

The root `.gitignore` excludes local environments, service runtime state, Python
bytecode/tool caches, coverage reports, build/distribution directories, credentials,
recovery backups, interrupted archive/export writes, and GIS refresh staging/locks.
The platform and satellite ignore files also protect standalone checkouts. Source Python,
configuration templates, tests, function references, reference SQLite/JSON/CSV data,
and retained raw source receipts remain trackable. Ignore rules do not remove
files that Git already tracks, including previously committed distribution files.

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
