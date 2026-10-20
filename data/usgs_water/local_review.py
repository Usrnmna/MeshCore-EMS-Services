"""Review local operator metadata without retaining historical measurements."""

from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from data.flood_impacts import archive
from data.usgs_water.relationships import read_csv, table

RULES = Path(__file__).with_name("local_review_rules.json")
MAX_DOCUMENT_BYTES = 50_000_000
ALTERNATIVE_FIELDS = (
    "original_source_id", "alternate_source_id", "original_source_url", "alternate_source_url",
    "original_status", "alternate_status", "alternate_retrieved_at_utc", "context_available",
    "scope", "limitation", "relationship_type", "station_match_supported", "routing_supported",
)


def normalized(text):
    """Normalize extraction whitespace only; preserve identifiers and wording."""
    return " ".join(text.split())


def station_signature(station):
    """Invalidate manual interpretation when the published name or location changes."""
    return {"name": station["properties"]["monitoring_location_name"],
            "geometry": station["geometry"]}


def select_excerpts(content, source):
    """Retain only reviewed metadata literals, never full report pages or tables.

    PDF page numbers are one-based. Literal selections are intentionally narrow:
    report documents may contain historical measurements elsewhere on the page.
    """
    if source["format"] == "pdf":
        from pypdf import PdfReader
        if not content.startswith(b"%PDF"):
            raise ValueError("Expected PDF; received another document")
        reader = PdfReader(io.BytesIO(content))
        pages = {item["page"] for item in source["excerpts"]}
        texts = {page: normalized(reader.pages[page - 1].extract_text()) for page in pages}
    else:
        soup = BeautifulSoup(content, "html.parser")
        for node in soup(["script", "style"]):
            node.decompose()
        texts = {None: normalized(soup.get_text(" ", strip=True))}
    found, missing = [], []
    for item in source["excerpts"]:
        literal = normalized(item["text"])
        if literal and literal in texts[item.get("page")]:
            found.append(item)
        else:
            missing.append(item["id"])
    return found, missing


def acquire_source(source):
    """Fetch a reviewed public document into memory and save a metadata-only receipt.

    Authentication, observation endpoints and linked downloads are never followed.
    Redirects must stay on the configured host. Failed retrieval and changed
    metadata remain explicit and cannot support a promoted relationship.
    """
    receipt = {"source_id": source["id"], "source_url": source["url"],
               "title": source["title"], "publisher": source["publisher"],
               "retrieved_at_utc": archive.utc_now(), "status": "retrieval_failed",
               "retention": "selected_metadata_only", "original_document_retained": False,
               "original_document_sha256": "", "original_document_bytes": 0,
               "http_status": None, "excerpts": [], "missing_excerpt_ids": [], "error": ""}
    try:
        url = source["url"]
        host = urlparse(url).hostname
        with requests.Session() as session:
            for _ in range(5):
                with session.get(url, timeout=(15, 50), stream=True, allow_redirects=False,
                                 headers={"User-Agent": "MC-EMS-USGS-local-metadata-review/1.0"}) as response:
                    receipt["http_status"] = response.status_code
                    if response.is_redirect:
                        from urllib.parse import urljoin
                        url = urljoin(url, response.headers["Location"])
                        if urlparse(url).scheme != "https" or urlparse(url).hostname != host:
                            raise ValueError("Redirect changed agency host")
                        continue
                    response.raise_for_status()
                    chunks, length = [], 0
                    for chunk in response.iter_content(65536):
                        length += len(chunk)
                        if length > MAX_DOCUMENT_BYTES:
                            raise ValueError("Source exceeds in-memory document limit")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    receipt.update(final_url=url, original_document_bytes=len(content),
                                   original_document_sha256=hashlib.sha256(content).hexdigest())
                    found, missing = select_excerpts(content, source)
                    receipt.update(excerpts=found, missing_excerpt_ids=missing,
                                   status="verified_selected_metadata" if not missing else "selected_metadata_changed")
                    return receipt
            raise ValueError("Too many redirects")
    except (requests.RequestException, ValueError, IndexError) as error:
        receipt["error"] = str(error)
        return receipt


def derive(priors, stations, rules, receipts):
    """Promote exact source-keyed identities only; never emit hydrography addresses."""
    by_source = {row["source_id"]: row for row in receipts}
    expected_sources = {row["id"]: row for row in rules["sources"]}
    if len(by_source) != len(receipts) or set(by_source) != set(expected_sources):
        raise ValueError("Source receipt inventory differs from reviewed sources")
    for key, receipt in by_source.items():
        source = expected_sources[key]
        if receipt["source_url"] != source["url"]:
            raise ValueError("Evidence came from another source URL")
        if any(item not in source["excerpts"] for item in receipt["excerpts"]):
            raise ValueError("Retained metadata differs from reviewed literal selection")
        if receipt["status"] == "verified_selected_metadata" and receipt["excerpts"] != source["excerpts"]:
            raise ValueError("Verified evidence is incomplete")
    decisions, links = [], []
    for prior in priors:
        sid = prior["station_id"]
        rule = rules["stations"].get(sid)
        reason = rule["finding"] if rule else "No reviewed local-source rule exists for this station."
        signature_ok = bool(rule and rule["station_signature"] == station_signature(stations[sid]))
        supported = []
        if rule and signature_ok:
            for link in rule.get("links", []):
                receipt = by_source[link["source_id"]]
                available = {item["id"] for item in receipt["excerpts"]}
                if receipt["status"] != "verified_selected_metadata" or not set(link["excerpt_ids"]) <= available:
                    continue
                # Every station link requires the complete source identifier in
                # a selected excerpt. Names and proximity cannot authorize a link.
                evidence = " ".join(item["text"] for item in receipt["excerpts"]
                                    if item["id"] in link["excerpt_ids"])
                if not re.search(r"(?<!\d)" + re.escape(sid.removeprefix("USGS-")) + r"(?!\d)", evidence):
                    raise ValueError("Station link lacks an exact published USGS identifier")
                supported.append({"station_id": sid, **{k: v for k, v in link.items() if k != "excerpt_ids"},
                                  "source_vintage": link.get("source_vintage", ""),
                                  "temporal_scope": link.get("temporal_scope", "published_metadata_not_current_operation"),
                                  "excerpt_ids": ";".join(link["excerpt_ids"]),
                                  "source_url": receipt["source_url"],
                                  "source_retrieved_at_utc": receipt["retrieved_at_utc"],
                                  "evidence_class": "published_local_metadata",
                                  "routing_supported": False})
        sources = rule["source_ids"] if rule else []
        issues = [source + ":" + by_source[source]["status"] for source in sources
                  if by_source[source]["status"] != "verified_selected_metadata"]
        status = ("local_identity_supported_routing_unresolved" if supported else
                  "local_context_only_routing_unresolved")
        if not signature_ok:
            status = "station_metadata_changed_requires_review" if rule else "local_source_review_required"
            if rule:
                reason = "Prior manual finding; changed station metadata requires re-review. " + reason
        if issues:
            reason += " Source retrieval or selection gaps remain explicit in source_issues."
        decisions.append({"station_id": sid, "station_name": prior["station_name"], "status": status,
                          "prior_agency_status": prior["status"], "supported_link_count": len(supported),
                          "finding": reason, "source_ids": ";".join(sources),
                          "source_issues": ";".join(issues), "routing_supported": False,
                          "network_address_status": "unresolved", "reach_id": "", "reachcode": ""})
        links.extend(supported)
    return decisions, links


def source_alternatives(rules, receipts):
    """Describe alternate evidence availability without promoting station identities.

    Each row preserves the original access result. Even a verified alternate
    supplies only its reviewed context; it cannot authorize a station or graph edge.
    Receipt contents and source inventory are validated by derive before export.
    """
    by_source = {row["source_id"]: row for row in receipts}
    rows = []
    for item in rules.get("source_alternatives", []):
        original = by_source[item["original_source_id"]]
        alternate = by_source[item["alternate_source_id"]]
        rows.append({
            "original_source_id": item["original_source_id"],
            "alternate_source_id": item["alternate_source_id"],
            "original_source_url": original["source_url"],
            "alternate_source_url": alternate["source_url"],
            "original_status": original["status"], "alternate_status": alternate["status"],
            "alternate_retrieved_at_utc": alternate["retrieved_at_utc"],
            "context_available": alternate["status"] == "verified_selected_metadata",
            "scope": item["scope"], "limitation": item["limitation"],
            "relationship_type": "alternate_official_context",
            "station_match_supported": False, "routing_supported": False,
        })
    return rows


def refresh_local_review(root, resume=None):
    """Refresh the unresolved cohort while preserving earlier decisions and source data."""
    from data.usgs_water.refresh import build_stage, retain_code
    from data.usgs_water.audit_source_rules import audit_generation, print_summary
    # Strict decoding happens before acquisition or publication. Never silently
    # reinterpret a rule file saved with a platform-specific code page.
    rules = json.loads(RULES.read_bytes().decode("utf-8"))
    pointer = archive.read_json(root / "agency_review.json")
    agency, am = archive.open_generation(root, "agency_review", pointer)
    settings = {"agency_review_pointer": pointer, "inventory_pointer": am["inventory_pointer"],
                "rules_sha256": archive.digest(RULES)["sha256"]}
    stage, identifier, settings = build_stage(root, "local_review", resume, settings)
    archive.write_json(stage / "review_rules.json", rules)
    priors = [row for row in read_csv(agency / "relationships/station_agency_review.csv")
              if row["status"] != "supported_static_nonnetwork_address"]
    stations = archive.read_json(agency / "current_station_metadata.json")
    # A resumed build reuses its verified evidence selection, never a cached
    # search-engine summary or a response from another source configuration.
    receipts = []
    for source in rules["sources"]:
        path = stage / "evidence" / (source["id"] + ".json")
        if path.exists():
            receipt = archive.read_json(path)
            if receipt["source_url"] != source["url"]:
                raise ValueError("Resumed source URL changed")
        else:
            receipt = acquire_source(source)
            archive.write_json(path, receipt)
        receipts.append(receipt)
    decisions, links = derive(priors, stations, rules, receipts)
    alternatives = source_alternatives(rules, receipts)
    table(stage, "source_alternatives", alternatives, ALTERNATIVE_FIELDS)
    table(stage, "station_local_review", decisions, tuple(decisions[0]))
    table(stage, "station_local_links", links, tuple(links[0]) if links else (
        "station_id", "relationship_type", "target_namespace", "target_id", "target_name",
        "source_id", "source_vintage", "temporal_scope", "excerpt_ids", "source_url", "source_retrieved_at_utc",
        "evidence_class", "routing_supported"))
    inventory, _ = archive.open_generation(root, "inventory", am["inventory_pointer"])
    members = defaultdict(set)
    for row in read_csv(inventory / "relationships/station_region_plan.csv"):
        members[row["region"]].add(row["station_id"])
    for region, ids in members.items():
        archive.write_csv(stage / "regions" / region / "station_local_review.csv",
                          [row for row in decisions if row["station_id"] in ids], tuple(decisions[0]))
    audit_result = audit_generation(root, stage, identifier, settings["rules_sha256"])
    archive.write_json(stage / "source_rule_audit.json", audit_result)
    print_summary(audit_result)
    retain_code(stage)
    target, manifest = archive.publish(root, stage, identifier, "local_review", {
        **settings, "reviewed_station_count": len(decisions), "supported_link_count": len(links),
        "stations_with_supported_local_links": len({row["station_id"] for row in links}),
        "status_counts": dict(Counter(row["status"] for row in decisions)),
        "source_status_counts": dict(Counter(row["status"] for row in receipts)),
        "alternate_context_count": sum(row["context_available"] for row in alternatives),
        "source_rule_audit_summary": audit_result["summary"],
        "routing_links_added": 0, "observations_retained": False})
    latest_audit = root / "source_rule_audit.download"
    archive.write_json(latest_audit, audit_result)
    latest_audit.replace(root / "source_rule_audit.json")
    write_catalog(root, target, manifest, decisions, receipts, alternatives)
    return target


def write_catalog(root, target, manifest, decisions, receipts, alternatives=()):
    """Generate a readable station-by-station catalog with original agency citations."""
    base = target.resolve().relative_to(root.resolve()).as_posix()
    lines = ["# Local operating-agency station investigation", "",
             f"Reviewed: {len(decisions)} stations. Supported metadata relationships: "
             f"{manifest['supported_link_count']} for {manifest['stations_with_supported_local_links']} stations. "
             "New hydrography routing links: 0.", "",
             "All reviewed network addresses remain unresolved. Facility identities, operational roles and "
             "station aliases do not establish downstream reach sequences or flood extents.", "",
             f"[Station decisions]({base}/relationships/station_local_review.csv) | "
             f"[Supported relationships]({base}/relationships/station_local_links.csv) | "
             f"[Manifest]({base}/manifest.json)", "",
             "| Station | Name | Supported links | Finding | Source gaps |",
             "| --- | --- | ---: | --- | --- |"]
    for row in decisions:
        lines.append(f"| {row['station_id']} | {row['station_name']} | {row['supported_link_count']} | "
                     f"{row['finding']} | {row['source_issues'] or 'None'} |")
    if "source_rule_audit_summary" in manifest:
        summary = manifest["source_rule_audit_summary"]
        lines += ["", "## Automatic source-rule audit", "",
                  f"[Generation-bound audit]({base}/source_rule_audit.json) | "
                  "[Audit interpretation and workflow](SOURCE_RULE_AUDIT.md)", "",
                  f"Current encoding flags: {summary['encoding_findings']}. "
                  f"Selection mismatches: {len(summary['selection_mismatch_sources'])}. "
                  f"Current identical-body discrepancies: {len(summary['current_same_body_discrepancy_sources'])}. "
                  f"Retrieval failures: {len(summary['retrieval_failure_sources'])}.", ""]
        for label, key in (("Selection mismatches", "selection_mismatch_sources"),
                           ("Current identical-body discrepancies", "current_same_body_discrepancy_sources"),
                           ("Retrieval failures", "retrieval_failure_sources")):
            if summary[key]:
                lines.append(f"- {label}: {', '.join(summary[key])}.")
        if summary["encoding_findings"]:
            lines.append("- Encoding flags require review; exact paths are listed in the audit.")
    if alternatives:
        lines += ["", "## Alternate official sources", "",
                  "These source-to-source references supply context only. Original access failures "
                  "remain explicit; no station identity or routing link is implied.", "",
                  f"[Source relationship table]({base}/relationships/source_alternatives.csv) | "
                  "[Investigation details and limitations](SOURCE_ACCESS_REVIEW.md)", "",
                  "| Original source | Alternate source | Original status | Alternate status | Scope and limits |",
                  "| --- | --- | --- | --- | --- |"]
        for row in alternatives:
            lines.append(f"| {row['original_source_id']} | {row['alternate_source_id']} | "
                         f"{row['original_status']} | {row['alternate_status']} | "
                         f"{row['scope']}. {row['limitation']} |")
    lines += ["", "## Checked sources", "",
              "Receipts retain selected metadata, original-response SHA-256 and retrieval time. "
              "Full reports and historical observations are not retained. Unavailable sources cannot authorize links.", ""]
    for receipt in receipts:
        lines.append(f"- **{receipt['source_id']}**: [{receipt['title']}]({receipt['source_url']}) "
                     f"({receipt['publisher']}); `{receipt['status']}`. "
                     f"[Metadata receipt]({base}/evidence/{receipt['source_id']}.json)")
    lines += ["", "See [methods, refresh and limitations](LOCAL_REVIEW_METHODS.md).", ""]
    (root / "LOCAL_REVIEW.md").write_text("\n".join(lines), encoding="utf-8")


def compatible(manifest, root, observation_inventory):
    """Suppress stale local joins if any upstream address review has changed."""
    if manifest["inventory_pointer"] != observation_inventory:
        return False
    if manifest["agency_review_pointer"] != archive.read_json(root / "agency_review.json"):
        return False
    _, agency = archive.open_generation(root, "agency_review", manifest["agency_review_pointer"])
    return all(agency[kind + "_pointer"] == archive.read_json(root / (kind + ".json"))
               for kind in ("inventory", "network", "link_review"))
