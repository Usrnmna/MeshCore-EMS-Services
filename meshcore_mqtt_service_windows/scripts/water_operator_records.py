"""Manually reviewed local-operator metadata; never an operational NOAA crosswalk.

Publication dates and historical coverage are provenance, not water readings.
Ordinary refresh copies this evidence without renewing its manual-review date.
"""

from copy import deepcopy

REVIEWED_AT = "2026-10-21T03:54:40+00:00"
WAC_REVIEWED_AT = "2026-10-21T04:13:27+00:00"
WAC_STATIONS = {"11464860", "11464880"}
# Static interpretation metadata, never a transform applied to observations.
WAC_VERTICAL_REFERENCE_REVIEW = {
    "status": "unresolved",
    "correction_authorized": False,
    "applied_correction": None,
    "station_elevations": {
        "preferred_source": "cdec",
        "preference_scope": "Station-elevation metadata only; source preference does not establish gauge zero or authorize reading corrections.",
        "cw3e": {"value": 190, "units": "m", "vertical_datum": None},
        "cdec": {"value": 470, "units": "ft", "vertical_datum": None},
        "cdec_in_metres": 143.256,
        "difference_metres": 46.744,
        "comparison_basis": "Arithmetic unit conversion only (1 ft = 0.3048 m); not a datum transformation or reading correction.",
    },
    "cdec_stage_metadata": {
        "station_id": "WAS",
        "sensor_number": 1,
        "units": "ft",
        "vertical_datum": None,
        "datum_evidence": "No WAS entry found in the reviewed RivStagesInfo report. Sensor 1 is generic river stage; datum-specific definitions 141/144 do not apply by inference.",
    },
    "logger_offset": {
        "reported_value_text": "1.420000",
        "reported_applied_on": "2026-07-15",
        "units": None,
        "sign_convention": None,
        "target_quantity": None,
        "vertical_datum": None,
        "already_in_published_readings": None,
        "interpretation": "The operator note says applied; it does not establish a service-side correction. Do not apply it again or assume its units from CDEC stage units.",
    },
    "limitations": [
        "The reviewed CW3E pressure-transducer page has blank height/distance fields and no calibration-history entries; this is not proof that calibration never occurred.",
        "No surveyed reference point, common vertical datum or published correction instruction was located in the reviewed records.",
        "Station elevation is not established as gauge zero, water-surface elevation, flood stage or a predecessor-gauge datum.",
    ],
    "required_evidence_for_correction": [
        "Surveyed reference point and vertical datum tying station elevation to gauge zero.",
        "Logger offset units, sign, affected quantity and effective configuration, including whether the publisher already applies it.",
        "Explicit operator correction instruction for the affected station and source product.",
    ],
}
SOURCES = {
    "rrfc": {
        "url": "https://www.rrfc.net/files/32a1f7e23/Telemetered%2BWater%2BMonitoring%2BProject%2BReport%2BPt%2B2%2BApril%2B2025.pdf",
        "locator": "Tables 2-2 through 2-4, printed pages 13-19 (PDF pages 26-32)",
        "scope": "Draft recommendations; the report explicitly describes these lists as non-exhaustive.",
    },
    "cw3e": {
        "url": "https://cw3e.ucsd.edu/metadata/sites/",
        "locator": "Russian watershed site inventory: DAC, WAC, MLL, RVY, RVP and CLD",
        "scope": "Public operator metadata; no legacy USGS crosswalk in the reviewed entries.",
    },
    "ukiah_fis": {
        "url": "https://cityofukiah.com/wp-content/uploads/2025/09/FIS-1.1.pdf",
        "locator": "Table 11, printed page 52 (PDF page 57), revised September 19, 2025",
        "sha256": "3d288f64d731ca85603f6a38b091049604bd461bdba7dc52f4356e4ecfbd9fe0",
        "scope": "City-hosted FEMA study; historical analysis inputs, not current operator telemetry.",
    },
    "ukiah_annual": {
        "url": "https://ukiahvalleygroundwater.org/wp-content/uploads/2026/02/1-052_WY2024.pdf",
        "locator": "WY2024 annual report; full extracted-text identity search",
        "sha256": "b3dc3ee4726a3d63388ddcba4dfb67da0f23aae47634e48f3db161321d42949c",
        "scope": "No explicit crosswalk for the reviewed upper-basin IDs located; not proof of absence elsewhere.",
    },
    "sonoma_ba": {
        "url": "https://www.sonomawater.org/media/PDF/Environment/BiologicalOpinion/RRBA_Final_20230823_rev1_ADA%20V2%20kt%20OCR%20and%20Scanned.pdf",
        "locator": "Tables 4-9 and 4-10, printed pages 4-70/4-71 (PDF pages 181/182); Table 4-10 visually checked",
        "sha256": "2f3945fde50a4dc4cfb3cb61899fb25f4892613b9d9869447000f5713f8c7ddf",
        "scope": "Mainstem Dry Creek gauges and tributaries; contains an identifier/name conflict.",
    },
    "talmage": {
        "url": "https://waterdata.usgs.gov/monitoring-location/USGS-11462080/",
        "locator": "Location name and agency identifier",
        "scope": "USGS identifies 11462080 as Russian River near Talmage, not Lambert Bridge.",
    },
    "mill_rcd": {
        "url": "https://sonomarcd.org/wp-content/uploads/2021/07/MillCreekFlowAvailabilityAnalysis.pdf",
        "locator": "Streamflow calibration discussion and Figure 35 (PDF pages 75-76)",
        "sha256": "4039fed01d25b81d02e9570910750ecb4d758d8805e2e7d69ff88001b7c1e168",
        "scope": "CEMAR/TU local gauge reoccupation and new sites; no legacy-USGS/NOAA pairing located.",
    },
    "maacama_rcd": {
        "url": "https://sonomarcd.org/wp-content/uploads/2017/06/Maacama-UpperMarkWest-IntegratedWshdMgmtPlan-FULL-3-25-15-1.pdf",
        "locator": "Stream Flow Monitoring, printed page 58 (PDF page 60)",
        "sha256": "dad4b83714a831c54d8a47676c7552318e9b5541a8a8d0052165aa0a80020ffb",
        "scope": "Historical Franz Creek identity and nearby research sites; no FVSC1 crosswalk.",
    },
    "county_emergency": {
        "url": "https://socoemergency.org/recover/2019-kincade-fire/rain-ready/",
        "locator": "Stay Informed: Big Sulphur forecast-point link BSCC1",
        "scope": "County operational guidance identifies a NOAA point, but not legacy station 11463160.",
    },
    "bscc1": {
        "url": "https://api.water.noaa.gov/nwps/v1/gauges/BSCC1",
        "locator": "Static identity: lid BSCC1, usgsId 11463200, Big Sulphur Creek near Cloverdale",
        "scope": "Different explicit USGS identity from Middletown 11463160.",
    },
    "cw3e_wac": {
        "url": "https://cw3e.ucsd.edu/metadata/sites/WAC",
        "locator": "Station identifiers, installation, location and equipment links",
        "sha256": "5f92f84b8586030fd78e5249de1f262afedcab344b26795d996f9413cc2b4811",
        "access": "retrieved_with_verified_windows_tls",
        "scope": "WAC explicitly identifies CDEC WAS; NWS ID is unpublished (--). No legacy USGS predecessor is identified.",
        "metadata": {
            "cw3e_id": "WAC",
            "cdec_id": "WAS",
            "published_nws_id": None,
            "latitude": 38.7025,
            "longitude": -123.0909,
            "installed_on": "2026-07-15",
            "reported_elevation_m": 190,
            "location_context": "Below Strawberry Creek and upstream of Lake Sonoma",
        },
    },
    "cw3e_wac_sensor": {
        "url": "https://cw3e.ucsd.edu/metadata/sites/WAC/sensors/899",
        "locator": "Pressure-transducer record linked from WAC",
        "sha256": "3838dc732dda2ff4d87297df4c6228f0da2a9d833e86d0f963f259b09643fe1b",
        "scope": "Ott Hydro PLS500 installed July 15, 2026; no predecessor or NOAA identifier. Height/distance fields and calibration-history entries are blank.",
    },
    "cw3e_wac_logger": {
        "url": "https://cw3e.ucsd.edu/metadata/sites/WAC/otherequipment/568",
        "locator": "Data-logger installation and notes linked from WAC",
        "sha256": "3e46a41280d315ab59e03cc7d26ea10337631fe1f514019f27660481b320aed1",
        "scope": "Sutron SatLink3 Lite installed July 15, 2026. An offset note lacks units and datum; it is not applied to any reading.",
    },
    "cw3e_russian_inventory": {
        "url": "https://cw3e.ucsd.edu/metadata/fields/1/options/1",
        "locator": "Russian watershed filtered inventory, WAC entry",
        "sha256": "92e3cfb0d10e51ef4598826920dd155eab330e548b50696813a0309c79246596",
        "scope": "Corroborates WAC installation and coordinates; no legacy-USGS crosswalk.",
    },
    "cdec_was": {
        "url": "https://cdec.water.ca.gov/dynamicapp/staMeta?station_id=WAS",
        "locator": "WAS station identity, operator and coordinates",
        "sha256": "83246c3a87d39f966d157239f3531bf548260ffbe37a37d79e25f08034c29cd3",
        "scope": "Names CW3E as operator at the same coordinates; no legacy-USGS crosswalk. Reported elevation differs from CW3E.",
        "metadata": {"cdec_id": "WAS", "reported_elevation_ft": 470},
    },
    "noaa_wssc1": {
        "url": "https://api.water.noaa.gov/nwps/v1/gauges/WSSC1",
        "locator": "Static identity fields only",
        "scope": "WSSC1 has the same name and coordinates but an empty USGS ID. Proximity cannot authorize a legacy-USGS link.",
        "metadata": {"lid": "WSSC1", "usgs_id": ""},
    },
    "cw3e_satellite_inventory": {
        "url": "https://cw3e.ucsd.edu/metadata/fields/2/options/15",
        "locator": "Live Satellite telemetry inventory, WAC row",
        "sha256": "2677bb69d6f01e0e6ef792324ca40196c7d396d5f3b3955f5c4d126f911e7cd9",
        "scope": "Live row corroborates 190 m and 38.702500/-123.090900. A differing search excerpt was not corroborated and cannot authorize a correction.",
    },
    "cdec_realtime_station_inventory": {
        "url": "https://cdec.water.ca.gov/reportapp/javareports?name=RealStations",
        "locator": "WAS row; station metadata only",
        "sha256": "8087b7bd7617a360c5b305b191b4e162a2498fa5d71d6a2cefcf9d535e5e66c5",
        "scope": "Separately reports WAS station elevation 470 ft; no vertical datum specified in the row.",
    },
    "cdec_sensor_definitions": {
        "url": "https://cdec.water.ca.gov/misc/senslist.html",
        "locator": "Sensor definitions 1, 141 and 144",
        "sha256": "c3a8d4effa9fbafd12165b4e77a65bdb43621abe9467851e0a3dbf56da23cc10",
        "scope": "Sensor 1 is river stage in feet. Separate definitions identify NAVD88 (141) and NGVD29 (144); neither may be assigned to WAS sensor 1 without station-specific evidence.",
    },
    "cdec_river_stage_information": {
        "url": "https://cdec.water.ca.gov/reportapp/javareports?name=RivStagesInfo",
        "locator": "Detailed river-stage station table, including DATUM 0 and DATUM columns",
        "sha256": "79204abda05a103a2f93b03ed08c80830a48e22084aee85d057c20a13329ca5e",
        "scope": "No exact WAS row found in the reviewed table. This is a coverage gap, not proof that no surveyed datum exists.",
    },
}

# Each entry describes the evidence gap, not a new route or replacement gauge.
# Source conflicts remain separate from live identity matching and refresh errors.
REVIEWS = {
    "11460940": (
        "coverage_period_difference",
        ("ukiah_fis", "ukiah_annual", "cw3e", "rrfc"),
        "FIS lists 1964-1976 for this ID; the earlier USGS discontinued-record table lists 1963-1968. These may describe different record types; equivalence is unverified. CW3E RVY/RVP are meteorological sites, not an explicit river-gauge successor.",
    ),
    "11461400": (
        "no_supported_crosswalk",
        ("rrfc", "cw3e", "ukiah_annual"),
        "No explicit pairing for the East Fork tributary was located. Cold Creek CLD and East Fork mainstem sites cannot substitute for an unnamed tributary by proximity.",
    ),
    "11462125": (
        "no_supported_crosswalk",
        ("rrfc", "ukiah_annual", "cw3e"),
        "No Slide Creek station pairing located in the reviewed local inventories and annual report. Coverage is incomplete; station closure is not established.",
    ),
    "11462700": (
        "operator_lead_unresolved",
        ("rrfc", "ukiah_fis"),
        "Table 2-3 identifies former 11462700 for proposed reactivation with NMFS, and separately lists CLSI Feliz 2/3/4. These recommendations supply no NOAA identifier or documented replacement chain.",
    ),
    "11462900": (
        "no_supported_crosswalk",
        ("rrfc", "cw3e", "ukiah_annual"),
        "No Cummisky Creek station pairing located. The regional inventories are not exhaustive, so missing entries cannot establish a discontinued current operation.",
    ),
    "11463160": (
        "different_station",
        ("county_emergency", "bscc1", "rrfc"),
        "County guidance points to BSCC1. NOAA explicitly identifies that point as 11463200 near Cloverdale, not 11463160 near Middletown; no substitution authorized.",
    ),
    "11463700": (
        "no_supported_crosswalk",
        ("rrfc", "cw3e"),
        "No Sausal Creek legacy-ID pairing located in the reviewed regional operator inventories; no NOAA successor established.",
    ),
    "11463940": (
        "coverage_period_difference",
        ("maacama_rcd", "rrfc"),
        "The RCD explicitly cites 11463940 near Kellogg but gives 1956-1976, unlike the USGS discontinued-record period 1964-1968. Record types may differ; equivalence is unverified. Nearby research sites have no NOAA replacement crosswalk; FVSC1 remains unverified.",
    ),
    "11464050": (
        "different_station",
        ("rrfc", "cw3e"),
        "The report's Dry Creek reactivation entry is 11464400 on the mainstem. Neither that entry nor DAC identifies the small Dry Creek tributary 11464050.",
    ),
    "11464400": (
        "operator_lead_unresolved",
        ("rrfc", "cw3e"),
        "Table 2-3 explicitly associates 11464400 with CW3E and pending flow/reactivation. CW3E lists DAC at Cooley Ranch Road. The report does not pair the legacy ID with DAC or DCOC1; common operator and proximity remain insufficient.",
    ),
    "11464500": (
        "operator_lead_unresolved",
        ("cw3e", "sonoma_ba", "talmage"),
        "DAC and the downstream Dry Creek gauges do not establish a successor for Dry Creek near Cloverdale. Table 4-10 labels 11462080 as Lambert Bridge, conflicting with USGS Talmage metadata; that table cannot supply an automatic crosswalk.",
    ),
    "11464860": (
        "operator_lead_unresolved",
        (
            "cw3e_wac",
            "cw3e_wac_sensor",
            "cw3e_wac_logger",
            "cw3e_russian_inventory",
            "cdec_was",
            "noaa_wssc1",
            "cw3e_satellite_inventory",
            "cdec_realtime_station_inventory",
            "cdec_sensor_definitions",
            "cdec_river_stage_information",
        ),
        "Recovered WAC detail and equipment records explicitly identify CDEC WAS but no Asti 11464860 predecessor. WSSC1 still has no USGS ID. CW3E and CDEC elevations differ; the logger offset lacks units/datum. No link, threshold or reading conversion is authorized.",
    ),
    "11464880": (
        "operator_lead_unresolved",
        (
            "cw3e_wac",
            "cw3e_wac_sensor",
            "cw3e_wac_logger",
            "cw3e_russian_inventory",
            "cdec_was",
            "noaa_wssc1",
            "cw3e_satellite_inventory",
            "cdec_realtime_station_inventory",
            "cdec_sensor_definitions",
            "cdec_river_stage_information",
        ),
        "Recovered WAC detail and equipment records explicitly identify CDEC WAS but no Skaggs Springs 11464880 predecessor. WSSC1 still has no USGS ID. Reservoir and creek gauges remain distinct. Conflicting reported elevations and an unqualified logger offset are not used to adjust readings.",
    ),
    "11465050": (
        "no_supported_crosswalk",
        ("sonoma_ba", "talmage", "rrfc"),
        "Table 4-9 identifies Dutcher as a Dry Creek tributary; Table 4-10 concerns mainstem gauges and contains the Lambert Bridge/Talmage conflict. Neither supplies a Dutcher Creek NOAA identity.",
    ),
    "11465150": (
        "operator_lead_unresolved",
        ("rrfc", "sonoma_ba"),
        "Table 2-3 lists TU Pena sites Pn01/Pn03 and Table 2-4 proposes Pena 5/Woods. No explicit 11465150 or NOAA pairing is provided; proposed installation is not active telemetry.",
    ),
    "11465300": (
        "operator_lead_unresolved",
        ("mill_rcd", "rrfc", "cw3e"),
        "RCD documents CEMAR sites reoccupied by TU plus new gauges; RRFC lists separate Mi-series sites. No explicit 11465300/NOAA crosswalk exists in those records. CW3E MLL is on the Redwood Valley Mill Creek, not Mill Creek near Healdsburg.",
    ),
}


def evidence(station_id):
    """Return independent static evidence; unknown IDs receive no review assertion."""
    number = station_id.removeprefix("USGS-")
    item = REVIEWS.get(number)
    if item is None:
        return None
    finding, source_ids, reason = item
    result = {
        "status": "unresolved_at_manual_review",
        "finding": finding,
        "link_authorized": False,
        "reviewed_at": WAC_REVIEWED_AT if number in WAC_STATIONS else REVIEWED_AT,
        "refresh_policy": "fixed_manual_evidence_not_retrieved_by_refresh",
        "sources": [
            dict(source_id=key, **deepcopy(SOURCES[key])) for key in source_ids
        ],
        "reason": reason,
        "limitation": "Only the cited records were reviewed. No proof that a NOAA match cannot exist. Live exact-identity checks remain authoritative.",
    }
    if number in WAC_STATIONS:
        result["vertical_reference_review"] = deepcopy(WAC_VERTICAL_REFERENCE_REVIEW)
    return result
