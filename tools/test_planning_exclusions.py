"""Keep local planning notes private without weakening maintained link checks."""
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_documentation as docs
import build_installers as service
import build_data_installers as datasets


class PlanningExclusionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git('init', '--quiet')
        for name in ('.gitignore', '.gitattributes'):
            shutil.copy2(docs.ROOT / name, self.root / name)
        self.note = self.root / 'docs/superpowers/plans/local.md'
        self.note.parent.mkdir(parents=True)
        self.note.write_text('[Missing](../../absent.md)\n')
        self.guide = self.root / 'docs/guide.md'
        self.guide.write_text('# Guide\n[Guide](guide.md#guide)\n')
        for platform in ('windows', 'linux'):
            (self.root / 'installers/datasets' / platform).mkdir(parents=True)
        (self.root / 'installers/desktop').mkdir()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.PIPE)

    def test_local_notes_are_ignored_but_broken_published_links_still_fail(self):
        with patch.object(docs, 'ROOT', self.root):
            paths = docs.maintained_paths()
            self.assertIn(self.guide, paths)
            self.assertNotIn(self.note, paths)
            docs.check_links(paths)
            self.guide.write_text('[Missing](missing.md)\n')
            with self.assertRaisesRegex(ValueError, 'Missing link:'):
                docs.check_links(docs.maintained_paths())
        self.assertTrue(self.note.is_file())

    def test_forced_tracking_is_rejected_and_export_still_excludes_notes(self):
        self.git('add', '-f', 'docs/superpowers/plans/local.md')
        self.git('add', '.gitattributes', 'docs/guide.md')
        with patch.object(docs, 'ROOT', self.root):
            with self.assertRaisesRegex(ValueError, 'Tracked files violate ignore policy'):
                docs.check_publication()
        tree = self.git('write-tree').decode().strip()
        with tarfile.open(fileobj=io.BytesIO(self.git('archive', '--format=tar', tree))) as archive:
            self.assertIn('docs/guide.md', archive.getnames())
            self.assertFalse(any('superpowers' in name for name in archive.getnames()))

    def test_both_installer_collectors_exclude_local_notes(self):
        with patch.object(service, 'ROOT', self.root), patch.object(service, 'PACKAGES', ()):
            sources = service.source_files()
        self.assertIn(self.guide, sources)
        self.assertNotIn(self.note, sources)
        sources = datasets.source_inventory(self.root)
        self.assertIn('docs/guide.md', sources)
        self.assertNotIn('docs/superpowers/plans/local.md', sources)


if __name__ == '__main__':
    unittest.main()
