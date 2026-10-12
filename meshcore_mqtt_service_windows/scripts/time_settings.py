"""Shared reply timezone. The responder exports its saved setting to every program."""
from datetime import datetime, timezone
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# USER SETTING: installed services persist responder.timezone in active config.json.
DEFAULT_TIMEZONE = 'America/Los_Angeles'
TIMEZONE_ENV = 'MESHCORE_TIMEZONE'


def display_timezone(name=None):
    """Return an IANA zone from an explicit name, responder environment, or Pacific default."""
    name = os.environ.get(TIMEZONE_ENV, DEFAULT_TIMEZONE) if name is None else name
    if not isinstance(name, str) or not name or name != name.strip():
        raise ValueError('responder.timezone must be an IANA timezone name.')
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError('Display timezone unavailable. Check responder.timezone and install tzdata.') from exc


def format_timestamp(value, zone=None):
    """Format an aware instant in the shared reply zone with date, time, and DST label."""
    if value.tzinfo is None:
        raise ValueError('Display time requires an explicit source timezone.')
    return value.astimezone(zone or display_timezone()).strftime('%Y-%m-%d %H:%M %Z')


def format_utc_observation(value):
    """Convert AirNow's UTC field for display; missing/unparseable values remain Unknown."""
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return 'Unknown'
    # The provider explicitly defines this field as UTC even without an ISO offset.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return format_timestamp(parsed)
