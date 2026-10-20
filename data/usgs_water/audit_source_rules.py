"""Audit source-rule encoding and compare retained selection outcomes offline."""

import argparse
from collections import Counter
import json
from pathlib import Path

from data.flood_impacts import archive
from data.usgs_water.local_review import RULES
from data.usgs_water.refresh import ROOT


def strings(value, path="$"):
    """Yield JSON string values with paths, including identifiers and findings."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def encoding_findings(value):
    """Flag replacement/control characters and reversible UTF-8 misdecoding.

    Reversible sequences are review candidates, not permission to rewrite text.
    Legitimate accents and punctuation must remain intact.
    """
    findings = []
    for path, text in strings(value):
        reasons = []
        if "\ufffd" in text:
            reasons.append("unicode_replacement_character")
        if any((ord(c) < 32 and c not in "\t\r\n") or 0x7f <= ord(c) <= 0x9f for c in text):
            reasons.append("unexpected_control_character")
        for codec in ("cp1252", "latin1"):
            try:
                candidate = text.encode(codec).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if candidate != text:
                reasons.append("possible_utf8_misdecode_via_" + codec)
        if reasons:
            findings.append({"path": path, "reasons": reasons, "text": text})
    return findings


def same_body_differences(source, receipt, history):
    """Identify selection changes that cannot establish a source-body change."""
    differences = []
    body_hash = receipt.get("original_document_sha256")
    if not body_hash:
        return differences
    for generation, old_source, old_receipt in history:
        if (old_receipt.get("source_url") == receipt["source_url"]
                and old_receipt.get("original_document_sha256") == body_hash
                and (old_receipt["status"], old_receipt.get("missing_excerpt_ids", []))
                != (receipt["status"], receipt.get("missing_excerpt_ids", []))):
            differences.append({
                "generation": generation, "status": old_receipt["status"],
                "missing_excerpt_ids": old_receipt.get("missing_excerpt_ids", []),
                "selection_rule_changed": old_source["excerpts"] != source["excerpts"],
                "interpretation": "Identical response bytes; inspect local rules and extraction, not agency wording.",
            })
    return differences


def audit_generation(root, directory, generation, rules_sha256, history_pointers=None):
    """Audit a pending or published generation before changing the active pointer.

    Pin historical manifests so later offline replay uses the same comparison
    set. Audit errors leave publication to the caller; no source files are edited.
    """
    rules_path = directory / "review_rules.json"
    rules = json.loads(rules_path.read_bytes().decode("utf-8"))
    if archive.digest(rules_path)["sha256"] != rules_sha256:
        raise ValueError("Audit rules differ from the pinned build")
    if history_pointers is None:
        history_pointers = [
            {"manifest_path": path.relative_to(root).as_posix(), **archive.digest(path)}
            for path in sorted((root / "local_review").glob("*/manifest.json"))
            if path.parent.name != generation
        ]
    history = {}
    historical_findings = []
    generations = []
    for pointer in history_pointers:
        old_directory, saved = archive.open_generation(root, "local_review", pointer)
        generations.append(saved["generation"])
        saved_rules = archive.read_json(old_directory / "review_rules.json")
        for finding in encoding_findings(saved_rules):
            historical_findings.append({"generation": saved["generation"], **finding})
        for source in saved_rules["sources"]:
            receipt = archive.read_json(old_directory / "evidence" / (source["id"] + ".json"))
            history.setdefault(source["id"], []).append((saved["generation"], source, receipt))
    rows = []
    for source in rules["sources"]:
        receipt = archive.read_json(directory / "evidence" / (source["id"] + ".json"))
        rows.append({
            "source_id": source["id"], "source_url": source["url"],
            "retrieved_at_utc": receipt["retrieved_at_utc"], "status": receipt["status"],
            "configured_excerpt_count": len(source["excerpts"]),
            "matched_excerpt_count": len(receipt["excerpts"]),
            "missing_excerpt_ids": receipt["missing_excerpt_ids"],
            "original_document_sha256": receipt["original_document_sha256"],
            "same_body_different_outcomes": same_body_differences(source, receipt, history.get(source["id"], [])),
        })
    result = {
        "audited_at_utc": archive.utc_now(), "local_review_generation": generation,
        "rules_sha256": rules_sha256, "strict_utf8_json": True,
        "source_count": len(rows), "excerpt_count": sum(len(s["excerpts"]) for s in rules["sources"]),
        "rule_string_count": len(list(strings(rules))),
        "current_encoding_findings": encoding_findings(rules),
        "historical_encoding_findings": historical_findings,
        "history_pointers": history_pointers,
        "published_generations_checked": generations,
        "source_status_counts": dict(Counter(r["status"] for r in rows)),
        "matched_excerpt_count": sum(r["matched_excerpt_count"] for r in rows),
        "sources": rows,
        "limitations": "Heuristic encoding flags require review. Retrieval failures cannot establish literal validity. "
                       "Identical-body comparisons use acquisition hashes; full source bodies are not retained. "
                       "No rules, station relationships or observations are modified.",
    }
    result["summary"] = audit_summary(result)
    return result


def audit_summary(result):
    """Separate active problems from historical discrepancies already corrected."""
    rows = result["sources"]
    return {
        "encoding_findings": len(result["current_encoding_findings"]),
        "selection_mismatch_sources": [
            row["source_id"] for row in rows if row["status"] == "selected_metadata_changed"],
        "current_same_body_discrepancy_sources": [
            row["source_id"] for row in rows
            if row["status"] != "verified_selected_metadata"
            and any(old["status"] == "verified_selected_metadata"
                    for old in row["same_body_different_outcomes"])],
        "retrieval_failure_sources": [
            row["source_id"] for row in rows if row["status"] == "retrieval_failed"],
        "historical_comparison_count": sum(len(row["same_body_different_outcomes"]) for row in rows),
    }


def print_summary(result):
    """Emit concise refresh diagnostics without claiming an agency text change."""
    summary = result["summary"]
    print(f"Source-rule audit: {summary['encoding_findings']} encoding flags; "
          f"{len(summary['selection_mismatch_sources'])} selection mismatches; "
          f"{len(summary['current_same_body_discrepancy_sources'])} current identical-body discrepancies; "
          f"{len(summary['retrieval_failure_sources'])} retrieval failures.", flush=True)
    for finding in result["current_encoding_findings"]:
        print(f"WARNING encoding: {finding['path']} ({', '.join(finding['reasons'])})", flush=True)
    for key in ("selection_mismatch_sources", "current_same_body_discrepancy_sources",
                "retrieval_failure_sources"):
        if summary[key]:
            print(f"WARNING {key}: {', '.join(summary[key])}", flush=True)


def audit(root, rules_path=RULES):
    """Recompute the active audit offline using its pinned comparison history."""
    active, manifest = archive.open_generation(root, "local_review")
    if archive.digest(rules_path)["sha256"] != manifest["rules_sha256"]:
        raise ValueError("Refresh local review after changing source rules")
    saved_path = active / "source_rule_audit.json"
    pointers = archive.read_json(saved_path)["history_pointers"] if saved_path.exists() else None
    return audit_generation(root, active, manifest["generation"], manifest["rules_sha256"], pointers)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--rules", type=Path, default=RULES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.directory, args.rules)
    if args.output:
        archive.write_json(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k != "sources"}, indent=2))
