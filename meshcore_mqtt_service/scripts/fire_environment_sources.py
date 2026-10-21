"""Observed smoke and fire-danger adapters; preserve provider times and metadata."""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from shapely.geometry import mapping, shape
from shapely import make_valid

from .wildfire_sources import NIFC

HMS_URL = "https://www.ospo.noaa.gov/data/spl/kmlfiles/fire/"
NFDRS_URL = NIFC + "NFDRS_ERC_and_BI_Percentiles_and_Trends/FeatureServer"
FEMS_URL = "https://fems.fs2c.usda.gov/api/ext-climatology/graphql"
NS = {"k": "http://www.opengis.net/kml/2.2"}
CLIMATOLOGY = "2005-2022, full calendar year, daily maxima; NFDRS2016 fuel model Y"


def download(client, url, payload=None, authorization=None):
    """Bound binary/XML and authenticated JSON requests without exposing credentials."""
    headers = {"User-Agent": "MC-EMS-Services-Wildfire/1.0"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if authorization:
        headers["Authorization"] = authorization
    remaining = client.deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Environment refresh budget exhausted")
    request = Request(url, data=payload, headers=headers)
    with urlopen(request, timeout=min(20, remaining)) as response:
        data = bytearray()
        while chunk := response.read(65536):
            data.extend(chunk)
            if len(data) > 32 * 1024 * 1024 or time.monotonic() > client.deadline:
                raise ValueError("Environment response size/time limit exceeded")
    return bytes(data)


def parse_hms(raw, day):
    """Parse dated NOAA KML polygons, including holes, and reject missing time metadata."""
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Unsupported XML declaration")
    root = ET.fromstring(raw)
    if root.tag != "{http://www.opengis.net/kml/2.2}kml":
        raise ValueError("Expected HMS KML")
    document = root.find("k:Document", NS)
    if document is None or document.findtext("k:name", "", NS) != "HMS Smoke Mapping-" + day:
        raise ValueError("HMS document date/name mismatch")
    features = []
    for index, mark in enumerate(root.findall(".//k:Placemark", NS)):
        description = mark.findtext("k:description", "", NS)
        density = re.search(r"Density:\s*(Light|Medium|Heavy)\b", description, re.I)
        times = [re.search(label + r" Time:\s*(\d{7} \d{4})UTC", description)
                 for label in ("Start", "End")]
        if not density or not all(times):
            raise ValueError("HMS plume missing density or observation interval")
        start, end = [datetime.strptime(m[1], "%Y%j %H%M").replace(tzinfo=timezone.utc).timestamp()
                      for m in times]
        if end < start:
            raise ValueError("HMS observation interval reversed")
        polygons = []
        for polygon in mark.findall(".//k:Polygon", NS):
            if len(polygon.findall("k:outerBoundaryIs/k:LinearRing/k:coordinates", NS)) != 1:
                raise ValueError("HMS polygon requires exactly one exterior ring")
            rings = []
            for boundary in ("outerBoundaryIs", "innerBoundaryIs"):
                for ring in polygon.findall(f"k:{boundary}/k:LinearRing/k:coordinates", NS):
                    coordinates = [list(map(float, c.split(",")[:2])) for c in (ring.text or "").split()]
                    if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
                        raise ValueError("HMS polygon ring is incomplete")
                    if any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in coordinates):
                        raise ValueError("HMS coordinates outside WGS84")
                    rings.append(coordinates)
            if not rings:
                raise ValueError("HMS polygon has no rings")
            polygons.append(rings)
        if not polygons:
            raise ValueError("HMS plume has no polygon")
        geometry = shape({"type": "MultiPolygon", "coordinates": polygons})
        repaired = not geometry.is_valid
        if repaired:
            geometry = make_valid(geometry)
        if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError("HMS geometry cannot be represented as polygons")
        features.append({
            "type": "Feature", "id": f"{day}:{index}", "geometry": mapping(geometry),
            "properties": {"density": density[1].lower(), "start": start, "end": end,
                           "product_day": day, "geometry_repaired": repaired,
                           "source_url": HMS_URL + f"hms_smoke{day}.kml",
                           "origin": None},
        })
    # Keep date provenance even for an empty valid document.
    features.append({"type": "Feature", "id": "coverage", "geometry": None,
                     "properties": {"product_day": day, "plume_count": len(features),
                                    "scope": "NOAA HMS full published document; detection is incomplete"}})
    return features


def hms(client, now=None):
    """Use today's analysis; fall back one UTC day only when today's file is absent."""
    now = now or datetime.now(timezone.utc)
    for offset in (0, 1):
        day = (now - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            return parse_hms(download(client, HMS_URL + f"hms_smoke{day}.kml"), day)
        except HTTPError as exc:
            if exc.code != 404 or offset:
                raise
    raise ValueError("HMS analysis unavailable")


def nfdrs(client):
    """Join public daily FEMS-derived ERC/BI summaries to national station geometry."""
    stations = client.arcgis(NFDRS_URL + "/0")
    rows = client.arcgis(NFDRS_URL + "/4")
    by_id = {}
    for row in rows:
        key = str(row["properties"]["Station_ID"])
        if key in by_id:
            raise ValueError("Duplicate NFDRS station summary")
        by_id[key] = row["properties"]
    result = []
    for station in stations:
        p = dict(station["properties"])
        row = by_id.get(str(p["Station_ID"]))
        if row is None:
            continue
        p.update(row)
        # The publisher specifies a daily 03:00 Mountain Time update. This is
        # publication time, not an instantaneous station observation time.
        issued = datetime.strptime(p["update_date"] + " " + p["update_time"], "%Y-%m-%d %H%M")
        p.update(published=issued.replace(tzinfo=ZoneInfo("America/Denver")).timestamp(),
                 fuel_model="Y", nfdrs_version="2016", climatology=CLIMATOLOGY,
                 observation_basis="Most recent daily maximum; published at 03:00 Mountain")
        result.append(dict(station, id=str(p["Station_ID"]), properties=p))
    if not result:
        raise ValueError("NFDRS station join returned no records")
    return result


FEMS_FIELDS = """station_id station_name latitude longitude elevation observation_time
fuel_model fuel_model_version nfdr_type energy_release_component burning_index
spread_component ignition_component one_hr_tl_fuel_moisture ten_hr_tl_fuel_moisture
hun_hr_tl_fuel_moisture thou_hr_tl_fuel_moisture herbaceous_lfi_fuel_moisture
woody_lfi_fuel_moisture kbdi quality_code"""


def fems(client, station_ids):
    """Fetch optional hourly modeled fuel moisture for explicitly configured stations."""
    username, key = os.environ.get("FEMS_USERNAME"), os.environ.get("FEMS_API_KEY")
    if not username or not key:
        raise ValueError("FEMS_USERNAME and FEMS_API_KEY are required for detailed fuel moisture")
    auth = "Basic " + base64.b64encode(f"{username}:{key}".encode()).decode()
    now = datetime.now(timezone.utc)
    query = """query($ids:String,$start:Date,$end:Date,$page:Int) {
      nfdrsObs(stationIds:$ids, fuelModels:"Y", startDateRange:$start,
        endDateRange:$end, dateTimeFormat:UTC, hasHistoricData:ALL,
        page:$page, per_page:500) {
          _metadata { page page_count total_count }
          data { """ + FEMS_FIELDS + """ }
      }}"""
    rows, expected = [], None
    for page in range(100):
        payload = json.dumps({"query": query, "variables": {
            "ids": ",".join(station_ids), "start": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
            "end": now.strftime("%Y-%m-%d"), "page": page}}).encode()
        response = json.loads(download(client, FEMS_URL, payload, auth))
        if response.get("errors"):
            # GraphQL responses can echo arguments; never propagate authenticated response text.
            raise ValueError("FEMS query failed; check API role and documented schema")
        batch = response["data"]["nfdrsObs"]
        meta = batch["_metadata"]
        expected = meta["total_count"] if expected is None else expected
        if meta["page"] != page or meta["total_count"] != expected or meta["page_count"] > 100:
            raise ValueError("Incomplete or changing FEMS pagination")
        rows.extend(batch["data"])
        if page + 1 >= meta["page_count"]:
            break
    if len(rows) != expected:
        raise ValueError("Incomplete FEMS observations")
    features = []
    for p in rows:
        if (str(p["station_id"]).lstrip("0") not in {s.lstrip("0") for s in station_ids}
                or p["fuel_model"] != "Y"):
            raise ValueError("Unexpected FEMS station or fuel model")
        # dateTimeFormat:UTC explicitly establishes the timezone for naive API timestamps.
        observed = datetime.fromisoformat(p["observation_time"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        p["observed"] = observed.timestamp()
        identity = json.dumps([p["station_id"], p["observation_time"], p["fuel_model"],
                               p["fuel_model_version"], p["nfdr_type"]])
        features.append({"type": "Feature", "id": hashlib.sha256(identity.encode()).hexdigest(),
                         "geometry": {"type": "Point", "coordinates": [float(p["longitude"]), float(p["latitude"])]},
                         "properties": p})
    return features
