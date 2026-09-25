#!/usr/bin/env bash
# Online installer for Debian 12+/Ubuntu 24.04+/Raspberry Pi OS Bookworm or newer.
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
port=''
channel=''
start_service=1
while (($#)); do
    case "$1" in
        --port) port=${2:?Missing serial device}; shift 2 ;;
        --channel) channel=${2:?Missing channel name}; shift 2 ;;
        --no-start) start_service=0; shift ;;
        --help) echo 'Usage: installer.run [--port /dev/serial/by-id/...] [--channel NAME] [--no-start]'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
[[ $EUID -eq 0 ]] || { echo 'Run this installer with sudo.' >&2; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'A running systemd Linux installation is required.' >&2; exit 1; }
command -v apt-get >/dev/null || { echo 'This installer supports Debian/Ubuntu/Raspberry Pi OS with apt.' >&2; exit 1; }
if [[ -z $port && -f /etc/meshcore-ems/config.json ]] && command -v python3 >/dev/null; then
    port=$(python3 -c 'import json; print(json.load(open("/etc/meshcore-ems/config.json")).get("serial_port", ""))')
fi
if [[ -z $port ]]; then
    shopt -s nullglob
    devices=(/dev/serial/by-id/*)
    ((${#devices[@]})) || devices=(/dev/ttyACM* /dev/ttyUSB*)
    if ((${#devices[@]} == 1)); then
        port=${devices[0]}
    elif [[ -t 0 ]]; then
        printf 'Discovered serial devices:\n'; printf '  %s\n' "${devices[@]}"
        read -r -p 'Companion serial device: ' port
    else
        echo 'Specify --port /dev/serial/by-id/... (or /dev/ttyUSB0).' >&2; exit 2
    fi
fi
[[ $port =~ ^/dev/tty(ACM|USB)[0-9]+$ || $port =~ ^/dev/serial/by-id/[A-Za-z0-9_.:+-]+$ ]] || {
    echo 'Invalid USB serial path.' >&2; exit 2;
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
release=$(mktemp -d /opt/meshcore-ems/releases/v0.2.0-alpha.XXXXXXXX)
cp -a "$source_dir/." "$release/"
chmod 0755 "$release"
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -I -m pip install --disable-pip-version-check -r "$release/meshcore_mqtt_service/requirements.txt" -r "$release/satellite_database/requirements-tracking.txt"
"$release/.venv/bin/python" -I -m pip check
args=(--root "$release" --state /var/lib/meshcore-ems --config-dir /etc/meshcore-ems --platform linux --port "$port")
[[ -z $channel ]] || args+=(--channel "$channel")
previous=$(readlink -f /opt/meshcore-ems/current 2>/dev/null || true)
was_active=0
systemctl is-active --quiet meshcore-ems.service && was_active=1
changed_link=0
config_backup=''
if [[ -f /etc/meshcore-ems/config.json ]]; then
    config_backup="$release/config.rollback.json"
    cp /etc/meshcore-ems/config.json "$config_backup"
    chmod 0600 "$config_backup"
fi
recover() {
    status=$?
    trap - ERR
    if [[ -n $previous ]]; then
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
chown -R meshcore-ems:meshcore-ems /var/lib/meshcore-ems
chown root:meshcore-ems /etc/meshcore-ems/*.json
chmod 0640 /etc/meshcore-ems/*.json
"$release/.venv/bin/python" "$release/meshcore_mqtt_service/service_runner.py" --config /etc/meshcore-ems/config.json --state-dir /var/lib/meshcore-ems/runtime --environment /etc/meshcore-ems/environment.json --check
ln -sfn "$release" /opt/meshcore-ems/current
changed_link=1
install -m 0644 "$release/installers/linux/meshcore-ems.service" /etc/systemd/system/meshcore-ems.service
install -m 0755 "$release/installers/linux/satellite-catalog" /usr/local/bin/meshcore-satellites
systemctl daemon-reload
systemctl enable meshcore-ems.service
if ((start_service)); then
    systemctl start meshcore-ems.service
    sleep 3
    if ! systemctl is-active --quiet meshcore-ems.service; then
        echo 'Service did not stay running. Inspect: journalctl -u meshcore-ems -n 50' >&2
        false
    fi
fi
trap - ERR
printf 'Installed v0.2.0-alpha. Settings: /etc/meshcore-ems/config.json\n'
printf 'Status: systemctl status meshcore-ems\nLogs: journalctl -u meshcore-ems -f\n'
printf 'The service manager status does not establish radio reception.\n'
