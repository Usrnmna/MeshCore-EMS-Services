"""Read advisory root hints after independent maintenance packages are removed.

Hints neither activate data nor establish ownership. A suggestion is returned
only when the hinted dataset has an actual managed registry selection and a
matching verified receipt beneath that root. Discovery never creates storage.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import stat

from installers.datasets import manage


def _fixed_directory():
    """Locate existing hint storage without calling a directory-creating helper."""
    if os.name == "nt":
        from .locking import lock_directory
        base = lock_directory()
    else:
        base = Path("/var/lib/meshcore-ems-maintenance")
    return base / "retained-roots"


@contextmanager
def _protected_hints(path):
    """Read only protected advisory storage; denied access requests authorization."""
    if os.name == "nt":
        from .windows_trust import protected_paths
        with protected_paths([path]):
            yield
        return
    for current in (path, *path.parents):
        metadata = current.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise PermissionError("Retained-root hints require protected root-owned storage")
    yield


def _read_hint(path):
    """Read one bounded regular hint, retaining no authority beyond its pathname."""
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError("Retained-root hint must be a regular file")
    if metadata.st_size > 4096:
        raise ValueError("Retained-root hint is oversized")
    with path.open("rb") as stream:
        value = stream.read(4097)
    lines = value.decode("utf-8-sig").splitlines()
    if len(value) > 4096 or len(lines) != 1 or not lines[0] or any(ord(character) < 32 for character in lines[0]):
        raise ValueError("Retained-root hint must contain one absolute directory")
    root = Path(lines[0])
    if not root.is_absolute() or root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
        raise ValueError("Retained-root hint must identify an absolute non-linked directory")
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError("Retained dataset root is no longer a directory")
    return root.resolve()


def discover(emit=lambda _: None, *, directory=None):
    """Group receipt-verified retained roots without modifying hints or registries.

    Missing storage returns no suggestions. Permission errors propagate so the
    existing desktop authorization path can retry protected discovery. Invalid
    or stale hints are reported without being treated as data ownership proof.
    ``directory`` supports isolated fixtures; native callers use fixed storage.
    """
    directory = Path(directory) if directory is not None else _fixed_directory()
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        return []
    if not stat.S_ISDIR(metadata.st_mode) or directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
        raise ValueError("Retained-root hint storage cannot be linked")
    grouped = {}
    with _protected_hints(directory):
        for dataset in sorted(manage.DATASETS):
            hint = directory / (dataset + ".txt")
            try:
                root = _read_hint(hint)
                state = manage.registry(root)
                entry = state["datasets"].get(dataset, {})
                records = [entry.get("active"), entry.get("previous")]
                verified = False
                for record in records:
                    if not isinstance(record, dict) or record.get("legacy"):
                        continue
                    try:
                        manage.verify_record(root, dataset, record)
                        verified = True
                    except PermissionError:
                        raise
                    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
                        emit(f"Retained data at {root}: {dataset} selection needs inspection: {error}")
                if verified:
                    grouped.setdefault(str(root), []).append(dataset)
                else:
                    emit(f"Retained-root hint for {dataset} at {root} has no verified managed selection. The hint grants no ownership; retained files were not changed.")
            except FileNotFoundError:
                continue
            except PermissionError:
                raise
            except (OSError, ValueError, KeyError, TypeError, RecursionError, UnicodeError) as error:
                emit(f"Retained-root hint {dataset} was not adopted: {error}. No retained files were changed.")
    return [{"root": root, "datasets": sorted(set(names)),
             "verification": "At least one retained selection per listed dataset has matching verified receipts; hints establish no ownership"}
            for root, names in sorted(grouped.items())]
