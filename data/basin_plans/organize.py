"""Build readable offline review folders without changing archived source files."""

import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from uuid import uuid4

try:
    from .reference import ROOT, open_snapshot, safe_path, verify_file
    from . import names
    from . import relationships
except ImportError:
    from reference import ROOT, open_snapshot, safe_path, verify_file
    import names
    import relationships


# Published names map to readable paths; source fields and compressed bytes stay intact.
REGIONAL_DATASETS = {
    "BasinPlanLines": ("waterbodies/line_segments", "Waterbody line segments",
                       "Individual published waterbody line features."),
    "BasinPlanPolys": ("waterbodies/areas", "Waterbody areas",
                       "Individual published waterbody polygon features."),
    "BPLinesDiss": ("waterbodies/grouped_lines", "Grouped waterbody lines",
                    "Published dissolved line features; no additional grouping or simplification."),
    "BPPolysDiss": ("waterbodies/grouped_areas", "Grouped waterbody areas",
                   "Published dissolved polygon features; no additional grouping or simplification."),
    "WB_BenUses": ("designations/beneficial_uses", "Beneficial-use designations",
                   "Published beneficial-use codes, descriptions, and designation records."),
    "ReachcodeTable": ("references/hydrography_references", "Hydrography references",
                       "Published waterbody-to-hydrography reference records."),
}
STATEWIDE_DATASETS = {
    "Beneficial Use Lines": ("waterbodies/beneficial_use_lines", "Statewide beneficial-use lines",
                             "Statewide published line representation, separate from regional extracts."),
    "Beneficial Use Polygons": ("waterbodies/beneficial_use_areas", "Statewide beneficial-use areas",
                                "Statewide published polygon representation, separate from regional extracts."),
    "BeneficialUses": ("designations/beneficial_uses", "Statewide beneficial-use designations",
                       "Statewide designation table; inspect exported fields before attempting joins."),
    "Reachcodes": ("references/hydrography_references", "Statewide hydrography references",
                   "Statewide published waterbody-to-hydrography reference records."),
}
CALWATER = "hydrologic_boundaries/calwater_2_2_1"
CALWATER_LEVELS = {
    "CalWater_Hydrologic_Region": ("01_hydrologic_regions", "Hydrologic regions"),
    "CalWater_Hydrologic_Unit": ("02_hydrologic_units", "Hydrologic units"),
    "CalWater_Hydrologic_Area": ("03_hydrologic_areas", "Hydrologic areas"),
    "CalWater_Hydrologic_Subarea": ("04_hydrologic_subareas", "Hydrologic subareas"),
    "CalWater_Hydrologic_SPW": ("05_super_planning_watersheds", "Super planning watersheds (SPW)"),
    "CalWater_Hydrologic_PW": ("06_planning_watersheds", "Planning watersheds (PW)"),
}
REGIONS = {
    "01_north_coast": "1 — North Coast",
    "02_san_francisco_bay": "2 — San Francisco Bay",
    "03_central_coast": "3 — Central Coast",
    "04_los_angeles": "4 — Los Angeles",
    "05_central_valley": "5 — Central Valley",
    "06_lahontan": "6 — Lahontan",
    "07_colorado_river": "7 — Colorado River Basin",
    "08_santa_ana": "8 — Santa Ana",
    "09_san_diego": "9 — San Diego",
}
PLANS = {"sacramento_san_joaquin": "Sacramento and San Joaquin River Basins",
         "tulare": "Tulare Lake Basin"}
CATALOG_FIELDS = (
    "dataset_key", "title", "original_name", "category", "description", "kind", "geometry_types",
    "record_count", "null_geometry_count", "data_path", "original_path", "metadata_path",
    "source_url", "service_title", "retrieval_started_utc", "retrieval_completed_utc",
    "source_vintage", "object_id_field", "available_review_fields", "relationship_key_fields",
    "indexed_name_fields", "indexed_name_rows", "unnamed_record_count", "placeholder_record_count",
    "sha256", "byte_count", "review_notes",
)
PATH_FIELDS = ("data_path", "original_path", "metadata_path")
REVIEW_FIELDS = {
    "gnis_name", "wb_name", "basinplanname", "wb_type", "wb_subtype", "wb_refkey", "wbrefkey",
    "wbf_id", "parent_wb", "reg_id", "region_key", "region_name", "reachcode", "bu_code", "bu_name",
    "bu_desc", "hrc", "hrname", "rbname", "hbpaname", "huname", "first_haname", "first_hsaname",
    "first_cdfspwname", "first_cdfpwsname", "rbu", "rbua", "rbuas", "rbuasp", "rbuaspw",
}


def file_digest(path):
    """Return the size and streaming SHA-256 of a file without loading it in memory."""
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": checksum, "byte_count": path.stat().st_size}


def atomic_text(path, content):
    """Replace a small generated index atomically on the same filesystem."""
    temporary = path.with_name(path.name + ".download")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def publish_directory(stage, final):
    """Retry brief Windows file-scanner locks without replacing any existing directory."""
    for attempt in range(5):
        try:
            stage.rename(final)
            return
        except PermissionError:
            if attempt == 4 or final.exists():
                raise
            time.sleep(0.2 * (attempt + 1))


def relative_path(target, directory):
    """Use portable relative links, including links back to the preserved snapshot."""
    return Path(os.path.relpath(target, directory)).as_posix()


def readable_slug(value):
    """Bound filenames and avoid Windows reserved device names through a fixed prefix."""
    return "source_" + (re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:70] or "unnamed")


def dataset_layout(entry):
    """Map known published names; retain unfamiliar layers under an explicit review category."""
    category = entry["category"]
    name = entry["name"]
    if category == CALWATER and name in CALWATER_LEVELS:
        folder, title = CALWATER_LEVELS[name]
        return f"{category}/{folder}/boundaries", title, f"Published CalWater 2.2.1 {title.lower()} boundaries."
    mapping = STATEWIDE_DATASETS if category == "statewide" else REGIONAL_DATASETS if category.startswith("regions/") else {}
    if name in mapping:
        stem, title, description = mapping[name]
        return f"{category}/{stem}", title, description
    return (f"{category}/unclassified/{readable_slug(name)}", name,
            "Additional published dataset retained for manual classification; see original metadata.")


def group_title(group):
    """Describe region, plan, and hydrologic categories without conflating their boundaries."""
    parts = group.split("/")
    if group == ".":
        return "Basin Plan dataset review"
    if group == "regions":
        return "Regional Water Board datasets"
    if parts[0] == "regions" and len(parts) > 1:
        title = "Region " + REGIONS.get(parts[1], parts[1])
        return title + (" — " + PLANS.get(parts[2], parts[2]) if len(parts) > 2 else "")
    if group.startswith(CALWATER):
        level = next((title for folder, title in CALWATER_LEVELS.values() if parts[-1] == folder), None)
        return "CalWater 2.2.1" + (" — " + level if level else " hydrologic boundaries")
    return {"statewide": "Statewide Basin Plan datasets", "supporting": "Supporting portal resources",
            "hydrologic_boundaries": "Hydrologic boundary datasets"}.get(group, group)


def catalog_row(entry, source, snapshot, destination):
    """Record source provenance and actual exported fields, without inferring unavailable joins."""
    metadata_file = safe_path(source, entry["metadata_path"])
    metadata = json.loads(metadata_file.read_bytes())
    fields = [field["name"] for field in metadata.get("fields", [])]
    relationships = sorted({rel["keyField"] for rel in metadata.get("relationships", []) if rel.get("keyField")})
    _, title, description = dataset_layout(entry)
    notes = []
    if "/unclassified/" in destination:
        notes.append("Unrecognized published layer name; manual classification required.")
    missing = [name for name in relationships if name.lower() not in {field.lower() for field in fields}]
    if missing:
        notes.append("Metadata relationship fields absent from exported schema: " + ", ".join(missing))
    if entry.get("null_geometry_count"):
        notes.append(f"Source export includes {entry['null_geometry_count']} null geometries; retained unchanged.")
    return {
        "dataset_key": entry["key"], "title": title, "original_name": entry["name"],
        "category": entry["category"], "description": description, "kind": entry["kind"],
        "geometry_types": "; ".join(entry.get("geometry_types", [])) or metadata.get("geometryType", ""),
        "record_count": entry["record_count"], "null_geometry_count": entry.get("null_geometry_count", 0),
        "data_path": destination, "original_path": snapshot / entry["path"],
        "metadata_path": snapshot / entry["metadata_path"], "source_url": entry["source_url"],
        "service_title": entry.get("service_title", ""), "retrieval_started_utc": entry.get("started_at_utc", ""),
        "retrieval_completed_utc": entry.get("completed_at_utc", ""),
        "source_vintage": "See source metadata; retrieval time is not the source data vintage.",
        "object_id_field": entry.get("object_id_field", ""),
        "available_review_fields": "; ".join(name for name in fields if name.lower() in REVIEW_FIELDS),
        "relationship_key_fields": "; ".join(relationships), "sha256": entry["sha256"],
        "byte_count": entry["byte_count"], "review_notes": "; ".join(notes),
    }


def write_catalog(path, rows, fields):
    """Write CSV with an explicit schema and spreadsheet-compatible UTF-8 encoding."""
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def resource_rows(manifest, snapshot):
    """Index every portal item and native ZIP using the archived item metadata paths."""
    rows = []
    for item in manifest.get("items", []):
        suffix = f"/metadata/items/{item['id']}/item.json"
        matches = [path for path in manifest["files"] if path.endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f"Expected one archived item metadata file: {item['id']}")
        category = matches[0].split("/metadata/items/")[0]
        native = f"{category}/native/{item['id']}.zip"
        rows.append({"title": item["title"], "item_id": item["id"], "type": item["type"],
                     "category": category, "metadata_path": snapshot / matches[0],
                     "resources_path": snapshot / Path(matches[0]).parent,
                     "native_path": snapshot / native if native in manifest["files"] else ""})
    return rows


def write_group(stage, final, group, rows, resources, groups, snapshot_id, name_rows, link_rows, relation_rows):
    """Generate a README and catalogs with paths relative to their own directory."""
    directory = stage / group
    directory.mkdir(parents=True, exist_ok=True)
    final_directory = final / group
    local_rows = []
    for row in rows:
        local = dict(row)
        for field in PATH_FIELDS:
            target = final / row[field] if field == "data_path" else row[field]
            local[field] = relative_path(target, final_directory)
        local_rows.append(local)
    write_catalog(directory / "catalog.csv", local_rows, CATALOG_FIELDS)
    local_names = []
    for row in name_rows:
        local = dict(row)
        local["data_path"] = relative_path(final / row["data_path"], final_directory)
        local["metadata_path"] = relative_path(row["metadata_path"], final_directory)
        local_names.append(local)
    write_catalog(directory / "names.csv", local_names, names.NAME_COLUMNS)
    local_links = []
    for row in link_rows:
        local = dict(row)
        local["data_path"] = relative_path(final / row["data_path"], final_directory)
        local["metadata_path"] = relative_path(row["metadata_path"], final_directory)
        local_links.append(local)
    write_catalog(directory / "waterway_links.csv", local_links, names.LINK_COLUMNS)
    relation_directory = directory / "relationships"
    relation_directory.mkdir(exist_ok=True)
    for kind in relationships.TABLES:
        selected = []
        for row in relation_rows:
            if row["relationship_type"] == kind:
                local = dict(row)
                for field in ("source_members_path", "target_members_path"):
                    local[field] = relative_path(final / row[field], final_directory / "relationships")
                selected.append(local)
        write_catalog(relation_directory / (kind + ".csv"), selected, relationships.RELATION_COLUMNS)
    provenance = []
    for row in local_rows:
        parts = row["category"].split("/")
        provenance.append({"dataset_key": row["dataset_key"], "snapshot_id": snapshot_id,
                           "category": row["category"], "region": REGIONS.get(parts[1], "") if parts[0] == "regions" else "",
                           "plan": PLANS.get(parts[2], parts[2]) if parts[0] == "regions" and len(parts) > 2 else row["service_title"],
                           "source_title": row["service_title"], "dataset_name": row["original_name"],
                           "source_url": row["source_url"], "retrieval_started_utc": row["retrieval_started_utc"],
                           "retrieval_completed_utc": row["retrieval_completed_utc"], "source_vintage": row["source_vintage"],
                           "data_path": "../" + row["data_path"], "metadata_path": "../" + row["metadata_path"]})
    write_catalog(relation_directory / "dataset_provenance.csv", provenance,
                  ("dataset_key", "snapshot_id", "category", "region", "plan", "source_title", "dataset_name",
                   "source_url", "retrieval_started_utc", "retrieval_completed_utc", "source_vintage", "data_path", "metadata_path"))
    local_resources = []
    for resource in resources:
        local = dict(resource)
        for field in ("metadata_path", "resources_path", "native_path"):
            local[field] = relative_path(local[field], final_directory) if local[field] else ""
        local_resources.append(local)
    write_catalog(directory / "resources.csv", local_resources,
                  ("title", "item_id", "type", "category", "metadata_path", "resources_path", "native_path"))
    lines = [f"# {group_title(group)}", "", f"Snapshot: `{snapshot_id}`.", "",
             "[Dataset catalog](catalog.csv) · [Searchable geographic names](names.csv) · "
             "[Waterway relationships](waterway_links.csv) · [Source items and native archives](resources.csv)", "",
             "Data files are independent, byte-identical copies of the archived exports. Original field names,",
             "records, codes, null values, and geometry are preserved. Catalog paths are relative to this folder.", ""]
    if group.startswith(CALWATER) or group == "hydrologic_boundaries":
        lines += ["CalWater levels run from hydrologic regions through units, areas, subareas, super planning",
                  "watersheds (SPW), and planning watersheds (PW). They are distinct from Regional Water Board",
                  "jurisdictions. No boundaries are clipped, reassigned, or merged.", ""]
    elif group.startswith("regions"):
        lines += ["Waterbody names and types remain in the source attributes. The catalogs list available review",
                  "fields and declared relationship keys. IDs must be scoped to the source service and plan.",
                  "Grouped layers are the published dissolved products, not newly simplified geometry.", ""]
    if group == "regions/05_central_valley":
        lines += ["The Sacramento and San Joaquin River Basins and Tulare Lake Basin remain separate plan datasets.", ""]
    if group in (".", "statewide"):
        lines += ["Statewide and regional representations overlap. Counts are source records, not unique waterbodies.",
                  "Relationship descriptions can refer to fields absent from an exported schema; inspect the",
                  "catalog notes and linked metadata before joining tables. No missing keys are invented.", ""]
    children = [child for child in groups if child != "." and Path(child).parent.as_posix() == group]
    if children:
        lines += ["## Categories", ""]
        lines += [f"- [{group_title(child)}]({relative_path(final / child / 'README.md', final_directory)})" for child in children]
        lines.append("")
    lines += ["## Find a stream, creek, river, or watershed", "",
              f"The [name index](names.csv) contains {len(local_names):,} source-scoped name entries. It retains",
              "published waterbody and GNIS names, parent waterbody names, and available CalWater names.",
              "Each entry identifies its name field and role, dataset, plan/type context, matching record count,",
              "and up to five example source object IDs. Parent-name matches indicate a relationship; they",
              "do not assert that the feature itself carries the parent name. Identical names in different",
              "datasets or regions remain separate. No stream/river classification is guessed from spelling.", "",
              "Blank names are counted in the dataset catalog; placeholders such as 'undefined' are flagged.",
              "A missing published name cannot be inferred. The offline names.py search can return all matching",
              "original records and source IDs, including geometry where the source supplies it.", ""]
    lines += ["## Waterway and tributary relationships", "",
              f"The [relationship table](waterway_links.csv) contains {len(local_links):,} published parent-waterbody",
              "association groups. It preserves parent names, tributary methods, exclusions, and comment flags.",
              "Child features without names remain identifiable by dataset and object ID. Candidate parent records",
              "are matched by published names within the same service and compatible plan context; ambiguous and",
              "unresolved matches are retained. Candidate groups can contain multiple source features or representations.",
              "These associations do not establish a complete flow network or immediate downstream connectivity.",
              "No edge is inferred from geometric proximity. An empty table means no published parent-name",
              "associations were indexed in this category, not that no tributaries exist.", ""]
    lines += ["## Additional relationship tables", "",
              "- [Waterbodies to beneficial-use designations](relationships/beneficial_uses.csv)",
              "- [Waterbodies to hydrography reachcodes](relationships/hydrography_reachcodes.csv)",
              "- [Individual segments to grouped waterbodies](relationships/segment_groups.csv)",
              "- [CalWater hierarchy and watershed-to-unit links](relationships/calwater_hierarchy.csv)",
              "- [Datasets to region, plan, source, and retrieval dates](relationships/dataset_provenance.csv)", "",
              "Key-group tables preserve complete source-ID membership in linked compressed CSV indexes.",
              "Samples in the tables are limited to five IDs; the membership files contain every record.",
              "Missing keys, unmatched keys, and ambiguous targets remain explicit. Multiple designation or",
              "reachcode rows per waterbody can be legitimate. No spatial-overlap relationships are inferred.", ""]
    lines += ["## Datasets", "", "| Readable dataset | Published name | Records | Metadata |",
              "| --- | --- | ---: | --- |"]
    for row in local_rows:
        title = str(row["title"]).replace("|", "\\|")
        name = str(row["original_name"]).replace("|", "\\|")
        lines.append(f"| [{title}]({row['data_path']}) | {name} | {row['record_count']:,} | [Fields and relationships]({row['metadata_path']}) |")
    if not rows:
        lines += ["", "No queryable datasets in this category in this snapshot."]
    if local_resources:
        lines += ["", "## Original resources", ""]
        for resource in local_resources:
            title = resource["title"].replace("[", "\\[").replace("]", "\\]")
            lines.append(f"- [{title}]({resource['metadata_path']}) — {resource['type']}; "
                         f"[archived item files]({resource['resources_path']})" +
                         (f"; [original geodatabase ZIP]({resource['native_path']})" if resource["native_path"] else ""))
    lines += ["", "## Review notes", "", "Retrieval dates do not establish source data vintage. Metadata retains published field definitions,",
              "domains, and relationships. The mapping project is informational; consult the applicable Basin Plan.",
              "Generated files may be rebuilt. Keep manual annotations outside generated directories.", ""]
    lines += [f"- **{row['title']}**: {row['review_notes']}" for row in local_rows if row["review_notes"]]
    (directory / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_organization(root, source, manifest, snapshot=None):
    """Stage and verify a complete review generation before exposing it to active readers.

    During refresh, source is the pending archive and snapshot is its future path.
    Every call creates a new generation, preserving older copies and annotations.
    Only small pointers are replaced by the caller after successful publication.
    """
    root, source = Path(root).resolve(), Path(source).resolve()
    snapshot = Path(snapshot).resolve() if snapshot else source
    if not manifest.get("complete"):
        raise ValueError("Cannot organize an incomplete snapshot")
    snapshot_id = manifest["snapshot_id"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", snapshot_id):
        raise ValueError("Invalid snapshot identifier")
    generation = snapshot_id + "_" + uuid4().hex[:8]
    final = root / "organized" / generation
    stage = final.with_name(".pending-" + generation)
    stage.mkdir(parents=True)
    datasets = manifest["datasets"]
    if len({entry["key"] for entry in datasets}) != len(datasets):
        raise ValueError("Duplicate dataset keys")
    stems = [dataset_layout(entry)[0] for entry in datasets]
    counts = Counter(stem.casefold() for stem in stems)
    rows, used_paths, name_rows, name_coverage, link_rows, indexes = [], set(), [], [], [], []
    previous_category = None
    for entry, stem in zip(datasets, stems):
        if entry["category"] != previous_category:
            print(f"Organizing datasets and geographic names: {entry['category']}", flush=True)
            previous_category = entry["category"]
        if counts[stem.casefold()] > 1:
            stem += "__" + hashlib.sha256(entry["key"].encode()).hexdigest()[:16]
        extension = ".geojson.gz" if entry["kind"] == "spatial" else ".json.gz"
        destination = stem + extension
        if destination.casefold() in used_paths:
            raise ValueError(f"Duplicate readable path: {destination}")
        used_paths.add(destination.casefold())
        target = safe_path(stage, destination)
        original = safe_path(source, entry["path"])
        verify_file(original, entry)
        verify_file(safe_path(source, entry["metadata_path"]), manifest["files"][entry["metadata_path"]])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        verify_file(target, entry)
        row = catalog_row(entry, source, snapshot, destination)
        metadata = json.loads(safe_path(source, entry["metadata_path"]).read_bytes())
        with relationships.DatasetIndex(stage, entry, row, metadata) as index:
            indexed_names, coverage, indexed_links = names.build_name_index(source, manifest, entry, row, index.add)
        indexes.append(index)
        row.update({"indexed_name_fields": "; ".join(coverage["name_fields"]),
                    "indexed_name_rows": coverage["name_rows"],
                    "unnamed_record_count": coverage["records_with_no_name"],
                    "placeholder_record_count": coverage["records_with_only_placeholder_names"]})
        rows.append(row)
        name_rows.extend(indexed_names)
        name_coverage.append(coverage)
        link_rows.extend(indexed_links)
    names.resolve_waterway_links(link_rows, name_rows)
    relation_rows = relationships.build_relationships(indexes)
    resources = resource_rows(manifest, snapshot)
    groups = {".", "regions", "statewide", "supporting", "hydrologic_boundaries", CALWATER}
    groups.update("regions/" + region for region in REGIONS)
    groups.update("regions/05_central_valley/" + plan for plan in PLANS)
    groups.update(CALWATER + "/" + folder for folder, _ in CALWATER_LEVELS.values())
    groups.update(entry["category"] for entry in datasets)
    groups.update(resource["category"] for resource in resources)
    groups = sorted(groups)
    for group in groups:
        selected = [row for row in rows if group == "." or row["data_path"].startswith(group + "/")]
        selected_resources = [row for row in resources if group == "." or row["category"] == group
                              or row["category"].startswith(group + "/")]
        selected_names = [row for row in name_rows if group == "." or row["data_path"].startswith(group + "/")]
        selected_links = [row for row in link_rows if group == "." or row["data_path"].startswith(group + "/")]
        selected_keys = {entry["dataset_key"] for entry in selected}
        selected_relations = [row for row in relation_rows if group == "." or row["category"] == group
                              or row["category"].startswith(group + "/") or row["source_dataset"] in selected_keys]
        write_group(stage, final, group, selected, selected_resources, groups, snapshot_id, selected_names, selected_links, selected_relations)
    atomic_text(stage / "name_coverage.json", json.dumps(name_coverage, indent=2) + "\n")
    report = {"schema_version": 1, "snapshot_id": snapshot_id,
              "source_manifest_sha256": file_digest(source / "manifest.json")["sha256"],
              "dataset_count": len(rows), "dataset_keys": sorted(row["dataset_key"] for row in rows),
              "name_rows": len(name_rows),
              "waterway_link_rows": len(link_rows),
              "relationship_rows": dict(Counter(row["relationship_type"] for row in relation_rows)),
              "groups": groups,
              "files": {path.relative_to(stage).as_posix(): file_digest(path)
                        for path in sorted(stage.rglob("*")) if path.is_file()}}
    atomic_text(stage / "organization.json", json.dumps(report, indent=2) + "\n")
    publish_directory(stage, final)
    return {"organization_path": relative_path(final, root),
            "organization_manifest_sha256": file_digest(final / "organization.json")["sha256"]}


def publish_review_index(root, organization):
    """Refresh the human entry point; sources.json remains the authoritative selector."""
    path = organization["organization_path"]
    report = json.loads((root / path / "organization.json").read_bytes())
    lines = ["# Basin Plan regional review", "", f"Snapshot: `{report['snapshot_id']}`.", "",
             f"[All {report['dataset_count']} datasets]({path}/README.md) · [Combined catalog]({path}/catalog.csv)", "",
             f"[Searchable stream, river, creek, and watershed names]({path}/names.csv) "
             f"({report['name_rows']:,} source-scoped entries). [Name search guide](ORGANIZATION.md#find-streams-creeks-rivers-and-watersheds-by-name).", "",
             f"[Waterway and tributary relationships]({path}/waterway_links.csv) "
             f"({report['waterway_link_rows']:,} published association groups).", "",
             "## Regional Water Boards", ""]
    lines += [f"- [{title}]({path}/regions/{region}/README.md)" for region, title in REGIONS.items()]
    lines += ["", "## Other collections", "", f"- [Statewide datasets]({path}/statewide/README.md)",
              f"- [CalWater: six separate hydrologic levels]({path}/{CALWATER}/README.md)",
              f"- [Supporting portal resources]({path}/supporting/README.md)", "",
              "[Organization and refresh guide](ORGANIZATION.md) · [Original archive inventory](INVENTORY.md)", "",
              "This index is generated. The active archive and review generation are selected together in sources.json.", ""]
    atomic_text(root / "REVIEW.md", "\n".join(lines))


def organize_active(root=ROOT):
    """Organize the current verified snapshot offline using the same lock as refresh."""
    root = Path(root).resolve()
    lock = root / ".refresh.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(f"PID {os.getpid()}\n")
    try:
        source, manifest = open_snapshot(root)
        organization = build_organization(root, source, manifest)
        pointer = json.loads((root / "sources.json").read_bytes())
        pointer.update(organization)
        atomic_text(root / "sources.json", json.dumps(pointer, indent=2) + "\n")
        publish_review_index(root, organization)
        print(f"Organized {len(manifest['datasets'])} datasets: {root / organization['organization_path']}")
    finally:
        lock.unlink()


def verify_organization(root=ROOT):
    """Verify all generated files, dataset coverage, original copies, and local review links."""
    root = Path(root).resolve()
    source, manifest = open_snapshot(root)
    pointer = json.loads((root / "sources.json").read_bytes())
    directory = safe_path(root, pointer["organization_path"])
    report_path = directory / "organization.json"
    if file_digest(report_path)["sha256"] != pointer["organization_manifest_sha256"]:
        raise ValueError("Organization manifest checksum mismatch")
    report = json.loads(report_path.read_bytes())
    expected_keys = sorted(entry["key"] for entry in manifest["datasets"])
    if (report["snapshot_id"] != manifest["snapshot_id"] or report["dataset_keys"] != expected_keys
            or report["dataset_count"] != len(expected_keys)
            or report["source_manifest_sha256"] != pointer["manifest_sha256"]):
        raise ValueError("Organization does not cover the active snapshot")
    for relative, evidence in report["files"].items():
        verify_file(safe_path(directory, relative), evidence)
    with (directory / "catalog.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if sorted(row["dataset_key"] for row in rows) != expected_keys:
        raise ValueError("Catalog does not cover every dataset exactly once")
    entries = {entry["key"]: entry for entry in manifest["datasets"]}
    for row in rows:
        entry = entries[row["dataset_key"]]
        verify_file(safe_path(directory, row["data_path"]), entry)
        verify_file(safe_path(source, entry["path"]), entry)
        if (directory / row["original_path"]).resolve() != safe_path(source, entry["path"]):
            raise ValueError("Catalog points to an unexpected original file")
    links, checked_targets = 0, set()
    for relative in report["files"]:
        path = directory / relative
        targets = []
        if path.suffix == ".md":
            targets = re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8"))
        elif path.suffix == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                targets = [value for row in csv.DictReader(stream) for key, value in row.items()
                           if key.endswith("_path") and value]
        for target in targets:
            candidate = path.parent / target
            if candidate not in checked_targets:
                if not safe_path(root, candidate).exists():
                    raise ValueError(f"Missing catalog or documentation target: {path}: {target}")
                checked_targets.add(candidate)
            links += 1
    result = {"snapshot_id": manifest["snapshot_id"], "datasets": len(rows),
              "generated_files": len(report["files"]), "local_links": links, "name_rows": report["name_rows"],
              "waterway_link_rows": report["waterway_link_rows"]}
    result["relationship_rows"] = report["relationship_rows"]
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    parser.add_argument("--verify", action="store_true", help="Check the current review generation without rebuilding")
    args = parser.parse_args()
    if args.verify:
        verify_organization(args.directory)
    else:
        organize_active(args.directory)
