"""Report local recreation points and amenities for !rec and standalone use."""

import sys

if __package__:
    from .gis_lookup import main as gis_main
else:
    from gis_lookup import main as gis_main


def main(argv=None):
    """Read a rec query and optional --settings path; return the shared GIS exit status."""
    return gis_main(argv, kind='rec')


if __name__ == '__main__':
    sys.exit(main())
