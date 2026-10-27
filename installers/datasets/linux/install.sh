#!/usr/bin/env bash
# Independent data maintenance runtime; no service or scheduler is installed.
set -euo pipefail
umask 0022
payload=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
source "$payload/installers/desktop/maintenance_lock.sh"
meshcore_lock_acquire
trap meshcore_lock_release EXIT
dataset=$(cat "$payload/dataset-id.txt")
case "$dataset" in ebmud|basin_plans|flood_impacts|usgs_water|wildfire|landslide|california_state_parks|satellites) ;; *) echo 'Invalid dataset identifier.' >&2; exit 2 ;; esac
prefix="/opt/meshcore-ems-data/$dataset"
data_root=/var/lib/meshcore-ems/data
retained_root="/var/lib/meshcore-ems-maintenance/retained-roots/$dataset.txt"
[[ ! -f $retained_root || -L $retained_root ]] || data_root=$(cat "$retained_root")
[[ ! -f "$prefix/data-root.txt" ]] || data_root=$(cat "$prefix/data-root.txt")
while (($#)); do
    case "$1" in
        --root) data_root=${2:?Missing data root}; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
[[ $EUID -eq 0 ]] || { echo 'Run the installer with sudo.' >&2; exit 1; }
[[ $data_root == /* && $data_root != *$'\n'* ]] || { echo 'Data root must be an absolute path.' >&2; exit 2; }
data_root=$(realpath -m -s -- "$data_root")
case "$data_root/" in "$prefix/"*) echo 'Data root must be outside the maintenance installation.' >&2; exit 2 ;; esac
source "$payload/installers/desktop/data_root.sh"
meshcore_protected_data_root "$data_root"
data_root=$MESHCORE_PROTECTED_DATA_ROOT
# Provision the OS Python only when needed. All package dependencies stay private.
if ! python3 -c 'import sys,venv,ensurepip; assert (3,11) <= sys.version_info < (3,14)' 2>/dev/null; then
    command -v apt-get >/dev/null || { echo 'Python 3.11-3.13 and venv are required.' >&2; exit 1; }
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv ca-certificates
fi
python3 -c 'import sys; assert (3,11) <= sys.version_info < (3,14), "Python 3.11-3.13 required"'
install -d -m 0755 "$prefix/releases"
# Venv paths must remain stable: build at the final generation path.
release=$(mktemp -d "$prefix/releases/runtime.XXXXXXXX")
chmod 0755 "$release"
cp -a "$payload" "$release/payload"
python3 -m venv "$release/venv"
"$release/venv/bin/python" -I -m pip install --disable-pip-version-check --only-binary=:all: -r "$release/payload/installers/datasets/requirements.txt"
"$release/venv/bin/python" -I -m pip check
# Publish tools only after their environment succeeds. Prior runtimes remain available.
ln -s "$release" "$prefix/current.next.$$"
mv -Tf "$prefix/current.next.$$" "$prefix/current"
printf '%s\n' "$data_root" > "$prefix/data-root.txt"
cp "$payload/installers/datasets/linux/dataset.sh" "$prefix/dataset"
cp "$payload/installers/datasets/linux/uninstall.sh" "$prefix/uninstall"
chmod 0755 "$prefix/dataset" "$prefix/uninstall"
"$prefix/dataset" install
