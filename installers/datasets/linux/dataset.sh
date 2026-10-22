#!/usr/bin/env bash
# The selected runtime is independent of the main service installation.
set -euo pipefail
umask 0022
prefix=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
release=$(readlink -f "$prefix/current")
dataset=$(cat "$release/payload/dataset-id.txt")
data_root=$(cat "$prefix/data-root.txt")
action=${1:-status}
[[ $# -eq 0 ]] || shift
exec "$release/venv/bin/python" "$release/payload/installers/datasets/manage.py" "$action" --dataset "$dataset" --root "$data_root" --payload "$release/payload" "$@"
