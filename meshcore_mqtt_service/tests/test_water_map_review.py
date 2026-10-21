"""Map candidates remain non-authorizing, explicit and free of measurements."""

from copy import deepcopy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest
from unittest.mock import patch

from scripts import water_map_review as maps, water_identifiers as identifiers


def document():
    return {
        "schema": 1,
        "catalog_source": identifiers.CATALOG,
        "retrieved_at": "2026-10-21T00:00:00+00:00",
        "stations": [
            {
                "station_id": sid,
                "name": "Fixture stream",
                "lid": "",
                "identity_status": "no_exact_catalog_match",
                "threshold_status": "unverified",
            }
            for sid in maps.REVIEW_IDS
        ],
    }


def sites():
    header = "agency_cd\tsite_no\tstation_nm\tdec_lat_va\tdec_long_va\tdec_coord_datum_cd\tsite_tp_cd\tobserved\n"
    return (
        header
        + "\n".join(
            f"USGS\t{sid[5:]}\tFixture\t38.7892\t-123.155803\tNAD83\tST\t987654"
            for sid in maps.REVIEW_IDS
        )
    ).encode()


def map_data():
    rows = [
        {
            "attributes": {
                "gaugelid": f"X{i:04}",
                "location": "Fixture",
                "waterbody": "Stream",
                "state": "CA",
                "latitude": 38.7,
                "longitude": -123,
                "observed": 987654,
            }
        }
        for i in range(100)
    ]
    rows.extend(
        {
            "attributes": {
                "gaugelid": lid,
                "location": name,
                "waterbody": "Stream",
                "state": "CA",
                "latitude": lat,
                "longitude": lon,
                "observed": 987654,
            }
        }
        for lid, (name, lat, lon) in maps.EXPECTED.items()
    )
    return {"features": rows}


def download(url):
    if url == maps.ONERAIN_SITES:
        return json.dumps(onerain_data()).encode()
    return sites() if url == maps.USGS_SITES else json.dumps(map_data()).encode()


def onerain_data():
    def site(number, system, alias, name, lat, lon):
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "site": str(number),
                "site_id": number,
                "site_alias": alias,
                "system": system,
                "name": name,
                "status": 2,
                "site_hover_html": "987654",
                "observed": 987654,
                "history": [987654],
            },
        }

    rows = [site(i, "TEST", str(i), "Fixture", 38, -123) for i in range(1, 61)]
    for i, (lid, (system, alias, name)) in enumerate(maps.ONERAIN_ALIASES.items(), 100):
        _, lat, lon = maps.EXPECTED[lid]
        rows.append(site(i, system, alias, name, lat, lon))
    return {"type": "FeatureCollection", "features": rows}


def gauge(url):
    lid = url.rsplit("/", 1)[-1]
    name, lat, lon = maps.EXPECTED[lid]
    return {
        "lid": lid,
        "name": name,
        "usgsId": "",
        "latitude": lat,
        "longitude": lon,
        "status": {"observed": {"primary": 987654}},
        "history": [987654],
    }


class MapReviewTests(unittest.TestCase):
    def test_all_sixteen_are_retained_without_links_or_readings(self):
        doc = document()
        before = deepcopy(doc["stations"])
        maps.enrich(doc, gauge, download)
        self.assertEqual(len(doc["stations"]), 16)
        for old, row in zip(before, doc["stations"]):
            self.assertEqual({k: row[k] for k in old}, old)
            self.assertEqual(row["map_record_review"]["status"], "not_linked")
            self.assertFalse(row["map_record_review"]["link_authorized"])
        self.assertNotIn("987654", json.dumps(doc))
        self.assertNotIn('"history"', json.dumps(doc))
        rows = identifiers.validate(doc)
        station = {"id": "USGS-11464400", "lid": ""}
        identifiers.apply(station, rows)
        self.assertEqual(station["lid"], "")

    def test_changed_identity_is_flagged_even_at_identical_coordinates(self):
        def changed(url):
            raw = gauge(url)
            raw["usgsId"] = "11464400"
            return raw

        doc = maps.enrich(document(), changed, download)
        row = next(r for r in doc["stations"] if r["station_id"] == "USGS-11464400")
        self.assertEqual(row["map_record_review"]["status"], "needs_review")
        self.assertEqual(row["lid"], "")
        self.assertEqual(row["identity_status"], "no_exact_catalog_match")

    def test_source_failures_are_not_negative_search_results(self):
        for failed_url in (maps.USGS_SITES, maps.MAP_QUERY, maps.ONERAIN_SITES):

            def failed(url):
                if url == failed_url:
                    raise OSError("Unavailable fixture")
                return download(url)

            doc = maps.enrich(document(), gauge, failed)
            self.assertTrue(
                all(
                    r["map_record_review"]["status"] == "source_unavailable"
                    for r in doc["stations"]
                )
            )
            self.assertTrue(all(not r["lid"] for r in doc["stations"]))

    def test_partial_duplicate_and_malformed_maps_are_rejected(self):
        for change in (
            lambda d: d.update(exceededTransferLimit=True),
            lambda d: d["features"].append(d["features"][0]),
            lambda d: d["features"][0]["attributes"].pop("waterbody"),
            lambda d: d["features"][0]["attributes"].update(latitude=float("nan")),
            lambda d: d.update(features=[]),
        ):
            data = map_data()
            change(data)
            with self.assertRaises(ValueError):
                maps.parse_map(json.dumps(data).encode())

    def test_duplicate_or_missing_usgs_records_are_explicit(self):
        with self.assertRaises(ValueError):
            maps.parse_sites(sites() + b"\n" + sites().splitlines()[1])

        def missing(url):
            return (
                b"\n".join(sites().splitlines()[:-1])
                if url == maps.USGS_SITES
                else download(url)
            )

        doc = maps.enrich(document(), gauge, missing)
        self.assertEqual(
            doc["stations"][-1]["map_record_review"]["status"], "source_unavailable"
        )

    def test_candidate_api_errors_and_changed_positions_are_explicit(self):
        for update, expected in (
            ({"lid": "WRONG"}, "source_unavailable"),
            ({"latitude": 39}, "needs_review"),
            ({"name": "Different site"}, "needs_review"),
        ):

            def changed(url):
                return dict(gauge(url), **update)

            doc = maps.enrich(document(), changed, download)
            row = next(r for r in doc["stations"] if r["station_id"] == "USGS-11463940")
            self.assertEqual(row["map_record_review"]["status"], expected)
            self.assertEqual(row["lid"], "")

    def test_auxiliary_review_never_revokes_supported_exact_recovery(self):
        doc = document()
        row = next(r for r in doc["stations"] if r["station_id"] == "USGS-11464400")
        row.update(
            identity_status="matched", lid="DCOC1", threshold_status="none_published"
        )
        original = deepcopy(row)
        maps.enrich(doc, gauge, download)
        self.assertEqual({k: row[k] for k in original}, original)

    def test_refresh_invokes_map_review(self):
        # Existing identifier matching remains responsible for authorizing links.
        target = {"station_id": "USGS-11464400", "name": "Fixture"}
        maps_enrich = maps.enrich
        with (
            patch.object(identifiers, "parse_catalog", return_value=([], {}, {})),
            patch("scripts.water_agency_review.enrich"),
            patch(
                "scripts.water_map_review.enrich",
                side_effect=lambda doc, fetch: maps_enrich(doc, fetch, download),
            ),
        ):
            reviewed = identifiers.review([target], lambda: b"Fixture", gauge)
        self.assertEqual(
            reviewed["stations"][0]["map_record_review"]["status"], "not_linked"
        )
        self.assertEqual(reviewed["stations"][0]["lid"], "")

    def test_refresh_reports_auxiliary_failures_and_changed_candidates(self):
        from scripts import water_refresh

        for status in ("source_unavailable", "needs_review"):
            doc = document()
            doc["stations"][0]["map_record_review"] = {"status": status}
            with (
                patch("sys.argv", ["water_refresh.py", "--noaa-identifiers"]),
                patch.object(water_refresh.water_settings, "load", return_value={}),
                patch.object(
                    identifiers, "refresh", return_value=("fixture.json", doc)
                ),
                patch("builtins.print"),
            ):
                self.assertEqual(water_refresh.main(), 1)

    def test_onerain_alias_is_a_lead_not_an_accepted_usgs_link(self):
        data = onerain_data()
        data["features"][0]["properties"].update(system="USGS", site_alias=11464400)

        def changed(url):
            return (
                json.dumps(data).encode()
                if url == maps.ONERAIN_SITES
                else download(url)
            )

        doc = maps.enrich(document(), gauge, changed)
        row = next(r for r in doc["stations"] if r["station_id"] == "USGS-11464400")
        self.assertEqual(row["map_record_review"]["status"], "needs_review")
        self.assertEqual(row["lid"], "")
        self.assertFalse(row["map_record_review"]["onerain_review"]["link_authorized"])
        self.assertNotIn("987654", json.dumps(doc))

    def test_onerain_duplicates_partial_responses_and_bad_geometry_fail(self):
        for change in (
            lambda d: d["features"].append(d["features"][0]),
            lambda d: d.update(features=[]),
            lambda d: d.update(exceededTransferLimit=True),
            lambda d: d["features"][0]["properties"].update(site_id={"history": [1]}),
            lambda d: d["features"][0]["geometry"].update(coordinates=[]),
        ):
            data = onerain_data()
            change(data)
            with self.assertRaises(ValueError):
                maps.parse_onerain(json.dumps(data).encode())

    def test_changed_or_ambiguous_operator_alias_requires_review(self):
        for change in (
            lambda row: row.update(name="Different site"),
            lambda row: row.update(alias="NEW"),
        ):
            rows = maps.parse_onerain(json.dumps(onerain_data()).encode())
            target = next(r for r in rows if r["alias"] == "DAC")
            change(target)
            result = maps.onerain_evidence("USGS-11464400", ["DCOC1"], rows, True)
            self.assertEqual(result["status"], "needs_review")
            self.assertFalse(result["link_authorized"])

    def test_manual_pdf_review_time_is_not_replaced_by_refresh_time(self):
        doc = document()
        doc["retrieved_at"] = "2026-11-01T00:00:00+00:00"
        maps.enrich(doc, gauge, download)
        context = doc["stations"][0]["map_record_review"]["historical_context"]
        self.assertEqual(context["pdf_page"], 18)
        self.assertEqual(context["reviewed_at"], "2026-10-21T03:40:21+00:00")
        self.assertNotIn("403", context["access"])

    def test_redirect_cookies_are_transient_and_downloads_succeed(self):
        from scripts.water_agency_review import fetch_bytes

        initial_cookies = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/start":
                    initial_cookies.append(self.headers.get("Cookie"))
                    self.send_response(302)
                    self.send_header("Set-Cookie", "test_session=ready; Path=/")
                    self.send_header("Location", "/metadata")
                    self.end_headers()
                elif "test_session=ready" in self.headers.get("Cookie", ""):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"metadata only")
                else:
                    self.send_response(403)
                    self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/start"
            self.assertEqual(fetch_bytes(url), b"metadata only")
            self.assertEqual(fetch_bytes(url), b"metadata only")
            self.assertEqual(initial_cookies, [None, None])
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
