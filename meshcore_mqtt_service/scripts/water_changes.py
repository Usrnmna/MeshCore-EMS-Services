"""Categorical subscription comparison without storing historical measurement values."""

from collections import Counter

from .water_lookup import compact
from .response_text import short_label, counted
from .water_notifications import official_notifications, format_notification


GAUGE_STATE_LABELS = {
    "major": "major flooding",
    "moderate": "moderate flooding",
    "minor": "minor flooding",
    "action": "action stage",
    "no_flooding": "below flood stage",
    "threshold_unavailable": "threshold unknown",
    "unavailable": "data unavailable",
    "stale": "data stale",
    "invalid": "data invalid",
    "future": "future-dated reading",
    "out_of_service": "out of service",
    "coverage_lost": "coverage lost",
}


def changes(before, snapshot, now, structured=False):
    """Retain last-known alert fingerprints through outages; compare material CAP updates."""
    after = compact(snapshot)
    notices = official_notifications(before, snapshot, now)
    before = before or {"official_status": "available", "alerts": {}, "conditions": {}}
    if after["official_status"] != "available":
        after["alerts"] = before["alerts"]
    messages = []
    gauge_changes = []
    for key in sorted(before["conditions"].keys() | after["conditions"].keys()):
        previous = before["conditions"].get(key)
        condition = after["conditions"].get(key)
        if previous == condition:
            continue
        if key.startswith("gauge:"):
            gauge_changes.append((key, condition, previous))
        elif condition is None:
            messages.append(
                "DERIVED COVERAGE LOST; not an all-clear. | " + short_label(previous["label"], 25)
            )
        else:
            messages.append(
                "DERIVED " + short_label(condition["state"], 24)
                + "; not point flooding. | " + short_label(condition["label"], 25)
            )
    if gauge_changes:
        # Compare every gauge before limiting presentation. Stable severity ordering
        # prevents a distant major category being hidden by many missing thresholds.
        priority = {
            "major": 0,
            "moderate": 1,
            "minor": 2,
            "action": 3,
            "coverage_lost": 4,
            "no_flooding": 6,
        }
        state = lambda item: item[1]["state"] if item[1] else "coverage_lost"
        gauge_changes.sort(key=lambda item: (priority.get(state(item), 5), item[0]))
        counts = Counter(state(item) for item in gauge_changes)
        worst = state(gauge_changes[0])
        totals = "; ".join(
            f"{counted(count, 'gauge')}: {GAUGE_STATE_LABELS.get(key, 'status unknown')}"
            for key, count in sorted(counts.items()) if key != worst
        )
        details = []
        for index, (key, condition, previous) in enumerate(gauge_changes[:3]):
            value = condition or previous
            category = GAUGE_STATE_LABELS.get(state((key, condition, previous)), "status unknown")
            # The primary field already gives the first gauge's category. Keep
            # each complete name, explicit ID and source qualifiers together.
            details.append(
                value["label"] + " [ID " + key.removeprefix("gauge:") + "]"
                + (": " + category if index else "")
                + (
                    "; agency successor"
                    if value.get("noaa_identity_status") == "matched_agency_successor"
                    else ""
                )
                + (
                    "; USGS " + condition.get("reading_status", "unavailable")
                    if condition
                    else ""
                )
            )
        qualifier = "not an all-clear" if worst == "coverage_lost" else "not point flooding"
        messages.append(
            f"{counted(counts[worst], 'gauge')}: {GAUGE_STATE_LABELS.get(worst, 'status unknown')}; {qualifier}. | "
            + " | ".join(details + ([totals] if totals else []))
        )

    notices.extend(
        {
            "kind": "derived",
            "key": "derived:" + str(i),
            "text": message,
            "conditions": after["conditions"],
        }
        for i, message in enumerate(messages)
    )
    if structured:
        return after, notices
    return after, [
        format_notification(notice, snapshot["target"], now) for notice in notices
    ]
