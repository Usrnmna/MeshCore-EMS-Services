"""Bounded facility references from independently verified EBMUD and Parks data.

Only explicit source classifications qualify. Coincident points and matching
names remain distinct; an EBMUD amenity flag locates a reference site, not a tap
or building. No query establishes public access or current operating status.
"""
import math
import os
import re
import sys

if __package__:
    from .gis_data import Snapshot, load_settings
    from .parks_sites import coordinates, parse as parse_site
    from .response_text import MESSAGE_BYTES, compact_fields
    from .stateparks_lookup import QueryError, load_snapshot, normalized
else:
    from gis_data import Snapshot, load_settings
    from parks_sites import coordinates, parse as parse_site
    from response_text import MESSAGE_BYTES, compact_fields
    from stateparks_lookup import QueryError, load_snapshot, normalized

CATEGORIES = ("restrooms", "water", "picnic", "visitors", "boatlaunch")
SOURCES = ("ebmud", "parks")
EBMUD_FIELDS = {"restrooms": ("RESTROOM", {"yes": "restroom", "ada": "restroom ADA"}),
                "water": ("DRINKING_WATER", {"yes": "water"}),
                "picnic": ("PICNIC_AREA", {"yes": "picnic"}),
                "boatlaunch": ("BOAT_LAUNCH", {"yes": "boatlaunch"})}
PARKS_TYPES = {
    "restrooms": ("buildings", {
        "Comfort station": "restroom", "Unisex comfort station": "unisex restroom",
        "Vault toilet": "vault toilet", "Chemical toilet": "chemical toilet",
        "Pit Toilet": "pit toilet", "Flush toilet": "flush toilet",
        "Floating restroom": "floating restroom", "Comfort station/dressing room": "restroom/dressing",
    }),
    "visitors": ("buildings", {"Museum/Visitor center": "museum/visitor"}),
    "picnic": ("picnic_grounds", {
        "Developed Family Picnic Area": "family picnic", "Primitive Family Picnic Area": "primitive family picnic",
        "Developed Group Picnic Area": "group picnic", "Primitive Group Picnic Area": "primitive group picnic",
    }),
}
# SHARE describes publication, not access permission. Staff/service context is
# conservatively excluded even in published records. Free text never qualifies
# a facility positively, including generic fountains, ramps and combo buildings.
NONPUBLIC_CONTEXT = re.compile(r"\b(?:staff|employee|employees|admin|administration|private|restricted)\b|\bservice\s+(?:yard|rd|road)\b", re.I)
# Preserve entire condition text rather than turning a historical or uncertain
# note into a present-tense status. Negations remain attached to their wording.
QUALIFIED_CONTEXT = re.compile(
    r"\b(?:ADA|accessible|accessibility|closed|seasonal|reservations?|reservable|permits?|only|"
    r"removed|abandoned|demolished|locked|limited|hours|temporary|temporarily|unavailable|inoperable|"
    r"out\s+of\s+(?:service|order)|not\s+(?:working|operating))\b", re.I)
SOURCE_FAILURES = (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, ImportError, OverflowError)


def parse(text):
    """Accept CATEGORY near LAT LON [MILES] [source=ebmud|parks]."""
    if len(text.encode("utf-8")) > 150 or any(not c.isprintable() for c in text):
        raise QueryError("Invalid facility query; maximum 150 UTF-8 bytes.")
    words = text.split()
    if not words or words[0].casefold() == "help":
        if len(words) > 2:
            raise QueryError("Use !facility help or help categories/sources")
        return "help", words[1].casefold() if len(words) == 2 else "", SOURCES
    category = words.pop(0).casefold()
    if category not in CATEGORIES:
        raise QueryError("Unknown category; use !facility help categories")
    sources, selected, coordinates_text = SOURCES, False, []
    for word in words:
        if word.casefold().startswith("source="):
            source = word.split("=", 1)[1].casefold()
            if selected or source not in SOURCES:
                raise QueryError("Use one source=ebmud or source=parks")
            sources, selected = (source,), True
        else:
            coordinates_text.append(word)
    parsed = parse_site("camp", " ".join(coordinates_text))
    if parsed[0] != "near" or parsed[2]:
        raise QueryError("Use CATEGORY near LAT LON [MILES] [source=SOURCE]")
    return category, parsed[1], sources


def help_text(topic):
    """Describe the complete bounded grammar without accessing datasets."""
    if topic == "categories":
        return "Categories: " + " ".join(CATEGORIES)
    if topic == "sources":
        return "Optional source=ebmud or source=parks; default both"
    if topic:
        raise QueryError("Use !facility help categories or help sources")
    return "!facility CATEGORY near LAT LON [MILES]; help categories/sources"


def load_source(source, category):
    """Pin one source generation, validate IDs, and retain source attributes."""
    if source == "parks":
        layer = PARKS_TYPES[category][0]
        return load_snapshot((layer,))[layer]
    settings = load_settings()
    snapshot = Snapshot(settings["data_directory"])
    if snapshot.manifest.get("coordinate_reference_system") != "WGS 84 (EPSG:4326)":
        raise ValueError("Unsupported EBMUD CRS")
    records = snapshot.load_dataset("recreation_points")
    seen = set()
    for record in records:
        ident = record["properties"]["OBJECTID"]
        if type(ident) is not int or ident < 0 or ident in seen:
            raise ValueError("Invalid EBMUD source IDs")
        seen.add(ident)
    snapshot.verify_unchanged()
    return records


def classification(source, category, properties):
    """Return the qualified facility label only for an explicit eligible record."""
    if source == "ebmud":
        field, accepted = EBMUD_FIELDS[category]
        if NONPUBLIC_CONTEXT.search(str(properties.get("LABEL") or "") + " " + str(properties.get("COMMENT_") or "")):
            return None
        return accepted.get(normalized(properties.get(field)))
    if normalized(properties.get("SHARE")) != "public" or NONPUBLIC_CONTEXT.search(str(properties.get("DETAIL") or "")):
        return None
    accepted = PARKS_TYPES[category][1]
    return next((label for raw, label in accepted.items() if normalized(properties.get("TYPE")) == normalized(raw)), None)


def rank_source(source, category, location, geod):
    """Filter before measuring; incomplete eligible geometry marks partial coverage."""
    lat, lon, radius = location
    candidates, incomplete = [], False
    for record in load_source(source, category):
        p = record["properties"]
        label = classification(source, category, p)
        if label is None:
            continue
        try:
            target_lat, target_lon = coordinates(record)
            miles = geod.inv(lon, lat, target_lon, target_lat)[2] / 1609.344
            if not math.isfinite(miles):
                raise ValueError("Invalid distance")
        except (QueryError, ValueError, TypeError, OverflowError):
            incomplete = True
            continue
        if miles > radius and not math.isclose(miles, radius, rel_tol=0, abs_tol=1e-9):
            continue
        ident = p["OBJECTID" if source == "ebmud" else "FID"]
        name = p.get("LABEL" if source == "ebmud" else "DETAIL")
        context = [name, p.get("COMMENT_")] if source == "ebmud" else [name]
        conditions = " / ".join(dict.fromkeys(" ".join(str(value).split()).replace("|", "/")
                                for value in context if value and QUALIFIED_CONTEXT.search(str(value))))
        candidates.append({"source": source, "id": ident, "label": label, "name": name,
                           "conditions": conditions, "latitude": target_lat,
                           "longitude": target_lon, "miles": miles})
    return candidates, "incomplete" if incomplete else "checked"


def format_result(category, candidates, statuses):
    """Retain partial coverage and source qualifications in the mandatory core."""
    partial = any(status != "checked" for status in statuses.values())
    suffix = "; partial" if partial else ""
    notes = [source + " " + status for source, status in statuses.items() if status != "checked"]
    if not candidates:
        if all(status == "unsupported" for status in statuses.values()):
            return compact_fields("Category unsupported for requested source(s).", notes)
        if all(status in {"unsupported", "unavailable"} for status in statuses.values()):
            return compact_fields("Facility source data unavailable" + suffix, notes)
        message = "No match in available data within radius" if partial else "No matching mapped reference within radius"
        return compact_fields(message + suffix, notes)
    candidates.sort(key=lambda c: (c["miles"], c["source"], c["id"]))
    first = candidates[0]
    tied = [c for c in candidates if math.isclose(c["miles"], first["miles"], rel_tol=0, abs_tol=0.01 / 1609.344)]
    if len(tied) > 1:
        return compact_fields("Multiple equally near references" + suffix,
                              [f"{c['source']}#{c['id']}" for c in tied] + notes)
    # EBMUD flags locate a site; Parks records locate a classified feature.
    kind = "site ref" if first["source"] == "ebmud" else "ref"
    caution = "potability unknown" if category == "water" else "access unknown"
    core = f"{first['source']}#{first['id']} {first['label']} {kind}; {caution}{suffix}"
    if first["conditions"]:
        # Qualifying source wording is indivisible, including negations and counts.
        # If it cannot fit, do not transmit a shorter unqualified facility claim.
        core += "; note: " + first["conditions"]
        budget = MESSAGE_BYTES - len(("@" + os.environ.get("MESHCORE_SENDER", "Reader") + " ").encode())
        if len(core.encode()) > budget:
            return compact_fields(f"{first['source']}#{first['id']} qualified ref; conditions cannot fit{suffix}", notes)
    name = " ".join(str(first["name"] or "Unnamed reference").split()).replace("|", "/")
    # A name already retained in a mandatory note must not displace coordinates.
    labels = [] if name in first["conditions"] else [name]
    return compact_fields(core, notes + [f"{first['miles']:.2f} mi straight-line"] + labels +
                          [f"{first['latitude']:.5f},{first['longitude']:.5f}"])


def lookup(parsed):
    """Rank verified source candidates independently, disclosing failures or gaps."""
    category, location, sources = parsed
    if category == "help":
        return help_text(location)
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    candidates, statuses = [], {}
    for source in sources:
        supported = EBMUD_FIELDS if source == "ebmud" else PARKS_TYPES
        if category not in supported:
            statuses[source] = "unsupported"
            continue
        try:
            records, statuses[source] = rank_source(source, category, location, geod)
            candidates.extend(records)
        except SOURCE_FAILURES:
            statuses[source] = "unavailable"
    return format_result(category, candidates, statuses)


def main(argv=None):
    """Return one radio reply; no downloads, dataset writes, or scheduling occur."""
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) > 1:
            raise QueryError("Use a single quoted facility query.")
        output = lookup(parse(args[0] if args else "help"))
    except QueryError as exc:
        output = str(exc)
    except SOURCE_FAILURES:
        output = "Facility data or proximity dependency unavailable."
    print(compact_fields(output))
    return 0
