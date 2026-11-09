"""Read-only, bounded satellite pass predictions using W12 observer inputs."""
from datetime import datetime, timedelta, timezone
import json
import math
import os
import sqlite3
import sys
import time

from . import satellite_lookup as catalog_reader
from . import satellite_pointing as pointing
from . import satellite_terrain

# Limits include solver refinement and its samples outside the requested window.
MAX_HOURS = 24
MAX_SAMPLES = 50000
MAX_BATCH = 8192
MAX_INITIAL_SAMPLES = 2048
MAX_EVENTS = 256
MAX_SEGMENTS = 64
SEARCH_SECONDS = 12
EVENT_SECONDS = 0.5
HELP = '!satpass ID LAT LON [next24h|hours H] [min DEG]; shipped defaults 24h/10deg; help selectors'
SELECTORS_HELP = 'hours 0.25..24; min 0..90; agl 0..1000m (default 0); terrain ID; orbit ID; field start/peak/end/window; help units'
UNITS_HELP = 'UTC; threshold crossings, geometric degrees/no refraction; GIS observer height is not a terrain horizon; RF/sightline unverified'


def parse(text):
    """Validate bounded pass selectors and delegate observer parsing to W12."""
    if len(text.encode('utf-8')) > 150 or any(not c.isprintable() for c in text):
        raise ValueError('Invalid or oversized pass query')
    words = text.split()
    if not words or words in (['help'], ['--help']):
        return None
    if words in (['help', 'selectors'], ['help', 'units']):
        return {'help': words[1]}
    if len(words) < 3:
        raise ValueError('Use !satpass NORAD-ID LAT LON; help')
    observer, extra, seen = words[:3], {'hours': 24.0}, set()
    tail = words[3:]
    while tail:
        key = tail.pop(0)
        if key == 'next24h':
            if 'hours' in seen:
                raise ValueError('Repeated search window')
            seen.add('hours')
            continue
        if key not in {'hours', 'min', 'field', 'agl', 'terrain', 'orbit'} or key in seen or not tail:
            raise ValueError('Unknown, repeated or incomplete pass selector')
        seen.add(key)
        value = tail.pop(0)
        if key in {'hours', 'min'}:
            value = float(value)
            low, high = (0.25, MAX_HOURS) if key == 'hours' else (0, 90)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError('hours must be 0.25..24; min must be 0..90 degrees')
            extra[key] = value
        elif key == 'field':
            if value not in {'start', 'peak', 'end', 'window'}:
                raise ValueError('Select field start, peak, end or window')
            extra[key] = value
        else:
            observer.extend([key, value])
    result = pointing.parse(' '.join(observer))
    result.update(extra)
    return result


def guarded_orbit(model, start, end, maximum_age):
    """Wrap every SGP4 call with time, sample, freshness and numeric checks."""
    import numpy as np
    from skyfield.vectorlib import VectorFunction

    class GuardedOrbit(VectorFunction):
        center, target = model.center, model.target

        def __init__(self):
            self.model = model.model
            self.samples = 0
            self.deadline = time.monotonic() + SEARCH_SECONDS

        def _at(self, instant):
            times = np.asarray(instant.tt)
            self.samples += times.size
            if times.size > MAX_BATCH or self.samples > MAX_SAMPLES or time.monotonic() > self.deadline:
                raise ValueError('Search limit reached; prediction incomplete; shorten hours')
            if (not np.all(np.isfinite(times)) or np.any(times < model.epoch.tt)
                    or np.any(times > model.epoch.tt + maximum_age)):
                raise ValueError('Orbit freshness does not cover solver margin; shorten hours')
            result = model._at(instant)
            errors = np.asarray(result[3], dtype=object).ravel()
            if any(errors) or not np.all(np.isfinite(result[0])) or not np.all(np.isfinite(result[1])):
                raise ValueError('Orbit propagation failed; prediction incomplete')
            if time.monotonic() > self.deadline:
                raise ValueError('Search time limit reached; prediction incomplete')
            return result

    if start.tt < model.epoch.tt or end.tt > model.epoch.tt + maximum_age:
        raise ValueError('Orbit freshness does not cover requested window; shorten hours')
    # Bound the library's initial allocation before any vector propagation.
    step = .05 / max(model.model.no_kozai * 1440 / (2 * math.pi), 1)
    if (end.tt - start.tt) / step + 5 > MAX_INITIAL_SAMPLES:
        raise ValueError('Orbit search resolution exceeds work limit')
    return GuardedOrbit(), step


def segments(events, duration, threshold, elevation, minima=()):
    """Validate event topology and return qualified intervals, including boundaries.

    Times are seconds from the window start. Minima and interval midpoints audit
    the library event stream; contradictory crossings fail instead of becoming
    an apparently complete empty result. Peaks are not assumed to alternate.
    """
    if len(events) > MAX_EVENTS or len(minima) > MAX_EVENTS:
        raise ValueError('Event limit reached; prediction incomplete')
    clean, previous = [], -1.0
    for stamp, code in events:
        if not math.isfinite(stamp) or not 0 <= stamp <= duration or code not in (0, 1, 2) or stamp < previous:
            raise ValueError('Unexpected event ordering; prediction incomplete')
        previous = stamp
        item = (stamp, code)
        if item not in clean:
            clean.append(item)
    # Simultaneous contact: opening, maximum, closing. Never reorder distinct times.
    clean.sort(key=lambda item: (item[0], item[1]))
    contacts = {stamp for stamp, code in clean if code == 1 and
                (stamp, 0) in clean and (stamp, 2) in clean and abs(elevation(stamp) - threshold) <= 1e-6}
    clean = [(stamp, code) for stamp, code in clean if stamp not in contacts or code == 1]
    start_el, end_el = elevation(0), elevation(duration)
    active = dict(start=0.0, start_kind='window_start', peaks=[]) if start_el >= threshold else None
    found = []
    for index, (stamp, code) in enumerate(clean):
        el = elevation(stamp)
        if code != 1:
            # A short pass can end inside the solver's half-second resolution.
            # Direction probes must stay between adjacent events, otherwise an
            # upward crossing can be incorrectly tested after the downward one.
            previous_stamp = clean[index - 1][0] if index else 0.0
            next_stamp = clean[index + 1][0] if index + 1 < len(clean) else duration
            before = elevation(max(0, stamp - EVENT_SECONDS, (previous_stamp + stamp) / 2))
            after = elevation(min(duration, stamp + EVENT_SECONDS, (next_stamp + stamp) / 2))
            if code == 0:
                valid = before <= threshold + 1e-6 and after >= threshold - 1e-6
            else:
                valid = before >= threshold - 1e-6 and after <= threshold + 1e-6
            if not valid:
                raise ValueError('Invalid threshold crossing; prediction incomplete')
        if code == 0:
            if active is not None and stamp != 0:
                raise ValueError('Conflicting upward crossing; prediction incomplete')
            active = dict(start=stamp, start_kind='threshold_up', peaks=[])
        elif code == 1:
            if el < threshold - 1e-6:
                raise ValueError('Invalid culmination; prediction incomplete')
            if active is None:
                if abs(el - threshold) > 1e-6:
                    raise ValueError('Missing upward crossing; prediction incomplete')
                found.append(dict(start=stamp, end=stamp, start_kind='grazing', end_kind='grazing', peaks=[(stamp, el)]))
            else:
                active['peaks'].append((stamp, el))
        else:
            if active is None:
                raise ValueError('Missing upward crossing; prediction incomplete')
            active.update(end=stamp, end_kind='threshold_down')
            found.append(active)
            active = None
    if active is not None:
        active.update(end=duration, end_kind='window_end')
        found.append(active)
    if end_el == threshold and not any(item['start'] <= duration <= item['end'] for item in found):
        # Equality qualifies, but an endpoint sample alone establishes neither
        # a crossing direction nor a local maximum beyond the search window.
        found.append(dict(start=duration, end=duration, start_kind='window_contact',
                          end_kind='window_contact', peaks=[(duration, end_el)]))
    if len(found) > MAX_SEGMENTS:
        raise ValueError('Pass count limit reached; prediction incomplete')

    # The event finder can omit a crossing near a window boundary. Check extrema
    # and open intervals independently before claiming a fully searched window.
    boundaries = sorted({0.0, duration, *(stamp for stamp, _ in clean)})
    checks = [(a + b) / 2 for a, b in zip(boundaries, boundaries[1:]) if b > a]
    checks.extend(minima)
    checks.extend([0.0, duration])
    for stamp in checks:
        if not math.isfinite(stamp) or not 0 <= stamp <= duration:
            raise ValueError('Invalid extremum; prediction incomplete')
        inside = any(item['start'] <= stamp <= item['end'] for item in found)
        el = elevation(stamp)
        # Crossing times are resolved to half a second, so do not assert which
        # side of the threshold an endpoint rounded by the solver occupies.
        near_crossing = any(code != 1 and abs(stamp - event) <= EVENT_SECONDS for event, code in clean)
        if not near_crossing and ((inside and el < threshold - 1e-6) or (not inside and el > threshold + 1e-6)):
            raise ValueError('Missing threshold event; prediction incomplete')
    for item in found:
        if item['start'] == item['end'] and item['start'] in (0, duration):
            item.update(start_kind='window_contact', end_kind='window_contact')
        complete = item['start_kind'] == 'threshold_up' and item['end_kind'] == 'threshold_down'
        if complete and not item['peaks']:
            raise ValueError('Missing culmination; prediction incomplete')
        candidates = item.pop('peaks') + [(item['start'], elevation(item['start'])), (item['end'], elevation(item['end']))]
        peak, peak_el = max(candidates, key=lambda pair: (pair[1], -pair[0]))
        item.update(peak=peak, peak_elevation_deg=peak_el, complete_pass=complete,
                    peak_kind='pass maximum' if complete else 'segment maximum')
    return found


def search(model, timescale, now, end, maximum_age, latitude, longitude, height, threshold):
    """Find one next segment with Skyfield events, bounded propagation and audits."""
    import numpy as np
    from skyfield.api import EarthSatellite, wgs84
    from skyfield.searchlib import find_minima
    start_t, end_t = timescale.from_datetime(now), timescale.from_datetime(end)
    guarded, step = guarded_orbit(model, start_t, end_t, maximum_age)
    observer = wgs84.latlon(latitude, longitude, elevation_m=height)
    relative = guarded - observer

    def altitude(instant):
        values = relative.at(instant).altaz()[0].degrees
        if not np.all(np.isfinite(values)):
            raise ValueError('Invalid elevation; prediction incomplete')
        return values

    altitude.step_days = step
    event_times, codes = EarthSatellite.find_events(guarded, observer, start_t, end_t, altitude_degrees=threshold)
    if len(codes) > MAX_EVENTS:
        raise ValueError('Event limit reached; prediction incomplete')
    minimum_times, _ = find_minima(start_t, end_t, altitude, epsilon=EVENT_SECONDS / 86400, num=12)
    duration = (end - now).total_seconds()

    def seconds(instant):
        # Split Julian dates retain precision at exact requested boundaries.
        return float((instant - start_t) * 86400)

    cache = {}

    def elevation(offset):
        if offset not in cache:
            cache[offset] = float(altitude(timescale.from_datetime(now + timedelta(seconds=offset))))
        return cache[offset]

    events = [(seconds(t), int(code)) for t, code in zip(event_times, codes)]
    found = segments(events, duration, threshold, elevation, [seconds(t) for t in minimum_times])
    selected = found[0] if found else None
    if selected:
        selected = dict(selected)
        for key in ('start', 'peak', 'end'):
            selected[key] = (now + timedelta(seconds=selected[key])).isoformat()
    return dict(segment=selected, search_complete=True, qualifying_segments=len(found),
                propagation_samples=guarded.samples, event_resolution_seconds=EVENT_SECONDS)


def lookup(text, now=None):
    """Pin the W11 catalog and W12 settings, GIS source, grids and orbit for a search."""
    query = parse(text)
    if query is None:
        return {'message': HELP}
    if query.get('help'):
        return {'message': UNITS_HELP if query['help'] == 'units' else SELECTORS_HELP}
    configuration = pointing.settings()
    values, base, maximum_age = configuration
    minimum = values.get('pointing', {}).get('pass_min_elevation_deg', 10)
    if type(minimum) not in (int, float) or not math.isfinite(minimum) or not 0 <= minimum <= 90:
        raise ValueError('Invalid default pass elevation threshold')
    threshold = query.get('min', minimum)
    satellite_terrain.sources(values, base, query.get('terrain'))
    from skyfield.api import load
    timescale = load.timescale(builtin=True)
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError('Prediction time requires UTC offset')
    now = now.astimezone(timezone.utc)
    end = now + timedelta(hours=query['hours'])
    with catalog_reader.catalog() as (db, _):
        satellite = pointing.exact_satellite(db, query['norad'])
        (orbit, model, age), partial = pointing.choose_orbit(db, satellite, now, maximum_age, query.get('orbit'), timescale)
        with satellite_terrain.terrain(values, base, query['latitude'], query['longitude'], query.get('terrain')) as terrain:
            height = terrain['ellipsoid_height_m'] + query['agl']
            result = search(model, timescale, now, end, maximum_age, query['latitude'], query['longitude'], height, threshold)
            result.update(norad_id=query['norad'], satellite_id=satellite['satellite_id'],
                          window_start=now.isoformat(), window_end=end.isoformat(), minimum_elevation_deg=threshold,
                          latitude=query['latitude'], longitude=query['longitude'], observer_height_wgs84_m=height,
                          antenna_agl_m=query['agl'], terrain=terrain, orbit_id=pointing.orbit_id(orbit),
                          orbit_epoch=model.epoch.utc_datetime().isoformat(), catalog_orbit_epoch=orbit['epoch'],
                          orbit_source=orbit['source_url'], orbit_age_start_days=age,
                          orbit_age_end_days=(end - model.epoch.utc_datetime()).total_seconds() / 86400,
                          orbit_max_age_days=maximum_age, partial_orbit_coverage=partial,
                          refraction='none', field=query.get('field'),
                          qualification='Orbital prediction only; optical visibility, RF and sightline unverified; no transmit authorization')
        if pointing.settings() != configuration:
            raise ValueError('Pass settings changed; retry')
    return result


def render(result):
    """Withhold oversized results; selectors retain provenance and partial qualifiers."""
    if 'message' in result:
        return catalog_reader.fit(result['message'])
    segment, field = result['segment'], result['field']
    start_label = 'up' if segment and segment['start_kind'] == 'threshold_up' else 'ongoing'
    end_label = 'down' if segment and segment['end_kind'] == 'threshold_down' else 'clipped'
    values = []
    if segment and field != 'window':
        if segment['start_kind'] in {'grazing', 'window_contact'}:
            values = [('at', segment['peak'])]
        else:
            if field in (None, 'start'):
                values.append((start_label, segment['start']))
            if field in (None, 'peak'):
                label = 'max' if segment['complete_pass'] else 'segmax'
                values.append((f"{label}={segment['peak_elevation_deg']:.1f}deg@", segment['peak']))
            if field in (None, 'end'):
                values.append((end_label, segment['end']))
    else:
        values = [('from', result['window_start']), ('to', result['window_end'])]
    stamps = [pointing.utc(stamp) for _, stamp in values]
    same_date = len({stamp.date() for stamp in stamps}) == 1
    events = (stamps[0].strftime('%Y%m%dZ ') if same_date else '') + ' '.join(
        label + stamp.strftime('%H%M%S' if same_date else '%Y%m%dT%H%M%SZ') for (label, _), stamp in zip(values, stamps))
    state = 'no pass;' if segment is None else ''
    if segment and not segment['complete_pass']:
        state = ('boundary contact;' if segment['start_kind'] == 'window_contact' else
                 'contact;' if segment['start_kind'] == 'grazing' else
                 ('ongoing;' if segment['start_kind'] == 'window_start' else '') +
                 ('clipped;' if segment['end_kind'] == 'window_end' else ''))
    if segment and field == 'window':
        state += 'pass found;'
    # Round age up so the displayed bound never understates element age.
    age = math.ceil(result['orbit_age_end_days'] * 10) / 10
    text = (f"{result['norad_id']} pred >={result['minimum_elevation_deg']:g}deg geom;{state}{events};"
            f"GIS:{result['terrain']['source_id']} hW84={result['observer_height_wgs84_m']:.1f}m "
            f"AGL={result['antenna_agl_m']:g}m;orb<={age:g}d;RF/sightline unverified")
    if result['partial_orbit_coverage']:
        text += ';partial sources'
    fitted = catalog_reader.fit(text)
    if fitted != text:
        return catalog_reader.fit('Pass result too long; use field start/peak/end or local --json.')
    return fitted


def main(argv=None):
    """Dedicated CLI with structured results restricted to local invocation."""
    args = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    structured = args[:1] == ['--json']
    if structured:
        if os.environ.get('MESHCORE_REQUEST_ID'):
            print(catalog_reader.fit('JSON is local-only; use !satpass help.'))
            return 0
        args = args[1:]
    try:
        result = lookup(' '.join(args))
        print(json.dumps(result, ensure_ascii=False) if structured else render(result))
    except ImportError:
        message = 'Pass unavailable: tracking or terrain dependency missing'
        print(json.dumps({'error': message}) if structured else catalog_reader.fit(message))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, ArithmeticError, RuntimeError, sqlite3.Error) as exc:
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else 'Catalog, terrain or datum input unavailable'
        message = 'Pass unavailable: ' + message
        print(json.dumps({'error': message}) if structured else catalog_reader.fit(message))
    return 0
