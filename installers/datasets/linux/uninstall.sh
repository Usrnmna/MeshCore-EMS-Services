#!/usr/bin/env bash
# Remove only this runtime after the data manager's ownership/dependency checks.
set -euo pipefail
prefix=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$prefix/current/payload/installers/desktop/maintenance_lock.sh"
meshcore_lock_acquire
trap meshcore_lock_release EXIT
dataset=$(cat "$prefix/current/payload/dataset-id.txt")
case "$dataset" in ebmud|basin_plans|flood_impacts|usgs_water|wildfire|landslide|california_state_parks|satellites) ;; *) exit 2 ;; esac
[[ $prefix == "/opt/meshcore-ems-data/$dataset" && $EUID -eq 0 ]] || { echo 'Run the installed uninstaller with sudo.' >&2; exit 1; }
[[ $# -eq 0 || ( $# -eq 1 && ( $1 == --remove-data || $1 == --purge ) ) ]] || { echo 'Usage: uninstall [--remove-data|--purge]'; exit 2; }
if [[ $# -eq 0 ]]; then
    "$prefix/dataset" uninstall --retain-data
elif [[ $1 == --remove-data ]]; then
    "$prefix/dataset" uninstall
else
    "$prefix/dataset" uninstall --purge
fi
rm -rf -- "$prefix"
echo "Removed $dataset maintenance runtime. Default removal retains all datasets; explicit data removal retains unowned or modified files under the receipt policy."
