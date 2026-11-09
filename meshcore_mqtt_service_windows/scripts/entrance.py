"""Query the installed State Parks reference for !entrance."""
import sys
if __package__:
    from .stateparks_lookup import main
else:
    from stateparks_lookup import main

if __name__ == "__main__":
    sys.exit(main("entrance"))
