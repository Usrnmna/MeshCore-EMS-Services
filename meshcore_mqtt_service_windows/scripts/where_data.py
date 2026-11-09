"""Bounded, read-only containment over existing installed geographic references."""
import gzip
import hashlib
import io
import json
import re
import time
import zlib

from . import basin_plan_data as basin, dataset_paths, gis_data, stateparks_lookup as parks
from . import water_settings, wildfire_settings

MAX_FEATURES = 20000
MAX_MATCHES = 32
MAX_BASIN_LAYERS = 12
MAX_FILE = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
QUERY_SECONDS = 45
# Legacy readers may expose attribute/index errors for malformed JSON shapes.
# Keep these source failures local to their collection, including corrupt gzip.
FAILURES = (OSError, ValueError, KeyError, TypeError, RuntimeError, EOFError,
            ImportError, AttributeError, IndexError, zlib.error)


class Guard:
    """Pin paths and file identities until all independent results are assembled.

    Existing readers verify content hashes. This guard additionally rejects file
    replacement or managed-path changes after a reader has finished its work.
    """

    def __init__(self, resolver):
        self.resolver = resolver
        self.root = resolver()
        self.files = {}

    def watch(self, relative, limit=MAX_FILE):
        path = dataset_paths.checked_path(self.root, relative)
        stat = path.stat()
        if stat.st_size > limit:
            raise ValueError('Reference exceeds file limit')
        self.files[relative] = (path, (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        return path

    def verify(self):
        if self.resolver() != self.root:
            raise ValueError('Dataset generation changed')
        for relative, (path, expected) in self.files.items():
            if dataset_paths.checked_path(self.root, relative) != path:
                raise ValueError('Dataset path changed during query')
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != expected:
                raise ValueError('Dataset changed during query')


def tick(deadline):
    """Bound scanning time without returning an unqualified partial match set."""
    if time.monotonic() > deadline:
        raise ValueError('Query time limit')


def geographic_features(document):
    """Require a bounded GeoJSON collection in longitude/latitude coordinates.

    GeoJSON without a CRS uses its geographic default. A contradictory explicit
    CRS cannot be interpreted as degrees merely because its numbers are small.
    """
    if (not isinstance(document, dict) or document.get('type') != 'FeatureCollection'
            or not isinstance(document.get('features'), list)):
        raise ValueError('Invalid polygon collection')
    crs = document.get('crs')
    if crs is not None and crs not in (
            {'type': 'name', 'properties': {'name': 'EPSG:4326'}},
            {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'}}):
        raise ValueError('Unsupported polygon CRS')
    if len(document['features']) > MAX_FEATURES:
        raise ValueError('Feature limit')
    return document['features']


def containing(features, point, identity, deadline, repaired=()):
    """Retain all identities, including exact edges; never use nearest geometry.

    Invalid polygons use the existing wildfire geometry repair policy. A repair
    yielding non-area components is rejected rather than treating lines as land.
    """
    if not isinstance(features, list) or len(features) > MAX_FEATURES:
        raise ValueError('Feature limit')
    from .wildfire_spatial import checked_geometry
    from shapely.errors import ShapelyError
    matches, seen = [], set()
    for feature in features:
        tick(deadline)
        if (not isinstance(feature, dict) or feature.get('type') != 'Feature'
                or not isinstance(feature.get('properties'), dict)
                or not isinstance(feature.get('geometry'), dict)
                or feature['geometry'].get('type') not in ('Polygon', 'MultiPolygon')):
            raise ValueError('Invalid polygon feature')
        row = identity(feature)
        identifier = row['id']
        if (not isinstance(identifier, str) or not identifier or identifier in seen
                or any(not c.isprintable() or c.isspace() for c in identifier)):
            raise ValueError('Missing or conflicting source identity')
        seen.add(identifier)
        try:
            geometry = checked_geometry(feature)
        except (ShapelyError, IndexError, AttributeError) as exc:
            raise ValueError('Invalid polygon geometry') from exc
        if geometry.geom_type not in ('Polygon', 'MultiPolygon'):
            raise ValueError('Non-polygon geometry')
        if geometry.covers(point):
            row.update(relation='boundary' if geometry.boundary.covers(point) else 'contains',
                       repaired=bool(feature['properties'].get('geometry_repaired') or identifier in repaired))
            matches.append(row)
    # Scan the complete bounded source before applying the result limit.
    tick(deadline)
    return sorted(matches, key=lambda row: row['id'])


def state_parks(point, deadline, level=None):
    """Read State Parks boundaries once, including recorded repair identities."""
    tick(deadline)
    guard = Guard(lambda: dataset_paths.resolve('california_state_parks', parks.ROOT.parent / 'data/california_state_parks'))
    manifest_path = guard.watch('sources.json', 4 * 1024 * 1024)
    manifest = parks.read_json(manifest_path, 4 * 1024 * 1024)[1]
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1):
        raise ValueError('Unsupported Parks schema')
    entry = manifest['datasets']['park_boundaries']
    guard.watch(entry['path'])
    if entry.get('geometry_repair'):
        guard.watch(entry['geometry_repair']['report_path'])
    data = parks.load_snapshot(('park_boundaries',), directory=guard.root)
    def identity(feature):
        p = feature['properties']
        unit = parks.unit(p.get('UNITNBR'))
        return dict(id='StateParks:FID:' + str(p['FID']), name=p.get('UNITNAME'),
                    followup='!statepark id ' + unit if unit else None, attributes=p)
    rows = containing(data['park_boundaries'], point, identity, deadline,
                      {'StateParks:FID:' + str(i) for i in data['repaired_ids']})
    return rows, guard.verify, dict(coverage='California State Parks boundaries; not all parks or legal access',
                                  evidence=entry.get('checked_at_utc'), source_url=entry.get('layer_url'),
                                  generation=entry['sha256'])


def ebmud(point, deadline, level=None):
    """Keep each EBMUD layer/object distinct even when display names coincide."""
    tick(deadline)
    settings = gis_data.load_settings()
    guard = Guard(lambda: settings['data_directory'])
    # Re-resolve only at final validation to detect managed removal or path swaps.
    guard.resolver = lambda: gis_data.load_settings()['data_directory']
    guard.watch('sources.json', 4 * 1024 * 1024)
    snapshot = gis_data.Snapshot(guard.root)
    if snapshot.manifest.get('coordinate_reference_system') != 'WGS 84 (EPSG:4326)':
        raise ValueError('Unsupported GIS CRS')
    rows, dates = [], []
    for name in gis_data.PARK_LAYERS:
        tick(deadline)
        entry = snapshot.manifest['datasets'][name]
        guard.watch(entry['path'])
        records = snapshot.load_dataset(name)
        features = [dict(type='Feature', geometry=r['geometry'], properties=r['properties']) for r in records]
        field = gis_data.LAYER_FIELDS[name][1]
        def identity(feature):
            p = feature['properties']
            value = p['OBJECTID']
            if type(value) not in (int, str) or not str(value):
                raise ValueError('Invalid GIS identity')
            return dict(id=f'EBMUD:{name}:{value}', name=p.get(field), attributes=p,
                        source=entry['source_url'])
        repaired = {f'EBMUD:{name}:{r["feature_id"]}' for r in entry.get('geometry_repair', {}).get('features', [])}
        rows.extend(containing(features, point, identity, deadline, repaired))
        dates.append(entry.get('retrieved_at_utc'))
    def verify():
        snapshot.verify_unchanged()
        guard.verify()
    return rows, verify, dict(coverage='Installed EBMUD park/recreation layers only; not legal access', evidence=dates,
                             generation=hashlib.sha256(snapshot.manifest_bytes).hexdigest())


def calwater(point, deadline, level=None):
    """Use verified Basin Plan source polygons, preserving all six CalWater levels.

    Water Board regions and named Basin Plan waterbodies are deliberately not
    substituted for CalWater hydrologic classifications.
    """
    tick(deadline)
    config = water_settings.load()
    if not config['enabled']:
        raise ValueError('Water feature disabled')
    collection = basin.Collection(config)
    rows, levels, dates = [], set(), []
    selected = [(key, entry) for key, entry in sorted(collection.entries.items())
                if basin.level(entry) is not None and (not level or basin.LEVELS[basin.level(entry)] == level)]
    if len(selected) > MAX_BASIN_LAYERS:
        raise ValueError('Basin layer limit')
    for key, entry in selected:
        if entry['category'] != 'hydrologic_boundaries/calwater_2_2_1':
            raise ValueError('Unsupported CalWater source')
        index = basin.level(entry)
        tick(deadline)
        levels.add(basin.LEVELS[index])
        raw = collection.checked(collection.path(collection.source, entry['path']), entry)
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            expanded = stream.read(MAX_EXPANDED + 1)
        if len(expanded) > MAX_EXPANDED:
            raise ValueError('Expanded polygon limit')
        document = json.loads(expanded)
        features = geographic_features(document)
        if len(features) != entry['record_count']:
            raise ValueError('Polygon count mismatch')
        evidence = entry['id_evidence_path']
        ids = json.loads(collection.checked(collection.path(collection.source, evidence), collection.manifest['files'][evidence]))['objectIds']
        actual = [basin.key_token([f['properties'][entry['object_id_field']]]) for f in features]
        if len(set(actual)) != len(actual) or set(actual) != {basin.key_token([i]) for i in ids}:
            raise ValueError('Polygon identity mismatch')
        def identity(feature):
            p = feature['properties']
            identifier = basin.identity(key, p[entry['object_id_field']])
            return dict(id=identifier, name=p.get(basin.OWN_NAMES[index]),
                        level=basin.LEVELS[index], classification=basin.LEVEL_NAMES[index],
                        attributes=p, source=entry['source_url'], followup='!basin parent ' + identifier)
        rows.extend(containing(features, point, identity, deadline))
        dates.append(entry.get('completed_at_utc'))
        # Do not retain expanded geometry between layers.
        del features, document, expanded
    if levels != ({level} if level else set(basin.LEVELS)):
        raise ValueError('Incomplete CalWater hierarchy')
    return rows, collection.verify_unchanged, dict(coverage='CalWater v2.2.1 polygons; not Water Board regions or connectivity', evidence=dates,
                                                  generation=collection.manifest['snapshot_id'])


def fire_zones(point, deadline, level=None):
    """Read installed NWS zone references; no cache writes or live hazard lookups."""
    tick(deadline)
    guard = Guard(lambda: dataset_paths.resolve('wildfire', wildfire_settings.ROOT / 'data/wildfire'))
    manifest = parks.read_json(guard.watch('manifest.json', 4 * 1024 * 1024), 4 * 1024 * 1024)[1]
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1):
        raise ValueError('Unsupported zone schema')
    path = guard.watch('zones.geojson')
    evidence = dict(manifest, byte_count=path.stat().st_size)
    document = parks.verified_json(guard.root, 'zones.geojson', evidence)
    features = geographic_features(document)
    if (not features or type(manifest['feature_count']) is not int
            or len(features) != manifest['feature_count']):
        raise ValueError('Zone count mismatch')
    def identity(feature):
        p = feature['properties']
        if (not isinstance(p.get('state'), str) or not re.fullmatch(r'[A-Z]{2}', p['state'])
                or not isinstance(p.get('zone'), str) or not re.fullmatch(r'[0-9]{1,3}', p['zone'])):
            raise ValueError('Invalid zone identity')
        identifier = p['state'] + 'Z' + p['zone'].zfill(3)
        if feature['id'] != identifier or p.get('id') != identifier or p.get('type') != 'fire':
            raise ValueError('Conflicting zone identity')
        return dict(id=identifier, name=p.get('name'), attributes=p, followup='!firezone ' + identifier)
    rows = containing(features, point, identity, deadline)
    if (not isinstance(manifest['zone_ids'], list) or len(manifest['zone_ids']) != len(features)
            or {f['id'] for f in features} != set(manifest['zone_ids'])):
        raise ValueError('Zone membership mismatch')
    return rows, guard.verify, dict(coverage=manifest['selection'], source_url=manifest['source'],
                                  evidence=manifest['retrieved_at'], generation=manifest['sha256'],
                                  qualification='Fire-weather zones, not evacuation zones or current hazards')


def availability():
    """Check local prerequisites without scanning statewide geometry for help.

    This is a manifest/path probe, not a guarantee that a collection will pass
    the complete query-time content and geometry checks.
    """
    import shapely, pyproj
    found = 0
    for kind in ('stateparks', 'ebmud', 'calwater', 'nws'):
        try:
            if kind == 'calwater':
                config = water_settings.load()
                if not config['enabled']:
                    continue
                with basin.Collection(config) as collection:
                    levels = set()
                    for entry in collection.entries.values():
                        index = basin.level(entry)
                        if index is not None:
                            collection.path(collection.source, entry['path']).stat()
                            levels.add(basin.LEVELS[index])
                    if levels != set(basin.LEVELS):
                        continue
            elif kind == 'ebmud':
                snapshot = gis_data.Snapshot(gis_data.load_settings()['data_directory'])
                for name in gis_data.PARK_LAYERS:
                    dataset_paths.checked_path(snapshot.directory, snapshot.manifest['datasets'][name]['path']).stat()
            else:
                root = dataset_paths.resolve('california_state_parks', parks.ROOT.parent / 'data/california_state_parks') if kind == 'stateparks' else dataset_paths.resolve('wildfire', wildfire_settings.ROOT / 'data/wildfire')
                manifest = parks.read_json(root / ('sources.json' if kind == 'stateparks' else 'manifest.json'), 4 * 1024 * 1024)[1]
                if manifest.get('schema_version') != 1:
                    continue
                relative = manifest['datasets']['park_boundaries']['path'] if kind == 'stateparks' else 'zones.geojson'
                dataset_paths.checked_path(root, relative).stat()
            found += 1
        except FAILURES:
            pass
    return found


SOURCES = {'park': (('stateparks', state_parks), ('ebmud', ebmud)),
           'basin': (('calwater', calwater),), 'firezone': (('nws', fire_zones),)}
