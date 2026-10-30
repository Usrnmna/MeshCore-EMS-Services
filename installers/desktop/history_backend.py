"""Strict installed-service history reads; no maintenance or radio operations."""
import base64
from contextlib import ExitStack, nullcontext
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

from installers.datasets.gui.discovery import native_target

MAX_RESPONSE = 2 * 1024 * 1024
MAX_REQUEST = 64 * 1024


def _date(value):
    """Parse an explicitly zoned ISO date without interpreting local time."""
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid history date")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("History dates require a timezone")
    return result.astimezone(timezone.utc)


def validate_history_request(request):
    """Validate a bounded request with no caller-selected paths or executable code."""
    if not isinstance(request, dict) or set(request) != {"schema", "kind", "target", "action", "query"}:
        raise ValueError("Invalid history request fields")
    if len(json.dumps(request, allow_nan=False).encode("utf-8")) > MAX_REQUEST:
        raise ValueError("History request is too large")
    if type(request["schema"]) is not int or request["schema"] != 1 or request["kind"] != "history":
        raise ValueError("Unsupported history request schema")
    if request["target"] != native_target():
        raise ValueError("History target does not match this computer")
    query = request["query"]
    if not isinstance(query, dict) or request["action"] not in {"catalog", "page"}:
        raise ValueError("Invalid history action or query")
    if request["action"] == "catalog":
        if query:
            raise ValueError("History catalog accepts no filters")
        return request
    if set(query) - {"channel_id", "start", "end", "sender", "sender_prefix", "page_size", "cursor"}:
        raise ValueError("Unknown history filter")
    channel = query.get("channel_id")
    if not isinstance(channel, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", channel):
        raise ValueError("Invalid channel ID")
    size = query.get("page_size", 200)
    if type(size) is not int or not 1 <= size <= 200:
        raise ValueError("History page size must be 1..200")
    dates = {key: _date(query[key]) for key in ("start", "end") if query.get(key) is not None}
    if len(dates) == 2 and dates["start"] > dates["end"]:
        raise ValueError("History start must not follow end")
    if query.get("sender") is not None and query.get("sender_prefix") is not None:
        raise ValueError("Choose one sender selector")
    for key in ("sender", "sender_prefix"):
        value = query.get(key)
        if value is not None and (not isinstance(value, str) or len(value.encode("utf-8")) > 4096):
            raise ValueError("Invalid history sender selector")
    cursor = query.get("cursor")
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
                raise ValueError()
            value = json.loads(base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True))
            if not isinstance(value, dict) or set(value) != {"filter", "upper", "time", "id"}:
                raise ValueError()
            if (not isinstance(value["filter"], str) or not re.fullmatch("[0-9a-f]{64}", value["filter"])
                    or type(value["upper"]) is not int or type(value["time"]) is not int
                    or not isinstance(value["id"], str) or not 1 <= len(value["id"]) <= 128):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError) as error:
            raise ValueError("Invalid history cursor") from error
    return request


def _serialize(value):
    """Serialize only public dataclass fields, preserving encoded metadata values."""
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _diagnostics(path):
    """Read a bounded optional counter snapshot without forwarding arbitrary text."""
    try:
        with path.open("rb") as source:
            content = source.read(16385)
        if len(content) > 16384:
            return None
        value = json.loads(content)
        if not isinstance(value, dict) or value.get("state") not in {"disabled", "starting", "ready", "unavailable", "stopping", "stopped"}:
            return None
        result = {"state": value["state"], "observed_at": _date(value.get("observed_at")).isoformat()}
        for key in ("offered", "admitted", "committed", "pending", "pending_bytes", "missed", "duplicates", "clock_corrections"):
            count = value.get(key)
            if type(count) is int and 0 <= count <= 2**63 - 1:
                result[key] = count
        return result
    except (OSError, ValueError, TypeError, OverflowError):
        return None


def read_installed(request):
    """Resolve and recheck protected installed code inside the disposable read child."""
    validate_history_request(request)
    from installers.desktop import service_backend as service
    from installers.desktop.history_state import service_state
    root, state, config, _, platform = service.installed_paths(request["target"])
    status = service_state(request["target"])
    if status == "missing":
        raise RuntimeError("Service not installed")
    package = "meshcore_mqtt_service_windows" if request["target"] == "windows-x64" else "meshcore_mqtt_service"
    try:
        if "channel-history-v1" not in service.installed_capabilities(root):
            raise RuntimeError("Service update required")
        source = service.trusted_installed(root / package / "channel_history.py", root)
    except (PermissionError, ValueError):
        raise RuntimeError("Untrusted history installation") from None
    database = state / "runtime/channel_history/channel_history.sqlite3"
    validate_storage_path(state, database)
    settings_path = config / "config.json"
    settings = {}
    if request["action"] == "catalog" and settings_path.exists():
        settings = service.history_summary(json.loads(settings_path.read_text(encoding="utf-8-sig")).get("channel_history"))
    catalog = dict(settings=settings, service_state=status, database_path=str(database),
                   availability="available", channels=[], observed_at=datetime.now(timezone.utc).isoformat(),
                   latest_received_at=None, diagnostics=None)
    if request["action"] == "catalog":
        catalog["diagnostics"] = _diagnostics(database.parent / "status.json")
    try:
        # A read-only OS open preserves permission-denial identity before SQLite
        # wraps it in its generic CANTOPEN error. It never creates a missing store.
        with database.open("rb"):
            pass
    except FileNotFoundError:
        if request["action"] == "catalog":
            return dict(catalog, availability="not_created")
        raise RuntimeError("History not created yet") from None
    protection = nullcontext()
    if os.name == "nt":
        from installers.desktop.windows_trust import protected_paths
        protection = protected_paths([root, source])
    with ExitStack() as protected:
        # Recheck after pinning the path; do not reuse a cached schema module.
        try:
            protected.enter_context(protection)
            source = service.trusted_installed(source, root)
        except (PermissionError, ValueError):
            raise RuntimeError("Untrusted history installation") from None
        validate_storage_path(state, database)
        name = "_installed_history_reader"
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        previous = sys.modules.get(name)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            if request["action"] == "catalog":
                catalog["channels"] = _serialize(module.list_recorded_channels(database))
                catalog["latest_received_at"] = max((channel["latest_received_at"] for channel in catalog["channels"]), default=None)
                value = catalog
            else:
                query = dict(request["query"])
                for key in ("start", "end"):
                    if query.get(key) is not None:
                        query[key] = _date(query[key])
                value = _serialize(module.read_message_page(database, **query))
        except module.HistoryUnavailable as error:
            cause = error
            while cause is not None:
                if isinstance(cause, PermissionError):
                    raise PermissionError("History access denied") from None
                if "Unsupported history schema" == str(cause):
                    raise RuntimeError("Unsupported history schema") from None
                cause = cause.__cause__
            if "response budget" in str(error):
                raise RuntimeError("History record exceeds response budget") from None
            raise RuntimeError("History database unavailable") from None
        finally:
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    if len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode()) > MAX_RESPONSE:
        raise RuntimeError("History response exceeds response budget")
    return value


def validate_storage_path(state, database):
    """Reject redirected optional storage before an authorized fixed-path read.

    The registered state root and descendants must be real local paths. Missing
    components are allowed so catalog reads can report an uncreated store.
    Permission errors remain eligible for the separate authorization path.
    """
    import stat
    state, database = Path(state).absolute(), Path(database).absolute()
    if not database.is_relative_to(state):
        raise RuntimeError("Untrusted history storage")
    paths = [state, state / 'runtime', database.parent, database,
             Path(str(database) + '-wal'), Path(str(database) + '-shm'), database.parent / 'status.json']
    for path in paths:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError("Untrusted history storage")
    if not database.resolve().is_relative_to(state.resolve()):
        raise RuntimeError("Untrusted history storage")


def perform(request, emit, cancel=None):
    """Run one supervised read without recursively requesting native authorization."""
    validate_history_request(request)
    from installers.desktop.history_process import supervise_read
    return supervise_read(request, cancel)


def query_history(request, emit, cancel=None):
    """Attempt ordinary access; authorize once only for an actual permission denial."""
    validate_history_request(request)
    try:
        return perform(request, lambda _: None, cancel)
    except PermissionError:
        from installers.desktop.authorization import run_authorized
        return run_authorized(request, lambda _: None, cancel)
