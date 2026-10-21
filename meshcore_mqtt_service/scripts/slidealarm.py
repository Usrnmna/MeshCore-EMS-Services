"""Dedicated !slidealarm program; scheduling and enrollment belong to the service."""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.landslide_lookup import main

if __name__ == "__main__":
    sys.exit(main("slidealarm"))
