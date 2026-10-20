"""Build auditable key-based relationship tables and complete record membership indexes."""

import csv
import gzip
import hashlib
import json
from pathlib import Path

KEY_FIELDS = ("wbf_id", "wb_refkey", "reachcode", "permanent_identifier", "hrc", "rbu", "rbua",
              "rbuas", "rbuasp", "rbuaspw")
KEY_SETS = tuple((field,) for field in KEY_FIELDS if field not in ("reachcode", "permanent_identifier")) + (("wbf_id", "wb_refkey"),)
MEMBER_COLUMNS = ("object_id_json", "wb_name", "gnis_name", "basin_plan", "bu_code", "bu_name",
                  "reachcode", "source_keys_json")
RELATION_COLUMNS = (
    "relationship_id", "relationship_type", "category", "source_dataset", "target_dataset",
    "source_title", "target_title", "source_fields", "target_fields", "source_key_json", "target_key_json",
    "source_records", "target_records", "source_sample_ids", "target_sample_ids", "source_name_examples",
    "target_name_examples", "status", "evidence", "source_members_path", "target_members_path",
)
TABLES = ("beneficial_uses", "hydrography_reachcodes", "segment_groups", "calwater_hierarchy")
CALWATER_EVIDENCE = "https://repository.library.noaa.gov/view/noaa/3943/noaa_3943_DS1.pdf#page=84"


def canonical_attributes(attributes):
    """Map capitalization and the published WBREFKEY spelling for comparisons only."""
    values = {key.lower(): value for key, value in attributes.items()}
    if "wb_refkey" not in values and "wbrefkey" in values:
        values["wb_refkey"] = values["wbrefkey"]
    return values


def key_json(values):
    """Preserve string codes and nulls; compare integral numeric IDs across numeric field types."""
    normalized = [int(value) if isinstance(value, float) and value.is_integer() else value for value in values]
    return json.dumps(normalized, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def missing_key(value):
    return any(item is None or isinstance(item, str) and not item.strip() for item in json.loads(value))


class DatasetIndex:
    """Stream complete source-ID membership to gzip CSV and retain bounded key-group summaries."""

    def __init__(self, stage, entry, row, metadata):
        self.entry, self.row = entry, row
        self.fields = {field["name"].lower(): field["name"] for field in metadata.get("fields", [])}
        if "wbrefkey" in self.fields and "wb_refkey" not in self.fields:
            self.fields["wb_refkey"] = self.fields["wbrefkey"]
        self.groups = {fields: {} for fields in KEY_SETS if all(field in self.fields for field in fields)}
        identifier = hashlib.sha256(entry["key"].encode()).hexdigest()[:16]
        self.path = f"{entry['category']}/relationships/record_keys/{identifier}.csv.gz"
        self.target = stage / self.path
        self.stream = None

    def __enter__(self):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.stream = gzip.open(self.target, "wt", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.stream, fieldnames=MEMBER_COLUMNS)
        self.writer.writeheader()
        return self

    def __exit__(self, *arguments):
        self.stream.close()

    def add(self, attributes):
        """Keep every object ID and exact source key, including records with null or missing keys."""
        values = canonical_attributes(attributes)
        identifier = attributes[self.entry["object_id_field"]]
        source_keys = {actual: attributes.get(actual) for canonical, actual in self.fields.items()
                       if canonical in KEY_FIELDS}
        self.writer.writerow({"object_id_json": json.dumps(identifier), "wb_name": values.get("wb_name"),
                              "gnis_name": values.get("gnis_name"), "basin_plan": values.get("basinplanname"),
                              "bu_code": values.get("bu_code"), "bu_name": values.get("bu_name"),
                              "reachcode": values.get("reachcode"),
                              "source_keys_json": json.dumps(source_keys, ensure_ascii=False, allow_nan=False)})
        for fields, groups in self.groups.items():
            token = key_json([values.get(field) for field in fields])
            group = groups.setdefault(token, {"count": 0, "ids": [], "names": []})
            group["count"] += 1
            if len(group["ids"]) < 5:
                group["ids"].append(identifier)
            name = values.get("wb_name") or values.get("gnis_name") or values.get("bu_name")
            if name and name not in group["names"] and len(group["names"]) < 5:
                group["names"].append(name)


def relationship_row(kind, source, target, source_fields, target_fields, source_key, target_key,
                     source_group, target_group, status, evidence):
    """Describe a key-group relationship without expanding a many-to-many Cartesian product."""
    identity = [kind, source.entry["key"], target.entry["key"], source_fields, target_fields, source_key, target_key]
    return {
        "relationship_id": hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:32],
        "relationship_type": kind, "category": source.entry["category"],
        "source_dataset": source.entry["key"], "target_dataset": target.entry["key"],
        "source_title": source.row["title"], "target_title": target.row["title"],
        "source_fields": "; ".join(source.fields.get(field, field) for field in source_fields),
        "target_fields": "; ".join(target.fields.get(field, field) for field in target_fields),
        "source_key_json": source_key, "target_key_json": target_key,
        "source_records": source_group.get("count", 0), "target_records": target_group.get("count", 0),
        "source_sample_ids": json.dumps(source_group.get("ids", [])),
        "target_sample_ids": json.dumps(target_group.get("ids", [])),
        "source_name_examples": json.dumps(source_group.get("names", []), ensure_ascii=False),
        "target_name_examples": json.dumps(target_group.get("names", []), ensure_ascii=False),
        "status": status, "evidence": evidence,
        "source_members_path": source.path, "target_members_path": target.path,
    }


def key_relationships(kind, source, target, fields, target_fields=None, expect_one=False):
    """Join exact scoped keys; retain missing fields, null keys, unmatched keys, and ambiguous targets."""
    target_fields = target_fields or fields
    evidence = "Shared published keys within one service; no name or spatial inference."
    if kind == "beneficial_uses":
        evidence = "Published WBF_ID designation key; grouped representations use their shared published WBF_ID."
    if fields not in source.groups or target_fields not in target.groups:
        side = "both" if fields not in source.groups and target_fields not in target.groups else "source" if fields not in source.groups else "target"
        return [relationship_row(kind, source, target, fields, target_fields, "", "",
                                 {"count": source.entry["record_count"]}, {"count": target.entry["record_count"]},
                                 f"missing_{side}_fields", evidence)]
    left, right = source.groups[fields], target.groups[target_fields]
    result = []
    for token in sorted(left.keys() | right.keys()):
        source_group, target_group = left.get(token, {}), right.get(token, {})
        if missing_key(token):
            # A null key never establishes a relationship even if both sides have nulls.
            status = "missing_key_no_join"
        elif not source_group:
            status = "unmatched_target_key"
        elif not target_group:
            status = "unmatched_source_key"
        elif expect_one and target_group["count"] != 1:
            status = "ambiguous_target_records"
        else:
            status = "matched_key_group"
        result.append(relationship_row(kind, source, target, fields, target_fields, token, token,
                                       source_group, target_group, status, evidence))
    return result


def calwater_relationships(source, target, source_field, target_field, divisor):
    """Decode documented CalWater suffix widths and validate against actual parent codes.

    HA/HSA occupy one digit each and SPW/PW two each. Integer division retains
    two-digit hydrologic region codes such as 10; fixed-length prefixes do not.
    An absent or duplicate parent remains unresolved or ambiguous.
    """
    source_fields, target_fields = (source_field,), (target_field,)
    if source_fields not in source.groups or target_fields not in target.groups:
        return key_relationships("calwater_hierarchy", source, target, source_fields, target_fields, True)
    result = []
    for source_key, group in source.groups[source_fields].items():
        value = json.loads(source_key)[0]
        valid = (isinstance(value, int) and not isinstance(value, bool) and value >= 0) if divisor > 1 else isinstance(value, str) and bool(value)
        parent_key = key_json([value // divisor if divisor > 1 else value]) if valid else ""
        parent = target.groups[target_fields].get(parent_key, {})
        status = ("invalid_or_missing_code" if not valid else "unmatched_parent_code" if not parent else
                  "ambiguous_parent_code" if parent["count"] != 1 else "verified_code_parent")
        evidence = (f"Published {source_field}; parent {target_field} = code // {divisor}; " if divisor > 1 else
                    f"Exact published {source_field} to {target_field}; ") + CALWATER_EVIDENCE
        result.append(relationship_row("calwater_hierarchy", source, target, source_fields, target_fields,
                                       source_key, parent_key, group, parent, status, evidence))
    return result


def build_relationships(indexes):
    """Create the four data-relationship families independently for each published service."""
    services = {}
    for index in indexes:
        service = (index.entry["category"], index.entry["key"].rsplit("/", 1)[0])
        services.setdefault(service, {}).setdefault(index.entry["name"], []).append(index)
    rows = []
    for layers in services.values():
        waterbodies = [index for name in ("BasinPlanLines", "BasinPlanPolys", "BPLinesDiss", "BPPolysDiss",
                                         "Beneficial Use Lines", "Beneficial Use Polygons") for index in layers.get(name, [])]
        for source in waterbodies:
            for name in ("WB_BenUses", "BeneficialUses"):
                for target in layers.get(name, []):
                    rows.extend(key_relationships("beneficial_uses", source, target, ("wbf_id",)))
            for name in ("ReachcodeTable", "Reachcodes"):
                for target in layers.get(name, []):
                    rows.extend(key_relationships("hydrography_reachcodes", source, target, ("wb_refkey",)))
        for individual, grouped in (("BasinPlanLines", "BPLinesDiss"), ("BasinPlanPolys", "BPPolysDiss")):
            for source in layers.get(individual, []):
                for target in layers.get(grouped, []):
                    rows.extend(key_relationships("segment_groups", source, target, ("wbf_id", "wb_refkey"), expect_one=True))
        hierarchy = (
            ("Unit", "Region", "hrc", "hrc", 1),
            ("Area", "Unit", "rbua", "rbu", 10),
            ("Subarea", "Area", "rbuas", "rbua", 10),
            ("SPW", "Subarea", "rbuasp", "rbuas", 100),
            ("PW", "SPW", "rbuaspw", "rbuasp", 100),
            ("SPW", "Unit", "rbuasp", "rbu", 10000),
            ("PW", "Unit", "rbuaspw", "rbu", 1000000),
        )
        for child, parent, child_field, parent_field, divisor in hierarchy:
            for source in layers.get("CalWater_Hydrologic_" + child, []):
                for target in layers.get("CalWater_Hydrologic_" + parent, []):
                    rows.extend(calwater_relationships(source, target, child_field, parent_field, divisor))
    return rows


def read_members(path, fields, expected_key):
    """Yield every indexed source record for a relationship endpoint, preserving complete membership."""
    if not expected_key or missing_key(expected_key):
        return
    field_names = [field.strip().lower() for field in fields.split(";")]
    field_names = ["wb_refkey" if field == "wbrefkey" else field for field in field_names]
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            values = canonical_attributes(json.loads(row["source_keys_json"]))
            if key_json([values.get(field) for field in field_names]) == expected_key:
                yield row
