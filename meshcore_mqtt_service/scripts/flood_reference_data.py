"""W10-A read-only generation evidence; no catalog queries or scenario selection."""
import gzip
import hashlib
import io
import json
import time

from . import basin_plan_data, dataset_paths, water_settings

MAX_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_FILES = 4096
VERIFY_SECONDS = 4


class EvidenceError(ValueError):
    """Carry a stable classification without exposing local paths in public summaries."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def resolve(config):
    """Use the existing installed registry and authoritative custom-root rules."""
    configured = water_settings.data_root(config) / 'flood_impacts'
    return dataset_paths.resolve('flood_impacts', configured, configured=configured,
                                 defaults=(water_settings.ROOT / '../data/flood_impacts',))


class Snapshot:
    """Pin one static pointer, verify consumed bytes, and reject changes before return.

    Integrity describes only explicitly checked artifacts. A manifest check alone
    never certifies its scenario files or validates hydraulic predictions.
    """

    def __init__(self, config):
        self.config = dict(config)
        self.until = time.monotonic() + VERIFY_SECONDS
        self.remaining = MAX_BYTES
        self.signatures = {}
        self.verified = set()
        self.root = resolve(config)
        self.pointer_bytes = self.read(self.root/'static.json', MAX_METADATA_BYTES)
        self.pointer = json.loads(self.pointer_bytes)
        if not isinstance(self.pointer, dict):
            raise EvidenceError('invalid_generation_pointer')
        self.manifest_path = dataset_paths.checked_path(self.root, self.pointer['manifest_path'])
        self.directory = self.manifest_path.parent
        self.manifest = json.loads(self.checked(self.manifest_path, self.pointer, metadata=True))
        m = self.manifest
        if not isinstance(m, dict):
            raise EvidenceError('invalid_generation_manifest')
        if (type(m.get('schema_version')) is not int or m['schema_version'] != 1
                or m.get('kind') != 'static' or m.get('complete') is not True):
            raise EvidenceError('incomplete_or_unsupported_generation')
        if (not isinstance(m.get('generation'), str) or not m['generation']
                or self.directory.name != m['generation']
                or not isinstance(m.get('files'), dict) or not 1 <= len(m['files']) <= MAX_FILES):
            raise EvidenceError('invalid_generation_manifest')
        self.compatibility = 'unknown'
        self.basin = None

    def tick(self):
        """Apply one verification deadline across pointer, metadata and artifact reads."""
        if time.monotonic() > self.until:
            raise EvidenceError('verification_limit')

    def read(self, path, limit):
        """Read bounded bytes and pin file identity across the read."""
        self.tick()
        before = path.stat()
        previous = self.signatures.get(path)
        if previous is not None and previous != (before.st_size, before.st_mtime_ns, before.st_ctime_ns):
            raise EvidenceError('generation_changed')
        if before.st_size > limit or before.st_size > self.remaining:
            raise EvidenceError('verification_limit')
        with path.open('rb') as stream:
            chunks = []
            size = 0
            while True:
                chunk = stream.read(min(65536, limit-size+1))
                self.tick()
                if not chunk:
                    break
                size += len(chunk)
                self.remaining -= len(chunk)
                if size > limit or self.remaining < 0:
                    raise EvidenceError('verification_limit')
                chunks.append(chunk)
        after = path.stat()
        signature = (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if signature != (before.st_size, before.st_mtime_ns, before.st_ctime_ns):
            raise EvidenceError('generation_changed')
        self.signatures[path] = signature
        return b''.join(chunks)

    def checked(self, path, expected, metadata=False):
        """Verify exact content; no generated report is accepted as proof of current integrity."""
        if (not isinstance(expected, dict) or type(expected.get('byte_count')) is not int
                or expected['byte_count'] < 0 or not isinstance(expected.get('sha256'), str)
                or len(expected['sha256']) != 64):
            raise EvidenceError('invalid_fingerprint')
        if not path.is_file():
            raise EvidenceError('artifact_missing')
        if path.stat().st_size != expected['byte_count']:
            raise EvidenceError('integrity_failed')
        raw = self.read(path, MAX_METADATA_BYTES if metadata else MAX_BYTES)
        if hashlib.sha256(raw).hexdigest() != expected['sha256']:
            raise EvidenceError('integrity_failed')
        return raw

    def artifact(self, relative):
        """Verify a named manifest artifact; callers cannot escape its generation root."""
        self.tick()
        if relative not in self.manifest['files']:
            raise EvidenceError('artifact_not_declared')
        path = dataset_paths.checked_path(self.directory, relative)
        raw = self.checked(path, self.manifest['files'][relative])
        self.verified.add(relative)
        return raw

    def metadata(self, relative):
        """Decode bounded source JSON without discovering or selecting site/scenario records."""
        raw = self.artifact(relative)
        if relative.endswith('.gz'):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(MAX_METADATA_BYTES+1)
        self.tick()
        if len(raw) > MAX_METADATA_BYTES:
            raise EvidenceError('metadata_expansion_limit')
        return json.loads(raw)

    def check_basins(self):
        """Reuse W09 source/organization checks and compare the exact recorded Basin Plan pin."""
        self.tick()
        owner = self
        configured = water_settings.data_root(self.config) / 'basin_plans'
        basin_root = dataset_paths.resolve('basin_plans', configured, configured=configured,
            defaults=(water_settings.ROOT / '../data/basin_plans',))
        pointer_bytes = self.read(basin_root/'sources.json', MAX_METADATA_BYTES)

        class PinnedBasins(basin_plan_data.Collection):
            """Share W10's total byte/deadline budget during W09 construction."""
            def read_pointer(self):
                """Bound every dependency pointer read, including the final pin check."""
                raw = owner.read(self.root/'sources.json', MAX_METADATA_BYTES)
                if not isinstance(json.loads(raw), dict):
                    raise EvidenceError('invalid_generation_pointer')
                return raw

            def checked(self, path, expected):
                evidence = dict(expected, byte_count=expected.get('byte_count', path.stat().st_size))
                # Basin Plan source manifests include substantial dataset metadata.
                # Retain their existing 64 MiB allowance within the shared budget.
                raw = owner.checked(path, evidence)
                if not isinstance(json.loads(raw), dict):
                    raise EvidenceError('invalid_generation_manifest')
                self.signatures[path] = owner.signatures[path]
                return raw

        self.basin = PinnedBasins(self.config)
        if self.basin.root != basin_root or self.basin.pointer_bytes != pointer_bytes:
            raise EvidenceError('generation_changed')
        self.basin.deadline = min(self.basin.deadline, self.until)
        self.tick()
        self.compatibility = ('compatible' if self.manifest.get('basin_source') == json.loads(self.basin.pointer_bytes)
                              else 'incompatible')
        self.check_basin_unchanged()
        return self.compatibility

    def check_basin_unchanged(self):
        """Classify a replaced dependency as a generation failure, not a usable pin."""
        try:
            self.basin.verify_unchanged()
        except EvidenceError:
            raise
        except (OSError, ValueError):
            raise EvidenceError('generation_changed') from None

    def verify_all(self):
        """Check the declared collection only; bounds leave verification explicitly partial."""
        for relative in self.manifest['files']:
            self.artifact(relative)
        self.finish()

    def finish(self):
        """Reject registry changes, pointer replacement and consumed-file changes."""
        self.tick()
        try:
            if resolve(self.config) != self.root:
                raise EvidenceError('generation_changed')
        except (OSError, ValueError):
            raise EvidenceError('generation_changed') from None
        try:
            if self.read(self.root/'static.json', MAX_METADATA_BYTES) != self.pointer_bytes:
                raise EvidenceError('generation_changed')
        except OSError:
            raise EvidenceError('generation_changed') from None
        for path, expected in self.signatures.items():
            self.tick()
            try:
                stat = path.stat()
            except OSError:
                raise EvidenceError('generation_changed') from None
            if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != expected:
                raise EvidenceError('generation_changed')
        if self.basin is not None:
            self.check_basin_unchanged()


def inspect(config=None):
    """Describe installed evidence and failed checks independently, without source acquisition.

    This internal helper performs collection-level verification only. It does not
    implement W10-B catalog discovery, station lookup, or scenario selection.
    """
    config = water_settings.load() if config is None else config
    result = dict(installation='unknown', integrity='unchecked', compatibility='unknown',
                  numerical_verification='not_assessed', predictive_validation='not_assessed',
                  acquisition='not_checked', generation=None, checked_files=0,
                  basin_installation='unknown', basin_integrity='unchecked',
                  basin_integrity_scope='source_and_organization_manifests', issues=[])
    snapshot = None
    try:
        root = resolve(config)
        if not (root/'static.json').is_file():
            result.update(installation='not_installed')
            result['issues'].append('static_pointer_missing')
            return result
        result['installation'] = 'installed'
        snapshot = Snapshot(config)
        result['generation'] = snapshot.manifest['generation']
        result['vintage'] = snapshot.manifest.get('created_at_utc')
        snapshot.verify_all()
        result['integrity'] = 'passed'
        try:
            result['compatibility'] = snapshot.check_basins()
            result['basin_integrity'] = 'passed'
            result['basin_installation'] = 'installed'
        except EvidenceError as exc:
            if exc.code in ('generation_changed', 'verification_limit'):
                raise
            result['basin_integrity'] = ('failed' if exc.code in
                ('integrity_failed', 'artifact_missing', 'invalid_fingerprint') else 'unchecked')
            result['issues'].append('basin_dependency:'+exc.code)
        except FileNotFoundError as exc:
            removed = str(exc).startswith('Dataset is not installed:')
            result['basin_installation'] = 'removed' if removed else 'unavailable'
            result['issues'].append('basin_dependency:managed_removal' if removed
                                    else 'basin_dependency_unavailable_or_invalid')
        except basin_plan_data.Unavailable as exc:
            if str(exc).startswith('Incompatible Basin Plan generations'):
                result['compatibility'] = 'incompatible'
            result['issues'].append('basin_dependency_unavailable_or_invalid')
        except (OSError, ValueError, KeyError, TypeError):
            result['issues'].append('basin_dependency_unavailable_or_invalid')
        snapshot.finish()
    except FileNotFoundError as exc:
        # Resolve distinguishes an explicit registry removal from a missing
        # active directory. Never substitute the bundled collection in either case.
        result['installation'] = 'removed' if str(exc).startswith('Dataset is not installed:') else 'unavailable'
        result['issues'].append('managed_removal' if result['installation'] == 'removed' else 'file_unavailable')
    except EvidenceError as exc:
        result['issues'].append(exc.code)
        if exc.code in ('integrity_failed', 'artifact_missing', 'invalid_fingerprint'):
            result['integrity'] = 'failed'
        elif exc.code in ('verification_limit', 'metadata_expansion_limit'):
            result['integrity'] = 'partial'
        elif exc.code == 'generation_changed':
            result.update(integrity='partial', compatibility='incompatible')
    except (OSError, ValueError, KeyError, TypeError):
        result['issues'].append('metadata_unavailable_or_invalid')
    if snapshot is not None:
        result['checked_files'] = len(snapshot.verified)
    if result['compatibility'] == 'incompatible':
        result['issues'].append('basin_generation_incompatible')
    return result
