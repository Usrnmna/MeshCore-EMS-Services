"""Query mapped parking reference records for !parking."""
import sys
if __package__:
    from .parks_sites import main
else:
    from parks_sites import main

if __name__ == "__main__":
    sys.exit(main("parking"))
