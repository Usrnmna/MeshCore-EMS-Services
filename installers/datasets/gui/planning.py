"""Pure batch planning and checked selection of existing native installer artifacts."""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from .catalog import DATASETS, LABELS, ordered

ACTIONS = {
    "install_selected": "Install Selected",
    "uninstall_selected": "Uninstall Selected",
    "missing_packages": "Install All Missing Source Packages",
    "missing_data": "Install All Missing Datasets",
    "uninstall_all": "Uninstall All Dataset Packages and Their Managed Data",
}


def file_hash(path):
    """Stream the artifact hash without loading a large installer into memory."""
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def installer_artifact(folder, name, target):
    """Require one matching installer and its existing release checksum entry.

    Separate release directories avoid guessing a version or silently downgrading
    maintenance tools. Checksums detect damage; they do not authenticate publishers.
    """
    suffix = "windows-x64-setup.exe" if target == "windows-x64" else target + ".run"
    expression = re.compile(r"MeshCore-EMS-Data-" + re.escape(name) + r"-v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?-" + re.escape(suffix))
    folder = Path(folder).resolve()
    matches = [path for path in folder.glob("MeshCore-EMS-Data-*") if path.is_file() and expression.fullmatch(path.name)]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name} {target} installer in {folder}; found {len(matches)}")
    artifact = matches[0]
    entries = {}
    for line in (folder / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            digest, filename = parts
            filename = filename.lstrip("*")
            if filename in entries:
                raise ValueError("Duplicate checksum entry: " + filename)
            entries[filename] = digest.lower()
    expected = entries.get(artifact.name, "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or file_hash(artifact) != expected:
        raise ValueError("Missing or mismatched SHA256SUMS.txt entry: " + artifact.name)
    return artifact, expected


@dataclass(frozen=True)
class Operation:
    dataset: str
    kind: str
    command: tuple[str, ...]
    reason: str
    prefix: Path
    artifact_hash: str = ""


@dataclass
class Plan:
    action: str
    root: Path
    target: str
    selected: tuple[str, ...]
    operations: list[Operation] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    demo: bool = False
    registry_fingerprint: str = ""

    def text(self):
        """Describe the complete mutation plan, exact arguments and skipped items."""
        lines = [ACTIONS[self.action], "Data root: " + str(self.root), "Target: " + self.target]
        if self.demo:
            lines.append("DEMO: every operation is simulated; no programs will run.")
        lines.append("Setup includes maintenance tools AND initial data. Existing valid data is retained.")
        if self.action.startswith("uninstall"):
            lines.append("Removal includes package tools and managed data. Stop dataset consumers first.")
            lines.append("Modified, unowned and legacy files are retained under the existing policy. Purge is disabled.")
        for index, operation in enumerate(self.operations, 1):
            command = subprocess.list2cmdline(operation.command) if self.target == "windows-x64" else shlex.join(operation.command)
            lines.extend([f"{index}. {LABELS[operation.dataset][0]}: {operation.kind} — {operation.reason}", "   " + command])
            if operation.artifact_hash:
                lines.append("   SHA-256: " + operation.artifact_hash)
        lines.extend("SKIP: " + item for item in self.skipped)
        lines.extend("BLOCKED: " + item for item in self.blocked)
        if not self.operations:
            lines.append("No changes are required or available.")
        lines.append("Failure stops the remaining batch. Cancellation takes effect after the current package finishes.")
        return "\n".join(lines)


def make_plan(snapshot, action, selected, folder, *, demo=False):
    """Expand install prerequisites; never add unrequested dependent removals.

    Broken active data cannot be replaced by an install-only action. Explicit
    Install Selected can repair maintenance tools, but missing-only actions report
    damaged packages separately instead of treating them as absent.
    """
    if action not in ACTIONS:
        raise ValueError("Unknown action")
    selected = tuple(sorted(set(selected)))
    if set(selected) - DATASETS.keys():
        raise ValueError("Unknown selection")
    plan = Plan(action, snapshot.root, snapshot.target, selected, demo=demo)
    plan.registry_fingerprint = hashlib.sha256(json.dumps(snapshot.registry, sort_keys=True).encode()).hexdigest()
    states = snapshot.collections
    if action.endswith("selected"):
        targets = set(selected)
    elif action == "missing_packages":
        targets = {name for name, state in states.items() if state.package.state == "missing"}
    elif action == "missing_data":
        targets = {name for name, state in states.items() if state.data in ("missing", "incomplete", "unmanaged")}
    else:
        targets = {name for name, state in states.items() if state.package.state != "missing" or state.managed}
    if action.startswith("missing"):
        for name, state in states.items():
            if name not in targets:
                damaged = state.package.state == "broken" or state.data == "broken"
                plan.skipped.append(f"{name}: package {state.package.state}, data {state.data}. " +
                                    ("Use Install Selected to repair tools; inspect verify/update/rollback for damaged data."
                                     if damaged else "Already present."))
    removing = action.startswith("uninstall")
    requested = set(targets)
    if not removing:
        def include_dependencies(name):
            for dependency in DATASETS[name]:
                if states[dependency].data != "valid" and dependency not in targets:
                    targets.add(dependency)
                    include_dependencies(dependency)
        for name in list(targets):
            include_dependencies(name)
    names = ordered(targets)
    if removing:
        names.reverse()
    for name in names:
        state = states[name]
        package = state.package
        if package.root is not None and package.root != snapshot.root:
            plan.blocked.append(f"{name}: package uses {package.root}; select that data root. Root migration is not automatic.")
            continue
        if removing:
            outside = set(state.dependents) - targets
            if outside:
                plan.blocked.append(f"{name}: required by active/rollback packages {', '.join(sorted(outside))}. Select dependents explicitly.")
            elif package.state == "ready":
                plan.operations.append(Operation(name, "uninstall", package.uninstaller,
                                                 "Remove with the existing native uninstaller", package.prefix))
            elif package.state == "missing" and not state.managed:
                plan.skipped.append(name + ": no registered package or managed data")
            else:
                plan.blocked.append(name + ": maintenance tools are missing/broken; repair the package before removal. " + package.detail)
            continue
        if state.data == "broken":
            plan.blocked.append(name + ": active data/status is damaged; inspect verify/update/rollback before installation. " + state.detail)
            continue
        if package.state == "broken" and action.startswith("missing"):
            plan.blocked.append(name + ": incomplete maintenance package; use Install Selected to repair it.")
            continue
        if package.state == "ready" and state.data == "valid":
            plan.skipped.append(name + ": tools and active data already valid")
            continue
        if state.data != "valid" and state.dependency_error:
            plan.blocked.append(name + ": " + state.dependency_error)
            continue
        reason = "Selected collection" if name in requested else "Required prerequisite"
        if state.data == "unmanaged":
            reason += "; validate/import legacy data without changing the original"
        if package.state == "ready":
            plan.operations.append(Operation(name, "install_data", package.launcher + ("install",),
                                             reason + "; acquire missing data using installed tools", package.prefix))
        else:
            try:
                if demo:
                    artifact, digest = Path("demo-installers") / (name + ".demo"), ""
                else:
                    artifact, digest = installer_artifact(folder, name, snapshot.target)
                if snapshot.target == "windows-x64":
                    command = (str(artifact), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                               "/SP-", "/DATAROOT=" + str(snapshot.root), "/DIR=" + str(package.prefix))
                else:
                    command = ("/bin/bash", str(artifact), "--root", str(snapshot.root))
                plan.operations.append(Operation(name, "setup", command,
                                                 reason + "; setup tools and initial data", package.prefix, digest))
            except (OSError, ValueError) as error:
                plan.blocked.append(name + ": " + str(error))
    return plan
