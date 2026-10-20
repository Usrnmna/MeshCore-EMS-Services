"""Lossless, resumable USGS downloads with validated pagination and receipts."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urljoin, urlparse

import requests

from data.flood_impacts import archive

BASE = "https://api.waterdata.usgs.gov/ogcapi/v1/collections"
ALLOWED_HOSTS = {"api.waterdata.usgs.gov", "api.water.usgs.gov", "api.water.noaa.gov",
                 "reference.geoconnex.us", "sb19.linked-data.internetofwater.dev", "gispublic.waterboards.ca.gov",
                 "www.sciencebase.gov", "dmap-data-commons-ow.s3.amazonaws.com"}


class Client:
    """Keep original bytes; resume only URL- and hash-verified responses in a build."""

    def __init__(self, stage, attempts=5, timeout=(15, 120)):
        self.stage = Path(stage)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "MC-EMS-California-water-archive/1.0"
        self.attempts = attempts
        self.timeout = timeout

    def fetch(self, name, url, params=None, as_json=True, accepted_statuses=()):
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"Untrusted source URL: {url}")
        path = archive.safe_path(self.stage, f"raw/{name}.gz")
        receipt_path = path.with_suffix(".receipt.json")
        if path.exists() and receipt_path.exists():
            receipt = archive.read_json(receipt_path)
            raw = gzip.decompress(path.read_bytes())
            if (receipt["url"] != url or archive.digest(path) != receipt["stored_file"]
                    or hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]):
                raise ValueError(f"Cached response mismatch: {name}")
        else:
            headers = {}
            # Credentials are sent only to their issuing host and never written to receipts.
            if parsed.hostname == "api.waterdata.usgs.gov" and os.getenv("USGS_API_KEY"):
                headers["X-Api-Key"] = os.environ["USGS_API_KEY"]
            for attempt in range(self.attempts):
                try:
                    response = self.session.get(url, headers=headers, timeout=self.timeout)
                    if response.status_code == 429:
                        delay = int(response.headers.get("Retry-After", "60"))
                        retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                        archive.write_json(self.stage / "rate_limit.json", {
                            "url": url, "retry_at_utc": retry_at.isoformat(), "retry_after_seconds": delay,
                            "note": "Pending responses remain resumable; no active pointer was replaced",
                        })
                        raise RuntimeError(f"USGS rate limit; resume this build after {retry_at.isoformat()}")
                    if response.status_code not in accepted_statuses:
                        response.raise_for_status()
                    raw = response.content
                    break
                except (requests.RequestException, TimeoutError):
                    if attempt == self.attempts - 1:
                        raise
                    delay = min(30, 2 ** (attempt + 1))
                    time.sleep(delay)
            if as_json:
                json.loads(raw)  # Never cache a successful HTTP response containing invalid JSON.
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(raw, mtime=0))
            archive.write_json(receipt_path, {
                "url": url, "retrieved_at_utc": archive.utc_now(),
                "response_headers": dict(response.headers),
                "http_status": response.status_code,
                "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_byte_count": len(raw),
                "stored_file": archive.digest(path),
            })
            time.sleep(0.15)
        return json.loads(raw) if as_json else raw

    def pages(self, name, collection, params):
        """Follow every next link, rejecting loops, duplicate IDs and collection changes."""
        url = f"{BASE}/{collection}/items?" + urlencode({"f": "json", "limit": 10000, **params})
        visited, identifiers = set(), set()
        count = 0
        while url:
            if url in visited or not url.startswith(f"{BASE}/{collection}/items?"):
                raise ValueError("Invalid pagination URL or loop")
            visited.add(url)
            document = self.fetch(f"{name}/{len(visited):05}", url)
            features = document["features"]
            if document.get("numberReturned", len(features)) != len(features):
                raise ValueError("Page count mismatch")
            for feature in features:
                key = str(feature["id"])
                if key in identifiers:
                    raise ValueError(f"Duplicate source feature ID: {key}")
                identifiers.add(key)
            count += len(features)
            print(f"{name}: {count:,} records, page {len(visited)}", flush=True)
            yield features
            links = [link for link in document.get("links", []) if link.get("rel") == "next"]
            if len(links) > 1:
                raise ValueError("Ambiguous pagination")
            url = urljoin(url, links[0]["href"]) if links else None
            if not url and document.get("numberMatched") is not None and count != document["numberMatched"]:
                raise ValueError("Incomplete collection")

    def collect(self, name, collection, params):
        return [feature for page in self.pages(name, collection, params) for feature in page]
