"""Report local parks and recreation areas for !park and standalone use."""

import sys

if __package__:
    from .gis_lookup import main as gis_main
else:
    from gis_lookup import main as gis_main


def main(argv=None):
    """Read a park query and optional --settings path; return the shared GIS exit status."""
    return gis_main(argv, kind='park')


if __name__ == '__main__':
    sys.exit(main())
