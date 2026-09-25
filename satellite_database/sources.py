"""Small, cached HTTP reader. No credentials, background jobs, or radio traffic."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    """Read an ISO UTC timestamp; missing/invalid timestamps remain unknown."""
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (ValueError, TypeError):
        return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Redirect: review the configured URL", headers, fp)


class SourceReader:
    """Cache by URL, keep acquisition time, and fail instead of hiding HTTP errors."""

    def __init__(self, directory, settings, offline=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.offline = offline
        self.receipts = []

    def read(self, url, cache_hours=None):
        if urlparse(url).scheme != "https":
            raise ValueError("Sources must use HTTPS: " + url)
        key = hashlib.sha256(url.encode()).hexdigest()
        body_path = self.directory / (key + ".body")
        meta_path = self.directory / (key + ".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
        age = None
        if meta and parse_time(meta.get("fetched_at")):
            age = (datetime.now(timezone.utc) - parse_time(meta["fetched_at"])).total_seconds() / 3600
        hours = self.settings["cache_hours"] if cache_hours is None else cache_hours
        if body_path.exists() and meta and (self.offline or (age is not None and 0 <= age < hours)):
            body = body_path.read_bytes()
            if hashlib.sha256(body).hexdigest() != meta["sha256"]:
                raise ValueError("Cache checksum mismatch: " + url)
            self.receipts.append(dict(meta, cached=True))
            return body, meta
        if self.offline:
            raise ValueError("No cached response for " + url)
        request = Request(url, headers={"User-Agent": self.settings["user_agent"], "Accept": "application/json,text/html"})
        with build_opener(NoRedirect()).open(request, timeout=self.settings["timeout_seconds"]) as response:
            if response.status != 200:
                raise ValueError("HTTP %s for %s" % (response.status, url))
            body = response.read(self.settings["max_response_bytes"] + 1)
        if len(body) > self.settings["max_response_bytes"]:
            raise ValueError("Response exceeds configured size limit: " + url)
        meta = {"url": url, "fetched_at": utc_now(), "sha256": hashlib.sha256(body).hexdigest()}
        # Replace cached files only after a complete download.
        temporary = body_path.with_suffix(".tmp")
        temporary.write_bytes(body)
        temporary.replace(body_path)
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        self.receipts.append(dict(meta, cached=False))
        return body, meta

    def records(self, url, required_field):
        """Accept a JSON list or paginated results; never silently truncate a feed."""
        records, visited = [], set()
        origin = urlparse(url).netloc
        while url:
            if url in visited or len(visited) >= self.settings["max_pages"]:
                raise ValueError("Repeated/excessive pagination: " + url)
            if urlparse(url).netloc != origin:
                raise ValueError("Pagination changed source host: " + url)
            visited.add(url)
            body, _ = self.read(url)
            data = json.loads(body)
            page = data if isinstance(data, list) else data.get("results") if isinstance(data, dict) else None
            if not isinstance(page, list) or any(not isinstance(row, dict) or required_field not in row for row in page):
                raise ValueError("Unexpected source schema: " + url)
            records.extend(page)
            next_url = data.get("next") if isinstance(data, dict) else None
            url = urljoin(url, next_url) if next_url else None
        if not records:
            raise ValueError("Empty source; existing database will be preserved")
        return records
