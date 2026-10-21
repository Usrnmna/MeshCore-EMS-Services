"""Read verified statewide collections using a separate spatial index; originals are read-only.

The index contains bounding boxes and source pointers, never level measurements.
Rebuild after inventory/routing changes. Observation refreshes are read directly.
"""

from contextlib import closing
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3

from . import water_identifiers, water_settings

# These statuses are emitted only after traversing supported directed source edges.
# Incomplete endpoints, tides and branches remain caveats, not invented connections.
SUPPORTED_PATH_STATUSES = {
    "paths_to_source_terminals",
    "paths_with_unresolved_endpoints",
    "no_source_terminal_reached",
}


def reading_status(rows):
    """Summarize current reading usability without retaining measurement values or ages."""
    return (
        ",".join(sorted({row.get("status", "invalid") for row in rows}))
        or "unavailable"
    )


def routing_caveats(coverage):
    """Retain source graph limitations separately from eligibility of existing paths."""
    flags = [
        name
        for name in ("unresolved_endpoints", "tidal_reaches", "potential_divergences")
        if coverage.get(name, 0)
    ]
    if coverage.get("status") != "paths_to_source_terminals":
        flags.append(coverage.get("status", "unresolved"))
    return ",".join(flags) or "none_reported"


def read_json(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8-sig") as stream:
        return json.load(stream)


def checked_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Water source path escapes its collection")
    return path


def verify_file(path, expected):
    """Hash source bytes once during index building, or small current files during lookup."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if (
        path.stat().st_size != expected["byte_count"]
        or digest.hexdigest() != expected["sha256"]
    ):
        raise ValueError("Water artifact checksum mismatch: " + path.name)


def generation(root, kind, files=()):
    """Verify manifest and requested artifacts without repeatedly hashing unrelated archives."""
    pointer = read_json(root / (kind + ".json"))
    path = checked_path(root, pointer["manifest_path"])
    verify_file(path, pointer)
    manifest = read_json(path)
    if not manifest.get("complete") or manifest.get("kind") != kind:
        raise ValueError("Incomplete water generation")
    for name in files:
        verify_file(checked_path(path.parent, name), manifest["files"][name])
    return path.parent, manifest, pointer


def readonly(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def signature(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def build_index(config, output=None):
    """Atomically index verified static geometry and station identities; store no observations."""
    import shapely
    from pyproj import Transformer

    root = water_settings.data_root(config) / "usgs_water"
    directory, manifest, pointer = generation(root, "routing", ["routing.sqlite"])
    inventory, im, ip = generation(
        root,
        "inventory",
        ["stations.geojson.gz", "relationships/station_identifiers.csv"],
    )
    if manifest["inventory_pointer"] != ip:
        raise ValueError(
            "Refresh routing after inventory changes before building the water index"
        )
    pins = {
        key: read_json(root / (key + ".json"))
        for key in ("network", "link_review")
        if (root / (key + ".json")).exists()
    }
    for key in ("network", "link_review"):
        if manifest.get(key + "_pointer") != pins.get(key):
            raise ValueError("Routing source versions differ; rebuild routing")
    target = output or water_settings.runtime() / "water_index.sqlite3"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".building")
    # Exclusive reservation prevents simultaneous index builders replacing one another.
    with temporary.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(temporary)) as index, closing(
            readonly(directory / "routing.sqlite")
        ) as source:
            index.executescript(
                """
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
                CREATE VIRTUAL TABLE reach_bounds USING rtree(id,minx,maxx,miny,maxy);
                CREATE VIRTUAL TABLE basin_bounds USING rtree(id,minx,maxx,miny,maxy);
                CREATE TABLE stations(id TEXT PRIMARY KEY,name TEXT,lon REAL,lat REAL,lid TEXT);
            """
            )
            transform = Transformer.from_crs(4326, 3310, always_xy=True).transform
            for table, bounds in (
                ("reaches", "reach_bounds"),
                ("basins", "basin_bounds"),
            ):
                for row in source.execute(
                    f"SELECT rowid,geometry_wkb FROM {table} WHERE geometry_wkb IS NOT NULL"
                ):
                    geom = shapely.from_wkb(row[1])
                    if table == "reaches":
                        geom = shapely.transform(geom, transform, interleaved=False)
                    if geom.is_empty:
                        continue
                    x1, y1, x2, y2 = geom.bounds
                    index.execute(
                        f"INSERT INTO {bounds} VALUES(?,?,?,?,?)",
                        (row[0], x1, x2, y1, y2),
                    )
            with (inventory / "relationships/station_identifiers.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                identifiers = {
                    r["station_id"]: r["nwps_lid"] for r in csv.DictReader(stream)
                }
            for feature in read_json(inventory / "stations.geojson.gz")["features"]:
                geometry = feature.get("geometry")
                lon, lat = (
                    geometry["coordinates"][:2]
                    if geometry and geometry["type"] == "Point"
                    else (None, None)
                )
                index.execute(
                    "INSERT INTO stations VALUES(?,?,?,?,?)",
                    (
                        feature["id"],
                        feature["properties"].get("monitoring_location_name")
                        or "Unnamed station",
                        lon,
                        lat,
                        identifiers.get(feature["id"], ""),
                    ),
                )
            metadata = {
                "routing": pointer,
                "inventory": ip,
                "pins": pins,
                "routing_path": str(directory / "routing.sqlite"),
                "routing_signature": signature(directory / "routing.sqlite"),
                "schema": 2,
            }
            index.executemany(
                "INSERT INTO metadata VALUES(?,?)",
                [(k, json.dumps(v)) for k, v in metadata.items()],
            )
            index.commit()
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def readings(root, now, max_age):
    """Read the sole latest-value generation; never copy measurements into the spatial index."""
    directory, manifest, pointer = generation(
        root, "observations", ["latest_measurements.csv", "series_conditions.csv"]
    )
    with (directory / "series_conditions.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    result = {}
    for row in rows:
        try:
            instant = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError("Naive reading time")
            age = now - instant.timestamp()
            value = float(row["value"])
            expected = "ft" if row["parameter_code"] == "00065" else "ft^3/s"
            status = (
                "invalid"
                if not math.isfinite(value) or value <= -999
                else (
                    "future"
                    if age < 0
                    else (
                        "stale"
                        if age > max_age
                        else (
                            "unexpected_units"
                            if row["unit_of_measure"] != expected
                            else "available"
                        )
                    )
                )
            )
            result.setdefault(row["station_id"], []).append(
                dict(row, age_seconds=age, status=status)
            )
        except (ValueError, TypeError, KeyError):
            result.setdefault(row.get("station_id", ""), []).append(
                {"status": "invalid", "time": row.get("time")}
            )
    return result, manifest["inventory_pointer"]


def context(latitude, longitude, config, now, index_path=None):
    """Resolve containing basins and nearby reaches; proximity is never an alarm-qualified link."""
    import shapely
    from pyproj import Transformer

    root = water_settings.data_root(config) / "usgs_water"
    path = index_path or water_settings.runtime() / "water_index.sqlite3"
    if not path.exists():
        raise ValueError(
            "Water index unavailable; run scripts/water_refresh.py --index"
        )
    with closing(readonly(path)) as index:
        metadata = {
            r[0]: json.loads(r[1]) for r in index.execute("SELECT * FROM metadata")
        }
        if metadata.get("schema") != 2:
            raise ValueError("Unsupported water index; rebuild")
        for kind in ("routing", "inventory"):
            if read_json(root / (kind + ".json")) != metadata[kind]:
                raise ValueError("Water index versions changed; rebuild index")
        for kind in ("network", "link_review"):
            current = (
                read_json(root / (kind + ".json"))
                if (root / (kind + ".json")).exists()
                else None
            )
            if current != metadata["pins"].get(kind):
                raise ValueError(
                    "Routing dependencies changed; refresh routing and index"
                )
        source_path = Path(metadata["routing_path"])
        if signature(source_path) != metadata["routing_signature"]:
            raise ValueError("Routing file changed since verified indexing")
        to_albers = Transformer.from_crs(4326, 3310, always_xy=True).transform
        x, y = to_albers(longitude, latitude)
        point = shapely.Point(x, y)
        with closing(readonly(source_path)) as source:
            basins = []
            for (rid,) in index.execute(
                "SELECT id FROM basin_bounds WHERE minx<=? AND maxx>=? AND miny<=? AND maxy>=?",
                (x, x, y, y),
            ):
                row = dict(
                    source.execute(
                        "SELECT * FROM basins WHERE rowid=?", (rid,)
                    ).fetchone()
                )
                geom = shapely.from_wkb(row.pop("geometry_wkb"))
                if geom.covers(point):
                    basins.append(row)
            radius = config["nearby_radius_miles"] * 1609.344
            waterways = []
            for (rid,) in index.execute(
                "SELECT id FROM reach_bounds WHERE minx<=? AND maxx>=? AND miny<=? AND maxy>=?",
                (x + radius, x - radius, y + radius, y - radius),
            ):
                row = dict(
                    source.execute(
                        "SELECT reach_id,name,geometry_wkb FROM reaches WHERE rowid=?",
                        (rid,),
                    ).fetchone()
                )
                geom = shapely.transform(
                    shapely.from_wkb(row.pop("geometry_wkb")),
                    to_albers,
                    interleaved=False,
                )
                distance = geom.distance(point)
                if distance <= radius:
                    row.update(
                        distance_miles=distance / 1609.344, relationship="nearby_only"
                    )
                    waterways.append(row)
            waterways.sort(key=lambda r: (r["distance_miles"], r["reach_id"]))
            stations = []
            exclusions = []
            # All stations are considered so an upstream link is not limited by a radius.
            basin_ids = [b["basin_id"] for b in basins if b["level"].startswith("06_")]
            if not basin_ids:
                basin_ids = [
                    b["basin_id"] for b in basins if b["level"].startswith("05_")
                ]
            connected = set()
            for bid in basin_ids:
                connected.update(
                    r[0]
                    for r in source.execute(
                        "SELECT station_id FROM station_downstream_basins WHERE basin_id=? AND positive_length_reaches>0",
                        (bid,),
                    )
                )
            identifier_review, identifier_reviewed_at = water_identifiers.load()
            for row in index.execute("SELECT * FROM stations"):
                station = dict(row)
                distance = math.inf
                if station["lon"] is not None and station["lat"] is not None:
                    sx, sy = to_albers(station["lon"], station["lat"])
                    distance = math.hypot(sx - x, sy - y)
                if distance <= radius or station["id"] in connected:
                    water_identifiers.apply(station, identifier_review)
                    coverage = source.execute(
                        "SELECT * FROM station_routing_coverage WHERE station_id=?",
                        (station["id"],),
                    ).fetchone()
                    coverage = dict(coverage) if coverage else {"status": "unresolved"}
                    linked = station["id"] in connected
                    supported = linked and coverage["status"] in SUPPORTED_PATH_STATUSES
                    if linked and not supported:
                        exclusions.append(
                            {
                                "id": station["id"],
                                "name": station["name"],
                                "reason": coverage["status"],
                            }
                        )
                    station.update(
                        distance_miles=(
                            distance / 1609.344 if math.isfinite(distance) else None
                        ),
                        relationship=(
                            "upstream_basin_context"
                            if supported
                            else "unverified_basin_link" if linked else "nearby_only"
                        ),
                        routing=coverage,
                    )
                    stations.append(station)
            found_ids = {station["id"] for station in stations}
            exclusions.extend(
                {"id": sid, "name": sid, "reason": "station_missing_from_inventory"}
                for sid in sorted(connected - found_ids)
            )
            try:
                values, ip = readings(root, now, config["reading_max_age"])
                if ip != metadata["inventory"]:
                    raise ValueError("Readings and routing use different inventories")
                observation_status = "available"
            except (OSError, ValueError, KeyError) as exc:
                values, observation_status = {}, str(exc)
            for station in stations:
                station["readings"] = values.get(station["id"], [])
            stations.sort(
                key=lambda r: (
                    r["relationship"] != "upstream_basin_context",
                    not bool(r["readings"]),
                    (
                        r["distance_miles"]
                        if r["distance_miles"] is not None
                        else math.inf
                    ),
                    r["id"],
                )
            )
            return {
                "basins": sorted(basins, key=lambda r: (r["level"], r["basin_id"])),
                "waterways": waterways[: config["max_results"]],
                "waterways_total": len(waterways),
                "stations": stations[: config["max_results"]],
                "stations_total": len(stations),
                # Display limits never restrict condition evaluation. No numeric readings
                # are copied to this full monitoring inventory or subscription baseline.
                "upstream_stations": [
                    {
                        "id": s["id"],
                        "name": s["name"],
                        "lid": s["lid"],
                        "noaa_identity_status": s["noaa_identity_status"],
                        "reading_status": reading_status(s["readings"]),
                        "routing_status": s["routing"]["status"],
                        "routing_caveats": routing_caveats(s["routing"]),
                    }
                    for s in stations
                    if s["relationship"] == "upstream_basin_context"
                ],
                "routing_exclusions": exclusions,
                "observations_status": observation_status,
                "noaa_identifier_reviewed_at": identifier_reviewed_at,
                "routing_generation": metadata["routing"]["manifest_path"],
                "interpretation": "Derived upstream basin context or nearby only; no point flood inference.",
            }
