from datetime import datetime, timezone

print(datetime.now(timezone.utc).strftime("Current UTC time: %Y-%m-%d %H:%M:%S"))
