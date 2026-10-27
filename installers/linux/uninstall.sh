#!/usr/bin/env bash
# Retain installed versions, settings and reference/runtime data for recovery.
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
source "$source_dir/installers/desktop/maintenance_lock.sh"
meshcore_lock_acquire
trap meshcore_lock_release EXIT
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
systemctl disable --now meshcore-ems.service
rm -f -- /etc/systemd/system/meshcore-ems.service /usr/local/bin/meshcore-satellites
systemctl daemon-reload
echo 'Service removed. Program versions, /etc/meshcore-ems and /var/lib/meshcore-ems were retained.'
