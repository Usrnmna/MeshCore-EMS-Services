"""Readable scope rules and normalization; no satellite-wide status inference."""

import re
from datetime import datetime, timedelta, timezone


VOICE_MODES = {"FM", "FMN", "NFM", "AM", "USB", "LSB", "SSB", "DSB", "DSTAR"}
WEATHER_FORMATS = {"APT", "LRPT", "HRPT", "AHRPT", "HRIT", "LRIT", "GRB", "EMWIN"}
IMAGE_FORMATS = {"SSTV", "SSDV"}
TV_FORMATS = {"DVB-S", "DVB-S2", "DATV"}
KNOWN_MODULATIONS = {"FM", "FMN", "NFM", "AM", "USB", "LSB", "SSB", "DSB", "CW", "BPSK", "QPSK", "OQPSK", "DQPSK", "GFSK", "GMSK", "AFSK", "FSK", "MSK", "PSK", "64-QAM", "OFDM", "LoRa"}


def has_term(text, term):
    """Match whole terms so APT does not accidentally match 'adapter'."""
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I))


def has_any(text, terms):
    return any(has_term(text, term) for term in terms)


def positive_number(value):
    try:
        value = float(value)
        return value if value > 0 and value < float("inf") else None
    except (ValueError, TypeError):
        return None


def amateur_frequency(value):
    """Discovery hint only, never proof that an uplink is public or permitted."""
    return any(low <= value <= high for low, high in [(28e6, 30e6), (144e6, 146e6), (435e6, 438e6), (1260e6, 1270e6), (2400e6, 2450e6)]) if value else False


def classify(tx, in_amsat, settings):
    """Return scope tags plus an admission reason, or a reason for exclusion."""
    description = str(tx.get("description") or "")
    mode = str(tx.get("mode") or "UNKNOWN")
    text = description + " " + mode
    service = str(tx.get("service") or "Unknown")
    downlink = positive_number(tx.get("downlink_low"))
    uplink = positive_number(tx.get("uplink_low"))
    if has_any(description, settings["excluded_description_terms"]):
        return [], "excluded description"
    if downlink is None:
        return [], "no documented downlink"
    if has_any(service, settings["public_service_terms"]):
        reason = "source identifies amateur service"
    elif has_any(text, settings["public_description_terms"]) or mode == "CW":
        reason = "documented public-interest signal; access requires review"
    elif service == "Meteorological" and has_any(text, WEATHER_FORMATS):
        reason = "documented weather broadcast"
    elif service == "Unknown" and in_amsat and amateur_frequency(downlink):
        reason = "AMSAT catalog and amateur-band downlink; access requires review"
    else:
        return [], "outside public radio scope or insufficient documentation"

    scopes = []
    if has_any(text, WEATHER_FORMATS):
        scopes.append("weather_data")
    if has_any(text, ["EMWIN", "HRIT"]):
        scopes.append("weather_alerts")
    if has_any(text, IMAGE_FORMATS) or has_any(description, ["image", "imaging"]):
        scopes.append("image_downlink")
    if has_any(text, TV_FORMATS) or has_term(text, "HamTV"):
        scopes.append("digital_television")
    if has_any(description, ["telemetry", "TLM", "sensor", "experiment"]):
        scopes.append("telemetry")
    if mode == "CW" or has_term(description, "beacon") or has_term(description, "carrier"):
        scopes.append("beacon")
    if has_any(description, ["music", "audio", "recorded message"]):
        scopes.append("downlink_audio")
    # A digital packet carried over FM is data, not a voice repeater.
    data_hint = has_any(text, ["APRS", "digipeater", "Digi", "packet"])
    if uplink and not scopes:
        scopes.append("two_way_voice" if mode in VOICE_MODES and not data_hint else "two_way_data")
    elif uplink and data_hint:
        scopes.append("two_way_data")
    if not scopes:
        scopes.append("downlink_audio" if mode in VOICE_MODES and not data_hint else "data_downlink")
    return sorted(set(scopes)), reason


def normalize_operation(tx, sat_key, scopes, reason, source_url, fetched_at):
    """Preserve source values and leave unreported parameters null."""
    mode = str(tx.get("mode") or "UNKNOWN")
    description = str(tx.get("description") or mode)
    params = tx.get("params") if isinstance(tx.get("params"), dict) else {}
    uplink = positive_number(tx.get("uplink_low"))
    downlink = positive_number(tx.get("downlink_low"))
    downlink_high = positive_number(tx.get("downlink_high"))
    is_transponder = str(tx.get("type", "")).lower() == "transponder"
    span = downlink_high - downlink if downlink_high and downlink_high > downlink else None
    protocols = sorted(p for p in IMAGE_FORMATS | TV_FORMATS | WEATHER_FORMATS | {"APRS", "AX.25", "LoRa", "DSTAR"} if has_term(description + " " + mode, p))
    # SSTV and LRPT are formats, not modulation types. Never guess the missing modulation.
    modulation = mode if mode in KNOWN_MODULATIONS else next((m for m in sorted(KNOWN_MODULATIONS, key=len, reverse=True) if has_term(mode, m)), None)
    return {
        "operation_id": "satnogs:" + tx["uuid"], "satellite_id": sat_key,
        "name": description, "scopes": scopes, "admission_reason": reason,
        "review_required": "review" in reason or bool(tx.get("unconfirmed")),
        "capability_evidence": "SatNOGS transmitter record", "transmitter_type": tx.get("type"),
        "uplink_availability": "documented_uplink_access_unknown" if uplink else "unknown",
        "uplink_low_hz": uplink, "uplink_high_hz": positive_number(tx.get("uplink_high")),
        "downlink_low_hz": downlink, "downlink_high_hz": downlink_high,
        "downlink_band": frequency_band(downlink), "modulation": modulation,
        "source_mode": mode, "uplink_mode": tx.get("uplink_mode"), "protocols": protocols,
        "occupied_bandwidth_hz": positive_number(params.get("occupied_bandwidth")),
        "passband_width_hz": span if is_transponder else None,
        "frequency_span_hz": span, "symbol_rate_baud": positive_number(tx.get("baud")),
        "data_rate_bps": None, "inverting": tx.get("invert") if is_transponder else None,
        "schedule": None, "source_reported_status": tx.get("status"),
        "source_updated_at": tx.get("updated"), "fetched_at": fetched_at,
        "source_url": source_url, "citation": tx.get("citation"),
        "present_in_latest_source": True, "raw": tx,
    }


def frequency_band(hz):
    if hz is None:
        return None
    for lower, upper, name in [(3e6, 30e6, "HF"), (30e6, 300e6, "VHF"), (300e6, 3e9, "UHF"), (3e9, 30e9, "SHF"), (30e9, 300e9, "EHF")]:
        if lower <= hz < upper:
            return name
    return "outside HF-EHF"


def tle_epoch(line):
    """Use the element epoch, not the time someone downloaded the element set."""
    try:
        year = int(line[18:20])
        year += 1900 if year >= 57 else 2000
        return (datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=float(line[20:32]) - 1)).isoformat()
    except (TypeError, ValueError):
        return None
