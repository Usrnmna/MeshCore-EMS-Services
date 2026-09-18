"""Read-only comparison against the original folder snapshot made before porting."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'source_integrity.json').read_text())
source = Path(manifest['source'])
current = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
           for p in source.rglob('*') if p.is_file()}
changed = sorted(key for key in set(current) | set(manifest['files'])
                 if current.get(key) != manifest['files'].get(key))
readme_ok = hashlib.sha256((source.parent / 'README.md').read_bytes()).hexdigest() == manifest['root_readme_sha256']
if changed or not readme_ok:
    raise SystemExit(f'Original differs from snapshot: {changed}; root README unchanged={readme_ok}')
print(f'UNCHANGED: all {len(current)} original files, including config.json, and the root README.')
