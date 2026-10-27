"""Sequential native execution, log streaming and cancellation at package boundaries."""

import codecs
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

from .discovery import inspect, native_target, tools_base
from .planning import file_hash, make_plan
from installers.desktop.native_environment import clean_environment


def privileged():
    """Use native privilege state without collecting passwords or elevating silently."""
    if os.name == "nt":
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return os.geteuid() == 0


@contextmanager
def batch_lock(target):
    """Share the native maintenance lease; data registries retain their own lock."""
    from installers.desktop.locking import operation_lock
    with operation_lock():
        yield


class LogTail:
    """Follow newly created Windows setup helper logs with incremental decoding."""

    def __init__(self, directory):
        self.directory = directory
        self.existing = set(directory.glob("*.log"))
        self.streams = {}

    def poll(self, emit):
        for path in sorted(set(self.directory.glob("*.log")) - self.existing):
            try:
                offset, decoder = self.streams.get(path, (0, None))
                with path.open("rb") as stream:
                    stream.seek(offset)
                    data = stream.read(64 * 1024)
                    if not data:
                        continue
                    if decoder is None:
                        if len(data) < 3:
                            continue
                        encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
                        decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
                        emit("Log: " + str(path))
                    self.streams[path] = (stream.tell(), decoder)
                text = decoder.decode(data)
                if text:
                    emit(text)
            except OSError as error:
                emit("Log unavailable: " + str(error))


def run_process(operation, emit):
    """Hold the Windows privilege boundary for the entire native process lifetime."""
    if os.name != "nt":
        return _run_process(operation, emit)
    from installers.desktop.windows_trust import protected_paths
    paths = [Path(operation.command[0])]
    if operation.kind != "setup":
        paths.append(operation.prefix)
    removal = operation.prefix if operation.kind in {"uninstall", "uninstall_tools"} else None
    with protected_paths(paths, allow_removal_under=removal):
        from installers.desktop.staging import private_temporary_directory
        with private_temporary_directory("meshcore-native-") as temporary:
            return _run_process(operation, emit, temporary=temporary)


def _run_process(operation, emit, *, temporary=None):
    """Drain subprocess output and native log files without killing active operations.

    Arguments are passed as an array with shell=False. Cancellation is deliberately
    handled by the batch loop only after this function returns and verifies state.
    """
    tail = LogTail(operation.prefix / "logs")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW, "cwd": str(Path(operation.command[0]).parent)} if os.name == "nt" else {}
    environment = clean_environment(temporary)
    # Frozen Qt applications alter the dynamic-library search path. External
    # installers must load their own runtime, not the GUI's bundled libraries.
    frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
    if frozen_windows:
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    lines = queue.Queue()
    try:
        child = subprocess.Popen(operation.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, env=environment, **options)
    finally:
        if frozen_windows:
            ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)
    with child as process:
        def drain():
            try:
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                while data := process.stdout.read1(4096):
                    lines.put(decoder.decode(data))
                final = decoder.decode(b"", final=True)
                if final:
                    lines.put(final)
            finally:
                lines.put(None)
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        finished_output = False
        while process.poll() is None or not finished_output:
            try:
                text = lines.get(timeout=0.15)
                if text is None:
                    finished_output = True
                else:
                    emit(text)
            except queue.Empty:
                pass
            tail.poll(emit)
        reader.join()
        # Drain any final helper log bytes written immediately before process exit.
        for _ in range(4):
            tail.poll(emit)
        return process.returncode


@dataclass(frozen=True)
class Result:
    dataset: str
    outcome: str
    detail: str


def run_batch(plan, folder, cancel, emit, progress, *, scan=inspect, launch=run_process,
              lock=batch_lock, is_privileged=privileged, target=native_target, on_result=None):
    """Revalidate the approved plan, run serially, and verify every reported success.

    Injection points support filesystem-isolated tests. Demo takes an early path
    that never discovers the host, obtains a lock, or invokes any external program.
    Any failure stops the remaining batch and reports each unstarted item.
    """
    if plan.blocked:
        raise ValueError("Resolve all blocked items before executing the plan")
    if plan.demo:
        results = []
        for index, operation in enumerate(plan.operations):
            outcome = "cancelled" if cancel.is_set() else "simulated"
            results.append(Result(operation.dataset, outcome, "Demo only; no files changed"))
            if on_result:
                on_result(results[-1])
            emit(f"{operation.dataset}: {outcome}")
            progress(index + 1, len(plan.operations))
        return results
    if not plan.operations:
        return []
    if target() != plan.target:
        raise ValueError("Plan target does not match this computer")
    if not is_privileged():
        raise PermissionError("This operation requires native administrator authorization. Use Execute Reviewed Plan in the desktop dataset manager to open the operating system authorization dialog.")
    results = []
    with lock(plan.target):
        if (plan.root / ".datasets.lock").exists() and plan.action != "recover_selected":
            raise RuntimeError("Dataset maintenance is already locked; wait for it to finish or inspect an interrupted operation.")
        fresh = scan(plan.root, plan.target, progress=emit)
        current = make_plan(fresh, plan.action, plan.selected, folder)
        if current != plan:
            raise RuntimeError("Package, dataset or installer state changed since review. Refresh and review a new plan.")
        stopped = False
        for index, operation in enumerate(plan.operations):
            if stopped or cancel.is_set():
                results.append(Result(operation.dataset, "not run" if stopped else "cancelled", "No operation started"))
                if on_result:
                    on_result(results[-1])
                progress(index + 1, len(plan.operations))
                continue
            emit(f"Starting {index + 1}/{len(plan.operations)}: {operation.dataset} ({operation.kind})")
            progress(index, len(plan.operations))
            try:
                if (plan.root / ".datasets.lock").exists() and operation.kind != "recover_lock":
                    raise RuntimeError("Another maintenance process owns the dataset lock")
                if operation.artifact_hash:
                    artifact = operation.command[0] if plan.target == "windows-x64" else operation.command[1]
                    if file_hash(artifact) != operation.artifact_hash:
                        raise ValueError("Installer changed after plan review")
                code = launch(operation, emit)
                if code != 0:
                    raise RuntimeError(f"Native operation exited with code {code}; inspect logs under {operation.prefix / 'logs'}")
                after = scan(plan.root, plan.target, names=(operation.dataset,), progress=emit)
                state = after.collections[operation.dataset]
                if operation.kind == "recover_lock":
                    if (plan.root / ".datasets.lock").exists() or after.registry != fresh.registry:
                        raise RuntimeError("Dataset lock recovery did not clear only the reviewed lock while retaining the registry")
                    detail = "Reviewed orphaned lock archived; dataset files and registry were retained. Data validation remains a separate operation."
                elif operation.kind == "uninstall":
                    entry = after.registry.get("datasets", {}).get(operation.dataset, {})
                    if state.package.state != "missing" or entry.get("active") or entry.get("previous"):
                        raise RuntimeError("Removal exit code was zero but package/data records still indicate installation")
                    detail = "Removed; modified, unowned or legacy files may remain. Review native logs."
                elif operation.kind == "uninstall_tools":
                    if state.package.state != "missing" or after.registry != fresh.registry:
                        raise RuntimeError("Tools-only uninstall did not retain exactly the reviewed dataset registry")
                    if state.data != fresh.collections[operation.dataset].data:
                        raise RuntimeError("Retained dataset verification changed after tools-only uninstall")
                    detail = "Maintenance package removed; all dataset selections and data retained. Reinstall tools for future maintenance."
                else:
                    if state.package.state != "ready" or state.data != "valid" or state.package.root != plan.root:
                        raise RuntimeError("Installation exit code was zero but tools/data did not pass verification: " + state.detail)
                    detail = "Package records and active data receipt hashes verified"
                results.append(Result(operation.dataset, "succeeded", detail))
            except Exception as error:
                stopped = True
                results.append(Result(operation.dataset, "failed", str(error)))
                emit("FAILED: " + str(error))
            if on_result:
                on_result(results[-1])
            progress(index + 1, len(plan.operations))
    return results
