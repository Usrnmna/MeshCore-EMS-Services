"""Bounded packaged-GUI verification using only generated synthetic history.

The separate smoke helper never discovers an installation or accepts a database,
module, executable, credential, or SQL path. Production helper flags retain their
fixed installed-path and trust checks. Fixtures use the reader bundled with the
application and are removed after each read.
"""
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time

SYNTHETIC_TEXT = "<b>synthetic markup remains text</b>\nSnow: \u96ea; symbols: % _ ' \""
SMOKE_MODES = {"read", "session", "orphan"}


@contextmanager
def replace_attribute(owner, name, value):
    """Temporarily substitute one smoke boundary, restoring it even after failure."""
    original = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, original)


def smoke_command(mode):
    """Launch only a fixed smoke mode through this application's real entry point."""
    if mode not in SMOKE_MODES:
        raise ValueError("Unknown history smoke helper")
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--history-smoke-helper", mode]
    return [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--history-smoke-helper", mode]


def request(action="catalog", **query):
    """Create the same bounded request envelope accepted by production helpers."""
    from installers.datasets.gui.discovery import native_target
    return dict(schema=1, kind="history", target=native_target(), action=action, query=query)


@contextmanager
def fixture_reader():
    """Load the version-owned reader and create a disposable known SQLite schema."""
    from installers.desktop import history_backend as backend
    from installers.desktop.service_backend import bundled_history_package
    from installers.datasets.gui.discovery import native_target
    source = bundled_history_package(native_target()) / "channel_history.py"
    name = "_packaged_smoke_history_reader"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="mc-ems-history-smoke-") as temporary:
            database = Path(temporary) / "synthetic.sqlite3"
            now = datetime.now(timezone.utc)
            anchor = now.replace(minute=0, second=0, microsecond=0) - timedelta(minutes=10)
            with closing(sqlite3.connect(database)) as writer, writer:
                writer.executescript("""
                    PRAGMA user_version=1;
                    CREATE TABLE channel_messages (
                        event_id TEXT PRIMARY KEY, received_at_us INTEGER,
                        channel_id TEXT, channel_name TEXT, channel_identity TEXT,
                        channel_index INTEGER, binding_source TEXT, binding_observed_at_us INTEGER,
                        text TEXT, sender TEXT, source_message_id_json TEXT, sender_timestamp INTEGER,
                        payload_json TEXT, attributes_json TEXT, device_json TEXT, reception_json TEXT);
                """)
                rows = []
                for index in range(205):
                    received = anchor - timedelta(seconds=index)
                    rows.append((f"public-{index:03}", module._us(received), "public", "Synthetic public",
                        "synthetic-identity", 0, "passive_snapshot", module._us(received),
                        SYNTHETIC_TEXT if index == 0 else f"Fixture: message {index}",
                        "synthetic-sender" if index % 2 else None, None, 123,
                        json.dumps({"data": {"encoding": "hex", "data": "00ff"}}), "{}", "{}", "{}"))
                for event, channel, received in (("private-one", "private", anchor),
                        ("previous-one", "previous", anchor),
                        ("expired", "public", now - timedelta(hours=25)),
                        ("future", "public", now + timedelta(hours=2))):
                    row = list(rows[0]); row[0:4] = [event, module._us(received), channel, "Synthetic " + channel]
                    rows.append(tuple(row))
                writer.executemany("INSERT INTO channel_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            original = database.read_bytes()

            def read(value):
                backend.validate_history_request(value)
                channel = value["query"].get("channel_id")
                failures = {"missing": "History not created yet", "schema": "Unsupported history schema",
                            "unavailable": "History database unavailable"}
                if channel in failures:
                    raise RuntimeError(failures[channel])
                if channel == "denied":
                    raise PermissionError("Synthetic access denial")
                if value["action"] == "catalog":
                    channels = backend._serialize(module.list_recorded_channels(database))
                    result = dict(settings={"enabled": True, "channel_id": "public"},
                        service_state="synthetic", database_path="(isolated synthetic fixture)",
                        availability="available", channels=channels, observed_at=now.isoformat(),
                        latest_received_at=max(item["latest_received_at"] for item in channels))
                else:
                    query = dict(value["query"])
                    for key in ("start", "end"):
                        if query.get(key) is not None:
                            query[key] = backend._date(query[key])
                    result = backend._serialize(module.read_message_page(database, **query))
                if database.read_bytes() != original:
                    raise AssertionError("A history read changed the synthetic database")
                return result

            yield read
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def helper_main(mode):
    """Exercise real helper framing/supervision with only a fixed internal fixture."""
    if mode not in SMOKE_MODES:
        raise ValueError("Unknown history smoke helper")
    from installers.desktop import history_backend as backend, history_process as process
    process.ensure_helper_stdio()
    with ExitStack() as stack:
        stack.enter_context(replace_attribute(process, "helper_command", smoke_command))
        if mode == "orphan":
            # Returning exits this process while its app-owned daemon is busy.
            # The external verifier checks that the owned session then exits.
            spawned = []
            launch = process.subprocess.Popen
            def observe(*args, **kwargs):
                child = launch(*args, **kwargs)
                spawned.append(child)
                return child
            stack.enter_context(replace_attribute(process.subprocess, "Popen", observe))
            session = process.HistoryReadSession()
            session.start(request("page", channel_id="stall"))
            until = time.monotonic() + 5
            while not spawned and time.monotonic() < until:
                time.sleep(.01)
            if not spawned:
                raise RuntimeError("Synthetic session did not start")
            time.sleep(.5)
            sys.stdout.buffer.write(json.dumps({"ok": True, "value": {"owned_pid": spawned[0].pid}}).encode())
            sys.stdout.buffer.flush()
            return 0
        def read(value):
            backend.validate_history_request(value)
            if value["query"].get("channel_id") == "stall":
                # Stall before creating temporary storage so forced termination
                # cannot leave a fixture behind. No external process exists.
                time.sleep(30)
                raise RuntimeError("History read deadline exceeded")
            with fixture_reader() as fixture:
                return fixture(value)
        stack.enter_context(replace_attribute(backend, "read_installed", read))
        # A synthetic denial may verify error reporting, but must never display
        # native authorization. Ordinary read/session requests are unchanged.
        from installers.desktop import authorization
        def deny_authorization(*args, **kwargs):
            raise RuntimeError("History authorization cancelled or unavailable")
        stack.enter_context(replace_attribute(authorization, "run_authorized", deny_authorization))
        return process.helper_main(mode)


@contextmanager
def demo_guard():
    """Fail and record any host discovery or native operation during a GUI smoke."""
    from installers.datasets.gui import discovery, privileges, window
    from installers.desktop import authorization, history_backend, history_state, history_window
    from installers.desktop import service_backend, unified_backend
    violations = []
    boundaries = ((discovery, ("inspect",)), (privileges, ("inspect_with_authorization", "execute_reviewed", "service_state")),
        (window, ("inspect", "inspect_with_authorization", "execute_reviewed")),
        (unified_backend, ("inspect",)), (history_backend, ("read_installed",)),
        (history_state, ("service_state",)), (history_window, ("native_session",)),
        (authorization, ("run_authorized", "launch_worker")),
        (service_backend, ("installed_paths", "snapshot", "control", "configure_installed", "validate_installed", "check_connection", "run_native")))
    with ExitStack() as stack:
        for module, names in boundaries:
            for name in names:
                label = module.__name__ + "." + name
                def denied(*args, _label=label, **kwargs):
                    violations.append(_label)
                    raise AssertionError("Smoke attempted native access: " + _label)
                stack.enter_context(replace_attribute(module, name, denied))
        yield violations


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


class FixtureSession:
    """Immediate fixture-backed session for deterministic presentation checks."""
    busy = False
    generation = 0
    def __init__(self, read):
        self.read = read
        self.outcome = None
        self.requests = []

    def start(self, value):
        self.generation += 1
        self.requests.append(value)
        try:
            self.outcome = {"state": "complete", "result": self.read(value), "generation": self.generation}
        except Exception as error:
            from installers.desktop.history_process import safe_error
            self.outcome = {"state": "failed", "error": safe_error(error), "generation": self.generation}
        return True

    def poll(self):
        return self.outcome

    def cancel_nowait(self):
        self.generation += 1
        self.outcome = {"state": "cancelled", "generation": self.generation}


def _settings_checks(widget):
    """Exercise displayed source choices without applying installation settings."""
    from PyQt6.QtWidgets import QLineEdit
    registry = {"public": {"name": "Synthetic public", "type": "public", "mqtt_export": True},
                "private": {"name": "Synthetic private", "type": "private", "mqtt_export": False}}
    widget.load({"enabled": False}, registry, True)
    _require(widget.override() is None, "Untouched settings must preserve saved recording")
    widget.applyCheck.setChecked(True)
    _require(widget.override() == {"enabled": False}, "Explicit disable was not preserved")
    widget.enabledCheck.setChecked(True)
    for channel in registry:
        widget.serviceChannel.setCurrentIndex(widget.serviceChannel.findData(channel))
        _require(widget.override() == {"enabled": True, "channel_id": channel}, "Service source selection failed")
    widget.sourceCombo.setCurrentIndex(widget.sourceCombo.findData("recording"))
    widget.channelId.setText("synthetic_archive")
    widget.channelName.setText("Synthetic archive")
    for kind in ("public", "private"):
        widget.channelType.setCurrentText(kind)
        widget.secretEnv.setText("MESHCORE_CHANNEL_KEY_SYNTHETIC")
        override = widget.override()
        _require(override["channel"]["type"] == kind and override["channel"]["mqtt_export"] is False,
                 "Recording-only source must preserve its type and disable MQTT export")
    _require(widget.secretValue.echoMode() == QLineEdit.EchoMode.Password, "Private input is not masked")
    _require(widget.credential_overrides() == {}, "Blank synthetic key must not create credentials")


def _viewer_checks(application, target, checks):
    """Verify real rendering, page replacement, UTC, expiry, and failure surfaces."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QAbstractItemView
    from installers.desktop import history_window as gui
    with fixture_reader() as read:
        session = FixtureSession(read)
        viewer = gui.HistoryWindow(target, session=session)
        viewer.show(); viewer.poll_result()
        try:
            _require(viewer.channel.currentData() == "public", "Saved channel was not selected")
            _require(viewer.channel.count() == 3, "Current/previous recorded channel catalog failed")
            viewer.refresh(); viewer.poll_result()
            _require(viewer.table.rowCount() == 200 and viewer.older_button.isEnabled(), "First bounded page failed")
            viewer.table.selectRow(0); application.processEvents()
            _require(SYNTHETIC_TEXT in viewer.detail.toPlainText(), "Plain text content changed")
            _require('"data": "00ff"' in viewer.detail.toPlainText() and '"sender_timestamp": 123' in viewer.detail.toPlainText(),
                     "Supplied metadata changed")
            _require(viewer.detail.isReadOnly() and viewer.table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers,
                     "Viewer is editable")
            _require(all(field.timeSpec() == Qt.TimeSpec.UTC for field in (viewer.start_time, viewer.end_time)),
                     "Custom time controls do not use UTC")
            _require(viewer.table.horizontalHeaderItem(0).text() == "Received (UTC)", "Reception label lost UTC")
            checks.extend(["read_only_plain_text", "metadata_preserved", "utc_controls", "bounded_first_page"])
            viewer.load_older(); viewer.poll_result()
            _require(viewer.table.rowCount() == 5 and not viewer.older_button.isEnabled(), "Older page must replace the first page")
            _require(session.requests[-1]["query"].get("cursor"), "Paging did not use the opaque cursor")
            checks.append("keyset_paging")
            viewer.refresh(); viewer.poll_result()
            viewer._submit("page", {"channel_id": "schema"}); viewer.poll_result()
            _require("stale" in viewer.status.text().lower() and "Unsupported history schema" in viewer.status.text(),
                     "Failed refresh must mark the retained page stale")
            for channel, label in (("missing", "History not created yet"), ("denied", "History access denied"),
                                   ("unavailable", "History database unavailable")):
                viewer._rows = []; viewer._draw()
                viewer._submit("page", {"channel_id": channel}); viewer.poll_result()
                _require(label in viewer.status.text() and not viewer.table.rowCount(), "Failure was presented as an empty success")
            checks.append("failure_and_stale_states")
            viewer.refresh(); viewer.poll_result(); viewer.table.selectRow(0)
            application.processEvents()
            with replace_attribute(gui, "utc_now", lambda: datetime.now(timezone.utc) + timedelta(days=2)):
                viewer.expire_rows()
            _require(viewer.table.rowCount() == 0 and not viewer.detail.toPlainText(), "Expired content remained visible")
            checks.append("display_expiration")
        finally:
            viewer.close()


def run_gui_checks(application, window, violations):
    """Check the real demo form and separate history window in the running app."""
    from PyQt6.QtWidgets import QLabel
    from installers.desktop import history_window as gui, history_process as process
    from installers.desktop.image_smoke import loaded_image_libraries, verify_image_decoding
    image_decoding = verify_image_decoding()
    image_libraries = loaded_image_libraries()
    checks = [image_format + "_decode_pixels" for image_format in image_decoding]
    if hasattr(window, "datasetTree"):
        _require(window.datasetTree.topLevelItemCount() == 8, "Dataset form was not populated")
        checks.append("eight_dataset_collections")
    visible = [window.windowTitle()] + [label.text() for label in window.findChildren(QLabel) if label.isVisible()]
    service = getattr(window, "serviceForm", window)
    if hasattr(service, "historySettings"):
        _require(service.historySettings is not None, "History settings failed to load")
        _settings_checks(service.historySettings)
        checks.extend(["public_private_settings", "service_and_recording_sources", "explicit_disable", "masked_private_input"])
        service.open_history()
        demo = service.historyWindow
        _require(demo is not None, "Demo viewer did not open")
        demo.refresh(); demo.poll_result()
        _require(demo.table.rowCount() == 1, "Synthetic demo viewer did not render")
        demo.close()
        checks.append("demo_history_no_host_access")
    _viewer_checks(application, window.target, checks)
    with replace_attribute(process, "helper_command", smoke_command):
        session = process.HistoryReadSession()
        viewer = gui.HistoryWindow(window.target, session=session)
        until = time.monotonic() + 15
        while session.busy and time.monotonic() < until:
            application.processEvents(); time.sleep(.01)
        viewer.poll_result()
        _require(session.poll().get("state") == "complete", "Packaged synthetic session did not complete")
        session.start(request("page", channel_id="stall"))
        time.sleep(.25)
        started = time.monotonic(); viewer.close()
        _require(time.monotonic() - started < .25, "Viewer close waited for a reader")
        until = time.monotonic() + 10
        while session.busy and time.monotonic() < until:
            application.processEvents(); time.sleep(.01)
        _require(not session.busy, "Cancelled packaged reader did not finish")
        checks.extend(["packaged_session_dispatch", "bounded_cancel", "nonblocking_viewer_close"])
    _require(not violations, "Demo attempted native access")
    checks.append("demo_no_host_discovery_or_native_operations")
    return {"schema": 1, "ok": True, "frozen": bool(getattr(sys, "frozen", False)),
            "target": window.target, "window": type(window).__name__, "visible_text": visible, "checks": checks,
            "native_access_attempts": violations, "image_decoding": image_decoding,
            "image_libraries": image_libraries}


def schedule_gui_smoke(application, window, report_path, violations):
    """Wait for initial demo discovery, emit a bounded JSON result, and exit."""
    from PyQt6.QtCore import QTimer
    started = time.monotonic()
    timer = QTimer(application)

    def finish(report, status):
        timer.stop()
        if report_path is not None:
            Path(report_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        elif sys.stdout is not None:
            print(json.dumps(report))
        application.exit(status)

    def check():
        if window.task is not None:
            if time.monotonic() - started > 30:
                finish({"schema": 1, "ok": False, "error": "Demo form initialization timed out"}, 2)
            return
        timer.stop()
        try:
            report = run_gui_checks(application, window, violations)
        except Exception as error:
            report = {"schema": 1, "ok": False, "error": str(error), "native_access_attempts": violations}
        finish(report, 0 if report["ok"] else 1)

    timer.timeout.connect(check)
    timer.start(100)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    if len(sys.argv) != 3 or sys.argv[1] != "--history-smoke-helper":
        raise SystemExit("Only a fixed synthetic history smoke mode is accepted")
    raise SystemExit(helper_main(sys.argv[2]))
