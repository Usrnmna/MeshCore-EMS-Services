"""Bounded local evidence for environmental input assessment; never acquire or activate.

An optional flood_readiness/readiness.json pins readiness/GEN/manifest.json.
Schema 1, kind environmental_input_readiness, declares files and profile headers
(id, scope, intended_use, path). Profile JSON contains requirements, inputs and
review artifacts. Reviews bind exact subjects to a recorded justification.
External inputs declare dataset, pointer, pointer fingerprint, generation and
artifact fingerprints. These are reviewed dependencies, not inferred associations.
No admission tool or source conversion is provided by this runtime contract.
"""
import gzip
import hashlib
import io
import json
import time

from . import dataset_paths, flood_evidence, flood_hazard_data, water_settings
from . import reference_policy
from .flood_reference_data import Snapshot as BoundedReader, EvidenceError

MAX_FILES = 128
MAX_DOCUMENT = 2 * 1024 * 1024
MAX_BYTES = 64 * 1024 * 1024
MAX_EXPANDED = 8 * 1024 * 1024
MAX_PROFILES = 32
MAX_RECORDS = 128
SECONDS = 4
SOURCE_POINTERS = {
    'basin_plans': ('sources.json',),
    'usgs_water': ('inventory.json', 'observations.json', 'network.json', 'routing.json'),
    'flood_impacts': ('static.json',),
    'flood_hazards': ('static.json',),
    'flood_readiness': ('readiness.json',),
}


def scope(value):
    """Validate a complete literal scope; CalWater levels remain reporting identities."""
    if not isinstance(value, dict) or value.get('kind') not in ('basin', 'model_domain'):
        raise ValueError('Exact basin or model_domain scope required')
    keys = {'kind', 'source', 'id', 'generation'}
    if value['kind'] == 'basin':
        keys.add('level')
    if set(value) != keys:
        raise ValueError('Incomplete or unsupported scope identity')
    for item in value.values():
        flood_evidence.identifier(item)
    if value['kind'] == 'basin' and value['level'] not in flood_evidence.LEVELS:
        raise ValueError('Recorded CalWater hierarchy level required')
    return dict(value)


def bounded_list(value, maximum=MAX_RECORDS):
    """Reject malformed or oversized inventories before processing their entries."""
    if not isinstance(value, list) or len(value) > maximum:
        raise EvidenceError('record_limit_or_invalid')
    return value


def review_digest(record):
    """Bind a review to the exact recorded requirements, facts and dependency pins."""
    raw = json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


class Snapshot(BoundedReader):
    """Share bytes, time, expansion and file pins across all evidence consumed."""

    def __init__(self, config):
        self.config = dict(config)
        self.until = time.monotonic() + SECONDS
        self.remaining = MAX_BYTES
        self.expanded_remaining = MAX_EXPANDED
        self.signatures = {}
        self.absent = set()
        self.resolutions = {}
        self.verified = set()
        self.documents = {}
        self.dependencies = {}
        self.dependency_metadata = {}

    def registry_reader(self, path):
        """Read the registry within this transaction; custom roots never call this."""
        if not self.exists(path):
            return None
        registry = flood_hazard_data.strict_json(self.read(path, MAX_DOCUMENT))
        if not isinstance(registry, dict):
            raise EvidenceError('invalid_dataset_registry')
        return registry

    def exists(self, path):
        """Remember absence; an appearing source invalidates an assessment as well."""
        self.tick()
        if not path.exists():
            self.absent.add(path)
            return False
        return True

    def read(self, path, limit):
        """Extend the shared bounded reader with a distinct-file cap."""
        if not self.exists(path):
            raise EvidenceError('artifact_missing')
        if path not in self.signatures and len(self.signatures) >= MAX_FILES:
            raise EvidenceError('file_limit')
        return super().read(path, limit)

    def resolve(self, dataset):
        """Reuse managed removal and custom water roots, including the landslide bundle."""
        flood_evidence.identifier(dataset)
        if not dataset.replace('_', '').isalnum():
            raise EvidenceError('invalid_dataset_identity')
        if dataset in self.resolutions:
            return self.resolutions[dataset]
        configured = water_settings.data_root(self.config) / dataset
        defaults = (water_settings.ROOT / '../data' / dataset,)
        if dataset == 'landslide' and configured.resolve() == defaults[0].resolve():
            selected = dataset_paths.resolve(dataset, water_settings.ROOT / 'data/landslide',
                                             registry_reader=self.registry_reader)
        else:
            selected = dataset_paths.resolve(dataset, configured, configured=configured, defaults=defaults,
                                             registry_reader=self.registry_reader)
        self.resolutions[dataset] = selected
        return selected

    def document(self, path, expected=None):
        """Decode bounded JSON/gzip once; fingerprints are checked on every use."""
        raw = self.checked(path, expected, metadata=True) if expected is not None else self.read(path, MAX_DOCUMENT)
        if path in self.documents:
            return self.documents[path]
        limit = min(MAX_DOCUMENT, self.expanded_remaining)
        if path.suffix == '.gz':
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise EvidenceError('expansion_limit')
        self.expanded_remaining -= len(raw)
        value = flood_hazard_data.strict_json(raw)
        # Bound traversal work and source strings independently of encoded bytes.
        stack, count = [(value, 0)], 0
        while stack:
            node, depth = stack.pop()
            count += 1
            if depth > 24 or count > 20000:
                raise EvidenceError('metadata_complexity_limit')
            if isinstance(node, dict):
                stack.extend((v, depth + 1) for v in node.values())
            elif isinstance(node, list):
                stack.extend((v, depth + 1) for v in node)
            if count % 256 == 0:
                self.tick()
        self.documents[path] = value
        return value

    def checked(self, path, expected, metadata=False):
        """Pin missing dependencies too, so installation during assessment is detected."""
        if not self.exists(path):
            raise EvidenceError('artifact_missing')
        return super().checked(path, expected, metadata)

    def open_profiles(self):
        """Read the optional reviewed profile inventory without changing its membership."""
        self.root = self.resolve('flood_readiness')
        pointer_path = self.root / 'readiness.json'
        if not self.exists(pointer_path):
            raise EvidenceError('not_installed')
        pointer = self.document(pointer_path)
        if not isinstance(pointer, dict):
            raise EvidenceError('invalid_generation_pointer')
        manifest_path = dataset_paths.checked_path(self.root, pointer['manifest_path'])
        self.manifest = self.document(manifest_path, pointer)
        m = self.manifest
        if not isinstance(m, dict):
            raise EvidenceError('invalid_generation_manifest')
        if (type(m.get('schema_version')) is not int or m['schema_version'] != 1
                or m.get('kind') != 'environmental_input_readiness' or m.get('complete') is not True):
            raise EvidenceError('incompatible_generation')
        flood_evidence.identifier(m['generation'])
        if manifest_path != dataset_paths.checked_path(self.root, 'readiness/' + m['generation'] + '/manifest.json'):
            raise EvidenceError('incompatible_generation')
        self.directory = manifest_path.parent
        if not isinstance(m.get('files'), dict) or not 1 <= len(m['files']) <= MAX_FILES:
            raise EvidenceError('artifact_inventory_limit_or_invalid')
        self.profiles = bounded_list(m.get('profiles'), MAX_PROFILES)
        for header in self.profiles:
            if not isinstance(header, dict):
                raise EvidenceError('invalid_profile_header')
            flood_evidence.identifier(header['id'])
            flood_evidence.identifier(header['intended_use'])
            scope(header['scope'])
            dataset_paths.checked_path(self.directory, header['path'])

    def artifact_document(self, relative):
        """Read only a manifest-declared, checksummed review or profile artifact."""
        if relative not in self.manifest['files']:
            raise EvidenceError('artifact_not_declared')
        value = self.document(dataset_paths.checked_path(self.directory, relative), self.manifest['files'][relative])
        self.verified.add(relative)
        return value

    def review(self, path, subject, reviewed_record=None):
        """Require exact evidence association and justification; strings alone are not review."""
        if not path:
            return False
        record = self.artifact_document(path)
        return (isinstance(record, dict) and record.get('subject') == subject
                and record.get('status') == 'reviewed'
                and (reviewed_record is None or record.get('record_sha256') == review_digest(reviewed_record))
                and isinstance(record.get('justification'), str) and bool(record['justification'].strip()))

    def dependency(self, entry):
        """Verify reviewed external bytes and their current generation pointer atomically.

        Fingerprints come from the immutable readiness profile. A dependency
        generation must also occur in its pinned source manifest. This checks
        integrity and association only; it does not validate numerical suitability.
        """
        if not isinstance(entry, dict):
            raise EvidenceError('invalid_dependency')
        reference_policy.reject_metadata(entry)
        # Known collections use their existing active pointers. New input
        # collections use current.json; archived receipts cannot impersonate it.
        if entry.get('pointer') not in SOURCE_POINTERS.get(entry.get('dataset'), ('current.json',)):
            raise EvidenceError('unsupported_dependency_pointer')
        root = self.resolve(entry['dataset'])
        pointer_path = dataset_paths.checked_path(root, entry['pointer'])
        pointer = self.document(pointer_path, entry['pin'])
        if not isinstance(pointer, dict):
            raise EvidenceError('invalid_dependency_pointer')
        reference_policy.reject_metadata(pointer)
        manifest_path = dataset_paths.checked_path(root, pointer['manifest_path'])
        if not self.exists(manifest_path):
            raise EvidenceError('artifact_missing')
        expected = dict(sha256=pointer.get('sha256', pointer.get('manifest_sha256')),
                        byte_count=pointer.get('byte_count', manifest_path.stat().st_size))
        manifest = self.document(manifest_path, expected)
        if not isinstance(manifest, dict):
            raise EvidenceError('invalid_dependency_manifest')
        reference_policy.reject_metadata(manifest)
        if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
            raise EvidenceError('incompatible_dependency_schema')
        if 'files' in manifest and not isinstance(manifest['files'], dict):
            raise EvidenceError('invalid_dependency_inventory')
        generation = manifest.get('generation', manifest.get('snapshot_id'))
        flood_evidence.identifier(entry['generation'])
        if generation != entry['generation'] or manifest.get('complete') is not True:
            raise EvidenceError('incompatible_dependency_generation')
        key = (entry['dataset'], entry['pointer'])
        if key in self.dependencies and self.dependencies[key] != entry['pin']:
            raise EvidenceError('conflicting_dependency_pins')
        self.dependencies[key] = entry['pin']
        self.dependency_metadata[key] = {field: manifest.get(field) for field in ('kind', 'retention')}
        files = bounded_list(entry.get('artifacts'), 16)
        if not files:
            raise EvidenceError('input_artifact_missing')
        numerical_artifacts = 0
        for artifact in files:
            if not isinstance(artifact, dict):
                raise EvidenceError('invalid_dependency_artifact')
            reference_policy.reject_metadata(artifact)
            path = dataset_paths.checked_path(root, artifact['path'])
            reference_policy.reject_path(path)
            if path != manifest_path:
                if type(artifact.get('byte_count')) is not int or artifact['byte_count'] <= 0:
                    raise EvidenceError('input_artifact_missing')
                numerical_artifacts += 1
                if not path.is_relative_to(manifest_path.parent):
                    raise EvidenceError('incompatible_artifact_generation')
                recorded = manifest.get('files', {}).get(path.relative_to(manifest_path.parent).as_posix())
                if isinstance(recorded, dict):
                    reference_policy.reject_metadata(recorded)
                if (not isinstance(recorded, dict) or recorded.get('sha256') != artifact.get('sha256')
                        or recorded.get('byte_count', recorded.get('bytes')) != artifact.get('byte_count')):
                    raise EvidenceError('incompatible_artifact_inventory')
            self.checked(path, artifact)
            self.verified.add(entry['dataset'] + ':' + artifact['path'])
        return numerical_artifacts

    def finish(self):
        """Reject changed roots, consumed files, registry, and previously absent pointers."""
        self.tick()
        if any(path.exists() for path in self.absent):
            raise EvidenceError('generation_changed')
        previous = dict(self.resolutions)
        self.resolutions.clear()
        try:
            for dataset, root in previous.items():
                if self.resolve(dataset) != root:
                    raise EvidenceError('generation_changed')
            for path, signature in self.signatures.items():
                self.tick()
                stat = path.stat()
                if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != signature:
                    raise EvidenceError('generation_changed')
        except EvidenceError:
            raise
        except (OSError, ValueError):
            raise EvidenceError('generation_changed') from None
