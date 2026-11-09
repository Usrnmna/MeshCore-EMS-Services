"""Exact station and nearby inventory queries with qualified latest observations."""
import math
import re
import sys
import time
from datetime import datetime

from . import gauge_data, water_identifiers, water_local, water_settings, water_sources
from .nearby_river_stations import haversine_miles
from .response_text import compact_fields

FAILURES = (OSError, ValueError, KeyError, TypeError, RuntimeError)
PARAMETERS = {'stage': '00065', 'flow': '00060'}
UNITS = {'stage': {'ft'}, 'flow': {'ft^3/s', 'cfs', 'kcfs'}}


def parse(command, text):
    """Validate bounded literal syntax; station and series IDs are never normalized."""
    if len(text.encode()) > 150 or any(not c.isprintable() for c in text):
        raise ValueError('Query must be printable and at most 150 bytes.')
    words = text.split()
    if not words or words == ['help']:
        return {'help': True}
    if command == 'gauges':
        if len(words) not in (3, 4) or words[0] != 'near':
            raise ValueError('Use !gauges near LAT LON [MILES].')
        numbers = tuple(float(n) for n in words[1:])
        if (not all(math.isfinite(n) for n in numbers) or not -90 <= numbers[0] <= 90
                or not -180 <= numbers[1] <= 180 or len(numbers) == 3 and not 0 < numbers[2] <= 50):
            raise ValueError('Invalid coordinates or radius (maximum 50 mi).')
        return {'near': numbers}
    if not re.fullmatch(r'[A-Za-z0-9]+-[A-Za-z0-9-]+', words[0]):
        raise ValueError('Use an exact AGENCY-STATION-ID.')
    result = {'station': words.pop(0), 'field': None, 'series': None}
    if words and words[0] in ('stage', 'flow', 'source'):
        result['field'] = words.pop(0)
    if words:
        if len(words) != 2 or words[0] != 'series' or not re.fullmatch(r'[A-Za-z0-9_.:-]+', words[1]):
            raise ValueError('Use ID [stage|flow|source] [series SERIES-ID].')
        result['series'] = words[1]
    return result


def qualify(row, now, max_age):
    """Recompute age and units independently of persisted usability labels."""
    result = dict(row, usable=False, age=None)
    states = []
    if row.get('inactive'):
        states.append('inactive')
    if row.get('ineligible'):
        states.append('ineligible')
    if row.get('unit_of_measure') not in UNITS.get(row.get('kind'), set()):
        states.append('unexpected_units')
    try:
        if not isinstance(row.get('time'), str):
            raise ValueError('Missing observation time')
        stamp = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Missing timezone')
        age = now - stamp.timestamp()
        result['age'] = max(0, int(age))
        if age < 0:
            states.append('future')
        elif age > max_age:
            states.append('stale')
    except (ValueError, TypeError, OverflowError, OSError):
        states.append('invalid time')
    try:
        if isinstance(row.get('value'), bool):
            raise ValueError('Boolean is not a measurement')
        value = float(row['value'])
        if not math.isfinite(value) or value <= -999:
            raise ValueError('Invalid measurement')
    except (ValueError, TypeError, KeyError, OverflowError):
        states.append('invalid value')
    result.update(state=','.join(states) or 'current', usable=not states)
    return result


def installed_rows(values, sid, now, config):
    """Retain each installed series and its complete approval and quality flags."""
    rows = []
    for original in values.get(sid, []):
        kind = next((k for k, p in PARAMETERS.items() if original.get('parameter_code') == p), None)
        if kind is None:
            continue
        row = dict(original, kind=kind, origin='snapshot', series=original.get('time_series_id', ''))
        if original.get('selection_status') != 'primary_instantaneous_candidate':
            row['ineligible'] = True
            row['qualifier'] = str(row.get('qualifier') or '') + ' selection ' + str(original.get('selection_status') or 'unknown')
        rows.append(qualify(row, now, config['reading_max_age']))
    return rows


def live_rows(sid, config, now, inventory_lid=''):
    """Use only reviewed exact links and the existing current-only NOAA adapter."""
    if not config['noaa_enabled']:
        return [], 'live disabled'
    reviews, _ = water_identifiers.load()
    station = {'id': sid, 'lid': inventory_lid}
    water_identifiers.apply(station, reviews)
    if station['noaa_identity_status'] not in {'matched', 'matched_agency_successor'}:
        return [], 'live link unavailable'
    result = water_sources.gauge(station['lid'], sid, config, now)
    observed = result.get('observation')
    if not isinstance(observed, dict):
        return [], 'live reading unavailable'
    rows = []
    for slot in ('primary', 'secondary'):
        unit = observed.get(slot + 'Unit')
        kind = next((k for k, units in UNITS.items() if unit in units), None)
        if kind is None or observed.get(slot) is None:
            continue
        row = dict(kind=kind, series='nwps-' + slot, origin='NOAA live/cache',
                   value=observed[slot], unit_of_measure=unit, time=observed.get('validTime'),
                   approval_status=observed.get('approval_status') or 'quality unknown',
                   qualifier=observed.get('qualifier') or '', inactive=result.get('in_service') is not True)
        rows.append(qualify(row, now, config['reading_max_age']))
    return rows, 'live checked' if rows else 'live units unavailable'


def exact(query, stations, values, observation_state, config, now, root, pointer):
    """Resolve one exact inventory identity; never pick an arbitrary series."""
    sid = query['station']
    if sid not in stations:
        return compact_fields('Station ID not found in installed inventory.', [sid])
    rows = installed_rows(values, sid, now, config)
    try:
        lid = gauge_data.station_link(root, pointer, sid) if config['noaa_enabled'] else ''
        live, live_state = live_rows(sid, config, now, lid)
    except FAILURES:
        live, live_state = [], 'live failed'
    rows += live
    field = query['field']
    if field in PARAMETERS:
        rows = [r for r in rows if r['kind'] == field]
    if query['series'] is not None:
        rows = [r for r in rows if r['series'] == query['series']]
    if not rows:
        return compact_fields(f'{sid}: readings unavailable; {live_state}; {observation_state}')
    if len(rows) != 1 or not rows[0]['series']:
        return compact_fields(f'{sid}: ambiguous; use series ID',
                              [r['kind'] + ' ' + r['series'] for r in rows])
    row = rows[0]
    quality = ' '.join(str(row.get(k) or '') for k in ('approval_status', 'qualifier')).strip() or 'quality unknown'
    # Qualifiers are essential text. Pipes from source fields cannot split it.
    status = f'{sid} {row["origin"]} {row["state"]}'
    if row['origin'] == 'snapshot':
        status += '; ' + live_state
    if field == 'source':
        return compact_fields(status + '; series ' + row['series'], [row.get('time', '')])
    detail = f'{row["kind"]} {row.get("value")} {row.get("unit_of_measure")}'
    age = f'{row["age"] // 60}m old' if row['age'] is not None else 'time invalid'
    text = f'{status}; {detail}; {age}; {quality}'.replace('|', '/')
    reply = compact_fields(text)
    return reply if reply != 'Unable to return this result.' else compact_fields(f'{sid}: qualified reading exceeds reply limit.')


def lookup(command, text, config=None, now=None):
    """Perform a bounded lookup without creating schedules, indexes, or history."""
    query = parse(command, text)
    if query.get('help'):
        return compact_fields('!gauges near LAT LON [MILES]' if command == 'gauges' else
                              '!gauge AGENCY-ID [stage|flow|source] [series ID]')
    config = water_settings.load() if config is None else config
    if not config['enabled']:
        return 'Water commands disabled.'
    now = time.time() if now is None else now
    root, pointer, stations = gauge_data.load_inventory(config)
    try:
        values = gauge_data.load_observations(root, pointer, now, config['reading_max_age'])
        observation_state = 'snapshot checked'
    except FAILURES:
        values, observation_state = {}, 'snapshot unavailable'
    if command == 'gauge':
        reply = exact(query, stations, values, observation_state, config, now, root, pointer)
    else:
        coordinates = query['near']
        lat, lon = coordinates[:2]
        radius = coordinates[2] if len(coordinates) == 3 else config['nearby_radius_miles']
        matches = []
        for sid, station in stations.items():
            geometry = station.get('geometry') or {}
            if geometry.get('type') != 'Point':
                continue
            point = geometry.get('coordinates', [])
            if len(point) < 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in point[:2]):
                continue
            if not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90:
                continue
            distance = haversine_miles(lat, lon, point[1], point[0])
            if distance <= radius:
                available = any(r['usable'] for r in installed_rows(values, sid, now, config))
                matches.append((distance, sid, 'snapshot reading' if available else 'inventory only'))
        matches.sort()
        reply = compact_fields('Nearby inventory; not upstream; ' + observation_state,
            [f'{sid} {distance:.1f}mi {state}' for distance, sid, state in matches[:config['max_results']]]) if matches else 'No inventory stations within radius.'
        if matches and matches[0][1] not in reply:
            reply = 'Nearby result exceeds reply limit; no station identified.'
    if water_local.read_json(root / 'inventory.json') != pointer:
        raise ValueError('Station inventory changed; retry')
    return reply


def main(command, argv=None):
    """Dedicated command runner; errors disclose no local configuration paths."""
    try:
        print(lookup(command, ' '.join(sys.argv[1:] if argv is None else argv)))
        return 0
    except FAILURES:
        print('Gauge query unavailable or invalid; use help. No current reading confirmed.')
        return 1
