"""Provide structured flood readings for !floodalarm's persistent service monitor.

Standalone invocation reads one snapshot; it does not create a subscription.
Enrollment, acknowledgment, scheduling, and expiry remain in the service.
"""

import sys

if __package__:
    from .flood_warn import main as flood_main
else:
    from flood_warn import main as flood_main


def main(argv=None):
    """Read location arguments and print the monitor's JSON snapshot or error."""
    args = list(sys.argv[1:] if argv is None else argv)
    return flood_main(['--snapshot', *args])


if __name__ == '__main__':
    sys.exit(main())
