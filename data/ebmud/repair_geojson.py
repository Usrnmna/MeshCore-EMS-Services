"""Repair invalid local polygons while preserving source bytes and feature attributes."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import shapely
from shapely.geometry import mapping, shape
from shapely.validation import explain_validity

from refresh_geojson import DATA_DIRECTORY, install_files


def repair(directory=DATA_DIRECTORY):
    """Repair invalid polygons with GEOS make_valid; abort on non-polygon results.

    Original affected files are retained under originals/ by their SHA-256.
    Counts, properties, feature IDs, valid geometries, and nulls are preserved.
    A repair establishes geometric validity, not surveyed boundary accuracy.
    """
    directory = Path(directory).resolve()
    lock = directory / '.refresh.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write('Polygon repair in progress\n')
    try:
        if any(directory.glob('.refresh-*')):
            raise ValueError('Pending recovery directory requires review before repair')
        manifest = json.loads((directory / 'sources.json').read_bytes())
        files = {}
        originals = {}
        repaired_count = 0
        for name, entry in manifest['datasets'].items():
            path = (directory / entry['path']).resolve()
            if not path.is_relative_to(directory):
                raise ValueError('Dataset path must remain inside the data directory')
            raw = path.read_bytes()
            checksum = hashlib.sha256(raw).hexdigest()
            if checksum != entry['sha256'] or len(raw) != entry['byte_count']:
                raise ValueError(f'Checksum or size mismatch: {name}')
            document = json.loads(raw)
            repairs = []
            for feature in document['features']:
                if feature['geometry'] is None:
                    continue
                geometry = shape(feature['geometry'])
                if geometry.is_valid:
                    continue
                if geometry.geom_type not in {'Polygon', 'MultiPolygon'}:
                    raise ValueError(f'Invalid non-polygon geometry in {name}')
                fixed = shapely.make_valid(geometry)
                if (not fixed.is_valid or fixed.is_empty or
                        fixed.geom_type not in {'Polygon', 'MultiPolygon'}):
                    raise ValueError(f'Repair requires manual review: {name}, ID {feature.get("id")}')
                repairs.append({'feature_id': feature.get('id'),
                                'reason': explain_validity(geometry),
                                'before_type': geometry.geom_type, 'after_type': fixed.geom_type})
                feature['geometry'] = mapping(fixed)
            if not repairs:
                continue
            backup = f'originals/{checksum}.geojson'
            originals[backup] = raw
            saved = (json.dumps(document, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
            files[entry['path']] = saved
            entry.update(byte_count=len(saved), sha256=hashlib.sha256(saved).hexdigest(),
                         geometry_types=sorted({feature['geometry']['type'] for feature in document['features']
                                                if feature['geometry'] is not None}))
            entry['geometry_repair'] = {
                'processed_at_utc': datetime.now(timezone.utc).isoformat(),
                'method': 'shapely.make_valid (default linework)',
                'shapely_version': shapely.__version__, 'geos_version': shapely.geos_version_string,
                'original_path': backup, 'original_sha256': checksum,
                'original_byte_count': len(raw), 'features': repairs,
            }
            repaired_count += len(repairs)
            print(f'{name}: {len(repairs)} polygon repairs', flush=True)
        if not files:
            print('All geometries are already valid; no changes made.')
            return
        # Preserve source bytes before any snapshot replacement.
        for relative, raw in originals.items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.read_bytes() != raw:
                    raise ValueError('Existing original backup has unexpected contents')
            else:
                with path.open('xb') as stream:
                    stream.write(raw)
        manifest['description'] = 'EBMUD local GIS snapshots; geometry repairs, if present, are recorded per dataset.'
        files['sources.json'] = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
        install_files(directory, files)
        print(f'Repaired {repaired_count} polygons; original files preserved.')
    finally:
        lock.unlink()


if __name__ == '__main__':
    try:
        repair()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Polygon repair failed: {error}', file=sys.stderr)
        sys.exit(1)
