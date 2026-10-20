"""Evidence-based routing, spatial intersections, and conservative stage comparisons."""

from collections import defaultdict
from datetime import datetime, timezone
import math

from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

NETWORK = "NHDPlusV2_USGS_wmadata"


def number(value):
    """Return a finite measurement; preserve zero and reject missing/sentinel values."""
    try:
        result = float(value)
        return result if math.isfinite(result) and result > -999 else None
    except (TypeError, ValueError):
        return None


def identifier(value):
    """Normalize published numeric network identifiers without spatial/name matching."""
    if value is None or str(value).strip() in ("", "0"):
        return ""
    return str(int(value))


def flow_connections(features):
    """Join published TONODE to FROMNODE, retaining branches and boundary uncertainty.

    This graph describes only the acquired NHDPlusV2 subset. Terminal flags are
    source attributes, not proof of an ocean outlet or current control operation.
    """
    starts = defaultdict(list)
    for feature in features:
        p = feature["properties"]
        node = identifier(p.get("fromnode"))
        if node:
            starts[node].append(p)
    rows = []
    for feature in features:
        p = feature["properties"]
        targets = starts.get(identifier(p.get("tonode")), [])
        for target in targets or [None]:
            rows.append({"from_reach_id": identifier(p["comid"]),
                         "to_reach_id": identifier(target["comid"]) if target else "",
                         "node_id": identifier(p.get("tonode")), "network": NETWORK,
                         "status": "published_node_connection" if target else
                         "source_terminal" if p.get("terminalfl") == 1 else "outside_subset_or_missing",
                         "downstream_divergence": target.get("divergence", "") if target else "",
                         "tidal": p.get("tidal", ""),
                         "evidence": "USGS wmadata FROMNODE/TONODE; present-day controls unassessed"})
    return rows


def downstream(start, rows):
    """Return reachable IDs including the source, terminating safely even with cycles."""
    adjacency = defaultdict(set)
    for row in rows:
        if row["to_reach_id"]:
            adjacency[row["from_reach_id"]].add(row["to_reach_id"])
    seen, pending = set(), [str(start)]
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(adjacency[current] - seen)
    return seen


class GeometryContext:
    """Transform WGS84 exports to a metric CRS and record every derived repair."""

    def __init__(self, crs="EPSG:3310"):
        self.forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
        self.inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
        self.diagnostics = []

    def project(self, geometry, source):
        if geometry is None:
            self.diagnostics.append({"source": source, "status": "null_geometry"})
            return None
        result = transform(self.forward, shape(geometry))
        if result.is_empty:
            self.diagnostics.append({"source": source, "status": "empty_geometry"})
            return None
        if not result.is_valid:
            original_area = result.area
            result = make_valid(result)
            self.diagnostics.append({"source": source, "status": "derived_make_valid",
                                     "original_area_m2": original_area, "repaired_area_m2": result.area})
        if result.is_empty or not result.is_valid:
            raise ValueError(f"Unusable geometry: {source}")
        return result

    def feature(self, geometry, properties):
        return {"type": "Feature", "geometry": mapping(transform(self.inverse, geometry)),
                "properties": properties}


def polygon_parts(geometry):
    """Discard non-area repair remnants; never turn lines or buffers into inundation."""
    if geometry is None:
        return []
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        return [geometry]
    return [part for child in getattr(geometry, "geoms", []) for part in polygon_parts(child)]


def basin_impacts(scenarios, basins, geometry_context):
    """Intersect each independent scenario with all supplied basin levels.

    Scenario fragments are unioned before this function. Each basin's portion is
    measured independently; nested levels must never be summed together.
    """
    rows, features = [], []
    for scenario, footprint in scenarios:
        for basin, boundary in basins:
            if not footprint.intersects(boundary):
                continue
            overlap = unary_union(polygon_parts(footprint.intersection(boundary)))
            if overlap.is_empty or overlap.area <= 0:
                continue
            row = {"scenario_id": scenario["scenario_id"], **basin,
                   "affected_area_m2": round(overlap.area, 3),
                   "basin_area_m2": round(boundary.area, 3),
                   "basin_fraction": overlap.area / boundary.area,
                   "evidence_class": "derived_static_stage_scenario_overlap",
                   "depth_status": "not_available", "event_valid_time": "",
                   "geometry_status": "see_geometry_diagnostics"}
            rows.append(row)
            features.append(geometry_context.feature(overlap, row))
    return rows, features


def parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def datum_compatible(gauge, site):
    """Require a published matching datum and zero; no vertical transformation is inferred."""
    aliases = {"NAVD88": "NAVD88", "NAVD 1988": "NAVD88", "NGVD29": "NGVD29", "NGVD 1929": "NGVD29"}
    site_datum = aliases.get(site.get("nws_data_vertical_datum_name"))
    zero = number(site.get("nws_data_zero_datum"))
    datums = gauge.get("datums") or {}
    vertical = datums.get("vertical") or {}
    for datum in vertical.get("value") or []:
        value = number(datum.get("value"))
        if (site_datum and aliases.get(datum.get("abbrev")) == site_datum and
                zero is not None and value is not None and abs(zero - value) < 0.01):
            return True
    return False


def stage_comparison(gauge, series, site, scenarios, kind, now, max_age_hours):
    """Bracket same-gauge stages without interpolation or claiming an event footprint.

    Forecasts are checked by issue time and restricted to future valid samples.
    Observations with future timestamps are rejected rather than selected.
    """
    block = series.get(kind) or {}
    result = {"gauge_lid": gauge["lid"], "kind": kind, "evaluated_at_utc": now.isoformat(),
              "status": "missing_measurement", "valid_time": "", "issued_time": block.get("issuedTime", ""),
              "stage_ft": "", "lower_scenarios": "", "upper_scenarios": "",
              "interpretation": "reference scenarios only; no event inundation inferred"}
    samples = []
    for sample in block.get("data") or []:
        timestamp, value = parse_time(sample.get("validTime")), number(sample.get("primary"))
        if timestamp and value is not None and ((timestamp <= now) if kind == "observed" else (timestamp >= now)):
            samples.append((timestamp, value))
    if not samples:
        return result
    stamp, value = max(samples, key=(lambda x: x[0]) if kind == "observed" else (lambda x: x[1]))
    is_stage_feet = (str(block.get("primaryName") or "").lower() == "stage" and
                     str(block.get("primaryUnits") or "").lower() == "ft")
    result.update(valid_time=stamp.isoformat(), stage_ft=value if is_stage_feet else "")
    freshness = stamp if kind == "observed" else parse_time(block.get("issuedTime"))
    if freshness is None or freshness > now:
        result["status"] = "invalid_issue_time"
    elif (now - freshness).total_seconds() > max_age_hours * 3600:
        result["status"] = "stale_measurement_or_forecast"
    elif not is_stage_feet:
        result["status"] = "unsupported_measurement_or_units"
    elif (gauge.get("inService") or {}).get("enabled") is False:
        result["status"] = "station_out_of_service"
    elif (gauge.get("inService") or {}).get("enabled") is not True:
        result["status"] = "station_service_status_unknown"
    elif str(gauge.get("usgsId")) != str(site.get("usgs_gage")):
        result["status"] = "station_identifier_conflict"
    elif site.get("mapped") != "yes":
        result["status"] = "no_published_inundation_coverage"
    elif not datum_compatible(gauge, site):
        result["status"] = "datum_unknown_or_changed"
    else:
        candidates = [s for s in scenarios if s["gauge_lid"] == gauge["lid"] and s["stage_units"].lower() == "ft"]
        stages = sorted({float(s["stage"]) for s in candidates})
        if not stages:
            result["status"] = "no_published_inundation_coverage"
        elif value < stages[0] or value > stages[-1]:
            result["status"] = "outside_published_stage_range"
        else:
            lower = max(s for s in stages if s <= value)
            upper = min(s for s in stages if s >= value)
            result.update(status="reference_stage_bracket",
                          lower_scenarios=";".join(s["scenario_id"] for s in candidates if float(s["stage"]) == lower),
                          upper_scenarios=";".join(s["scenario_id"] for s in candidates if float(s["stage"]) == upper))
    return result
