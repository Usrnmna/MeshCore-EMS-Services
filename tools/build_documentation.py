"""Collect a relocatable operational documentation tree for desktop bundles."""

from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit

from distribution_policy import is_local_reference, validate_paths


def source_files(root):
    """Follow maintained local links without copying environments or runtime data.

    Operational guides keep their repository-relative layout. Linked source
    examples are copied only from the service builder's maintained inventory;
    generated dataset references remain outside the desktop application.
    """
    import build_installers
    root = Path(root)
    allowed = set(build_installers.source_files())
    allowed.update(root.glob("RELEASE_*.md"))
    pending = [root / "docs" / name for name in (
        "DESKTOP_INSTALLATION.md", "UNIFIED_INSTALLER.md", "DATA_PACKAGES.md", "DATASET_GUI.md")]
    selected = set()
    while pending:
        path = pending.pop()
        if path in selected or path not in allowed:
            continue
        selected.add(path)
        if path.suffix != ".md":
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            # Historical release notes retain their original Windows encoding.
            text = raw.decode("cp1252")
        text = re.sub(r"(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$", "", text)
        for match in re.finditer(r"\]\(([^\n)]+)\)", text):
            target = match[1].strip().strip("<>")
            if urlsplit(target).scheme:
                continue
            filename = target.split("#", 1)[0]
            if not filename:
                continue
            destination = (path.parent / unquote(filename)).resolve()
            if destination.is_relative_to(root) and not is_local_reference(destination.relative_to(root)):
                pending.append(destination)
    return validate_paths(selected, root)


def copy_documentation(root, destination):
    """Copy linked guides and examples into a new tree with unchanged relative paths."""
    root, destination = Path(root), Path(destination)
    selected = source_files(root)
    for source in selected:
        target = destination / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".md":
            target.write_text(render_document(source, root, set(selected)), encoding="utf-8", newline="\n")
        else:
            shutil.copy2(source, target)


def render_document(source, root, selected):
    """Make separately installed data references explicit in the packaged copy.

    Some source READMEs contain machine-maintained linked inventory rows. Their
    original bytes and updater contract stay unchanged; only the distributable
    copy renders unavailable dataset files as paths instead of broken links.
    """
    raw = source.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    converted = False

    def replace(match):
        nonlocal converted
        target = match[2].strip().strip("<>")
        if urlsplit(target).scheme or target.startswith("#"):
            return match[0]
        filename = target.split("#", 1)[0]
        resolved = (source.parent / unquote(filename)).resolve()
        if resolved in selected or any(p.is_relative_to(resolved) for p in selected):
            return match[0]
        relative = resolved.relative_to(root).as_posix()
        if not relative.startswith("data/"):
            raise ValueError("Unresolved packaged documentation link: " + relative)
        converted = True
        return match[1] + " (`" + filename + "`)"

    output, fenced = [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fenced is None:
                fenced = marker[1][0]
            elif marker[1][0] == fenced:
                fenced = None
        elif fenced is None:
            line = re.sub(r"\[([^\]\n]+)\]\(([^\n)]+)\)", replace, line)
        output.append(line)
    if converted:
        output.insert(1, "\nDataset file paths refer to separately installed data; these files are not included in this documentation bundle.\n")
    return "".join(output)
