#!/usr/bin/env bash
# Remove only this runtime after the data manager's ownership/dependency checks.
set -euo pipefail
prefix=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
dataset=$(cat "$prefix/current/payload/dataset-id.txt")
case "$dataset" in ebmud|basin_plans|flood_impacts|usgs_water|wildfire|landslide|california_state_parks|satellites) ;; *) exit 2 ;; esac
[[ $prefix == "/opt/meshcore-ems-data/$dataset" && $EUID -eq 0 ]] || { echo 'Run the installed uninstaller with sudo.' >&2; exit 1; }
[[ $# -eq 0 || ( $# -eq 1 && $1 == --purge ) ]] || { echo 'Usage: uninstall [--purge]'; exit 2; }
"$prefix/dataset" uninstall "$@"
rm -rf -- "$prefix"
echo "Removed $dataset maintenance runtime. Unowned or modified data may have been retained."
