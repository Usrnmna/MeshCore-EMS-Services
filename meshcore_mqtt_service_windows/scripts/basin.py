"""Dedicated !basin location command; standalone execution creates no subscription."""
from pathlib import Path
import sys
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.water_lookup import main as water_main

def main(argv=None):
    return water_main("basin", argv)

if __name__ == "__main__":
    raise SystemExit(main())
