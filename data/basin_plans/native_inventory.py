"""Inspect original geodatabase contents without extracting or modifying them.

Optional dependency: pyogrio (with its GDAL OpenFileGDB driver). The generated
report is outside immutable snapshots and identifies the inspected generation.
"""

import argparse
import json
from pathlib import Path
import warnings
import zipfile

from reference import ROOT, open_snapshot, safe_path, verify_file
from refresh import category_label


def inspect_native(directory=ROOT):
    """Write a categorized table/field inventory and compare published counts."""
    import pyogrio

    directory = Path(directory).resolve()
    root, manifest = open_snapshot(directory)
    report = {"snapshot_id": manifest["snapshot_id"], "pyogrio_version": pyogrio.__version__,
              "gdal_version": pyogrio.__gdal_version_string__, "archives": []}
    lines = ["# Native Basin Plan geodatabase inventory", "",
             f"Inspected snapshot: `{manifest['snapshot_id']}`.", "",
             "Native archives and feature services are separate published products. Count differences",
             "are recorded without replacing either source. Files are inspected in place without extraction.", "",
             "GDAL's displayed geometry type may omit M dimensions; original ZIP bytes remain unchanged.", ""]
    for relative, file_info in sorted(manifest["files"].items()):
        if "/native/" not in relative or not relative.endswith(".zip"):
            continue
        path = safe_path(root, relative)
        verify_file(path, file_info)
        region = relative.split("/native/", 1)[0]
        with zipfile.ZipFile(path) as archive:
            gdb_roots = sorted({name[:name.lower().index(".gdb") + 4] for name in archive.namelist()
                                if ".gdb" in name.lower()})
        record = {"category": region, "path": relative, "sha256": file_info["sha256"], "geodatabases": []}
        lines += [f"## {category_label(region)}", "", f"[Original ZIP](snapshots/{manifest['snapshot_id']}/{relative})", "",
                  "| Native dataset | Geometry type reported by GDAL | Native records | Service records |",
                  "| --- | --- | ---: | ---: |"]
        for gdb in gdb_roots:
            uri = "/vsizip/" + path.as_posix() + "/" + gdb
            database = {"name": gdb, "datasets": [], "reader_warnings": []}
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                for name, geometry in pyogrio.list_layers(uri):
                    info = pyogrio.read_info(uri, layer=name, force_feature_count=True)
                    matching = [entry for entry in manifest["datasets"]
                                if entry["category"] == region and entry["name"] == name]
                    counts = [entry["record_count"] for entry in matching]
                    entry = {"name": name, "geometry_type_reported_by_gdal": geometry,
                             "feature_count": int(info["features"]), "crs": info["crs"],
                             "fields": info["fields"].tolist(), "dtypes": info["dtypes"].tolist(),
                             "service_counts": counts}
                    database["datasets"].append(entry)
                    lines.append(f"| {name} | {geometry or 'Nonspatial table'} | {entry['feature_count']:,} | "
                                 + ", ".join(f"{c:,}" for c in counts) + " |")
                database["reader_warnings"] = sorted({str(w.message) for w in caught})
            record["geodatabases"].append(database)
        report["archives"].append(record)
        lines.append("")
    (directory / "native_inventory.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (directory / "NATIVE_INVENTORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Inspected {len(report['archives'])} native archives.")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT)
    args = parser.parse_args()
    inspect_native(args.directory)
