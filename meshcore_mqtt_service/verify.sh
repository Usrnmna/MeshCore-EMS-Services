#!/usr/bin/env bash
# Run all offline tests, including the loopback MQTT broker integration checks.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv-linux/bin/python ]]; then
    printf 'Run bash setup.sh before verification.\n' >&2
    exit 1
fi
.venv-linux/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv-linux/bin/python -m pip check
