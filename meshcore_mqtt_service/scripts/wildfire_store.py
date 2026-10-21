"""Atomic source snapshots and spatial candidates; SQLite connections stay local."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from shapely.geometry import shape


def encode(value):
    """Serialize stable, finite JSON for provenance and change comparisons."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Store:
    """One connection per process/thread, with read-only command connections."""

    def __init__(self, path, writable=False):
        self.path = Path(path).resolve()
        self.writable = writable
        if writable:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path, timeout=10)
            if self.db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                self.db.close()
                raise ValueError("Unsupported wildfire cache schema")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots(
                    source TEXT PRIMARY KEY, fetched REAL, attempted REAL,
                    error TEXT, digest TEXT, url TEXT, count INTEGER);
                CREATE TABLE IF NOT EXISTS features(
                    rowid INTEGER PRIMARY KEY, source TEXT, feature_id TEXT,
                    body TEXT NOT NULL, UNIQUE(source, feature_id));
                CREATE VIRTUAL TABLE IF NOT EXISTS feature_bounds USING rtree(
                    rowid, minx, maxx, miny, maxy);
                CREATE TABLE IF NOT EXISTS history(
                    source TEXT, captured REAL, digest TEXT, body TEXT,
                    PRIMARY KEY(source, captured));
                CREATE TABLE IF NOT EXISTS refresh_lease(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), owner TEXT, expires REAL);
                PRAGMA user_version=1;
            """)
        else:
            self.db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
            self.db.execute("PRAGMA query_only=ON")
        self.db.row_factory = sqlite3.Row
        if self.db.execute("PRAGMA user_version").fetchone()[0] != 1:
            self.db.close()
            raise ValueError("Unsupported wildfire cache schema")

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def status(self, source):
        row = self.db.execute("SELECT * FROM snapshots WHERE source=?", (source,)).fetchone()
        return dict(row) if row else {"source": source, "fetched": None, "error": "Not initialized"}

    def statuses(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM snapshots ORDER BY source")]

    def features(self, source, bounds=None):
        """Use an R-tree to narrow candidates; callers perform exact intersections."""
        if bounds is None:
            rows = self.db.execute("SELECT body FROM features WHERE source=? ORDER BY feature_id", (source,))
        else:
            west, south, east, north = bounds
            rows = self.db.execute("""
                SELECT f.body FROM features f JOIN feature_bounds b ON b.rowid=f.rowid
                WHERE f.source=? AND b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?
                ORDER BY f.feature_id""", (source, east, west, north, south))
        return [json.loads(r[0]) for r in rows]

    def replace(self, source, features, url, now=None, history_days=7):
        """Validate a complete batch before atomically replacing one source.

        Prior successful snapshots survive errors. Changed observations are retained
        for bounded local history; geometry is never synthesized for point-only fires.
        """
        now = time.time() if now is None else now
        rows, seen = [], set()
        for feature in features:
            key = str(feature["id"])
            if key in seen or not isinstance(feature.get("properties"), dict):
                raise ValueError(f"Duplicate ID or invalid properties in {source}")
            seen.add(key)
            bounds = None
            if feature.get("geometry") is not None:
                geometry = shape(feature["geometry"])
                if geometry.is_empty or not geometry.is_valid:
                    raise ValueError(f"Invalid geometry in {source}/{key}")
                bounds = geometry.bounds
            rows.append((key, encode(feature), bounds))
        body = encode(features)
        digest = hashlib.sha256(body.encode()).hexdigest()
        old = self.status(source)
        with self.db:
            self.db.execute("DELETE FROM feature_bounds WHERE rowid IN (SELECT rowid FROM features WHERE source=?)", (source,))
            self.db.execute("DELETE FROM features WHERE source=?", (source,))
            for key, record, bounds in rows:
                cursor = self.db.execute("INSERT INTO features(source,feature_id,body) VALUES(?,?,?)", (source, key, record))
                if bounds:
                    west, south, east, north = bounds
                    self.db.execute("INSERT INTO feature_bounds VALUES(?,?,?,?,?)", (cursor.lastrowid, west, east, south, north))
            self.db.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?,?,?,?)",
                            (source, now, now, None, digest, url, len(rows)))
            if digest != old.get("digest"):
                self.db.execute("INSERT OR REPLACE INTO history VALUES(?,?,?,?)", (source, now, digest, body))
            else:
                # Last-seen history must advance even when the provider's content is unchanged.
                self.db.execute("""UPDATE history SET captured=? WHERE source=? AND digest=?
                    AND captured=(SELECT MAX(captured) FROM history WHERE source=?)""",
                    (now, source, digest, source))
            self.db.execute("DELETE FROM history WHERE captured<?", (now - history_days * 86400,))

    def fail(self, source, error, now=None):
        """Record a failed attempt without altering good data or its acquisition time."""
        now = time.time() if now is None else now
        with self.db:
            self.db.execute("""
                INSERT INTO snapshots(source,attempted,error) VALUES(?,?,?)
                ON CONFLICT(source) DO UPDATE SET attempted=excluded.attempted,error=excluded.error
            """, (source, now, str(error)[:500]))

    @contextmanager
    def lease(self, seconds=600):
        """Exclude competing writers; expiry recovers a killed bounded refresh process."""
        owner, now = str(uuid.uuid4()), time.time()
        self.db.execute("BEGIN IMMEDIATE")
        row = self.db.execute("SELECT expires FROM refresh_lease WHERE singleton=1").fetchone()
        if row and row[0] > now:
            self.db.rollback()
            raise RuntimeError("Another wildfire refresh is already running")
        self.db.execute("INSERT OR REPLACE INTO refresh_lease VALUES(1,?,?)", (owner, now + seconds))
        self.db.commit()
        try:
            yield
        finally:
            with self.db:
                self.db.execute("DELETE FROM refresh_lease WHERE owner=?", (owner,))
