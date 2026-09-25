"""Flood alerts from the NWS API used by https://www.flashfloodwarn.com/.

Uses the standard library; city/ZIP coordinates come from Open-Meteo/GeoNames.
Run: python scripts/flood_warn.py Sacramento (or ZIP or LATITUDE LONGITUDE).
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

# USER SETTINGS AND SOURCES: preserve the NWS GeoJSON contract when changing URLs.
HTTP_TIMEOUT_SECONDS = 12  # Each geocoder, coverage, and alert request.
GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
GEOCODING_RESULT_LIMIT = 100
NWS_POINTS_URL = 'https://api.weather.gov/points/{point}'
NWS_ALERTS_URL = 'https://api.weather.gov/alerts/active'
USER_AGENT = 'MC-EMS-Services-FloodWarn/1.0'

# REPLY TEXT: dictionary order controls alert priority; keys must match NWS event names.
USAGE = 'Use !floodwarn LATITUDE LONGITUDE, ZIP, or CITY [STATE].'
UNAVAILABLE = 'Flood alert lookup unavailable. Please try again later.'
ALERTS = {
    'Flash Flood Warning': ('🟥', 'Life-threatening flash flooding is imminent or occurring. Move to higher ground immediately.'),
    'Flood Warning': ('🟧', 'Flooding is imminent or occurring. Take necessary precautions now.'),
    'Flood Advisory': ('🟨', 'Minor flooding expected. May cause inconvenience but not typically life-threatening.'),
    'Flood Watch': ('🟦', 'Conditions favorable for flooding. Stay alert and be ready to take action.'),
}


def parse_location(text):
    """Reuse UV's shared input parser and relabel usage errors for !floodwarn; performs no HTTP requests."""
    try:
        return _parse_location(text)
    except ValueError as exc:
        raise ValueError(str(exc).replace('!uv', '!floodwarn')) from exc


def get_json(url, params=None):
    """Fetch JSON/GeoJSON; distinguish NWS coverage, rate-limit, and availability errors."""
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
            raise RuntimeError('Flood lookup rate limit reached. Try again later.') from exc
        if exc.code == 404 and '/points/' in url:
            raise ValueError('Location is outside NWS coverage. Use a US location.') from exc
        raise RuntimeError(UNAVAILABLE) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(UNAVAILABLE) from exc


def resolve_location(parsed):
    """Return GPS coordinates or geocode an exact US city/ZIP; reject missing and invalid matches."""
    kind, value, state = parsed
    if kind == 'coordinates':
        return value
    data = get_json(GEOCODING_URL, {
        'name': f'{value}, {state}' if state else value,
        'count': GEOCODING_RESULT_LIMIT, 'language': 'en', 'format': 'json', 'countryCode': 'US',
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
        raise ValueError('Location not found. Try a ZIP code or GPS coordinates.')
    selected = max(candidates, key=lambda item: item.get('population', 0))
    lat, lon = selected['latitude'], selected['longitude']
    if (any(type(n) not in (int, float) or not math.isfinite(n) for n in (lat, lon))
            or not (-90 <= lat <= 90 and -180 <= lon <= 180)):
        raise RuntimeError('Location service returned invalid coordinates.')
    return lat, lon


def timestamp(value):
    """Parse an ISO timestamp with an explicit time zone; raise RuntimeError for invalid or naive times."""
    if not isinstance(value, str):
        raise RuntimeError('Flood alert service returned an invalid time.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise RuntimeError('Flood alert service returned an invalid time.') from exc
    if parsed.tzinfo is None:
        raise RuntimeError('Flood alert service returned an invalid time.')
    return parsed


def active_types(data, now=None):
    """NWS /alerts/active?point= performs polygon/zone matching, even for null geometry."""
    if (not isinstance(data, dict) or data.get('type') != 'FeatureCollection'
            or not isinstance(data.get('features'), list)):
        raise RuntimeError('Flood alert service returned an invalid response.')
    if data.get('pagination', {}).get('next'):
        # Do not report a partial response as a complete list of local alerts.
        raise RuntimeError('Flood alert response incomplete. Please try again later.')
    now = now or datetime.now(timezone.utc)
    found = set()
    for feature in data['features']:
        if not isinstance(feature, dict) or not isinstance(feature.get('properties'), dict):
            raise RuntimeError('Flood alert service returned an invalid alert.')
        props = feature['properties']
        event = props.get('event')
        if not isinstance(event, str) or not event:
            raise RuntimeError('Flood alert service returned an invalid alert type.')
        if event not in ALERTS:
            continue
        if props.get('status') not in ('Actual', 'Exercise', 'System', 'Test', 'Draft'):
            raise RuntimeError('Flood alert service returned an invalid status.')
        if props['status'] != 'Actual' or props.get('messageType') in ('Cancel', 'Ack', 'Error'):
            continue
        if props.get('messageType') not in ('Alert', 'Update'):
            raise RuntimeError('Flood alert service returned an invalid message type.')
        effective, expires = timestamp(props.get('effective')), timestamp(props.get('expires'))
        ends = timestamp(props['ends']) if props.get('ends') is not None else expires
        # Future-onset watches are already active once their message is effective.
        if effective <= now < min(expires, ends):
            found.add(event)
    return [event for event in ALERTS if event in found]


def snapshot(text):
    """Return comparable alert types plus reply text; failures raise, never become a clear reading."""
    text = ' '.join(text.strip().split())
    lat, lon = resolve_location(parse_location(text))
    point = f'{lat:.4f},{lon:.4f}'
    # An empty alerts response alone does not establish that NWS covers this point.
    coverage = get_json(NWS_POINTS_URL.format(point=point))
    if (not isinstance(coverage, dict) or coverage.get('type') != 'Feature'
            or not isinstance(coverage.get('properties'), dict)
            or not coverage['properties'].get('forecastZone')):
        raise RuntimeError('Unable to verify NWS coverage for this location.')
    data = get_json(NWS_ALERTS_URL, {'point': point, 'status': 'actual'})
    events = active_types(data)
    return {'events': events, 'text': format_status(text, events)}


def format_status(text, events):
    """One shared formatter for on-demand replies and alarm status changes."""
    if not events:
        return f'no flooding events declared for {text}'
    return text + ':\n' + '\n'.join(
        f'{event} {ALERTS[event][0]} - {ALERTS[event][1]}' for event in events)


def lookup(text):
    """Keep the original one-shot text interface."""
    return snapshot(text)['text']


def main(argv=None):
    """Print UTF-8 alert/usage/error text for location arguments; return 0 so the responder forwards the text."""
    args = list(sys.argv[1:] if argv is None else argv)
    # Internal subprocess mode: the alarm compares structured types, never error text.
    structured = bool(args and args[0] == '--snapshot')
    if structured:
        args.pop(0)
    if args and args[0] == '!floodwarn':
        args.pop(0)
    # Preserve the requested emoji when invoked directly on Windows as well as by the bot.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        print(json.dumps(snapshot(' '.join(args)), ensure_ascii=False) if structured else lookup(' '.join(args)))
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}) if structured else str(exc))
    except (KeyError, TypeError, AttributeError, OverflowError):
        message = 'Flood alert lookup unavailable: invalid service response.'
        print(json.dumps({'error': message}) if structured else message)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
