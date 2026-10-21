"""Independent flood notifications with explicit CAP priority and uncertainty.

Priority is an application dispatch policy, not an official NWS ranking. Unknown
fields use the highest scheduling tier without changing the published values.
"""

from .flood_warn import ALERTS
from .water_lookup import floodwarn_expiry
from .response_text import compact_fields, short_label

PRIORITY_FIELDS = {
    "urgency": ("Immediate", "Expected", "Future", "Past"),
    "severity": ("Extreme", "Severe", "Moderate", "Minor"),
    "certainty": ("Observed", "Likely", "Possible", "Unlikely"),
}
ALERT_FIELDS = (
    "id",
    "event",
    "effective",
    "expires",
    "fingerprint",
    "references",
    "urgency",
    "severity",
    "certainty",
)


def normalized_priority(alert, field):
    """Normalize CAP's deprecated Very Likely value; retain unknown source values."""
    value = alert.get(field)
    return "Likely" if field == "certainty" and value == "Very Likely" else value


def priority(notice):
    """Order active notices by urgency, severity, certainty, newest effective time and ID."""
    if notice["kind"] != "alert":
        return (
            1,
            {"lifecycle": 0, "status": 1, "derived": 2}[notice["kind"]],
            notice["key"],
        )
    alert = notice["alert"]
    ranks = []
    for field, values in PRIORITY_FIELDS.items():
        value = normalized_priority(alert, field)
        ranks.append(values.index(value) if value in values else 0)
    return (
        0,
        *ranks,
        -alert["effective"],
        list(ALERTS).index(alert["event"]),
        alert["id"],
    )


def active_notice(alert, change):
    """Keep only current alert metadata needed for delivery, never bulletin or gauge history."""
    selected = {key: alert.get(key) for key in ALERT_FIELDS}
    selected["references"] = list(alert.get("references", []))
    return {
        "kind": "alert",
        "key": "alert:" + alert["id"],
        "change": change,
        "alert": selected,
    }


def status_notice(text, available, alert_ids=None):
    """Bind a source-status notice to expected availability and optional exact active IDs."""
    return {
        "kind": "status",
        "key": "official_status",
        "text": text,
        "available": available,
        "alert_ids": alert_ids,
    }


def official_notifications(before, snapshot, now):
    """Create independent active/lifecycle notices; outages cannot claim alerts cleared."""
    official = snapshot["official"]
    if official["status"] != "available":
        if before is None or before["official_status"] == "available":
            return [status_notice("NWS alerts unavailable; status unknown.", False)]
        return []
    current = official["data"]["alerts"]
    initial = before is None
    old = {} if initial else before["alerts"]
    recovered = not initial and before["official_status"] != "available"
    notices, replaced = [], set()
    unconfirmed_disappearance = False
    for key, alert in current.items():
        references = set(alert["references"]) & old.keys()
        replaced.update(references)
        previous = old.get(key)
        if previous is None and references:
            previous = old[sorted(references)[0]]
        if initial or recovered:
            notices.append(active_notice(alert, "ACTIVE"))
        elif previous is None or previous["fingerprint"] != alert["fingerprint"]:
            notices.append(
                active_notice(alert, "NEW" if previous is None else "UPDATED")
            )
    for key in sorted(old.keys() - current.keys() - replaced):
        alert = old[key]
        if key in official["data"]["cancelled_ids"]:
            reason = "cancelled by NWS. Not an all-clear."
        elif now >= alert["expires"]:
            reason = "expired. Not an all-clear."
        else:
            reason = "no longer listed; cancellation unconfirmed."
            unconfirmed_disappearance = True
        notices.append(
            {
                "kind": "lifecycle",
                "key": "alert:" + key,
                "alert_id": key,
                "text": f"NWS {alert['event']} {reason}",
            }
        )
    # An empty response is not evidence that an unexpired, uncancelled alert ended.
    # Keep recovery of source access distinct from the unresolved alert status.
    verified_empty = not current and not unconfirmed_disappearance
    if recovered:
        notices.append(
            status_notice(
                "NWS monitoring restored."
                + (" No active NWS flood alerts." if verified_empty else ""),
                True,
                [] if not current else None,
            )
        )
    elif verified_empty and (initial or old):
        notices.append(
            status_notice("No active NWS flood alerts. Monitoring continues.", True, [])
        )
    return sorted(notices, key=priority)


def format_notification(notice, target, now):
    """Send one concise notification; uncertainty takes precedence over names and times."""
    if notice["kind"] != "alert":
        essential = notice["text"].replace("no longer listed; cancellation unconfirmed.", "missing; cancellation unconfirmed.")
        if notice["kind"] == "derived":
            return compact_fields(essential, [short_label(target, 25)])
        return compact_fields(essential, [short_label(target, 25)])
    alert = notice["alert"]
    event = alert["event"].upper() if alert["event"].endswith("Warning") else alert["event"]
    uncertain = any(normalized_priority(alert, field) not in values for field, values in PRIORITY_FIELDS.items())
    essential = "NWS " + event + "."
    if event == "FLASH FLOOD WARNING":
        essential += " Move to higher ground now."
    if uncertain:
        essential += " Priority unknown" + ("" if event == "FLASH FLOOD WARNING" else ".")
    return compact_fields(essential, [notice["change"], "Until " + floodwarn_expiry(alert["expires"], now), short_label(target, 25)])
