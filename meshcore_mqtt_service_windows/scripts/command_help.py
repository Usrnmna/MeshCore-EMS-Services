"""Show channel-filtered command help; standalone channel availability is unknown."""
import json
import os
import sys
from response_text import compact_fields
from command_dependencies import dependency_status

TOPICS = {
    "geography": ("!where",),
    "parks": ("!trail", "!rec", "!peak", "!park", "!boundary", "!statepark", "!entrance", "!camp", "!parking"),
    "sites": ("!camp", "!parking", "!facility"),
    "water": ("!wateruse", "!downstream", "!tributaries","!gauge", "!gauges","!rivers", "!waterway", "!basin", "!floodstatus", "!floodwarn", "!floodalarm", "!snowpack"),
    "fire": ("!firezone", "!fires", "!fire", "!firewx", "!firewarn", "!firedata", "!firealarm", "!smoke", "!firedanger"),
    "weather": ("!brief", "!weather", "!aqi", "!uv", "!heatadv", "!lightning", "!traffic"),
    "landslide": ("!slidewarn", "!slidealarm", "!slideinfo"),
    "service": ("!help", "!data", "!status", "!time"),
    "satellites": ("!sat", "!satfreq", "!satpoint", "!satpass"),
}
SYNTAX = {
    "!brief": "!brief [alerts|weather|fire|water] LOCATION",
    "!weather": "!weather [hourly|wind] LOCATION",
    "!where": "!where LAT LON [park|basin|firezone]",
    "!satpass": "!satpass ID LAT LON; help",
    "!satpoint": "!satpoint ID LAT LON; help",
    "!sat": "!sat NORAD-ID or name NAME", "!satfreq": "!satfreq NORAD-ID; help",
    "!wateruse": "!wateruse ID or name NAME; help",
    "!downstream": "!downstream help", "!tributaries": "!tributaries help",
    "!gauge": "!gauge AGENCY-ID; help", "!gauges": "!gauges near LAT LON [MILES]",
    "!help": "!help [topic or command]", "!data": "!data DATASET; help", "!status": "!status", "!time": "!time",
    "!aqi": "!aqi LAT LON", "!rivers": "!rivers LAT LON", "!traffic": "!traffic ROUTE",
    "!uv": "!uv LOCATION", "!heatadv": "!heatadv LOCATION", "!lightning": "!lightning LOCATION",
    "!snowpack": "!snowpack LOCATION", "!waterway": "!waterway LOCATION/name/id; help", "!basin": "!basin LOCATION/parent ID; help",
    "!floodstatus": "!floodstatus LOCATION", "!floodwarn": "!floodwarn LOCATION",
    "!floodalarm": "!floodalarm LOCATION; help",
    "!slidewarn": "!slidewarn LOCATION", "!slidealarm": "!slidealarm on LOCATION; help",
    "!slideinfo": "!slideinfo LOCATION or station ID", "!firezone": "!firezone ZONE or LOCATION",
    "!fires": "!fires ZONE or LOCATION", "!fire": "!fire INCIDENT", "!firewx": "!firewx ZONE or LOCATION",
    "!firewarn": "!firewarn ZONE or LOCATION", "!firedata": "!firedata CATEGORY ZONE or LOCATION",
    "!firealarm": "!firealarm on LOCATION; help", "!smoke": "!smoke LOCATION",
    "!firedanger": "!firedanger LOCATION",
    **{name: name + " NAME | near LAT LON | help" for name in TOPICS["parks"]},
    "!boundary": "!boundary LAT LON; help",
    "!statepark": "!statepark NAME; help", "!entrance": "!entrance PARK; help",
    "!camp": "!camp NAME; help", "!parking": "!parking NAME; help",
    "!facility": "!facility help",
}


DESCRIPTIONS = {
    "!brief": "Selected location briefing; not all-clear",
    "!weather": "NWS forecast, not observations",
    "!where": "Installed geographic containment",
    "!satpass": "Bounded GIS-qualified pass prediction",
    "!satpoint": "GIS-qualified predicted pointing",
    "!sat": "Satellite catalog identity", "!satfreq": "Recorded operation frequencies",
    "!wateruse": "Basin Plan use designations",
    "!help": "Command discovery", "!data": "Dataset status", "!status": "Local service check", "!time": "Local time",
    "!aqi": "Air quality", "!rivers": "Nearby river stations", "!traffic": "Highway restrictions",
    "!uv": "UV index", "!heatadv": "Heat alerts", "!lightning": "Lightning potential",
    "!snowpack": "Snow depth and forecast", "!waterway": "Waterway context", "!basin": "Watershed context",
    "!floodstatus": "Flood conditions", "!floodwarn": "Flood alerts", "!floodalarm": "Flood monitoring",
    "!slidewarn": "Landslide-related alerts", "!slidealarm": "Landslide alert monitoring",
    "!slideinfo": "Research station information", "!firezone": "Fire-weather zone",
    "!fires": "Fire incidents", "!fire": "Fire incident details", "!firewx": "Fire-weather forecast",
    "!firewarn": "Fire-weather alerts", "!firedata": "Fire context", "!firealarm": "Fire monitoring",
    "!smoke": "Smoke context", "!firedanger": "Fire-danger context", "!trail": "Trail information",
    "!statepark": "California State Parks", "!entrance": "Park entrance",
    "!camp": "Campground/site records", "!parking": "Parking references",
    "!facility": "Facility references",
    "!rec": "Recreation amenities", "!peak": "Mapped peaks", "!park": "Local parks", "!boundary": "Mapped boundaries",
}


def main():
    """Print bounded discovery using only the requesting channel's safe catalog.

    Catalog values identify recognized shipped registrations, not configuration
    details. Dependency checks are local and read-only. Availability of remote
    providers and location-specific results is never inferred from registration.
    """
    query = sys.argv[1] if len(sys.argv) == 2 else ""
    if len(sys.argv) > 2 or not all(c.isprintable() for c in query) or len(query.encode("utf-8")) > 150:
        print(compact_fields("Invalid help query."))
        return
    raw = os.environ.get("MESHCORE_HELP_COMMANDS")
    if raw is None:
        print(compact_fields("Channel availability unknown.", ["Use !help on a configured channel."]))
        return
    try:
        if len(raw.encode("utf-8")) > 16384:
            raise ValueError("Catalog exceeds context limit")
        allowed = json.loads(raw)
        if not isinstance(allowed, dict) or not all(isinstance(k, str) and k.isprintable() and type(v) is bool for k, v in allowed.items()):
            raise ValueError("Invalid catalog")
    except (ValueError, TypeError):
        print(compact_fields("Command availability unavailable."))
        return
    known = {name for names in TOPICS.values() for name in names}
    topics = dict(TOPICS, other=tuple(sorted(set(allowed) - known)))
    if not query:
        names = [name for name, commands in topics.items() if any(c in allowed for c in commands)]
        print(compact_fields("Help topics: " + " ".join(names), ["Use !help TOPIC or !help COMMAND"]))
    elif query.lower() in topics:
        names = [name for name in topics[query.lower()] if name in allowed]
        fields = []
        for name in names:
            status = dependency_status(name, allowed[name])
            suffix = " (unavailable)" if status.startswith("Unavailable:") else " (partial)" if status.startswith("Partial:") else ""
            fields.append(name + suffix)
        print(compact_fields(query.lower() + ":" if names else query.lower() + ": No commands enabled", fields + ["Use !help COMMAND"]))
    elif query in allowed:
        status = dependency_status(query, allowed[query])
        syntax = SYNTAX.get(query, "Syntax unverified") if allowed[query] else "Syntax unverified"
        # Keep availability and primary syntax visible for 80-byte sender tags.
        label = status.split(":", 1)[0] if ":" in status else status.split(";", 1)[0]
        reason = status.split(":", 1)[1].strip() if ":" in status else ""
        description = DESCRIPTIONS.get(query, "") if allowed[query] else ""
        print(compact_fields(query + ": " + label, [syntax, reason, description]))
    else:
        print(compact_fields("Command or topic unavailable on this channel."))


if __name__ == "__main__":
    main()
