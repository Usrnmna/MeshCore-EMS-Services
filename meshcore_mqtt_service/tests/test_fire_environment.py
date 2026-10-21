"""Regression tests for point smoke, source integrity, and local ERC interpretation."""

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import fire_environment as env
from scripts import fire_environment_sources as sources
from scripts.wildfire_lookup import parse_query
from scripts.wildfire_settings import validate
from scripts.wildfire_sources import Client
from scripts.wildfire_store import Store
from responder import match_command

NOW = datetime(2026, 10, 20, 18, tzinfo=timezone.utc).timestamp()


def feature(key, properties, coordinates=(-120, 40)):
    return {"type": "Feature", "id": key, "properties": properties,
            "geometry": {"type": "Point", "coordinates": list(coordinates)}}


def plume(key="p"):
    return dict(type="Feature", id=key, properties=dict(density="medium", start=NOW-7200, end=NOW-3600),
                geometry=dict(type="Polygon", coordinates=[
                    [[-121, 39], [-119, 39], [-119, 41], [-121, 41], [-121, 39]]]))


def station(key="1", erc=45, percentile=95, coordinates=(-120, 40)):
    return feature(key, dict(Station_ID=key, Station_Name="Test", Process=1, erc=erc,
                            erc_percentile=percentile, published=NOW-3600, bi=30,
                            erc_trend="Increase", fuel_model="Y"), coordinates)


class PointReports(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/"test.sqlite3", writable=True)
        self.config = validate({})

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def put(self, name, features):
        self.store.replace(name, features, "fixture", now=NOW)

    def smoke(self, lat=40, lon=-120):
        return dict(command="smoke", **env.smoke_report(self.store, lat, lon, self.config, NOW))

    def test_smoke_format_and_json_provenance(self):
        self.put("hms", [plume()])
        self.put("aqi", [feature("a", dict(SiteName="Example", ValidTime=(NOW-600)*1000,
                 PM25=42, PM25_Unit="UG/M3", PM25_AQI=118, PM10=51, PM10_AQI=40, PM10_Unit="UG/M3"))])
        data = self.smoke()
        text = env.format_report(data)
        self.assertTrue(text.startswith("Smoke:"))
        for forbidden in ("Monitor:", "PM10:", "ZIP", "South Lake", "Resolved point"):
            self.assertNotIn(forbidden, text)
        self.assertIn("Unhealthy for Sensitive Groups", text)
        self.assertIn("surface exposure may differ", text)
        self.assertLessEqual(len(("@Reader " + text).encode()), 150)
        self.assertEqual(data["air_quality"]["PM10"]["concentration"], 51)
        self.assertEqual(data["air_quality"]["PM25"]["station"], "Example")

    def test_boundary_is_inside_and_hole_is_outside(self):
        p = plume()
        p["geometry"]["coordinates"].append([[-120.1,39.9],[-119.9,39.9],[-119.9,40.1],[-120.1,40.1],[-120.1,39.9]])
        self.put("hms", [p])
        self.assertEqual(self.smoke(40, -121)["coverage"], "inside")
        result = self.smoke()
        self.assertEqual(result["coverage"], "outside")
        self.assertGreater(result["distance_miles"], 0)
        self.assertLess(result["distance_miles"], 7)

    def test_outside_distance_uses_edge_not_centroid(self):
        self.put("hms", [plume()])
        result = self.smoke(40, -121.1)
        self.assertAlmostEqual(result["distance_miles"], 5.3, delta=.2)
        self.assertEqual(result["direction"], "E")

    def test_far_point_not_claimed_clear(self):
        self.put("hms", [plume()])
        result = self.smoke(35, -120)
        self.assertNotIn("distance_miles", result)
        self.assertIn("detection incomplete", env.format_report(result))

    def test_stale_or_failed_hms_is_unknown(self):
        p = plume()
        p["properties"]["end"] = NOW - self.config["smoke_max_age"] - 1
        self.put("hms", [p])
        self.assertEqual(self.smoke()["coverage"], "unknown")
        self.put("hms", [plume()])
        self.store.fail("hms", "offline", now=NOW)
        self.assertEqual(self.smoke()["coverage"], "unknown")
        self.assertEqual(len(self.store.features("hms")), 1)

    def test_empty_smoke_is_not_clean_air(self):
        self.put("hms", [])
        self.assertEqual(self.smoke()["coverage"], "unknown")

    def test_freshness_and_sentinels_before_monitor_distance(self):
        self.put("aqi", [
            feature("old", dict(PM25=40, ValidTime=(NOW-86400)*1000)),
            feature("missing", dict(PM25=-999, PM25_AQI=-1, ValidTime=NOW*1000)),
            feature("valid", dict(PM25=0, PM25_AQI=0, ValidTime=NOW*1000), (-120.1,40)),
        ])
        result = self.smoke()["air_quality"]["PM25"]
        self.assertEqual(result["concentration"], 0)
        self.assertEqual(result["category"], "Good")
        self.assertGreater(result["distance_miles"], 0)

    def test_pollutants_select_independent_monitors(self):
        self.put("aqi", [feature("pm", dict(PM25=20, ValidTime=NOW*1000)),
                         feature("oz", dict(OZONE=25, ValidTime=NOW*1000), (-120.1,40))])
        data = self.smoke()["air_quality"]
        self.assertEqual(data["PM25"]["distance_miles"], 0)
        self.assertGreater(data["OZONE"]["distance_miles"], 0)

    def test_future_and_distant_air_data_rejected(self):
        self.put("aqi", [feature("future", dict(PM25=10, ValidTime=(NOW+3600)*1000)),
                         feature("far", dict(PM25=20, ValidTime=NOW*1000), (-100,40))])
        self.assertEqual(self.smoke()["air_quality"], {})

    def test_malformed_monitor_time_does_not_hide_valid_monitor(self):
        self.put("aqi", [feature("bad",dict(PM25=20,ValidTime="invalid")),
                         feature("good",dict(PM25=8,ValidTime=NOW*1000),(-120.1,40))])
        self.assertEqual(self.smoke()["air_quality"]["PM25"]["concentration"],8)

    def test_erc_uses_nearest_eligible_station(self):
        bad = station("bad")
        bad["properties"]["published"] = NOW-3*86400
        inactive = station("off")
        inactive["properties"]["Process"] = 0
        self.put("nfdrs", [bad, inactive, station("good", coordinates=(-120.1,40))])
        data = env.danger_report(self.store,40,-120,self.config,NOW)
        self.assertEqual(data["station"]["id"], "good")
        self.assertIn("Unusually high", data["assessment"])
        self.assertIn("Local danger rating unknown", env.format_report(dict(command="firedanger", **data)))

    def test_no_percentile_does_not_classify_raw_erc(self):
        self.put("nfdrs", [station(percentile=None, erc=100)])
        data = env.danger_report(self.store,40,-120,self.config,NOW)
        self.assertIn("unclassified", data["assessment"])
        self.assertNotIn("Exceptionally", data["assessment"])

    def test_percentile_interpretation_boundaries(self):
        self.assertIn("below", env.fuel_assessment(49.99))
        self.assertIn("median", env.fuel_assessment(50))
        self.assertIn("Unusually", env.fuel_assessment(90))
        self.assertIn("Exceptionally", env.fuel_assessment(97))

    def test_warning_is_independent_of_missing_erc(self):
        z = plume()
        z["id"] = "CAZ272"
        self.put("zones", [z])
        a = feature("warning", dict(event="Red Flag Warning", status="Actual", messageType="Alert",
                    effective="2026-10-20T17:00:00Z", expires="2026-10-21T18:00:00Z",
                    geocode={"UGC":["CAZ272"]}))
        a["geometry"] = None
        self.put("alerts", [a])
        data = env.danger_report(self.store,40,-120,self.config,NOW)
        self.assertIsNone(data["station"])
        self.assertEqual(data["warning_status"], "active")
        self.assertIn("Red Flag Warning", env.format_report(dict(command="firedanger", **data)))

    def test_all_location_forms_and_radio_validation(self):
        commands = json.loads((ROOT/"config.json").read_bytes())["responder"]["commands"]
        for command in ("smoke","firedanger"):
            for text in ("96150","Reno NV","South Lake Tahoe","40, -120","40 -120"):
                self.assertEqual(parse_query(command,text)["target"], text)
                self.assertIsNone(match_command(f"!{command} {text}", commands)[2])
            for text in ("CAZ272","--db file","91, -120","40 -120 page 2"):
                with self.assertRaises(ValueError):
                    parse_query(command,text)

    def test_location_outside_zone_seed_is_supported(self):
        with patch.object(env,"resolve_location",return_value=(40,-120)) as resolver:
            data = env.report("smoke","96150",self.store,self.config,NOW)
        resolver.assert_called_once()
        self.assertEqual(data["resolved_point"], [40,-120])


KML = b'''<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<name>HMS Smoke Mapping-20261020</name><Placemark>
<description>Start Time: 2026293 1200UTC End Time: 2026293 1500UTC Density: Medium</description>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
-121,39 -119,39 -119,41 -121,41 -121,39
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Document></kml>'''


class SourceTests(unittest.TestCase):
    def test_hms_parses_times_and_full_polygon(self):
        data = sources.parse_hms(KML, "20261020")
        self.assertEqual(data[0]["properties"]["density"], "medium")
        self.assertEqual(data[0]["properties"]["end"], NOW-10800)
        self.assertEqual(data[-1]["properties"]["plume_count"], 1)

    def test_hms_rejects_schema_time_and_date_errors(self):
        for body in (b"<html/>", KML.replace(b"End Time:",b"Missing:"),
                     KML.replace(b"20261020",b"20261019"),
                     b"<!DOCTYPE kml>"+KML):
            with self.assertRaises(ValueError):
                sources.parse_hms(body,"20261020")

    def test_hms_only_falls_back_on_404(self):
        missing = HTTPError("test",404,"missing",None,None)
        # Yesterday's file is preserved as yesterday's analysis.
        with patch.object(sources,"download",side_effect=[missing,KML.replace(b"20261020",b"20261019")]):
            data = sources.hms(Client(),datetime(2026,10,20,tzinfo=timezone.utc))
        self.assertEqual(data[-1]["properties"]["product_day"], "20261019")
        with patch.object(sources,"download",side_effect=HTTPError("test",503,"offline",None,None)) as call:
            with self.assertRaises(HTTPError):
                sources.hms(Client(),datetime(2026,10,20,tzinfo=timezone.utc))
        self.assertEqual(call.call_count,1)

    def test_public_nfdrs_joins_by_id(self):
        class Fake:
            def arcgis(self,url):
                if url.endswith("/0"):
                    return [feature("s",dict(Station_ID=1,Station_Name="Station"))]
                return [feature("r",dict(Station_ID=1,erc=40,update_date="2026-10-20",update_time="0300"))]
        result = sources.nfdrs(Fake())[0]
        self.assertEqual(result["properties"]["erc"],40)
        self.assertEqual(result["properties"]["fuel_model"],"Y")
        self.assertIn("2005-2022",result["properties"]["climatology"])
        self.assertEqual(result["geometry"]["coordinates"],[-120,40])

    def test_fems_missing_credentials(self):
        with patch.dict("os.environ",{},clear=True):
            with self.assertRaisesRegex(ValueError,"FEMS_USERNAME"):
                sources.fems(Client(),["1"])

    def test_fems_errors_are_redacted(self):
        with patch.dict("os.environ",{"FEMS_USERNAME":"example","FEMS_API_KEY":"secret"}):
            with patch.object(sources,"download",return_value=b'{"errors":[{"message":"secret"}]}'):
                with self.assertRaisesRegex(ValueError,"FEMS query failed") as exc:
                    sources.fems(Client(),["1"])
        self.assertNotIn("secret",str(exc.exception))

    def test_fems_complete_page_and_quality_preservation(self):
        row=dict(station_id="1",latitude=40,longitude=-120,fuel_model="Y",
                 fuel_model_version="2016",nfdr_type="O",observation_time="2026-10-20T17:00:00",
                 quality_code="test",ten_hr_tl_fuel_moisture=8)
        body=json.dumps({"data":{"nfdrsObs":{"_metadata":{"page":0,"page_count":1,"total_count":1},
                                            "data":[row]}}}).encode()
        with patch.dict("os.environ",{"FEMS_USERNAME":"example","FEMS_API_KEY":"secret"}):
            with patch.object(sources,"download",return_value=body):
                data=sources.fems(Client(),["1"])
        self.assertEqual(data[0]["properties"]["observed"],NOW-3600)
        self.assertEqual(data[0]["properties"]["quality_code"],"test")

    def test_fems_partial_page_cannot_publish(self):
        body=json.dumps({"data":{"nfdrsObs":{"_metadata":{"page":0,"page_count":1,"total_count":2},
                                            "data":[]}}}).encode()
        with patch.dict("os.environ",{"FEMS_USERNAME":"example","FEMS_API_KEY":"secret"}):
            with patch.object(sources,"download",return_value=body):
                with self.assertRaisesRegex(ValueError,"Incomplete FEMS"):
                    sources.fems(Client(),["1"])

    def test_settings_bound_optional_requests(self):
        for settings in ({"fems_station_ids":["1"]*21},{"fems_station_ids":["1","1"]},
                         {"fems_station_ids":[1]},{"monitor_radius_miles":201}):
            with self.assertRaises(ValueError):
                validate(settings)


if __name__ == "__main__":
    unittest.main()
