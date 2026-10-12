"""Manually refresh the EBMUD snapshots; importing this module performs no I/O."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from uuid import uuid4
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import urlopen


# Adjustable settings. Dataset URLs and relative filenames belong in sources.json.
DATA_DIRECTORY = Path(__file__).resolve().parent
REQUEST_TIMEOUT_SECONDS = 60
REQUEST_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2
MAX_RESPONSE_BYTES = 100 * 1024 * 1024


def read_json(raw):
    """Decode JSON and reject ArcGIS errors, including errors sent with HTTP 200."""
    document = json.loads(raw)
    if not isinstance(document, dict) or 'error' in document:
        raise ValueError(f'Invalid response or ArcGIS error: {str(document)[:400]}')
    return document


def fetch(url):
    """Download bounded response bytes with retries for network failures only."""
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            with urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError('Response exceeds MAX_RESPONSE_BYTES')
            return raw
        except (URLError, TimeoutError, ConnectionError):
            if attempt + 1 == REQUEST_ATTEMPTS:
                raise
            time.sleep(RETRY_DELAY_SECONDS)


def query_url(source_url, **parameters):
    """Build independent verification queries against the configured layer."""
    parts = urlsplit(source_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(parameters), ''))


def validate_source(source_url):
    """Require a complete WGS 84 GeoJSON query rather than a filtered snapshot."""
    parts = urlsplit(source_url)
    parameters = dict(parse_qsl(parts.query))
    required = {'where': '1=1', 'outFields': '*', 'returnGeometry': 'true',
                'outSR': '4326', 'f': 'geojson'}
    if (parts.scheme != 'https' or not parts.netloc or
            not re.search(r'/MapServer/\d+/query$', parts.path) or
            parameters != required):
        raise ValueError(f'Source must be an unfiltered HTTPS GeoJSON query: {source_url}')


def feature_ids(source_url):
    """Obtain the full object-ID set independently of feature response limits."""
    document = read_json(fetch(query_url(
        source_url, where='1=1', returnIdsOnly='true', f='json')))
    ids = document.get('objectIds')
    if not isinstance(ids, list) or any(type(value) is not int for value in ids):
        raise ValueError('Missing or invalid objectIds response')
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate IDs in objectIds response')
    return set(ids)


def download_dataset(entry):
    """Preserve raw bytes only when count and exact ID coverage prove completeness.

    ID checks before and after downloading detect membership changes. They do
    not provide a transactionally consistent snapshot of remote attribute edits.
    Null geometry is valid and remains unchanged.
    """
    source = entry['source_url']
    validate_source(source)
    expected_ids = feature_ids(source)
    raw = fetch(source)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    document = read_json(raw)
    features = document.get('features')
    if document.get('type') != 'FeatureCollection' or not isinstance(features, list):
        raise ValueError('Response is not a GeoJSON FeatureCollection')
    if (document.get('exceededTransferLimit') or
            (document.get('properties') or {}).get('exceededTransferLimit')):
        raise ValueError('Truncated response; local snapshot was not replaced')
    actual_ids = []
    geometry_types = set()
    null_count = 0
    for feature in features:
        if (feature.get('type') != 'Feature' or
                not isinstance(feature.get('properties'), dict) or
                type(feature.get('id')) is not int or 'geometry' not in feature):
            raise ValueError('Invalid feature, properties, geometry, or object ID')
        actual_ids.append(feature['id'])
        geometry = feature['geometry']
        if geometry is None:
            null_count += 1
        elif (isinstance(geometry, dict) and geometry.get('type') in
              {'Point', 'MultiPoint', 'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon'}
              and isinstance(geometry.get('coordinates'), list)):
            geometry_types.add(geometry['type'])
        else:
            raise ValueError('Unsupported or malformed GeoJSON geometry')
    count = read_json(fetch(query_url(
        source, where='1=1', returnCountOnly='true', f='json'))).get('count')
    if (type(count) is not int or count != len(features) or
            len(actual_ids) != len(set(actual_ids)) or
            set(actual_ids) != expected_ids or feature_ids(source) != expected_ids):
        raise ValueError('Incomplete download, duplicate IDs, or changing source membership')
    updated = dict(entry)
    # A new raw response replaces any previously repaired local geometry.
    updated.pop('geometry_repair', None)
    updated.update(retrieved_at_utc=retrieved_at, feature_count=len(features),
                   byte_count=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                   geometry_types=sorted(geometry_types), null_geometry_count=null_count)
    return raw, updated


def update_readme(text, datasets):
    """Update the count at the start of each existing dataset table row."""
    for entry in datasets.values():
        pattern = (r'(?m)^(\| \[[^\]\n]+\]\(' + re.escape(entry['path']) +
                   r'\) \| )\d+( )')
        text, matches = re.subn(pattern, lambda match:
                               match[1] + str(entry['feature_count']) + match[2], text)
        if matches != 1:
            raise ValueError(f'Expected one README count row for {entry["path"]}')
    return text


def install_files(directory, files):
    """Stage every file, then replace files individually with exception rollback.

    A process or power interruption can leave a mixed generation. The retained
    .refresh-* directory contains the previous files for manual recovery.
    """
    # Inherit the data directory's permissions, including Windows ACLs.
    staging = directory / ('.refresh-' + uuid4().hex)
    staging.mkdir()
    replaced = []
    try:
        for relative_path, raw in files.items():
            target = directory / relative_path
            backup = staging / 'previous' / relative_path
            pending = staging / 'pending' / relative_path
            backup.parent.mkdir(parents=True, exist_ok=True)
            pending.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            pending.write_bytes(raw)
        try:
            for relative_path in files:
                os.replace(staging / 'pending' / relative_path, directory / relative_path)
                replaced.append(relative_path)
        except BaseException:
            for relative_path in reversed(replaced):
                os.replace(staging / 'previous' / relative_path, directory / relative_path)
            raise
    except BaseException:
        print(f'Refresh failed. Recovery files retained at: {staging}', file=sys.stderr)
        raise
    else:
        shutil.rmtree(staging)


def refresh(directory=DATA_DIRECTORY, check_only=False):
    """Validate all configured datasets before updating snapshots and metadata.

    An exclusive lock prevents overlapping runs. Existing service_resources
    metadata remains unchanged because this utility refreshes GeoJSON only.
    """
    directory = Path(directory).resolve()
    lock = directory / '.refresh.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(f'PID {os.getpid()}\n')
    try:
        manifest_raw = (directory / 'sources.json').read_bytes()
        readme_raw = (directory / 'README.md').read_bytes()
        manifest = read_json(manifest_raw)
        datasets = manifest['datasets']
        if not isinstance(datasets, dict) or not datasets:
            raise ValueError('Manifest has no datasets')
        paths = set()
        for entry in datasets.values():
            path = Path(entry['path'])
            target = (directory / path).resolve()
            if (path.is_absolute() or not target.is_relative_to(directory) or
                    target.suffix != '.geojson' or target in paths or not target.is_file()):
                raise ValueError(f'Invalid, duplicate, or missing dataset path: {path}')
            paths.add(target)
            validate_source(entry['source_url'])
        # Reject missing README rows before making network requests.
        update_readme(readme_raw.decode('utf-8'), datasets)
        files = {}
        for name, entry in datasets.items():
            print(f'Downloading {name} ...', flush=True)
            raw, updated = download_dataset(entry)
            manifest['datasets'][name] = updated
            files[entry['path']] = raw
            print(f'  Verified {updated["feature_count"]} features', flush=True)
        files['README.md'] = update_readme(
            readme_raw.decode('utf-8'), manifest['datasets']).encode('utf-8')
        files['sources.json'] = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
        if check_only:
            print('Check complete; snapshots, manifest, and README were not changed.')
            return
        if ((directory / 'sources.json').read_bytes() != manifest_raw or
                (directory / 'README.md').read_bytes() != readme_raw):
            raise ValueError('Manifest or README changed during download; retry after editing')
        install_files(directory, files)
        print(f'Refreshed {len(datasets)} datasets, sources.json, and README counts.')
    finally:
        lock.unlink()


def main():
    """Expose manual refresh and download-only verification from any working directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='Download and verify without replacing local reference files')
    args = parser.parse_args()
    try:
        refresh(check_only=args.check)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Refresh failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
