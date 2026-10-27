"""Native authorization for bounded installer requests, without an elevated Qt UI.

The worker accepts structured operations, never executable names or shell text.
Request/result files belong to one temporary session; credentials are not printed.
Cancellation is a marker observed at safe backend boundaries, never process killing.
"""

from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time

MAX_REQUEST = 64 * 1024


def validate_envelope(request):
    """Reject unrecognized dispatchers and unbounded/non-object JSON requests."""
    if not isinstance(request, dict) or request.get("kind") not in {"dataset", "service", "unified"}:
        raise ValueError("Unknown desktop operation")
    if len(json.dumps(request).encode("utf-8")) > MAX_REQUEST:
        raise ValueError("Desktop request is too large")
    return request


def worker_command(request_path):
    """Select only this application's worker; source invocation is developer-only."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--desktop-worker", str(request_path)]
    return [sys.executable, "-I", str(Path(__file__).resolve()), "--desktop-worker", str(request_path)]


class WindowsProcess:
    """Own the UAC-launched process handle until exit, without exposing a console."""

    def __init__(self, handle):
        self.handle = handle

    def poll(self):
        import ctypes
        code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise OSError("Cannot inspect the authorized operation")
        return None if code.value == 259 else code.value

    def close(self):
        import ctypes
        ctypes.windll.kernel32.CloseHandle(self.handle)


def launch_worker(command):
    """Request native authorization; fail without falling back to terminal passwords."""
    if os.name != "nt":
        pkexec = shutil.which("pkexec")
        if pkexec is None:
            raise RuntimeError("Desktop authorization is unavailable. Install the distribution's polkit desktop authentication agent through its graphical software manager, then reopen this application.")
        # No Qt/display variables are forwarded. A session authentication agent
        # supplies the dialog; disabling the internal agent forbids a text prompt.
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME"}}
        return subprocess.Popen([pkexec, "--disable-internal-agent", *command],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env=environment)
    import ctypes
    from ctypes import wintypes
    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # NOCLOSEPROCESS and NOASYNC retain a waitable handle.
    info.lpVerb = "runas"
    info.lpFile = command[0]
    info.lpParameters = subprocess.list2cmdline(command[1:])
    info.lpDirectory = str(Path(command[0]).parent)
    info.nShow = 0
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == 1223:
            raise RuntimeError("Administrator authorization was cancelled. No operation started.")
        raise OSError(code, "Cannot open the administrator authorization dialog")
    # Explicit HANDLE signatures prevent truncation in 64-bit Python.
    ctypes.windll.kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    ctypes.windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return WindowsProcess(info.hProcess)


def _read_events(path, emit, offset):
    """Read complete worker log lines; leave partial writes for the next poll."""
    if not path.exists():
        return offset
    with path.open("r", encoding="utf-8") as stream:
        stream.seek(offset)
        while True:
            start = stream.tell()
            line = stream.readline()
            if not line.endswith("\n"):
                return start
            emit(json.loads(line))
            offset = stream.tell()


def run_authorized(request, emit, cancel=None):
    """Authorize one request and return its backend result; raise on refusal/failure."""
    validate_envelope(request)
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise RuntimeError("Operation cancelled before authorization. No operation started.")
    with tempfile.TemporaryDirectory(prefix="meshcore-desktop-") as temporary:
        directory = Path(temporary)
        request_path = directory / "request.json"
        with request_path.open("x", encoding="utf-8") as stream:
            json.dump(request, stream, allow_nan=False)
        if os.name != "nt":
            request_path.chmod(0o600)
        emit("Waiting for the operating system authorization dialog…")
        process = launch_worker(worker_command(request_path))
        offset = 0
        try:
            while process.poll() is None:
                offset = _read_events(directory / "events.jsonl", emit, offset)
                if cancel.is_set() and not (directory / "cancel").exists():
                    (directory / "cancel").touch(exist_ok=False)
                time.sleep(0.1)
            _read_events(directory / "events.jsonl", emit, offset)
            result_path = directory / "result.json"
            if not result_path.is_file():
                raise RuntimeError("Authorization was cancelled or no graphical authentication agent was available. No completed result was received. Check the desktop's polkit agent on Linux/Pi and retry.")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "The authorized operation failed"))
            if process.poll() != 0:
                raise RuntimeError("The authorized operation exited unsuccessfully; review its logs.")
            return result["value"]
        finally:
            close = getattr(process, "close", None)
            if close:
                close()


class WorkerSession:
    """Keep worker I/O attached to the validated directory for the entire operation."""

    def __init__(self, path, directory_fd=None):
        self.path = path
        self.directory_fd = directory_fd
        self.request = None

    def open_output(self, name):
        """Create an exclusive output in the anchored session, never a substituted path."""
        if name not in {"result.json", "events.jsonl"}:
            raise ValueError("Unknown worker output")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        if self.directory_fd is not None:
            return os.open(name, flags, 0o600, dir_fd=self.directory_fd)
        # Windows ancestors are held with handles that forbid rename/delete.
        # CREATE_NEW from O_EXCL also refuses a preplaced leaf reparse point.
        return os.open(self.path.parent / name, flags, 0o600)

    def cancelled(self):
        """Check only the fixed cancellation marker, without following its target."""
        try:
            if self.directory_fd is not None:
                os.stat("cancel", dir_fd=self.directory_fd, follow_symlinks=False)
            else:
                os.lstat(self.path.parent / "cancel")
            return True
        except FileNotFoundError:
            return False


def _windows_locked_handle(path, *, directory, delete=False):
    """Lock one path against replacement and reject directory/file reparse points.

    Ancestors are opened from the volume root downward and held until dispatch
    finishes. FILE_SHARE_DELETE is deliberately absent so a caller cannot rename
    an already validated directory and replace it with a junction or symlink.
    """
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # LIST_DIRECTORY is required for the no-delete share to pin an empty
    # directory against rename; READ_ATTRIBUTES alone does not establish that pin.
    access = 0x81 if directory else 0x80000000
    if delete:
        access |= 0x00010000
    sharing = 0x1 | 0x2 if directory else 0x1  # Files also forbid concurrent writes.
    flags = 0x00200000 | (0x02000000 if directory else 0)
    handle = kernel.CreateFileW(str(path), access, sharing, None, 3, flags, None)
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
        if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
            raise ValueError("Authorization session paths cannot contain reparse points or unexpected file types")
    except Exception:
        kernel.CloseHandle(handle)
        raise
    return handle, kernel.CloseHandle


@contextmanager
def worker_session(path):
    """Anchor private request/output I/O before validating the requested operation."""
    path = Path(path)
    if not path.is_absolute() or path.name != "request.json" or path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Invalid authorization request location")
    with ExitStack() as resources:
        if os.name == "nt":
            # Lock top-down. Each held ancestor protects lookup of the next child.
            for directory in [*reversed(path.parent.parents), path.parent]:
                handle, close = _windows_locked_handle(directory, directory=True)
                resources.callback(close, handle)
            handle, close = _windows_locked_handle(path, directory=False)
            import msvcrt
            try:
                descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
            except Exception:
                close(handle)
                raise
            resources.callback(os.close, descriptor)
            session = WorkerSession(path)
        else:
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            resources.callback(os.close, directory_fd)
            parent = os.fstat(directory_fd)
            caller = int(os.environ.get("PKEXEC_UID", os.getuid()))
            if parent.st_uid != caller or parent.st_mode & 0o077:
                raise ValueError("Authorization directory must be private and owned by its caller")
            descriptor = os.open("request.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory_fd)
            resources.callback(os.close, descriptor)
            session = WorkerSession(path, directory_fd)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REQUEST:
            raise ValueError("Authorization request must be a bounded regular file")
        if os.name != "nt" and (info.st_uid != caller or info.st_mode & 0o077):
            raise ValueError("Authorization request must be private and owned by its caller")
        # dup keeps the immutable/anchored request handle alive until context exit.
        with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as stream:
            content = stream.read(MAX_REQUEST + 1)
        if len(content.encode("utf-8")) > MAX_REQUEST:
            raise ValueError("Desktop request is too large")
        session.request = validate_envelope(json.loads(content))
        yield session


def _worker_request(path):
    """Read request metadata for inspection; worker dispatch must retain its session."""
    with worker_session(path) as session:
        return session.path, session.request


def worker_privileged():
    """Require native elevation before accepting even a read-only worker request."""
    if os.name == "nt":
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return os.geteuid() == 0


def worker_main(request_path):
    """Dispatch a validated operation before importing Qt and write one final result."""
    if not worker_privileged():
        raise PermissionError("A desktop worker must be launched through native administrator authorization")
    with worker_session(request_path) as session:
        return _dispatch_session(session)


def _dispatch_session(session):
    """Create output handles and dispatch while the validated session stays anchored."""
    request = session.request
    # Open both output handles before dispatch, never following preplaced links.
    result_fd = session.open_output("result.json")
    try:
        event_fd = session.open_output("events.jsonl")
    except Exception:
        os.close(result_fd)
        raise
    if os.name != "nt" and "PKEXEC_UID" in os.environ:
        caller = int(os.environ["PKEXEC_UID"])
        # Keep logs readable by the desktop user while retaining safe open handles.
        os.fchown(result_fd, caller, -1)
        os.fchown(event_fd, caller, -1)
    with os.fdopen(result_fd, "w", encoding="utf-8") as output, \
         os.fdopen(event_fd, "w", encoding="utf-8", buffering=1) as events:
        def emit(message):
            events.write(json.dumps(str(message)) + "\n")
            events.flush()
        class Cancellation:
            def is_set(self):
                return session.cancelled()
        try:
            if request["kind"] == "dataset":
                from installers.datasets.gui.privileges import perform
            elif request["kind"] == "unified":
                from installers.desktop.unified_backend import perform
            else:
                from installers.desktop.service_backend import perform
            value = perform(request, emit, Cancellation())
            result = {"ok": True, "value": value}
            status = 0
        except Exception as error:
            result = {"ok": False, "error": str(error)}
            status = 1
        json.dump(result, output, allow_nan=False)
        output.flush()
    return status


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    if len(sys.argv) != 3 or sys.argv[1] != "--desktop-worker":
        raise SystemExit("Only a reviewed desktop worker request is accepted")
    raise SystemExit(worker_main(sys.argv[2]))
