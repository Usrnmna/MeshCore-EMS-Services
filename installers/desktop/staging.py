"""Atomically private native staging outside desktop-controlled ancestors.

Only newly created stage directories/files receive the explicit Windows owner
and DACL. Existing arbitrary paths are never repaired or given new permissions.
The active context bounds the file writer and cleanup to its own random child.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import ctypes
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

PRIVATE_SDDL = "O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
_ACTIVE_STAGE = ContextVar("meshcore_private_stage", default=None)


@contextmanager
def _windows_attributes():
    """Build a LocalFree-owned security descriptor for atomic new-object creation."""
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(PRIVATE_SDDL, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]
    value = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
    try:
        yield value
    finally:
        kernel.LocalFree(descriptor)


def _create_private_directory(path):
    """Create one new directory with protection present at its first visibility."""
    if os.name != "nt":
        os.mkdir(path, 0o700)
        return
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    with _windows_attributes() as attributes:
        kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(type(attributes))]
        kernel.CreateDirectoryW.restype = wintypes.BOOL
        if not kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
            raise ctypes.WinError(ctypes.get_last_error())


def _open_private_file(path):
    """Create a new private file exclusively; return an owned binary descriptor."""
    if os.name != "nt":
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    with _windows_attributes() as attributes:
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(type(attributes)), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        handle = kernel.CreateFileW(str(path), 0x40000000, 0, ctypes.byref(attributes), 1, 0x00200080, None)
        error = ctypes.get_last_error() if handle == ctypes.c_void_p(-1).value else 0
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(error)
    try:
        return msvcrt.open_osfhandle(int(handle), os.O_WRONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise


def require_trusted_owner(path):
    """Inspect ownership of fixed privileged storage without changing its ACL."""
    path = Path(path)
    if os.name == "nt":
        from .windows_trust import TRUSTED_SIDS, _security
        owner, _ = _security(path, directory=path.is_dir())
        if owner not in TRUSTED_SIDS:
            raise PermissionError("Protected maintenance storage requires a system or Administrators owner; existing ownership was not changed")
    elif path.lstat().st_uid != 0:
        raise PermissionError("Protected maintenance storage must be root-owned")


@contextmanager
def _protected_base(base):
    """Keep the fixed machine staging parent protected throughout creation/cleanup."""
    if os.name == "nt":
        from .windows_trust import protected_paths
        with protected_paths([base]):
            yield
        return
    metadata = base.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o077:
        raise PermissionError("Private staging storage must be root-owned and private")
    yield


def _stage_identity(path):
    """Reject redirected roots and retain identity for scoped cleanup and writes."""
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise PermissionError("Private stage cannot be redirected")
    return metadata.st_dev, metadata.st_ino


def _destination(path):
    """Require a regular new-file destination beneath the active unchanged stage."""
    active = _ACTIVE_STAGE.get()
    if active is None:
        raise PermissionError("Private files require an active staging context")
    root, identity = active
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(root) or path == root:
        raise PermissionError("Private file destination escapes the active stage")
    if _stage_identity(root) != identity:
        raise PermissionError("Private staging directory changed identity")
    current = path.parent
    while current != root:
        metadata = current.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise PermissionError("Private file parent cannot be redirected")
        current = current.parent
    if any(":" in part or part.endswith((".", " ")) for part in path.relative_to(root).parts):
        raise PermissionError("Private file cannot use alternate streams or alias spellings")
    return path


def write_private_file(path, *, content=None, source=None):
    """Write bytes or copy one source into a new file scoped to the active stage.

    Source copying streams large installers. Callers still compare the staged
    hash against the reviewed artifact. Existing files are never overwritten.
    """
    if (content is None) == (source is None) or content is not None and not isinstance(content, bytes):
        raise ValueError("Supply exactly one bytes content value or source path")
    path = _destination(path)
    with os.fdopen(_open_private_file(path), "wb") as stream:
        if source is None:
            stream.write(content)
        else:
            with Path(source).open("rb") as original:
                shutil.copyfileobj(original, stream, 1024 * 1024)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _cleanup(root, base, identity):
    """Remove only the unchanged random child created by this context."""
    try:
        actual = _stage_identity(root)
    except FileNotFoundError:
        return
    if actual != identity or root.parent != base or root.resolve().parent != base.resolve():
        raise PermissionError("Private stage changed; retained for inspection instead of cleanup")
    shutil.rmtree(root)


@contextmanager
def private_temporary_directory(prefix):
    """Keep native artifacts/settings in a new protected machine-owned directory."""
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", prefix):
        raise ValueError("Private staging prefix must be a short fixed identifier")
    from .locking import maintenance_directory
    base = Path(maintenance_directory())
    with _protected_base(base):
        root = base / (prefix + uuid.uuid4().hex)
        _create_private_directory(root)
        identity = _stage_identity(root)
        token = _ACTIVE_STAGE.set((root, identity))
        try:
            yield str(root)
        finally:
            _ACTIVE_STAGE.reset(token)
            _cleanup(root, base, identity)
