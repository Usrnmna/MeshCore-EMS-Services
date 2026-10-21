"""Local agency evidence remains static, non-authorizing and measurement-free."""

from copy import deepcopy
from decimal import Decimal
import json
import unittest

from scripts import water_identifiers, water_map_review, water_operator_records
from test_water_map_review import document, download, gauge


class OperatorRecordTests(unittest.TestCase):
    def test_all_sixteen_records_survive_refresh_without_authorizing_links(self):
        doc = document()
        before = deepcopy(doc["stations"])
        water_map_review.enrich(doc, gauge, download)
        self.assertEqual(
            {"USGS-" + sid for sid in water_operator_records.REVIEWS},
            set(water_map_review.REVIEW_IDS),
        )
        reviewed = water_identifiers.validate(doc)
        for old, row in zip(before, doc["stations"]):
            self.assertEqual({key: row[key] for key in old}, old)
            evidence = row["map_record_review"]["operator_record_review"]
            self.assertFalse(evidence["link_authorized"])
            self.assertEqual(evidence["status"], "unresolved_at_manual_review")
            self.assertTrue(evidence["sources"])
            station = {"id": row["station_id"], "lid": ""}
            water_identifiers.apply(station, reviewed)
            self.assertEqual(station["lid"], "")
        # Fixtures deliberately include unwanted measurements in all live sources.
        self.assertNotIn("987654", json.dumps(doc))

    def test_manual_dates_do_not_become_fresh_verifications(self):
        doc = document()
        doc["retrieved_at"] = "2030-01-01T00:00:00+00:00"
        water_map_review.enrich(doc, gauge, download)
        for row in doc["stations"]:
            evidence = row["map_record_review"]["operator_record_review"]
            expected_date = (
                water_operator_records.WAC_REVIEWED_AT
                if row["station_id"][5:] in water_operator_records.WAC_STATIONS
                else water_operator_records.REVIEWED_AT
            )
            self.assertEqual(evidence["reviewed_at"], expected_date)
            self.assertNotEqual(evidence["reviewed_at"], doc["retrieved_at"])
            self.assertEqual(
                evidence["refresh_policy"],
                "fixed_manual_evidence_not_retrieved_by_refresh",
            )

    def test_operator_evidence_cannot_override_later_exact_recovery(self):
        doc = document()
        row = next(r for r in doc["stations"] if r["station_id"] == "USGS-11464400")
        row.update(
            identity_status="matched",
            lid="DCOC1",
            threshold_status="none_published",
            catalog_candidates=["DCOC1"],
            gauge_source=water_identifiers.GAUGES + "DCOC1",
            api_usgs_id="11464400",
            api_lid="DCOC1",
            thresholds={
                key: {"stage": None, "flow": None}
                for key in water_identifiers.CATEGORIES
            },
        )
        water_map_review.enrich(doc, gauge, download)
        station = {"id": row["station_id"], "lid": ""}
        water_identifiers.apply(station, water_identifiers.validate(doc))
        self.assertEqual(station["lid"], "DCOC1")

    def test_known_conflicts_and_coverage_gaps_remain_explicit(self):
        for sid in ("11460940", "11463940"):
            self.assertEqual(
                water_operator_records.evidence("USGS-" + sid)["finding"],
                "coverage_period_difference",
            )
        source = water_operator_records.SOURCES["talmage"]
        self.assertIn("11462080", source["scope"])
        self.assertIn("not Lambert Bridge", source["scope"])
        self.assertIn(
            "11463200", water_operator_records.evidence("USGS-11463160")["reason"]
        )
        self.assertEqual(
            water_operator_records.evidence("USGS-11462125")["finding"],
            "no_supported_crosswalk",
        )

    def test_recovered_wac_alias_does_not_authorize_legacy_links_or_adjust_readings(
        self,
    ):
        doc = water_map_review.enrich(document(), gauge, download)
        for row in doc["stations"]:
            if row["station_id"][5:] not in water_operator_records.WAC_STATIONS:
                continue
            evidence = row["map_record_review"]["operator_record_review"]
            sources = {s["source_id"]: s for s in evidence["sources"]}
            self.assertEqual(sources["cw3e_wac"]["metadata"]["cdec_id"], "WAS")
            self.assertIsNone(sources["cw3e_wac"]["metadata"]["published_nws_id"])
            self.assertEqual(sources["noaa_wssc1"]["metadata"]["usgs_id"], "")
            self.assertNotIn("timed out", evidence["reason"])
            # Even apparently matching manual evidence cannot replace live validation.
            sources["cw3e_wac"]["metadata"]["published_nws_id"] = "WSSC1"
            sources["noaa_wssc1"]["metadata"]["usgs_id"] = row["station_id"][5:]
            evidence["vertical_reference_review"]["correction_authorized"] = True
            evidence["vertical_reference_review"]["applied_correction"] = 1.42
            station = {"id": row["station_id"], "lid": "", "reading": {"stage": 3.25}}
            water_identifiers.apply(station, water_identifiers.validate(doc))
            self.assertEqual(station["lid"], "")
            self.assertEqual(station["reading"], {"stage": 3.25})
            self.assertEqual(row["threshold_status"], "unverified")

    def test_wac_metadata_retains_uncertainty_without_telemetry(
        self,
    ):
        evidence = water_operator_records.evidence("USGS-11464860")
        sources = {s["source_id"]: s for s in evidence["sources"]}
        self.assertEqual(sources["cw3e_wac"]["metadata"]["reported_elevation_m"], 190)
        self.assertEqual(sources["cdec_was"]["metadata"]["reported_elevation_ft"], 470)
        self.assertIn("lacks units and datum", sources["cw3e_wac_logger"]["scope"])
        self.assertIn("not applied", sources["cw3e_wac_logger"]["scope"])
        allowed = {
            "cw3e_id",
            "cdec_id",
            "published_nws_id",
            "latitude",
            "longitude",
            "installed_on",
            "reported_elevation_m",
            "reported_elevation_ft",
            "location_context",
            "lid",
            "usgs_id",
        }
        for source in sources.values():
            self.assertLessEqual(set(source.get("metadata", {})), allowed)
        encoded = json.dumps(evidence)
        for forbidden in (
            '"observed"',
            '"history"',
            '"forecast"',
            '"stage"',
            '"flow"',
        ):
            self.assertNotIn(forbidden, encoded)

    def test_elevation_conversion_does_not_establish_datum_or_offset_units(self):
        evidence = water_operator_records.evidence("USGS-11464860")
        review = evidence["vertical_reference_review"]
        elevations = review["station_elevations"]
        converted = Decimal(str(elevations["cdec"]["value"])) * Decimal("0.3048")
        self.assertEqual(converted, Decimal(str(elevations["cdec_in_metres"])))
        self.assertEqual(
            Decimal("190") - converted, Decimal(str(elevations["difference_metres"]))
        )
        self.assertFalse(review["correction_authorized"])
        self.assertIsNone(review["applied_correction"])
        self.assertIsNone(elevations["cw3e"]["vertical_datum"])
        self.assertIsNone(elevations["cdec"]["vertical_datum"])
        stage = review["cdec_stage_metadata"]
        self.assertEqual((stage["sensor_number"], stage["units"]), (1, "ft"))
        self.assertIsNone(stage["vertical_datum"])
        # Published stage units cannot fill missing logger configuration fields.
        self.assertIsNone(review["logger_offset"]["units"])

    def test_reported_offset_is_static_evidence_and_does_not_spread_between_stations(
        self,
    ):
        first = water_operator_records.evidence("USGS-11464860")
        offset = first["vertical_reference_review"]["logger_offset"]
        self.assertEqual(offset["reported_value_text"], "1.420000")
        self.assertEqual(offset["reported_applied_on"], "2026-07-15")
        for field in (
            "units",
            "sign_convention",
            "target_quantity",
            "vertical_datum",
            "already_in_published_readings",
        ):
            self.assertIsNone(offset[field])
        offset["units"] = "ft"
        self.assertIsNone(
            water_operator_records.evidence("USGS-11464880")[
                "vertical_reference_review"
            ]["logger_offset"]["units"]
        )
        self.assertNotIn(
            "vertical_reference_review",
            water_operator_records.evidence("USGS-11464400"),
        )

    def test_evidence_is_independent_and_unknown_stations_are_not_reviewed(self):
        first = water_operator_records.evidence("USGS-11464400")
        first["sources"][0]["scope"] = "changed fixture"
        self.assertNotEqual(first, water_operator_records.evidence("USGS-11464400"))
        self.assertIsNone(water_operator_records.evidence("USGS-00000000"))


if __name__ == "__main__":
    unittest.main()
