"""Synthetic source drift checks never authorize identities or alter readings."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import water_identifiers, water_operator_records, water_refresh
from scripts import water_settings, water_vertical_review as vertical


def table(cells):
    return (
        "<table><tr>" + "".join("<td>" + c + "</td>" for c in cells) + "</tr></table>"
    )


def pages():
    """Provide only invented HTML fixtures, including unwanted measurement sentinels."""
    equipment = '<a href="/metadata/sites/WAC">WAC</a>'
    report = table(
        [
            "STATION",
            "ID",
            "MONITOR STAGE (FEET)",
            "FLOOD STAGE (FEET)",
            "DATUM 0",
            "DATUM",
            "PEAK DATE",
            "PEAK OF RECORD",
            "OPERATING AGENCY",
        ]
    )
    report += table(
        [
            v
            for i in range(50)
            for v in [
                "Example",
                f"A{i:02}",
                "20.0",
                "30.0",
                "0.0",
                "NGVD",
                "1900-01-01",
                "987654",
                "Example",
            ]
        ]
    )
    values = {
        "cw3e_wac": "CW3E id: <b>WAC</b><br>CDEC id: <b>WAS</b><br>NWS id: <b>--</b><br>"
        "Elevation: <b>190m</b><br>Lat/Long: <b>38.702500 / -123.090900</b><br>"
        '<a href="/metadata/sites/WAC/otherequipment/568">Logger</a>'
        '<a href="/metadata/sites/WAC/sensors/899">Sensor</a>',
        "cw3e_wac_logger": equipment
        + table(
            [
                "Type",
                "Data Logger",
                "Model",
                "Sutron SatLink3 Lite",
                "Installed on",
                "July 15, 2026",
                "Notes",
                "Offset 1.420000 applied 15 July 2026",
            ]
        ),
        "cw3e_wac_sensor": equipment
        + table(
            [
                "Type",
                "Pressure transducer",
                "Model",
                "Ott Hydro PLS500",
                "Installed on",
                "July 15, 2026",
                "Deactivated on",
                "--",
                "Height (cm)",
                "--",
                "Distance (cm)",
                "--",
                "Notes",
                "",
            ]
        )
        + "<h2>Calibration History</h2>"
        + table(["On", "Notes"]),
        "cdec_was": table(
            [
                "Station ID",
                "WAS",
                "Elevation",
                "470 ft",
                "Sensor Description",
                "Sensor Number",
                "RIVER STAGE, FEET",
                "1",
            ]
        ),
        "cdec_datums": report,
    }
    return {
        vertical.SOURCE_URLS[key]: (
            "<html>" + body + "<p>Observed 987654</p></html>"
        ).encode()
        for key, body in values.items()
    }


def document():
    return {
        "schema": 1,
        "catalog_source": water_identifiers.CATALOG,
        "retrieved_at": "2030-01-01T00:00:00+00:00",
        "stations": [
            dict(
                station_id="USGS-" + sid,
                name="Fixture",
                lid="",
                identity_status="no_exact_catalog_match",
                threshold_status="unverified",
            )
            for sid in sorted(water_operator_records.WAC_STATIONS)
        ],
    }


class VerticalReviewTests(unittest.TestCase):
    def check(self, source=None):
        result = document()
        vertical.enrich(result, (source or pages()).__getitem__)
        return result

    def test_unchanged_conflict_is_explicit_without_retaining_readings(self):
        result = self.check()
        check = result["wac_was_refresh_check"]
        self.assertEqual(check["status"], "unchanged_uncertainty")
        self.assertFalse(check["correction_authorized"])
        self.assertFalse(check["link_authorized"])
        self.assertIsNone(check["applied_correction"])
        self.assertTrue(
            all(v is None for v in check["unverified_configuration"].values())
        )
        self.assertNotEqual(check["baseline_reviewed_at"], check["checked_at"])
        self.assertNotIn("987654", json.dumps(result))
        self.assertEqual(
            {key: row["metadata"] for key, row in check["sources"].items()},
            vertical.BASELINE,
        )
        self.assertEqual(
            water_operator_records.evidence("USGS-11464860")["reviewed_at"],
            check["baseline_reviewed_at"],
        )

    def test_changes_flag_specific_fields(self):
        for key, old, new, field in (
            ("cw3e_wac", b"190m", b"159m", "elevation_m"),
            ("cdec_was", b"470 ft", b"623 ft", "elevation_ft"),
            ("cw3e_wac_logger", b"1.420000", b"2.420000", "offset"),
            (
                "cw3e_wac_logger",
                b"1.420000 applied",
                b"1.420000 ft applied",
                "offset_note_recognized",
            ),
            ("cw3e_wac_logger", b"15 July 2026", b"16 July 2026", "offset_applied_on"),
            ("cw3e_wac", b"<b>WAS</b>", b"<b>XYZ</b>", "cdec_id"),
            (
                "cw3e_wac",
                b"otherequipment/568",
                b"otherequipment/999",
                "logger_link_present",
            ),
            ("cdec_was", b"<td>1</td>", b"<td>141</td>", "stage_sensor_number"),
            (
                "cw3e_wac_sensor",
                b"<td>Notes</td><td></td>",
                b"<td>Notes</td><td>Calibration added 987654</td>",
                "notes_present",
            ),
        ):
            with self.subTest(key=key, field=field):
                source = pages()
                source[vertical.SOURCE_URLS[key]] = source[
                    vertical.SOURCE_URLS[key]
                ].replace(old, new)
                result = self.check(source)["wac_was_refresh_check"]
                self.assertEqual(result["status"], "needs_review")
                self.assertEqual(result["sources"][key]["status"], "source_changed")
                self.assertIn(field, result["sources"][key]["changed_fields"])
                self.assertNotIn("987654", json.dumps(result))

    def test_formatting_and_encoding_do_not_create_false_changes(self):
        source = pages()
        for url, raw in source.items():
            source[url] = (
                raw.replace(b"190m", b"190.00 m")
                .replace(b"470 ft", b"470.000&nbsp;ft")
                .replace(b"1.420000 applied", b"1.42\n applied")
                .replace(b"38.702500 /", b"38.7025/")
                .replace(b"Sutron SatLink3 Lite", b"Sutron&nbsp;SatLink3   Lite")
                .replace(b"</html>", b"<p>\xb0</p></html>")
            )
        result = self.check(source)["wac_was_refresh_check"]
        self.assertEqual(result["status"], "unchanged_uncertainty")
        self.assertNotEqual(
            result["sources"]["cw3e_wac"]["sha256"],
            self.check()["wac_was_refresh_check"]["sources"]["cw3e_wac"]["sha256"],
        )

    def test_missing_duplicate_units_and_truncated_pages_are_invalid(self):
        for key, old, new in (
            ("cw3e_wac", b"190m", b"190ft"),
            ("cw3e_wac", b"Elevation:", b"Missing:"),
            ("cw3e_wac", b"</html>", b"Elevation: <b>190m</b></html>"),
            (
                "cdec_was",
                b"</html>",
                b"<table><td>Station ID</td><td>WAS</td></table></html>",
            ),
            ("cw3e_wac_sensor", b"<td>On</td>", b"<td>Unknown</td>"),
            ("cdec_datums", b"</html>", b""),
            ("cdec_datums", b"DATUM 0", b"DATUM UNKNOWN"),
        ):
            with self.subTest(key=key, new=new):
                source = pages()
                source[vertical.SOURCE_URLS[key]] = source[
                    vertical.SOURCE_URLS[key]
                ].replace(old, new)
                check = self.check(source)["wac_was_refresh_check"]
                self.assertEqual(check["sources"][key]["status"], "invalid_metadata")
                self.assertEqual(check["status"], "needs_review")

    def test_new_calibration_or_datum_record_requires_review_without_peak_storage(self):
        for key, addition, field in (
            (
                "cw3e_wac_sensor",
                table(["2030-01-01", "New calibration 987654"]),
                "calibration_entries_present",
            ),
            (
                "cdec_datums",
                table(
                    [
                        "Example",
                        "WAS",
                        "20",
                        "30",
                        "0",
                        "NAVD88",
                        "1900-01-01",
                        "987654",
                        "Example",
                    ]
                ),
                "was_entry_present",
            ),
        ):
            source = pages()
            url = vertical.SOURCE_URLS[key]
            source[url] = source[url].replace(
                b"</html>", addition.encode() + b"</html>"
            )
            check = self.check(source)["wac_was_refresh_check"]
            self.assertIn(field, check["sources"][key]["changed_fields"])
            self.assertNotIn("987654", json.dumps(check))

    def test_empty_report_cannot_verify_absence(self):
        source = pages()
        source[vertical.SOURCE_URLS["cdec_datums"]] = (
            b"<html>"
            + table(
                [
                    "STATION",
                    "ID",
                    "MONITOR STAGE (FEET)",
                    "FLOOD STAGE (FEET)",
                    "DATUM 0",
                    "DATUM",
                    "PEAK DATE",
                    "PEAK OF RECORD",
                    "OPERATING AGENCY",
                ]
            ).encode()
            + b"</html>"
        )
        self.assertEqual(
            self.check(source)["wac_was_refresh_check"]["sources"]["cdec_datums"][
                "status"
            ],
            "invalid_metadata",
        )

    def test_each_unavailable_source_replaces_prior_success_and_recovers(self):
        for key, url in vertical.SOURCE_URLS.items():
            with self.subTest(key=key):
                result = self.check()
                source = pages()
                del source[url]
                vertical.enrich(result, source.__getitem__)
                check = result["wac_was_refresh_check"]
                self.assertEqual(check["sources"][key]["status"], "source_unavailable")
                self.assertNotIn("metadata", check["sources"][key])
                self.assertEqual(check["status"], "needs_review")
                vertical.enrich(result, pages().__getitem__)
                self.assertEqual(
                    result["wac_was_refresh_check"]["status"], "unchanged_uncertainty"
                )

    def test_auxiliary_checks_never_authorize_links_or_change_current_values(self):
        result = self.check()
        result["wac_was_refresh_check"]["correction_authorized"] = True
        rows = water_identifiers.validate(result)
        for sid in rows:
            station = {"id": sid, "lid": "", "reading": {"stage": 3.25}}
            water_identifiers.apply(station, rows)
            self.assertEqual(station["lid"], "")
            self.assertEqual(station["reading"], {"stage": 3.25})
        result["stations"][0]["vertical_reference_check"]["status"] = "fixture"
        self.assertEqual(
            result["stations"][1]["vertical_reference_check"]["status"],
            "unchanged_uncertainty",
        )

    def test_refresh_runs_checks_on_catalog_failure_and_overwrites_one_file(self):
        good = document()
        bad = deepcopy(good)
        for row in bad["stations"]:
            row["identity_status"] = "source_unavailable"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / water_identifiers.REVIEW_FILE).write_text(
                json.dumps(good), encoding="utf-8"
            )
            real_enrich = vertical.enrich
            source = pages()
            with patch.object(water_settings, "ROOT", root), patch.object(
                water_settings, "runtime", return_value=root / "runtime"
            ), patch.object(
                water_identifiers, "review", side_effect=[good, bad]
            ), patch.object(
                vertical,
                "enrich",
                side_effect=lambda doc: real_enrich(doc, source.__getitem__),
            ):
                path, first = water_identifiers.refresh()
                self.assertEqual(
                    first["wac_was_refresh_check"]["status"], "unchanged_uncertainty"
                )
                del source[vertical.SOURCE_URLS["cw3e_wac_logger"]]
                path, second = water_identifiers.refresh()
                self.assertEqual(
                    second["wac_was_refresh_check"]["status"], "needs_review"
                )
                self.assertEqual(
                    json.loads(path.read_text())["wac_was_refresh_check"],
                    second["wac_was_refresh_check"],
                )
                self.assertEqual(list(path.parent.iterdir()), [path])

    def test_cli_flags_drift_after_saving_but_unchanged_uncertainty_succeeds(self):
        for changed in (False, True):
            source = pages()
            if changed:
                url = vertical.SOURCE_URLS["cw3e_wac"]
                source[url] = source[url].replace(b"190m", b"159m")
            result = self.check(source)
            output = io.StringIO()
            with patch(
                "sys.argv", ["water_refresh.py", "--noaa-identifiers"]
            ), patch.object(water_settings, "load", return_value={}), patch.object(
                water_identifiers, "refresh", return_value=(Path("saved.json"), result)
            ), redirect_stdout(
                output
            ):
                self.assertEqual(water_refresh.main(), int(changed))
            self.assertIn("WAC/WAS metadata:", output.getvalue())
            if changed:
                self.assertIn("elevation_m", output.getvalue())

    def test_unrelated_targets_do_not_download_sources(self):
        doc = document()
        doc["stations"] = [{"station_id": "USGS-11464400"}]
        with patch.object(vertical, "parse_metadata") as parser:
            vertical.enrich(doc, lambda _: self.fail("Unexpected network call"))
            parser.assert_not_called()
        self.assertNotIn("wac_was_refresh_check", doc)

    def test_cdec_priority_retains_conflict_and_never_falls_back_or_corrects(self):
        check = self.check()["wac_was_refresh_check"]
        preferred = check["preferred_station_elevation"]
        self.assertEqual(
            (preferred["source"], preferred["value"], preferred["units"]),
            ("cdec_was", "470", "ft"),
        )
        self.assertIsNone(preferred["vertical_datum"])
        self.assertEqual(check["sources"]["cw3e_wac"]["metadata"]["elevation_m"], "190")
        self.assertEqual(
            water_operator_records.evidence("USGS-11464860")[
                "vertical_reference_review"
            ]["station_elevations"]["preferred_source"],
            "cdec",
        )
        for failure in ("unavailable", "wrong_station", "changed_elevation"):
            source = pages()
            url = vertical.SOURCE_URLS["cdec_was"]
            if failure == "unavailable":
                del source[url]
            elif failure == "wrong_station":
                source[url] = source[url].replace(b"WAS", b"XYZ")
            else:
                source[url] = source[url].replace(b"470 ft", b"471 ft")
            check = self.check(source)["wac_was_refresh_check"]
            self.assertEqual(check["status"], "needs_review")
            self.assertFalse(check["correction_authorized"])
            preferred = check["preferred_station_elevation"]
            self.assertEqual(preferred["source"], "cdec_was")
            if failure == "changed_elevation":
                self.assertEqual(preferred["value"], "471")
                self.assertEqual(preferred["status"], "source_changed")
            else:
                self.assertIsNone(preferred["value"])
                self.assertEqual(preferred["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
