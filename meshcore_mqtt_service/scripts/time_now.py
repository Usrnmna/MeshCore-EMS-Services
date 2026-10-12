"""Print the host clock in the shared reply timezone for !time."""
from datetime import datetime, timezone

try:
    from scripts.time_settings import display_timezone
except ModuleNotFoundError:
    from time_settings import display_timezone

TIME_FORMAT = 'Current time: %Y-%m-%d %H:%M:%S %Z'


def main():
    """Print the current instant in the saved reply zone, including its PST/PDT-style label."""
    print(datetime.now(timezone.utc).astimezone(display_timezone()).strftime(TIME_FORMAT))


if __name__ == '__main__':
    main()
