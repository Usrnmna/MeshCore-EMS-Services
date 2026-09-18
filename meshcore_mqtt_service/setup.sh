#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
# A separate environment avoids reusing a Windows .venv copied with the folder.
python3 -m venv .venv-linux
.venv-linux/bin/python -m pip install -r requirements.txt
