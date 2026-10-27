"""Owned local integration edits and static custom-program staging.

Receipts describe configuration changes, not package installations. Credential
values never enter these records. Reversion requires the recorded after-value to
remain unchanged; files copied into the protected programs directory are retained.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from importlib.machinery import PathFinder
import json
import os
from pathlib import Path
import re
import sys

RECEIPT = "desktop-integrations.json"
ABSENT = {"present": False}
INPUTS = {"none", "coordinates", "route_number", "location", "gis_query", "fire_query", "slide_query", "water_query"}


def program_name(value):
    """Restrict registered command phrases to a bounded, printable single token."""
    if not isinstance(value, str) or not re.fullmatch(r"!?[A-Za-z][A-Za-z0-9_-]{0,62}", value):
        raise ValueError("Custom command name must be a single ASCII command token")
    return value


def validate_programs(value):
    """Validate metadata only; source bytes are checked again before staging."""
    if not isinstance(value, dict) or set(value) != {"register", "unregister"}:
        raise ValueError("Programs must contain register and unregister lists")
    if not isinstance(value["register"], list) or not isinstance(value["unregister"], list) or len(value["register"]) + len(value["unregister"]) > 64:
        raise ValueError("Too many program registration changes")
    names = []
    for spec in value["register"]:
        if not isinstance(spec, dict) or set(spec) - {"name", "source", "sha256", "channels", "input", "args"} or not {"name", "source", "sha256", "channels"} <= set(spec):
            raise ValueError("Invalid custom program registration")
        names.append(program_name(spec["name"]))
        source = spec["source"]
        if not isinstance(source, str) or not Path(source).is_absolute() or Path(source).suffix.lower() != ".py" or len(source) > 4096 or any(ord(c) < 32 for c in source):
            raise ValueError("Select an absolute Python source file")
        if not isinstance(spec["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", spec["sha256"]):
            raise ValueError("Custom program requires its reviewed SHA-256")
        channels = spec["channels"]
        if not isinstance(channels, list) or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item) for item in channels) or len(set(channels)) != len(channels):
            raise ValueError("Invalid custom program channel assignments")
        if spec.get("input", "none") not in INPUTS:
            raise ValueError("Unsupported custom program input")
        args = spec.get("args", [])
        if not isinstance(args, list) or len(args) > 32 or any(not isinstance(arg, str) or len(arg) > 4096 or any(ord(c) < 32 for c in arg) for arg in args):
            raise ValueError("Program arguments must be bounded fixed strings")
    names.extend(program_name(name) for name in value["unregister"])
    if len(set(names)) != len(names):
        raise ValueError("Duplicate or conflicting program registration")


def read_receipt(config):
    """Read the protected local change receipt; reject damaged records."""
    path = config / RECEIPT
    if not path.exists():
        return {"schema": 1, "changes": [], "disabled_commands": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != 1 or not isinstance(value.get("changes"), list) or not isinstance(value.get("disabled_commands", {}), dict):
        raise ValueError("Invalid local integration receipt; retain it and restore a recovery snapshot")
    return value


def node(value, path):
    """Return a JSON node plus explicit absence, without ambiguous null sentinels."""
    current = value
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return dict(ABSENT)
        current = current[part]
    return {"present": True, "value": copy.deepcopy(current)}


def changed_nodes(before, after, path=()):
    """Yield the smallest differing dictionary leaves; lists remain ordered values."""
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            if key in before and key in after:
                yield from changed_nodes(before[key], after[key], (*path, key))
            else:
                yield (*path, key)
    elif before != after:
        yield path


def record_changes(before, after, receipt):
    """Record this interface's exact edits, retaining an unconflicted original baseline."""
    result = copy.deepcopy(receipt)
    entries = {tuple(entry["path"]): entry for entry in result["changes"]}
    for path in changed_nodes(before, after):
        previous, following = node(before, path), node(after, path)
        owned = entries.get(path)
        baseline = owned["before"] if owned and owned["after"] == previous else previous
        if baseline == following:
            entries.pop(path, None)
        else:
            entries[path] = {"path": list(path), "before": baseline, "after": following}
    result["changes"] = list(entries.values())
    return result


def revert_changes(current, receipt):
    """Restore unchanged owned values; retain conflicts and unrelated current values."""
    candidate = copy.deepcopy(current)
    pending, conflicts = [], []
    # Deeper leaves first avoids removing parents while a nested edit remains.
    for entry in sorted(receipt["changes"], key=lambda item: len(item["path"]), reverse=True):
        path = entry["path"]
        if not path or any(not isinstance(key, str) for key in path):
            raise ValueError("Invalid integration receipt path")
        if node(candidate, path) != entry["after"]:
            pending.append(entry); conflicts.append(".".join(path)); continue
        parent = candidate
        for part in path[:-1]:
            parent = parent.setdefault(part, {})
        if entry["before"].get("present"):
            parent[path[-1]] = copy.deepcopy(entry["before"]["value"])
        else:
            parent.pop(path[-1], None)
    return candidate, {"schema": 1, "changes": pending, "disabled_commands": {}}, conflicts


def configure_commands(candidate, settings, receipt):
    """Enable/disable by channel assignment; do not add separate execution ownership."""
    commands = candidate["responder"]["commands"]
    previous = receipt.setdefault("disabled_commands", {})
    for name, enabled in settings.get("commands", {}).items():
        if name not in commands:
            raise ValueError("Unknown command: " + name)
        spec = commands[name]
        if not enabled:
            if spec.get("channels"):
                previous[name] = list(spec["channels"])
            spec["channels"] = []
        elif not spec.get("channels"):
            restored = previous.get(name, [])
            if not restored:
                raise ValueError("Choose channel assignments before enabling " + name)
            spec["channels"] = list(restored)


def validate_imports(tree, directory):
    """Resolve unconditional top-level imports without importing operator code.

    Conditional, relative and dynamic imports remain runtime concerns. Resolution
    inspects module specifications in the private runtime, never executes source.
    """
    search = [str(directory)] + [value for value in sys.path if value and Path(value).resolve() != Path(__file__).resolve().parents[2]]
    required = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            required.update(alias.name.split(".")[0] for alias in statement.names)
        elif isinstance(statement, ast.ImportFrom) and statement.level == 0 and statement.module:
            required.add(statement.module.split(".")[0])
    for name in sorted(required):
        if name in sys.builtin_module_names or name in getattr(sys, "stdlib_module_names", ()):
            continue
        if PathFinder.find_spec(name, search) is None:
            raise ValueError("Required custom-program import is unavailable in the installed runtime: " + name + ". Optional dependencies must be provisioned through a supported package, not an elevated arbitrary installer.")


def stage_programs(candidate, settings, config):
    """Copy hash-bound source into a protected directory without importing/executing it.

    Returns newly created files for rollback on failed configuration publication.
    Existing programs, including modified files and unregistered code, are retained.
    """
    requested = settings.get("programs")
    if not requested:
        return []
    validate_programs(requested)
    responder = candidate["responder"]
    commands = responder["commands"]
    directory = config / "programs"
    if Path(responder.get("program_directory", "")).resolve() != directory.resolve() or directory.is_symlink():
        raise ValueError("Automatic import requires the installation-owned programs directory; existing custom locations remain unchanged")
    created = []
    try:
        for name in requested["unregister"]:
            existing = commands.get(name)
            if existing is None:
                continue
            if not existing.get("script", "").startswith("programs/"):
                raise ValueError("Shipped programs belong to the service package and cannot be deregistered")
            commands.pop(name)
        for spec in requested["register"]:
            name = spec["name"]
            if name in commands:
                raise ValueError("A registered command already owns " + name + "; deregister custom commands in a separate reviewed operation")
            source = Path(spec["source"])
            if source.is_symlink() or not source.is_file() or source.stat().st_size > 128 * 1024:
                raise ValueError("Choose a regular Python source file no larger than 128 KiB")
            with source.open("rb") as stream:
                content = stream.read(128 * 1024 + 1)
            if len(content) > 128 * 1024 or hashlib.sha256(content).hexdigest() != spec["sha256"]:
                raise ValueError("Custom program bytes changed after review")
            tree = ast.parse(content, filename=source.name)
            validate_imports(tree, directory)
            # Content-derived dedicated names cannot replace another operator file.
            filename = name.lstrip("!") + "-" + spec["sha256"][:16] + ".py"
            destination = directory / filename
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink() or destination.read_bytes() != content:
                    raise ValueError("Retained custom program conflicts with the selected source")
            else:
                with destination.open("xb") as stream:
                    stream.write(content)
                if os.name != "nt":
                    metadata = directory.stat()
                    os.chown(destination, metadata.st_uid, metadata.st_gid)
                    destination.chmod(0o640)
                created.append(destination)
            commands[name] = {"script": "programs/" + filename, "args": list(spec.get("args", [])),
                              "input": spec.get("input", "none"), "channels": list(spec["channels"])}
        return created
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
