"""Offline campground/site-group and parking-point reference queries.

Filters describe recorded attributes, never present access, vacancy, or fees.
Exact facility names and source FIDs identify features rather than whole parks.
"""
import math
from pathlib import Path
import sys

if __package__:
    from .stateparks_lookup import QueryError, choices, load_snapshot, normalized, read_json, unit
    from .response_text import compact_fields
else:
    from stateparks_lookup import QueryError, choices, load_snapshot, normalized, read_json, unit
    from response_text import compact_fields

SETTINGS_FILE = Path(__file__).resolve().parents[1] / "gis_settings.json"
LAYERS = {"camp": ("campgrounds", "Campground"), "parking": ("parking", "NAME")}
# Exact values in the installed Parks layer attributes. Unknown values never
# satisfy an affirmative filter. Slugs are radio query values, not new categories.
CAMP_TYPES = {
    "developed-family": "Developed Family Camp Area", "developed-group": "Developed Group Camp Area",
    "primitive-family": "Primitive Family Camp Area", "primitive-group": "Primitive Group Camp Area",
    "environmental": "Environmental Camp Area", "hike-bike": "Hike/Bike Camp Area",
    "horse": "Horse Camp Area", "enroute": "Enroute Camp Area",
    "walk-in": "Walk-in Camp Area", "trail": "Trail Camp",
}
CAMP_SUBTYPES = {"tent-only": "Tent Only", "walk-in": "Walk-in", "boat-in": "Boat-in",
                 "hookups": "Hookups", "rental-cabins": "Rental Cabins", "tent-cabins": "Tent Cabins",
                 "multiple": "Multiple types"}
PARKING_TYPES = {"vehicle": "Vehicle", "boat": "Boat", "equestrian": "Equestrian",
                 "rv-bus-trailer": "RV/Bus/Trailer", "administrative": "Administrative",
                 "campground-spur": "Campground Spur"}
PARKING_USES = {"day-fee": "Day Use (Fee)", "day-no-fee": "Day Use (No Fee)",
                "restroom": "Rest Room/Shower", "short-term": "Other Short Term Parking",
                "group-camp": "Group Camp", "overflow": "Campground Overflow",
                "admin": "Admin Office", "service": "DPR Service Areas"}
FILTERS = {
    "camp": {"type": ("TYPE", CAMP_TYPES), "subtype": ("SUBTYPE", CAMP_SUBTYPES)},
    "parking": {"type": ("SUBTYPE", PARKING_TYPES), "use": ("USETYPE", PARKING_USES),
                "trailhead": ("TRAILHEAD", {"yes": "Yes", "no": "No"})},
}
# Named help groups keep every accepted value discoverable in a single reply,
# including with the maximum sender tag. Each group lists whole filter tokens.
HELP_GROUPS = {
    "camp": {
        "type": {"developed": ("developed-family", "developed-group"),
                 "primitive": ("primitive-family", "primitive-group"),
                 "other": ("environmental", "hike-bike", "horse", "unknown"),
                 "access": ("enroute", "walk-in", "trail")},
        "subtype": {"access": ("walk-in", "boat-in"),
                    "stay": ("tent-only", "hookups", "rental-cabins", "tent-cabins"),
                    "other": ("multiple", "unknown")},
    },
    "parking": {
        "type": {"vehicle": ("vehicle", "rv-bus-trailer", "boat", "equestrian"),
                 "other": ("administrative", "campground-spur", "unknown")},
        "use": {"day": ("day-fee", "day-no-fee", "restroom", "short-term"),
                "camp": ("group-camp", "overflow"), "other": ("admin", "service", "unknown")},
    },
}


def radius_limit():
    """Read the existing GIS radius setting without requiring the EBMUD dataset."""
    _, settings = read_json(SETTINGS_FILE, 65536)
    limit = settings["maximum_radius_miles"]
    try:
        valid = type(limit) in (int, float) and limit > 0 and math.isfinite(limit)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Invalid GIS radius limit")
    return limit


def help_text(command, topic=""):
    """Expose bounded syntax and field-specific filter values without loading data."""
    words = topic.split()
    if words and words[0] in FILTERS[command]:
        field = words[0]
        groups = HELP_GROUPS[command].get(field, {})
        if len(words) == 1:
            if groups:
                return compact_fields("help " + field + " GROUP: " + ",".join(groups))
            values = list(FILTERS[command][field][1]) + ["unknown"]
        elif len(words) == 2 and words[1] in groups:
            values = groups[words[1]]
        else:
            raise QueryError("Unknown help group; use help " + field)
        return compact_fields(field + "=" + ",".join(values))
    if topic == "filters":
        return compact_fields("Append KEY=VALUE; help KEY for values", list(FILTERS[command]))
    syntax = {"name": f"!{command} name NAME (literal, without filters)",
              "near": f"!{command} near LAT LON [MILES]; help filters",
              "id": f"!{command} id FID; help filters",
              "unit": f"!{command} unit UNIT; help filters"}
    if topic in syntax:
        return compact_fields(syntax[topic])
    if topic:
        raise QueryError("Unknown help topic; use !" + command + " help")
    return compact_fields(f"!{command} NAME; help near/name/id/unit/filters")


def parse(command, text):
    """Parse literal selectors and AND-combined exact attribute filters."""
    if len(text.encode("utf-8")) > 150 or any(not c.isprintable() for c in text):
        raise QueryError("Invalid query; maximum 150 UTF-8 bytes.")
    words = text.split()
    if not words:
        return "help", "", {}
    if words[0].casefold() == "name":
        if len(words) < 2:
            raise QueryError("Use name NAME for a literal facility name.")
        return "name", normalized(" ".join(words[1:])), {}
    if words[0].casefold() == "help":
        if len(words) > 3:
            raise QueryError("Use help FILTER [GROUP]")
        return "help", " ".join(words[1:]).casefold(), {}
    filters, selector = {}, []
    for word in words:
        if "=" not in word:
            selector.append(word)
            continue
        key, value = word.casefold().split("=", 1)
        if key not in FILTERS[command] or key in filters:
            raise QueryError("Invalid or repeated filter; use help filters")
        if value not in FILTERS[command][key][1] and value != "unknown":
            raise QueryError("Unknown filter value; use help " + key)
        filters[key] = value
    if not selector:
        raise QueryError("Supply a facility name, id, unit, or near LAT LON.")
    mode = selector[0].casefold()
    if mode == "near":
        if len(selector) not in (3, 4):
            raise QueryError("Use near LAT LON [MILES]")
        try:
            values = [float(value) for value in selector[1:]]
        except ValueError:
            raise QueryError("Coordinates and radius must be numbers.") from None
        if not all(math.isfinite(value) for value in values):
            raise QueryError("Coordinates and radius must be finite.")
        lat, lon = values[:2]
        if not 32 <= lat <= 42.1 or not -125 <= lon <= -114:
            raise QueryError("Location outside supported coordinate bounds.")
        limit = radius_limit()
        radius = values[2] if len(values) == 3 else limit
        if not 0 < radius <= limit:
            raise QueryError(f"Radius must be >0 and <= {limit:g} miles.")
        return mode, (lat, lon, radius), filters
    if mode in {"id", "unit"}:
        if len(selector) != 2 or (mode == "id" and not selector[1].isascii()) or (mode == "id" and not selector[1].isdigit()):
            raise QueryError("Use id FID or unit UNIT")
        return mode, selector[1], filters
    return "name", normalized(" ".join(selector)), filters


def category(properties, field, mapping):
    """Map exact recorded values; missing, undefined, and new values stay unknown."""
    raw = normalized(properties.get(field))
    return next((key for key, value in mapping.items() if normalized(value) == raw), "unknown")


def eligible(command, properties, filters):
    """Apply every requested attribute predicate before any distance ranking."""
    return all(category(properties, *FILTERS[command][key]) == value for key, value in filters.items())


def coordinates(feature):
    """Validate a recorded point; never substitute a park centroid or entrance."""
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        raise QueryError("Eligible site coordinates unavailable; nearest unknown.")
    values = geometry.get("coordinates")
    if not isinstance(values, list) or len(values) < 2:
        raise QueryError("Eligible site coordinates invalid; nearest unknown.")
    lon, lat = values[:2]
    if (type(lat) not in (int, float) or type(lon) not in (int, float)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180
            or not math.isfinite(lat) or not math.isfinite(lon)):
        raise QueryError("Eligible site coordinates invalid; nearest unknown.")
    return lat, lon


def format_record(command, feature, datasets, distance=None):
    """Keep the source ID/reference qualifier and proximity distance mandatory.

    Names, source categories, coordinates and park association fit as whole fields.
    Campground records may describe individual site groups, not an entire camp.
    """
    p = feature["properties"]
    label = "Camp" if command == "camp" else "Parking"
    essential = f"{label} record #{p['FID']}; reference"
    if distance is not None:
        essential += f"; {distance:.2f} mi straight-line"
    fields = []
    name = " ".join(str(p.get(LAYERS[command][1]) or "").split())
    fields.append(name or "Unnamed feature")
    for key, (field, mapping) in FILTERS[command].items():
        value = category(p, field, mapping)
        # Retain unrecognized source wording as a qualified, whole optional field.
        raw = " ".join(str(p.get(field) or "").split())
        fields.append(f"Recorded {key}: " + (mapping[value] if value != "unknown" else "unknown" + (f" ({raw})" if raw else "")))
    try:
        lat, lon = coordinates(feature)
        fields.insert(1, f"{lat:.5f},{lon:.5f}")
    except QueryError:
        fields.insert(1, "Coordinates unavailable")
    ident = unit(p.get("UNITNBR"))
    if ident:
        fields.append("unit " + ident)
        names = {" ".join(str(f["properties"].get("UNITNAME") or "").split())
                 for f in datasets["park_boundaries"] if unit(f["properties"].get("UNITNBR")) == ident} - {""}
        if len(names) == 1:
            fields.append("Park: " + next(iter(names)))
    return compact_fields(essential, fields)


def lookup(command, parsed, datasets):
    """Return one exact/nearest feature or bounded ambiguity; never choose by name alone."""
    mode, value, filters = parsed
    layer, name_field = LAYERS[command]
    found = [f for f in datasets[layer] if eligible(command, f["properties"], filters)]
    distance = None
    if mode == "near":
        from pyproj import Geod
        geod = Geod(ellps="WGS84")
        lat, lon, radius = value
        ranked = []
        for feature in found:
            target_lat, target_lon = coordinates(feature)
            meters = geod.inv(lon, lat, target_lon, target_lat)[2]
            if not math.isfinite(meters):
                raise QueryError("Site distance unavailable.")
            miles = meters / 1609.344
            if miles <= radius or math.isclose(miles, radius, rel_tol=0, abs_tol=1e-9):
                ranked.append((miles, feature))
        if not ranked:
            return "No eligible mapped record within radius."
        ranked.sort(key=lambda item: item[0])
        distance = ranked[0][0]
        found = [f for d, f in ranked if math.isclose(d, distance, rel_tol=0, abs_tol=0.01 / 1609.344)]
    elif mode == "name":
        found = [f for f in found if normalized(f["properties"].get(name_field)) == value]
    else:
        field = "FID" if mode == "id" else "UNITNBR"
        found = [f for f in found if unit(f["properties"].get(field)) == value]
    if not found:
        return "No matching eligible reference record."
    if len(found) > 1:
        return choices(command, "id", {str(f["properties"]["FID"]) for f in found})
    return format_record(command, found[0], datasets, distance)


def main(command, argv=None):
    """Run one bounded local lookup; expected failures remain usable radio replies."""
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) > 1:
            raise QueryError("Use a single quoted query.")
        parsed = parse(command, args[0] if args else "help")
        if parsed[0] == "help":
            output = help_text(command, parsed[1])
        else:
            datasets = load_snapshot(("park_boundaries", LAYERS[command][0]))
            output = lookup(command, parsed, datasets)
    except QueryError as exc:
        output = str(exc)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, RuntimeError):
        output = "Parks site data or dependency unavailable or invalid."
    print(compact_fields(output))
    return 0
