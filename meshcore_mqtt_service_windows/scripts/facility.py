"""Query installed EBMUD and State Parks facility references for !facility."""
import sys
if __package__:
    from .facility_lookup import main
else:
    from facility_lookup import main

if __name__ == "__main__":
    sys.exit(main())
