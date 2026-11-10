"""Bounded optional channel recording and independent read-only local queries.

The receive path only copies bounded data and tries admission. The daemon owns
all storage, identity pins and maintenance. Admission is never a commit receipt.
"""
from __future__ import annotations

import base64
from collections import deque
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
from typing import Mapping, Literal

RETENTION_SECONDS = 86400
SWEEP_SECONDS = 60
RECOVERY_SECONDS = 60
MAX_RECORDS = 1024
MAX_PENDING_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 64 * 1024
MAX_STORAGE_BYTES = 256 * 1024 * 1024
FREE_RESERVE_BYTES = 512 * 1024 * 1024
MAX_PAGE_BYTES = 2 * 1024 * 1024
BATCH_SIZE = 32
BUSY_SECONDS = 1
RETRY_SECONDS = 5
SCHEMA_VERSION = 1
ID_PATTERN = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
OfferResult = Literal['queued', 'not_target', 'unverified', 'full', 'contended',
                      'oversized', 'unavailable', 'stopping']


def _now():
    return datetime.now(timezone.utc)


def _us(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('An aware datetime is required')
    delta = value.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def _date(value):
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=value)


class HistoryUnavailable(RuntimeError):
    """Storage is missing, inaccessible or incompatible; this is not an empty log."""


@dataclass(frozen=True)
class HistorySettings:
    enabled: bool
    channel_id: str | None
    channel: Mapping[str, object] | None
    identity: str | None = None
    core: bool = False


@dataclass(frozen=True)
class ChannelObservation:
    index: int
    name: str
    identity: str
    observed_at: datetime


@dataclass(frozen=True)
class BindingEvidence:
    verification: str = 'not_performed'
    binding: ChannelObservation | None = None


@dataclass(frozen=True)
class HistoryStatus:
    state: str
    offered: int
    admitted: int
    committed: int
    pending: int
    pending_bytes: int
    missed: int
    reasons: dict
    observed_at: datetime
    last_error: str | None
    duplicates: int = 0
    clock_corrections: int = 0


@dataclass(frozen=True)
class ChannelMessage:
    event_id: str
    received_at: datetime
    channel_id: str
    channel_name: str
    channel_identity: str
    channel_index: int
    binding_source: str
    binding_observed_at: datetime
    text: str | None
    sender: str | None
    source_message_id: object
    sender_timestamp: int | None
    payload: dict
    attributes: dict
    device: dict


@dataclass(frozen=True)
class RecordedChannel:
    channel_id: str
    channel_name: str
    latest_received_at: datetime


@dataclass(frozen=True)
class HistoryPage:
    messages: list[ChannelMessage]
    next_cursor: str | None
    queried_at: datetime
    window_start: datetime
    query_upper: datetime


def validate_history_config(config: Mapping[str, object]) -> HistorySettings:
    """Strict optional-feature validation; callers isolate errors from core checks."""
    from channels import validate_channels, expected_key
    section = config.get('channel_history', {})
    if not isinstance(section, dict) or set(section) - {'enabled', 'channel_id', 'channel'}:
        raise ValueError('Invalid channel_history settings')
    enabled = section.get('enabled', False)
    if type(enabled) is not bool:
        raise ValueError('History enabled must be boolean')
    if not enabled:
        return HistorySettings(False, section.get('channel_id'), section.get('channel'))
    channel_id = section.get('channel_id')
    if not isinstance(channel_id, str) or not ID_PATTERN.fullmatch(channel_id):
        raise ValueError('Select a valid stable history channel ID')
    registry = config.get('responder', {}).get('channels', {})
    channel = section.get('channel')
    core = channel is None
    if core:
        if channel_id not in registry:
            raise ValueError('History service channel is not configured')
        channel = registry[channel_id]
    elif channel_id in registry:
        raise ValueError('Recording-only ID must not collide with a service channel')
    validate_channels({'channels': {channel_id: channel}, 'commands': {}})
    if not core and channel['mqtt_export'] is not False:
        raise ValueError('Recording-only channels require mqtt_export=false')
    key = expected_key(channel)
    return HistorySettings(True, channel_id, dict(channel),
                           hashlib.sha256(key).hexdigest() if key is not None else None, core)


def _snapshot(value):
    """Bound traversal before encoding; never truncate a message or invoke repr hooks."""
    remaining = MAX_SNAPSHOT_BYTES
    nodes = 0

    def copy(item, depth=0):
        nonlocal remaining, nodes
        nodes += 1
        if depth > 32 or nodes > 8192 or remaining < 0:
            raise ValueError('Snapshot exceeds budget')
        if isinstance(item, Enum):
            item = item.name
        if isinstance(item, bytes):
            if len(item) * 2 > remaining: raise ValueError('Snapshot exceeds budget')
            item = {'encoding': 'hex', 'data': item.hex()}
        if isinstance(item, str):
            if len(item) > remaining: raise ValueError('Snapshot exceeds budget')
            remaining -= len(item.encode('utf-8')) + 2
            return item
        if item is None or type(item) in (bool, int, float):
            if type(item) is int and item.bit_length() > 256: raise ValueError('Oversized integer')
            if type(item) is float and not math.isfinite(item): raise ValueError('Nonfinite metadata')
            remaining -= 32
            return item
        if isinstance(item, dict):
            if len(item) > 8192: raise ValueError('Snapshot exceeds budget')
            result = {}
            for key, val in item.items():
                if not isinstance(key, str): raise ValueError('Metadata key must be text')
                key = copy(key, depth+1)
                result[key] = '[redacted]' if key.lower() in {
                    'private_key', 'priv_key', 'secret', 'password', 'channel_secret'} else copy(val, depth+1)
            return result
        if isinstance(item, (list, tuple)):
            if len(item) > 8192: raise ValueError('Snapshot exceeds budget')
            return [copy(part, depth+1) for part in item]
        raise ValueError('Unsupported metadata type')

    encoded = json.dumps(copy(value), ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ValueError('Snapshot exceeds budget')
    return encoded


class ChannelHistoryRecorder:
    """Single receive-thread producer and daemon writer with immediate admission.

    Public methods perform no filesystem access. Status is an observational copy,
    not an atomic transaction across producer and worker counters.
    """
    def __init__(self, db_path: Path, *, settings: HistorySettings):
        """Allocate bounded producer state without opening files or starting work."""
        self.path = Path(db_path)
        self.settings = settings
        self._observations = ()
        self._queue = deque()
        self._lock = threading.Lock()
        self._pending = self._bytes = 0
        self._offered = self._admitted = self._committed = self._duplicates = 0
        self._reasons = {}
        self._worker_missed = 0
        self._worker_reasons = {}
        self._state, self._error = 'initializing', None
        self._stopping = False
        self._thread = None
        self._next_sweep = 0
        self._next_report = 0
        self._clock_sample = None
        self._clock_corrections = 0

    def start(self):
        """Start once; do not await initialization or any storage result."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='channel-history', daemon=True)
            self._thread.start()

    def observe_binding(self, observation: ChannelObservation):
        """Replace at most one of 256 sanitized slots, without a worker lock."""
        if not isinstance(observation, ChannelObservation):
            observation = ChannelObservation(*observation)
        if type(observation.index) is not int or not 0 <= observation.index <= 255:
            return
        self._observations = tuple(x for x in self._observations if x.index != observation.index) + (observation,)

    def _reject(self, reason, when):
        count, first, _ = self._reasons.get(reason, (0, when, when))
        self._reasons[reason] = (count+1, first, when)
        return reason

    def offer_received(self, record: Mapping[str, object], *, evidence: BindingEvidence) -> OfferResult:
        """Offer a whole reception; rejected observations never delay primary work."""
        if record.get('event') != 'CHANNEL_MSG_RECV':
            return 'not_target'
        if not self.settings.enabled:
            return 'not_target'
        payload = record.get('payload', {})
        if not isinstance(payload, dict): return 'not_target'
        if self.settings.core and payload.get('channel_id') not in (None, self.settings.channel_id):
            return 'not_target'
        if 'slot' in self.settings.channel and payload.get('channel_idx') != self.settings.channel['slot']:
            return 'not_target'
        matches = tuple(x for x in self._observations
                        if x.name == self.settings.channel['name'] and
                        ('slot' not in self.settings.channel or x.index == self.settings.channel['slot']))
        observation = evidence.binding if evidence.verification == 'passed' else (matches[0] if len(matches) == 1 else None)
        if observation and payload.get('channel_idx') != observation.index:
            return 'not_target'
        self._offered += 1
        when = record.get('received_at')
        if self._stopping: return self._reject('stopping', when)
        if evidence.verification == 'failed' or observation is None or (
            self.settings.core and evidence.verification != 'passed'
        ) or (self.settings.identity and observation.identity != self.settings.identity):
            return self._reject('unverified', when)
        if observation.name != self.settings.channel['name'] or not re.fullmatch(r'[0-9a-f]{64}', observation.identity or ''):
            return self._reject('unverified', when)
        if self._state not in ('initializing', 'ready'):
            return self._reject('unavailable', when)
        try:
            snapshot = _snapshot(record)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return self._reject('oversized', when)
        if not self._lock.acquire(blocking=False):
            return self._reject('contended', when)
        try:
            if self._pending >= MAX_RECORDS or self._bytes + len(snapshot) > MAX_PENDING_BYTES:
                return self._reject('full', when)
            self._queue.append((snapshot, observation, evidence.verification))
            self._pending += 1
            self._bytes += len(snapshot)
            self._admitted += 1
            return 'queued'
        finally:
            self._lock.release()

    def status(self):
        """Copy bounded counters without worker locks or diagnostic I/O."""
        return HistoryStatus('stopping' if self._stopping else self._state,
                             self._offered, self._admitted, self._committed,
                             self._pending, self._bytes,
                             sum(v[0] for v in self._reasons.values()) + self._worker_missed,
                             dict(self._reasons, **self._worker_reasons), _now(), self._error,
                             self._duplicates, self._clock_corrections)

    def _observe_clock(self):
        """Count UTC corrections over one second against monotonic elapsed time.

        Reception timestamps remain untouched. Retention always uses current UTC;
        the counter explains early expiry or temporarily future-dated records.
        """
        sample = (_us(_now()) / 1000000, time.monotonic())
        if self._clock_sample is not None:
            utc, monotonic = self._clock_sample
            if abs((sample[0] - utc) - (sample[1] - monotonic)) > 1:
                self._clock_corrections += 1
        self._clock_sample = sample

    def stop_nowait(self):
        """Close admission; no joining or flushing, including on normal restart."""
        self._stopping = True
        return self.status()

    def _space(self, growth=0):
        """Conservative local budget; never reclaim unrelated or unexpired data."""
        size = sum(p.stat().st_size for p in (self.path, Path(str(self.path)+'-wal'),
                    Path(str(self.path)+'-shm'), self.path.parent/'status.json',
                    self.path.parent/'status.json.tmp') if p.exists())
        if size + growth + 1048576 > MAX_STORAGE_BYTES or shutil.disk_usage(self.path.parent).free < FREE_RESERVE_BYTES + growth + 1048576:
            raise OSError('History resource budget exhausted')

    def _open(self):
        """Initialize the isolated WAL store and prune it before accepting inserts."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._space()
        db = sqlite3.connect(self.path, timeout=BUSY_SECONDS)
        try:
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0, SCHEMA_VERSION):
                raise HistoryUnavailable('Unsupported history schema')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            page_size = db.execute('PRAGMA page_size').fetchone()[0]
            db.execute(f'PRAGMA max_page_count={MAX_STORAGE_BYTES // (2 * page_size)}')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS history_bindings (
                    channel_id TEXT PRIMARY KEY, name TEXT NOT NULL, identity TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS channel_messages (
                    event_id TEXT PRIMARY KEY, received_at_us INTEGER NOT NULL,
                    channel_id TEXT NOT NULL, channel_name TEXT NOT NULL,
                    channel_identity TEXT NOT NULL, channel_index INTEGER NOT NULL,
                    binding_source TEXT NOT NULL, binding_observed_at_us INTEGER NOT NULL,
                    text TEXT, sender TEXT, source_message_id_json TEXT, sender_timestamp INTEGER,
                    payload_json TEXT NOT NULL, attributes_json TEXT NOT NULL, device_json TEXT NOT NULL,
                    reception_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS history_time ON channel_messages(received_at_us);
                CREATE INDEX IF NOT EXISTS history_channel ON channel_messages(channel_id,received_at_us,event_id);
                CREATE INDEX IF NOT EXISTS history_sender ON channel_messages(channel_id,sender,received_at_us);
            ''')
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            self._sweep(db)
            return db
        except BaseException:
            db.close()
            raise

    def _sweep(self, db):
        """Remove expired rows and schedule maintenance independently of traffic."""
        db.execute('DELETE FROM channel_messages WHERE received_at_us<=?',
                   (_us(_now()) - RETENTION_SECONDS*1000000,))
        db.commit()
        db.execute('PRAGMA wal_checkpoint(PASSIVE)')
        self._next_sweep = time.monotonic() + SWEEP_SECONDS

    def _insert(self, db, job):
        """Pin channel identity and insert one immutable reception idempotently."""
        snapshot, binding, verification = job
        record = json.loads(snapshot)
        payload = record['payload']
        receipt = _us(datetime.fromisoformat(record['received_at']))
        event_id = record['id']
        if not isinstance(event_id, str) or not event_id:
            raise ValueError('Missing reception ID')
        previous = db.execute('SELECT reception_json FROM channel_messages WHERE event_id=?', (event_id,)).fetchone()
        if previous:
            if previous[0] != snapshot.decode('utf-8'):
                raise ValueError('Conflicting reception ID')
            return False
        pin = db.execute('SELECT name,identity FROM history_bindings WHERE channel_id=?', (self.settings.channel_id,)).fetchone()
        if pin and pin != (binding.name, binding.identity):
            raise ValueError('History identity changed; select a new ID')
        db.execute('INSERT INTO history_bindings VALUES (?,?,?) ON CONFLICT(channel_id) DO NOTHING',
                   (self.settings.channel_id, binding.name, binding.identity))
        text = payload.get('text')
        sender = payload.get('sender')
        stamp = payload.get('sender_timestamp')
        source_id = payload.get('message_id')
        db.execute('INSERT INTO channel_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
            event_id, receipt, self.settings.channel_id, binding.name, binding.identity, binding.index,
            'core_verification' if verification == 'passed' else 'passive_snapshot', _us(binding.observed_at),
            text if isinstance(text, str) else None, sender if isinstance(sender, str) else None,
            json.dumps(source_id) if source_id is not None else None,
            stamp if type(stamp) is int and -(2**63) <= stamp < 2**63 else None,
            json.dumps(payload, ensure_ascii=False), json.dumps(record.get('attributes', {}), ensure_ascii=False),
            json.dumps(record.get('device', {}), ensure_ascii=False), snapshot.decode('utf-8')))
        return True

    def _run(self):
        """Own storage, retry and idle maintenance; failures never escape to supervision."""
        db = None
        recovery_at = 0
        try:
            while not self._stopping:
                self._observe_clock()
                if db is None:
                    if time.monotonic() < recovery_at:
                        time.sleep(.05)
                        continue
                    try:
                        db = self._open()
                        self._state, self._error = 'ready', None
                    except Exception as error:
                        self._state, self._error = 'unavailable', type(error).__name__
                        recovery_at = time.monotonic() + RECOVERY_SECONDS
                        self._discard()
                        self._report()
                        continue
                batch = []
                with self._lock:
                    for _ in range(min(BATCH_SIZE, len(self._queue))):
                        batch.append(self._queue.popleft())
                committed = False
                try:
                    if time.monotonic() >= self._next_sweep:
                        self._sweep(db)
                    if batch:
                        self._space(sum(len(job[0]) for job in batch) * 4)
                        deadline = time.monotonic() + RETRY_SECONDS
                        while True:
                            try:
                                inserted = sum(self._insert(db, job) for job in batch)
                                db.commit()
                                self._committed += inserted
                                self._duplicates += len(batch) - inserted
                                committed = True
                                break
                            except sqlite3.OperationalError as error:
                                db.rollback()
                                if 'locked' not in str(error).lower() or time.monotonic() >= deadline or self._stopping:
                                    raise
                        db.execute('PRAGMA wal_checkpoint(PASSIVE)')
                except Exception as error:
                    if not committed:
                        self._missed_jobs(batch)
                    self._state, self._error = 'unavailable', type(error).__name__
                    if db is not None:
                        db.close()
                        db = None
                    recovery_at = time.monotonic() + RECOVERY_SECONDS
                    self._discard()
                finally:
                    with self._lock:
                        self._pending -= len(batch)
                        self._bytes -= sum(len(job[0]) for job in batch)
                self._report()
                time.sleep(.01 if batch else .05)
        except Exception as error:
            self._state, self._error = 'unavailable', type(error).__name__
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    self._state, self._error = 'unavailable', 'close_failed'

    def _discard(self):
        """Bounded worker-only cleanup of failed queued work; no producer waits."""
        with self._lock:
            self._missed_jobs(self._queue)
            self._pending -= len(self._queue)
            self._bytes -= sum(len(job[0]) for job in self._queue)
            self._queue.clear()

    def _missed_jobs(self, jobs):
        """Aggregate worker failures without retaining message bodies or ID lists."""
        if not jobs: return
        first = json.loads(jobs[0][0])['received_at']
        last = json.loads(jobs[-1][0])['received_at']
        count, previous, _ = self._worker_reasons.get('storage', (0, first, last))
        self._worker_reasons = {'storage': (count+len(jobs), previous, last)}
        self._worker_missed += len(jobs)

    def _report(self):
        """Best-effort bounded diagnostic snapshot, never using primary log locks."""
        if time.monotonic() < self._next_report: return
        self._next_report = time.monotonic() + SWEEP_SECONDS
        try:
            from dataclasses import asdict
            self._space(32768)
            status = asdict(self.status())
            status['observed_at'] = status['observed_at'].isoformat()
            content = json.dumps(status, ensure_ascii=True)
            if len(content) > 16384: return
            temporary = self.path.parent / 'status.json.tmp'
            temporary.write_text(content, encoding='utf-8')
            temporary.replace(self.path.parent / 'status.json')
        except Exception:
            pass


def _reader(path):
    try:
        db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=BUSY_SECONDS)
        db.execute('PRAGMA query_only=ON')
        deadline = time.monotonic() + 5
        db.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
        if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
            raise HistoryUnavailable('Unsupported history schema')
        return db
    except Exception as error:
        if 'db' in locals(): db.close()
        raise HistoryUnavailable('History database unavailable') from error


def _message(row):
    """Decode one stored record; damaged storage is distinct from invalid selectors."""
    try:
        return ChannelMessage(row[0], _date(row[1]), *row[2:7], _date(row[7]),
                              row[8], row[9], json.loads(row[10]) if row[10] is not None else None,
                              row[11], json.loads(row[12]), json.loads(row[13]), json.loads(row[14]))
    except (ValueError, TypeError, OverflowError, IndexError) as error:
        raise HistoryUnavailable('History record is damaged') from error


def _filters(channel_id, start, end, sender, sender_prefix, now):
    """Validate selectors and intersect every query with the exact current window."""
    if not isinstance(channel_id, str) or not ID_PATTERN.fullmatch(channel_id):
        raise ValueError('Invalid channel ID')
    if sender is not None and sender_prefix is not None:
        raise ValueError('Choose only one sender selector')
    for value in (sender, sender_prefix):
        if value is not None and (not isinstance(value, str) or len(value.encode('utf-8')) > 4096):
            raise ValueError('Invalid sender selector')
    clauses = ['channel_id=?', 'received_at_us>?', 'received_at_us<=?']
    values = [channel_id, _us(now)-RETENTION_SECONDS*1000000, _us(now)]
    for value, clause in ((start, 'received_at_us>=?'), (end, 'received_at_us<?')):
        if value is not None:
            clauses.append(clause); values.append(_us(value))
    if start is not None and end is not None and _us(start) > _us(end):
        raise ValueError('Start must not follow end')
    if sender is not None:
        clauses.append('sender=?'); values.append(sender)
    if sender_prefix is not None:
        prefix = sender_prefix + ': '
        clauses.append('substr(text,1,?)=?'); values.extend((len(prefix), prefix))
    return clauses, values


def read_recent_messages(db_path: Path, *, channel_id: str, start=None, end=None,
                         sender=None, sender_prefix=None) -> list[ChannelMessage]:
    """Return all committed matches in the current window; never consume or mutate."""
    clauses, values = _filters(channel_id, start, end, sender, sender_prefix, _now())
    try:
        with closing(_reader(db_path)) as db:
            return [_message(row) for row in db.execute(
                'SELECT * FROM channel_messages WHERE '+' AND '.join(clauses)+' ORDER BY received_at_us,event_id', values)]
    except sqlite3.Error as error:
        raise HistoryUnavailable('History query failed') from error


def list_recorded_channels(db_path: Path) -> list[RecordedChannel]:
    """List only channels with records in the current retention window."""
    now = _us(_now())
    try:
        with closing(_reader(db_path)) as db:
            return [RecordedChannel(id, name, _date(when)) for id, name, when in db.execute(
                'SELECT channel_id,channel_name,MAX(received_at_us) FROM channel_messages '
                'WHERE received_at_us>? AND received_at_us<=? GROUP BY channel_id ORDER BY channel_id',
                (now-RETENTION_SECONDS*1000000, now))]
    except sqlite3.Error as error:
        raise HistoryUnavailable('History catalog failed') from error


def read_message_page(db_path: Path, *, channel_id: str, start=None, end=None,
                      sender=None, sender_prefix=None, page_size=200, cursor=None) -> HistoryPage:
    """Bounded newest-first keyset page; expiration is reapplied on every call."""
    if type(page_size) is not int or not 1 <= page_size <= 200:
        raise ValueError('Page size must be 1..200')
    now = _now()
    clauses, values = _filters(channel_id, start, end, sender, sender_prefix, now)
    identity = hashlib.sha256(json.dumps([channel_id, _us(start) if start else None,
        _us(end) if end else None, sender, sender_prefix], ensure_ascii=False).encode()).hexdigest()
    upper = _us(now)
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or len(cursor) > 2048: raise ValueError()
            data = json.loads(base64.urlsafe_b64decode(cursor.encode('ascii')))
            if set(data) != {'filter','upper','time','id'} or data['filter'] != identity:
                raise ValueError()
            if type(data['upper']) is not int or type(data['time']) is not int or not isinstance(data['id'], str) or len(data['id']) > 128:
                raise ValueError()
            _date(data['upper']); _date(data['time'])
            upper = data['upper']
            clauses.append('(received_at_us,event_id)<(?,?)')
            values.extend((data['time'], data['id']))
        except Exception as error:
            raise ValueError('Invalid or mismatched history cursor') from error
    clauses.append('received_at_us<=?'); values.append(upper)
    try:
        with closing(_reader(db_path)) as db:
            rows = db.execute('SELECT * FROM channel_messages WHERE '+' AND '.join(clauses)+
                              ' ORDER BY received_at_us DESC,event_id DESC LIMIT ?', values+[page_size+1]).fetchall()
    except sqlite3.Error as error:
        raise HistoryUnavailable('History page failed') from error
    selected, size = [], 512
    for row in rows[:page_size]:
        cost = len(json.dumps(row, ensure_ascii=True).encode()) * 2
        if size + cost > MAX_PAGE_BYTES:
            if not selected: raise HistoryUnavailable('History record exceeds response budget')
            break
        selected.append(row); size += cost
    next_cursor = None
    if len(rows) > len(selected) and selected:
        last = selected[-1]
        next_cursor = base64.urlsafe_b64encode(json.dumps(dict(
            filter=identity, upper=upper, time=last[1], id=last[0])).encode()).decode()
    return HistoryPage([_message(row) for row in selected], next_cursor, now,
                       now-timedelta(seconds=RETENTION_SECONDS), _date(min(upper, _us(end)) if end else upper))
