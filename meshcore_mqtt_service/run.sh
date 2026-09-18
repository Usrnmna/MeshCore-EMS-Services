#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv-linux/bin/python ]]; then
    bash setup.sh
fi
if [[ $# -eq 0 ]]; then
    set -- bridge
fi
exec .venv-linux/bin/python service.py "$@"
