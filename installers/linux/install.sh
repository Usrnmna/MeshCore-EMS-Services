#!/usr/bin/env bash
# Online installer for Debian 12+/Ubuntu 24.04+/Raspberry Pi OS Bookworm or newer.
set -euo pipefail
umask 0027
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
# Detect the USB radio at each service start instead of saving today's tty number.
port=''
transport=''
tcp_host=''
tcp_port=''
ble_address=''
channel=''
channels_config=''
start_service=1
while (($#)); do
    case "$1" in
        --port) port=${2:?Missing serial device}; shift 2 ;;
        --transport) transport=${2:?Missing transport}; shift 2 ;;
        --tcp-host) tcp_host=${2:?Missing IP address}; shift 2 ;;
        --tcp-port) tcp_port=${2:?Missing TCP port}; shift 2 ;;
        --ble-address) ble_address=${2:?Missing BLE address}; shift 2 ;;
        --channel) channel=${2:?Missing channel name}; shift 2 ;;
        --channels-config) channels_config=${2:?Missing channels JSON path}; shift 2 ;;
        --no-start) start_service=0; shift ;;
        --help) echo 'Usage: installer.run [--transport serial|tcp|ble] [--port auto|DEVICE] [--tcp-host IP --tcp-port 5000] [--ble-address ADDRESS] [--channel NAME | --channels-config FILE.json] [--no-start] (omitted connection options preserve settings; new installs default to serial auto)'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
[[ -z $channel || -z $channels_config ]] || { echo 'Use --channel or --channels-config, not both.' >&2; exit 2; }
[[ -z $channels_config || -f $channels_config ]] || { echo 'Channels JSON file does not exist.' >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo 'Run this installer with sudo.' >&2; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'A running systemd Linux installation is required.' >&2; exit 1; }
command -v apt-get >/dev/null || { echo 'This installer supports Debian/Ubuntu/Raspberry Pi OS with apt.' >&2; exit 1; }
[[ ${port,,} != auto ]] || port='auto'
[[ -z $port || $port == auto || $port =~ ^/dev/tty(ACM|USB)[0-9]+$ || $port =~ ^/dev/serial/by-id/[A-Za-z0-9_.:+-]+$ ]] || {
    echo 'Use auto or a valid USB serial path.' >&2; exit 2;
}
echo 'Installing Python, serial support, and dependency build tools...'
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip python3-dev build-essential libffi-dev libssl-dev ca-certificates
python3 -c 'import sys; assert (3,11) <= sys.version_info < (3,15), "Python 3.11-3.14 required; use Debian 12+/Ubuntu 24.04+/current Raspberry Pi OS"'
getent group dialout >/dev/null || groupadd --system dialout
id meshcore-ems >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/meshcore-ems --shell /usr/sbin/nologin meshcore-ems
usermod -a -G dialout meshcore-ems
install -d -m 0755 /opt/meshcore-ems/releases
install -d -m 0750 -o root -g meshcore-ems /etc/meshcore-ems
install -d -m 0750 -o meshcore-ems -g meshcore-ems /var/lib/meshcore-ems
# Build in its final path because virtual environments contain absolute paths.
release=$(mktemp -d /opt/meshcore-ems/releases/v0.3.0-beta.XXXXXXXX)
cp -a "$source_dir/." "$release/"
chmod 0755 "$release"
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -I -m pip install --disable-pip-version-check -r "$release/meshcore_mqtt_service/requirements.txt" -r "$release/satellite_database/requirements-tracking.txt"
"$release/.venv/bin/python" -I -m pip check
args=(--root "$release" --state /var/lib/meshcore-ems --config-dir /etc/meshcore-ems --platform linux)
[[ -z $port ]] || args+=(--port "$port")
[[ -z $transport ]] || args+=(--transport "$transport")
[[ -z $tcp_host ]] || args+=(--tcp-host "$tcp_host")
[[ -z $tcp_port ]] || args+=(--tcp-port "$tcp_port")
[[ -z $ble_address ]] || args+=(--ble-address "$ble_address")
[[ -z $channel ]] || args+=(--channel "$channel")
[[ -z $channels_config ]] || args+=(--channels-config "$channels_config")
previous=$(readlink -f /opt/meshcore-ems/current 2>/dev/null || true)
was_active=0
systemctl is-active --quiet meshcore-ems.service && was_active=1
changed_link=0
start_attempted=0
config_backup=''
if [[ -f /etc/meshcore-ems/config.json ]]; then
    config_backup="$release/config.rollback.json"
    cp /etc/meshcore-ems/config.json "$config_backup"
    chmod 0600 "$config_backup"
fi
recover() {
    # Restore only pre-start failures automatically; runtime migrations need matched rollback.
    status=$?
    trap - ERR
    if ((start_attempted)); then
        # Startup can migrate SQLite before reporting failure. Keep the new code
        # and settings together; never launch the old binary against that state.
        systemctl stop meshcore-ems.service || true
        echo 'Service startup failed after runtime migration may have begun. Automatic rollback was not attempted.' >&2
        echo 'The new release/settings are retained and a stop was requested. Check systemctl status meshcore-ems.' >&2
        echo 'For rollback, restore a matching configuration AND runtime snapshot while the service is stopped.' >&2
        echo 'Upgrade snapshots: /var/lib/meshcore-ems/backups/. See MULTI_CHANNEL_GUIDE.md for recovery.' >&2
    elif [[ -n $previous ]]; then
        ((changed_link == 0)) || ln -sfn "$previous" /opt/meshcore-ems/current
        [[ -z $config_backup ]] || cp "$config_backup" /etc/meshcore-ems/config.json
        ((was_active == 0)) || systemctl restart meshcore-ems.service || true
    fi
    echo 'Installation failed; settings/data were retained. Inspect the error above.' >&2
    exit "$status"
}
trap recover ERR
if systemctl cat meshcore-ems.service >/dev/null 2>&1; then
    systemctl stop meshcore-ems.service
fi
"$release/.venv/bin/python" "$release/installers/configure.py" "${args[@]}"
# BlueZ is needed only when this installation actually selects BLE.
if python3 -c 'import json,sys; sys.exit(json.load(open("/etc/meshcore-ems/config.json")).get("connection", {}).get("type") != "ble")'; then
    apt-get install -y bluez
    systemctl enable --now bluetooth.service
fi
chown -R meshcore-ems:meshcore-ems /var/lib/meshcore-ems
chmod -R o-rwx /var/lib/meshcore-ems
find /var/lib/meshcore-ems/runtime -type d -exec chmod 0700 {} +
find /var/lib/meshcore-ems/runtime -type f -exec chmod 0600 {} +
if [[ -d /var/lib/meshcore-ems/backups ]]; then
    chown -R root:root /var/lib/meshcore-ems/backups
    find /var/lib/meshcore-ems/backups -type d -exec chmod 0700 {} +
    find /var/lib/meshcore-ems/backups -type f -exec chmod 0600 {} +
fi
chown root:meshcore-ems /etc/meshcore-ems/*.json
chmod 0640 /etc/meshcore-ems/*.json
# Operators install Python programs here; the service can read but not modify code.
chown -R root:meshcore-ems /etc/meshcore-ems/programs
find /etc/meshcore-ems/programs -type d -exec chmod 0750 {} +
find /etc/meshcore-ems/programs -type f -exec chmod 0640 {} +
"$release/.venv/bin/python" "$release/meshcore_mqtt_service/service_runner.py" --config /etc/meshcore-ems/config.json --state-dir /var/lib/meshcore-ems/runtime --environment /etc/meshcore-ems/environment.json --check
ln -sfn "$release" /opt/meshcore-ems/current
changed_link=1
install -m 0644 "$release/installers/linux/meshcore-ems.service" /etc/systemd/system/meshcore-ems.service
install -m 0755 "$release/installers/linux/satellite-catalog" /usr/local/bin/meshcore-satellites
systemctl daemon-reload
systemctl enable meshcore-ems.service
if ((start_service)); then
    start_attempted=1
    systemctl start meshcore-ems.service
    sleep 3
    if ! systemctl is-active --quiet meshcore-ems.service; then
        echo 'Service did not stay running. Inspect: journalctl -u meshcore-ems -n 50' >&2
        false
    fi
fi
trap - ERR
printf 'Installed v0.3.0-beta. Settings: /etc/meshcore-ems/config.json\n'
printf 'Status: systemctl status meshcore-ems\nLogs: journalctl -u meshcore-ems -f\n'
printf 'The service manager status does not establish radio reception.\n'
