"""Read reviewed static-hazard collections without acquisition or activation.

The optional flood_hazards collection uses static.json and a checksum-pinned
static/GENERATION/manifest.json. Schema 1 has kind static_flood_hazard, complete,
generation, files, and products. Each product identifies source/product/version,
generation, publication_status, regions, qualifications, review_reference,
evidence_files, zones, and coverage. Zones specify path, id_field, record_count,
complete and fields; coverage specifies path (or null), id_field, record_count,
state_field, complete, and reference. Completeness requires reviewed export
evidence, not merely a valid file or a provider's mapped flag.
Optional zones.missing_values maps field-view names to reviewed source sentinels;
sentinels are preserved in original properties and never used as measurements.
Per-measurement units and vertical_reference fields override shared fields even
when their recorded value is missing; no units or reference are inferred.
Field mappings expose recorded values, not cross-provider reclassifications.
Admission/acquisition tooling is intentionally outside this runtime contract.
"""
import gzip
import io
import json
import math
import time

from . import dataset_paths, flood_evidence, flood_reference_data, water_settings
from .flood_reference_data import EvidenceError

MAX_PRODUCTS = 64
MAX_FEATURES = 2048
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
PUBLICATION_STATES = ('effective', 'preliminary', 'historical', 'superseded', 'unknown')
FIELDS = ('zone_code', 'description', 'probability_class', 'regulatory_status',
          'study_date', 'effective_date', 'qualification', 'base_flood_elevation',
          'depth', 'units', 'vertical_reference')
MEASUREMENT_FIELDS = ('base_flood_elevation_units', 'base_flood_elevation_vertical_reference',
                      'depth_units', 'depth_vertical_reference')


def resolve(config):
    """Honor existing custom roots and explicit managed removal without fallback."""
    configured = water_settings.data_root(config) / 'flood_hazards'
    return dataset_paths.resolve('flood_hazards', configured, configured=configured,
        defaults=(water_settings.ROOT / '../data/flood_hazards',))


def strict_json(raw):
    """Reject non-finite numbers and duplicate keys rather than choose a value."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EvidenceError('duplicate_json_key')
            result[key] = value
        return result

    def constant(value):
        raise EvidenceError('nonfinite_json_value')

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise EvidenceError('nonfinite_json_value')
        return parsed

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


class Snapshot(flood_reference_data.Snapshot):
    """Reuse bounded hashing/path reads while keeping hazard and CatFIM pins separate."""

    def __init__(self, config):
        self.config = dict(config)
        self.until = time.monotonic() + flood_reference_data.VERIFY_SECONDS
        self.remaining = flood_reference_data.MAX_BYTES
        self.expanded_remaining = MAX_EXPANDED_BYTES
        self.signatures = {}
        self.verified = set()
        self.cache = {}
        self.root = resolve(config)
        if not (self.root / 'static.json').exists():
            raise EvidenceError('not_installed')
        self.pointer_bytes = self.read(self.root / 'static.json', MAX_DOCUMENT_BYTES)
        pointer = strict_json(self.pointer_bytes)
        if not isinstance(pointer, dict):
            raise EvidenceError('invalid_generation_pointer')
        self.manifest_path = dataset_paths.checked_path(self.root, pointer['manifest_path'])
        self.directory = self.manifest_path.parent
        self.manifest = strict_json(self.checked(self.manifest_path, pointer, metadata=True))
        m = self.manifest
        if not isinstance(m, dict):
            raise EvidenceError('invalid_generation_manifest')
        if (type(m.get('schema_version')) is not int or m['schema_version'] != 1
                or m.get('kind') != 'static_flood_hazard'):
            raise EvidenceError('incompatible_generation')
        flood_evidence.identifier(m.get('generation'))
        if (m.get('complete') is not True or m['generation'] != self.directory.name
                or self.manifest_path != dataset_paths.checked_path(
                    self.root, 'static/' + m['generation'] + '/manifest.json')):
            raise EvidenceError('incomplete_or_incompatible_generation')
        if (not isinstance(m.get('files'), dict)
                or not 1 <= len(m['files']) <= flood_reference_data.MAX_FILES):
            raise EvidenceError('invalid_artifact_inventory')
        self.products = m.get('products')
        if not isinstance(self.products, list) or len(self.products) > MAX_PRODUCTS:
            raise EvidenceError('product_inventory_limit_or_invalid')
        for product in self.products:
            self.validate_product(product)

    def validate_product(self, product):
        """Validate selection metadata; source strings and classifications remain literal."""
        if not isinstance(product, dict):
            raise EvidenceError('invalid_product_metadata')
        for key in ('source', 'product', 'version'):
            flood_evidence.identifier(product[key])
        if product.get('generation') != self.manifest['generation']:
            raise EvidenceError('incompatible_product_generation')
        if product.get('publication_status') not in PUBLICATION_STATES:
            raise EvidenceError('unsupported_publication_status')
        for key in ('regions', 'qualifications'):
            if not isinstance(product.get(key), list) or len(product[key]) > 32:
                raise EvidenceError('invalid_product_metadata')
            for value in product[key]:
                if key == 'regions':
                    flood_evidence.identifier(value)
                elif not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > 8192:
                    raise EvidenceError('source_qualification_limit_or_invalid')
        flood_evidence.identifier(product.get('review_reference'))
        evidence = product.get('evidence_files')
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
            raise EvidenceError('source_evidence_missing')
        for path in evidence:
            dataset_paths.checked_path(self.directory, path)
        zones = product['zones']
        if not isinstance(zones, dict):
            raise EvidenceError('invalid_zone_metadata')
        if type(zones.get('complete')) is not bool:
            raise EvidenceError('zone_completeness_missing')
        self.validate_count(zones)
        flood_evidence.identifier(zones['id_field'])
        dataset_paths.checked_path(self.directory, zones['path'])
        if not isinstance(zones.get('fields'), dict) or set(zones['fields']) - set(FIELDS + MEASUREMENT_FIELDS):
            raise EvidenceError('unsupported_field_mapping')
        for field in zones['fields'].values():
            flood_evidence.identifier(field)
        missing = zones.get('missing_values', {})
        if not isinstance(missing, dict) or set(missing) - set(zones['fields']):
            raise EvidenceError('unsupported_missing_value_mapping')
        for values in missing.values():
            if (not isinstance(values, list) or len(values) > 16
                    or any(type(value) not in (str, int, float, type(None)) for value in values)):
                raise EvidenceError('invalid_source_missing_values')
        coverage = product['coverage']
        if not isinstance(coverage, dict):
            raise EvidenceError('invalid_coverage_metadata')
        if type(coverage.get('complete')) is not bool:
            raise EvidenceError('coverage_completeness_unknown')
        if coverage.get('path') is not None:
            self.validate_count(coverage)
            dataset_paths.checked_path(self.directory, coverage['path'])
            for key in ('id_field', 'state_field', 'reference'):
                flood_evidence.identifier(coverage[key])
        elif coverage['complete']:
            raise EvidenceError('coverage_evidence_missing')

    def validate_count(self, descriptor):
        """Require an admitted feature inventory; complete files can still be truncated exports."""
        count = descriptor.get('record_count')
        if type(count) is not int or count < 0:
            raise EvidenceError('feature_inventory_missing')
        if count > MAX_FEATURES:
            raise EvidenceError('feature_limit')

    def source_evidence(self, product):
        """Verify declared review/source artifacts without asserting hydraulic validity."""
        for path in product['evidence_files']:
            self.artifact(path)

    def document(self, path):
        """Read each geometry file once, sharing decompression and total read budgets."""
        if path not in self.cache:
            raw = self.artifact(path)
            limit = min(MAX_DOCUMENT_BYTES, self.expanded_remaining)
            if path.endswith('.gz'):
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                    raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise EvidenceError('geometry_expansion_limit')
            self.expanded_remaining -= len(raw)
            document = strict_json(raw)
            if (not isinstance(document, dict) or document.get('type') != 'FeatureCollection'
                    or not isinstance(document.get('features'), list)):
                raise EvidenceError('invalid_feature_collection')
            if document.get('crs') not in (None,
                    {'type': 'name', 'properties': {'name': 'EPSG:4326'}},
                    {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'}}):
                raise EvidenceError('geometry_crs_unsupported')
            if len(document['features']) > MAX_FEATURES:
                raise EvidenceError('feature_limit')
            self.cache[path] = document
        self.tick()
        return self.cache[path]

    def finish(self):
        """Reject registry, active pointer and consumed-file changes before returning."""
        self.tick()
        try:
            current = resolve(self.config)
        except (OSError, ValueError):
            raise EvidenceError('generation_changed') from None
        try:
            if (current != self.root
                    or self.read(self.root / 'static.json', MAX_DOCUMENT_BYTES) != self.pointer_bytes):
                raise EvidenceError('generation_changed')
            for path, signature in self.signatures.items():
                self.tick()
                stat = path.stat()
                if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != signature:
                    raise EvidenceError('generation_changed')
        except OSError:
            raise EvidenceError('generation_changed') from None
