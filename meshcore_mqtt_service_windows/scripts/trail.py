"""Report local trail features for !trail and standalone use."""

import sys

if __package__:
    from .gis_lookup import main as gis_main
else:
    from gis_lookup import main as gis_main


def main(argv=None):
    """Read a trail query and optional --settings path; return the shared GIS exit status."""
    return gis_main(argv, kind='trail')


if __name__ == '__main__':
    sys.exit(main())
