"""Bounded NWS transport and current-only forecast caching in the service runtime."""
from contextlib import closing
from email.utils import parsedate_to_datetime
import json
import math
import re
import sqlite3
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from . import water_settings
from .uv_index import GEOCODING_URL

MAX_BYTES = 1024 * 1024
REQUEST_SECONDS = 8
QUERY_SECONDS = 35
MAX_REQUESTS = 6
CACHE_SECONDS = 300
REFRESH_SECONDS = 60
MAX_CACHE_ROWS = 128
NWS = 'https://api.weather.gov'


class Unavailable(ValueError):
    """A safe public explanation, without provider payloads or local paths."""


class NoRedirect(HTTPRedirectHandler):
    """Prevent validated provider URLs redirecting to an unapproved destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Unavailable('Weather unavailable: provider redirect unsupported.')


def allowed_url(url):
    """Allow only existing geocoding and NWS point/forecast endpoint families."""
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.query or parsed.fragment:
        return False
    if url == GEOCODING_URL:
        return True
    return parsed.netloc == 'api.weather.gov' and bool(re.fullmatch(
        r'/points/[+-]?[0-9]+(?:\.[0-9]+)?,[+-]?[0-9]+(?:\.[0-9]+)?'
        r'|/gridpoints/[A-Z]{3}/[0-9]+,[0-9]+/forecast(?:/hourly)?', parsed.path))


def http_expiry(headers, now):
    """Respect HTTP age/expiry and no-store; cap reuse at five minutes."""
    age = float(headers.get('Age', '0'))
    if not math.isfinite(age) or age < 0:
        raise Unavailable('Weather unavailable: invalid HTTP age.')
    date = headers.get('Date')
    if date:
        instant = parsedate_to_datetime(date)
        if instant.tzinfo is None or instant.timestamp() > now + 60:
            raise Unavailable('Weather unavailable: invalid HTTP date.')
        age = max(age, now - instant.timestamp())
    directives = {part.strip().lower() for part in headers.get('Cache-Control', '').split(',')}
    max_age = CACHE_SECONDS
    for item in directives:
        if item.startswith('max-age='):
            value = item.split('=', 1)[1].strip('"')
            if not value.isascii() or not value.isdigit():
                raise Unavailable('Weather unavailable: invalid HTTP expiry.')
            max_age = min(max_age, int(value))
    if max_age > 0 and age >= max_age:
        raise Unavailable('Weather unavailable: expired HTTP response.')
    remaining = max(0, max_age - age)
    expires = headers.get('Expires')
    if expires:
        instant = parsedate_to_datetime(expires)
        if instant.tzinfo is None:
            raise Unavailable('Weather unavailable: invalid HTTP expiry.')
        if instant.timestamp() <= now and age > 0:
            raise Unavailable('Weather unavailable: expired HTTP response.')
        remaining = min(remaining, max(0, instant.timestamp() - now))
    if age > CACHE_SECONDS:
        raise Unavailable('Weather unavailable: stale HTTP response.')
    if 'no-cache' in directives or 'no-store' in directives:
        remaining = 0
    return now + remaining, 'no-store' not in directives


class Client:
    """Bound total requests, bytes and elapsed time; retry one transient failure."""

    def __init__(self, clock=time.time, opener=None):
        self.clock = clock
        self.opener = opener or build_opener(NoRedirect())
        self.deadline = time.monotonic() + QUERY_SECONDS
        self.requests = 0
        self.retried = False

    allowed_url = staticmethod(allowed_url)
    request_seconds = REQUEST_SECONDS

    def reserve(self):
        """Reserve an attempt; composite lookups may impose an additional budget."""
        if self.requests >= MAX_REQUESTS:
            raise Unavailable('Weather unavailable: request limit reached.')
        self.requests += 1

    def get(self, url, params=None):
        """Return JSON and HTTP reuse evidence, never infer a forecast from failure."""
        if not self.allowed_url(url):
            raise Unavailable('Weather unavailable: unsupported provider endpoint.')
        target = url + ('?' + urlencode(params) if params else '')
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise Unavailable('Weather unavailable: request limit reached.')
            self.reserve()
            request = Request(target, headers={'User-Agent': 'MC-EMS-Services-Weather/1.0',
                                               'Accept': 'application/geo+json, application/json'})
            try:
                with self.opener.open(request, timeout=min(self.request_seconds, remaining)) as response:
                    chunks, size = [], 0
                    while True:
                        chunk = response.read(min(65536, MAX_BYTES + 1 - size))
                        size += len(chunk)
                        if size > MAX_BYTES or time.monotonic() > self.deadline:
                            raise Unavailable('Weather unavailable: response size/time limit.')
                        if not chunk:
                            break
                        chunks.append(chunk)
                    expires, store = http_expiry(response.headers, self.clock())
                value = json.loads(b''.join(chunks))
                if not isinstance(value, dict) or value.get('error'):
                    raise Unavailable('Weather unavailable: malformed provider response.')
                return value, expires, store
            except HTTPError as exc:
                if not self.retried and exc.code in (502, 503, 504):
                    self.retried = True
                    exc.close()
                    continue
                raise

    def geocode(self, url, params):
        """Adapt bounded HTTP to the existing location resolver's fetch contract."""
        return self.get(url, params)[0]


class Cache:
    """Replace the current composite per location/product; retain no forecast history.

    This uses the existing runtime directory and current-only SQLite pattern.
    Expired rows are removed on writes, with a fixed row cap and secure deletion.
    Cache failures must not prevent otherwise valid live queries.
    """

    def __init__(self, path=None):
        self.path = path or water_settings.runtime() / 'weather_current.sqlite3'

    def read(self, key, now):
        """Read a matching unexpired composite; malformed or inaccessible caches miss."""
        try:
            if not self.path.exists():
                return None
            with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                row = db.execute('SELECT body FROM current WHERE key=? AND expires>? AND length(body)<=?',
                                 (key, now, 3 * MAX_BYTES)).fetchone()
            value = json.loads(row[0]) if row else None
            if not isinstance(value, dict) or value.get('key') != key:
                return None
            if not 0 <= now - value['retrieved'] <= CACHE_SECONDS or not now < value['expires'] <= value['retrieved'] + CACHE_SECONDS:
                return None
            return value
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            return None

    def write(self, key, value, now):
        """Best-effort cache replacement; a no-store response clears its prior row."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=1)) as db, db:
                db.execute('PRAGMA secure_delete=ON')
                db.execute('CREATE TABLE IF NOT EXISTS current(key TEXT PRIMARY KEY, expires REAL, body TEXT)')
                db.execute('DELETE FROM current WHERE key=? OR expires<=?', (key, now))
                if value is not None and value['expires'] > now:
                    body = json.dumps(value, allow_nan=False, separators=(',', ':'))
                    if len(body.encode()) <= 3 * MAX_BYTES:
                        db.execute('INSERT INTO current VALUES(?,?,?)', (key, value['expires'], body))
                db.execute('DELETE FROM current WHERE key IN (SELECT key FROM current ORDER BY expires DESC, key LIMIT -1 OFFSET ?)', (MAX_CACHE_ROWS,))
            return True
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return False
