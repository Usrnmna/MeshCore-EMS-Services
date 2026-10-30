"""Verify an actual frozen GUI and its history helpers using synthetic fixtures.

No service installation, host discovery, native authorization, radio, credentials,
or provider is used. The optional --python switch exercises a source entry point;
release evidence must omit that switch and must report frozen=true.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def require(condition, message):
    """Fail with one bounded diagnostic instead of an apparent successful smoke."""
    if not condition:
        raise AssertionError(message)


def helper_exchange(command, value, *, mode="read", normal=False, cancel_after=None, timeout=20):
    """Keep the request lease open while draining bounded output concurrently."""
    flags = ["--history-read"] if normal else ["--history-smoke-helper", mode]
    child = subprocess.Popen(command + flags, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output, errors = bytearray(), bytearray()

    def drain(stream, buffer, maximum):
        while len(buffer) <= maximum:
            chunk = stream.read(min(65536, maximum + 1 - len(buffer)))
            if not chunk:
                return
            buffer.extend(chunk)

    readers = [threading.Thread(target=drain, args=(stream, buffer, maximum), daemon=True)
               for stream, buffer, maximum in ((child.stdout, output, 2 * 1024 * 1024 + 1024),
                                               (child.stderr, errors, 65536))]
    for reader in readers:
        reader.start()
    started = time.monotonic()
    try:
        if value is not None:
            child.stdin.write(json.dumps(value).encode() + b"\n")
            child.stdin.flush()
        if cancel_after is not None:
            time.sleep(cancel_after)
            child.stdin.close()
        child.wait(timeout=timeout)
        for reader in readers:
            reader.join(1)
        require(len(output) <= 2 * 1024 * 1024 + 1024, "Helper exceeded its response limit")
        try:
            result = json.loads(output)
        except (ValueError, UnicodeError):
            raise AssertionError("Helper returned invalid JSON: " + errors.decode(errors="replace")[-2000:]) from None
        return result, child.returncode, time.monotonic() - started
    finally:
        child.stdin.close()
        if child.poll() is None:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=3)
        child.stdout.close(); child.stderr.close()


def process_alive(pid):
    """Observe only the recorded smoke-owned PID, treating a POSIX zombie as exited."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only.
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle, 0) == 258
        finally:
            api.CloseHandle(handle)
    state = Path(f"/proc/{pid}/stat")
    try:
        if state.exists():
            return state.read_text().split(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def verify_helpers(command):
    """Check actual executable dispatch, response framing, and owned-process lifetime."""
    from installers.desktop.history_smoke import request, SYNTHETIC_TEXT
    results = []
    value, status, _ = helper_exchange(command, dict(request(), action="invalid"), normal=True)
    require(status == 1 and value.get("ok") is False, "Production helper accepted an invalid request")
    results.append("production_dispatch_rejects_invalid_request_before_discovery")
    catalog, status, _ = helper_exchange(command, request(), mode="session")
    require(status == 0 and catalog.get("ok") and len(catalog["value"]["channels"]) == 3,
            "Packaged session/catalog helper failed")
    results.append("synthetic_session_catalog")
    first, status, _ = helper_exchange(command, request("page", channel_id="public", page_size=200))
    require(status == 0 and first.get("ok"), "Packaged read helper failed")
    first = first["value"]
    require(len(first["messages"]) == 200 and first["next_cursor"], "Packaged first page is not bounded")
    require(first["messages"][0]["text"] == SYNTHETIC_TEXT, "Packaged text/Unicode changed")
    require(first["messages"][0]["payload"]["data"] == {"encoding": "hex", "data": "00ff"}, "Packaged metadata changed")
    second, status, _ = helper_exchange(command, request("page", channel_id="public", page_size=200, cursor=first["next_cursor"]))
    require(status == 0 and second.get("ok"), "Packaged continuation failed")
    ids = [row["event_id"] for row in first["messages"] + second["value"]["messages"]]
    require(len(ids) == len(set(ids)) == 205 and "expired" not in ids and "future" not in ids,
            "Packaged pagination or retention filtering failed")
    results.extend(["synthetic_read_only_sqlite", "plain_text_unicode_metadata", "paging_and_expiry"])
    for channel, expected in (("missing", "History not created yet"), ("schema", "Unsupported history schema"),
            ("denied", "History access denied"), ("unavailable", "History database unavailable")):
        value, status, _ = helper_exchange(command, request("page", channel_id=channel))
        require(status == 1 and not value.get("ok") and value.get("error") == expected,
                "Packaged failure state mismatch: " + channel)
    results.append("distinct_failure_responses")
    denied, status, _ = helper_exchange(command, request("page", channel_id="denied"), mode="session")
    require(status == 1 and denied.get("error") == "History authorization cancelled or unavailable",
            "Synthetic session denial did not stay within the no-prompt seam")
    results.append("authorization_denial_without_native_prompt")
    timed, status, duration = helper_exchange(command, request("page", channel_id="stall"), mode="session")
    require(status == 1 and timed.get("error") == "History read deadline exceeded" and duration < 10,
            "Packaged read did not meet its deadline")
    results.append("five_second_read_deadline")
    cancelled, status, duration = helper_exchange(command, request("page", channel_id="stall"), mode="session", cancel_after=.5)
    require(status == 1 and cancelled.get("error") == "History read cancelled" and duration < 8,
            "Parent pipe loss did not cancel the packaged session")
    results.append("parent_pipe_cancellation")
    orphan, status, _ = helper_exchange(command, None, mode="orphan")
    require(status == 0 and orphan.get("ok"), "Synthetic parent-exit helper failed")
    pid = orphan["value"]["owned_pid"]
    require(type(pid) is int and pid > 0, "Synthetic owned PID is invalid")
    until = time.monotonic() + 10
    while process_alive(pid) and time.monotonic() < until:
        time.sleep(.05)
    require(not process_alive(pid), "Owned packaged session survived parent exit")
    results.append("owned_session_exits_after_parent_exit")
    return results


def require_image_decoding(report):
    """Reject reports without complete pixel evidence from both native decoders."""
    from installers.desktop.image_smoke import EXPECTED_PIXELS
    evidence = report.get("image_decoding")
    require(isinstance(evidence, dict), "GUI report has no image decoding evidence")
    for image_format in ("webp", "tiff"):
        require(image_format + "_decode_pixels" in report.get("checks", []),
                "GUI report omitted the " + image_format + " decoding check")
        decoded = evidence.get(image_format)
        require(isinstance(decoded, dict) and decoded.get("width") == 3 and decoded.get("height") == 2
                and decoded.get("rgba_pixels") == EXPECTED_PIXELS,
                "GUI report has invalid " + image_format + " pixel evidence")


def verify_application(application, *, python=None, expected_version=None, datasets_only=False):
    """Run bounded GUI and helper checks and return evidence tied to the executable."""
    command = ([str(python)] if python else []) + [str(application)]
    reports = []
    with tempfile.TemporaryDirectory(prefix="mc-ems-packaged-smoke-") as temporary:
        for extra in ([], ["--datasets-only"]) if datasets_only else ([],):
            output = Path(temporary) / ("datasets.json" if extra else "main.json")
            environment = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
            result = subprocess.run(command + ["--demo", "--smoke-test", "--smoke-report", str(output)] + extra,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            require(output.is_file(), "GUI did not produce a smoke report: " + result.stderr.decode(errors="replace")[-2000:])
            report = json.loads(output.read_text(encoding="utf-8"))
            require(result.returncode == 0 and report.get("ok"), "GUI smoke failed: " + json.dumps(report))
            require(report.get("frozen") == (python is None), "Packaged smoke unexpectedly ran from source")
            require_image_decoding(report)
            if expected_version:
                require(any(expected_version in text for text in report.get("visible_text", [])), "Expected version is not visible in the GUI")
                report["checks"].append("expected_version_visible")
            reports.append(report)
    helpers = verify_helpers(command)
    return dict(schema=1, ok=True, application=str(application),
                executable_sha256=hashlib.sha256(application.read_bytes()).hexdigest(),
                frozen=python is None, expected_version=expected_version, gui=reports, helper_checks=helpers,
                verified_at=datetime.now(timezone.utc).isoformat(),
                scope="Synthetic local fixture; no installation, device, live provider, or native authorization validation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--python", type=Path, help="Source-only verification; omit for frozen release evidence")
    parser.add_argument("--expected-version", default="v0.9.8-beta")
    parser.add_argument("--include-datasets-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_application(args.application.resolve(), python=args.python, expected_version=args.expected_version,
                                    datasets_only=args.include_datasets_only)
    except Exception as error:
        result = {"schema": 1, "ok": False, "application": str(args.application), "error": str(error)}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["ok"], "report": str(args.output), "error": result.get("error")}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
