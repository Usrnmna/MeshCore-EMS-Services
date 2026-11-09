"""Bounded read-only integrity and observation checks for data reporting."""
import csv
import hashlib
from datetime import datetime, timezone
import time
from dataset_paths import checked_path


class IntegrityFailure(ValueError):
    """A recorded file or manifest differs from its expected identity."""


class VerificationLimit(ValueError):
    """The report cannot verify the complete collection within radio limits."""


class Budget:
    """Share a 64 MiB/four-second verification bound across a request."""
    def __init__(self):
        self.remaining = 64 * 1024 * 1024
        self.until = time.monotonic() + 4

    def verify(self, root, relative, expected):
        """Stream a safe file and compare both size and SHA-256 without writes."""
        if time.monotonic() > self.until:
            raise VerificationLimit("Verification deadline")
        if not isinstance(expected, dict):
            raise IntegrityFailure("Invalid inventory record")
        path = checked_path(root, relative)
        size = expected.get("bytes", expected.get("byte_count"))
        digest = expected.get("sha256")
        if type(size) is not int or size < 0 or not isinstance(digest, str) or len(digest) != 64:
            raise IntegrityFailure("Invalid fingerprint")
        if not path.is_file() or path.stat().st_size != size:
            raise IntegrityFailure("Missing or resized file")
        if size > self.remaining:
            raise VerificationLimit("Byte budget")
        hashed = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(65536):
                if time.monotonic() > self.until or len(chunk) > self.remaining:
                    raise VerificationLimit("Verification budget")
                self.remaining -= len(chunk)
                hashed.update(chunk)
        if hashed.hexdigest() != digest:
            raise IntegrityFailure("Checksum mismatch")
        return path


def verify_files(directory, files, budget):
    """Check every listed file; extra files are not certified by this check."""
    if not isinstance(files, dict) or not files:
        raise IntegrityFailure("No inventory")
    for relative, expected in files.items():
        budget.verify(directory, relative, expected)


def observation_status(directory, read_json):
    """Recalculate USGS snapshot freshness from observation times, never download time."""
    budget = Budget()
    pointer = read_json(directory / "observations.json")
    manifest_path = budget.verify(directory, pointer["manifest_path"], pointer)
    manifest = read_json(manifest_path)
    if manifest.get("kind") != "observations" or manifest.get("complete") is not True:
        raise IntegrityFailure("Incomplete observation snapshot")
    relative = "series_conditions.csv"
    file = budget.verify(manifest_path.parent, relative, manifest["files"][relative])
    from scripts.water_settings import load
    max_age = load()["reading_max_age"]
    now = datetime.now(timezone.utc).timestamp()
    fresh = stale = invalid = 0
    with file.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or reader.fieldnames.count("time") != 1:
            raise IntegrityFailure("Missing or ambiguous observation time")
        for row in reader:
            if time.monotonic() > budget.until:
                raise VerificationLimit("Observation budget")
            try:
                stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
                if stamp.utcoffset() is None:
                    raise ValueError("No timezone")
                age = now - stamp.timestamp()
                if age < -60:
                    raise ValueError("Future reading")
                if age > max_age:
                    stale += 1
                else:
                    fresh += 1
            except (ValueError, KeyError, TypeError):
                invalid += 1
    if not fresh + stale + invalid:
        return "water observations: no rows"
    return f"water observations: {fresh} fresh; {stale} stale; {invalid} invalid"
