"""Dedicated exact station lookup."""
from pathlib import Path
import sys
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.gauge_lookup import main as gauge_main

def main(argv=None):
    """Execute only the gauge command."""
    return gauge_main('gauge', argv)

if __name__ == '__main__':
    raise SystemExit(main())
