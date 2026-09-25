"""California snow depth (CDEC sensor 18) and next-24h snowfall (NWS).

Standard-library CLI; the MeshCore responder supplies the @sender prefix.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import math
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if __package__:
    from .uv_index import parse_location as _parse_location
else:
    from uv_index import parse_location as _parse_location

# USER SETTINGS AND SOURCES: per-request seconds and byte cap.
# NWS URLs are also validated in lookup(); changing provider requires parser changes.
HTTP_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 8_000_000
GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
GEOCODING_RESULT_LIMIT = 100
NWS_POINTS_URL = 'https://api.weather.gov/points/{point}'
USER_AGENT = 'MC-EMS-Services-Snowpack/1.0'

UTC = timezone.utc
UNAVAILABLE = 'Snowpack lookup unavailable. Please try again later.'
CA_ONLY = 'Use a California GPS location, ZIP code, or city name.'
STATIONS_URL = 'https://cdec.water.ca.gov/dynamicapp/staSearch'
OBS_URL = 'https://cdec.water.ca.gov/dynamicapp/req/JSONDataServlet'
MAX_AGE = timedelta(hours=24)  # Applies to BOTH depth readings and forecast update time.
# Sensor 18 / hourly H / INCHES identify snow depth; they are a data contract.
# The forecast horizon is fixed at 24 hours to match the output wording.


def get_text(url, params=None):
    """Fetch UTF-8 text with a byte cap and per-request timeout; raise coverage or availability errors."""
    if params:
        url += '?' + urlencode(params)
    request = Request(url, headers={'User-Agent': USER_AGENT,
                                   'Accept': 'application/geo+json, application/json, text/html'})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RuntimeError(UNAVAILABLE)
            return raw.decode('utf-8')
    except HTTPError as exc:
        if exc.code == 404 and '/points/' in url:
            raise ValueError(CA_ONLY) from exc
        raise RuntimeError(UNAVAILABLE) from exc
    except (URLError, TimeoutError, OSError, UnicodeError) as exc:
        raise RuntimeError(UNAVAILABLE) from exc


def get_json(url, params=None):
    """Decode a fetched JSON response; translate malformed data into an availability error."""
    try:
        return json.loads(get_text(url, params))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(UNAVAILABLE) from exc


def parse_location(text):
    """Reuse the shared location syntax and reject explicitly non-California city/state input."""
    try:
        parsed = _parse_location(text)
    except ValueError as exc:
        raise ValueError(str(exc).replace('!uv', '!snowpack')) from exc
    if parsed[0] == 'city' and parsed[2] != 'California':
        raise ValueError(CA_ONLY)
    return parsed


def number(value):
    """Return whether value is a finite int/float, excluding booleans and missing readings."""
    return type(value) in (int, float) and math.isfinite(value)


def resolve_location(parsed):
    """Return GPS directly or geocode a California city/ZIP; reject invalid coordinate results."""
    kind, value, state = parsed
    if kind == 'coordinates':
        return value
    data = get_json(GEOCODING_URL, {
        'name': f'{value}, California' if kind == 'city' else value,
        'count': GEOCODING_RESULT_LIMIT, 'language': 'en', 'format': 'json', 'countryCode': 'US'})
    if not isinstance(data, dict) or data.get('error'):
        raise RuntimeError('Location lookup unavailable.')
    results = data.get('results', [])
    if not isinstance(results, list) or any(not isinstance(row, dict) for row in results):
        raise RuntimeError('Location lookup unavailable.')
    candidates = [row for row in results if row.get('country_code') == 'US'
                  and row.get('admin1') == 'California'
                  and (kind != 'zip' or value in (row.get('postcodes') or []))
                  and (kind != 'city' or row.get('name', '').casefold() == value.casefold())]
    if not candidates:
        raise ValueError('California location not found. Try GPS coordinates or a ZIP code.')
    selected = max(candidates, key=lambda row: row.get('population') or 0)
    lat, lon = selected.get('latitude'), selected.get('longitude')
    if not (number(lat) and number(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise RuntimeError('Location lookup unavailable.')
    return lat, lon


class StationTable(HTMLParser):
    """Read only CDEC's station_table, using its column headings."""
    def __init__(self):
        """Initialize CDEC table, row, and cell buffers."""
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.cell = None
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        """Enter the station_table and start collecting its rows and cells."""
        if tag == 'table' and dict(attrs).get('id') == 'station_table':
            self.inside = True
        if self.inside and tag == 'tr':
            self.row = []
        if self.inside and tag in ('td', 'th'):
            self.cell = []

    def handle_data(self, data):
        """Append text to the active station-table cell."""
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        """Finish cells/rows and stop collecting at the end of the table."""
        if self.inside and tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        if self.inside and tag == 'tr' and self.row:
            self.rows.append(self.row)
        if tag == 'table':
            self.inside = False


def parse_stations(html):
    """Return validated station id/name/coordinates from CDEC HTML; reject incomplete directories."""
    parser = StationTable()
    parser.feed(html)
    required = ['ID', 'Station Name', 'Longitude', 'Latitude']
    if not parser.rows or any(key not in parser.rows[0] for key in required):
        raise RuntimeError('Snow station directory unavailable.')
    indices = [parser.rows[0].index(key) for key in required]
    stations = {}
    for row in parser.rows[1:]:
        # Reject incomplete directories instead of silently picking a farther station.
        try:
            code, name, lon, lat = [row[i] for i in indices]
            lat, lon = float(lat), float(lon)
            if not (re.fullmatch(r'[A-Z0-9]{3}', code) and name
                    and math.isfinite(lat) and math.isfinite(lon)
                    and -90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError()
        except (ValueError, IndexError) as exc:
            raise RuntimeError('Snow station directory unavailable.') from exc
        stations[code] = {'id': code, 'name': name, 'lat': lat, 'lon': lon}
    if not stations:
        raise RuntimeError('No hourly snow-depth stations available.')
    return list(stations.values())


def distance_miles(lat, lon, station):
    """Return great-circle miles between the user coordinates and one parsed station."""
    a, b = math.radians(lat), math.radians(station['lat'])
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(station['lon']-lon)/2)**2
    return 3958.761 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def current_depth(data, station_id, now):
    """Return the newest unflagged, fresh hourly sensor-18 depth in inches, or None; zero is valid."""
    if not isinstance(data, list):
        raise RuntimeError(UNAVAILABLE)
    readings = []
    for row in data:
        if not isinstance(row, dict):
            raise RuntimeError(UNAVAILABLE)
        if (row.get('stationId') != station_id or row.get('SENSOR_NUM') != 18
                or row.get('durCode') != 'H' or row.get('units') != 'INCHES'
                or str(row.get('dataFlag', '')).strip()):
            continue
        value = row.get('value')
        if not number(value) or value < 0:
            continue
        try:
            local = datetime.strptime(row['obsDate'], '%Y-%m-%d %H:%M')
        except (KeyError, ValueError, TypeError):
            continue
        # CDEC JSON omits the UTC offset. Require freshness under BOTH Pacific
        # offsets to avoid calling an old/future value current across DST or
        # station timestamp conventions. This may omit the newest hour.
        earliest = local.replace(tzinfo=UTC) + timedelta(hours=7)
        latest = local.replace(tzinfo=UTC) + timedelta(hours=8)
        if now - MAX_AGE <= earliest and latest <= now + timedelta(minutes=15):
            readings.append((local, value))
    return max(readings, key=lambda item: item[0])[1] if readings else None


def timestamp(text):
    """Parse an ISO timestamp with an explicit offset; raise ValueError if the time zone is absent."""
    value = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Missing time zone')
    return value


def interval(text):
    """Convert an ISO start/end or start/duration interval into (start, end); reject nonpositive spans."""
    start_text, end_text = text.split('/')
    start = timestamp(start_text)
    if end_text.startswith('P'):
        match = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?', end_text)
        if not match or not any(match.groups()):
            raise ValueError('Invalid duration')
        days, hours, minutes, seconds = [float(v or 0) for v in match.groups()]
        end = start + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    else:
        end = timestamp(end_text)
    if end <= start:
        raise ValueError('Invalid interval')
    return start, end


def snowfall_24h(data, now):
    """Integrate period totals over [now, now+24h), prorating boundary bins."""
    try:
        props = data['properties']
        updated = timestamp(props['updateTime'])
        if not now - MAX_AGE <= updated <= now + timedelta(minutes=15):
            return None
        layer = props['snowfallAmount']
        factors = {'wmoUnit:mm': 1/25.4, 'wmoUnit:cm': 1/2.54, 'wmoUnit:m': 1/0.0254,
                   'wmoUnit:in': 1}
        factor = factors[layer['uom']]
        finish = now + timedelta(hours=24)
        periods = []
        for row in layer['values']:
            start, end = interval(row['validTime'])
            if end <= now or start >= finish:
                continue
            value = row['value']
            if not number(value) or value < 0:
                return None
            periods.append((max(now, start), min(finish, end), value * factor,
                            (end-start).total_seconds()))
        cursor, total = now, 0.0
        for start, end, amount, seconds in sorted(periods):
            if start != cursor:  # Missing or overlapping periods are not zero snowfall.
                return None
            total += amount * (end-start).total_seconds()/seconds
            cursor = end
        return total if cursor == finish and math.isfinite(total) else None
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def inches(value):
    """Format inches compactly, preserve small positive amounts, and label None as unavailable."""
    if value is None:
        return 'unavailable'
    if 0 < value < 0.05:
        return '<0.1in'
    return f'{value:.1f}'.rstrip('0').rstrip('.') + 'in'


def lookup(text, now=None):
    """Verify California coverage, choose the closest station, and combine depth with the user's 24h forecast."""
    now = now or datetime.now(UTC)
    lat, lon = resolve_location(parse_location(text))
    point = get_json(NWS_POINTS_URL.format(point=f'{lat:.4f},{lon:.4f}'))
    props = point['properties']
    county = props.get('county', '')
    if not isinstance(county, str) or not re.fullmatch(r'https://api\.weather\.gov/zones/county/[A-Z]{2}C\d{3}', county):
        raise RuntimeError('Unable to verify California coverage. Try another nearby location.')
    if not county.rsplit('/', 1)[-1].startswith('CAC'):
        raise ValueError(CA_ONLY)
    grid_url = props.get('forecastGridData', '')
    if not isinstance(grid_url, str) or not re.fullmatch(r'https://api\.weather\.gov/gridpoints/[A-Z]{3}/\d+,\d+', grid_url):
        raise RuntimeError(UNAVAILABLE)
    stations = parse_stations(get_text(STATIONS_URL, {
        'search': 'Search', 'sensor_chk': 'on', 'sensor': 18, 'dur_chk': 'on',
        'dur': 'H', 'active_chk': 'on', 'active': 'Y', 'display': 'sta'}))
    station = min(stations, key=lambda row: (distance_miles(lat, lon, row), row['id']))
    distance = distance_miles(lat, lon, station)
    try:
        observations = get_json(OBS_URL, {'Stations': station['id'], 'SensorNums': 18,
            'dur_code': 'H', 'Start': (now-timedelta(days=2)).strftime('%Y-%m-%d'),
            'End': (now+timedelta(days=1)).strftime('%Y-%m-%d')})
        depth = current_depth(observations, station['id'], now)
    except (RuntimeError, ValueError, KeyError, TypeError):
        depth = None
    try:
        snowfall = snowfall_24h(get_json(grid_url), now)
    except (RuntimeError, ValueError):
        snowfall = None
    return (f'Snowpack: Current: {inches(depth)} | Next 24h: {inches(snowfall)} | '
            f'Station: {station["name"]} {distance:.1f}mi.')


def main(argv=None):
    """Print a UTF-8 result or useful error for location arguments; return 0 so the responder forwards the text."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == '!snowpack':
        args.pop(0)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        print(lookup(' '.join(args)))
    except (ValueError, RuntimeError) as exc:
        print(str(exc))
    except (KeyError, TypeError, AttributeError, OverflowError):
        print(UNAVAILABLE)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
