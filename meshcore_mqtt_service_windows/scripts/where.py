"""Dedicated geographic identification command; read-only installed references."""
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.where_lookup import main

if __name__ == '__main__':
    raise SystemExit(main())
