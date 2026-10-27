"""Protected process leases shared by independent native maintenance backends.

The inherited value is a random lease identifier, not an instruction. It is
accepted only against a protected record whose original process is still alive.
An interrupted lease is never stolen automatically; recovery requires review.
"""

from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from installers.desktop.native_environment import clean_environment
import stat
import subprocess
import threading

VARIABLE = "MESHCORE_MAINTENANCE_LEASE"
_THREAD_LOCK = threading.RLock()


def lock_directory():
    """Use a machine location independent of service or dataset package removal."""
    if os.name != "nt":
        return Path("/run/meshcore-ems-maintenance")
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 38, None, 0, buffer):
        raise OSError("Cannot locate the protected maintenance directory")
    return Path(buffer.value) / "MeshCore-EMS-Maintenance"


def maintenance_directory():
    """Create protected persistent journal storage independent of service ownership."""
    path = lock_directory() if os.name == "nt" else Path("/var/lib/meshcore-ems-maintenance")
    _secure_directory(path)
    return path


def process_identity(pid):
    """Return the OS process creation value, so PID reuse cannot delegate a lease."""
    if os.name != "nt":
        text = Path(f"/proc/{pid}/stat").read_text()
        return text[text.rfind(")") + 2:].split()[19]
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    times = [wintypes.FILETIME() for _ in range(4)]
    try:
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            raise OSError("Cannot verify maintenance lease owner")
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def _secure_directory(path):
    """Create the fixed privileged directory and reject link redirection.

    Windows uses Program Files protection plus an administrator/System-only DACL.
    POSIX requires root ownership and denies group/other access to the lease.
    """
    for parent in (path.parent, *path.parent.parents):
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise PermissionError("Maintenance lock ancestors cannot be links")
        if os.name != "nt":
            metadata = parent.stat()
            if metadata.st_uid != 0 or metadata.st_mode & 0o022:
                raise PermissionError("Maintenance ancestors must be root-owned and protected")
    if os.name == "nt":
        # Apply the same restrictive DACL on creation and on an existing directory.
        # Program Files ancestors prevent replacement by a desktop user.
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.c_void_p()
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW("O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", 1, ctypes.byref(pointer), None):
            raise OSError("Cannot protect the maintenance lease")
        try:
            class SecurityAttributes(ctypes.Structure):
                _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), pointer, False)
            kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SecurityAttributes)]
            created = kernel.CreateDirectoryW(str(path), ctypes.byref(attributes))
            if not created:
                if ctypes.get_last_error() != 183:
                    raise OSError("Cannot create the protected maintenance directory")
                from installers.desktop.staging import require_trusted_owner
                require_trusted_owner(path)
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise PermissionError("Maintenance lock cannot be a reparse point")
            advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
            if not advapi.SetFileSecurityW(str(path), 0x80000004, pointer):
                raise OSError("Cannot restrict maintenance lease access")
        finally:
            kernel.LocalFree(pointer)
    else:
        path.mkdir(mode=0o700, exist_ok=True)
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o077:
            raise PermissionError("Maintenance lease directory must be root-owned and private")


def create_private_file(path, content):
    """Create a bounded privileged record with trusted owner/DACL at creation."""
    from installers.desktop.staging import _open_private_file
    with os.fdopen(_open_private_file(Path(path)), "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def create_private_directory(path):
    """Create one new privileged directory with protection present at first visibility."""
    from installers.desktop.staging import _create_private_directory
    _create_private_directory(Path(path))


def _record(path):
    """Read bounded regular lease content without following a substituted link."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 512:
            raise PermissionError("Invalid maintenance lease file")
        if os.name != "nt" and (metadata.st_uid != 0 or metadata.st_mode & 0o077):
            raise PermissionError("Maintenance lease file must be root-owned and private")
        if os.name == "nt":
            _private_owner(path)
        content = os.read(descriptor, 513).decode("ascii").splitlines()
    finally:
        os.close(descriptor)
    if len(content) != 3 or not content[0].isdigit() or not content[1].isdigit() or not re.fullmatch("[0-9a-f]{32}", content[2]):
        raise RuntimeError("Invalid maintenance lease record; inspect recovery material")
    return content


def _private_owner(path):
    """Require Windows privileged record ownership without changing an existing ACL."""
    if os.name == "nt":
        from installers.desktop.staging import require_trusted_owner
        require_trusted_owner(path)


def _participant_directory(directory, token, *, create=False):
    """Require explicit protocol evidence before permitting orphan recovery."""
    path = directory / ("participants-" + token)
    if create:
        create_private_directory(path)
        create_private_file(path / "PROTOCOL", b"2\n")
    _private_owner(path)
    _private_owner(path / "PROTOCOL")
    if path.is_symlink() or not path.is_dir() or (path / "PROTOCOL").read_text(encoding="ascii") != "2\n":
        raise RuntimeError("Legacy or unknown maintenance participants cannot be recovered graphically")
    return path


def _join(directory, token, *, owner=False):
    """Register a live privileged participant before any delegated mutation."""
    participants = _participant_directory(directory, token, create=owner)
    identity = process_identity(os.getpid())
    path = participants / f"{os.getpid()}-{identity}.participant"
    try:
        create_private_file(path, f"{os.getpid()}\n{identity}\n{token}\n".encode("ascii"))
    except FileExistsError:
        if _record(path) != [str(os.getpid()), identity, token]:
            raise RuntimeError("Maintenance participant identity changed")
        return None
    if (directory / "recovery-guard").exists():
        path.unlink()
        raise RuntimeError("Maintenance recovery is in progress; refresh after it finishes")
    return path


def _process_state(pid, identity):
    """Distinguish absence/PID reuse from inaccessible processes conservatively."""
    try:
        return "live" if process_identity(int(pid)) == identity else "dead"
    except FileNotFoundError:
        return "dead"
    except OSError as error:
        return "dead" if getattr(error, "winerror", None) in {87, 1168} else "unknown"


def _native_process_gate(token):
    """Conservatively detect orphaned native descendants without terminating them.

    POSIX children inherit the protected lease token, including package-manager
    subprocesses. Unreadable process evidence blocks recovery. Windows uses a
    fixed CIM inventory and blocks every other potential maintenance executable;
    this intentionally permits false positives instead of ignoring orphaned work.
    """
    found = []
    if os.name != "nt":
        needle = (VARIABLE + "=" + token).encode()
        for path in Path("/proc").iterdir():
            if not path.name.isdigit() or int(path.name) == os.getpid():
                continue
            try:
                environment = (path / "environ").read_bytes()
                if needle in environment.split(b"\x00"):
                    found.append({"pid": int(path.name), "state": "live", "role": "native child"})
            except FileNotFoundError:
                continue
            except OSError:
                found.append({"pid": int(path.name), "state": "unknown", "role": "unreadable native process"})
        return sorted(found, key=lambda item: item["pid"])
    buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)):
        raise RuntimeError("Cannot locate the native process inventory tool")
    executable = Path(buffer.value) / "WindowsPowerShell/v1.0/powershell.exe"
    script = "$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process | Select-Object ProcessId,Name) | ConvertTo-Json -Compress"
    process = subprocess.Popen([str(executable), "-NoProfile", "-NonInteractive", "-Command", script],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, creationflags=subprocess.CREATE_NO_WINDOW,
                               env=clean_environment())
    try:
        output, error = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        # Only this read-only inventory query is stopped, never maintenance work.
        process.kill()
        process.communicate()
        raise RuntimeError("Native process inventory did not finish; recovery is blocked")
    if process.returncode or len(output) > 2 * 1024 * 1024:
        raise RuntimeError("Native process inventory is unavailable; recovery is blocked")
    values = json.loads(output)
    if not isinstance(values, list):
        raise RuntimeError("Native process inventory is incomplete")
    allowed = {}
    current = os.environ.get(VARIABLE, "")
    if re.fullmatch("[0-9a-f]{32}", current) and current != token:
        directory = lock_directory()
        owner = _record(directory / "lease")
        if owner[2] == current and _process_state(owner[0], owner[1]) == "live":
            for path in _participant_directory(directory, current).glob("*.participant"):
                record = _record(path)
                if record[2] != current:
                    raise RuntimeError("Current maintenance participant record is invalid")
                allowed[int(record[0])] = record[1]
    for item in values:
        if not isinstance(item, dict):
            raise RuntimeError("Native process inventory is invalid")
        pid, name = item.get("ProcessId"), item.get("Name")
        if type(pid) is not int or not isinstance(name, str):
            raise RuntimeError("Native process inventory is invalid")
        if pid in {os.getpid(), process.pid}:
            continue
        if pid in allowed and _process_state(pid, allowed[pid]) == "live":
            continue
        if re.match(r"(?i)^(?:(?:python.*|pip.*|powershell|pwsh|cmd|msiexec|sc|icacls|taskkill|Dataset)\.exe|(?:setup|unins.*|MeshCore-EMS.*setup|is-.*)\.(?:exe|tmp))$", name):
            found.append({"pid": pid, "state": "unknown", "role": "potential native maintenance: " + name})
    return sorted(found, key=lambda item: item["pid"])


def _recovery_state(directory, *, ignore_guard=False):
    """Fingerprint protected recovery evidence without exposing lease tokens."""
    path = directory / "lease"
    if not path.exists():
        guard = directory / "recovery-guard"
        if guard.exists() and not ignore_guard:
            content = guard.read_bytes()
            try:
                record = _record(guard)
                participants = [{"pid": int(record[0]), "state": _process_state(record[0], record[1]), "role": "recovery"}]
                if participants[0]["state"] == "dead":
                    participants.extend(_native_process_gate(record[2]))
                safe = all(item["state"] == "dead" for item in participants)
            except (OSError, ValueError, RuntimeError):
                safe, participants = False, []
            return {"revision": hashlib.sha256(content).hexdigest(), "recoverable": safe,
                    "participants": participants, "guard_only": True,
                    "detail": "A completed lease recovery left a guard. It can be cleared only after its process and native maintenance candidates have exited."}
        return {"revision": "", "recoverable": False, "participants": [], "detail": "No interrupted maintenance lease exists."}
    evidence = {"lease": path.read_bytes().hex()}
    participants = []
    try:
        owner = _record(path)
        owner_state = _process_state(owner[0], owner[1])
        participants.append({"pid": int(owner[0]), "state": owner_state, "role": "owner"})
        group = _participant_directory(directory, owner[2])
        names = sorted(group.iterdir())
        for item in names:
            if item.name == "PROTOCOL":
                evidence[item.name] = item.read_bytes().hex()
                continue
            evidence[item.name] = item.read_bytes().hex()
            record = _record(item)
            if item.name != f"{record[0]}-{record[1]}.participant" or record[2] != owner[2]:
                raise RuntimeError("Unknown maintenance participant")
            participants.append({"pid": int(record[0]), "state": _process_state(record[0], record[1]), "role": "participant"})
        guard = directory / "recovery-guard"
        if guard.exists() and not ignore_guard:
            evidence["guard"] = guard.read_bytes().hex()
            record = _record(guard)
            participants.append({"pid": int(record[0]), "state": _process_state(record[0], record[1]), "role": "recovery"})
        if all(item["state"] == "dead" for item in participants):
            native = _native_process_gate(owner[2])
            evidence["native_processes"] = native
            participants.extend(native)
        safe = all(item["state"] == "dead" for item in participants)
        detail = "Orphaned protocol-2 lease can be released after review. Dataset locks, data, journals and receipts remain unchanged." if safe else "A maintenance participant or potential native maintenance process is live or inaccessible; recovery is blocked. Wait for it to finish or close unrelated maintenance tools. A running EMS Python service may require Stop in the native graphical Services console."
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        safe = False
        detail = "Unknown or legacy lease evidence blocks graphical recovery: " + str(error)
    revision = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    return {"revision": revision, "recoverable": safe, "participants": participants, "detail": detail}


def inspect_recovery():
    """Inspect only the fixed protected lease; never steal or remove any state."""
    directory = lock_directory()
    _secure_directory(directory)
    return _recovery_state(directory)


@contextmanager
def _recovery_mutex(directory):
    """Serialize recovery requests with a kernel lock that releases on process exit."""
    descriptor = os.open(directory / "recovery-mutex", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            if not os.fstat(descriptor).st_size:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def recover_interrupted(expected_revision):
    """Release only a reviewed orphan after proving all recorded processes exited.

    No dataset lock is removed. Legacy leases without complete participant
    tracking fail closed. Lease evidence is archived instead of discarded.
    """
    if not isinstance(expected_revision, str) or not re.fullmatch("[0-9a-f]{64}", expected_revision):
        raise ValueError("A reviewed recovery fingerprint is required")
    directory = lock_directory()
    _secure_directory(directory)
    with _THREAD_LOCK, _recovery_mutex(directory):
        state = _recovery_state(directory)
        if state["revision"] != expected_revision or not state["recoverable"]:
            raise RuntimeError("Recovery evidence changed or a participant remains live/unknown. Inspect and review again.")
        guard = directory / "recovery-guard"
        if state.get("guard_only"):
            guard.replace(directory / ("orphan-recovery-guard-" + expected_revision + "-" + secrets.token_hex(4)))
            return {"released": True, "detail": "Interrupted recovery guard archived. Dataset locks and retained state were unchanged."}
        guard.unlink(missing_ok=True)  # Only a reviewed dead recovery process can reach this step.
        token = secrets.token_hex(16)
        create_private_file(guard, f"{os.getpid()}\n{process_identity(os.getpid())}\n{token}\n".encode("ascii"))
        try:
            if not _recovery_state(directory, ignore_guard=True)["recoverable"]:
                raise RuntimeError("A delegated process appeared during recovery; no lease was released")
            archive = directory / ("orphan-" + expected_revision + "-" + secrets.token_hex(4))
            (directory / "lease").replace(archive)
        finally:
            guard.unlink(missing_ok=True)
    return {"released": True, "detail": "Orphaned maintenance lease archived. Dataset locks, retained files, receipts and operation journals were preserved. Refresh installation state before rerunning."}


@contextmanager
def _operation_lock():
    """Exclude competing maintenance, allowing verified privileged child delegation.

    Existing lease records fail closed unless this process inherited the exact
    protected token and the original process creation identity still matches.
    Tokens supplied through desktop request fields are never accepted.
    """
    directory = lock_directory()
    _secure_directory(directory)
    if (directory / "recovery-guard").exists():
        raise RuntimeError("Maintenance recovery is in progress or interrupted; inspect recovery before continuing")
    path = directory / "lease"
    previous = os.environ.get(VARIABLE)
    owned = False
    token = secrets.token_hex(16)
    try:
        create_private_file(path, f"{os.getpid()}\n{process_identity(os.getpid())}\n{token}\n".encode("ascii"))
    except FileExistsError:
        record = _record(path)
        if previous != record[2] or process_identity(int(record[0])) != record[1]:
            raise RuntimeError("Another maintenance operation or interrupted lease exists. Finish it or inspect the protected lease before recovery.")
        token = record[2]
    else:
        owned = True
    os.environ[VARIABLE] = token
    participant = _join(directory, token, owner=owned)
    try:
        yield
    finally:
        if participant is not None:
            participant.unlink(missing_ok=True)
        if previous is None:
            os.environ.pop(VARIABLE, None)
        else:
            os.environ[VARIABLE] = previous
        remaining = list(_participant_directory(directory, token).glob("*.participant"))
        if owned and not remaining and _record(path)[2] == token:
            path.unlink()


@contextmanager
def operation_lock():
    """Serialize threads as well as native processes while preserving nested leases."""
    with _THREAD_LOCK:
        with _operation_lock():
            yield


def require_consumers_stopped():
    """Fail closed before independent maintenance changes consumed data generations."""
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)):
            raise RuntimeError("Cannot verify the EMS service state")
        result = subprocess.run([str(Path(buffer.value) / "sc.exe"), "query", "MeshCoreEMS"],
                                capture_output=True, text=True, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 1060:
            return
        match = re.search(r":\s*([1-7])\s+\S+\s*$", result.stdout, re.MULTILINE)
        stopped = result.returncode == 0 and match is not None and match[1] == "1"
    else:
        result = subprocess.run(["/usr/bin/systemctl", "show", "meshcore-ems.service", "--property=LoadState", "--property=ActiveState"], capture_output=True, text=True, timeout=15)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        stopped = values.get("LoadState") == "not-found" or (result.returncode == 0 and values.get("ActiveState") in {"inactive", "failed"})
    if not stopped:
        raise RuntimeError("Stop MeshCore EMS in the graphical maintenance application before changing or removing consumed datasets. Its stopped state could not be confirmed.")
