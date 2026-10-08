# Installer and packaging Python function reference

See [the installation guide](../INSTALL.md) for operator workflows.
These tools change local configuration or build artifacts only when invoked.

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

Initialize installed settings/data without replacing operator state on upgrade.

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
| `main()` | Check paired sources, then atomically replace each validated standalone ZIP. |

<a id="build-installers-py"></a>

## build_installers.py

[Source](build_installers.py)

Build online Windows x64 and Linux x86_64/ARM64 installers from this workspace. Windows compilation needs the .NET Framework C# compiler and Inno Setup 6.7+. Linux .run payloads are architecture-neutral source; architecture is checked at install. No Python runtimes, pip wheels, environments or private state are embedded.

| Function signature | Purpose and behavior |
| --- | --- |
| `sha(data)` | Return the SHA-256 digest used by payload manifests and download checks. |
| `source_files()` | Collect maintained source/data while excluding runtime state and build environments. |
| `stage_payload(destination)` | Create an isolated build snapshot with normalized shell files and an integrity manifest. |
| `linux_installer(payload, output, arch)` | Write a checksum-protected self-extracting Linux installer for the selected architecture. |
| `main()` | Build platform installers and checksums locally; never install or publish them. |
