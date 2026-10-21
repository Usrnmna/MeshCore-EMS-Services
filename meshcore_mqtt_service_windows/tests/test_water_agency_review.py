"""Agency-successor provenance, changed-source withholding and no-history regressions."""

from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import water_agency_review as agency, water_identifiers as identifiers
from scripts import water_sources, water_settings, water_lookup

PDF = b"%PDF reviewed fixture"
PDF_HASH = hashlib.sha256(PDF).hexdigest()
CDEC = b"<table><tr><td>Station ID</td><td>CDM</td><td>Operator</td><td>US Army Corps of Engineers</td><td>Latitude</td><td>39.197500&#176;</td><td>Longitude</td><td>-123.186400\xb0</td></tr></table>"
HADS_META = b"<table><td>EAST FORK RUSSIAN RIVER BELOW COYOTE DAM NEAR UKIAH 3NNE (CDM)</td><td>YDMC1</td><td>CE902418</td><td>EKA</td><td>39 degrees</td><td>-123 degrees</td><td>CESPD1</td></table>"
HADS = (
    "NWS STATION\nIDENTIFR\nHEADER\n-----\n"
    + "\n".join(f"A{i:04}|12345678|AAAA|EKA|0|0|Other" for i in range(100))
).encode()
USGS = b"# metadata only\nagency_cd\tsite_no\tstation_nm\tdata_type_cd\tparm_cd\tbegin_date\tend_date\tvalue\n5s\t15s\t50s\t2s\t5s\t10d\t10d\t8n\nUSGS\t11462000\tEF Russian\tuv\t00065\t2007-10-01\t2011-10-02\t987654\nUSGS\t11462000\tEF Russian\tqw\t00010\t2000-01-01\t2001-01-01\t999999\n"


def source_bytes(url):
    return {
        agency.REPORT: PDF,
        agency.CDEC: CDEC,
        agency.HADS_EKA: HADS_META,
        agency.HADS: HADS,
        agency.USGS: USGS,
    }[url]


def gauge():
    return {
        "lid": "YDMC1",
        "usgsId": "",
        "name": agency.SUCCESSOR_NAME,
        "latitude": 39.1975,
        "longitude": -123.1864,
        "flood": {
            "stageUnits": "ft",
            "flowUnits": "cfs",
            "categories": {
                name: {"stage": -9999, "flow": -9999} for name in identifiers.CATEGORIES
            },
            "crests": {"historic": [123456]},
        },
        "inService": {"enabled": True},
        "status": {
            "observed": {
                "primary": 5,
                "validTime": datetime.fromtimestamp(
                    1792500000, timezone.utc
                ).isoformat(),
                "floodCategory": "not_defined",
            }
        },
    }


def document():
    return {
        "schema": 1,
        "catalog_source": identifiers.CATALOG,
        "retrieved_at": "2026-10-21T00:00:00+00:00",
        "stations": [
            {
                "station_id": agency.SUCCESSOR_ID,
                "name": "EF RUSSIAN R NR UKIAH CA",
                "lid": "",
                "identity_status": "no_exact_catalog_match",
                "threshold_status": "unverified",
            }
        ],
    }


class AgencyReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for patcher in (
            patch.object(agency, "REPORT_SHA256", PDF_HASH),
            patch.object(water_settings, "runtime", return_value=Path(self.temp.name)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def reviewed(self):
        return agency.enrich(document(), lambda _: gauge(), source_bytes)

    def test_successor_chain_retains_static_provenance_only(self):
        report = self.reviewed()
        rows = identifiers.validate(report)
        row = rows[agency.SUCCESSOR_ID]
        self.assertEqual(row["identity_status"], "matched_agency_successor")
        self.assertEqual(row["threshold_status"], "none_published")
        self.assertEqual(row["api_usgs_id"], "")
        self.assertEqual(
            row["agency_review"]["usgs_record_status"], "historical_periods_only"
        )
        self.assertEqual(len(row["agency_review"]["usgs_periods"]), 1)
        station = {"id": agency.SUCCESSOR_ID, "lid": ""}
        identifiers.apply(station, rows)
        self.assertEqual(station["lid"], "YDMC1")
        for key in ("primary", "observed", "crests", "987654", "999999", "123456"):
            self.assertNotIn(key, json.dumps(report))

    def test_report_identity_operator_coordinates_and_duplicate_hads_are_guards(self):
        agency.verify_successor_metadata(PDF, CDEC, HADS_META)
        cases = [
            (PDF + b"changed", CDEC, HADS_META),
            (PDF, CDEC.replace(b"CDM", b"OTHER"), HADS_META),
            (PDF, CDEC.replace(b"US Army Corps of Engineers", b"Other"), HADS_META),
            (PDF, CDEC.replace(b"39.197500", b"39.198500"), HADS_META),
            (PDF, CDEC, HADS_META.replace(b"CE902418", b"DIFFERENT")),
            (PDF, CDEC, HADS_META + HADS_META),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                agency.verify_successor_metadata(*args)

    def test_each_source_failure_withholds_successor_without_erasing_original_result(
        self,
    ):
        for unavailable in agency.SOURCE_URLS.values():

            def fetch(url):
                if url == unavailable:
                    raise OSError("offline")
                return source_bytes(url)

            row = agency.enrich(document(), lambda _: gauge(), fetch)["stations"][0]
            self.assertEqual(row["lid"], "")
            self.assertEqual(row["identity_status"], "no_exact_catalog_match")
            self.assertEqual(row["agency_review"]["status"], "source_unavailable")

    def test_changed_report_and_api_identity_are_not_accepted(self):
        row = agency.enrich(
            document(),
            lambda _: gauge(),
            lambda u: PDF + b"new" if u == agency.REPORT else source_bytes(u),
        )["stations"][0]
        self.assertEqual(row["lid"], "")
        for field, value in (
            ("usgsId", "11462080"),
            ("usgsId", None),
            ("lid", "OTHER"),
            ("name", "Similar name"),
            ("latitude", 39.2),
        ):
            raw = gauge()
            raw[field] = value
            row = agency.enrich(document(), lambda _: raw, source_bytes)["stations"][0]
            self.assertEqual(row["lid"], "")

    def test_proof_cannot_be_missing_or_forged(self):
        report = self.reviewed()
        for key in agency.SOURCE_URLS:
            altered = deepcopy(report)
            altered["agency_sources"].pop(key)
            with self.assertRaisesRegex(ValueError, "successor"):
                identifiers.validate(altered)
        altered = deepcopy(report)
        altered["agency_sources"]["agency_report"]["sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "successor"):
            identifiers.validate(altered)

    def test_cached_successor_is_withheld_immediately_after_review_failure(self):
        rows = identifiers.validate(self.reviewed())
        config = water_settings.validate({})
        with patch.object(identifiers, "load", return_value=(rows, "checked")):
            result = water_sources.gauge(
                "YDMC1", agency.SUCCESSOR_ID, config, 1792500000, lambda _: gauge()
            )
        self.assertEqual(result["condition"], "threshold_unavailable")
        self.assertEqual(result["identity_basis"], "agency_successor")
        with patch.object(
            identifiers, "load", return_value=({}, "failed")
        ), self.assertRaisesRegex(ValueError, "withheld"):
            water_sources.gauge(
                "YDMC1",
                agency.SUCCESSOR_ID,
                config,
                1792500001,
                lambda _: self.fail("Should not fetch revoked link"),
            )
        with closing(
            sqlite3.connect(Path(self.temp.name) / "water_current.sqlite3")
        ) as db:
            body = db.execute("SELECT body FROM current").fetchone()[0]
            self.assertNotIn("crests", body)
            self.assertNotIn("123456", body)

    def test_blank_noaa_usgs_id_does_not_authorize_other_stations(self):
        with self.assertRaisesRegex(ValueError, "identity conflict"):
            water_sources.gauge(
                "YDMC1",
                "USGS-11465300",
                water_settings.validate({}),
                1792500000,
                lambda _: gauge(),
            )

    def test_exact_id_recovery_revalidates_an_agency_cache_entry(self):
        rows = identifiers.validate(self.reviewed())
        config = water_settings.validate({})
        with patch.object(identifiers, "load", return_value=(rows, "checked")):
            water_sources.gauge(
                "YDMC1", agency.SUCCESSOR_ID, config, 1792500000, lambda _: gauge()
            )
        exact = deepcopy(rows)
        exact[agency.SUCCESSOR_ID]["identity_status"] = "matched"
        raw = gauge()
        raw["usgsId"] = "11462000"
        with patch.object(identifiers, "load", return_value=(exact, "checked")):
            result = water_sources.gauge(
                "YDMC1", agency.SUCCESSOR_ID, config, 1792500001, lambda _: raw
            )
        self.assertEqual(result["identity_basis"], "exact_usgs_id")

    def test_metadata_errors_and_historical_records_never_create_matches(self):
        for raw in (b"error page", USGS.replace(b"11462000", b"11464000")):
            with self.assertRaises(ValueError):
                agency.parse_usgs(raw)
        with self.assertRaises(ValueError):
            agency.parse_hads(b"error page")
        self.assertNotIn(agency.SUCCESSOR_ID, agency.parse_hads(HADS))
        report = document()
        report["stations"][0]["station_id"] = "USGS-11465300"
        row = agency.enrich(
            report,
            lambda _: self.fail("Historical metadata is not a match"),
            source_bytes,
        )["stations"][0]
        self.assertEqual(row["lid"], "")

    def test_radio_summary_labels_successor_and_baseline_is_categorical(self):
        condition = {
            "state": "threshold_unavailable",
            "label": "Outlet",
            "evidence": "derived_graph_plus_basin_overlap",
            "noaa_identity_status": "matched_agency_successor",
            "threshold_status": "none_published",
            "reading_status": "unavailable",
        }
        conditions = {"gauge:" + agency.SUCCESSOR_ID: condition}
        self.assertIn(
            "Agency-successor links=1", water_lookup.condition_summary(conditions)
        )
        snapshot = {
            "point": [39, -123],
            "official": {"status": "available", "data": {"alerts": {}}},
            "conditions": conditions,
        }
        baseline = water_lookup.compact(snapshot)
        self.assertEqual(
            baseline["conditions"]["gauge:" + agency.SUCCESSOR_ID][
                "noaa_identity_status"
            ],
            "matched_agency_successor",
        )


if __name__ == "__main__":
    unittest.main()
