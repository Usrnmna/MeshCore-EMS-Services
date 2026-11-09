"""Dedicated satellite reference command; no tracking or transmission."""
from pathlib import Path
import sys
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.satellite_lookup import main as lookup_main

def main(argv=None):
    """Run the dedicated catalog query with direct or service-supplied arguments."""
    return lookup_main('satfreq', argv)

if __name__ == '__main__':
    raise SystemExit(main())
