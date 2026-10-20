"""Offline current-value freshness and quality; no hydraulic forecast is inferred."""

from datetime import datetime, timezone
import math


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def numeric(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) and result > -999 else None


def condition(row, metadata, now, max_age_hours=6):
    """Keep quality flags visible and distinguish missing, old and future values."""
    age = (now - timestamp(row["time"])).total_seconds() / 3600
    value = numeric(row["value"])
    units = row.get("unit_of_measure")
    expected = "ft" if row["parameter_code"] == "00065" else "ft^3/s"
    status = ("invalid_value" if value is None else "future_timestamp" if age < 0 else
              "stale" if age > max_age_hours else "unexpected_units" if units != expected else "available")
    primary = metadata.get("primary") == "Primary"
    instantaneous = metadata.get("computation_identifier") == "Instantaneous"
    return {"station_id": row["monitoring_location_id"], "time_series_id": row["time_series_id"],
            "parameter_code": row["parameter_code"], "time": row["time"], "value": row["value"],
            "unit_of_measure": units, "age_hours": round(age, 3), "status": status,
            "approval_status": row.get("approval_status"), "qualifier": row.get("qualifier"),
            "selection_status": "primary_instantaneous_candidate" if primary and instantaneous else "alternative_or_missing_metadata",
            "flood_extent_status": "not_inferred_from_stage_or_discharge"}


def write_conditions(stage, inventory, latest):
    """Summarize each returned latest series independently, including alternate sensors."""
    from data.flood_impacts import archive
    metadata = {str(f["id"]): f["properties"] for f in archive.read_json(inventory / "time_series.geojson.gz")["features"]}
    now = datetime.now(timezone.utc)
    rows = []
    for row in latest:
        output = condition(row, metadata.get(row["time_series_id"], {}), now)
        rows.append(output)
    if rows:
        archive.write_csv(stage / "series_conditions.csv", rows, tuple(rows[0]))
    archive.write_json(stage / "conditions_context.json", {
        "evaluated_at_utc": now.isoformat(), "max_age_hours": 6,
        "note": "Freshness is evaluated at build time; recalculate for later use. Qualifiers and provisional status remain source facts.",
    })


def applicable_thresholds(metadata, now):
    """Expose only effective source thresholds, keeping operational limits distinct."""
    rows = []
    for sid, series in metadata.items():
        for threshold in series.get("thresholds") or []:
            for period in threshold.get("Periods") or []:
                start, end = period.get("StartTime"), period.get("EndTime")
                try:
                    active = (not start or timestamp(start) <= now) and (not end or now <= timestamp(end))
                    status = "effective_at_evaluation_time" if active else "outside_effective_period"
                except (ValueError, TypeError, OverflowError):
                    active, status = True, "unparseable_effective_period_requires_review"
                if active:
                    rows.append({"station_id": series["monitoring_location_id"], "time_series_id": sid,
                                 "parameter_code": series["parameter_code"], "unit_of_measure": series.get("unit_of_measure"),
                                 "name": threshold.get("Name"), "reference_code": threshold.get("ReferenceCode"),
                                 "reference_value": period.get("ReferenceValue"), "start": start, "end": end,
                                 "status": status, "interpretation": "published_named_flood_reference"
                                 if "flood" in (threshold.get("Name") or "").lower() else "operational_or_other_reference"})
    return rows
