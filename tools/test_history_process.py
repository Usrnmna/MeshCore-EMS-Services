"""Subprocess isolation and shutdown contracts for optional history reads."""
import errno
import io
import json
import os
import socket
import signal
from pathlib import Path
import subprocess
import sys
import threading
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.test_history_backend import request


class HistoryProcessTests(unittest.TestCase):
    def process(self):
        from installers.desktop import history_process
        return history_process

    def test_fixed_dispatch_rejects_unknown_modes(self):
        process = self.process()
        with self.assertRaises(ValueError):
            process.helper_command("shell")
        command = process.helper_command("read")
        self.assertEqual(command[-1], "--history-read")
        self.assertNotIn("-c", command)

    def test_installer_exit_does_not_wait_for_stalled_launch(self):
        source = '''
import threading, time
import sys
from unittest.mock import patch
from installers.desktop.history_process import HistoryReadSession
from installers.datasets.gui.discovery import native_target
started = threading.Event()
target = native_target()
def stalled(*args, **kwargs):
    started.set()
    time.sleep(60)
with patch('installers.desktop.history_process.subprocess.Popen', stalled):
    session = HistoryReadSession()
    session.start(dict(schema=1, kind='history', target=target, action='catalog', query={}))
    assert started.wait(2)
    session.cancel_nowait()
'''
        result = subprocess.run([sys.executable, "-B", "-c", source], capture_output=True, timeout=4)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_cancellation_refuses_replacement_until_owned_helper_exits(self):
        process = self.process()
        gate = threading.Event()
        entered = threading.Event()
        value = request()
        def held(*args, **kwargs):
            entered.set()
            gate.wait(3)
            raise RuntimeError("held launch")
        with patch.object(process.subprocess, "Popen", held):
            session = process.HistoryReadSession()
            self.assertTrue(session.start(value))
            self.assertTrue(entered.wait(1))
            first_generation = session.poll()["generation"]
            session.cancel_nowait()
            self.assertTrue(session.busy)
            self.assertFalse(session.start(value))
            self.assertGreater(session.poll()["generation"], first_generation)
            gate.set()
            deadline = time.monotonic() + 2
            while session.busy and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(session.busy)
            self.assertEqual(session.poll()["state"], "cancelled")

    def test_read_deadline_terminates_owned_stalled_process(self):
        process = self.process()
        original = subprocess.Popen
        owned = []
        def launch(*args, **kwargs):
            child = original([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
            owned.append(child)
            return child
        before = time.monotonic()
        with patch.object(process.subprocess, "Popen", side_effect=launch), patch.object(process, "READ_SECONDS", .15), patch.object(process, "CANCEL_GRACE", .1):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                process.supervise_read(request(), threading.Event())
        self.assertLess(time.monotonic() - before, 2)
        self.assertIsNotNone(owned[0].poll())

    def test_blocked_request_pipe_obeys_deadline_and_cancel_without_releasing_child(self):
        process = self.process()
        # Escaped controls remain a legal 4096-byte selector but serialize to
        # more than 24 KiB, filling the deliberately small unread input pipe.
        value = request("page", channel_id="public", sender="\x01" * 4096)
        original = subprocess.Popen
        for mode, cancellation in (("read", False), ("read", True), ("session", True)):
            with self.subTest(mode=mode, cancellation=cancellation):
                owned = []
                finished = threading.Event()
                cancel = threading.Event()
                errors = []
                def launch(*args, **kwargs):
                    if os.name != "nt":
                        kwargs["pipesize"] = 4096
                    child = original([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
                    owned.append(child)
                    return child
                def exchange():
                    try:
                        process._exchange(mode, value, cancel, 5 if cancellation else .15)
                    except Exception as error:
                        errors.append(str(error))
                    finally:
                        finished.set()
                with patch.object(process.subprocess, "Popen", side_effect=launch), patch.object(process, "CANCEL_GRACE", .05):
                    worker = threading.Thread(target=exchange, daemon=True)
                    worker.start()
                    if cancellation:
                        time.sleep(.15)
                        cancel.set()
                    bounded = finished.wait(1.5)
                    # Always reap this test's process even against the broken
                    # implementation; the assertion records the missed deadline.
                    for child in owned:
                        if child.poll() is None:
                            child.kill()
                        child.wait(timeout=2)
                    worker.join(2)
                self.assertTrue(bounded, "Supervisor blocked writing a request to an unread pipe")
                self.assertEqual(errors, ["History read cancelled" if cancellation else "History read deadline exceeded"])

    def test_request_pipe_sends_all_chunks_without_changing_selector(self):
        process = self.process()
        value = request("page", channel_id="public", sender="\x01" * 4096)
        original = subprocess.Popen
        def launch(*args, **kwargs):
            source = "import json,sys; r=json.loads(sys.stdin.buffer.readline()); print(json.dumps({'ok':True,'value':{'sender':r['query']['sender']}}))"
            if os.name != "nt":
                kwargs["pipesize"] = 4096
            return original([sys.executable, "-c", source], **kwargs)
        with patch.object(process.subprocess, "Popen", side_effect=launch):
            result = process._exchange("read", value, threading.Event(), 2)
        self.assertEqual(result, {"sender": "\x01" * 4096})

    def test_cancelled_response_reader_handles_pipe_close_without_thread_failure(self):
        process = self.process()
        value = request()
        original = subprocess.Popen
        for mode in ("read", "session"):
            with self.subTest(mode=mode):
                cancel = threading.Event()
                closed = threading.Event()
                readers = []
                owned = []
                failures = []

                def launch(*args, **kwargs):
                    # Emit a valid reply, then retain the parent's input lease.
                    source = "import sys; sys.stdin.buffer.readline(); print('{\"ok\":true,\"value\":{}}', flush=True); sys.stdin.buffer.read()"
                    child = original([sys.executable, "-c", source], **kwargs)
                    owned.append(child)
                    read_stdout = child.stdout.read
                    close_stdout = child.stdout.close

                    def delayed_read(size):
                        chunk = read_stdout(size)
                        if not readers:
                            readers.append(threading.current_thread())
                            cancel.set()
                            # Reproduce a descheduled reader: cleanup closes the
                            # real pipe before its next FileIO.read call.
                            if not closed.wait(3):
                                raise TimeoutError("Supervisor did not close the response pipe")
                        return chunk

                    def release_reader():
                        close_stdout()
                        closed.set()

                    child.stdout.read = delayed_read
                    child.stdout.close = release_reader
                    return child

                def record_failure(failure):
                    failures.append((failure.exc_type, str(failure.exc_value)))

                with patch.object(process.subprocess, "Popen", side_effect=launch), \
                     patch.object(threading, "excepthook", record_failure):
                    try:
                        with self.assertRaisesRegex(RuntimeError, "History read cancelled"):
                            process._exchange(mode, value, cancel, 5)
                    finally:
                        closed.set()
                        for reader in readers:
                            reader.join(2)  # Test cleanup; production remains nonblocking.
                    self.assertEqual(len(readers), 1)
                    self.assertFalse(readers[0].is_alive())
                    self.assertEqual(failures, [])
                    self.assertEqual(owned[0].returncode, 0)
                    self.assertTrue(owned[0].stdout.closed)

    def test_completed_child_cannot_return_success_after_launch_deadline(self):
        process = self.process()
        original = subprocess.Popen
        def launch(*args, **kwargs):
            child = original([sys.executable, "-c", "print('{\"ok\":true,\"value\":{}}')"], **kwargs)
            child.wait(timeout=2)
            time.sleep(.1)
            return child
        with patch.object(process.subprocess, "Popen", side_effect=launch):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                process._exchange("read", request(), threading.Event(), .05)

    @unittest.skipIf(os.name == "nt", "POSIX process-group ownership")
    def test_read_cleanup_terminates_stalled_descendant_after_deadline_or_leader_exit(self):
        process = self.process()
        original = subprocess.Popen
        for finish in (False, True):
            with self.subTest(reader_finishes=finish), tempfile.TemporaryDirectory() as temporary:
                pidfile = Path(temporary) / "descendant.pid"
                source = '''
import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(sys.argv[1]).write_text(str(child.pid))
time.sleep(.08)
if sys.argv[2] == 'finish':
    print('{"ok":true,"value":{}}')
else:
    time.sleep(60)
'''
                def launch(*args, **kwargs):
                    return original([sys.executable, "-c", source, str(pidfile), "finish" if finish else "stall"], **kwargs)
                descendant = None
                try:
                    with patch.object(process.subprocess, "Popen", side_effect=launch), patch.object(process, "CANCEL_GRACE", .05):
                        if finish:
                            self.assertEqual(process._exchange("read", request(), threading.Event(), 2), {})
                        else:
                            with self.assertRaisesRegex(RuntimeError, "deadline"):
                                process._exchange("read", request(), threading.Event(), .3)
                    descendant = int(pidfile.read_text())
                    until = time.monotonic() + 1
                    while time.monotonic() < until:
                        stat = Path(f"/proc/{descendant}/stat")
                        if not stat.exists() or stat.read_text().split(")", 1)[1].split()[0] == "Z":
                            break
                        time.sleep(.02)
                    else:
                        self.fail("Owned read descendant survived supervisor cleanup")
                finally:
                    if descendant is None and pidfile.exists():
                        descendant = int(pidfile.read_text())
                    if descendant is not None:
                        try:
                            os.kill(descendant, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_response_budget_rejects_unbounded_child_output(self):
        process = self.process()
        original = subprocess.Popen
        def launch(*args, **kwargs):
            return original([sys.executable, "-c", "import sys; sys.stdout.write('x' * (3 * 1024 * 1024))"], **kwargs)
        with patch.object(process.subprocess, "Popen", side_effect=launch):
            with self.assertRaisesRegex(RuntimeError, "response"):
                process.supervise_read(request(), threading.Event())

    def test_cancel_keeps_session_supervisor_alive_until_cleanup_finishes(self):
        process = self.process()
        value = request()
        original = subprocess.Popen
        owned = []
        # This fixed test helper represents cleanup after its parent pipe closes.
        def launch(*args, **kwargs):
            source = "import sys,time; sys.stdin.buffer.readline(); sys.stdin.buffer.read(); time.sleep(.35)"
            child = original([sys.executable, "-c", source], **kwargs)
            owned.append(child)
            return child
        with patch.object(process.subprocess, "Popen", side_effect=launch), patch.object(process, "CANCEL_GRACE", .02):
            session = process.HistoryReadSession()
            session.start(value)
            until = time.monotonic() + 2
            while not owned and time.monotonic() < until:
                time.sleep(.01)
            session.cancel_nowait()
            time.sleep(.15)
            self.assertTrue(session.busy)
            self.assertIsNone(owned[0].poll())
            while session.busy and time.monotonic() < until:
                time.sleep(.01)
            self.assertFalse(session.busy)
            self.assertEqual(owned[0].returncode, 0)

    def test_entry_points_dispatch_helpers_before_qt(self):
        from installers.desktop import service_main
        from installers.datasets.gui import main
        for entry in (service_main.main, main.main):
            with patch("installers.desktop.history_process.helper_main", return_value=37) as helper:
                self.assertEqual(entry(["--history-read"]), 37)
                self.assertEqual(helper.call_args.args, ("read",))

    def test_real_helper_exits_without_buffered_stdin_shutdown_deadlock(self):
        process = self.process()
        child = subprocess.Popen(process.helper_command("read"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        child.stdin.write(json.dumps(dict(request(), action="invalid")).encode() + b"\n")
        child.stdin.flush()
        child.wait(timeout=4)
        child.stdin.close()
        self.assertEqual(child.returncode, 1)
        self.assertFalse(json.loads(child.stdout.read())["ok"])
        self.assertNotIn(b"Fatal Python", child.stderr.read())
        child.stdout.close()
        child.stderr.close()

    def test_lost_response_pipe_does_not_escape_to_windowed_bootloader(self):
        process = self.process()
        for buffered in (False, True):
            for error_number in (errno.EPIPE, errno.EINVAL):
                with self.subTest(buffered=buffered, error_number=error_number):
                    class DisconnectedPipe(io.RawIOBase):
                        def writable(self):
                            return True

                        def write(self, data):
                            raise OSError(error_number, "Synthetic disconnected parent pipe")

                    pipe = DisconnectedPipe()
                    output = io.TextIOWrapper(io.BufferedWriter(pipe) if buffered else pipe)
                    # Invalid input exercises final response delivery without
                    # discovering a service or starting a parent-watch thread.
                    incoming = io.TextIOWrapper(io.BytesIO(b"{}\n"))
                    escaped = None
                    status = None
                    closed_after_delivery = False
                    try:
                        with patch.object(process.sys, "stdin", incoming), patch.object(process.sys, "stdout", output):
                            try:
                                status = process.helper_main("read")
                            except OSError as error:
                                escaped = error
                            closed_after_delivery = output.closed
                    finally:
                        incoming.close()
                        try:
                            output.close()
                        except OSError:
                            pass
                    self.assertIsNone(escaped, "Output failure escaped to the frozen windowed exception handler")
                    self.assertEqual(status, 1)
                    self.assertTrue(closed_after_delivery, "Shutdown must not retry a failed buffered flush")

    def test_history_authorization_rejects_late_or_lost_parent_before_read(self):
        from installers.desktop import authorization
        from types import SimpleNamespace
        process = self.process()
        for expires in (time.time() - 1, time.time() + 121):
            session = SimpleNamespace(read_private=lambda name: json.dumps(dict(port=9, token="a" * 64, expires=expires)).encode())
            with self.assertRaises(RuntimeError):
                authorization.history_parent(session)
        session = SimpleNamespace(read_private=lambda name: json.dumps(dict(port=9, token="a" * 64, expires=time.time() + 60)).encode())
        with self.assertRaises(RuntimeError):
            authorization.history_parent(session)

    def test_history_kind_validated_before_native_authorization(self):
        from installers.desktop import authorization
        self.assertEqual(authorization.validate_envelope(request()), request())
        with self.assertRaises(ValueError):
            authorization.validate_envelope(dict(request(), command="shell"))

    def test_authorized_history_private_response_roundtrip_and_cleanup(self):
        from installers.desktop import authorization
        captured = []
        original = subprocess.Popen
        def launch(command):
            captured.append(Path(command[-1]).parent)
            source = '''
import sys
from unittest.mock import patch
from installers.desktop.authorization import worker_main
with patch('installers.desktop.authorization.worker_privileged', return_value=True), patch('installers.desktop.history_backend.perform', return_value={'messages': [{'text': 'PRIVATE BODY'}]}):
    status = worker_main(sys.argv[1])
    from pathlib import Path
    import os
    folder = Path(sys.argv[1]).parent
    assert not (folder / 'events.jsonl').exists()
    if os.name != 'nt':
        assert (folder / 'result.json').stat().st_mode & 0o777 == 0o600
    raise SystemExit(status)
'''
            return original([sys.executable, "-B", "-c", source, command[-1]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with patch.object(authorization, "launch_worker", side_effect=launch):
            result = authorization.run_authorized(request(), lambda _: self.fail("History must not emit events"), threading.Event())
        self.assertEqual(result, {"messages": [{"text": "PRIVATE BODY"}]})
        self.assertEqual(len(captured), 1)
        self.assertFalse(captured[0].exists())

    def test_authorized_supervisor_terminates_its_child_after_parent_pipe_loss(self):
        from installers.desktop import authorization
        from types import SimpleNamespace
        process = self.process()
        value = request()
        parent, child_socket = socket.socketpair()
        child_socket.settimeout(.05)
        original = subprocess.Popen
        owned = []
        def launch(*args, **kwargs):
            child = original([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
            owned.append(child)
            return child
        with tempfile.TemporaryDirectory() as temporary:
            result_path = Path(temporary) / "result.json"
            session = SimpleNamespace(request=value, cancelled=lambda: False,
                                      open_output=lambda name: os.open(result_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            with patch.object(authorization, "history_parent", return_value=child_socket), \
                 patch.object(process.subprocess, "Popen", side_effect=launch), patch.object(process, "CANCEL_GRACE", .05):
                worker = threading.Thread(target=authorization._dispatch_history_session, args=(session,), daemon=True)
                worker.start()
                until = time.monotonic() + 3
                while not owned and time.monotonic() < until:
                    time.sleep(.01)
                parent.close()
                worker.join(2)  # Test cleanup; no production/UI join exists.
                self.assertFalse(worker.is_alive())
                self.assertIsNotNone(owned[0].poll())
                self.assertFalse(json.loads(result_path.read_text())["ok"])

    def test_cleanup_failure_does_not_report_success(self):
        from installers.desktop import authorization
        from types import SimpleNamespace
        directories = []
        original = authorization.shutil.rmtree
        def refuse(path):
            directories.append(Path(path))
            raise OSError("cleanup refused")
        try:
            with patch.object(authorization, "launch_worker", return_value=SimpleNamespace(poll=lambda: 126)), \
                 patch.object(authorization.shutil, "rmtree", side_effect=refuse):
                with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                    authorization.run_authorized(request(), lambda _: None, threading.Event())
        finally:
            for directory in directories:
                original(directory)

    def test_authorization_refusal_never_returns_empty_success(self):
        from installers.desktop import authorization
        from types import SimpleNamespace
        with patch.object(authorization, "launch_worker", return_value=SimpleNamespace(poll=lambda: 126)):
            with self.assertRaisesRegex(RuntimeError, "cancelled or unavailable"):
                authorization.run_authorized(request(), lambda _: self.fail("private output"), threading.Event())

    def test_authorization_lifetime_bounds_stalled_native_launch(self):
        from installers.desktop import authorization
        process = self.process()
        gate = threading.Event()
        def stalled(command):
            gate.wait(2)
            raise RuntimeError("closed test authorization")
        before = time.monotonic()
        with patch.object(authorization, "launch_worker", side_effect=stalled), patch.object(process, "AUTH_SECONDS", .15):
            with self.assertRaisesRegex(RuntimeError, "expired"):
                authorization.run_authorized(request(), lambda _: None, threading.Event())
        self.assertLess(time.monotonic() - before, 1)
        gate.set()

    def test_installer_exit_while_authorization_and_cleanup_are_stalled(self):
        for phase in ("authorization", "cleanup"):
            source = '''
import threading, time, sys
from unittest.mock import patch
from installers.desktop.history_process import HistoryReadSession
from installers.datasets.gui.discovery import native_target
from installers.desktop.authorization import run_authorized_history
from types import SimpleNamespace
value = dict(schema=1, kind='history', target=native_target(), action='catalog', query={})
entered = threading.Event()
def stalled(*args, **kwargs):
    entered.set()
    time.sleep(60)
def exchange(mode, request, cancel, lifetime):
    return run_authorized_history(request, cancel)
phase = PHASE
launch = stalled if phase == 'authorization' else lambda command: SimpleNamespace(poll=lambda: 126)
with patch('installers.desktop.history_process._exchange', exchange), patch('installers.desktop.authorization.launch_worker', launch), patch('installers.desktop.authorization.tempfile.mkdtemp', return_value=sys.argv[1]), patch('installers.desktop.authorization.shutil.rmtree', stalled if phase == 'cleanup' else lambda path: None):
    session = HistoryReadSession()
    session.start(value)
    assert entered.wait(2)
    session.cancel_nowait()
'''.replace("PHASE", repr(phase))
            with self.subTest(phase=phase):
                with tempfile.TemporaryDirectory() as temporary:
                    result = subprocess.run([sys.executable, "-B", "-c", source, temporary], capture_output=True, timeout=4)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == "__main__":
    unittest.main()
