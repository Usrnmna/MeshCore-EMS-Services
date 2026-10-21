"""Refresh reviewed NOAA identities and/or the verified radio spatial index."""

import argparse
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import water_identifiers, water_local, water_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", action="store_true")
    parser.add_argument(
        "--noaa-identifiers",
        action="store_true",
        help="Recheck 33 NOAA identities and WAC/WAS elevation/logger metadata",
    )
    parser.add_argument(
        "--data-directory", help="Downloaded root containing usgs_water/"
    )
    args = parser.parse_args()
    if not args.index and not args.noaa_identifiers:
        parser.error("Select --index and/or --noaa-identifiers")
    config = water_settings.load()
    if args.data_directory:
        config["data_directory"] = str(Path(args.data_directory).resolve())
    failed = False
    if args.noaa_identifiers:
        path, review = water_identifiers.refresh()
        from collections import Counter

        counts = Counter(row["identity_status"] for row in review["stations"])
        print(path)
        print(dict(counts))
        vertical = review.get("wac_was_refresh_check", {})
        if vertical:
            print("WAC/WAS metadata: " + vertical["status"])
            for key, source in vertical["sources"].items():
                if source["status"] != "unchanged":
                    detail = ", ".join(source.get("changed_fields", [])) or source.get(
                        "reason", ""
                    )
                    print(f"  {key}: {source['status']} ({detail})")
        failed = any(
            counts[key]
            for key in (
                "source_unavailable",
                "identity_conflict",
                "ambiguous_catalog_match",
            )
        )
        failed = failed or any(
            row.get("agency_review", {}).get("status") == "source_unavailable"
            for row in review["stations"]
        )
        failed = failed or vertical.get("status") == "needs_review"
        failed = failed or any(
            row.get("map_record_review", {}).get("status")
            in {"source_unavailable", "needs_review"}
            for row in review["stations"]
        )
    if args.index:
        print(water_local.build_index(config))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
