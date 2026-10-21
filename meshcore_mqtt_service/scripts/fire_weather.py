"""NWS fire-weather product parsing and zone-based alert interpretation."""

import re
import time
from .wildfire_sources import NWS, timestamp


def ugc_codes(header):
    """Expand state-qualified and compressed UGC ranges; exclude the expiration token."""
    codes, prefix = [], None
    for token in re.sub(r"\s+", "", header).split("-"):
        if not token or re.fullmatch(r"\d{6}", token):
            continue
        match = re.fullmatch(r"([A-Z]{2}Z)?(\d{3})(?:>(\d{3}))?", token)
        if not match:
            raise ValueError("Unrecognized FWF zone header")
        prefix = match[1] or prefix
        if not prefix:
            raise ValueError("FWF zone header lacks state")
        start, end = int(match[2]), int(match[3] or match[2])
        if end < start:
            raise ValueError("Reversed FWF zone range")
        codes.extend(f"{prefix}{number:03d}" for number in range(start, end + 1))
    return codes


def parse_fwf(product):
    """Retain raw text, discussion, zone sections, and named forecast periods.

    FWF office formats differ. Unrecognized/empty products fail explicitly; raw
    text remains available in successful records for manual interpretation.
    """
    text = product.get("productText")
    if not isinstance(text, str) or not product.get("issuanceTime"):
        raise ValueError("Missing FWF text or issuance time")
    issued = timestamp(product["issuanceTime"])
    headers = []
    lines = text.splitlines(keepends=True)
    offset, index = 0, 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^[A-Z]{2}Z\d{3}[- >]", line) and re.fullmatch(r"[A-Z0-9>\s-]+", line):
            start, header = offset, line
            while not re.search(r"\d{6}-\s*$", header):
                index += 1
                offset += len(line)
                if index >= len(lines):
                    raise ValueError("Incomplete FWF zone header")
                line = lines[index]
                if not re.fullmatch(r"[A-Z0-9>\s-]+", line):
                    raise ValueError("Malformed FWF zone continuation")
                header += line
            headers.append((start, offset + len(line), ugc_codes(header)))
        offset += len(line)
        index += 1
    if not headers:
        raise ValueError("No recognized FWF zone sections")
    sections = {}
    for number, (_, start, codes) in enumerate(headers):
        end = headers[number + 1][0] if number + 1 < len(headers) else len(text)
        body = text[start:end].split("$$")[0].strip()
        periods = []
        matches = list(re.finditer(r"(?m)^\.(?!DISCUSSION)([A-Z][A-Z0-9 /()'-]*)\.\.\.", body))
        for n, match in enumerate(matches):
            stop = matches[n + 1].start() if n + 1 < len(matches) else len(body)
            periods.append({"name": match[1].title(), "text": body[match.end():stop].strip()})
        if not periods:
            raise ValueError("FWF zone has no recognizable forecast periods")
        for code in codes:
            sections[code] = {"text": body, "periods": periods}
    return {"issued": issued, "office": product.get("issuingOffice"), "product_id": product.get("id"),
            "discussion": text[:headers[0][0]].strip(), "sections": sections, "raw": text}


def fetch_fwf(client, office):
    """Follow the most recently issued FWF product, including amended/corrected issues."""
    listing = client.get(f"{NWS}/products/types/FWF/locations/{office}")
    products = listing.get("@graph")
    if not isinstance(products, list) or not products:
        raise ValueError(f"No FWF products available for {office}")
    latest = max(products, key=lambda p: timestamp(p["issuanceTime"]))
    product_id = latest["id"]
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", product_id):
        raise ValueError("Invalid NWS product identifier")
    url = f"{NWS}/products/{product_id}"
    parsed = parse_fwf(client.get(url))
    return [{"type": "Feature", "id": office, "geometry": None, "properties": dict(parsed, url=url)}]


def fire_alerts(features, codes, now=None):
    """Match official fire-zone codes even when NWS supplies no polygon."""
    now = time.time() if now is None else now
    result = []
    for feature in features:
        props = feature.get("properties", {})
        if props.get("event") not in {"Red Flag Warning", "Fire Weather Watch"}:
            continue
        if props.get("status") != "Actual" or props.get("messageType") == "Cancel":
            continue
        expires = timestamp(props.get("ends") or props.get("expires"))
        effective = timestamp(props.get("effective"))
        if expires is None or expires <= now or (effective is not None and effective > now):
            continue
        affected = set(props.get("geocode", {}).get("UGC", []))
        affected.update(url.rsplit("/", 1)[-1] for url in props.get("affectedZones", []))
        if affected.intersection(codes):
            result.append(feature)
    return sorted(result, key=lambda f: (f["properties"]["event"] != "Red Flag Warning", f["id"]))


def compact_period(period):
    """Select fire-relevant fields while retaining terrain labels and wind reference height."""
    lines, selected, keep = period["text"].splitlines(), [], False
    for line in lines:
        text = line.strip().lstrip("*").strip()
        if re.search(r"\.{2,}", text):
            label = re.split(r"\.{2,}", text)[0].strip()
            # Terrain rows belong to the preceding field (for example ridge-top winds).
            terrain = bool(re.search(r"Valley|Valleys|Slope|Ridge|Above|Below", label, re.I))
            if not terrain:
                keep = bool(re.search(r"Humidity|Winds|Thunder|Wetting|LAL", label, re.I))
            if keep:
                selected.append(re.sub(r"\.{2,}", ": ", text))
        elif keep and text and not text.startswith("."):
            selected.append(text)
    return period["name"] + ": " + " ".join(selected or [" ".join(period["text"].split())])
