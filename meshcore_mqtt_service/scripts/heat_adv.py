"""Look up active NWS heat alerts for GPS coordinates, a US ZIP, or a city/state.

Uses only the standard library and the adjacent uv_index.py location parser.
Run: python scripts/heat_adv.py Sacramento (or ZIP or LATITUDE LONGITUDE).
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if __package__:
    from .uv_index import parse_location as _parse_location
else:
    from uv_index import parse_location as _parse_location

# USER SETTINGS: each lookup makes at most three requests; the bot allows 45 seconds.
HTTP_TIMEOUT_SECONDS = 12
GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
GEOCODING_RESULT_LIMIT = 100
NWS_POINTS_URL = 'https://api.weather.gov/points/{point}'
NWS_ALERTS_URL = 'https://api.weather.gov/alerts/active'
USER_AGENT = 'MC-EMS-Services-HeatAdv/1.0'
UNAVAILABLE = 'Heat alert lookup unavailable. Please try again later.'

# REPLY TEXT: keep the requested spelling and capitalization, including the clear reply.
ALERT_REPLIES = {
    'Extreme Heat Warning': 'Advisory: Extreme Heat Warning for {location}',
    'Extreme Heat Watch': 'Advisory: Extreme Heat Watch for {location}',
    'Heat Advisory': 'Heat Advisory for {location}',
}
NO_ALERTS = 'There is no Heat Advisories for {location}'
# NWS renamed these products in March 2025; accept either spelling from a feed.
LEGACY_EVENTS = {
    'Excessive Heat Warning': 'Extreme Heat Warning',
    'Excessive Heat Watch': 'Extreme Heat Watch',
}


def parse_location(text):
    """Validate location syntax without HTTP; cities default to California."""
    try:
        return _parse_location(text)
    except ValueError as exc:
        raise ValueError(str(exc).replace('!uv', '!heatadv')) from exc


def get_json(url, params=None):
    """Fetch JSON with a timeout; coverage and provider failures never imply no alerts."""
    if params:
        url += '?' + urlencode(params)
    request = Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'application/geo+json, application/json',
    })
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError('Heat lookup rate limit reached. Try again later.') from exc
        if exc.code == 404 and '/points/' in url:
            raise ValueError('Location is outside NWS coverage. Use a US location.') from exc
        raise RuntimeError(UNAVAILABLE) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(UNAVAILABLE) from exc


def resolve_location(parsed):
    """Return GPS directly or an exact US city/ZIP match; enforce the requested state."""
    kind, value, state = parsed
    if kind == 'coordinates':
        return value
    data = get_json(GEOCODING_URL, {
        'name': f'{value}, {state}' if state else value,
        'count': GEOCODING_RESULT_LIMIT, 'language': 'en', 'format': 'json',
        'countryCode': 'US',
    })
    if not isinstance(data, dict) or data.get('error'):
        raise RuntimeError('Location lookup unavailable. Try again later.')
    results = data.get('results', [])
    if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
        raise RuntimeError('Location service returned invalid results.')
    candidates = [item for item in results
                  if item.get('country_code') == 'US'
                  and (state is None or item.get('admin1', '').casefold() == state.casefold())
                  and (kind != 'zip' or value in item.get('postcodes', []))
                  and (kind != 'city' or item.get('name', '').casefold() == value.casefold())]
    if not candidates:
        raise ValueError('Location not found. Use a ZIP or GPS; cities outside California need a state.')
    # A city/ZIP describes a representative point, not its entire geographic boundary.
    selected = max(candidates, key=lambda item: item.get('population', 0))
    lat, lon = selected['latitude'], selected['longitude']
    if (any(type(n) not in (int, float) or not math.isfinite(n) for n in (lat, lon))
            or not (-90 <= lat <= 90 and -180 <= lon <= 180)):
        raise RuntimeError('Location service returned invalid coordinates.')
    return lat, lon


def timestamp(value):
    """Parse an explicit-timezone NWS timestamp, rejecting missing or malformed times."""
    if not isinstance(value, str):
        raise RuntimeError('Heat alert service returned an invalid time.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise RuntimeError('Heat alert service returned an invalid time.') from exc
    if parsed.tzinfo is None:
        raise RuntimeError('Heat alert service returned an invalid time.')
    return parsed


def active_types(data, now=None):
    """Return distinct, effective heat types in reply order; reject incomplete alert data.

    NWS's point filter handles polygons and zones, including null-geometry alerts.
    Future-onset watches count once issued/effective; test and cancelled alerts do not.
    """
    if (not isinstance(data, dict) or data.get('type') != 'FeatureCollection'
            or not isinstance(data.get('features'), list)):
        raise RuntimeError('Heat alert service returned an invalid response.')
    pagination = data.get('pagination', {})
    if not isinstance(pagination, dict) or pagination.get('next'):
        raise RuntimeError('Heat alert response incomplete. Please try again later.')
    now = now or datetime.now(timezone.utc)
    found = set()
    for feature in data['features']:
        if not isinstance(feature, dict) or not isinstance(feature.get('properties'), dict):
            raise RuntimeError('Heat alert service returned an invalid alert.')
        props = feature['properties']
        event = props.get('event')
        if not isinstance(event, str) or not event:
            raise RuntimeError('Heat alert service returned an invalid alert type.')
        event = LEGACY_EVENTS.get(event, event)
        if event not in ALERT_REPLIES:
            continue
        if props.get('status') not in ('Actual', 'Exercise', 'System', 'Test', 'Draft'):
            raise RuntimeError('Heat alert service returned an invalid status.')
        if props['status'] != 'Actual' or props.get('messageType') in ('Cancel', 'Ack', 'Error'):
            continue
        if props.get('messageType') not in ('Alert', 'Update'):
            raise RuntimeError('Heat alert service returned an invalid message type.')
        effective, expires = timestamp(props.get('effective')), timestamp(props.get('expires'))
        ends = timestamp(props['ends']) if props.get('ends') is not None else expires
        if effective >= expires or ends < effective:
            raise RuntimeError('Heat alert service returned an invalid time interval.')
        if effective <= now < min(expires, ends):
            found.add(event)
    return [event for event in ALERT_REPLIES if event in found]


def lookup(text):
    """Resolve a location, confirm NWS coverage, then format its active heat alerts."""
    text = ' '.join(text.strip().split())
    lat, lon = resolve_location(parse_location(text))
    point = f'{lat:.4f},{lon:.4f}'
    # Empty alerts alone cannot prove that NWS covers the requested point.
    coverage = get_json(NWS_POINTS_URL.format(point=point))
    if (not isinstance(coverage, dict) or coverage.get('type') != 'Feature'
            or not isinstance(coverage.get('properties'), dict)
            or not coverage['properties'].get('forecastZone')):
        raise RuntimeError('Unable to verify NWS coverage for this location.')
    data = get_json(NWS_ALERTS_URL, {'point': point, 'status': 'actual'})
    events = active_types(data)
    if not events:
        return NO_ALERTS.format(location=text)
    return '\n'.join(ALERT_REPLIES[event].format(location=text) for event in events)


def main(argv=None):
    """Print a reply or useful error; return 0 so the responder forwards either text."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == '!heatadv':
        args.pop(0)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        print(lookup(' '.join(args)))
    except (ValueError, RuntimeError) as exc:
        print(str(exc))
    except (KeyError, TypeError, AttributeError, OverflowError):
        print('Heat alert lookup unavailable: invalid service response.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
