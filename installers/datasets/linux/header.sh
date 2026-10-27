#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    --help) echo 'MeshCore EMS @DATASET@ @VERSION@ dataset installer (@ARCH@)'
        echo 'Install: sudo bash installer.run [--root ABSOLUTE_DATA_ROOT]'
        echo 'Inspect: bash installer.run --check | --extract EMPTY_DIRECTORY'
        echo 'Maintenance: /opt/meshcore-ems-data/@DATASET@/dataset ACTION'
        echo 'Remove tools and retain data: sudo /opt/meshcore-ems-data/@DATASET@/uninstall'
        echo 'Explicit managed data removal: uninstall --remove-data [or --purge for modified receipt-owned data]'; exit 0 ;;
esac
line=$(awk '/^__MESHCORE_DATA_PAYLOAD__$/{print NR+1; exit}' "$0")
actual_sha=$(tail -n +"$line" "$0" | sha256sum | cut -d ' ' -f1)
[[ $actual_sha == '@SHA@' ]] || { echo 'Installer payload checksum mismatch.' >&2; exit 1; }
if [[ ${1:-} == --check ]]; then echo '@DATASET@ @ARCH@: payload checksum verified'; exit 0; fi
if [[ ${1:-} == --extract ]]; then
    destination=${2:?Specify an empty destination directory}
    mkdir -p -- "$destination"
    [[ -z $(ls -A -- "$destination") ]] || { echo 'Extraction directory must be empty.' >&2; exit 1; }
    tail -n +"$line" "$0" | tar -xz --no-same-owner -C "$destination"
    exit 0
fi
[[ $(uname -m) == '@ARCH@' ]] || { echo 'This installer requires @ARCH@.' >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo 'Run the installer with sudo.' >&2; exit 1; }
temporary=$(mktemp -d /tmp/meshcore-ems-data.XXXXXXXX)
trap 'rm -rf -- "$temporary"' EXIT
tail -n +"$line" "$0" | tar -xz --no-same-owner -C "$temporary"
bash "$temporary/installers/datasets/linux/install.sh" "$@"
exit 0
__MESHCORE_DATA_PAYLOAD__
