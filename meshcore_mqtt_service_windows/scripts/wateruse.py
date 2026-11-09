"""Dedicated !wateruse executable for installed Basin Plan designations."""
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.basin_plan_lookup import main as reference_main


def main(argv=None):
    """Query designation records without scheduling, subscriptions or source updates."""
    return reference_main('wateruse', argv)


if __name__ == '__main__':
    raise SystemExit(main())
