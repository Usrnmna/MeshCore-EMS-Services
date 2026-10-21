"""Official identifier corroboration, withheld matches and current-only review tests."""

from datetime import datetime, timezone
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import water_identifiers as identifiers, water_sources, water_settings

SID = "USGS-11462500"
TARGET = {"station_id": SID, "name": "Example river"}


def catalog(extra=None):
    """Produce a national-sized fixture; unrelated rows cannot authorize a target."""
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["usgs id", "nws shef id", "location name", "state"])
    writer.writerows([["", f"X{i:04}", "Unrelated", "CA"] for i in range(1000)])
    writer.writerows(
        extra if extra is not None else [["11462500", "HOPC1", "Example river", "CA"]]
    )
    return stream.getvalue().encode()


def gauge():
    return {
        "usgsId": "11462500",
        "lid": "HOPC1",
        "name": "Example river",
        "flood": {
            "stageUnits": "ft",
            "flowUnits": "cfs",
            "categories": {
                "action": {"stage": -9999, "flow": -9999},
                "minor": {"stage": 15, "flow": -9999},
                "moderate": {"stage": 23, "flow": -9999},
                "major": {"stage": 26, "flow": -9999},
            },
            "crests": {"historic": [{"stage": 123456}]},
        },
        "status": {"observed": {"primary": 987654}},
    }


class IdentifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name) / "runtime"
        patcher = patch.object(water_settings, "runtime", return_value=self.runtime)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_exact_crosswalk_keeps_provenance_and_static_thresholds_only(self):
        report = identifiers.review([TARGET], catalog, lambda url: gauge())
        rows = identifiers.validate(report)
        row = rows[SID]
        self.assertEqual(row["lid"], "HOPC1")
        self.assertEqual(row["threshold_status"], "published")
        self.assertIsNone(row["thresholds"]["action"]["stage"])
        self.assertEqual(row["thresholds"]["minor"]["stage"], 15)
        self.assertEqual(row["gauge_source"], identifiers.GAUGES + "HOPC1")
        self.assertEqual(len(report["catalog_sha256"]), 64)
        serialized = json.dumps(report)
        for forbidden in ("observed", "crests", "123456", "987654"):
            self.assertNotIn(forbidden, serialized)

    def test_duplicate_catalog_id_or_shared_lid_is_withheld(self):
        base = ["11462500", "HOPC1", "Example river", "CA"]
        for extra in ([base, base], [base, ["11462000", "HOPC1", "Other", "CA"]]):
            with self.subTest(extra=extra):
                report = identifiers.review(
                    [TARGET],
                    lambda: catalog(extra),
                    lambda _: self.fail("Ambiguous identities must not fetch"),
                )
                self.assertEqual(
                    report["stations"][0]["identity_status"], "ambiguous_catalog_match"
                )
                self.assertEqual(report["stations"][0]["lid"], "")

    def test_same_name_different_id_is_not_a_match(self):
        report = identifiers.review(
            [TARGET], lambda: catalog([["11462000", "HOPC1", TARGET["name"], "CA"]])
        )
        row = report["stations"][0]
        self.assertEqual(row["identity_status"], "no_exact_catalog_match")
        self.assertEqual(row["lid"], "")

    def test_api_identity_mismatch_and_failure_are_explicit(self):
        for field in ("usgsId", "lid"):
            data = gauge()
            data[field] = "WRONG"
            row = identifiers.review([TARGET], catalog, lambda _: data)["stations"][0]
            self.assertEqual(row["identity_status"], "identity_conflict")
            self.assertEqual(row["lid"], "")

        def unavailable(_):
            raise OSError("offline")

        row = identifiers.review([TARGET], catalog, unavailable)["stations"][0]
        self.assertEqual(row["identity_status"], "source_unavailable")
        self.assertEqual(row["threshold_status"], "unverified")

    def test_catalog_error_or_short_response_is_not_a_negative_search(self):
        for raw in (
            b"<html>error</html>",
            b"usgs id,nws shef id,location name,state\n",
        ):
            row = identifiers.review([TARGET], lambda: raw)["stations"][0]
            self.assertEqual(row["identity_status"], "source_unavailable")
        data = gauge()
        del data["flood"]["categories"]
        row = identifiers.review([TARGET], catalog, lambda _: data)["stations"][0]
        self.assertEqual(row["identity_status"], "source_unavailable")
        self.assertEqual(identifiers.threshold_status({}), "unverified")

    def test_undefined_thresholds_do_not_discard_supported_identity(self):
        data = gauge()
        for values in data["flood"]["categories"].values():
            values["stage"] = -9999
        row = identifiers.review([TARGET], catalog, lambda _: data)["stations"][0]
        self.assertEqual(
            (row["identity_status"], row["threshold_status"]),
            ("matched", "none_published"),
        )
        self.assertEqual(row["lid"], "HOPC1")

    def test_overlay_preserves_original_and_withholds_conflict(self):
        rows = identifiers.validate(
            identifiers.review([TARGET], catalog, lambda _: gauge())
        )
        station = {"id": SID, "lid": ""}
        identifiers.apply(station, rows)
        self.assertEqual(station["lid"], "HOPC1")
        conflicting = {"id": SID, "lid": "OTHER"}
        identifiers.apply(conflicting, rows)
        self.assertEqual(conflicting["lid"], "")
        self.assertEqual(
            conflicting["noaa_identity_status"], "inventory_identity_conflict"
        )
        self.assertEqual(rows[SID]["lid"], "HOPC1")
        untouched = {"id": "USGS-11464000", "lid": "HEAC1"}
        identifiers.apply(untouched, rows)
        self.assertEqual(untouched["lid"], "HEAC1")

    def test_refresh_replaces_success_with_failure_and_never_falls_back(self):
        good = identifiers.review([TARGET], catalog, lambda _: gauge())
        bad = identifiers.review([TARGET], lambda: b"unavailable")
        bundle = Path(self.temp.name) / identifiers.REVIEW_FILE
        bundle.write_text(json.dumps(good), encoding="utf-8")
        with patch.object(water_settings, "ROOT", bundle.parent), patch.object(
            identifiers, "review", side_effect=[good, bad]
        ):
            path, _ = identifiers.refresh()
            self.assertEqual(identifiers.load()[0][SID]["lid"], "HOPC1")
            identifiers.refresh()
            self.assertEqual(
                identifiers.load()[0][SID]["identity_status"], "source_unavailable"
            )
            self.assertEqual(list(self.runtime.iterdir()), [path])
            self.assertNotIn("HOPC1", path.read_text())
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                identifiers.load()

    def test_bundled_review_has_all_33_results_and_six_new_threshold_sites(self):
        document = json.loads(
            (water_settings.ROOT / identifiers.REVIEW_FILE).read_text(encoding="utf-8")
        )
        rows = identifiers.validate(document)
        self.assertEqual(len(rows), 33)
        self.assertEqual(
            sum(r["identity_status"] == "matched" for r in rows.values()), 16
        )
        self.assertEqual(
            sum(r["threshold_status"] == "published" for r in rows.values()), 6
        )
        self.assertEqual(
            sum(r["threshold_status"] == "none_published" for r in rows.values()), 11
        )
        self.assertEqual(
            sum(
                r["identity_status"] == "no_exact_catalog_match" for r in rows.values()
            ),
            16,
        )
        self.assertEqual(
            rows["USGS-11462000"]["identity_status"], "matched_agency_successor"
        )

    def test_gauge_category_requires_corresponding_defined_threshold(self):
        now = 1792500000
        config = water_settings.validate({})
        data = gauge()
        data["inService"] = {"enabled": True}
        data["status"]["observed"] = {
            "primary": 5,
            "validTime": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "floodCategory": "no_flooding",
        }
        with patch.object(
            water_sources, "cached", side_effect=lambda key, config, fetch, now: fetch()
        ):
            self.assertEqual(
                water_sources.gauge("HOPC1", SID, config, now, lambda _: data)[
                    "condition"
                ],
                "no_flooding",
            )
            for values in data["flood"]["categories"].values():
                values["stage"] = -9999
            for category in ("no_flooding", "action", "minor", "moderate", "major"):
                data["status"]["observed"]["floodCategory"] = category
                result = water_sources.gauge("HOPC1", SID, config, now, lambda _: data)
                self.assertEqual(result["condition"], "threshold_unavailable")
                self.assertEqual(result["threshold_status"], "none_published")
            data["flood"]["categories"]["major"]["stage"] = 0
            self.assertEqual(
                water_sources.gauge("HOPC1", SID, config, now, lambda _: data)[
                    "condition"
                ],
                "major",
            )
            self.assertEqual(
                water_sources.gauge("HOPC1", SID, config, now + 21601, lambda _: data)[
                    "condition"
                ],
                "stale",
            )
            data["status"]["observed"]["primary"] = -9999
            self.assertEqual(
                water_sources.gauge("HOPC1", SID, config, now, lambda _: data)[
                    "condition"
                ],
                "invalid",
            )


if __name__ == "__main__":
    unittest.main()
