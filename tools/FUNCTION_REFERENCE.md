# Installer and packaging Python function reference

See [the installation guide](../INSTALL.md) for operator workflows.
These tools change local configuration or build artifacts only when invoked.
Independent dataset packaging and transactional maintenance are described in
[dataset lifecycle and validation](../docs/DATA_PACKAGES.md) and the
[dataset build reference](../installers/datasets/BUILD.md). The manager, adapters
and builder document their nontrivial functions alongside the implementation.
The shared GeoJSON utilities have a separate [refresh and repair function reference](../data/ebmud/FUNCTION_REFERENCE.md).
Current GIS source and documentation updates do not imply rebuilt artifacts;
see [source deployment](../INSTALL.md#gis-source-deployment).

This reference covers functions defined in maintained application files, including
methods and nested callbacks. Test helpers, imported library functions, and generated
files are excluded. Signatures show inputs and defaults; explanations describe the
work and important effects. Update this reference and source docstrings together
when a function changes. These descriptions are source documentation, not evidence
that a live service, device, or provider was tested.

## Modules

- [../installers/configure.py](#installers-configure-py)
- [package_services.py](#package-services-py)
- [build_installers.py](#build-installers-py)

<a id="installers-configure-py"></a>

## ../installers/configure.py

[Source](../installers/configure.py)

Initialize installed settings/data without replacing operator state on upgrade. Save a default responder.timezone for legacy installs and preserve an operator's existing shared timezone.

| Function signature | Purpose and behavior |
| --- | --- |
| `write_json(path, value)` | Replace one JSON file atomically; restrict new POSIX files before replacement. |
| `channel_settings(package)` | Use the installed package's schema and migration, without opening the radio. |
| `channel_settings.validate(config, root)` | Check channel privacy first, then enabled command scripts and limits. |
| `import_channels(responder, path)` | Apply registry and explicit assignments; reject typos instead of ignoring them. |
| `backup_state(config_path, state)` | Save a dated config and consistent SQLite snapshots before changing settings. |
| `configure_connection(config, package, platform, port, transport, tcp_host, tcp_port, ble_address)` | Merge explicit transport options, then validate before writing installed settings. |
| `configure(root, state, config_dir, platform, port=None, channel=None, channels_config=None, transport=None, tcp_host=None, tcp_port=None, ble_address=None)` | Merge settings, validate, back up existing state, then write installed files. Existing program assignments are preserved. An existing registry disables new programs until explicitly assigned; legacy settings retain their one channel. This function never connects to or programs a radio, and never starts services. |

<a id="package-services-py"></a>

## package_services.py

[Source](package_services.py)

Build standalone service ZIPs from current source, without local state. Run from anywhere: python tools/package_services.py Shared implementations must agree; resolve differences before packaging rather than silently distributing two versions. Platform-specific files stay separate.

| Function signature | Purpose and behavior |
| --- | --- |
| `package_files(name)` | Return the explicit distributable inventory; reject missing files or scripts. |
| `main()` | Check paired sources, then atomically replace each validated standalone ZIP and write its SHA-256 file. |

<a id="build-installers-py"></a>

## build_installers.py

[Source](build_installers.py)

Build online Windows x64 and Linux x86_64/ARM64 installers from this workspace. Windows compilation needs the .NET Framework C# compiler and Inno Setup 6.7+. Linux .run payloads are architecture-neutral source; architecture is checked at install. No Python runtimes, pip wheels, environments or private state are embedded.

| Function signature | Purpose and behavior |
| --- | --- |
| `sha(data)` | Return the SHA-256 digest used by payload manifests and download checks. |
| `source_files()` | Collect maintained source, documentation, and data without runtime state or environments. Include the linked topic guides and artwork, release comparison, repository instructions, root Git metadata, and archive guidance; exclude recovery ZIPs. |
| `stage_payload(destination)` | Create an isolated build snapshot with normalized shell files and an integrity manifest. |
| `linux_installer(payload, output, arch)` | Write a checksum-protected self-extracting Linux installer for the selected architecture. |
| `main()` | Build platform installers and checksums locally; never install or publish them. |


## prepare_wildfire_data.py

`main()` retrieves the California reference boundary and NWS fire-weather
polygons, selects full polygons with material California overlap, validates
interstate coverage, records source dates and a SHA-256 digest, and mirrors the
seed to both packages. See [wildfire data provenance](../data/wildfire/README.md).
`package_services.package_files()` includes both wildfire seed files, the guide
and service module; `main()` verifies paired copies before producing ZIPs.

`build_installers.water_download_rules()` reads the root-anchored water-collection
exclusions and exceptions from `.gitignore`. `download_only()` applies that
specific publication policy without requiring Git during a distribution build.
Generated water snapshots are excluded; curated inputs remain in the payload.


## check_documentation.py

[Source](check_documentation.py). Run from a Git checkout with
`python tools/check_documentation.py`; no network or device access occurs.

| Function signature | Purpose and behavior |
| --- | --- |
| `git(*arguments, input_bytes=None)` | Run a read-only Git query in the repository and return its captured bytes. |
| `read_text(path)` | Read UTF-8 or legacy CP1252 documentation without rewriting its encoding. |
| `maintained_paths()` | Include tracked and new publishable files, excluding deleted paths and local outputs. |
| `prose(text)` | Remove fenced examples before interpreting Markdown links or heading anchors. |
| `anchors(text)` | Collect explicit HTML anchors and duplicate-aware GitHub-style heading IDs. |
| `source_constant(path, name)` | Read a literal published vocabulary without importing application or provider code. |
| `check_commands()` | Check registered command programs, subcommand vocabulary, paired guides, and badges. |
| `check_response_examples()` | Verify command, GIS-field, context-category and alarm-control response coverage, paired catalogs, exact tagged byte counts and the 150-byte limit. |
| `function_definitions(node, prefix='')` | Yield qualified function names and definitions, including methods and nested callbacks. |
| `check_function_references()` | Compare focused water/wildfire signatures with the current source definitions. |
| `check_links(paths)` | Check local paths/fragments; recognize explicitly ignored generated water outputs. |
| `check_cli_options(paths)` | Require every literal argparse flag/subcommand from maintained entry points in the CLI guide. |
| `check_publication()` | Keep generated/private files out of Git and retain required maintained sources. |
| `main()` | Run offline documentation gates and report checks separately from generated links. |
