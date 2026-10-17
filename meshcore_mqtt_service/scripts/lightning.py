"""Summarize NWS lightning potential during the 24 hours after a request.

Run: python scripts/lightning.py [--timezone America/Los_Angeles] LOCATION.
All bot replies use responder.timezone from the installed config.json.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if __package__:
    from .time_settings import display_timezone
    from .heat_adv import resolve_location
    from .uv_index import parse_location as _parse_location
else:
    from time_settings import display_timezone
    from heat_adv import resolve_location
    from uv_index import parse_location as _parse_location

# USER SETTINGS: shared display timezone is in time_settings.py / responder.timezone.
HTTP_TIMEOUT_SECONDS = 12
FORECAST_MAX_AGE_HOURS = 12
LOOKAHEAD_HOURS = 24
NWS_POINTS_URL = 'https://api.weather.gov/points/{point}'
NWS_ALERTS_URL = 'https://api.weather.gov/alerts/active'
UNAVAILABLE = 'Lightning lookup unavailable. Please try again later.'
USAGE = 'Use !lightning <GPS, US ZIP, or city/state>. Cities default to California.'

THUNDER_EVENTS = {
    'Severe Thunderstorm Warning', 'Severe Thunderstorm Watch',
    'Tornado Warning', 'Tornado Watch',
}
LAL_LABELS = {
    2: 'isolated thunderstorms (LAL 2)',
    3: 'scattered thunderstorms (LAL 3)',
    4: 'thunderstorms common (LAL 4)',
    5: 'numerous thunderstorms (LAL 5)',
    6: 'dry lightning (LAL 6)',
}
DURATION = re.compile(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?')
HAZARD = re.compile(r'\b(?:lightning|thunderstorms?|thunder)\b', re.I)
CHANCE = re.compile(
    r'\b(?:slight chance|chance|possible|likely|isolated|widely scattered|scattered|'
    r'numerous|occasional|definite|frequent|widespread)\b|\b\d+(?:\.\d+)?\s*(?:%|percent\b)', re.I)
NEGATED_HAZARD = re.compile(
    r'\b(?:no|without)\s+(?:(?:chance|risk|threat|of|additional|further)\s+)*'
    r'(?:lightning|thunderstorms?|thunder)\b|'
    r'\b(?:lightning|thunderstorms?|thunder)\s*(?:\.{2,}|:)\s*(?:none|not expected)\b|'
    r'\b(?:lightning|thunderstorms?|thunder)\s+(?:(?:is|are|will|be)\s+)*'
    r'(?:not expected|not forecast|no longer expected|unlikely)\b', re.I)


def parse_location(text):
    """Validate shared GPS/ZIP/city syntax and give lightning-specific usage errors."""
    try:
        return _parse_location(text)
    except ValueError as exc:
        raise ValueError(str(exc).replace('!uv', '!lightning')) from exc


def get_json(url, params=None):
    """Fetch JSON with bounded network time; HTTP/network failures never mean clear."""
    if params:
        url += '?' + urlencode(params)
    request = Request(url, headers={'User-Agent': 'MC-EMS-Services-Lightning/1.0',
                                   'Accept': 'application/geo+json, application/json'})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 404 and '/points/' in url:
            raise ValueError('Location is outside NWS coverage. Use a US location.') from exc
        raise RuntimeError(UNAVAILABLE) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(UNAVAILABLE) from exc


def timestamp(value):
    """Parse an aware NWS ISO timestamp into UTC so DST cannot change elapsed hours."""
    if not isinstance(value, str):
        raise RuntimeError('NWS returned an invalid time.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    raise RuntimeError('NWS returned an invalid time.')


def interval(value):
    """Decode NWS start/duration or start/end intervals; reject empty/reversed spans."""
    if not isinstance(value, str) or value.count('/') != 1:
        raise RuntimeError('NWS returned an invalid forecast interval.')
    first, last = value.split('/')
    start = timestamp(first)
    if last.startswith('P'):
        match = DURATION.fullmatch(last)
        if not match or not any(match.groups()):
            raise RuntimeError('NWS returned an invalid forecast duration.')
        days, hours, minutes, seconds = (float(n or 0) for n in match.groups())
        end = start + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    else:
        end = timestamp(last)
    if end <= start:
        raise RuntimeError('NWS returned an invalid forecast interval.')
    return start, end


def weather_labels(conditions):
    """Keep NWS thunder coverage wording, including slight chance and dry attributes."""
    if not isinstance(conditions, list):
        raise RuntimeError('NWS weather forecast is missing or invalid.')
    labels = []
    for condition in conditions:
        if (not isinstance(condition, dict) or 'weather' not in condition
                or not isinstance(condition.get('attributes'), list)):
            raise RuntimeError('NWS returned an invalid weather condition.')
        weather = condition['weather']
        if weather is not None and not isinstance(weather, str):
            raise RuntimeError('NWS returned an invalid weather type.')
        dry = 'dry_thunderstorms' in condition['attributes']
        if dry or (weather and HAZARD.search(weather.replace('_', ' '))):
            coverage = condition.get('coverage')
            if coverage is not None and not isinstance(coverage, str):
                raise RuntimeError('NWS returned an invalid chance level.')
            qualifier = coverage.replace('_', ' ') if coverage else 'chance not stated:'
            labels.append(f'{qualifier} {"dry thunderstorms" if dry else "thunderstorms"}')
    return labels


def forecast_windows(data, now):
    """Return (start, end, label) hazards; require fresh weather covering all 24 hours.

    Missing optional thunder probability/LAL layers are normal. When supplied,
    positive probabilities and LAL 2-6 also count; rain probability never does.
    A null weather type inside a condition is NWS's valid no-weather value.
    """
    if not isinstance(data, dict) or not isinstance(data.get('properties'), dict):
        raise RuntimeError('NWS returned an invalid forecast.')
    props = data['properties']
    updated = timestamp(props.get('updateTime'))
    if not -timedelta(minutes=15) <= now - updated <= timedelta(hours=FORECAST_MAX_AGE_HOURS):
        raise RuntimeError('NWS lightning forecast is stale or has an invalid update time.')
    finish = now + timedelta(hours=LOOKAHEAD_HOURS)
    covered, found = [], []
    for name in ('weather', 'probabilityOfThunder', 'lightningActivityLevel'):
        layer = props.get(name, {'values': []})
        if not isinstance(layer, dict) or not isinstance(layer.get('values'), list):
            raise RuntimeError('NWS returned an invalid forecast layer.')
        for row in layer['values']:
            if not isinstance(row, dict) or 'value' not in row:
                raise RuntimeError('NWS returned an invalid forecast value.')
            start, end = interval(row.get('validTime'))
            if end <= now or start >= finish:
                continue
            start, end = max(start, now), min(end, finish)
            value, labels = row['value'], []
            if name == 'weather':
                labels = weather_labels(value)
                covered.append((start, end))
            elif value is not None:
                maximum = 100 if name == 'probabilityOfThunder' else 6
                if (type(value) not in (int, float) or not math.isfinite(value)
                        or not 0 <= value <= maximum):
                    raise RuntimeError('NWS returned an invalid lightning probability/level.')
                if name == 'probabilityOfThunder' and value > 0:
                    labels = [f'{value:g}% thunderstorm chance']
                elif name == 'lightningActivityLevel':
                    if value != int(value) or value < 1:
                        raise RuntimeError('NWS returned an invalid lightning activity level.')
                    if value > 1:
                        labels = [LAL_LABELS[int(value)]]
            found.extend((start, end, label) for label in labels)
    cursor = now
    for start, end in sorted(covered):
        if start > cursor:
            break
        cursor = max(cursor, end)
    if cursor < finish:
        raise RuntimeError('NWS lightning forecast does not cover the full next 24h.')
    return found


def alert_labels(props):
    """Identify convective alerts or explicit lightning hazard text and stated chance.

    Do not treat wind-only fire alerts or generic preparedness instructions as
    lightning. Regular-expression matching handles common negations; unlisted
    phrasing can remain ambiguous.
    """
    event = props.get('event')
    if not isinstance(event, str) or not event:
        raise RuntimeError('NWS returned an invalid alert type.')
    text = ' '.join(props.get(key) or '' for key in ('headline', 'description'))
    text = re.split(r'PRECAUTIONARY/PREPAREDNESS ACTIONS', text, flags=re.I)[0]
    # Preserve sentence boundaries, but join NWS's wrapped lines before matching.
    text = ' '.join(text.split())
    phrases = re.split(r'(?<!\.)\.(?![.\d])|[;*]', text)
    relevant = [phrase for phrase in phrases
                if HAZARD.search(NEGATED_HAZARD.sub('', phrase))]
    if event not in THUNDER_EVENTS and not relevant:
        return []
    chances = sorted({m.group().lower() for phrase in relevant for m in CHANCE.finditer(phrase)})
    return [f'{event}: {", ".join(chances) if chances else "chance not stated"}']


def alert_windows(data, now):
    """Select actual lightning-related point alerts overlapping the requested 24h.

    Onset is the hazard start, effective is its fallback; ends is preferred to
    product expiration. Point matching covers NWS polygons and zones server-side.
    """
    if (not isinstance(data, dict) or data.get('type') != 'FeatureCollection'
            or not isinstance(data.get('features'), list)):
        raise RuntimeError('NWS returned an invalid alert response.')
    pagination = data.get('pagination', {})
    if not isinstance(pagination, dict) or pagination.get('next'):
        raise RuntimeError('NWS lightning alert response is incomplete.')
    finish, found = now + timedelta(hours=LOOKAHEAD_HOURS), []
    for feature in data['features']:
        if not isinstance(feature, dict) or not isinstance(feature.get('properties'), dict):
            raise RuntimeError('NWS returned an invalid alert.')
        props = feature['properties']
        if props.get('status') in ('Exercise', 'System', 'Test', 'Draft'):
            continue
        if props.get('messageType') in ('Cancel', 'Ack', 'Error'):
            continue
        if props.get('status') != 'Actual' or props.get('messageType') not in ('Alert', 'Update'):
            raise RuntimeError('NWS returned an invalid alert status.')
        labels = alert_labels(props)
        if not labels:
            continue
        start = timestamp(props.get('onset') or props.get('effective'))
        expires = timestamp(props.get('expires'))
        end = timestamp(props.get('ends') or props.get('expires'))
        if expires <= now or end <= now:
            continue
        if end <= start:
            raise RuntimeError('NWS returned an invalid alert interval.')
        if start >= finish:
            continue
        found.extend((max(start, now), min(end, finish), label) for label in labels)
    return found


def merge_windows(windows):
    """Combine coincident labels and adjacent identical spans without hiding clear gaps."""
    boundaries = sorted({value for start, end, _ in windows for value in (start, end)})
    merged = []
    for start, end in zip(boundaries, boundaries[1:]):
        labels = tuple(sorted({label for first, last, label in windows if first < end and last > start}))
        if not labels:
            continue
        if merged and merged[-1][1] == start and merged[-1][2] == labels:
            merged[-1] = (merged[-1][0], end, labels)
        else:
            merged.append((start, end, labels))
    return merged


def format_window(start, end, zone):
    """Display source-window bounds in the selected zone, labeling both sides of DST."""
    start, end = start.astimezone(zone), end.astimezone(zone)
    end_format = '%H:%M %Z' if start.date() == end.date() else '%Y-%m-%d %H:%M %Z'
    return f'{start:%Y-%m-%d %H:%M %Z}-{end.strftime(end_format)}'


def request_time():
    """Use the responder's original request timestamp from stdin; CLI uses current UTC."""
    now = datetime.now(timezone.utc)
    if not os.environ.get('MESHCORE_REQUEST_ID'):
        return now
    try:
        context = json.load(sys.stdin)
        value = context['sender_timestamp']
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('invalid timestamp')
        return datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, KeyError, TypeError, OverflowError, OSError) as exc:
        raise RuntimeError('Lightning lookup unavailable: invalid request time.') from exc


def lookup(text, now=None, timezone_name=None):
    """Resolve location, fetch NWS point alerts/grid, and format chance/time or clear text."""
    text = ' '.join(text.split())
    parsed = parse_location(text)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Request time must include a timezone.')
    now = now.astimezone(timezone.utc)
    zone = display_timezone(timezone_name)
    lat, lon = resolve_location(parsed, fetch=get_json)
    point = f'{lat:.4f},{lon:.4f}'
    coverage = get_json(NWS_POINTS_URL.format(point=point))
    if not isinstance(coverage, dict) or not isinstance(coverage.get('properties'), dict):
        raise RuntimeError('Unable to verify NWS coverage for this location.')
    grid_url = coverage['properties'].get('forecastGridData')
    if not isinstance(grid_url, str) or not re.fullmatch(
            r'https://api\.weather\.gov/gridpoints/[A-Z]{3}/\d+,\d+', grid_url):
        raise RuntimeError('NWS gridded lightning forecast is unavailable for this location.')
    found, incomplete = [], False
    for url, params, select in (
            (NWS_ALERTS_URL, {'point': point, 'status': 'actual'}, alert_windows),
            (grid_url, None, forecast_windows)):
        try:
            data = get_json(url, params) if params else get_json(url)
            found.extend(select(data, now))
        except (RuntimeError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
            # A positive result still matters when the other provider request fails.
            # Neither an empty partial response nor a failed request can mean clear.
            incomplete = True
    windows = merge_windows(found)
    if not windows:
        if incomplete:
            raise RuntimeError(UNAVAILABLE)
        return f'No Lightning expected for {text} in the next 24h'
    periods = '; '.join(f'{format_window(start, end, zone)} ({", ".join(labels)})'
                        for start, end, labels in windows)
    note = '; additional NWS data unavailable' if incomplete else ''
    return f'Lightning Strike Warning for {text} at {periods}{note}'


def main(argv=None):
    """Read optional timezone and location args; print replies/errors for the responder."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == '!lightning':
        args.pop(0)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        zone = None
        if args and args[0] == '--timezone':
            if len(args) < 3:
                raise ValueError('Use --timezone <IANA zone> followed by a location. ' + USAGE)
            _, zone, *args = args
        if os.environ.get('MESHCORE_REQUEST_ID'):
            # Bot replies always share the persisted service setting; CLI overrides are standalone only.
            zone = None
        print(lookup(' '.join(args), now=request_time(), timezone_name=zone))
    except (ValueError, RuntimeError) as exc:
        print(str(exc))
    except (KeyError, TypeError, AttributeError, OverflowError):
        print('Lightning lookup unavailable: invalid service response.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
