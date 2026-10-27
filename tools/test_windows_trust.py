"""Conservative installed-code ACL checks without modifying system permissions."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installers.desktop import windows_trust as trust


def sid(value):
    fields = [int(value) for value in value.split("-")[1:]]
    return bytes([fields[0], len(fields) - 2]) + fields[1].to_bytes(6, "big") + b"".join(struct.pack("<I", item) for item in fields[2:])


def ace(principal, mask, *, flags=0, kind=0, object_flags=0):
    content = struct.pack("<I", mask)
    if kind in {5, 6, 11, 12}:
        content += struct.pack("<I", object_flags)
        if object_flags & 1:
            content += bytes(16)
        if object_flags & 2:
            content += bytes(16)
    content += sid(principal)
    return struct.pack("<BBH", kind, flags, len(content) + 4) + content


def acl(*entries):
    content = b"".join(entries)
    return struct.pack("<BBHHH", 2, 0, len(content) + 8, len(entries), 0) + content


class AclTrustTests(unittest.TestCase):
    def test_trusted_owners_and_privileged_writes_are_accepted(self):
        for owner in trust.TRUSTED_SIDS:
            trust.check_security(owner, acl(ace(owner, 0x1F01FF)))

    def test_user_owner_is_rejected_even_with_read_only_acl(self):
        with self.assertRaisesRegex(PermissionError, "owner"):
            trust.check_security("S-1-5-21-1-2-3-1001", acl(ace("S-1-5-32-545", 0x1200A9)))

    def test_null_dacl_is_rejected(self):
        with self.assertRaisesRegex(PermissionError, "DACL"):
            trust.check_security("S-1-5-18", None)

    def test_unprivileged_read_only_access_is_allowed(self):
        trust.check_security("S-1-5-32-544", acl(ace("S-1-5-32-545", 0x1200A9)))

    def test_all_file_write_and_control_rights_are_rejected(self):
        for mask in (2, 4, 0x10, 0x100, 0x10000, 0x40000, 0x80000, 0x40000000, 0x10000000):
            with self.subTest(mask=hex(mask)), self.assertRaises(PermissionError):
                trust.check_security("S-1-5-18", acl(ace("S-1-5-32-545", mask)))

    def test_ancestors_allow_creation_but_reject_replacement_and_acl_rights(self):
        trust.check_security("S-1-5-32-544", acl(ace("S-1-5-11", 4)), ancestor=True, directory=True)
        for mask in (0x40, 0x10000, 0x40000, 0x80000, 0x10000000, 0x40000000):
            with self.subTest(mask=hex(mask)), self.assertRaises(PermissionError):
                trust.check_security("S-1-5-32-544", acl(ace("S-1-5-11", mask)), ancestor=True, directory=True)

    def test_non_volume_directory_cannot_allow_sibling_module_injection(self):
        for mask in (2, 4, 0x40):
            with self.subTest(mask=mask), self.assertRaises(PermissionError):
                trust.check_security("S-1-5-18", acl(ace("S-1-5-11", mask)), directory=True)

    def test_inherit_only_permission_is_not_an_access_grant_to_this_object(self):
        trust.check_security("S-1-5-18", acl(ace("S-1-3-0", 0x1F01FF, flags=8)), ancestor=True, directory=True)

    def test_inherited_effective_write_is_still_rejected(self):
        with self.assertRaises(PermissionError):
            trust.check_security("S-1-5-18", acl(ace("S-1-5-11", 2, flags=0x10)))

    def test_deny_aces_do_not_turn_unsafe_allow_into_trusted_policy(self):
        with self.assertRaises(PermissionError):
            trust.check_security("S-1-5-18", acl(ace("S-1-5-11", 2, kind=1), ace("S-1-5-11", 2)))

    def test_object_ace_sid_is_parsed_after_both_optional_guids(self):
        with self.assertRaises(PermissionError):
            trust.check_security("S-1-5-18", acl(ace("S-1-5-11", 2, kind=5, object_flags=3)))
        trust.check_security("S-1-5-18", acl(ace("S-1-5-18", 2, kind=5, object_flags=3)))

    def test_unknown_and_truncated_aces_fail_closed(self):
        for value in (acl(ace("S-1-5-18", 2, kind=99)), acl(ace("S-1-5-18", 2))[:-1], bytes(8)):
            with self.subTest(value=value), self.assertRaises((ValueError, PermissionError)):
                trust.check_security("S-1-5-18", value)

    @unittest.skipUnless(os.name == "nt", "Windows native path and repair guidance")
    def test_unsafe_custom_path_message_explains_graphical_repair(self):
        with patch.object(trust, "_security", return_value=("S-1-5-21-1-2-3-1001", acl())):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "program.py"
                path.write_text("pass\n")
                with self.assertRaisesRegex(PermissionError, "repair|Repair"):
                    with trust.protected_paths([path]):
                        self.fail("unsafe path accepted")


@unittest.skipUnless(os.name == "nt", "Windows handle sharing contract")
class WindowsHandleTests(unittest.TestCase):
    def test_real_unprotected_temporary_installation_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            program = Path(temporary) / "program.py"
            program.write_text("pass\n")
            with self.assertRaisesRegex(PermissionError, "repair"):
                with trust.protected_paths([program]):
                    self.fail("unprotected user installation was trusted")

    def test_network_traversal_and_alternate_stream_paths_are_rejected(self):
        for value in (r"\\server\share\program.exe", r"C:\Program Files\..\program.exe", r"C:\Program Files\program.exe:stream"):
            with self.subTest(path=value), self.assertRaises(ValueError):
                with trust.protected_paths([Path(value)]):
                    self.fail("unsafe spelling accepted")

    def test_validated_path_is_pinned_against_parent_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "programs"
            parent.mkdir()
            program = parent / "program.py"; program.write_text("pass\n")
            # Only metadata is fixture-supplied; actual native handles remain held.
            with patch.object(trust, "_security", return_value=("S-1-5-18", acl())):
                with trust.protected_paths([program]):
                    with self.assertRaises(PermissionError):
                        parent.rename(parent.with_name("replacement"))
                    with self.assertRaises(PermissionError):
                        program.write_text("changed\n")

    def test_uninstall_releases_only_inside_the_reviewed_removal_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "installed"
            root.mkdir()
            program = root / "uninstall.exe"; program.write_bytes(b"fixture")
            with patch.object(trust, "_security", return_value=("S-1-5-18", acl())):
                with trust.protected_paths([program], allow_removal_under=root):
                    program.unlink(); root.rmdir()
                    with self.assertRaises(PermissionError):
                        parent.rename(parent.with_name(parent.name + "-moved"))


if __name__ == "__main__":
    unittest.main()
