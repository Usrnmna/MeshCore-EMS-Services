"""Offline spatial, source freshness, provenance, ambiguity and current-only regressions."""

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import shapely
from pyproj import Transformer
from scripts import (
    water_local as local,
    water_lookup as lookup,
    water_sources as sources,
    water_settings,
)

NOW = 1792500000


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(
            water_settings, "runtime", return_value=Path(self.temp.name)
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.config = water_settings.validate({})

    def test_location_ambiguity_and_exact_match(self):
        records = [
            dict(
                name="Example",
                country_code="US",
                admin1="California",
                admin2="A",
                latitude=38,
                longitude=-121,
            ),
            dict(
                name="Example",
                country_code="US",
                admin1="California",
                admin2="B",
                latitude=39,
                longitude=-122,
            ),
        ]
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            lookup.resolve("Example", lambda *args: {"results": records})
        self.assertEqual(lookup.resolve("38 -121"), [38, -121])
        self.assertEqual(
            lookup.resolve("Example", lambda *args: {"results": [records[0]]}),
            [38, -121],
        )
        with self.assertRaisesRegex(ValueError, "not found"):
            lookup.resolve("Other", lambda *args: {"results": records})

    def test_controls_and_invalid_locations(self):
        self.assertEqual(
            lookup.parse_query("floodalarm", "conditions 95814")["mode"], "conditions"
        )
        for text in ("stop", "status"):
            self.assertEqual(lookup.parse_query("floodalarm", text)["action"], text)
        for text in ("conditions", "91 0", "x; exit", "0 -181"):
            with self.assertRaises(ValueError):
                lookup.parse_query("floodalarm", text)

    def test_missing_thresholds_are_explicit_and_nearby_never_alarm_qualified(self):
        stations = [
            {
                "id": "USGS-1",
                "name": "Upstream",
                "lid": "",
                "relationship": "upstream_basin_context",
                "readings": [],
            },
            {
                "id": "USGS-2",
                "name": "Nearby",
                "lid": "",
                "relationship": "nearby_only",
                "readings": [],
            },
        ]
        context = {
            "stations": stations,
            "stations_total": 20,
            "basins": [],
            "observations_status": "available",
            "upstream_stations": [
                {
                    "id": "USGS-1",
                    "name": "Upstream",
                    "lid": "",
                    "reading_status": "unavailable",
                    "routing_status": "paths_to_source_terminals",
                    "routing_caveats": "none_reported",
                }
            ],
        }
        with patch.object(local, "context", return_value=context), patch.object(
            sources, "alerts_at", return_value={"alerts": {}, "cancelled_ids": []}
        ), patch.object(
            sources, "model_at", return_value={"condition": "outside_published_domain"}
        ), patch.object(
            sources, "rainfall_at", side_effect=ValueError("no-data")
        ):
            result = lookup.snapshot("38 -121", config=self.config, now=NOW)
        self.assertEqual(
            result["conditions"]["gauge:USGS-1"]["state"], "threshold_unavailable"
        )
        self.assertNotIn("gauge:USGS-2", result["conditions"])
        text = lookup.format_status("floodstatus", result)
        self.assertIn("Outside model domain; inundation unknown", text)
        self.assertLessEqual(len(("@Reader " + text).encode()), 150)
        self.assertEqual(result["conditions"]["gauge:USGS-1"]["state"], "threshold_unavailable")

    def test_all_linked_gauges_evaluated_independent_of_display_limit(self):
        upstream = [
            dict(
                id=f"USGS-{i}",
                name=f"River gauge {i}",
                lid=f"TEST{i}",
                reading_status="stale" if i == 5 else "available",
                routing_status="paths_to_source_terminals",
                routing_caveats="none_reported",
            )
            for i in range(1, 7)
        ]
        stations = [
            dict(s, relationship="upstream_basin_context", readings=[])
            for s in upstream
        ]

        def gauge(lid, sid, *args):
            if sid == "USGS-4":
                raise ValueError("identity conflict")
            return {"condition": "major" if sid == "USGS-6" else "no_flooding"}

        outcomes = []
        for limit in (1, 3):
            context = dict(
                stations=stations[:limit],
                upstream_stations=upstream,
                stations_total=6,
                basins=[],
                observations_status="available",
            )
            with patch.object(
                local, "context", return_value=deepcopy(context)
            ), patch.object(
                sources, "alerts_at", return_value={"alerts": {}, "cancelled_ids": []}
            ), patch.object(
                sources,
                "model_at",
                return_value={"condition": "outside_published_domain"},
            ), patch.object(
                sources, "rainfall_at", side_effect=ValueError("missing")
            ), patch.object(
                sources, "gauge", side_effect=gauge
            ) as fetch:
                result = lookup.snapshot(
                    "38 -121", config=dict(self.config, max_results=limit), now=NOW
                )
            self.assertEqual(fetch.call_count, 6)
            self.assertEqual(
                {call.args[1] for call in fetch.call_args_list},
                {s["id"] for s in upstream},
            )
            self.assertEqual(result["conditions"]["gauge:USGS-6"]["state"], "major")
            self.assertEqual(
                result["conditions"]["gauge:USGS-4"]["state"], "unavailable"
            )
            self.assertEqual(
                result["conditions"]["gauge:USGS-5"]["reading_status"], "stale"
            )
            self.assertIn(
                "all 6 evaluated", lookup.condition_summary(result["conditions"])
            )
            self.assertNotIn("upstream_stations", result["local"]["data"])
            outcomes.append(result["conditions"])
        self.assertEqual(outcomes[0], outcomes[1])

    def test_gauge_drops_historical_values_and_rechecks_staleness(self):
        raw = {
            "lid": "DEMO1",
            "usgsId": "123",
            "status": {
                "observed": {
                    "primary": 5,
                    "primaryUnit": "ft",
                    "validTime": iso(NOW - 10),
                    "floodCategory": "action",
                }
            },
            "inService": {"enabled": True},
            "flood": {
                "categories": {"action": {"stage": 4}},
                "crests": {"historic": [{"stage": 99999}]},
            },
            "datums": {"zero": 1},
        }
        fetch = lambda *args: raw
        first = sources.gauge("DEMO1", "USGS-123", self.config, NOW, fetch)
        self.assertEqual(first["condition"], "action")
        with closing(
            sqlite3.connect(Path(self.temp.name) / "water_current.sqlite3")
        ) as db:
            body = db.execute("SELECT body FROM current").fetchone()[0]
            self.assertNotIn("99999", body)
            self.assertNotIn("historic", body)
        stale = sources.gauge("DEMO1", "USGS-123", self.config, NOW + 21601, fetch)
        self.assertEqual(stale["condition"], "stale")
        with self.assertRaisesRegex(ValueError, "identity"):
            sources.gauge("DEMO1", "USGS-999", self.config, NOW, fetch)

    def test_cache_replaces_instead_of_accumulates_and_failure_not_fresh(self):
        sources.cached("x", self.config, lambda: {"value": 1}, NOW)
        sources.cached("x", self.config, lambda: {"value": 2}, NOW + 301)
        with closing(
            sqlite3.connect(Path(self.temp.name) / "water_current.sqlite3")
        ) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM current").fetchone()[0], 1
            )
            self.assertEqual(
                json.loads(db.execute("SELECT body FROM current").fetchone()[0]),
                {"value": 2},
            )

        def fail():
            raise ValueError("offline")

        with self.assertRaisesRegex(ValueError, "offline"):
            sources.cached("x", self.config, fail, NOW + 602)
        with self.assertRaisesRegex(ValueError, "offline"):
            sources.cached("x", self.config, lambda: {}, NOW + 603)

    def test_nws_coverage_and_expiry(self):
        props = {
            "id": "a",
            "event": "Flood Warning",
            "status": "Actual",
            "messageType": "Alert",
            "effective": iso(NOW - 1),
            "expires": iso(NOW + 30),
            "references": [],
        }
        raw = {"type": "FeatureCollection", "features": [{"properties": props}]}

        def fetch(url, *args):
            return (
                {"type": "Feature", "properties": {"forecastZone": "zone"}}
                if "/points/" in url
                else raw
            )

        self.assertTrue(sources.alerts_at(38, -121, self.config, NOW, fetch)["alerts"])
        self.assertFalse(
            sources.alerts_at(38, -121, self.config, NOW + 31, fetch)["alerts"]
        )
        with self.assertRaisesRegex(ValueError, "coverage"):
            sources.alerts_at(39, -121, self.config, NOW, lambda *a: {})
        for invalid in (
            {},
            dict(raw, pagination={"next": "next"}),
            dict(raw, features=[raw["features"][0]] * 2),
        ):
            with self.assertRaises(ValueError):
                sources.select_alerts(invalid, NOW)

    def test_model_missing_stale_and_fresh_distinguished(self):
        def fetch(url, params):
            attrs = {} if "static_public" in url else {"update_time": iso(NOW - 10)}
            return {"features": [{"attributes": attrs}]}

        self.assertEqual(
            sources.model_at(38, -121, self.config, NOW, fetch)["condition"],
            "modeled_footprint_intersects_point",
        )
        self.assertEqual(
            sources.model_at(38, -121, self.config, NOW + 10801, fetch)["condition"],
            "stale_or_unverified_time",
        )

        def empty(url, params):
            return (
                {"features": [{"attributes": {}}]}
                if "static_public" in url
                else {"features": []}
            )

        self.assertIn(
            "not_all_clear",
            sources.model_at(39, -121, self.config, NOW, empty)["condition"],
        )
        self.assertEqual(
            sources.model_at(40, -121, self.config, NOW, lambda *a: {"features": []})[
                "condition"
            ],
            "outside_published_domain",
        )
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            sources.model_at(
                41,
                -121,
                self.config,
                NOW,
                lambda *a: {"features": [], "exceededTransferLimit": True},
            )

    def test_rainfall_nodata_and_unverified_time_are_not_alarm_conditions(self):
        def fetch(url, params):
            return {
                "results": [
                    {"layerId": 28, "attributes": {"Service Pixel Value": "1.2"}}
                ]
            }

        r = sources.rainfall_at(38, -121, self.config, NOW, fetch)
        self.assertIsNone(r["source_time"])
        self.assertIn("not a basin mean", r["interpretation"])

        def nodata(url, params):
            return {
                "results": [
                    {"layerId": 28, "attributes": {"Service Pixel Value": "-10000"}}
                ]
            }

        with self.assertRaises(ValueError):
            sources.rainfall_at(39, -121, self.config, NOW, nodata)


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.u = self.root / "usgs_water"
        self.u.mkdir()
        self.config = water_settings.validate({"data_directory": str(self.root)})
        self.index = self.root / "index.sqlite3"
        self.inventory = self.u / "inventory"
        self.inventory.mkdir()
        (self.inventory / "relationships").mkdir()
        stations = {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": "USGS-1",
                    "properties": {"monitoring_location_name": "Far upstream"},
                    "geometry": {"type": "Point", "coordinates": [-120, 39]},
                },
                {
                    "id": "USGS-2",
                    "properties": {"monitoring_location_name": "Nearby unrelated"},
                    "geometry": {"type": "Point", "coordinates": [-121, 38]},
                },
            ],
        }
        with gzip.open(
            self.inventory / "stations.geojson.gz", "wt", encoding="utf-8"
        ) as f:
            json.dump(stations, f)
        (self.inventory / "relationships/station_identifiers.csv").write_text(
            "station_id,nwps_lid\nUSGS-1,DEMO1\nUSGS-2,\n"
        )
        self.ip = self.publish(
            "inventory",
            self.inventory,
            ["stations.geojson.gz", "relationships/station_identifiers.csv"],
        )
        self.route = self.u / "routing"
        self.route.mkdir()
        with closing(sqlite3.connect(self.route / "routing.sqlite")) as db:
            db.executescript(
                """CREATE TABLE reaches(reach_id TEXT,name TEXT,geometry_wkb BLOB);
                CREATE TABLE basins(basin_id TEXT,level TEXT,code TEXT,name TEXT,region TEXT,plan TEXT,geometry_wkb BLOB);
                CREATE TABLE station_downstream_basins(station_id TEXT,basin_id TEXT,positive_length_reaches INT);
                CREATE TABLE station_routing_coverage(station_id TEXT,status TEXT);"""
            )
            project = Transformer.from_crs(4326, 3310, always_xy=True).transform
            poly = shapely.transform(
                shapely.box(-121.1, 37.9, -120.9, 38.1), project, interleaved=False
            )
            db.execute(
                "INSERT INTO basins VALUES(?,?,?,?,?,?,?)",
                (
                    "pw",
                    "06_planning_watersheds",
                    "1",
                    "Example PW",
                    "",
                    "",
                    shapely.to_wkb(poly),
                ),
            )
            db.execute(
                "INSERT INTO reaches VALUES(?,?,?)",
                (
                    "r",
                    "Example Creek",
                    shapely.to_wkb(shapely.LineString([(-121, 37.9), (-121, 38.1)])),
                ),
            )
            db.execute(
                "INSERT INTO station_downstream_basins VALUES(?,?,?)",
                ("USGS-1", "pw", 1),
            )
            db.execute(
                "INSERT INTO station_routing_coverage VALUES(?,?)",
                ("USGS-1", "paths_with_unresolved_endpoints"),
            )
            db.commit()
        self.publish(
            "routing",
            self.route,
            ["routing.sqlite"],
            inventory_pointer=self.ip,
            network_pointer=None,
            link_review_pointer=None,
        )
        obs = self.u / "observations"
        obs.mkdir()
        (obs / "latest_measurements.csv").write_text("station_id\nUSGS-1\n")
        fields = [
            "station_id",
            "time",
            "value",
            "parameter_code",
            "unit_of_measure",
            "approval_status",
        ]
        with (obs / "series_conditions.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                dict(
                    station_id="USGS-1",
                    time=iso(NOW - 21700),
                    value="2",
                    parameter_code="00065",
                    unit_of_measure="ft",
                    approval_status="Provisional",
                )
            )
        self.publish(
            "observations",
            obs,
            ["series_conditions.csv", "latest_measurements.csv"],
            inventory_pointer=self.ip,
        )

    def publish(self, kind, directory, files, **extra):
        def digest(p):
            return {
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "byte_count": p.stat().st_size,
            }

        manifest = {
            "complete": True,
            "kind": kind,
            "files": {name: digest(directory / name) for name in files},
            **extra,
        }
        path = directory / "manifest.json"
        path.write_text(json.dumps(manifest))
        pointer = {"manifest_path": str(path.relative_to(self.u)), **digest(path)}
        (self.u / (kind + ".json")).write_text(json.dumps(pointer))
        return pointer

    def test_basin_contains_and_upstream_not_nearest_with_stale_values(self):
        local.build_index(self.config, self.index)
        result = local.context(38, -121, self.config, NOW, self.index)
        self.assertEqual(result["basins"][0]["name"], "Example PW")
        upstream = result["stations"][0]
        self.assertEqual(upstream["id"], "USGS-1")
        self.assertGreater(upstream["distance_miles"], 15)
        self.assertEqual(upstream["relationship"], "upstream_basin_context")
        self.assertEqual(upstream["readings"][0]["status"], "stale")
        self.assertEqual(result["stations"][1]["relationship"], "nearby_only")
        self.assertEqual(result["waterways"][0]["relationship"], "nearby_only")
        with closing(local.readonly(self.index)) as db:
            self.assertNotIn(
                "observations",
                [r[0] for r in db.execute("SELECT name FROM sqlite_master")],
            )

    def test_index_source_change_and_checksum_mismatch_fail_closed(self):
        local.build_index(self.config, self.index)
        (self.route / "routing.sqlite").touch()
        with self.assertRaisesRegex(ValueError, "changed"):
            local.context(38, -121, self.config, NOW, self.index)
        (self.inventory / "stations.geojson.gz").write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "checksum"):
            local.build_index(self.config, self.index)

    def test_missing_index_explicit(self):
        with self.assertRaisesRegex(ValueError, "unavailable"):
            local.context(38, -121, self.config, NOW, self.index)

    def test_monitor_inventory_includes_all_supported_paths_and_missing_coordinates(
        self,
    ):
        features = local.read_json(self.inventory / "stations.geojson.gz")
        for number in range(3, 10):
            features["features"].append(
                {
                    "id": f"USGS-{number}",
                    "properties": {"monitoring_location_name": f"Gauge {number}"},
                    "geometry": (
                        None
                        if number == 9
                        else {"type": "Point", "coordinates": [-121, 38]}
                    ),
                }
            )
        with gzip.open(
            self.inventory / "stations.geojson.gz", "wt", encoding="utf-8"
        ) as stream:
            json.dump(features, stream)
        self.ip = self.publish(
            "inventory",
            self.inventory,
            ["stations.geojson.gz", "relationships/station_identifiers.csv"],
        )
        with closing(sqlite3.connect(self.route / "routing.sqlite")) as db:
            for number in (3, 4, 5, 6, 7, 9):
                db.execute(
                    "INSERT INTO station_downstream_basins VALUES(?,?,?)",
                    (f"USGS-{number}", "pw", 0 if number == 7 else 1),
                )
                db.execute(
                    "INSERT INTO station_routing_coverage VALUES(?,?)",
                    (
                        f"USGS-{number}",
                        (
                            "published_reachcode_mismatch_requires_review"
                            if number == 6
                            else "paths_to_source_terminals"
                        ),
                    ),
                )
            # Duplicate join evidence must never create duplicate gauge checks.
            db.execute(
                "INSERT INTO station_downstream_basins VALUES(?,?,?)",
                ("USGS-3", "pw", 1),
            )
            db.commit()
        self.publish(
            "routing",
            self.route,
            ["routing.sqlite"],
            inventory_pointer=self.ip,
            network_pointer=None,
            link_review_pointer=None,
        )
        local.build_index(self.config, self.index)
        result = local.context(
            38, -121, dict(self.config, max_results=1), NOW, self.index
        )
        self.assertEqual(len(result["stations"]), 1)
        self.assertEqual(
            {s["id"] for s in result["upstream_stations"]},
            {"USGS-1", "USGS-3", "USGS-4", "USGS-5", "USGS-9"},
        )
        self.assertEqual(result["routing_exclusions"][0]["id"], "USGS-6")
        self.assertNotIn("readings", result["upstream_stations"][0])
        self.assertIn(
            "paths_with_unresolved_endpoints",
            (
                result["upstream_stations"][-1]["routing_caveats"]
                if result["upstream_stations"][-1]["id"] == "USGS-1"
                else next(
                    s["routing_caveats"]
                    for s in result["upstream_stations"]
                    if s["id"] == "USGS-1"
                )
            ),
        )

    def test_old_display_only_index_requires_rebuild(self):
        local.build_index(self.config, self.index)
        with closing(sqlite3.connect(self.index)) as db:
            db.execute("UPDATE metadata SET value='1' WHERE key='schema'")
            db.commit()
        with self.assertRaisesRegex(ValueError, "rebuild"):
            local.context(38, -121, self.config, NOW, self.index)


if __name__ == "__main__":
    unittest.main()
