"""Review and coordinate independent native owners without replacing their registries.

Only validated component intentions cross the authorization boundary. Plans are
rebuilt there, and their revisions are checked under the shared maintenance lease.
The journal records outcomes, never credentials, executable arguments or settings.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
import uuid

from installers.datasets.gui.catalog import DATASETS
from installers.datasets.manage import default_root
from installers.datasets.gui.discovery import demo_snapshot, inspect, native_target
from installers.datasets.gui.planning import make_plan
from installers.datasets.gui.privileges import plan_digest, snapshot_payload
from . import service_backend as service

DATA_ACTIONS = {"keep": None, "install": "install_selected", "remove_data": "uninstall_selected",
                "remove_tools": "retain_selected", "verify": "verify_selected", "update": "update_selected",
                "rollback": "rollback_selected", "repair": "repair_selected", "recover": "recover_selected"}
SERVICE_ACTIONS = {"keep", "install", "configure", "uninstall", "deconfigure", "validate", "check_connection", "start", "stop"}
INTENT_FIELDS = {"target", "root", "folder", "datasets", "dataset_action", "service_action", "settings", "startup", "start"}


def validate_intent(value):
    """Accept a small typed intention, never native command strings or purge flags."""
    if not isinstance(value, dict) or set(value) != INTENT_FIELDS:
        raise ValueError("Unexpected unified operation fields")
    if value["target"] not in service.TARGETS or value["dataset_action"] not in DATA_ACTIONS or value["service_action"] not in SERVICE_ACTIONS:
        raise ValueError("Unsupported unified operation")
    if value["startup"] not in {"preserve", "disabled", "manual", "automatic"} or type(value["start"]) is not bool:
        raise ValueError("Invalid service startup selection")
    names = value["datasets"]
    if not isinstance(names, list) or any(not isinstance(name, str) or name not in DATASETS for name in names) or len(set(names)) != len(names):
        raise ValueError("Invalid dataset selection")
    for field in ("root", "folder"):
        path = Path(service.safe_text(value[field], field))
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("Choose an absolute, non-symbolic-link " + field)
        if field == "root" and path == Path(path.anchor):
            raise ValueError("Choose a dedicated shared dataset directory, not a filesystem root")
    service.validate_settings(service.core_settings(value["settings"]))
    if any(value["settings"].values()) and value["service_action"] not in {"install", "configure"}:
        raise ValueError("Settings require Install / Repair or Save settings")
    if value["start"] and value["service_action"] in {"uninstall", "deconfigure", "stop"}:
        raise ValueError("Removal, deconfiguration and stopping cannot also start the service")
    if value["start"] and value["startup"] == "disabled":
        raise ValueError("A disabled service cannot be started; choose manual or automatic startup")
    return value


def digest(value):
    """Bind review to structured state, including protected revision fingerprints."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def dataset_folder(folder):
    """Discover adjacent independent dataset installers in an extracted kit."""
    path = Path(folder)
    return path / "datasets" if (path / "datasets").is_dir() else path


def service_folder(folder):
    """Find the adjacent service artifact, including the first-stage kit layout."""
    path = Path(folder)
    for candidate in (path / "service-installers", path, path.parent / "service-setup/service-installers"):
        if candidate.is_dir() and any(candidate.glob("MeshCore-EMS-v*-*")):
            return candidate
    return path


def discover(intent, emit, *, demo=False):
    """Read native owner records; demo never discovers the host or artifacts."""
    root, target = Path(intent["root"]), intent["target"]
    if demo:
        return demo_snapshot(root, target), dict(registered=False, state="missing", startup="manual", settings={},
                                                revision="demo", capabilities=["operation-lock-v1", "settings-v2", "channel-history-v1"])
    installed = service.snapshot(target, emit)
    if not installed.get("registered") and not installed.get("settings"):
        installed["settings"] = default_settings(target)
    datasets = inspect(root, target, progress=emit)
    if not installed.get("settings", {}).get("dataset_root"):
        from .retained_roots import discover as retained_roots
        suggestions = {item["root"]: item for item in retained_roots(emit)}
        for name, collection in datasets.collections.items():
            recorded = collection.package.root
            if recorded is None:
                continue
            location = str(recorded)
            entry = suggestions.setdefault(location, {"root": location, "datasets": [],
                "verification": "native package record; data verification required"})
            if name not in entry["datasets"]:
                entry["datasets"].append(name)
        installed["retained_roots"] = sorted(suggestions.values(), key=lambda item: item["root"])
    return datasets, installed


def default_settings(target):
    """Expose bundled version-owned initial command references without executing code."""
    package = "meshcore_mqtt_service_windows" if target == "windows-x64" else "meshcore_mqtt_service"
    path = (Path(sys._MEIPASS) / "defaults" / package / "config.json" if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2] / package / "config.json")
    config = json.loads(path.read_text(encoding="utf-8"))
    responder = config["responder"]
    commands = responder["commands"]
    return {"channels": {"channels": responder["channels"], "command_channels": {name: spec.get("channels", []) for name, spec in commands.items()}},
            "commands": {name: {"enabled": bool(spec.get("channels")), "channels": spec.get("channels", []),
                                "script": spec["script"], "owner": "service-package"} for name, spec in commands.items()},
            "defaults_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "defaults_package": package}


def recording_description(section, registry):
    """Describe the non-secret target without querying its optional database."""
    section = service.history_summary(section)
    channel_id = section.get("channel_id", "none")
    if not isinstance(channel_id, (str, type(None))):
        return "invalid optional channel ID; recording unavailable"
    channel = section.get("channel") or registry.get(channel_id, {})
    if not isinstance(channel, dict):
        return "invalid optional channel reference; recording unavailable"
    return ("enabled" if section.get("enabled") is True else "disabled") + "; ID " + str(channel_id) + "; " + str(channel.get("name", "unavailable")) + " (" + str(channel.get("type", "unknown")) + ")"


def build_plan(intent, datasets, installed, *, demo=False):
    """Expand owner operations, service coordination, retention and review blockers."""
    validate_intent(intent)
    action, selected = intent["service_action"], intent["dataset_action"]
    registered = installed.get("registered", installed.get("installed", False))
    state = installed.get("state", "unknown")
    blocked, warnings, steps = [], [], []
    dataset_plan = None
    if DATA_ACTIONS[selected]:
        dataset_plan = make_plan(datasets, DATA_ACTIONS[selected], intent["datasets"], dataset_folder(intent["folder"]), demo=demo)
        blocked.extend(dataset_plan.blocked)
        if not demo:
            for operation in dataset_plan.operations:
                package = datasets.collections[operation.dataset].package
                if operation.kind != "setup" and "maintenance-lock-v1" not in package.capabilities:
                    blocked.append(operation.dataset + ": legacy maintenance tools cannot coordinate this operation. Select Repair selected maintenance packages with current installers first.")
                elif operation.kind == "setup":
                    index = 0 if intent["target"] == "windows-x64" else 1
                    artifact_path = Path(operation.command[index])
                    try:
                        record = json.loads(artifact_path.with_name(artifact_path.name + ".provenance.json").read_text(encoding="utf-8"))
                        if record.get("artifact_sha256") != operation.artifact_hash or "maintenance-lock-v1" not in record.get("capabilities", []):
                            raise ValueError("Dataset installer lacks current maintenance-coordination provenance")
                    except (OSError, ValueError) as error:
                        blocked.append(operation.dataset + ": " + str(error))
    changing_data = bool(dataset_plan and dataset_plan.operations and selected != "verify")
    service_change = action in {"install", "configure", "uninstall", "deconfigure"}
    must_stop = registered and (changing_data or service_change or action in {"stop", "check_connection"} or intent["startup"] == "disabled")
    if state in {"unknown", "pending"} and (must_stop or intent["start"] or action == "start"):
        blocked.append("The service state cannot be established. Inspect service diagnostics before changing consumers.")
    if action not in {"keep", "install"} and not registered:
        blocked.append("Install the service package before this service operation.")
    if intent["startup"] != "preserve" and not registered and action != "install":
        blocked.append("Startup policy requires an installed or selected service package.")
    if must_stop and state != "stopped":
        steps.append(dict(owner="service", action="stop", detail="Stop EMS consumers; release the companion connection."))
    if action == "uninstall":
        retained = (" Linux also retains installed releases and their private runtime under /opt/meshcore-ems for recovery."
                    if intent["target"] != "windows-x64" else " Windows removes its registered installed application files.")
        steps.append(dict(owner="service", action="uninstall", detail="Run the native service uninstaller before selected dataset removals; retain configuration, credentials, custom programs, databases, datasets and recovery material." + retained))
    if dataset_plan and dataset_plan.operations:
        steps.append(dict(owner="datasets", action=dataset_plan.action,
                          detail="; ".join(op.dataset + ": " + op.kind for op in dataset_plan.operations)))
    artifact = None
    if action == "install":
        if not demo:
            try:
                path = service.select_installer(service_folder(intent["folder"]), intent["target"])
                with path.open("rb") as stream:
                    artifact = {"name": path.name, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}
                provenance_path = path.with_name(path.name + ".provenance.json")
                record = json.loads(provenance_path.read_text(encoding="utf-8"))
                if record.get("artifact_sha256") != artifact["sha256"] or record.get("target") != intent["target"] or "staged-startup-v1" not in record.get("capabilities", []):
                    raise ValueError("Rebuild the service installer with staged-startup and shared-lock capabilities")
                artifact["provenance_sha256"] = digest(record)
                artifact["history_supported"] = service.incoming_history_supported(record, intent["target"])
                defaults = installed.get("settings", {})
                if not registered and defaults.get("defaults_sha256") and record.get("source_sha256", {}).get(defaults["defaults_package"] + "/config.json") != defaults["defaults_sha256"]:
                    raise ValueError("Service installer and displayed initial command configuration differ. Use a matching desktop kit.")
            except (OSError, ValueError) as error:
                blocked.append(str(error))
        steps.append(dict(owner="service", action="install", detail="Native service installation/repair, inactive until settings validate; preserve package identity."))
    elif action not in {"keep", "start", "stop", "uninstall"}:
        steps.append(dict(owner="service", action=action, detail={
            "configure": "Save selected settings; preserve unspecified settings and credentials.",
            "uninstall": "Run the native uninstaller; retain configuration, credentials, programs, databases, datasets and recovery material.",
            "deconfigure": "Revert only unchanged receipt-owned settings; retain conflicts, credentials and program files; leave stopped.",
            "validate": "Validate installed configuration offline without opening a radio.",
            "check_connection": "Read configured companion channels without device writes; require exclusive access while EMS is stopped."
        }[action]))
    if registered and action in {"configure", "deconfigure"} and "settings-v2" not in installed.get("capabilities", []) and not demo:
        blocked.append("The installed maintenance backend is older. Select Install / Repair with current artifacts first.")
    # Legacy native tools do not participate in the shared lease. Do not claim
    # concurrency safety for an operation that cannot establish that capability.
    if registered and service_change and "operation-lock-v1" not in installed.get("capabilities", []) and action != "install" and not demo:
        blocked.append("The installed service tools lack maintenance coordination. Repair with a current installer first.")
    if action == "deconfigure" and intent["startup"] == "automatic":
        blocked.append("Deconfiguration leaves consumers stopped. Choose preserved, manual or disabled startup; enabling automatic startup requires a separate validated operation.")
    if action == "deconfigure" and installed.get("settings", {}).get("deconfiguration_error"):
        blocked.append(installed["settings"]["deconfiguration_error"])
    if intent["startup"] != "preserve" and action != "uninstall":
        steps.append(dict(owner="service", action="startup", detail="Set service startup to " + intent["startup"] + "."))
    restart = state == "running" and must_stop and action not in {"uninstall", "deconfigure", "stop"} and intent["startup"] != "disabled"
    if (intent["start"] or action == "start" or restart) and action not in {"uninstall", "deconfigure", "stop"}:
        if not registered and action != "install":
            blocked.append("No service package is available to start.")
        steps.append(dict(owner="service", action="start", detail="Start only after preceding owners and configuration validations succeed."))
    gate = next((index for index, step in enumerate(steps) if step["action"] == "start" or
                 step["action"] == "startup" and intent["startup"] == "automatic"), None)
    if gate is not None and not any(step["action"] == "validate" for step in steps[:gate]):
        steps.insert(gate, dict(owner="service", action="validate", detail="Validate installed configuration, dependencies and dataset-root access before enabling or starting consumers."))
    if changing_data or service_change:
        warnings.append("Failures leave completed native operations in place. Cancellation occurs between safe owner operations; review the recovery journal before retrying.")
    if selected == "remove_tools":
        warnings.append("Only selected maintenance packages are removed. Active and rollback dataset records and files remain; reinstall matching tools to maintain them.")
    if selected == "remove_data":
        warnings.append("Selected receipt-owned datasets will be removed explicitly. Modified, unowned and legacy files remain. No unselected dependent is removed.")
    if intent["settings"].keys() & {"channel", "channels", "commands", "programs"}:
        warnings.append("Channel identity or command-assignment changes may make stored subscriptions ineligible. Scheduling, expiry and subscriptions remain service-owned.")
    if intent["startup"] == "disabled" and restart:
        blocked.append("The plan would restart a disabled service. Stop the service separately or choose manual startup.")
    if registered and changing_data and "operation-lock-v1" not in installed.get("capabilities", []) and not demo:
        blocked.append("Repair legacy service tools before a coordinated dataset mutation; independent legacy tools cannot be excluded safely.")
    if action == "install" and dataset_plan and dataset_plan.operations:
        consumer_root = intent["settings"].get("dataset_root") or installed.get("settings", {}).get("dataset_root") or str(default_root())
        if Path(consumer_root).resolve() != Path(intent["root"]).resolve():
            blocked.append("Selected datasets use a different root from the service. Select Apply this dataset root to service consumers, or use the current service data root. No root migration is automatic.")
    if not demo:
        for program in intent["settings"].get("programs", {}).get("register", []):
            try:
                source = Path(program["source"])
                if source.is_symlink() or source.stat().st_size > 128 * 1024:
                    raise ValueError("Custom source must be a regular file no larger than 128 KiB")
                with source.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != program["sha256"]:
                        raise ValueError("Custom source changed after selection; choose it again")
            except (OSError, ValueError) as error:
                blocked.append(program["name"] + ": " + str(error))
    reviewed_steps = steps
    history_outcome = service.review_history(intent["settings"], installed, intent["target"],
        supported=demo or (bool(artifact and artifact.get("history_supported")) if action == "install" else "channel-history-v1" in installed.get("capabilities", [])), demo=demo, incoming=action == "install")
    if (action == "configure" and service.HISTORY_FIELDS & intent["settings"].keys()
            and not any(service.core_settings(intent["settings"]).values())
            and history_outcome["status"] == "not_applied"):
        steps = [step for step in steps if not (step["owner"] == "service" and step["action"] == "configure")]
        # A rejected history-only request has no configuration side effects. An
        # independently selected dataset/startup/start operation keeps its checks.
        if not changing_data and intent["startup"] == "preserve" and not intent["start"]:
            steps = [step for step in steps if step["owner"] != "service"]
    payload = dict(intent=intent, snapshot={"service": dict(installed, installed=registered, status=state), "datasets": snapshot_payload(datasets)},
                   steps=steps, blocked=blocked, warnings=warnings, artifact=artifact,
                   dataset_operations=[{"dataset": op.dataset, "action": op.kind} for op in dataset_plan.operations] if dataset_plan else [],
                   dataset_digest=plan_digest(dataset_plan) if dataset_plan else None, demo=demo)
    payload["digest"] = digest(dict(payload, steps=reviewed_steps))
    # Optional validation may become unavailable after Review. Core revisions and
    # requested fields remain bound; a changed optional outcome is reported later.
    payload["history_outcome"] = history_outcome
    lines = ["SIMULATION — no host changes" if demo else "Reviewed independent-package operation", ""]
    lines.extend(f"{i}. {step['owner']}: {step['action']} — {step['detail']}" for i, step in enumerate(steps, 1))
    if dataset_plan:
        lines.extend(["", dataset_plan.text()])
    if artifact:
        lines.append("Service artifact: " + artifact["name"] + " SHA-256 " + artifact["sha256"])
    if intent["settings"]:
        lines.append("Service fields selected: " + ", ".join(sorted(intent["settings"])))
        visible = {k: v for k, v in intent["settings"].items() if k not in {"credentials", "programs", *service.HISTORY_FIELDS}}
        lines.append(json.dumps(visible, indent=2))
        lines.append("Credential values are hidden; blank values preserve saved credentials.")
        for program in intent["settings"].get("programs", {}).get("register", []):
            lines.append("Register custom command " + program["name"] + " from " + program["source"] + " SHA-256 " + program["sha256"] + "; channels: " + ", ".join(program["channels"]))
        for name in intent["settings"].get("programs", {}).get("unregister", []):
            lines.append("Deregister " + name + "; retain its source file.")
    if service.HISTORY_FIELDS & intent["settings"].keys():
        lines.append("Recording: " + ("Not applied" if history_outcome["status"] == "not_applied" else "Apply selected recording settings") + ". " + history_outcome["reason"])
        saved = installed.get("settings", {})
        old_registry = saved.get("channels", {}).get("channels", {})
        new_registry = intent["settings"].get("channels", {}).get("channels", old_registry)
        lines.append("Saved recording: " + recording_description(saved.get("channel_history"), old_registry))
        lines.append("Requested recording: " + recording_description(intent["settings"].get("channel_history"), new_registry))
        state_directory = installed.get("state_directory", "<installed service state>")
        lines.append("Retention: 86400 seconds (24 hours). Database: " + str(Path(state_directory) / "runtime/channel_history/channel_history.sqlite3") + (" (synthetic demo; no database opened)" if demo else ""))
        actions = {step["action"] for step in steps if step["owner"] == "service"}
        lines.append("Recording operation stop: " + ("yes" if "stop" in actions else "no") + "; restart: " + ("yes" if "stop" in actions and "start" in actions else "no") + ".")
    lines.extend("NOTICE: " + item for item in warnings)
    if action == "deconfigure":
        preview = installed.get("settings", {}).get("deconfiguration", {})
        for change in preview.get("changes", []):
            lines.append("RESTORE " + change["path"] + ": " + json.dumps(change["current"], sort_keys=True) + " -> " + json.dumps(change["restore"], sort_keys=True))
        for name in preview.get("conflicts", []):
            lines.append("RETAIN CONFLICT: " + name + "; current settings differ from the interface receipt.")
        lines.append("Credential values, custom files and subscription databases are retained. Preserved startup policy can still apply on a later reboot; choose Disabled explicitly when required.")
    lines.extend("BLOCKED: " + item for item in blocked)
    if not steps:
        lines.append("No changes selected. Refresh status or select an operation.")
    lines.append("Firmware, device channels, Wi-Fi, external brokers and shared OS dependencies are not changed.")
    payload["text"] = "\n".join(lines)
    return payload, dataset_plan


def prepare(intent, emit=lambda _: None, *, demo=False):
    """Discover and review locally, authorizing protected discovery only if needed."""
    validate_intent(intent)
    try:
        datasets, installed = discover(intent, emit, demo=demo)
        return build_plan(intent, datasets, installed, demo=demo)[0]
    except PermissionError:
        if demo:
            raise
        from .authorization import run_authorized
        return run_authorized(dict(kind="unified", action="prepare", intent=intent), emit)


class Journal:
    """Write atomic, credential-free recovery evidence; never an ownership registry."""
    def __init__(self, directory, plan):
        from .staging import _create_private_directory, require_trusted_owner
        directory = Path(directory)
        if directory.is_symlink():
            raise ValueError("The recovery journal directory cannot be a symbolic link")
        try:
            _create_private_directory(directory)
        except FileExistsError:
            pass
        require_trusted_owner(directory)
        self.path = directory / (uuid.uuid4().hex + ".json")
        self.value = {"schema": 1, "complete": False, "steps": [
            {"owner": step["owner"], "action": step["action"], "outcome": "not run"} for step in plan["steps"]],
            "recovery": "Completed owner operations remain in place. Refresh and review a new plan; repair only the failed owner. Configuration backups and dataset previous generations are retained where available."}
        if "intent" in plan:
            self.value["datasets"] = {"root": plan["intent"]["root"], "selected": plan["intent"]["datasets"],
                                      "planned": plan.get("dataset_operations", []), "results": []}
        self.save()

    def save(self):
        from .locking import create_private_file
        temporary = self.path.with_suffix(".tmp")
        create_private_file(temporary, json.dumps(self.value, indent=2).encode("utf-8"))
        temporary.replace(self.path)

    def record(self, index, outcome, detail):
        self.value["steps"][index].update(outcome=outcome, detail=detail)
        self.save()

    def finish(self, complete):
        self.value["complete"] = complete
        self.save()

    def dataset_result(self, result):
        """Persist each owner outcome promptly without storing arbitrary log text."""
        self.value["datasets"]["results"].append({"dataset": result.dataset, "outcome": result.outcome,
            "detail": "Independent dataset owner completed" if result.outcome == "succeeded" else "Inspect dataset maintenance diagnostics; refresh before retrying"})
        self.save()


def validate_request(request):
    """Validate dispatcher fields independently of caller-supplied review output."""
    if not isinstance(request, dict) or request.get("kind") != "unified" or request.get("action") not in {"prepare", "execute", "history", "inspect_recovery", "recover"}:
        raise ValueError("Invalid unified request")
    if request["action"] == "history":
        if set(request) != {"kind", "action", "target"} or request["target"] not in service.TARGETS:
            raise ValueError("Invalid recovery history request")
        return
    if request["action"] in {"inspect_recovery", "recover"}:
        fields = {"kind", "action", "target"} | ({"revision"} if request["action"] == "recover" else set())
        if set(request) != fields or request["target"] not in service.TARGETS:
            raise ValueError("Invalid maintenance recovery request")
        if request["action"] == "recover" and not re.fullmatch(r"[a-f0-9]{64}", request.get("revision", "")):
            raise ValueError("Invalid maintenance recovery review")
        return
    fields = {"kind", "action", "intent"} | ({"digest"} if request["action"] == "execute" else set())
    if request["action"] == "execute" and "history_reviewed" in request:
        fields.add("history_reviewed")
        if type(request["history_reviewed"]) is not bool:
            raise ValueError("Invalid recording Review decision")
    if set(request) != fields:
        raise ValueError("Unexpected unified request fields")
    validate_intent(request["intent"])
    if request["action"] == "execute" and not re.fullmatch(r"[0-9a-f]{64}", request.get("digest", "")):
        raise ValueError("Invalid reviewed-plan fingerprint")


def perform(request, emit, cancel=None):
    """Reconstruct under a lease and delegate only to existing validated owners."""
    validate_request(request)
    target = request.get("target", request.get("intent", {}).get("target"))
    if target != native_target():
        raise ValueError("Unified operation target does not match this computer")
    from installers.datasets.gui.execution import privileged
    if not privileged():
        raise PermissionError("Unified operations require native administrator authorization")
    if request["action"] == "history":
        return read_history()
    if request["action"] == "inspect_recovery":
        from .locking import inspect_recovery
        return inspect_recovery()
    if request["action"] == "recover":
        from .locking import recover_interrupted
        if cancel is not None and cancel.is_set():
            raise RuntimeError("Recovery cancelled before it started")
        return recover_interrupted(request["revision"])
    intent = request["intent"]
    from .locking import operation_lock
    with operation_lock():
        datasets, installed = discover(intent, emit)
        plan, dataset_plan = build_plan(intent, datasets, installed)
        if request["action"] == "prepare":
            return plan
        if plan["digest"] != request["digest"]:
            raise RuntimeError("Artifacts, configuration, package records or service state changed after review. Refresh and review again.")
        if plan["blocked"]:
            raise RuntimeError("Resolve all review blockers before execution")
        plan["history_reviewed"] = request.get("history_reviewed", False)
        if not plan["history_reviewed"]:
            omit_history_only_steps(plan)
        return run_plan(plan, dataset_plan, emit, cancel or threading.Event())


def omit_history_only_steps(plan):
    """Never activate a previously rejected override or stop consumers for a no-op."""
    intent = plan["intent"]
    if (intent["service_action"] != "configure" or not service.HISTORY_FIELDS & intent["settings"].keys()
            or any(service.core_settings(intent["settings"]).values())):
        return
    plan["history_outcome"] = {"status": "not_applied", "available": False,
        "reason": "Recording settings not applied: the override was not accepted during Review."}
    plan["steps"] = [step for step in plan["steps"] if not (step["owner"] == "service" and step["action"] == "configure")]
    changing_data = bool(plan["dataset_operations"] and intent["dataset_action"] != "verify")
    if not changing_data and intent["startup"] == "preserve" and not intent["start"]:
        plan["steps"] = [step for step in plan["steps"] if step["owner"] != "service"]


def read_history():
    """Read bounded recent journals from a fixed protected location only."""
    from .locking import maintenance_directory
    directory = maintenance_directory() / "operations"
    if directory.is_symlink():
        raise ValueError("Recovery storage cannot be a symbolic link")
    if not directory.exists():
        return []
    records = []
    for path in sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:20]:
        if path.is_symlink() or not re.fullmatch(r"[0-9a-f]{32}\.json", path.name) or path.stat().st_size > 256 * 1024:
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        records.append({"file": path.name, "report": value})
    return records


def recovery_history(target, emit=lambda _: None):
    """Request graphical authorized access to fixed, secret-free recovery records."""
    from .authorization import run_authorized
    return run_authorized(dict(kind="unified", action="history", target=target), emit)


def recover_maintenance(target, emit=lambda _: None):
    """Inspect then recover only a reviewed orphan, preserving owner recovery material.

    The GUI explicitly confirms this operation before calling. Native workers
    fail closed on changed evidence, live participants or unknown subprocesses.
    """
    from .authorization import run_authorized
    state = run_authorized(dict(kind="unified", action="inspect_recovery", target=target), emit)
    if not state["recoverable"]:
        return state
    emit(state["detail"])
    return run_authorized(dict(kind="unified", action="recover", target=target, revision=state["revision"]), emit)


def run_plan(plan, dataset_plan, emit, cancel):
    """Execute bounded owners serially and preserve truthful partial-completion evidence."""
    from installers.datasets.gui import privileges
    intent, target = plan["intent"], plan["intent"]["target"]
    from .locking import maintenance_directory
    journal = Journal(maintenance_directory() / "operations", plan)
    results, failed = [], False
    expected = service.snapshot(target, emit)
    for index, step in enumerate(plan["steps"]):
        if failed or cancel.is_set():
            outcome, detail = ("not run", "A previous operation failed") if failed else ("cancelled", "No new native operation started")
        else:
            try:
                current = service.snapshot(target, emit)
                if current != expected:
                    raise RuntimeError("Service configuration or registration changed between operations; refresh before retrying")
                emit(step["detail"])
                journal.record(index, "running", "The native owner may have partially completed; refresh actual records before retrying.")
                if step["owner"] == "datasets":
                    value = privileges.perform(dict(kind="dataset", action=dataset_plan.action, selected=list(dataset_plan.selected),
                        root=str(dataset_plan.root), folder=str(dataset_folder(intent["folder"])), target=target,
                        plan_digest=plan_digest(dataset_plan)), emit, cancel, on_result=journal.dataset_result)
                    # Preserve individual owner results; a failed/cancelled batch
                    # prevents subsequent service startup and reports partial work.
                    if any(item["outcome"] != "succeeded" for item in value):
                        raise RuntimeError("Dataset batch incomplete. " + json.dumps(value))
                else:
                    action = step["action"]
                    request = dict(kind="service", action=action, target=target)
                    if action in {"install", "configure"}:
                        request.update(settings=intent["settings"], start=False)
                        optional = bool(service.HISTORY_FIELDS & intent["settings"].keys())
                        accepted_now = plan.get("history_outcome", {}).get("status") != "not_applied"
                        accepted_review = plan.get("history_reviewed", accepted_now)
                        skip_history = optional and not (accepted_now and accepted_review)
                        if skip_history:
                            request["settings"] = service.core_settings(intent["settings"])
                    if action == "install":
                        request.update(folder=str(service_folder(intent["folder"])), artifact_sha256=plan["artifact"]["sha256"])
                    if action == "startup":
                        request["mode"] = intent["startup"]
                    value = service.perform(request, emit, cancel)
                    if action in {"install", "configure"} and skip_history:
                        value = dict(value or {}, history_outcome={"status": "not_applied", "available": False,
                            "reason": "Recording settings not applied: override was rejected during Review or the optional check is now unavailable."})
                outcome, detail = "succeeded", "Owner operation completed and verified"
                if isinstance(value, dict) and value.get("conflicts"):
                    detail += "; retained integration conflicts: " + ", ".join(value["conflicts"])
                if isinstance(value, dict) and value.get("history_outcome"):
                    detail += "; " + value["history_outcome"]["reason"]
                expected = service.snapshot(target, emit)
            except Exception as error:
                failed = True
                outcome = "failed"
                # Native owners already redact logs. Do not persist arbitrary
                # exception text which could include secrets from validation.
                detail = "Owner operation failed; inspect the redacted session diagnostics. Refresh before retrying."
                emit(service.redact(str(error), intent["settings"].get("credentials", {})))
        item = {"owner": step["owner"], "action": step["action"], "outcome": outcome, "detail": detail}
        if outcome == "succeeded" and isinstance(value, dict):
            for field in ("core_outcome", "history_outcome"):
                if field in value:
                    item[field] = value[field]
        results.append(item); journal.record(index, outcome, detail)
    complete = not cancel.is_set() and all(item["outcome"] == "succeeded" for item in results)
    journal.finish(complete)
    return dict(complete=complete, results=results, journal=str(journal.path), recovery=journal.value["recovery"],
                history_outcome=plan.get("history_outcome"))


def execute_reviewed(plan, cancel, emit, *, demo=False):
    """Authorize one reviewed operation; demo never touches files or native tools."""
    if demo:
        results = [dict(owner=step["owner"], action=step["action"], outcome="cancelled" if cancel.is_set() else "simulated",
                        detail="Simulation only; no changes") for step in plan["steps"]]
        return dict(complete=bool(results) and not cancel.is_set(), results=results, journal=None, recovery="Simulation only")
    if plan.get("demo"):
        raise ValueError("A simulated plan cannot authorize native operations")
    from .authorization import run_authorized
    request = dict(kind="unified", action="execute", intent=plan["intent"], digest=plan["digest"])
    if service.HISTORY_FIELDS & plan["intent"]["settings"].keys():
        request["history_reviewed"] = plan.get("history_outcome", {}).get("status") == "applied"
    return run_authorized(request, emit, cancel)
