"""Dedicated !smoke point lookup; scheduling remains service-owned."""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fire_environment import main

if __name__ == "__main__":
    sys.exit(main("smoke"))
