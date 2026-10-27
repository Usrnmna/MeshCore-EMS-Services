"""Pin protected Windows code paths before privileged native child execution.

An uninstall registration identifies its package but does not establish that its
code is protected. This boundary accepts only privileged ownership and denies
effective write grants to other principals. Unsupported ACL forms fail closed.
No ACL or owner is modified. Legitimate custom locations remain usable when the
whole path is protected; unsafe locations require graphical native repair.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import re
import struct

TRUSTED_SIDS = frozenset({
    "S-1-5-18",                  # Local System
    "S-1-5-32-544",             # Builtin Administrators
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",  # TrustedInstaller
})
ALLOW_TYPES = {0, 5, 9, 11}
DENY_TYPES = {1, 6, 10, 12}
OBJECT_TYPES = {5, 6, 11, 12}
INHERIT_ONLY = 0x08
# Generic writes/all, DELETE, WRITE_DAC, WRITE_OWNER, data/append/EA/attribute
# writes. Directories also require protection against FILE_DELETE_CHILD.
WRITE_MASK = 0x500D0116
REPLACEMENT_MASK = 0x500D0150
REPAIR = ("Installed code or an ancestor is not protected for administrator execution. "
          "Use the current graphical native installer to repair the package in a "
          "protected installation location. Existing custom files and settings must be retained.")


def _sid(data, offset=0):
    """Decode a bounded Windows SID from ACL bytes without running native code."""
    if offset + 8 > len(data) or data[offset] != 1:
        raise ValueError("Invalid security identifier")
    count = data[offset + 1]
    end = offset + 8 + count * 4
    if count > 15 or end > len(data):
        raise ValueError("Truncated security identifier")
    authority = int.from_bytes(data[offset + 2:offset + 8], "big")
    subs = struct.unpack_from("<" + "I" * count, data, offset + 8) if count else ()
    return "S-1-" + str(authority) + "".join("-" + str(value) for value in subs)


def parse_acl(data):
    """Return effective-grant metadata; reject malformed or unsupported ACE forms.

    Callback conditions and object restrictions can narrow a grant. They never
    justify accepting an otherwise unsafe principal, so no condition evaluator
    is needed. Deny entries are not used to prove a broad allow grant safe.
    """
    if data is None:
        raise PermissionError("A null DACL grants unrestricted access")
    if len(data) < 8:
        raise ValueError("Truncated DACL")
    revision, _, size, count, _ = struct.unpack_from("<BBHHH", data)
    if revision not in {2, 4} or size < 8 or size > len(data):
        raise ValueError("Invalid DACL size or revision")
    offset, entries = 8, []
    for _ in range(count):
        if offset + 4 > size:
            raise ValueError("Truncated ACE header")
        kind, flags, length = struct.unpack_from("<BBH", data, offset)
        if kind not in ALLOW_TYPES | DENY_TYPES or length < 16 or offset + length > size:
            raise ValueError("Unsupported or malformed DACL entry")
        value = data[offset:offset + length]
        mask = struct.unpack_from("<I", value, 4)[0]
        sid_offset = 8
        if kind in OBJECT_TYPES:
            if length < 20:
                raise ValueError("Truncated object ACE")
            object_flags = struct.unpack_from("<I", value, 8)[0]
            if object_flags & ~3:
                raise ValueError("Unsupported object ACE flags")
            sid_offset = 12 + (16 if object_flags & 1 else 0) + (16 if object_flags & 2 else 0)
        entries.append((kind, flags, mask, _sid(value, sid_offset)))
        offset += length
    return entries


def check_security(owner, dacl, *, directory=False, ancestor=False):
    """Require privileged ownership and no effective unprivileged mutation grant.

    ``ancestor=True`` is reserved for the volume root: normal Windows volume
    roots permit creating a new directory while preventing replacement of an
    existing protected branch. Every other directory is checked for all writes
    to prevent injected sibling modules or DLLs below an import root.
    """
    if owner not in TRUSTED_SIDS:
        raise PermissionError("Installed code owner is not a protected system principal")
    forbidden = REPLACEMENT_MASK if ancestor else WRITE_MASK | (0x40 if directory else 0)
    for kind, flags, mask, principal in parse_acl(dacl):
        if kind in DENY_TYPES or flags & INHERIT_ONLY:
            continue
        if principal not in TRUSTED_SIDS and mask & forbidden:
            raise PermissionError("Installed code DACL grants modification to an untrusted principal")


def _security(path, *, directory):
    """Read owner/DACL through a READ_CONTROL handle while the path stays pinned.

    The session helper's directory handles request only FILE_READ_ATTRIBUTES.
    A second handle supplies READ_CONTROL; neither handle shares deletion.
    GetSecurityInfo returns a LocalFree-owned descriptor and performs no writes.
    """
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    flags = 0x00200000 | (0x02000000 if directory else 0)
    handle = kernel.CreateFileW(str(path), 0x20080, 3, None, 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    descriptor, owner, dacl = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    advapi.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetSecurityInfo.restype = wintypes.DWORD
    advapi.IsValidSid.argtypes = [ctypes.c_void_p]
    advapi.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi.GetLengthSid.restype = wintypes.DWORD
    advapi.IsValidAcl.argtypes = [ctypes.c_void_p]
    try:
        code = advapi.GetSecurityInfo(handle, 1, 5, ctypes.byref(owner), None,
            ctypes.byref(dacl), None, ctypes.byref(descriptor))
        if code:
            raise ctypes.WinError(code)
        if not owner.value or not advapi.IsValidSid(owner):
            raise ValueError("Installed code has an invalid owner")
        owner_sid = _sid(ctypes.string_at(owner, advapi.GetLengthSid(owner)))
        if not dacl.value:
            return owner_sid, None
        if not advapi.IsValidAcl(dacl):
            raise ValueError("Installed code has an invalid DACL")
        size = struct.unpack_from("<H", ctypes.string_at(dacl, 8), 2)[0]
        return owner_sid, ctypes.string_at(dacl, size)
    finally:
        if descriptor.value:
            kernel.LocalFree(descriptor)
        kernel.CloseHandle(handle)


def _directory_pin(path):
    """Hold FILE_LIST_DIRECTORY access so no-delete sharing actually pins a folder.

    Windows permits renaming an empty directory when only attribute/security
    handles remain open. FILE_LIST_DIRECTORY participates in sharing checks and
    prevents that replacement, including after a native uninstall empties a child.
    """
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x20081, 3, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    class AttributeTagInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]
    info = AttributeTagInfo()
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
        ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    try:
        if not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & 0x400 or not info.attributes & 0x10:
            raise ValueError("Protected program ancestors cannot be reparse points")
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    return handle, kernel.CloseHandle


def _paths(values):
    """Accept local absolute paths without aliases, ADS syntax or traversal."""
    if isinstance(values, (str, Path)):
        values = [values]
    result = []
    for value in values:
        path = Path(value)
        if not path.is_absolute() or not re.fullmatch(r"[A-Za-z]:", path.drive) or any(
                part in {".", ".."} or ":" in part or part.endswith((".", " "))
                for part in path.parts[1:]):
            raise ValueError("Protected execution requires absolute local Windows paths without traversal or alternate streams")
        result.append(path)
    if not result:
        raise ValueError("No installed program paths were supplied")
    return tuple(dict.fromkeys(result))


@contextmanager
def protected_paths(paths, *, allow_removal_under=None):
    """Pin and validate fixed installed code until its privileged operation ends.

    Normal execution retains no-delete ancestor and immutable file handles.
    Native uninstall must remove its own files: that explicit mode releases only
    handles inside the fully validated removal root after all checks succeed.
    Protected outside ancestors stay pinned, and unprivileged modification is
    excluded by the checked owner/DACL. No arbitrary removal is performed here.
    """
    if os.name != "nt":
        raise ValueError("Windows protected execution is unavailable on this platform")
    from .authorization import _windows_locked_handle
    requested = _paths(paths)
    removal = _paths([allow_removal_under])[0] if allow_removal_under is not None else None
    if removal is not None and (removal == Path(removal.anchor) or not any(path.is_relative_to(removal) for path in requested)):
        raise ValueError("Native removal must name its registered package subtree")
    nodes = set()
    for path in (*requested, *((removal,) if removal else ())):
        nodes.update(path.parents); nodes.add(path)
    held = []
    try:
        try:
            for path in sorted(nodes, key=lambda value: (len(value.parts), str(value).casefold())):
                directory = path.is_dir()
                handle, close = _windows_locked_handle(path, directory=directory)
                held.append((path, handle, close))
                if directory:
                    handle, close = _directory_pin(path)
                    held.append((path, handle, close))
                check_security(*_security(path, directory=directory), directory=directory,
                               ancestor=path == Path(path.anchor))
        except (OSError, ValueError) as error:
            raise PermissionError(REPAIR) from error
        if removal is not None:
            retained = []
            for path, handle, close in reversed(held):
                if path.is_relative_to(removal):
                    close(handle)
                else:
                    retained.append((path, handle, close))
            held = list(reversed(retained))
        yield requested
    finally:
        for _, handle, close in reversed(held):
            close(handle)


def validate_paths(paths):
    """Validate protected paths for discovery; execution must keep its own context."""
    with protected_paths(paths):
        return True


def _create_data_directory(path):
    """Create new data storage with privileged ownership and read-only service access."""
    from ctypes import wintypes
    from . import staging
    # No global descriptor mutation: construct a private directory first, then
    # only add read grants while its owner and parent are already protected.
    staging._create_private_directory(path)
    security = "O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;GRGX;;;AU)(A;OICI;GRGX;;;LS)"
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p()
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(security, 1, ctypes.byref(pointer), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        if not advapi.SetFileSecurityW(str(path), 0x80000004, pointer):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(pointer)


@contextmanager
def protected_data_root(value, *, create=False):
    """Pin a protected data root and ancestors without altering existing ownership.

    Ancestors may permit creation of unrelated siblings, as ProgramData normally
    does. They must not permit replacement of an existing protected branch. The
    actual dataset root denies all unprivileged writes for the full mutation.
    """
    if os.name != "nt":
        raise ValueError("Windows data-root protection is unavailable")
    path = _paths([value])[0]
    held = []
    try:
        for current in (*reversed(path.parents), path):
            if not current.exists():
                if not create:
                    raise FileNotFoundError(str(current))
                _create_data_directory(current)
            handle, close = _directory_pin(current)
            held.append((handle, close))
            check_security(*_security(current, directory=True), directory=True, ancestor=current != path)
        yield path
    except (OSError, ValueError) as error:
        raise PermissionError("Dataset storage or an ancestor is not protected. Choose a root-owned/system-owned protected data location in the graphical installer; existing custom directories and permissions were not changed.") from error
    finally:
        for handle, close in reversed(held):
            close(handle)
