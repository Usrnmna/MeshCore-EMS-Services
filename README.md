# MC-EMS-Services

Python services that use MQTT and a USB-connected MeshCore Companion Node to share concise, useful local weather and other important information over the MeshCore network.

## About

MC-EMS-Services is intended to turn local information into short messages that are practical to read on a mesh device. A Python service gathers or prepares information, publishes it through MQTT, and a bridge connected to the USB Companion Node carries the message onto MeshCore.

```text
Local information → Python service → MQTT broker → MeshCore bridge → USB Companion Node → MeshCore network
```

The exact data sources, message topics, and delivery schedule depend on the service and bridge configuration.

## Project files

| File | Purpose |
| --- | --- |
| `README.md` | Project overview and setup guidance. |

There are currently no Python programs or configuration files in this folder. Add each service to the table as its files become available, including what information it sends, how to configure it, and how to run it.

## What you need

- A Python installation for the services.
- An MQTT broker accessible to the Python services and the MeshCore bridge.
- A MeshCore Companion Node connected by USB and a bridge configured to use it.
- Any credentials or data-source access required by the individual services.

## Getting started

1. Connect the USB Companion Node and confirm the MeshCore bridge can communicate with it.
2. Configure the bridge and services to use the same MQTT broker and compatible topics.
3. Add and configure a service, including its local area and any required data-source credentials.
4. Run the bridge and service, then check that a short message arrives on the intended MeshCore destination.

Service-specific installation commands and settings will be documented here when the program files are added. Keep passwords and API keys out of this README and out of version control.

## Intended message style

Messages should prioritize current, locally relevant conditions and use brief wording that is easy to read over a low-bandwidth mesh connection. Include a location and observation time when they help readers judge whether the information is still useful.
