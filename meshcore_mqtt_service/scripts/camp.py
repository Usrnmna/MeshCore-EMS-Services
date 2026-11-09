"""Query campground and site-group reference records for !camp."""
import sys
if __package__:
    from .parks_sites import main
else:
    from parks_sites import main

if __name__ == "__main__":
    sys.exit(main("camp"))
