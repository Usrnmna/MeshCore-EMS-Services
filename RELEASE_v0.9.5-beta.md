# Version 0.9.5 - Beta

Release identifier: `v0.9.5-beta`. Release date: October 20, 2026.

Both platform packages provide 28 dedicated MeshCore command programs. This
release adds California and Nevada landslide information and alert monitoring,
and includes the current wildfire, weather, water, highway, and local GIS functions.

## Landslide commands

- `!slidewarn LOCATION` reports applicable NWS alerts mentioning landslides,
  debris flows, mudslides, or mud flows, including watches under their official names.
- `!slidealarm on LOCATION` enrolls a temporary sender/channel subscription.
  Defaults are four hours with checks every five minutes. `status` reports its
  state; `off` cancels it. Standalone Python execution does not enroll subscriptions.
- `!slideinfo LOCATION` reports the nearest eligible station in the reviewed
  California USGS catalog, its distance, monitored variables, graph cadence, and link.

Locations accept ZIP/ZIP+4, city/state, or decimal latitude/longitude. Both
California and Nevada are supported, including both sides of Lake Tahoe. Bare
cities default to California; Nevada examples include `Reno NV`, `89501`,
`Las Vegas Nevada`, and `39.25,-119.96`.

The reviewed USGS index lists no Nevada stations. A nearest California station
does not establish local conditions or warning coverage. Station telemetry is
unverified, and an empty alert response is not an all-clear. Reference polygons,
station metadata, source provenance, and checksums are bundled in both packages.
See the [landslide guide](meshcore_mqtt_service/LANDSLIDE_GUIDE.md).

## Existing capabilities and upgrades

Nine wildfire commands remain included, together with the existing weather,
flood, snowpack, air-quality, river, highway, and offline local GIS programs.
Serial, Bluetooth LE, TCP, channel assignments, shared timezone settings, and
external operator programs retain their established behavior.

Upgrade configuration preserves existing settings and channel assignments.
New commands are initially unassigned in an existing channel registry; assign
them to the intended channels and restart the installed service. The smaller
standalone packages require shared EBMUD data separately for local GIS queries.
See [installation and migration](INSTALL.md) and the
[complete command reference](meshcore_mqtt_service/COMMAND_REFERENCE.md).

## Release artifacts and verification

| Artifact | Target |
| --- | --- |
| `meshcore_mqtt_service.zip` | Linux standalone source package |
| `meshcore_mqtt_service_windows.zip` | Windows standalone source package |
| `MeshCore-EMS-v0.9.5-beta-windows-x64-setup.exe` | Windows 10/11 x64 online installer |
| `MeshCore-EMS-v0.9.5-beta-linux-x86_64.run` | Linux x86_64 online installer |
| `MeshCore-EMS-v0.9.5-beta-raspberry-pi-arm64.run` | Raspberry Pi 64-bit online installer |
| `MeshCore-EMS-v0.9.5-beta-installers.zip` | All three installers, guides, and checksums |

Standalone packages include `VERSION.txt` containing `v0.9.5-beta`. Installer
manifests and filenames use the same identifier; Windows assembly/file metadata
uses `0.9.5.0`. SHA-256 files identify the generated artifacts. Runtime databases,
credentials, local environments, and generated water downloads are excluded.

Host regression results and artifact verification limits are recorded in
[installer validation](installers/VALIDATION.md). These checks do not establish
physical radio delivery, native Linux service operation, or installed-service
acceptance. Installers obtain dependencies online; the Windows installer is unsigned.
