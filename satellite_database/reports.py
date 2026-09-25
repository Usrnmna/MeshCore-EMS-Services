"""Read AMSAT reception reports as text; never execute downloaded JavaScript."""

import hashlib
import html
import re
from datetime import datetime


def parse_amsat_reports(document):
    """Extract timestamped tooltip reports, including negative/ambiguous reports."""
    tips = dict(re.findall(r"tips\.(a\d+)\s*=\s*new Array\([^\n]*?'(.*?)'\);", document))
    result = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", document, re.I | re.S):
        label = re.search(r">([^<>]+)_\[([^<>]+)\]</a>", row)
        if not label:
            continue
        name, mode = map(html.unescape, label.groups())
        for tip_id in re.findall(r"docTips\.show\('(a\d+)'\)", row):
            for entry in re.split(r"<br\s*/?><br\s*/?>", tips.get(tip_id, ""), flags=re.I):
                fields = [html.unescape(s).strip() for s in re.split(r"<br\s*/?>", entry, flags=re.I)]
                if len(fields) != 5:
                    continue
                status, callsign, grid, date, time = fields
                match = re.match(r"(\d{1,2}):(\d{2})-:(\d{2}) UTC", time)
                if not match or status not in ("Heard", "Not Heard", "Telemetry Only"):
                    continue
                try:
                    timestamp = datetime.fromisoformat(date + "T%02d:%02d:00+00:00" % (int(match[1]), int(match[2])))
                except ValueError:
                    continue
                report = {"satellite_label": name, "mode_label": mode.replace("_", " "), "reported_status": status,
                          "observed_at": timestamp.isoformat(), "time_resolution": "15-minute reporting interval",
                          "callsign": callsign, "grid": grid}
                report["report_id"] = hashlib.sha256(repr(sorted(report.items())).encode()).hexdigest()
                result.append(report)
    if not tips or not result:
        raise ValueError("AMSAT status page layout changed or has no parsable reports")
    return result


def match_operation(report, satellites, operations, mappings):
    """Only unambiguous existing capabilities receive a status observation."""
    label = report["satellite_label"] + " [" + report["mode_label"] + "]"
    explicit = mappings.get(label)
    if explicit:
        return explicit if explicit in operations else None
    candidates = []
    for sat in satellites.values():
        aliases = [sat["name"]] + sat.get("aliases", [])
        if report["satellite_label"].casefold() not in [a.casefold() for a in aliases]:
            continue
        for op in operations.values():
            if op["satellite_id"] != sat["satellite_id"] or op["source_reported_status"] != "active":
                continue
            mode = report["mode_label"]
            scopes = op["scopes"]
            matched = ((mode == "FM" and "two_way_voice" in scopes and op["source_mode"] in ("FM", "FMN", "NFM"))
                       or (mode in ("SSTV", "SSDV") and mode in op["protocols"])
                       or (mode == "DATV" and "digital_television" in scopes)
                       or (mode in ("DVB-S", "DVB-S2") and mode in op["protocols"])
                       or (mode == "TLM" and "telemetry" in scopes)
                       or (mode == "Music" and "downlink_audio" in scopes))
            if mode in ("VHF Digi", "UHF Digi") and "two_way_data" in scopes:
                down = op.get("downlink_low_hz")
                matched = bool(down and ((mode == "VHF Digi" and 30e6 <= down < 300e6)
                                        or (mode == "UHF Digi" and 300e6 <= down < 3e9)))
            if mode == "NB" and "two_way_voice" in scopes:
                matched = op.get("source_mode") in ("USB", "LSB", "SSB")
            if mode in ("V/u", "U/v", "V/a") and "two_way_voice" in scopes:
                up, down = op.get("uplink_low_hz"), op.get("downlink_low_hz")
                matched = bool(up and down and ((mode == "V/u" and 144e6 <= up <= 146e6 and 435e6 <= down <= 438e6)
                           or (mode == "U/v" and 430e6 <= up <= 438e6 and 144e6 <= down <= 146e6)
                           or (mode == "V/a" and 144e6 <= up <= 146e6 and 28e6 <= down <= 30e6)))
            if matched:
                candidates.append(op["operation_id"])
    return candidates[0] if len(candidates) == 1 else None
