"""Read-only State Parks identity and entrance queries over a pinned snapshot."""
import hashlib
import json
import math
from pathlib import Path
import sys

if __package__:
    from .dataset_paths import checked_path, resolve
    from .response_text import compact_fields
else:
    from dataset_paths import checked_path, resolve
    from response_text import compact_fields

ROOT = Path(__file__).resolve().parents[1]
SOURCE_IDS = {"park_boundaries": "FID", "park_entry_points": "OBJECTID",
              "campgrounds": "FID", "parking": "FID", "buildings": "FID",
              "picnic_grounds": "FID"}
MAX_FILE_BYTES = 64 * 1024 * 1024


class QueryError(ValueError):
    """A fixed public query explanation that is safe to transmit over radio."""


def read_json(path, limit):
    """Read bounded JSON without trusting a manifest's declared file size."""
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Reference exceeds read bound")
    return raw, json.loads(raw)


def verified_json(directory, relative, metadata):
    """Verify source bytes before using a collection or repair report."""
    with checked_path(directory, relative).open('rb') as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('Reference exceeds read bound')
    if len(raw) != metadata["byte_count"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
        raise ValueError("Dataset integrity failure")
    return json.loads(raw)


def load_snapshot(names=("park_boundaries", "park_entry_points"), *, directory=None):
    """Verify selected Parks collections, preserving the W03 default pair.

    A caller aggregating sources may supply an already resolved directory and
    retain its own final generation/removal check across the entire operation.
    """
    if not names or any(name not in SOURCE_IDS for name in names):
        raise ValueError("Unknown Parks collection")
    directory = directory if directory is not None else resolve("california_state_parks", ROOT.parent / "data/california_state_parks")
    manifest_path = checked_path(directory, "sources.json")
    manifest_bytes, manifest = read_json(manifest_path, 4 * 1024 * 1024)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or manifest.get("geojson_crs") != "EPSG:4326":
        raise ValueError("Unsupported Parks manifest")
    datasets = {}
    for name in names:
        oid = SOURCE_IDS[name]
        entry = manifest["datasets"][name]
        if entry["object_id_field"] != oid:
            raise ValueError("Unexpected source ID field")
        data = verified_json(directory, entry["path"], entry)
        if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
            raise ValueError("Invalid dataset")
        features = data["features"]
        ids = []
        for feature in features:
            if not isinstance(feature, dict) or feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
                raise ValueError("Invalid feature")
            ident = feature["properties"][oid]
            if type(ident) is not int or ident < 0:
                raise ValueError("Invalid source ID")
            ids.append(ident)
        if len(features) != entry["feature_count"] or len(set(ids)) != len(ids):
            raise ValueError("Dataset identity mismatch")
        datasets[name] = features
    repair = manifest["datasets"]["park_boundaries"].get("geometry_repair") if "park_boundaries" in names else None
    datasets["repaired_ids"] = set()
    if repair is not None:
        relative = repair["report_path"]
        report = verified_json(directory, relative, manifest["files"][relative])
        repaired = [row["object_id"] for row in report["features"]]
        boundary_ids = {feature["properties"]["FID"] for feature in datasets["park_boundaries"]}
        if (any(type(ident) is not int for ident in repaired)
                or len(set(repaired)) != len(repaired)
                or len(repaired) != repair["repaired_feature_count"]
                or not set(repaired) <= boundary_ids):
            raise ValueError("Invalid repair identities")
        datasets["repaired_ids"] = set(repaired)
    if read_json(manifest_path, 4 * 1024 * 1024)[0] != manifest_bytes:
        raise ValueError("Dataset changed; retry")
    return datasets


def unit(value):
    """Normalize numeric unit identifiers while preserving zero-padded string IDs."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return ""


def normalized(value):
    """Normalize whitespace and case for exact-name matching."""
    return " ".join(str(value or "").split()).casefold()


def choices(command, selector, ids):
    """Offer whole candidate IDs within the reply budget without choosing a record."""
    return compact_fields(f"Ambiguous; use !{command} {selector}:", sorted(ids))


def boundary_identity(feature):
    """Keep records without a unit ID distinct using their verified source ID."""
    p = feature["properties"]
    ident = unit(p.get("UNITNBR"))
    return "unit " + ident if ident else "FID " + str(p["FID"])


def nearest(words, datasets):
    """Rank mapped boundaries in California Albers; incomplete geometry fails closed.

    The coordinate envelope bounds supported queries, not California membership.
    Repaired interiors remain uncertain even when their topology is valid.
    """
    if len(words) != 3:
        raise QueryError("Use !statepark near LAT LON")
    try:
        lat, lon = float(words[1]), float(words[2])
    except ValueError:
        raise QueryError("Use !statepark near LAT LON") from None
    if not math.isfinite(lat) or not math.isfinite(lon) or not 32 <= lat <= 42.1 or not -125 <= lon <= -114:
        raise QueryError("Location outside supported coordinate bounds.")
    from shapely.geometry import shape, Point
    from shapely.ops import transform
    from shapely.errors import ShapelyError
    from pyproj import Transformer, network
    network.set_network_enabled(False)
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    point = transform(project, Point(lon, lat))
    ranked = []
    for feature in datasets["park_boundaries"]:
        try:
            geom = shape(feature.get("geometry"))
            if geom.is_empty or not geom.is_valid or geom.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError("Invalid mapped boundary")
            west, south, east, north = geom.bounds
            if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
                raise ValueError("Invalid geographic coordinates")
            projected = transform(project, geom)
            distance = projected.distance(point)
            if not projected.is_valid or not math.isfinite(distance):
                raise ValueError("Invalid projected boundary")
        except (AttributeError, IndexError, KeyError, TypeError, ValueError, ShapelyError):
            raise QueryError("Mapped boundary coverage incomplete or invalid.") from None
        ranked.append((distance, feature))
    if not ranked:
        raise QueryError("No mapped boundaries available.")
    ranked.sort(key=lambda item: item[0])
    distance, feature = ranked[0]
    tied = [f for d, f in ranked if math.isclose(distance, d, rel_tol=0, abs_tol=0.01)]
    if len({boundary_identity(f) for f in tied}) > 1:
        return compact_fields("Multiple mapped parks equally near.", [boundary_identity(f) for f in tied])
    repaired = datasets.get("repaired_ids", set())
    qualifier = "; repair uncertain" if any(f["properties"]["FID"] in repaired for f in tied) else ""
    return compact_fields(f"Boundary approx; {boundary_identity(feature)}; {distance / 1609.344:.1f} mi{qualifier}",
                          [str(feature["properties"].get("UNITNAME") or "Unnamed"), "Access status unknown"])


def lookup(command, query, datasets):
    """Select a park or entrance; ambiguity never selects an arbitrary feature."""
    query = query.strip()
    if not query or normalized(query) == "help":
        return "Use !statepark NAME | id UNIT | near LAT LON" if command == "statepark" else "Use !entrance PARK | unit UNIT | id ENTRANCE_ID"
    boundaries = datasets["park_boundaries"]
    entrances = datasets["park_entry_points"]
    words = query.split()
    if command == "entrance" and words[0].casefold() == "id" and len(words) == 2:
        found = [x for x in entrances if str(x["properties"].get("OBJECTID")) == words[1]]
    elif command == "statepark" and words[0].casefold() == "near":
        return nearest(words, datasets)
    else:
        if words[0].casefold() in {"id", "unit"} and (len(words) != 2 or words[0].casefold() == "unit" and command == "statepark"):
            raise QueryError("Invalid selector; use !" + command + " help")
        if words[0].casefold() in ({"id"} if command == "statepark" else {"unit"}):
            ids = {words[1]}
        else:
            name = normalized(query)
            ids = {unit(x["properties"].get("UNITNBR")) for x in boundaries if normalized(x["properties"].get("UNITNAME")) == name}
            ids |= {unit(x["properties"].get("UNIT_NBR")) for x in entrances if normalized(x["properties"].get("PARK_NAME")) == name}
            if "" in ids:
                return "Matching park lacks a unit ID; reference ambiguous."
        if len(ids) > 1:
            return choices(command, "id" if command == "statepark" else "unit", ids)
        if not ids:
            return "No matching park in the local reference."
        ident = next(iter(ids))
        found = [x for x in (boundaries if command == "statepark" else entrances) if unit(x["properties"].get("UNITNBR" if command == "statepark" else "UNIT_NBR")) == ident]
    if not found:
        return "No matching reference record."
    if len(found) > 1:
        if command == "entrance":
            return choices(command, "id", {str(x["properties"]["OBJECTID"]) for x in found})
        names = {normalized(item["properties"].get("UNITNAME")) for item in found} - {""}
        if len(names) > 1:
            return "Multiple park names for unit; reference ambiguous."
        found.sort(key=lambda item: not bool(item["properties"].get("UNITNAME")))
    p = found[0]["properties"]
    if command == "statepark":
        classes = {str(x["properties"].get("SUBTYPE") or "Classification unknown") for x in found}
        classification = next(iter(classes)) if len(classes) == 1 else "Classification varies"
        return compact_fields("Park reference; " + boundary_identity(found[0]), [str(p.get("UNITNAME") or "Unnamed"), classification])
    geometry = found[0].get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        raise QueryError("Entrance coordinates unavailable.")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise QueryError("Invalid entrance coordinates.")
    lon, lat = coordinates[:2]
    if type(lat) not in (int, float) or type(lon) not in (int, float) or not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise QueryError("Invalid entrance coordinates.")
    return compact_fields("Entrance reference " + str(p["OBJECTID"]) + ": " + f"{lat:.5f},{lon:.5f}",
                          [str(p.get("PARK_NAME") or "Unnamed park"), str(p.get("STREET_ADDRESS") or "Address unrecorded")])


def main(command, argv=None):
    """Execute one query without network access or dataset mutation."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("Use a single quoted query.")
        return 0
    query = args[0] if args else "help"
    if len(query.encode("utf-8")) > 150 or not all(c.isprintable() for c in query):
        print("Invalid query.")
        return 0
    try:
        if not query.strip() or normalized(query) == "help":
            output = lookup(command, query, {})
        else:
            output = lookup(command, query, load_snapshot())
    except QueryError as exc:
        output = str(exc)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, RuntimeError):
        output = "State Parks data unavailable or invalid."
    print(compact_fields(output))
    return 0
