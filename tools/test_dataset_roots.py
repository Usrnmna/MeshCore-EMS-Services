"""Protected native data-root boundaries; no installer or service is executed."""

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installers.datasets import manage
from installers.desktop import locking, windows_trust


class RootBoundaryTests(unittest.TestCase):
    def test_coordinated_mutation_cannot_reach_lock_or_acquisition_after_root_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "uncreated data"
            with patch.dict(os.environ, {locking.VARIABLE: "a" * 32}), \
                    patch.object(manage, "protected_data_root", side_effect=PermissionError("unsafe parent")), \
                    patch.object(manage, "_locked_record", side_effect=AssertionError("Created lock")):
                with self.assertRaisesRegex(PermissionError, "unsafe parent"):
                    manage.install(root, "ebmud", Path(temporary), acquire=lambda *args: self.fail("Acquired"), validate=lambda *args: None)
            self.assertFalse(root.exists())

    def test_filesystem_or_volume_root_is_rejected(self):
        root = Path.cwd().anchor
        with self.assertRaises(ValueError):
            with manage.protected_data_root(Path(root), create=True):
                self.fail("Accepted operating system root")

    @unittest.skipUnless(os.name == "nt", "Windows native directory trust")
    def test_windows_untrusted_custom_ancestor_is_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "uncreated data"
            with self.assertRaises(PermissionError):
                with windows_trust.protected_data_root(root, create=True):
                    self.fail("Accepted caller-controlled ancestors")
            self.assertFalse(root.exists())

    @unittest.skipUnless(os.name == "nt", "Windows default data-root permission policy")
    def test_windows_programdata_sibling_creation_is_compatible_while_root_remains_read_only(self):
        from test_windows_trust import acl, ace
        root = Path("C:/ProgramData/MeshCore-EMS/data")
        closed = []
        def pin(path):
            return str(path), closed.append
        def security(path, directory):
            grants = acl(ace("S-1-5-32-544", 0x1F01FF), ace("S-1-5-19", 0x1200A9))
            if path == Path("C:/ProgramData"):
                grants = acl(ace("S-1-5-32-544", 0x1F01FF), ace("S-1-5-11", 4))
            return "S-1-5-32-544", grants
        with patch.object(Path, "exists", return_value=True), patch.object(windows_trust, "_directory_pin", side_effect=pin), \
                patch.object(windows_trust, "_security", side_effect=security):
            with windows_trust.protected_data_root(root):
                self.assertEqual(closed, [])
        self.assertEqual(len(closed), 4)

    @unittest.skipUnless(os.name == "nt", "Windows data-root writable consumer rejection")
    def test_windows_service_read_grants_do_not_allow_service_write_access_to_root(self):
        from test_windows_trust import acl, ace
        root = Path("C:/ProgramData/MeshCore-EMS/data")
        def security(path, directory):
            return "S-1-5-32-544", acl(ace("S-1-5-32-544", 0x1F01FF), ace("S-1-5-19", 0x1301BF if path == root else 0x1200A9))
        with patch.object(Path, "exists", return_value=True), patch.object(windows_trust, "_directory_pin", return_value=(1, lambda handle: None)), \
                patch.object(windows_trust, "_security", side_effect=security):
            with self.assertRaises(PermissionError):
                with windows_trust.protected_data_root(root):
                    self.fail("Accepted writable consumer root")

    @unittest.skipUnless(os.name == "nt", "Windows native bootstrap helper")
    def test_powershell_native_preflight_rejects_unsafe_parent_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "uncreated data"
            helper = Path(__file__).resolve().parents[1] / "installers/desktop/data_root.ps1"
            script = Path(temporary) / "check.ps1"
            script.write_text('''param([string]$Helper,[string]$Root)
$ErrorActionPreference='Stop'
. $Helper
try { $lease = Enter-MeshCoreDataRoot $Root; Exit-MeshCoreDataRoot $lease; exit 27 }
catch { if (Test-Path -LiteralPath $Root) { exit 28 }; Write-Output $_.Exception.Message; exit 0 }
''')
            executable = Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-File", str(script), str(helper), str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Dataset storage", result.stdout)
            self.assertFalse(root.exists())

    @unittest.skipIf(os.name == "nt", "POSIX metadata root boundary")
    def test_posix_caller_owned_or_writable_ancestor_blocks_without_mutation(self):
        root = Path("/trusted/data")
        for owner, mode in ((1000, 0o755), (0, 0o775), (0, 0o777)):
            def metadata(path, *args, **kwargs):
                return SimpleNamespace(st_uid=owner if path == Path("/trusted") else 0,
                                       st_mode=stat.S_IFDIR | (mode if path == Path("/trusted") else 0o755))
            with patch.object(Path, "exists", return_value=True), patch.object(Path, "lstat", metadata), \
                    patch.object(Path, "mkdir", side_effect=AssertionError("Changed storage")):
                with self.assertRaises(PermissionError):
                    with manage.protected_data_root(root, create=True):
                        self.fail("Accepted unsafe ancestor")

    @unittest.skipIf(os.name == "nt", "POSIX symlink race rejection")
    def test_posix_symlink_substitution_is_rejected_before_mutation(self):
        root = Path("/trusted/data")
        def metadata(path, *args, **kwargs):
            return SimpleNamespace(st_uid=0, st_mode=(stat.S_IFLNK if path == Path("/trusted") else stat.S_IFDIR) | 0o755)
        with patch.object(Path, "exists", return_value=True), patch.object(Path, "lstat", metadata), \
                patch.object(Path, "mkdir", side_effect=AssertionError("Changed storage")):
            with self.assertRaises(PermissionError):
                with manage.protected_data_root(root, create=True):
                    self.fail("Accepted substituted link")

    @unittest.skipIf(os.name == "nt", "POSIX default creation policy")
    def test_posix_new_default_child_uses_root_readable_nonwritable_mode(self):
        root = Path("/var/lib/meshcore-ems/data")
        existing = set(root.parents)
        def metadata(path, *args, **kwargs):
            return SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | (0o750 if path == root.parent else 0o755))
        with patch.object(Path, "exists", autospec=True, side_effect=lambda path: path in existing), \
                patch.object(Path, "lstat", metadata), patch.object(Path, "mkdir", autospec=True) as mkdir:
            with manage.protected_data_root(root, create=True):
                pass
        mkdir.assert_called_once_with(root, mode=0o755)


if __name__ == "__main__":
    unittest.main()
