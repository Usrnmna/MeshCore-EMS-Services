"""Shared distribution boundary for local development references.

Selection rules do not depend on Git or the presence of the excluded directory.
Collectors omit local references; final tree/provenance checks reject accidental
reintroduction before an archive or manifest is written.
"""

from pathlib import Path, PurePosixPath


def is_local_reference(relative):
    """Identify planning paths, including copies beneath a bundle's source tree."""
    parts = PurePosixPath(str(relative).replace("\\", "/")).parts
    parts = tuple(part.casefold() for part in parts)
    return any(pair == ("docs", "superpowers") for pair in zip(parts, parts[1:]))


def validate_paths(paths, root):
    """Reject local references in explicit build inputs; return normalized paths."""
    root = Path(root).resolve()
    selected = sorted(set(map(Path, paths)))
    for path in selected:
        relative = path.resolve().relative_to(root)
        if is_local_reference(relative):
            raise ValueError("Local development references cannot enter a distribution")
    return selected


def validate_tree(root):
    """Reject local planning paths in a completed staging or application tree."""
    root = Path(root)
    for path in root.rglob("*"):
        if is_local_reference(path.relative_to(root)):
            raise ValueError("Local development references cannot enter a distribution")
