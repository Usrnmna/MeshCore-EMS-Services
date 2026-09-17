# MC-EMS-Services

Python services that use MQTT and a USB-connected MeshCore Companion Node to share concise, useful local weather and other important information over the MeshCore network.

## About

MC-EMS-Services is intended to turn local information into short messages that are practical to read on a mesh device. The planned flow is for Python programs to gather and shorten the information, publish it through MQTT, and use a bridge connected to the USB Companion Node to carry it onto MeshCore.

```text
Local information → Python service → MQTT broker → MeshCore bridge → USB Companion Node → MeshCore network
```

The exact data sources, message topics, and delivery schedule depend on the service and bridge configuration.

## Project files

| File | Purpose |
| --- | --- |
| `README.md` | Project overview and setup guidance. |

## Programs being developed

| Program | What it does | How it could help on MeshCore |
| --- | --- | --- |
| **AirNow air quality lookup** (`airnow_aqi.py`) | Takes latitude and longitude on the command line, finds a nearby AirNow monitor, and reports the PM2.5 air quality index, concentration, and a short rating. It needs an AirNow API key. | A brief local air quality update. |
| **CDEC latest readings** (`cdec_latest.py`) | Searches California Data Exchange Center stations near a coordinate pair and returns the latest valid reading for each sensor category and reporting interval, with units and timestamps. | Local water, weather, or related station readings when available. |
| **Nearby river stations** (`nearby_river_stations.py`) | Finds stations within 30 miles of a coordinate pair from the CDEC river stage report. It returns stage data, AS/FS values, distance, and the original report row. | Nearby river level information with the source details retained for checking. |
| **Caltrans highway conditions** (`highway_info.py`) | Retrieves California highway information by route number and formats active restrictions into compact, separate text blocks. | Short road closure, restriction, or advisory messages. |
| **MeshCore MQTT bridge** | Connects an MQTT broker to a MeshCore Companion Node over USB serial. A separate Windows package was prepared for COM11 with configuration and setup/start scripts. | Carries prepared messages between the broker and MeshCore. |

The lookup programs currently produce their own command-line or structured output. They still need a shared message formatter, MQTT publishing configuration, and destination rules before this folder can operate as a combined information service.

## What you need

- A Python installation for the services.
- An MQTT broker accessible to the Python services and the MeshCore bridge.
- A MeshCore Companion Node connected by USB and a bridge configured to use it.
- Any credentials or data-source access required by the individual services.

## Getting started

1. Connect the USB Companion Node and confirm the MeshCore bridge can communicate with it.
2. Configure the bridge and services to use the same MQTT broker and compatible topics.
3. Add and configure a service, including its local area and any required data-source credentials.
4. Once a lookup program is connected to MQTT, run the bridge and service, then check that a short message arrives on the intended MeshCore destination.

Service-specific installation commands and settings will be documented here when the program files are added. Keep passwords and API keys out of this README and out of version control.

## Intended message style

Messages should prioritize current, locally relevant conditions and use brief wording that is easy to read over a low-bandwidth mesh connection. Include a location and observation time when they help readers judge whether the information is still useful.
