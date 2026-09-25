"""Print host-clock UTC time for !time; the responder adds @sender.

Edit TIME_FORMAT for wording/layout. timezone.utc controls the time basis.
"""
from datetime import datetime, timezone

TIME_FORMAT = "Current UTC time: %Y-%m-%d %H:%M:%S"

print(datetime.now(timezone.utc).strftime(TIME_FORMAT))
