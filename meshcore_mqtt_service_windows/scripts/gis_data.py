"""Local GIS configuration, query parsing, and verified snapshot access.

No network operations are performed. Field mappings are centralized below;
source URLs and snapshot filenames remain in the shared sources.json manifest.
"""

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

if __package__:
    from . import dataset_paths
else:
    import dataset_paths


SETTINGS_FILE = Path(__file__).resolve().parents[1] / 'gis_settings.json'
MAX_QUERY_CHARACTERS = 150
# Dataset: (display category, name field, allowed geometry types).
LAYER_FIELDS = {
    'trails': ('Trail', 'TRAIL_NAME', {'LineString', 'MultiLineString'}),
    'additional_trails': ('Trail', 'TRAIL_NAME', {'LineString', 'MultiLineString'}),
    'recreation_points': ('Recreation', 'LABEL', {'Point'}),
    'peaks': ('Peak', 'PEAK_NAME', {'Point'}),
    'trail_endpoints': ('Endpoint', 'TRAIL_NAME', {'Point'}),
    'ebrpd': ('Park', 'NAME', {'Polygon', 'MultiPolygon'}),
    'ebrpd_display_2_jan_14': ('Park', 'NAME', {'Polygon', 'MultiPolygon'}),
    'adjacent_local_parks_jan_14': ('Park', 'SITE_NAME', {'Polygon', 'MultiPolygon'}),
    'recreation_areas': ('Recreation area', 'NAME', {'Polygon', 'MultiPolygon'}),
    'reservoirs': ('Reservoir', 'COMMENT_', {'Polygon', 'MultiPolygon'}),
    'watershed_boundary': ('Watershed', 'COUNTY', {'Polygon', 'MultiPolygon'}),
}
PARK_LAYERS = ('ebrpd', 'ebrpd_display_2_jan_14', 'adjacent_local_parks_jan_14',
               'recreation_areas')
BOUNDARY_LAYERS = PARK_LAYERS + ('reservoirs', 'watershed_boundary')

# Command vocabulary and boundary categories are shared by parsing and help text.
SUBCOMMANDS = {
    'trail': ('dogs', 'horses', 'bikes', 'length', 'difficulty', 'gain', 'surface',
              'shade', 'time', 'start', 'areas', 'description', 'info'),
    'rec': ('type', 'parking', 'restrooms', 'water', 'picnic', 'fishing',
            'boatlaunch', 'boatrental', 'playground', 'horsetrailers', 'location', 'info'),
    'peak': ('elevation', 'location', 'info'),
    'park': ('status', 'agency', 'trails', 'recreation', 'info'),
    'boundary': ('parks', 'watersheds', 'reservoirs', 'recreation'),
}
BOUNDARY_FILTERS = {
    'parks': ('ebrpd', 'ebrpd_display_2_jan_14', 'adjacent_local_parks_jan_14'),
    'watersheds': ('watershed_boundary',),
    'reservoirs': ('reservoirs',),
    'recreation': ('recreation_areas',),
}


class GISUnavailable(RuntimeError):
    """A required local snapshot cannot support a reliable result."""


def load_settings(path=SETTINGS_FILE):
    """Read tunable settings; resolve a relative data path against the settings file."""
    path = Path(path).resolve()
    settings = json.loads(path.read_text(encoding='utf-8'))
    for key in ('maximum_radius_miles',):
        value = settings[key]
        if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{key} must be a positive finite number')
    # Older files may retain default_radius_miles; omitted radii never use it.
    for key, low, high in [('max_results', 1, 20), ('max_reply_bytes', 200, 2000),
                           ('description_characters', 0, 500)]:
        if type(settings[key]) is not int or not low <= settings[key] <= high:
            raise ValueError(f'{key} must be an integer between {low} and {high}')
    if type(settings['include_unnamed_peaks']) is not bool:
        raise ValueError('include_unnamed_peaks must be true or false')
    bounds = settings['search_bounds']
    if (not isinstance(bounds, list) or len(bounds) != 4 or
            any(type(v) not in (float, int) or not math.isfinite(v) for v in bounds) or
            not -180 <= bounds[0] < bounds[2] <= 180 or
            not -90 <= bounds[1] < bounds[3] <= 90):
        raise ValueError('search_bounds must be [west, south, east, north]')
    configured = (path.parent / settings['data_directory']).resolve()
    settings['data_directory'] = dataset_paths.resolve(
        'ebmud', configured, configured=configured,
        defaults=(SETTINGS_FILE.parent / '../data/ebmud',),
    )
    return settings


def parse_query(text):
    """Return mode/value for a name, coordinates, near coordinates, or trail name.

    Optional near radius is expressed in miles. Only syntax and global coordinate
    bounds are checked here; configured radius and projection bounds are checked
    in the lookup process. The parser is safe to import into the responder.
    """
    if not isinstance(text, str) or not text or len(text) > MAX_QUERY_CHARACTERS:
        raise ValueError('A name or coordinates are required (maximum 150 characters).')
    if any(not char.isprintable() for char in text):
        raise ValueError('Control characters are not allowed.')
    text = ' '.join(text.split())
    if not text or text.startswith('-') and not re.match(r'-\d', text):
        raise ValueError('A feature name or coordinates are required.')
    words = text.replace(',', ' ').split()
    near = words[0].casefold() == 'near'
    if near or re.match(r'^[+\-\d.]', text):
        values = words[1:] if near else words
        if len(values) not in ((2, 3) if near else (2,)):
            raise ValueError('Use near LATITUDE LONGITUDE [RADIUS_MILES].')
        try:
            numbers = tuple(float(value) for value in values)
        except ValueError:
            raise ValueError('Coordinates and radius must be numbers.') from None
        if not all(math.isfinite(value) for value in numbers):
            raise ValueError('Coordinates and radius must be finite.')
        if not -90 <= numbers[0] <= 90 or not -180 <= numbers[1] <= 180:
            raise ValueError('Latitude must be -90..90; longitude -180..180.')
        if len(numbers) == 3 and numbers[2] <= 0:
            raise ValueError('Radius must be positive.')
        return ('near' if near else 'coordinates'), numbers
    if text.casefold().startswith('trail '):
        return 'trail', text[6:].strip()
    if not any(char.isalnum() for char in text):
        raise ValueError('A feature name is required.')
    return 'name', text


def parse_command_query(kind, text):
    """Parse a named attribute, filtered proximity, or boundary-category query.

    Return (mode, value, attribute). Coordinate values retain whether a radius
    was supplied; an absent radius means closest-only, never a default radius.
    Reserved attributes precede near and follow names. Boundary categories
    precede coordinates, near, or trail NAME. No data or projection is loaded.
    """
    if kind not in SUBCOMMANDS:
        raise ValueError('Unknown GIS command.')
    mode, value = parse_query(text)
    words = text.split()
    if text.strip().casefold() == 'help':
        return 'help', None, None
    attribute = None
    if kind == 'boundary':
        if words[0].casefold() in BOUNDARY_FILTERS:
            attribute = words.pop(0).casefold()
            mode, value = parse_query(' '.join(words))
        if mode not in {'coordinates', 'near', 'trail'}:
            raise ValueError('Use !boundary [CATEGORY] LAT LON, near LAT LON [MILES], or trail NAME.')
    elif len(words) > 1 and words[1].casefold() == 'near':
        attribute = words[0].casefold()
        if attribute not in SUBCOMMANDS[kind]:
            raise ValueError(f'Unknown !{kind} subcommand: {attribute}. Use !{kind} help.')
        mode, value = parse_query(' '.join(words[1:]))
    elif mode not in {'coordinates', 'near'}:
        mode, value = 'name', ' '.join(words)
        if len(words) > 1 and words[-1].casefold() in SUBCOMMANDS[kind]:
            attribute = words[-1].casefold()
            value = ' '.join(words[:-1])
    return mode, value, attribute


def normalize_name(name):
    """Normalize case, punctuation, accents, and an optional trailing Trail label."""
    name = unicodedata.normalize('NFKD', str(name)).casefold()
    name = ''.join(char for char in name if not unicodedata.combining(char))
    name = re.sub(r"['\u2019]", '', name)
    name = ' '.join(re.sub(r'[^\w\s]', ' ', name).split())
    return re.sub(r'\s+trail$', '', name)


def group_features(records):
    """Group same-category names without discarding separate source records."""
    groups = {}
    for record in records:
        key = (record['category'], normalize_name(record['name']))
        groups.setdefault(key, []).append(record)
    return sorted(groups.values(), key=lambda group: (group[0]['name'].casefold(), group[0]['category']))


def find_by_name(groups, query):
    """Prefer exact normalized matches; return all partial matches if none are exact."""
    query = normalize_name(query)
    exact = [group for group in groups if normalize_name(group[0]['name']) == query]
    return exact or [group for group in groups if query in normalize_name(group[0]['name'])]


class Snapshot:
    """Read a consistent, integrity-checked set of local layers for one request."""

    def __init__(self, directory):
        """Capture manifest bytes before reading layers; reject an active refresh."""
        self.directory = Path(directory)
        self.loaded = {}
        self.check_lock()
        self.manifest_bytes = (self.directory / 'sources.json').read_bytes()
        self.manifest = json.loads(self.manifest_bytes)

    def check_lock(self):
        """Reject refresh overlap and retained refresh recovery directories."""
        if ((self.directory / '.refresh.lock').exists() or
                any(self.directory.glob('.refresh-*'))):
            raise GISUnavailable('GIS refresh or recovery is pending; retry after it completes.')

    def load_dataset(self, name):
        """Verify checksum/count, retain source fields, and expose named features."""
        if name in self.loaded:
            return self.loaded[name]
        self.check_lock()
        entry = self.manifest['datasets'][name]
        path = (self.directory / entry['path']).resolve()
        if not path.is_relative_to(self.directory.resolve()):
            raise GISUnavailable('GIS dataset path is outside the data directory.')
        raw = path.read_bytes()
        if len(raw) != entry['byte_count'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise GISUnavailable(f'GIS snapshot integrity check failed: {name}.')
        document = json.loads(raw)
        if (document.get('type') != 'FeatureCollection' or
                not isinstance(document.get('features'), list) or
                len(document['features']) != entry['feature_count']):
            raise GISUnavailable(f'Invalid GIS feature collection: {name}.')
        category, name_field, allowed_geometry = LAYER_FIELDS[name]
        records = []
        for feature in document['features']:
            properties = feature.get('properties')
            geometry = feature.get('geometry')
            if feature.get('type') != 'Feature' or not isinstance(properties, dict):
                raise GISUnavailable(f'Invalid GIS feature: {name}.')
            if geometry is not None and (not isinstance(geometry, dict) or
                                         geometry.get('type') not in allowed_geometry):
                raise GISUnavailable(f'Unexpected GIS geometry: {name}.')
            label = properties.get(name_field)
            named = isinstance(label, str) and bool(label.strip())
            if not named:
                label = f'Unnamed {category.lower()} #{feature.get("id", len(records))}'
            records.append({'name': label, 'named': named, 'category': category,
                            'dataset': name, 'properties': properties, 'geometry': geometry})
        self.loaded[name] = records
        return records

    def verify_unchanged(self):
        """Reject a refresh completed during the request before exposing its answer."""
        self.check_lock()
        if (self.directory / 'sources.json').read_bytes() != self.manifest_bytes:
            raise GISUnavailable('GIS snapshots changed during lookup; retry the command.')

    def date_label(self):
        """Return the oldest retrieval date among layers used, not a source-edit date."""
        dates = [datetime.fromisoformat(self.manifest['datasets'][name]['retrieved_at_utc'])
                 for name in self.loaded]
        return min(dates).date().isoformat()
