"""Dedicated tributaries reference command."""
from pathlib import Path
import sys
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.connectivity_lookup import main as connectivity_main

def main(argv=None):
    """Execute only this registered command."""
    return connectivity_main('tributaries', argv)

if __name__ == '__main__':
    raise SystemExit(main())
