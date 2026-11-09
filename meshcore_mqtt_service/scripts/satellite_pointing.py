"""Bounded orbital pointing using exact catalog identity and qualified GIS terrain."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys

from . import satellite_lookup as catalog_reader
from . import satellite_terrain

# Same shipped policy as the independent satellite catalog; installed settings
# remain authoritative. Terrain sources are explicitly configured, never guessed.
DEFAULT_ORBIT_AGE_DAYS = 14
HELP = '!satpoint ID LAT LON [agl M] [terrain ID] [orbit ID]; WGS84 degrees; GIS required; agl defaults 0m; help units'
UNITS_HELP = 'azT: true north clockwise; el: geometric degrees, no refraction; hW84: WGS84 ellipsoid metres; AGL: above ground metres'


def settings():
    """Read the same external settings context as W11, without maintenance imports."""
    override = os.environ.get('MESHCORE_SATELLITE_SETTINGS')
    path = Path(override).resolve() if override is not None else catalog_reader.ROOT / 'satellite-settings.json'
    values = catalog_reader.read_json(path) if override is not None or path.exists() else {}
    age = values.get('orbit_max_age_days', DEFAULT_ORBIT_AGE_DAYS)
    if type(age) not in (int, float) or not math.isfinite(age) or age <= 0:
        raise ValueError('Invalid orbit freshness policy')
    return values, path.parent, age


def parse(text):
    """Parse finite WGS84 latitude/longitude and explicit bounded selectors."""
    if len(text.encode('utf-8')) > 150 or any(not c.isprintable() for c in text):
        raise ValueError('Invalid or oversized pointing query')
    words = text.split()
    if not words or words in (['help'], ['--help']):
        return None
    if words == ['help', 'units']:
        return {'help': 'units'}
    if len(words) < 3 or not re.fullmatch('[1-9][0-9]{0,8}', words[0]):
        raise ValueError('Use !satpoint NORAD-ID LAT LON; help')
    try:
        latitude, longitude = float(words[1]), float(words[2])
    except ValueError as exc:
        raise ValueError('Invalid WGS84 coordinates') from exc
    if not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError('WGS84 coordinates out of range')
    result = dict(norad=int(words[0]), latitude=latitude, longitude=longitude, agl=0.0)
    seen = set()
    if len(words[3:]) % 2:
        raise ValueError('Incomplete pointing selector')
    for key, value in zip(words[3::2], words[4::2]):
        if key not in {'agl', 'terrain', 'orbit'} or key in seen:
            raise ValueError('Unknown or repeated pointing selector')
        seen.add(key)
        if key == 'agl':
            try:
                value = float(value)
            except ValueError as exc:
                raise ValueError('AGL must be metres from 0 to 1000') from exc
            if not math.isfinite(value) or not 0 <= value <= 1000:
                raise ValueError('AGL must be metres from 0 to 1000')
        elif not re.fullmatch('[A-Za-z0-9_-]{1,12}', value):
            raise ValueError('Invalid source selector')
        result[key] = value
    return result


def utc(value, *, omm=False):
    """Normalize explicit timestamps; only OMM's specified UTC field allows no suffix."""
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Invalid orbit timestamp') from exc
    if stamp.utcoffset() is None:
        if not omm:
            raise ValueError('Undated orbit timestamp')
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def exact_satellite(db, number):
    """Apply W11 exact identity and lifecycle checks in the pinned read transaction."""
    rows = db.execute('SELECT * FROM satellites WHERE norad_id=? LIMIT 2', (number,)).fetchall()
    if not rows:
        raise ValueError('Satellite not in installed catalog')
    if len(rows) != 1:
        raise ValueError('Ambiguous NORAD identity')
    satellite = dict(rows[0])
    raw = json.loads(satellite['data_json'])
    for key in ('satellite_id', 'norad_id', 'name', 'lifecycle'):
        if key in raw and raw[key] != satellite[key]:
            raise ValueError('Conflicting satellite identity')
    catalog_reader.validate_identifier(satellite['satellite_id'], 'satellite')
    if (satellite['lifecycle'] or '').casefold() in catalog_reader.RETIRED:
        raise ValueError('Satellite lifecycle excludes pointing')
    return satellite


def orbit_id(row):
    """Return a stable selector for the schema's source URL and format key."""
    return hashlib.sha256((row['source_url'] + '\0' + row['format']).encode()).hexdigest()[:12]


def norad_number(value):
    """Accept integer NORAD identities without truncating fractional source values."""
    if isinstance(value, str) and re.fullmatch('[0-9]{1,9}', value):
        value = int(value)
    if type(value) is not int or not 0 < value < 1000000000:
        raise ValueError('Invalid orbit NORAD identity')
    return value


def build_orbit(row, satellite, timescale):
    """Validate source identity, format and epoch before constructing an SGP4 model."""
    from skyfield.api import EarthSatellite
    values = json.loads(row['data_json'])
    if values.get('sat_id', satellite['satellite_id']) != satellite['satellite_id']:
        raise ValueError('Orbit source satellite identity mismatch')
    number = satellite['norad_id']
    if row['format'] == 'OMM_JSON':
        if norad_number(values['NORAD_CAT_ID']) != number:
            raise ValueError('Orbit NORAD identity mismatch')
        for key, expected in [('CENTER_NAME', 'EARTH'), ('REF_FRAME', 'TEME'),
                              ('TIME_SYSTEM', 'UTC'), ('MEAN_ELEMENT_THEORY', 'SGP4')]:
            if values.get(key, expected) != expected:
                raise ValueError('Unsupported OMM reference convention')
        for key in ('MEAN_MOTION', 'ECCENTRICITY', 'INCLINATION', 'RA_OF_ASC_NODE',
                    'ARG_OF_PERICENTER', 'MEAN_ANOMALY', 'BSTAR', 'MEAN_MOTION_DOT', 'MEAN_MOTION_DDOT'):
            if isinstance(values[key], bool) or not math.isfinite(float(values[key])):
                raise ValueError('Invalid OMM numeric element')
        epoch = utc(values['EPOCH'], omm=True)
        values['EPOCH'] = epoch.strftime('%Y-%m-%dT%H:%M:%S.%f')
        model = EarthSatellite.from_omm(timescale, values)
    elif row['format'] == 'TLE':
        for index, key in enumerate(('tle1', 'tle2'), 1):
            line = values[key]
            if not isinstance(line, str) or len(line) != 69 or not line.startswith(str(index) + ' '):
                raise ValueError('Malformed TLE')
            checksum = sum(int(c) if c.isdigit() and c.isascii() else 1 if c == '-' else 0 for c in line[:68]) % 10
            if line[-1] != str(checksum) or values['tle1'][2:7] != values['tle2'][2:7]:
                raise ValueError('TLE checksum or identity mismatch')
        if 'norad_cat_id' in values and norad_number(values['norad_cat_id']) != number:
            raise ValueError('Orbit NORAD identity mismatch')
        model = EarthSatellite(values['tle1'], values['tle2'], values.get('tle0', ''), timescale)
    else:
        raise ValueError('Unsupported orbit format')
    if model.model.satnum != number:
        raise ValueError('Orbit NORAD identity mismatch')
    if not (0 <= model.model.ecco < 1 and 0 <= model.model.inclo <= math.pi and model.model.no_kozai > 0):
        raise ValueError('Invalid orbital elements')
    if abs((model.epoch.utc_datetime() - utc(row['epoch'])).total_seconds()) > 1:
        raise ValueError('Orbit epoch disagrees with source elements')
    return model


def choose_orbit(db, satellite, now, maximum_age, selector, timescale):
    """Reject stale/future elements; multiple eligible sources require selection."""
    rows = db.execute('SELECT * FROM orbits WHERE satellite_id=? ORDER BY source_url,format LIMIT 21',
                      (satellite['satellite_id'],)).fetchall()
    if len(rows) > 20:
        raise ValueError('Orbit inventory exceeds bounded lookup limit')
    if selector:
        rows = [row for row in rows if orbit_id(row) == selector]
        if len(rows) != 1:
            raise ValueError('Unknown or conflicting orbit source ID')
    eligible, rejected = [], []
    for row in rows:
        try:
            model = build_orbit(row, satellite, timescale)
            age = (now - model.epoch.utc_datetime()).total_seconds() / 86400
            if age < 0:
                raise ValueError('Future orbital elements unavailable')
            if age > maximum_age:
                raise ValueError('Stale orbital elements unavailable')
            eligible.append((row, model, age))
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            rejected.append(str(exc))
    if not eligible:
        raise ValueError(rejected[0] if len(set(rejected)) == 1 else 'No eligible orbital elements; missing, stale or invalid')
    if len(eligible) != 1:
        ids = [orbit_id(row) for row, _, _ in eligible]
        if len(set(ids)) != len(ids):
            raise ValueError('Conflicting orbit source IDs')
        raise ValueError('Select orbit ' + ','.join(ids[:4]) + ('; partial' if len(ids) > 4 else ''))
    return eligible[0], bool(rejected)


def angles(model, timescale, now, latitude, longitude, height):
    """Calculate unrefracted topocentric angles, clockwise from true north."""
    from skyfield.api import wgs84
    instant = timescale.from_datetime(now)
    observer = wgs84.latlon(latitude, longitude, elevation_m=height)
    relative = (model - observer).at(instant)
    if relative.message:
        raise ValueError('Orbit propagation failed')
    elevation, azimuth, distance = relative.altaz()
    el, az, km = float(elevation.degrees), float(azimuth.degrees), float(distance.km)
    if not all(math.isfinite(value) for value in (el, az, km)) or km <= 0:
        raise ValueError('Invalid propagated position')
    # At zenith/nadir azimuth is ill-conditioned; at a pole local north is undefined.
    if abs(math.cos(math.radians(el))) < 1e-7 or abs(latitude) == 90:
        az = None
    return dict(azimuth_true_deg=az, elevation_deg=el, range_km=km,
                above_geometric_horizon=el > 0, refraction='none')


def lookup(text, now=None):
    """Pin settings, orbit generation and terrain for one prediction at query time."""
    query = parse(text)
    if query is None:
        return {'message': HELP}
    if query.get('help'):
        return {'message': UNITS_HELP}
    configuration = settings()
    values, base, maximum_age = configuration
    # Fail explicitly before importing optional tracking when no terrain is configured.
    satellite_terrain.sources(values, base, query.get('terrain'))
    from skyfield.api import load
    timescale = load.timescale(builtin=True)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with catalog_reader.catalog() as (db, _):
        satellite = exact_satellite(db, query['norad'])
        (orbit, model, age), partial = choose_orbit(db, satellite, now, maximum_age, query.get('orbit'), timescale)
        with satellite_terrain.terrain(values, base, query['latitude'], query['longitude'], query.get('terrain')) as terrain:
            height = terrain['ellipsoid_height_m'] + query['agl']
            result = angles(model, timescale, now, query['latitude'], query['longitude'], height)
            result.update(norad_id=query['norad'], satellite_id=satellite['satellite_id'], predicted_at=now.isoformat(),
                          latitude=query['latitude'], longitude=query['longitude'], observer_height_wgs84_m=height,
                          antenna_agl_m=query['agl'], terrain=terrain, orbit_id=orbit_id(orbit),
                          orbit_epoch=model.epoch.utc_datetime().isoformat(), catalog_orbit_epoch=orbit['epoch'],
                          orbit_source=orbit['source_url'], orbit_age_days=age, orbit_max_age_days=maximum_age,
                          partial_orbit_coverage=partial, qualification='Prediction only; RF and sightline unverified')
        if settings() != configuration:
            raise ValueError('Pointing settings changed; retry')
    return result


def render(result):
    """Keep complete qualifications or withhold the radio prediction."""
    if 'message' in result:
        return catalog_reader.fit(result['message'])
    timestamp = utc(result['predicted_at']).strftime('%Y%m%dT%H%M%SZ')
    azimuth = '?' if result['azimuth_true_deg'] is None else f"{round(result['azimuth_true_deg'], 1) % 360:.1f}"
    horizon = 'above' if result['above_geometric_horizon'] else 'below'
    text = (f"{result['norad_id']} pred {timestamp} azT={azimuth}deg el={result['elevation_deg']:.1f}deg {horizon}; "
            f"GIS:{result['terrain']['source_id']} hW84={result['observer_height_wgs84_m']:.1f}m "
            f"AGL={result['antenna_agl_m']:g}m; orb={result['orbit_age_days']:.1f}d; geom; RF/sightline unverified")
    if result['partial_orbit_coverage']:
        text += '; partial sources'
    return catalog_reader.fit(text)


def main(argv=None):
    """Run a read-only query; full structured output remains local-only."""
    args = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    structured = args[:1] == ['--json']
    if structured:
        if os.environ.get('MESHCORE_REQUEST_ID'):
            print(catalog_reader.fit('JSON is local-only; use !satpoint help.'))
            return 0
        args = args[1:]
    try:
        result = lookup(' '.join(args))
        print(json.dumps(result, ensure_ascii=False) if structured else render(result))
    except ImportError:
        message = 'Pointing unavailable: tracking or terrain dependency missing'
        print(json.dumps({'error': message}) if structured else catalog_reader.fit(message))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, ArithmeticError, RuntimeError, sqlite3.Error) as exc:
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else 'Catalog, terrain or datum input unavailable'
        message = 'Pointing unavailable: ' + message
        print(json.dumps({'error': message}) if structured else catalog_reader.fit(message))
    return 0
