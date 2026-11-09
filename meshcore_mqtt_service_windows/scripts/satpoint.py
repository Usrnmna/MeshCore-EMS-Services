"""Dedicated !satpoint program for GIS-qualified orbital pointing."""
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.satellite_pointing import main

if __name__ == '__main__':
    raise SystemExit(main())
