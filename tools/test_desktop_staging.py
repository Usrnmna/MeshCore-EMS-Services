"""Private staging boundaries with fixture-only secure-creation substitutes."""
from contextlib import nullcontext
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installers.desktop import staging


def fixture_staging(test_case, base):
    """Scope secure-creation substitutes to disposable test-owned storage only.

    These fixtures verify staging control flow, not native Windows owner/DACL
    creation. Production code has no bypass for its ownership boundary.
    """
    for replacement in (
            patch("installers.desktop.locking.maintenance_directory", return_value=Path(base)),
            patch.object(staging, "_protected_base", side_effect=lambda base: nullcontext()),
            patch.object(staging, "_create_private_directory", side_effect=lambda path: path.mkdir(mode=0o700)),
            patch.object(staging, "_open_private_file", side_effect=lambda path: os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))):
        replacement.start(); test_case.addCleanup(replacement.stop)


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        fixture_staging(self, self.base)

    def test_writer_requires_active_private_stage(self):
        with self.assertRaisesRegex(PermissionError, "active"):
            staging.write_private_file(self.base / "settings.json", content=b"{}")

    def test_created_content_is_exclusive_and_stage_is_cleaned(self):
        with staging.private_temporary_directory("fixture-") as directory:
            stage = Path(directory)
            file = stage / "settings.json"
            staging.write_private_file(file, content=b"private settings")
            self.assertEqual(file.read_bytes(), b"private settings")
            with self.assertRaises(FileExistsError):
                staging.write_private_file(file, content=b"replacement")
            self.assertEqual(file.read_bytes(), b"private settings")
        self.assertFalse(stage.exists())

    def test_outside_destination_and_parent_traversal_are_rejected(self):
        with staging.private_temporary_directory("fixture-") as directory:
            for path in (self.base / "outside.py", Path(directory) / ".." / "outside.py"):
                with self.subTest(path=path), self.assertRaises(PermissionError):
                    staging.write_private_file(path, content=b"pass\n")
        self.assertFalse((self.base / "outside.py").exists())

    def test_source_is_copied_into_new_private_file(self):
        source = self.base / "checked artifact.exe"; source.write_bytes(b"checked installer")
        with staging.private_temporary_directory("fixture-") as directory:
            destination = Path(directory) / source.name
            staging.write_private_file(destination, source=source)
            self.assertEqual(destination.read_bytes(), source.read_bytes())

    def test_alternate_streams_and_alias_components_are_rejected(self):
        with staging.private_temporary_directory("fixture-") as directory:
            for name in ("file:stream", "file.", "file "):
                with self.subTest(name=name), self.assertRaises(PermissionError):
                    staging.write_private_file(Path(directory) / name, content=b"x")

    def test_nested_stages_restore_outer_context(self):
        with staging.private_temporary_directory("outer-") as first:
            with staging.private_temporary_directory("inner-") as second:
                with self.assertRaises(PermissionError):
                    staging.write_private_file(Path(first) / "wrong-context", content=b"x")
                staging.write_private_file(Path(second) / "inside", content=b"x")
            staging.write_private_file(Path(first) / "restored", content=b"x")

    def test_exception_cleanup_preserves_unrelated_files(self):
        unrelated = self.base / "retained"; unrelated.write_bytes(b"retain")
        with self.assertRaisesRegex(RuntimeError, "failure"):
            with staging.private_temporary_directory("fixture-") as directory:
                staging.write_private_file(Path(directory) / "file", content=b"secret")
                raise RuntimeError("failure")
        self.assertEqual(unrelated.read_bytes(), b"retain")
        self.assertEqual(list(self.base.iterdir()), [unrelated])

    def test_invalid_prefix_cannot_select_arbitrary_directory(self):
        for prefix in ("../unsafe", "", "x" * 100, "C:\\unsafe"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                with staging.private_temporary_directory(prefix):
                    self.fail("unsafe prefix accepted")

    def test_exactly_one_content_source_is_required(self):
        with staging.private_temporary_directory("fixture-") as directory:
            for values in ({}, {"content": b"x", "source": self.base / "file"}, {"content": "text"}):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    staging.write_private_file(Path(directory) / "file", **values)


if __name__ == "__main__":
    unittest.main()
