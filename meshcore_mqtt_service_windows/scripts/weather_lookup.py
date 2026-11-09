"""One qualified NWS forecast period per stateless weather request."""
from datetime import datetime, timezone
import json
import math
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from . import heat_adv, lightning, uv_index
from .weather_source import Cache, Client, Unavailable, NWS, REFRESH_SECONDS, CACHE_SECONDS
from .response_text import MESSAGE_BYTES

MAX_PERIODS = 200
SOURCE_MAX_AGE = 12 * 3600
HELP = '!weather [hourly|wind] LAT LON/ZIP/CITY [STATE]. Cities default CA. Forecast only; local --json for full detail.'
FAILURES = (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError, OverflowError)


def parse(text):
    """Keep existing location forms, with one optional focused forecast selector."""
    if not isinstance(text, str) or len(text.encode()) > 150 or any(not c.isprintable() for c in text):
        raise Unavailable('Invalid weather query; use !weather help.')
    words = text.split()
    if not words or words == ['help']:
        return None
    mode = words.pop(0) if words[0] in ('hourly', 'wind') else 'period'
    if not words or any(w.lower() in ('hourly', 'wind', 'help', 'nan', 'inf', 'infinity') for w in words):
        raise Unavailable('Invalid weather selector/location; use !weather help.')
    try:
        parsed = uv_index.parse_location(' '.join(words))
    except ValueError as exc:
        raise Unavailable('Invalid weather location; use LAT LON, ZIP or CITY STATE.') from exc
    return mode, parsed


def instant(value):
    """Reuse the NWS aware-timestamp parser and normalize comparisons to UTC."""
    try:
        return lightning.timestamp(value)
    except RuntimeError as exc:
        raise Unavailable('Forecast unavailable: invalid or missing source time.') from exc


def mapping(point, product):
    """Validate the authoritative point endpoint, grid identity and local timezone."""
    p = point['properties']
    office, x, y = p['gridId'], p['gridX'], p['gridY']
    if (not isinstance(office, str) or not re.fullmatch('[A-Z]{3}', office)
            or type(x) is not int or type(y) is not int or x < 0 or y < 0):
        raise Unavailable('Forecast unavailable: invalid NWS grid identity.')
    expected = f'{NWS}/gridpoints/{office}/{x},{y}/forecast' + ('/hourly' if product == 'hourly' else '')
    endpoint = p.get('forecastHourly' if product == 'hourly' else 'forecast')
    if endpoint != expected:
        raise Unavailable('Forecast unavailable: unsupported or conflicting NWS endpoint.')
    zone = p['timeZone']
    if not isinstance(zone, str):
        raise Unavailable('Forecast unavailable: location timezone missing.')
    ZoneInfo(zone)
    return endpoint, zone


def selected(data, now, product):
    """Select the containing or earliest bounded future period; reject conflicts."""
    p = data['properties']
    updated = instant(p.get('updateTime'))
    if not 0 <= now - updated.timestamp() <= SOURCE_MAX_AGE:
        raise Unavailable('Forecast unavailable: stale or future-dated source update.')
    generated = p.get('generatedAt')
    if generated is not None:
        generated_time = instant(generated)
        if not updated <= generated_time <= datetime.fromtimestamp(now, timezone.utc):
            raise Unavailable('Forecast unavailable: contradictory generation times.')
    try:
        valid_start, valid_end = lightning.interval(p['validTimes'])
    except (KeyError, RuntimeError) as exc:
        raise Unavailable('Forecast unavailable: invalid source validity interval.') from exc
    if valid_end.timestamp() <= now:
        raise Unavailable('Forecast unavailable: source validity expired.')
    periods = p.get('periods')
    if not isinstance(periods, list) or not periods or len(periods) > MAX_PERIODS:
        raise Unavailable('Forecast unavailable: missing or excessive periods.')
    eligible = []
    for row in periods:
        start, end = instant(row.get('startTime')), instant(row.get('endTime'))
        span = (end - start).total_seconds()
        if not 0 < span <= (3600 if product == 'hourly' else 86400):
            raise Unavailable('Forecast unavailable: invalid period duration.')
        if end.timestamp() <= now:
            continue
        if start < valid_start or end > valid_end:
            raise Unavailable('Forecast unavailable: conflicting validity intervals.')
        eligible.append((start, end, row))
    eligible.sort(key=lambda item: (item[0], item[1]))
    unique = []
    for entry in eligible:
        if unique and entry[0] < unique[-1][1]:
            if entry == unique[-1]:
                continue
            raise Unavailable('Forecast unavailable: overlapping or conflicting periods.')
        unique.append(entry)
    horizon = 24 * 3600 if product == 'hourly' else 48 * 3600
    if not unique or unique[0][0].timestamp() - now > horizon:
        raise Unavailable('Forecast unavailable: no applicable upcoming period.')
    start, end, row = unique[0]
    return dict(period=row, start=start.isoformat(), end=end.isoformat(), updated=updated.isoformat(),
                generated=generated, gap_seconds=max(0, start.timestamp() - now), units=p.get('units'))


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def quantity(value, units, low=None, high=None):
    """Preserve quantitative-value ranges and units without conversion or guessing."""
    if not isinstance(value, dict) or value.get('unitCode') not in units:
        return None
    scalar = value.get('value')
    numbers = [scalar]
    minimum, maximum = value.get('minValue'), value.get('maxValue')
    if minimum is not None or maximum is not None:
        numbers = [minimum, maximum]
    if (not all(numeric(n) and (low is None or n >= low) and (high is None or n <= high) for n in numbers)
            or len(numbers) == 2 and numbers[0] > numbers[1] or value.get('qualityControl') is not None):
        return None
    if len(numbers) == 2 and scalar is not None:
        if not numeric(scalar) or not minimum <= scalar <= maximum:
            return None
    return '-'.join(f'{n:g}' for n in numbers) + units[value['unitCode']]


def wind_value(value):
    """Accept recorded speed ranges, calm, or quantitative values with known units."""
    if isinstance(value, dict):
        return quantity(value, {'wmoUnit:km_h-1': ' km/h', 'wmoUnit:m_s-1': ' m/s',
                                'wmoUnit:mi_h-1': ' mph', 'wmoUnit:kn': ' kt'}, 0)
    if isinstance(value, str) and (value.lower() == 'calm' or re.fullmatch(r'[0-9]+(?:\.[0-9]+)?(?: (?:to|-) [0-9]+(?:\.[0-9]+)?)? (?:mph|km/h|m/s|kt)', value)):
        numbers = [float(n) for n in re.findall(r'[0-9]+(?:\.[0-9]+)?', value)]
        if all(math.isfinite(n) for n in numbers) and (len(numbers) < 2 or numbers[0] <= numbers[1]):
            return value
    return None


def fields(row, mode):
    """Render complete qualified fields; null or unsupported values remain unknown."""
    speed = wind_value(row.get('windSpeed')) or 'unknown'
    direction = row.get('windDirection')
    if direction not in ('N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW','VRB','Variable','variable'):
        direction = 'direction unknown'
    wind = 'wind ' + direction + ' ' + speed
    gust = wind_value(row.get('windGust'))
    if gust or mode == 'wind':
        wind += '; gust ' + (gust or 'unknown')
    if mode == 'wind':
        return [wind], None
    temperature = row.get('temperature')
    if isinstance(temperature, dict):
        temp = quantity(temperature, {'wmoUnit:degF': 'F', 'wmoUnit:degC': 'C'})
        unit = {'wmoUnit:degF': 'F', 'wmoUnit:degC': 'C'}.get(temperature.get('unitCode'))
        if row.get('temperatureUnit') not in (None, unit):
            temp = None
    else:
        temp = f'{temperature:g}{row["temperatureUnit"]}' if numeric(temperature) and row.get('temperatureUnit') in ('F','C') else None
    trend = row.get('temperatureTrend')
    if trend not in (None, 'rising', 'falling'):
        temp = None
    label = 'temp' if mode == 'hourly' else 'high' if row.get('isDaytime') is True else 'low' if row.get('isDaytime') is False else 'temp(type unknown)'
    temp = label + ' ' + (temp or 'unknown') + (' ' + trend if trend in ('rising', 'falling') else '')
    pop = quantity(row.get('probabilityOfPrecipitation'), {'wmoUnit:percent': '%'}, 0, 100)
    summary = row.get('shortForecast')
    if not isinstance(summary, str) or not summary or any(not c.isprintable() for c in summary):
        summary = 'summary unknown'
    return [temp, 'precip chance ' + (pop or 'unknown'), wind], summary


def lookup(text, *, clock=time.time, client=None, cache=None, resolved=None):
    """Resolve once; refresh a pinned point/product pair and qualify cached fallback."""
    query = parse(text)
    if query is None:
        return {'help': True}
    mode, location = query
    product = 'period' if mode == 'period' else 'hourly'
    client, cache = client or Client(clock=clock), cache or Cache()
    try:
        lat, lon = heat_adv.resolve_location(location, fetch=client.geocode) if resolved is None else resolved
        if not all(numeric(n) for n in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError('Invalid resolved point')
    except FAILURES as exc:
        raise Unavailable('Weather unavailable: location unresolved; use LAT LON or CITY STATE.') from exc
    # Match the established NWS point precision used by heat/lightning/snowpack.
    point = f'{lat:.4f},{lon:.4f}'
    point_url = NWS + '/points/' + point
    key = 'v1:' + point + ':' + product + ':us'
    old = cache.read(key, clock())
    if old:
        try:
            old_url, zone = mapping(old['point'], product)
            if old['url'] != old_url:
                raise Unavailable('Cached grid mismatch')
            selected(old['forecast'], clock(), product)
        except FAILURES:
            old = None
    delivery = 'cached'
    latest_url = None
    if old and clock() - old['retrieved'] < REFRESH_SECONDS:
        record = old
    else:
        try:
            for attempt in range(2):
                point_data, point_expiry, point_store = client.get(point_url)
                latest_url, zone = mapping(point_data, product)
                try:
                    forecast, expiry, store = client.get(latest_url, {'units': 'us'})
                    break
                except HTTPError as exc:
                    if attempt or exc.code not in (404, 410):
                        raise
                    # A removed endpoint invalidates its cached product even if
                    # the subsequent point re-resolution fails transiently.
                    old = None
                    exc.close()
            selected(forecast, clock(), product)
            record = dict(key=key, point=point_data, url=latest_url, forecast=forecast,
                          retrieved=clock(), expires=min(point_expiry, expiry))
            cache.write(key, record if store and point_store else None, clock())
            delivery = 'live'
        except (OSError, URLError) as exc:
            transient = not isinstance(exc, HTTPError) or exc.code in (429, 500, 502, 503, 504)
            if old and transient and (latest_url is None or latest_url == old['url']) and clock() < old['expires']:
                record, delivery = old, 'cached; provider failed'
            else:
                cache.write(key, None, clock())
                if isinstance(exc, HTTPError) and exc.code == 404 and latest_url is None:
                    raise Unavailable('Weather unavailable: location outside supported NWS coverage.') from exc
                raise Unavailable('Weather unavailable: NWS failed; no eligible cached forecast.') from exc
        except FAILURES:
            cache.write(key, None, clock())
            raise
    endpoint, zone = mapping(record['point'], product)
    checked_at = clock()
    if delivery != 'live' and (not 0 <= checked_at - record['retrieved'] <= CACHE_SECONDS
                               or checked_at >= record['expires']):
        raise Unavailable('Weather unavailable: cached forecast expired during query.')
    result = selected(record['forecast'], checked_at, product)
    result.update(source='NWS', mode=mode, product=product, delivery=delivery, timezone=zone,
                  endpoint=endpoint, point=point, retrieved=record['retrieved'], cache_expires=record['expires'],
                  qualification='Forecast, not observations or a comprehensive hazard check.')
    return result


def fit(text, fallback='Forecast details withheld; use hourly/wind or local --json.'):
    """Keep complete fields and qualifications within the sender's UTF-8 budget."""
    budget = MESSAGE_BYTES - len(('@' + os.environ.get('MESHCORE_SENDER', 'Reader') + ' ').encode())
    for value in (text, fallback, 'Forecast withheld.'):
        if len(value.encode()) <= budget:
            return value
    return ''


def render(result):
    """Use location-zone validity and UTC update time, never the host timezone."""
    if result.get('help'):
        return fit(HELP, '!weather [hourly|wind] LOCATION; help; local --json.')
    zone = ZoneInfo(result['timezone'])
    start, end = (instant(result[k]).astimezone(zone) for k in ('start','end'))
    first = start.strftime('%m-%d %H:%M %Z')
    last = end.strftime('%H:%M %Z' if start.date() == end.date() else '%m-%d %H:%M %Z')
    if start.year != end.year:
        first, last = start.strftime('%Y-%m-%d %H:%M %Z'), end.strftime('%Y-%m-%d %H:%M %Z')
    delivery = '' if result['delivery'] == 'live' else result['delivery'] + '; '
    gap = 'future gap; ' if result['gap_seconds'] else ''
    heading = f'NWS {delivery}{gap}{"hourly " if result["product"] == "hourly" else ""}forecast {first}-{last}; upd ' + instant(result['updated']).strftime('%m-%d %H:%MZ')
    values, summary = fields(result['period'], result['mode'])
    detail = '; '.join(values + ([summary] if summary else []))
    text = heading + '; ' + detail
    if fit(text, ''):
        return text
    if summary:
        text = heading + '; ' + '; '.join(values) + '; summary omitted'
        if fit(text, ''):
            return text
    return fit(heading + '; detail withheld; local --json.')


def main(argv=None):
    """Run directly or through the service; JSON is a local CLI option only."""
    args = list(sys.argv[1:] if argv is None else argv)
    structured = bool(args and args[0] == '--json')
    if structured:
        args.pop(0)
    try:
        if structured and (os.environ.get('MESHCORE_REQUEST_ID') or os.environ.get('MESHCORE_SENDER')):
            raise Unavailable('Weather structured output is local-only.')
        result = lookup(' '.join(args))
        print(json.dumps(result, ensure_ascii=True, allow_nan=False) if structured else render(result))
    except FAILURES as exc:
        message = str(exc) if isinstance(exc, Unavailable) else 'Weather unavailable: invalid provider data or local dependency.'
        print(json.dumps({'error': message}) if structured and not os.environ.get('MESHCORE_REQUEST_ID') and not os.environ.get('MESHCORE_SENDER') else fit(message))
    return 0
