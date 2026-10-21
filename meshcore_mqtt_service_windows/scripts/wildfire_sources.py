"""Bounded public-source clients. Only complete, validated batches are returned."""

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

NIFC = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
NWS = "https://api.weather.gov"
ZONE_URL = "https://mapservices.weather.noaa.gov/static/rest/services/nws_reference_maps/nws_reference_map/MapServer/9"
STATE_URL = NIFC + "US_State_and_County/FeatureServer/1"
SOURCES = {
    "egp": (NIFC + "EGP_Active_Incidents_Prod_Public_View/FeatureServer/0", "1=1"),
    "incidents": (NIFC + "WFIGS_Incident_Locations_Current/FeatureServer/0", "IncidentTypeCategory IN ('WF','CX')"),
    "perimeters": (NIFC + "WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0", "attr_IncidentTypeCategory='WF'"),
    "raws": (NIFC + "PublicView_RAWS/FeatureServer/1", "1=1"),
    "aqi": ("https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Air%20Now%20Current%20Monitor%20Data%20Public/FeatureServer/0", "1=1"),
    "smoke": ("https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/NDGD_SmokeForecast_v1/FeatureServer/0", "1=1"),
    "aqi_today": ("https://services.arcgis.com/cJ9YHowT8TU7DUyn/ArcGIS/rest/services/AirNow_National_Air_Quality_Index_(AQI)_Forecast/FeatureServer/0", "1=1"),
    "aqi_tomorrow": ("https://services.arcgis.com/cJ9YHowT8TU7DUyn/ArcGIS/rest/services/AirNow_National_Air_Quality_Index_(AQI)_Forecast/FeatureServer/1", "1=1"),
    "viirs": (NIFC + "VIIRS_Heat_Detections/FeatureServer/0", "Raw_Confidence IN ('Nominal','High') AND AgeInHours <= 24"),
    "modis": (NIFC + "Modis_Heat_Detections/FeatureServer/0", "Confidence >= 70 AND AgeInHours <= 24"),
    "cameras": ("https://services8.arcgis.com/X84q166Srnyl4JMV/ArcGIS/rest/services/ALERTCalifornia_Camera_Feed/FeatureServer/0", "isActive='active'"),
    "treatments": (NIFC + "Integrated_Interagency_Fuels_Treatments_View/FeatureServer/0", "1=1"),
    "history": (NIFC + "InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer/0", "1=1"),
    "spc": ("https://mapservices.weather.noaa.gov/vector/rest/services/fire_weather/SPC_firewx/MapServer", "1=1"),
    "potential": ("https://fsapps.nwcg.gov/psp/arcgis/rest/services/npsg/outlooks_forecast/MapServer", "1=1"),
}


def timestamp(value):
    """Convert ArcGIS epoch milliseconds or explicit-offset ISO timestamps to UTC seconds."""
    if value is None or value == "":
        return None
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite timestamp")
        return value / 1000
    # EGP publishes audit strings such as "operator, 2026-10-20 02:3206.517 UTC".
    audit = re.search(r"(?:^|, )(\d{4}-\d{2}-\d{2} \d{2}):(\d{2})(\d{2}(?:\.\d+)?) UTC$", value)
    if audit:
        value = f"{audit[1]}:{audit[2]}:{audit[3]}+00:00"
    elif value.endswith(" UTC"):
        value = value[:-4] + "+00:00"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Source timestamp lacks timezone")
    return parsed.astimezone(timezone.utc).timestamp()


class Client:
    """Bound response sizes and total execution time, with one short transient retry."""

    def __init__(self, seconds=240, stage_dir=None):
        self.deadline = time.monotonic() + seconds
        self.stage_dir = Path(stage_dir) if stage_dir else None
        self.stage_cleaned = False

    def staged_get(self, url, params, prefix, suffix):
        """Resume large reference downloads across bounded passes; never publish partial data."""
        if time.monotonic() >= self.deadline:
            raise TimeoutError("Reference download paused at the refresh time limit; retry resumes saved batches")
        if self.stage_dir is None:
            return self.get(url, params, post=True)
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        if not self.stage_cleaned:
            for expired in self.stage_dir.iterdir():
                if (expired.is_file() and re.fullmatch(r"[0-9a-f]{64}-(?:inventory|[0-9a-f]{64})\.(?:json|tmp)", expired.name)
                        and time.time() - expired.stat().st_mtime >= 21600):
                    expired.unlink()
            self.stage_cleaned = True
        path = self.stage_dir / (prefix + "-" + suffix + ".json")
        if path.is_file() and time.time() - path.stat().st_mtime < 21600:
            return json.loads(path.read_bytes())
        result = self.get(url, params, post=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        temporary.replace(path)
        return result

    def get(self, url, params=None, post=False):
        if not url.startswith("https://"):
            raise ValueError("Only HTTPS source URLs are supported")
        payload = urlencode(params or {}).encode()
        target = url if post or not params else url + "?" + payload.decode()
        for attempt in range(2):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Wildfire refresh time budget exhausted")
            request = Request(target, data=payload if post else None, headers={
                "User-Agent": "MC-EMS-Services-Wildfire/1.0",
                "Accept": "application/geo+json,application/json",
            })
            try:
                with urlopen(request, timeout=min(20, remaining)) as response:
                    data = bytearray()
                    while chunk := response.read(65536):
                        data.extend(chunk)
                        if len(data) > 64 * 1024 * 1024 or time.monotonic() > self.deadline:
                            raise ValueError("Wildfire response size/time limit exceeded")
                result = json.loads(data)
                if not isinstance(result, dict) or result.get("error"):
                    raise ValueError(f"Source returned an error: {str(result)[:250]}")
                return result
            except HTTPError as exc:
                if attempt or exc.code not in (429, 502, 503, 504):
                    raise
                time.sleep(min(2, max(0, self.deadline - time.monotonic())))
        raise RuntimeError("Source request failed")

    def arcgis(self, url, where="1=1", bounds=None, resume=False):
        """Fetch a stable ID inventory, then complete batches; reject missing/extra IDs."""
        metadata = self.get(url, {"f": "json"})
        fields = metadata.get("fields", [])
        oid = metadata.get("objectIdField") or next(
            (f["name"] for f in fields if f["type"] == "esriFieldTypeOID"), None)
        if not oid:
            raise ValueError("Source has no object identifier field")
        params = {"f": "json", "where": where, "returnIdsOnly": "true"}
        if bounds:
            params.update(geometry=",".join(map(str, bounds)), geometryType="esriGeometryEnvelope",
                          inSR=4326, spatialRel="esriSpatialRelIntersects")
        prefix = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        fetch = (lambda values, suffix: self.staged_get(url + "/query", values, prefix, suffix)) if resume else (
            lambda values, suffix: self.get(url + "/query", values, post=True))
        inventory = fetch(params, "inventory")
        ids = inventory.get("objectIds")
        if ids is None and "objectIds" in inventory:
            # Some NOAA map layers use null for an empty inventory; verify independently.
            count_params = dict(params, returnCountOnly="true")
            count_params.pop("returnIdsOnly")
            if self.get(url + "/query", count_params, post=True).get("count") == 0:
                ids = []
        if not isinstance(ids, list) or len(ids) > 100000 or len(ids) != len(set(ids)):
            raise ValueError("Invalid or excessive ArcGIS ID inventory")
        if inventory.get("exceededTransferLimit"):
            raise ValueError("Truncated ArcGIS ID inventory")
        features = []
        batch_size = min(50 if resume else 200, metadata.get("maxRecordCount", 200))
        if batch_size < 1:
            raise ValueError("Invalid ArcGIS batch limit")
        for offset in range(0, len(ids), batch_size):
            batch = ids[offset:offset + batch_size]
            result = fetch({
                "f": "geojson", "objectIds": ",".join(map(str, batch)),
                "outFields": "*", "returnGeometry": "true", "outSR": 4326,
            }, hashlib.sha256(json.dumps(batch).encode()).hexdigest())
            chunk = result.get("features")
            if not isinstance(chunk, list) or result.get("exceededTransferLimit") or result.get("properties", {}).get("exceededTransferLimit"):
                raise ValueError("Incomplete ArcGIS feature batch")
            actual = []
            for feature in chunk:
                key = feature.get("properties", {}).get(oid, feature.get("id"))
                actual.append(key)
                feature["id"] = str(key)
            if len(actual) != len(set(actual)) or set(actual) != set(batch):
                raise ValueError("ArcGIS snapshot changed or batch is incomplete")
            features.extend(chunk)
        if resume and self.stage_dir:
            # Flat generated files only; no recursive directory removal.
            for path in self.stage_dir.glob(prefix + "-*.json"):
                path.unlink()
        return features

    def source(self, name, bounds):
        """Collect outlook leaf layers atomically, preserving day/type and layer URL."""
        url, where = SOURCES[name]
        if name not in {"spc", "potential"}:
            return self.arcgis(url, where, bounds, resume=name in {"history", "treatments"})
        layers = self.get(url, {"f": "json"}).get("layers")
        if not isinstance(layers, list) or not layers:
            raise ValueError("Outlook layer inventory unavailable")
        features = []
        for layer in layers:
            if layer.get("subLayerIds") is not None:
                continue
            layer_url = url + "/" + str(layer["id"])
            for feature in self.arcgis(layer_url, where, bounds):
                feature["id"] = str(layer["id"]) + ":" + feature["id"]
                feature["properties"].update(source_layer=layer["name"], source_url=layer_url)
                features.append(feature)
        return features

    def alerts(self):
        """Fetch all pages for the four-state region; cancelled/expired filtering is downstream."""
        url = NWS + "/alerts/active?area=CA,NV,OR,AZ"
        features, seen = [], set()
        for _ in range(100):
            if url in seen or not url.startswith(NWS + "/alerts"):
                raise ValueError("Invalid alert pagination URL")
            seen.add(url)
            result = self.get(url)
            if not isinstance(result.get("features"), list):
                raise ValueError("Invalid alert collection")
            features.extend(result["features"])
            url = result.get("pagination", {}).get("next")
            if not url:
                return features
        raise ValueError("Alert pagination limit exceeded")
