"""Offline checks for completeness and preservation of existing snapshots."""

import json
from contextlib import contextmanager
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

import refresh_geojson as refresh


SOURCE = ('https://example.org/MapServer/0/query?where=1%3D1&outFields=*'
          '&returnGeometry=true&outSR=4326&f=geojson')


@contextmanager
def temporary_directory():
    """Isolate file tests under the workspace with inherited directory permissions."""
    folder = Path(__file__).resolve().parent / ('.test-refresh-' + uuid4().hex)
    folder.mkdir()
    try:
        yield folder
    finally:
        shutil.rmtree(folder)


def response(ids=(1, 2), truncated=False):
    """Construct a source response containing a valid null-geometry record."""
    document = {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'id': value, 'properties': {'name': 'Example'},
         'geometry': None} for value in ids]}
    if truncated:
        document['exceededTransferLimit'] = True
    return json.dumps(document).encode()


class RefreshTests(unittest.TestCase):
    def download(self, raw, final_ids=(1, 2), count=2):
        """Exercise the download contract with independent count and ID responses."""
        replies = [b'{"objectIds":[1,2]}', raw,
                   json.dumps({'count': count}).encode(),
                   json.dumps({'objectIds': final_ids}).encode()]
        with patch.object(refresh, 'fetch', side_effect=replies):
            return refresh.download_dataset({'source_url': SOURCE, 'path': 'a.geojson'})

    def test_preserves_raw_bytes_and_null_geometry(self):
        raw = response()
        saved, metadata = self.download(raw)
        self.assertEqual(saved, raw)
        self.assertEqual(metadata['null_geometry_count'], 2)

    def test_rejects_incomplete_duplicate_and_changing_ids(self):
        for raw, final_ids, count in [
            (response((1,)), (1, 2), 2),
            (response((1, 1)), (1, 2), 2),
            (response(), (1, 3), 2),
            (response(truncated=True), (1, 2), 2),
            (b'{"error":{"code":500}}', (1, 2), 2),
        ]:
            with self.subTest(raw=raw, final_ids=final_ids):
                with self.assertRaises(ValueError):
                    self.download(raw, final_ids, count)

    def test_readme_requires_unique_rows(self):
        datasets = {'a': {'path': 'a.geojson', 'feature_count': 7}}
        row = '| [a](a.geojson) | 2 features |\n'
        self.assertIn('| 7 features', refresh.update_readme(row, datasets))
        for text in ['', row + row]:
            with self.assertRaises(ValueError):
                refresh.update_readme(text, datasets)

    def test_install_failure_restores_previous_files(self):
        with temporary_directory() as temporary:
            folder = Path(temporary)
            for name in ['a.geojson', 'sources.json']:
                (folder / name).write_bytes(b'original')
            replace = refresh.os.replace
            calls = 0

            def fail_second_replace(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError('Simulated replacement failure')
                replace(source, target)

            with patch.object(refresh.os, 'replace', side_effect=fail_second_replace):
                with self.assertRaises(OSError):
                    refresh.install_files(folder, {'a.geojson': b'new', 'sources.json': b'new'})
            self.assertEqual((folder / 'a.geojson').read_bytes(), b'original')
            self.assertEqual((folder / 'sources.json').read_bytes(), b'original')

    def test_check_failure_and_success_at_refresh_boundary(self):
        with temporary_directory() as temporary:
            folder = Path(temporary)
            datasets = {name: {'path': name + '.geojson', 'source_url': SOURCE,
                               'feature_count': 1} for name in ['a', 'b']}
            (folder / 'sources.json').write_text(json.dumps({'datasets': datasets}))
            (folder / 'README.md').write_text(
                '| [a](a.geojson) | 1 features |\n| [b](b.geojson) | 1 features |\n')
            for entry in datasets.values():
                (folder / entry['path']).write_bytes(b'old')
            before = {path.name: path.read_bytes() for path in folder.iterdir()}

            def successful_download(entry):
                return response(), dict(entry, feature_count=2)

            with patch.object(refresh, 'download_dataset', side_effect=successful_download):
                refresh.refresh(folder, check_only=True)
            self.assertEqual(before, {path.name: path.read_bytes() for path in folder.iterdir()})
            with patch.object(refresh, 'download_dataset', side_effect=[
                    successful_download(datasets['a']), ValueError('Incomplete second dataset')]):
                with self.assertRaises(ValueError):
                    refresh.refresh(folder)
            self.assertEqual(before, {path.name: path.read_bytes() for path in folder.iterdir()})
            with patch.object(refresh, 'download_dataset', side_effect=successful_download):
                refresh.refresh(folder)
            self.assertEqual((folder / 'a.geojson').read_bytes(), response())
            self.assertEqual((folder / 'README.md').read_text().count('| 2 features'), 2)
            self.assertEqual(json.loads((folder / 'sources.json').read_text())['datasets']['b']['feature_count'], 2)


if __name__ == '__main__':
    unittest.main()
