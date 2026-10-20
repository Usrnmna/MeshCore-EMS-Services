"""Index and search published stream, river, creek, waterbody, and watershed names offline."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

try:
    from .reference import ROOT, open_snapshot, safe_path, verify_file, iter_snapshot_records
except ImportError:
    from reference import ROOT, open_snapshot, safe_path, verify_file, iter_snapshot_records

# Only geographic name fields are indexed; beneficial-use labels are not place names.
NAME_FIELDS = {
    "wb_name": "waterbody name",
    "gnis_name": "GNIS feature name",
    "parent_wb": "parent waterbody name",
    "hrname": "hydrologic region name",
    "hbpaname": "hydrologic basin planning area name",
    "huname": "hydrologic unit name",
    "first_haname": "hydrologic area name",
    "first_hsaname": "hydrologic subarea name",
    "first_cdfspwname": "super planning watershed name",
    "first_cdfpwsname": "planning watershed name",
}
NAME_COLUMNS = (
    "name", "name_field", "name_role", "name_status", "basin_plan", "waterbody_type", "waterbody_subtype",
    "dataset_key", "dataset_title", "category", "matching_records", "object_id_field", "sample_object_ids",
    "data_path", "metadata_path", "source_url",
)
PLACEHOLDERS = {"undefined", "unknown", "unnamed", "not named", "n/a", "none", "null"}
SAMPLE_SIZE = 5
LINK_SOURCE_FIELDS = ("wb_name", "gnis_name", "parent_wb", "basinplanname", "wb_type", "wb_subtype",
                      "trib_method", "trib_exclusion", "tribcomm_flag", "wbid_t")
LINK_COLUMNS = ("link_id", "link_kind", "dataset_key", "dataset_title", "category", *LINK_SOURCE_FIELDS,
                "matching_records", "object_id_field", "sample_object_ids", "resolution_status",
                "target_candidates", "topology_note", "data_path", "metadata_path", "source_url")


def waterway_key(attributes):
    """Retain the published parent and tributary context as an exact relationship grouping key."""
    lowered = {key.lower(): value for key, value in attributes.items()}
    return tuple(str(lowered.get(field) or "") for field in LINK_SOURCE_FIELDS)


def normalized(value):
    """Normalize case and whitespace for searching while retaining exact source strings in output."""
    return " ".join(str(value).casefold().split())


def record_attributes(record, entry):
    """Select published attributes without renaming fields or modifying their values."""
    return record["properties"] if entry["kind"] == "spatial" else record


def name_occurrences(attributes, fields):
    """Yield exact geographic names with plan/type context and the role of each name field."""
    lowered = {key.lower(): value for key, value in attributes.items()}
    context = tuple(str(lowered.get(field) or "") for field in ("basinplanname", "wb_type", "wb_subtype"))
    for field in fields:
        name = attributes.get(field)
        if isinstance(name, str) and name.strip():
            yield (name, field, *context)


def build_name_index(source, manifest, entry, dataset_row, record_consumer=None):
    """Aggregate exact names from verified records and retain bounded example IDs for review.

    Each row is scoped to a dataset, field, plan, and source type. A parent-name
    match describes a relationship, not a claim that the feature itself has that
    name. All matching records remain accessible through the offline search CLI.
    """
    metadata = json.loads((source / entry["metadata_path"]).read_bytes())
    fields = [field["name"] for field in metadata.get("fields", []) if field["name"].lower() in NAME_FIELDS]
    counts, link_counts, unnamed, placeholders, no_parent = {}, {}, 0, 0, 0
    if (fields or record_consumer) and entry["record_count"]:
        for record in iter_snapshot_records(source, entry, manifest):
            attributes = record_attributes(record, entry)
            if record_consumer:
                record_consumer(attributes)
            relationship = waterway_key(attributes)
            if relationship[2].strip():
                group = link_counts.setdefault(relationship, {"count": 0, "ids": []})
                group["count"] += 1
                if len(group["ids"]) < SAMPLE_SIZE:
                    group["ids"].append(attributes[entry["object_id_field"]])
            elif any(value.strip() for value in relationship[6:9]) or relationship[9].casefold() == "trib":
                no_parent += 1
            occurrences = list(name_occurrences(attributes, fields))
            if not occurrences:
                unnamed += 1
            elif all(normalized(key[0]) in PLACEHOLDERS for key in occurrences):
                placeholders += 1
            for key in occurrences:
                group = counts.setdefault(key, {"count": 0, "ids": []})
                group["count"] += 1
                if len(group["ids"]) < SAMPLE_SIZE:
                    group["ids"].append(attributes[entry["object_id_field"]])
    rows = []
    for (name, field, plan, kind, subtype), group in sorted(counts.items()):
        rows.append({"name": name, "name_field": field, "name_role": NAME_FIELDS[field.lower()],
                     "name_status": "placeholder" if normalized(name) in PLACEHOLDERS else "published",
                     "basin_plan": plan, "waterbody_type": kind, "waterbody_subtype": subtype,
                     "dataset_key": entry["key"], "dataset_title": dataset_row["title"],
                     "category": entry["category"], "matching_records": group["count"],
                     "object_id_field": entry.get("object_id_field", ""),
                     "sample_object_ids": json.dumps(group["ids"]),
                     "data_path": dataset_row["data_path"], "metadata_path": dataset_row["metadata_path"],
                     "source_url": entry["source_url"]})
    links = []
    for key, group in sorted(link_counts.items()):
        identifier = hashlib.sha256(json.dumps([entry["key"], *key]).encode()).hexdigest()[:32]
        links.append({"link_id": identifier, "link_kind": "published_parent_waterbody",
                      "dataset_key": entry["key"], "dataset_title": dataset_row["title"],
                      "category": entry["category"], **dict(zip(LINK_SOURCE_FIELDS, key)),
                      "matching_records": group["count"], "object_id_field": entry["object_id_field"],
                      "sample_object_ids": json.dumps(group["ids"]),
                      "resolution_status": "unresolved", "target_candidates": "[]",
                      "topology_note": "Published parent/tributary association; direct downstream connectivity is not established.",
                      "data_path": dataset_row["data_path"], "metadata_path": dataset_row["metadata_path"],
                      "source_url": entry["source_url"]})
    coverage = {"dataset_key": entry["key"], "name_fields": fields, "name_rows": len(rows),
                "waterway_link_rows": len(links), "records_with_tributary_fields_but_no_parent": no_parent,
                "records_with_no_name": unnamed if fields else entry["record_count"],
                "records_with_only_placeholder_names": placeholders,
                "note": "No indexed geographic name fields in published schema." if not fields else ""}
    return rows, coverage, links


def resolve_waterway_links(links, name_rows):
    """Link parent names to explicit same-service names, retaining all ambiguous candidates.

    WB_NAME takes precedence over GNIS aliases when both exist. Names are only
    compared after case/whitespace normalization; geometry and proximity do not
    invent edges. Multiple source representations remain distinct candidates.
    """
    candidates = {}
    for row in name_rows:
        if row["name_field"].lower() in ("wb_name", "gnis_name") and row["name_status"] == "published":
            scope = (row["category"], row["dataset_key"].rsplit("/", 1)[0], normalized(row["name"]))
            candidates.setdefault(scope, []).append(row)
    for link in links:
        scope = (link["category"], link["dataset_key"].rsplit("/", 1)[0], normalized(link["parent_wb"]))
        matches = candidates.get(scope, [])
        matches = [row for row in matches if not link["basinplanname"] or not row["basin_plan"]
                   or normalized(link["basinplanname"]) == normalized(row["basin_plan"])]
        primary = [row for row in matches if row["name_field"].lower() == "wb_name"]
        matches = primary or matches
        targets = [{field: row[field] for field in
                    ("dataset_key", "name", "name_field", "basin_plan", "matching_records", "sample_object_ids")}
                   for row in matches]
        for target in targets:
            target["sample_object_ids"] = json.loads(target["sample_object_ids"])
        link["target_candidates"] = json.dumps(targets, ensure_ascii=False)
        link["resolution_status"] = ("one_candidate_group" if len(matches) == 1 else
                                     "multiple_candidate_groups" if matches else "unresolved_parent_name")


def read_name_catalog(directory=ROOT, filename="names.csv"):
    """Load the active name catalog only after verifying its snapshot identity and checksum."""
    directory = Path(directory).resolve()
    source, manifest = open_snapshot(directory)
    pointer = json.loads((directory / "sources.json").read_bytes())
    review = safe_path(directory, pointer["organization_path"])
    report_bytes = (review / "organization.json").read_bytes()
    if hashlib.sha256(report_bytes).hexdigest() != pointer["organization_manifest_sha256"]:
        raise ValueError("Organization manifest checksum mismatch")
    report = json.loads(report_bytes)
    if (report["snapshot_id"] != manifest["snapshot_id"]
            or report["source_manifest_sha256"] != pointer["manifest_sha256"]):
        raise ValueError("Name catalog does not describe the active snapshot")
    path = safe_path(review, filename)
    verify_file(path, report["files"][filename])
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return source, manifest, review, rows


def category_matches(value, region=None, category=None):
    """Accept readable region labels, board numbers, and literal category path fragments."""
    readable = normalized(value.replace("_", " "))
    if region:
        if str(region).isdigit():
            if not value.startswith(f"regions/{int(region):02d}_"):
                return False
        elif normalized(str(region).replace("_", " ")) not in readable:
            return False
    return not category or normalized(str(category).replace("_", " ")) in readable


def search_names(query, directory=ROOT, exact=False, region=None, category=None, name_field=None):
    """Return case-insensitive substring or exact matches with explicit regional and field filters."""
    needle = normalized(query)
    if not needle:
        raise ValueError("A nonempty name is required")
    _, _, review, rows = read_name_catalog(directory)
    matches = []
    for row in rows:
        candidate = normalized(row["name"])
        if not (candidate == needle if exact else needle in candidate):
            continue
        if not category_matches(row["category"], region, category):
            continue
        if name_field and row["name_field"].casefold() != name_field.casefold():
            continue
        match = dict(row)
        match["matching_records"] = int(row["matching_records"])
        match["sample_object_ids"] = json.loads(row["sample_object_ids"])
        for field in ("data_path", "metadata_path"):
            match[field] = str((review / row[field]).resolve())
        matches.append(match)
    return matches


def matching_records(matches, directory=ROOT):
    """Yield every matching original feature/row once per dataset, including all source attributes."""
    source, manifest = open_snapshot(directory)
    criteria = {}
    for row in matches:
        key = (row["name"], row["name_field"], row["basin_plan"], row["waterbody_type"], row["waterbody_subtype"])
        criteria.setdefault(row["dataset_key"], set()).add(key)
    for entry in manifest["datasets"]:
        wanted = criteria.get(entry["key"])
        if not wanted:
            continue
        fields = {key[1] for key in wanted}
        for record in iter_snapshot_records(source, entry, manifest):
            attributes = record_attributes(record, entry)
            if any(key in wanted for key in name_occurrences(attributes, fields)):
                yield {"dataset_key": entry["key"], "category": entry["category"],
                       "source_url": entry["source_url"], "object_id": attributes[entry["object_id_field"]],
                       "record": record}


def search_waterway_links(query, directory=ROOT, exact=False, region=None, category=None, direction="both"):
    """Find published parent associations by child name, parent name, or either endpoint."""
    needle = normalized(query)
    if not needle:
        raise ValueError("A nonempty name is required")
    _, _, review, rows = read_name_catalog(directory, "waterway_links.csv")
    result = []
    for row in rows:
        values = ([row["parent_wb"]] if direction == "children" else [row["wb_name"], row["gnis_name"]]
                  if direction == "parents" else [row["parent_wb"], row["wb_name"], row["gnis_name"]])
        if not any(normalized(value) == needle if exact else needle in normalized(value) for value in values):
            continue
        if not category_matches(row["category"], region, category):
            continue
        match = dict(row)
        match["matching_records"] = int(row["matching_records"])
        for field in ("sample_object_ids", "target_candidates"):
            match[field] = json.loads(row[field])
        for field in ("data_path", "metadata_path"):
            match[field] = str((review / row[field]).resolve())
        result.append(match)
    return result


def linked_records(matches, directory=ROOT):
    """Yield all child records underlying selected associations, including unnamed tributary features."""
    source, manifest = open_snapshot(directory)
    criteria = {}
    for row in matches:
        criteria.setdefault(row["dataset_key"], set()).add(tuple(row[field] for field in LINK_SOURCE_FIELDS))
    for entry in manifest["datasets"]:
        wanted = criteria.get(entry["key"])
        if not wanted:
            continue
        for record in iter_snapshot_records(source, entry, manifest):
            attributes = record_attributes(record, entry)
            if waterway_key(attributes) in wanted:
                yield {"dataset_key": entry["key"], "category": entry["category"],
                       "source_url": entry["source_url"], "object_id": attributes[entry["object_id_field"]],
                       "record": record}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Published name or part of a name")
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--exact", action="store_true", help="Match the entire name, ignoring case and whitespace")
    parser.add_argument("--region", help="Regional Board number or name, e.g. 2 or 'San Francisco Bay'")
    parser.add_argument("--category", help="Part of a category, e.g. calwater")
    parser.add_argument("--name-field", help="Restrict to a source field, e.g. wb_name, gnis_name, parent_wb")
    parser.add_argument("--limit", type=int, default=20, help="Maximum catalog matches displayed; 0 displays all")
    parser.add_argument("--records", action="store_true", help="Write ALL matched original records as JSON Lines")
    parser.add_argument("--links", action="store_true", help="Search published parent/tributary associations")
    parser.add_argument("--direction", choices=("both", "children", "parents"), default="both",
                        help="With --links: find associations for either endpoint, children of a named parent, or parents of a named child")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    if args.links and args.name_field:
        parser.error("--name-field applies to name searches, not --links")
    if not args.links and args.direction != "both":
        parser.error("--direction requires --links")
    matches = (search_waterway_links(args.query, args.directory, args.exact, args.region, args.category, args.direction)
               if args.links else search_names(args.query, args.directory, args.exact, args.region, args.category, args.name_field))
    if args.records:
        for record in (linked_records(matches, args.directory) if args.links else matching_records(matches, args.directory)):
            print(json.dumps(record, ensure_ascii=True, allow_nan=False))
    else:
        selected = matches[:args.limit] if args.limit else matches
        print(json.dumps({"query": args.query, "match_type": "waterway_links" if args.links else "names",
                          "matching_rows": len(matches), "returned": len(selected),
                          "truncated": len(selected) < len(matches), "matches": selected}, indent=2, ensure_ascii=True))
