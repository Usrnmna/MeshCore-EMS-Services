"""Read installed Basin Plan indexes without modifying or acquiring datasets."""
import csv
import gzip
import hashlib
import io
import json
import time

from . import dataset_paths, water_settings

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_ROWS = 1000000
QUERY_SECONDS = 25
WATER_LAYERS = {'BasinPlanLines', 'BasinPlanPolys', 'BPLinesDiss', 'BPPolysDiss',
                'Beneficial Use Lines', 'Beneficial Use Polygons'}
USE_LAYERS = {'WB_BenUses', 'BeneficialUses'}
LEVELS = ('Region', 'Unit', 'Area', 'Subarea', 'SPW', 'PW')
LEVEL_NAMES = ('hydrologic region', 'hydrologic unit', 'hydrologic area',
               'hydrologic subarea', 'super planning watershed', 'planning watershed')
LEVEL_FIELDS = ('hrc', 'rbu', 'rbua', 'rbuas', 'rbuasp', 'rbuaspw')
OWN_NAMES = ('hrc', 'huname', 'first_haname', 'first_hsaname',
             'first_cdfspwname', 'first_cdfpwsname')


class Unavailable(ValueError):
    """The selected installed collection cannot establish a qualified answer."""


def attributes(values):
    """Normalize field spelling only; source values and their types remain intact."""
    result = {key.lower(): value for key, value in values.items()}
    if 'wbrefkey' in result:
        result.setdefault('wb_refkey', result['wbrefkey'])
    return result


def key_token(values):
    """Match published numeric keys while keeping string keys and zeroes distinct."""
    return json.dumps([int(v) if type(v) is float and v.is_integer() else v for v in values],
                      ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def level(entry):
    name = entry['name'].removeprefix('CalWater_Hydrologic_')
    return LEVELS.index(name) if entry['name'].startswith('CalWater_Hydrologic_') and name in LEVELS else None


def identity(key, identifier):
    """A complete service/layer/object identity never reuses a hydrographic reach namespace."""
    return f'BP:{key}:{identifier}'


class Collection:
    """Pin source and organized generations; verify every file used by a query.

    Queries read the installed membership and relationship indexes, not geometry.
    Byte, row and time bounds fail visibly rather than returning unverified data.
    """

    def __init__(self, config):
        configured = water_settings.data_root(config) / 'basin_plans'
        self.root = dataset_paths.resolve('basin_plans', configured, configured=configured,
            defaults=(water_settings.ROOT / '../data/basin_plans',))
        self.config = config
        self.deadline = time.monotonic() + QUERY_SECONDS
        self.signatures = {}
        self.cache = {}
        self.pointer_bytes = self.read_pointer()
        pointer = json.loads(self.pointer_bytes)
        manifest_path = self.path(self.root, pointer['manifest_path'])
        self.source = manifest_path.parent
        self.manifest = json.loads(self.checked(manifest_path, {'sha256': pointer['manifest_sha256']}))
        self.review = self.path(self.root, pointer['organization_path'])
        self.report = json.loads(self.checked(self.review / 'organization.json',
                                             {'sha256': pointer['organization_manifest_sha256']}))
        entries = self.manifest['datasets']
        keys = sorted(e['key'] for e in entries)
        if any(type(document.get('schema_version')) is not int or document['schema_version'] != 1
               for document in (pointer, self.manifest, self.report)):
            raise Unavailable('Unsupported Basin Plan schema version')
        if (self.manifest.get('complete') is not True or self.manifest['snapshot_id'] != pointer['snapshot_id']
                or self.report['snapshot_id'] != pointer['snapshot_id']
                or self.report['source_manifest_sha256'] != pointer['manifest_sha256']
                or self.report['dataset_keys'] != keys or self.report['dataset_count'] != len(keys)
                or len(set(keys)) != len(keys)):
            raise Unavailable('Incompatible Basin Plan generations')
        self.entries = {e['key']: e for e in entries}

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.verify_unchanged()

    def tick(self):
        if time.monotonic() > self.deadline:
            raise Unavailable('Basin Plan query limit; narrow source selection')

    @staticmethod
    def path(root, relative):
        return dataset_paths.checked_path(root, relative)

    def read_pointer(self):
        """Read the source pin; composed queries may override this to share a byte budget."""
        return (self.root / 'sources.json').read_bytes()

    def checked(self, path, evidence):
        """Hash the exact bytes consumed and remember file identity for the final check."""
        self.tick()
        if path in self.cache:
            raw = self.cache[path]
        else:
            before = path.stat()
            if before.st_size > MAX_FILE_BYTES:
                raise Unavailable('Basin Plan file exceeds query limit')
            raw = path.read_bytes()
            after = path.stat()
            signature = (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            if signature != (before.st_size, before.st_mtime_ns, before.st_ctime_ns):
                raise Unavailable('Basin Plan file changed during query')
            self.signatures[path] = signature
            self.cache[path] = raw
        if (hashlib.sha256(raw).hexdigest() != evidence['sha256']
                or len(raw) != evidence.get('byte_count', len(raw))):
            raise Unavailable('Basin Plan integrity failure')
        return raw

    def review_bytes(self, relative):
        return self.checked(self.path(self.review, relative), self.report['files'][relative])

    def csv_rows(self, relative, compressed=False):
        """Stream complete verified CSV membership with bounded expansion and row count."""
        raw = self.review_bytes(relative)
        stream = gzip.GzipFile(fileobj=io.BytesIO(raw)) if compressed else io.BytesIO(raw)
        with io.TextIOWrapper(stream, encoding='utf-8-sig', newline='') as text:
            for count, row in enumerate(csv.DictReader(text), 1):
                if count > MAX_ROWS or stream.tell() > MAX_EXPANDED_BYTES:
                    raise Unavailable('Basin Plan index exceeds query limit')
                if count % 1000 == 0:
                    self.tick()
                yield row

    def members(self, key):
        entry = self.entries[key]
        token = hashlib.sha256(key.encode()).hexdigest()[:16]
        path = f"{entry['category']}/relationships/record_keys/{token}.csv.gz"
        count = 0
        for row in self.csv_rows(path, True):
            count += 1
            yield row
        if count != entry['record_count']:
            raise Unavailable('Basin Plan membership count mismatch')

    def record(self, key, object_id):
        """Find exactly one object without coercing numeric-looking string identifiers."""
        if key not in self.entries:
            return None
        matches = [r for r in self.members(key) if str(json.loads(r['object_id_json'])) == object_id]
        if len(matches) > 1:
            raise Unavailable('Ambiguous source object identity')
        return matches[0] if matches else None

    def relations(self, family):
        return self.csv_rows(f'relationships/{family}.csv')

    def matching_members(self, key, fields, token):
        """Expand complete membership, never the relationship table's sample IDs."""
        wanted = json.loads(token)
        if not wanted or any(v is None or isinstance(v, str) and not v.strip() for v in wanted):
            return []
        result = []
        for row in self.members(key):
            values = attributes(json.loads(row['source_keys_json']))
            if key_token([values.get(f) for f in fields]) == key_token(wanted):
                result.append(row)
                if len(result) > 100:
                    raise Unavailable('Relationship membership exceeds query limit')
        return result

    def table(self, key):
        """Read designation attributes and metadata, retaining codes without invented translations."""
        entry = self.entries[key]
        raw = self.checked(self.path(self.source, entry['path']), entry)
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            expanded = stream.read(MAX_EXPANDED_BYTES + 1)
        if len(expanded) > MAX_EXPANDED_BYTES:
            raise Unavailable('Designation table exceeds query limit')
        rows = json.loads(expanded)['rows']
        evidence = entry['id_evidence_path']
        ids = json.loads(self.checked(self.path(self.source, evidence), self.manifest['files'][evidence]))['objectIds']
        actual = [key_token([r[entry['object_id_field']]]) for r in rows]
        if (len(rows) != entry['record_count'] or len(set(actual)) != len(actual)
                or set(actual) != {key_token([i]) for i in ids}):
            raise Unavailable('Designation membership mismatch')
        metadata = entry['metadata_path']
        schema = json.loads(self.checked(self.path(self.source, metadata), self.manifest['files'][metadata]))
        return rows, schema

    def verify_unchanged(self):
        """Reject pointer swaps, removals, and file replacements before publishing a result."""
        self.tick()
        configured = water_settings.data_root(self.config) / 'basin_plans'
        selected = dataset_paths.resolve('basin_plans', configured, configured=configured,
            defaults=(water_settings.ROOT / '../data/basin_plans',))
        if selected != self.root or self.read_pointer() != self.pointer_bytes:
            raise Unavailable('Basin Plan generation changed during query')
        for path, signature in self.signatures.items():
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != signature:
                raise Unavailable('Basin Plan file changed during query')
