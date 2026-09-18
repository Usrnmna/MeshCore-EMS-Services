#!/usr/bin/env bash
# Run once to start the local broker and continuous MeshCore channel responder.
set -euo pipefail
service_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--check" ]]; then
    for required in run.sh setup.sh service.py config.json requirements.txt; do
        [[ -f "$service_dir/$required" ]] || { printf 'Missing: %s\n' "$required" >&2; exit 1; }
    done
    printf 'Launcher files found in %s\n' "$service_dir"
    exit 0
fi
exec bash "$service_dir/run.sh" bridge
