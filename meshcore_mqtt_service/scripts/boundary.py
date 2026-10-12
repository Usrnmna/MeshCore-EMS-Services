"""Report local point containment and trail boundary intersections for !boundary and standalone use."""

import sys

if __package__:
    from .gis_lookup import main as gis_main
else:
    from gis_lookup import main as gis_main


def main(argv=None):
    """Read a boundary query and optional --settings path; return the shared GIS exit status."""
    return gis_main(argv, kind='boundary')


if __name__ == '__main__':
    sys.exit(main())
