# MC-EMS-Services

Python services that connect an MQTT broker to a USB MeshCore Companion Node and deliver concise, useful local weather, environmental, river, and highway information over a MeshCore channel.

## About

MC-EMS-Services turns a MeshCore channel into a small command-driven information service. A user sends a supported command on the configured channel, the attached computer runs the matching Python lookup, and the result is returned to the same channel with the sender's name.

```text
MeshCore user
    ↓ command over LoRa
USB Companion Node
    ↓ serial connection
Linux or Windows service
    ├─ runs the requested local Python program
    ├─ publishes radio events and commands through MQTT
    └─ sends a concise reply back to the same MeshCore channel
```

The default channel is `#autatestbot`. The channel must already exist on the Companion Node.

## Included service folders

| Folder | Platform | Purpose |
| --- | --- | --- |
| [`meshcore_mqtt_service/`](meshcore_mqtt_service/) | Linux | Linux launcher, local MQTT broker, MeshCore bridge, command responder, lookup scripts, configuration, and tests. |
| [`meshcore_mqtt_service_windows/`](meshcore_mqtt_service_windows/) | Windows 10 x64 | Independent Windows package with its own settings, runtime data, setup scripts, tests, and double-click launcher. |
| [`highway_info/`](highway_info/) | Standalone Python | Original Caltrans highway information program. The service folders contain their own adapted copies for `!traffic`. |

The Linux and Windows folders are self-contained. Each uses its own virtual environment, configuration, MQTT namespace, and SQLite request database.

## MeshCore commands

Send commands from another MeshCore node on `#autatestbot`.

| Command | Example | Result | Data source |
| --- | --- | --- | --- |
| `!status` | `!status` | Confirms that the local command service is running. | Local service |
| `!time` | `!time` | Returns the current UTC time. | Local system |
| `!aqi` | `!aqi 37.7749 -122.4194` | Nearest-monitor PM2.5 AQI, concentration, rating, station, distance, and observation time. | AirNow |
| `!traffic` | `!traffic 80` | Compact active California highway restrictions for route 1–999. | Caltrans |
| `!rivers` | `!rivers 39.0000, -121.0000` | Nearby river stations within 15 miles, including stage, report time, action stage, and flood stage. | CDEC and NOAA |
| `!uv` | `!uv Sacramento` | Current UV index and risk level for coordinates, a US ZIP code, or a city and state. | CurrentUVIndex.com plus location lookup |

Examples of accepted UV locations include `!uv 95814`, `!uv Reno NV`, and `!uv 38.5816, -121.4944`. City names without a state default to California.

AQI lookups require an `AIRNOW_API_KEY` environment variable. Traffic, river, status, time, and UV commands do not require an API key. Internet access is required for all external data lookups.

## Main features

- USB serial connection to a MeshCore Companion Node through the interactive `-S` device selector.
- Bundled local MQTT broker for operation without a separate broker installation.
- Optional external MQTT broker with username/password environment variables and TLS support.
- Radio events published as structured MQTT messages with available text, channel, timestamps, RSSI, SNR, paths, and other metadata.
- Same-channel replies prefixed with the saved sender name, such as `@Alice`.
- Exact command matching, validated arguments, fixed script paths, execution timeouts, and no shell interpretation of received text.
- Persistent SQLite request history, duplicate suppression, stale-message rejection, sender cooldowns, and bounded request queues.
- Durable QoS 1 MQTT event outbox with automatic reconnection.
- Long replies divided into as many as four 150-byte messages by default.
- Separate Linux and Windows MQTT ports and topic namespaces, allowing both copies to coexist on one network.

## Quick start

### Linux

Requirements: Python 3.11 or newer, virtual-environment support, and permission to access the USB serial device.

```bash
cd meshcore_mqtt_service
export AIRNOW_API_KEY="YOUR_AIRNOW_API_KEY"  # only needed for !aqi
bash Start-Service.sh
```

Choose the attached `/dev/ttyACM*` or `/dev/ttyUSB*` device when prompted. Keep the terminal open while the service is running. If access is denied, add the user to the serial-device group used by the Linux distribution, commonly `dialout`, then sign in again.

See the [Linux service README](meshcore_mqtt_service/README.md) for setup, operating modes, command details, and verification instructions.

### Windows 10 x64

Requirements: 64-bit Python 3.11 or newer and a USB-connected MeshCore Companion Node.

1. Open [`meshcore_mqtt_service_windows/`](meshcore_mqtt_service_windows/).
2. Run `setup.cmd` once on a new computer.
3. Double-click `Start-Service.exe`.
4. Select the attached COM device in the MeshCore `-S` selector.
5. Keep the console window open while the service is running.

Set `AIRNOW_API_KEY` before starting the service if `!aqi` will be used. No COM port is hard-coded or saved, and administrator permission is normally unnecessary.

See the [Windows service README](meshcore_mqtt_service_windows/README.md) for complete setup and diagnostic instructions.

## Default platform settings

| Setting | Linux folder | Windows folder |
| --- | --- | --- |
| MQTT address | `127.0.0.1:1883` | `127.0.0.1:1884` |
| Topic prefix | `meshcore/usb` | `meshcore/windows` |
| MQTT client ID | `meshcore-usb-bridge` | `meshcore-windows-bridge` |
| Python environment | `.venv-linux/` | `.venv/` |
| Runtime database | `runtime/bridge.sqlite3` | `runtime/bridge.sqlite3` |
| Default channel | `#autatestbot` | `#autatestbot` |
| Serial speed | 115200 baud | 115200 baud |

Edit the appropriate folder's `config.json` to change the channel, broker, topics, timeouts, cooldowns, reply limits, or command definitions. Restart the service after changing its configuration.

## MQTT interface

The service can be used as a MeshCore-to-MQTT bridge even when the automatic responder is disabled.

| Topic suffix | Purpose |
| --- | --- |
| `events/<event_name>` | Radio events and available packet metadata. |
| `events/bot_reply` | Records an automatic reply accepted by the local radio. |
| `command` | Accepts non-retained JSON MeshCore CLI requests. |
| `results/<id>` | Returns MQTT command output and status. |
| `errors` | Reports rejected MQTT commands. |
| `status` | Retained online/offline state and last will. |

Supported MQTT commands include `infos`, `ver`, `contacts`, `self_telemetry`, `clock`, `msg`, and `chan`.

Example request:

```json
{"id":"info-001","argv":["infos"]}
```

Use a unique request ID for every intentional command. Restrict publishing access to the command topic when an external broker is used.

## Reliability and message handling

The service records requests before execution so sender names and request state survive restarts. It ignores duplicate, stale, future-dated, malformed, self-originated, and reply-like messages. Interrupted scripts and failed radio sends are recorded without automatic retransmission because execution or transmission may already have occurred.

A `sent` result means the local Companion Node accepted the message for transmission. It does not confirm reception by a remote node. Weather, air-quality, river, and highway reports are informational source data; they are not forecasts or emergency alerts.

## Development and verification

Both service folders include tests for:

- Command parsing and input validation.
- Script execution, timeouts, failures, and output limits.
- Sender retention and same-channel tagged replies.
- Duplicate suppression and persistent request state.
- AQI, traffic, river, and UV formatting with sample source responses.
- A real loopback MQTT broker with simulated radio events.

The Windows package reports 42 passing tests on Windows 10 x64 with Python 3.13. A live read-only check connected to a COM11 node, published events, and completed an MQTT `infos` request. Native Linux execution, live external-data calls for every provider, and automatic over-the-air reply delivery have not all been verified. Follow the platform README when repeating checks.

## Dependencies

The service packages pin these main dependencies:

- `meshcore-cli 1.6.4`
- `meshcore 2.3.11`
- `paho-mqtt 2.1.0`
- `pyserial 3.5`
- `amqtt 0.12.1`

Do not commit API keys, MQTT passwords, virtual environments, runtime databases, or generated cache files to a public repository.
