"""Disposable history processes with independent deadlines and nonblocking UI ownership.

Only fixed history helper modes are launched. The GUI owns an unjoined daemon;
each helper owns its read child and observes parent loss through an open pipe.
No service or maintenance process is a termination target.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

READ_SECONDS = 5.0
AUTH_SECONDS = 120.0
CANCEL_GRACE = 1.0
MAX_RESPONSE = 2 * 1024 * 1024
MAX_REQUEST = 64 * 1024


def ensure_helper_stdio():
    """Recover redirected pipes in a Windows windowed executable without a console.

    PyInstaller's windowed bootloader leaves the Python standard streams unset.
    Only inherited standard handles are duplicated; no console or named pipe is
    opened, and the ordinary GUI does not call this helper-only function.
    """
    if os.name != "nt" or (sys.stdin is not None and sys.stdout is not None):
        return
    import ctypes
    from ctypes import wintypes
    import io
    import msvcrt

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetStdHandle.argtypes = [wintypes.DWORD]
    api.GetStdHandle.restype = wintypes.HANDLE
    api.GetCurrentProcess.restype = wintypes.HANDLE
    api.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                   ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                   wintypes.BOOL, wintypes.DWORD]
    api.DuplicateHandle.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    process = api.GetCurrentProcess()
    for name, identifier, mode, flags in (("stdin", -10, "rb", os.O_RDONLY),
                                          ("stdout", -11, "wb", os.O_WRONLY)):
        if getattr(sys, name) is not None:
            continue
        source = api.GetStdHandle(identifier & 0xffffffff)
        duplicate = wintypes.HANDLE()
        if not source or source == wintypes.HANDLE(-1).value or not api.DuplicateHandle(
                process, source, process, ctypes.byref(duplicate), 0, False, 2):
            raise RuntimeError("History helper requires redirected standard pipes")
        try:
            descriptor = msvcrt.open_osfhandle(duplicate.value, flags | os.O_BINARY)
        except BaseException:
            api.CloseHandle(duplicate)
            raise
        setattr(sys, name, io.TextIOWrapper(io.FileIO(descriptor, mode), encoding="utf-8"))


def helper_command(mode):
    """Return an immutable application entry point for the two read-only helpers."""
    if mode not in {"read", "session"}:
        raise ValueError("Unknown history helper")
    flag = "--history-" + mode
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), flag]
    return [sys.executable, "-I", "-B", str(Path(__file__).resolve()), flag]


def _stop_owned(child, process_group=None):
    """Terminate the owned read group, including short-lived discovery descendants."""
    if process_group is not None:
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif child.poll() is not None:
        return
    else:
        child.terminate()
    limit = time.monotonic() + CANCEL_GRACE
    while child.poll() is None and time.monotonic() < limit:
        time.sleep(.02)
    if process_group is not None:
        # The reader may already have exited while a systemctl query remains.
        # Always terminate remaining group members before releasing ownership.
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif child.poll() is None:
        child.kill()
    # This is never called on the UI thread. An unkillable OS child keeps the
    # session busy so opening another viewer cannot accumulate replacements.
    while child.poll() is None:
        time.sleep(.05)


def _exchange(mode, request, cancel, lifetime):
    """Supervise fixed subprocess I/O with a bounded buffer and wall-clock budget."""
    started = time.monotonic()
    outgoing = json.dumps(request, allow_nan=False).encode("utf-8") + b"\n"
    sent = 0
    child = subprocess.Popen(helper_command(mode), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, bufsize=0,
                             start_new_session=(os.name != "nt" and mode == "read"),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    process_group = child.pid if os.name != "nt" and mode == "read" else None
    done = threading.Event()
    overflow = threading.Event()
    content = bytearray()
    def receive():
        try:
            while True:
                chunk = child.stdout.read(min(65536, MAX_RESPONSE + 1025 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_RESPONSE + 1024:
                    overflow.set()
                    break
        except OSError:
            pass
        except ValueError:
            # Cancellation/deadline cleanup can close the pipe while this
            # daemon is descheduled. Unexpected errors on an open pipe remain visible.
            if not child.stdout.closed:
                raise
        finally:
            done.set()
    threading.Thread(target=receive, name="history-response", daemon=True).start()
    reason = None
    try:
        # Anonymous pipe writes can block before a helper starts consuming its
        # request. Nonblocking OS writes keep both admission and cancellation in
        # this deadline loop; FileIO.write/flush is never called on the supervisor.
        # Unsupported runtimes fail closed instead of falling back to blocking I/O.
        os.set_blocking(child.stdin.fileno(), False)
        while True:
            if cancel.is_set():
                reason = "History read cancelled"
            elif overflow.is_set():
                reason = "History response exceeds response budget"
            elif time.monotonic() - started >= lifetime:
                reason = "History read deadline exceeded"
            if reason:
                child.stdin.close()  # EOF is also the parent's non-reusable lease.
                if mode == "session" and sent == len(outgoing):
                    # The helper owns authorization and protected result cleanup.
                    # Its read supervisor enforces the child deadline. Keep this
                    # daemon busy through cleanup; parent application exit never
                    # joins it, and no replacement session can accumulate.
                    while child.poll() is None:
                        time.sleep(.05)
                else:
                    until = time.monotonic() + CANCEL_GRACE
                    while child.poll() is None and time.monotonic() < until:
                        time.sleep(.02)
                    _stop_owned(child, process_group)
                    process_group = None
                raise RuntimeError(reason)
            if child.poll() is not None and done.is_set():
                break
            if sent < len(outgoing) and child.poll() is None:
                try:
                    sent += os.write(child.stdin.fileno(), outgoing[sent:sent + 4096])
                except BlockingIOError:
                    pass
                except BrokenPipeError:
                    raise RuntimeError("History helper failed") from None
            time.sleep(.02)
        if overflow.is_set() or len(content) > MAX_RESPONSE + 1024:
            raise RuntimeError("History response exceeds response budget")
        try:
            result = json.loads(content)
        except (ValueError, UnicodeError):
            raise RuntimeError("History helper returned an invalid response") from None
        if not isinstance(result, dict) or not result.get("ok"):
            if isinstance(result, dict) and result.get("permission"):
                raise PermissionError("History access denied")
            raise RuntimeError(result.get("error", "History database unavailable") if isinstance(result, dict) else "History database unavailable")
        if child.returncode != 0:
            raise RuntimeError("History helper failed")
        value = result.get("value")
        if not isinstance(value, dict) or len(json.dumps(value).encode()) > MAX_RESPONSE:
            raise RuntimeError("History response exceeds response budget")
        if cancel.is_set():
            raise RuntimeError("History read cancelled")
        if time.monotonic() - started >= lifetime:
            raise RuntimeError("History read deadline exceeded")
        return value
    finally:
        _stop_owned(child, process_group)
        child.stdin.close()
        child.stdout.close()


def supervise_read(request, cancel=None):
    """Enforce the five-second discovery/open/query limit outside the read process."""
    from installers.desktop.history_backend import validate_history_request
    validate_history_request(request)
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise RuntimeError("History read cancelled")
    return _exchange("read", request, cancel, READ_SECONDS)


class HistoryReadSession:
    """One app-owned optional session; polling and cancellation never wait for I/O."""
    def __init__(self):
        self._worker = None
        self._cancel = threading.Event()
        self._generation = 0
        self._status = {"state": "cancelled", "generation": 0}

    @property
    def busy(self):
        return self._worker is not None and self._worker.is_alive()

    @property
    def generation(self):
        """Current request token for rejecting replies after filter changes or close."""
        return self._generation

    def start(self, request):
        """Accept one validated request only after the previous helper has finished."""
        if self.busy:
            return False
        from installers.desktop.history_backend import validate_history_request
        validate_history_request(request)
        request = json.loads(json.dumps(request))
        self._generation += 1
        generation = self._generation
        self._cancel = threading.Event()
        cancel = self._cancel
        self._status = {"state": "running", "generation": generation}
        def run():
            try:
                value = _exchange("session", request, cancel, AUTH_SECONDS + 2 * READ_SECONDS + 2 * CANCEL_GRACE)
                status = {"state": "complete", "result": value}
            except Exception as error:
                status = {"state": "failed", "error": safe_error(error)}
            if generation == self._generation and not cancel.is_set():
                self._status = dict(status, generation=generation)
        self._worker = threading.Thread(target=run, name="history-session", daemon=True)
        self._worker.start()
        return True

    def cancel_nowait(self):
        """Invalidate old results immediately; daemon cleanup retains child ownership."""
        self._generation += 1
        self._cancel.set()
        self._status = {"state": "cancelled", "generation": self._generation}

    def poll(self):
        """Return the current in-memory status without touching a filesystem or Qt."""
        return dict(self._status)


def safe_error(error):
    """Never return raw driver errors, paths, queries, or message contents as logs."""
    if isinstance(error, PermissionError):
        return "History access denied"
    known = {"Service not installed", "Service update required", "History not created yet",
             "Unsupported history schema", "History database unavailable", "History access denied",
             "History record exceeds response budget", "History response exceeds response budget",
             "History read cancelled", "History read deadline exceeded", "History authorization cancelled or unavailable",
             "History authorization expired", "History cleanup failed", "Untrusted history installation"}
    return str(error) if str(error) in known else "History database unavailable"


def helper_main(mode):
    """Read a single bounded request before Qt imports; EOF cancels parent ownership."""
    if mode not in {"read", "session"}:
        raise ValueError("Unknown history helper")
    ensure_helper_stdio()
    cancel = threading.Event()
    try:
        line = sys.stdin.buffer.readline(MAX_REQUEST + 2)
        if len(line) > MAX_REQUEST + 1 or not line.endswith(b"\n"):
            raise ValueError("Invalid history request")
        request = json.loads(line)
        from installers.desktop.history_backend import validate_history_request, read_installed, query_history
        validate_history_request(request)
        def parent_watch():
            os.read(sys.stdin.fileno(), 1)
            cancel.set()
        threading.Thread(target=parent_watch, name="history-parent", daemon=True).start()
        if cancel.is_set():
            raise RuntimeError("History read cancelled")
        value = read_installed(request) if mode == "read" else query_history(request, lambda _: None, cancel)
        if cancel.is_set():
            raise RuntimeError("History read cancelled")
        result = {"ok": True, "value": value}
        status = 0
    except Exception as error:
        result = {"ok": False, "error": safe_error(error), "permission": isinstance(error, PermissionError)}
        status = 1
    body = json.dumps(result, allow_nan=False).encode("utf-8")
    if len(body) > MAX_RESPONSE + 1024:
        body = b'{"ok":false,"error":"History response exceeds response budget"}'
        status = 1
    try:
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()
    except OSError:
        # A lost parent can make Windows pipe flush report EINVAL instead of
        # EPIPE. Close buffered output so interpreter shutdown does not retry
        # it or let a windowed bootloader display an unhandled-error dialog.
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 1
    return status


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    if len(sys.argv) != 2 or sys.argv[1] not in {"--history-read", "--history-session"}:
        raise SystemExit("Only a reviewed history helper request is accepted")
    raise SystemExit(helper_main(sys.argv[1].removeprefix("--history-")))
