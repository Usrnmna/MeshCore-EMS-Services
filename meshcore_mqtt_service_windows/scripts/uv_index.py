"""Current UV Index CLI. UV data: https://currentuvindex.com (CC BY 4.0).

Location data: Open-Meteo / GeoNames. Uses only the Python standard library.
"""
from __future__ import annotations

import json
import math
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# USER SETTINGS AND SOURCES: seconds for timeouts; see ../README.md.
# Changing providers also requires adapting the response parser, not just the URL.
DEFAULT_CITY_STATE = 'California'  # Also used by flood_warn and snowpack input parsing.
HTTP_TIMEOUT_SECONDS = 12  # Per HTTP request, not the entire script.
GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
GEOCODING_RESULT_LIMIT = 100  # Candidate places requested before local filtering.
UV_API_URL = 'https://currentuvindex.com/api/v1/uvi'
USER_AGENT = 'MC-EMS-Services-UV/1.0'

# INPUT CONTRACT: state aliases and decimal-degree syntax, not tuning settings.
STATES = dict(pair.split(':') for pair in (
    'AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|'
    'CT:Connecticut|DE:Delaware|FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|'
    'IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|LA:Louisiana|'
    'ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|'
    'MS:Mississippi|MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|'
    'NH:New Hampshire|NJ:New Jersey|NM:New Mexico|NY:New York|'
    'NC:North Carolina|ND:North Dakota|OH:Ohio|OK:Oklahoma|OR:Oregon|'
    'PA:Pennsylvania|RI:Rhode Island|SC:South Carolina|SD:South Dakota|'
    'TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|VA:Virginia|WA:Washington|'
    'WV:West Virginia|WI:Wisconsin|WY:Wyoming|DC:District of Columbia|PR:Puerto Rico'
).split('|'))
USAGE = 'Use !uv LATITUDE LONGITUDE, ZIP, or CITY [STATE].'
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'


def parse_location(text):
    """Return (kind, value, state) for GPS, US ZIP, or city text; raise ValueError on bad input. No network access."""
    text = ' '.join(text.strip().split())
    if not text or len(text) > 150:
        raise ValueError(USAGE)
    match = re.fullmatch(rf'({NUMBER})(?:\s*,\s*|\s+)({NUMBER})', text)
    if match:
        lat, lon = map(float, match.groups())
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError('Latitude must be -90..90; longitude -180..180.')
        return 'coordinates', (lat, lon), None
    if re.fullmatch(r'\d{5}(?:-\d{4})?', text):
        return 'zip', text[:5], None
    if not re.fullmatch(r"[A-Za-z][A-Za-z .,'-]*", text):
        raise ValueError(USAGE)
    state = DEFAULT_CITY_STATE
    # Longest suffix first handles multiword state names, with or without a comma.
    aliases = {name.casefold(): name for name in STATES.values()}
    aliases.update({abbr.casefold(): name for abbr, name in STATES.items()})
    for alias in sorted(aliases, key=len, reverse=True):
        match = re.fullmatch(rf"(.+?)(?:,\s*|\s+){re.escape(alias)}", text, re.I)
        if match:
            text, state = match[1].strip(' ,'), aliases[alias]
            break
    if ',' in text or not text or not any(c.isalpha() for c in text):
        raise ValueError(USAGE)
    return 'city', text, state


def get_json(url, params):
    """Fetch one JSON response with a per-request timeout; convert HTTP/decoding failures into readable errors."""
    request = Request(url + '?' + urlencode(params), headers={
        'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError('UV lookup rate limit reached. Try again later.') from exc
        raise RuntimeError(f'Lookup service returned HTTP {exc.code}. Try again later.') from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError('UV lookup unavailable. Try again later.') from exc


def resolve_location(parsed):
    """Return (latitude, longitude); use GPS directly or geocode a US ZIP/city with state filtering."""
    kind, value, state = parsed
    if kind == 'coordinates':
        return value
    data = get_json(GEOCODING_URL, {
        'name': f'{value}, {state}' if state else value,
        'count': GEOCODING_RESULT_LIMIT, 'language': 'en', 'format': 'json', 'countryCode': 'US'})
    if not isinstance(data, dict) or data.get('error'):
        raise RuntimeError('Location lookup unavailable. Try again later.')
    candidates = [item for item in data.get('results', [])
                  if item.get('country_code') == 'US'
                  and (state is None or item.get('admin1', '').casefold() == state.casefold())
                  and (kind != 'zip' or value in item.get('postcodes', []))]
    if not candidates:
        raise ValueError('Location not found. Try a ZIP code or GPS coordinates.')
    # Prefer exact city names over prefix matches, then the largest settlement.
    exact = [item for item in candidates if item.get('name', '').casefold() == value.casefold()]
    selected = max(exact or candidates, key=lambda item: item.get('population', 0))
    lat, lon = selected['latitude'], selected['longitude']
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise RuntimeError('Location service returned invalid coordinates.')
    return lat, lon


def risk_level(uvi):
    """Validate a nonnegative finite UV reading and return its category; thresholds are category definitions."""
    if type(uvi) not in (float, int) or not math.isfinite(uvi) or uvi < 0:
        raise ValueError('UV service returned an invalid current reading.')
    for threshold, label in ((3, 'Low'), (6, 'Moderate'), (8, 'High'), (11, 'Very-High')):
        if uvi < threshold:
            return label
    return 'Extreme'


def lookup(text):
    """Resolve location, request the current UV reading, and return one reply string; raise on unavailable data."""
    lat, lon = resolve_location(parse_location(text))
    data = get_json(UV_API_URL, {'latitude': lat, 'longitude': lon})
    if not isinstance(data, dict) or data.get('ok') is not True:
        raise RuntimeError('Current UV reading unavailable. Try again later.')
    now = data.get('now')
    if not isinstance(now, dict):
        raise RuntimeError('Current UV reading unavailable. Try again later.')
    uvi = now.get('uvi')
    risk = risk_level(uvi)
    return f'UV Index: {uvi:g} {risk}'


def main(argv=None):
    """Read location arguments and print a reply or useful lookup error; return 0 so the responder sends that text."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == '!uv':
        args.pop(0)
    try:
        print(lookup(' '.join(args)))
    except (ValueError, RuntimeError) as exc:
        # Expected lookup failures remain useful in the tagged mesh reply.
        print(str(exc))
    except (KeyError, TypeError, AttributeError, OverflowError):
        print('UV lookup unavailable: invalid service response.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
