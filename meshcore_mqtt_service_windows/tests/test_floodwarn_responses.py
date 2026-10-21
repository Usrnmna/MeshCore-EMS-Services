"""Offline one-shot flood-warning syntax, concise replies and complete bulletin text."""

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import responder
from scripts import flood_warn, water_lookup as lookup, water_sources as sources

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 20, 19, tzinfo=timezone.utc).timestamp()
EXPIRES = datetime(2026, 10, 21, 1, tzinfo=timezone.utc).timestamp()


def record(event="Flood Warning", key="a", **changes):
    """Synthetic current bulletin, not a real alert or observation."""
    result = dict(
        id=key,
        event=event,
        expires=EXPIRES,
        effective=NOW - 60,
        headline="Hypothetical headline",
        description="Hypothetical full description.",
        instruction="Hypothetical source instructions.",
        area="Example area",
        severity="Severe",
        urgency="Immediate",
        certainty="Observed",
        url="https://api.weather.gov/alerts/" + key,
        fingerprint="fixture",
        references=[],
    )
    result.update(changes)
    return result


def snapshot(*records):
    return dict(
        target="Sacramento",
        point=[38.5816, -121.4944],
        fetched=NOW,
        mode="alerts",
        conditions={},
        official=dict(
            status="available",
            data=dict(alerts={r["id"]: r for r in records}, cancelled_ids=[]),
        ),
    )


class FloodWarnResponseTests(unittest.TestCase):
    def setUp(self):
        timezone_patch = patch.dict(
            os.environ, {"MESHCORE_TIMEZONE": "America/Los_Angeles"}
        )
        timezone_patch.start()
        self.addCleanup(timezone_patch.stop)

    def run_main(self, args, data=None, error=None):
        output = io.StringIO()
        with patch.object(
            lookup, "snapshot", return_value=data, side_effect=error
        ) as collect, redirect_stdout(output):
            self.assertEqual(flood_warn.main(args), 0)
        return output.getvalue().strip(), collect

    def test_details_rejected_and_registration_uses_dedicated_program(self):
        config = json.loads((ROOT / "config.json").read_text())["responder"]
        self.assertEqual(config["commands"]["!floodwarn"]["script"], "scripts/flood_warn.py")
        for target in ("Sacramento CA", "95814", "38.58 -121.49"):
            with self.assertRaises(ValueError): lookup.parse_query("floodwarn", "details " + target)
            self.assertIsNotNone(responder.match_command("!floodwarn details " + target, config["commands"])[2])
        self.assertEqual(lookup.parse_query("floodalarm", "Sacramento")["action"], "subscribe")

    def test_all_four_types_keep_hazard_meaning_in_one_message(self):
        meanings = {"Flash Flood Warning": "Move to higher ground now", "Flood Warning": "Flooding imminent/occurring",
                    "Flood Advisory": "Minor flooding expected", "Flood Watch": "Flooding possible; stay alert"}
        for event, meaning in meanings.items():
            text = lookup.format_floodwarn(snapshot(record(event)))
            self.assertIn(event.upper() if event.endswith("Warning") else event, text)
            self.assertIn(meaning, text)
            self.assertIn("Until 6 PM PDT", text)
            self.assertLessEqual(len(("@Alice " + text).encode()), 150)

    def test_verified_empty_and_unavailable_remain_distinct(self):
        self.assertEqual(lookup.format_floodwarn(snapshot()), "No active NWS flood alerts. | Sacramento")
        data = snapshot(record()); data["official"]["status"] = "unavailable"
        self.assertEqual(lookup.format_floodwarn(data), "NWS alerts unavailable; status unknown. | Sacramento")
        self.assertNotIn("Flooding imminent", lookup.format_floodwarn(data))

    def test_live_collection_failures_never_become_no_alert_replies(self):
        for message in (
            "Source HTTP response is stale",
            "NWS point coverage could not be verified",
            "Incomplete or invalid NWS collection",
            "Connection unavailable",
        ):
            with self.subTest(message=message), patch.object(
                sources, "alerts_at", side_effect=ValueError(message)
            ):
                data = lookup.snapshot(
                    "38 -121", "alerts", config={"enabled": True}, now=NOW
                )
            text = lookup.format_floodwarn(data)
            self.assertEqual(text, "NWS alerts unavailable; status unknown. | 38 -121")

    def test_multiple_alerts_prioritize_flash_warning_and_count_remaining(self):
        data = snapshot(record("Flood Watch", "watch"), record("Flood Advisory", "advisory"),
                        record("Flash Flood Warning", "flash"), record("Flood Warning", "warning"))
        text = lookup.format_floodwarn(data)
        self.assertIn("FLASH FLOOD WARNING", text)
        self.assertIn("+3 active alerts", text)
        self.assertEqual(text.count("Sacramento"), 1)
        self.assertNotIn("details", text)

    def test_json_preserves_full_bulletins_without_radio_details(self):
        long_text = "Hypothetical lengthy text. " * 30
        data = snapshot(record(description=long_text, instruction=long_text))
        text, _ = self.run_main(["--json", "Sacramento"], data)
        self.assertEqual(json.loads(text), data)
        self.assertNotIn(long_text, lookup.format_floodwarn(data))

    def test_optional_description_is_not_needed_for_summary(self):
        alert = record(); del alert["description"]
        self.assertIn("FLOOD WARNING", lookup.format_floodwarn(snapshot(alert)))

    def test_expiry_preserves_minutes_next_day_date_and_configured_timezone(self):
        self.assertEqual(lookup.floodwarn_expiry(EXPIRES + 1800, NOW), "6:30 PM PDT")
        self.assertEqual(
            lookup.floodwarn_expiry(EXPIRES + 86400, NOW), "Wed Oct 21 6 PM PDT"
        )
        with patch.dict(os.environ, {"MESHCORE_TIMEZONE": "America/New_York"}):
            self.assertEqual(lookup.floodwarn_expiry(EXPIRES, NOW), "9 PM EDT")

    def test_main_uses_alerts_only_without_creating_subscription(self):
        text, collect = self.run_main(["Sacramento"], snapshot(record()))
        collect.assert_called_once_with("Sacramento", "alerts")
        self.assertEqual(text, lookup.format_floodwarn(snapshot(record())))
        self.assertNotIn("subscription", text)

    def test_help_missing_location_ambiguity_and_not_found_are_short(self):
        text, collect = self.run_main([])
        self.assertIn("!floodwarn CITY", text)
        collect.assert_not_called()
        text, collect = self.run_main(["details"])
        self.assertIn("details and paging are not supported", text)
        collect.assert_not_called()
        for error, expected in (
            (
                "Ambiguous location: Example A; Example B. Resend with coordinates; monitoring not started.",
                "Multiple matches for Sacramento. Specify state or coordinates.",
            ),
            (
                "Location not found; use coordinates or a US ZIP/city and state",
                "Location not found. Use ZIP or coordinates.",
            ),
        ):
            text, _ = self.run_main(["Sacramento"], error=ValueError(error))
            self.assertEqual(text, expected)

    def test_json_stays_structured_and_categorical_baselines_omit_full_text(self):
        data = snapshot(record())
        for args in (["--json", "Sacramento"],):
            text, _ = self.run_main(args, data)
            self.assertEqual(json.loads(text), data)
        baseline = json.dumps(lookup.compact(data))
        self.assertNotIn("Hypothetical", baseline)
        self.assertNotIn("description", baseline)
        self.assertNotIn("instruction", baseline)

    def test_source_full_text_is_allowlisted_and_inactive_alerts_are_excluded(self):
        props = dict(
            id="a",
            event="Flood Warning",
            status="Actual",
            messageType="Alert",
            effective="2026-10-20T18:00:00Z",
            expires="2026-10-21T01:00:00Z",
            headline="Hypothetical headline",
            description="Full description " * 50,
            instruction="Full instructions " * 50,
            areaDesc="Example area",
            severity="Severe",
            urgency="Immediate",
            certainty="Observed",
            historical_readings=[987654],
        )
        raw = {"type": "FeatureCollection", "features": [{"properties": props}]}
        selected = sources.select_alerts(raw, NOW)
        self.assertEqual(selected["alerts"]["a"]["description"], props["description"])
        self.assertEqual(selected["alerts"]["a"]["instruction"], props["instruction"])
        self.assertNotIn("987654", json.dumps(selected))
        for change in (
            {"status": "Test"},
            {"messageType": "Cancel"},
            {"expires": "2026-10-20T18:30:00Z"},
        ):
            modified = deepcopy(raw)
            modified["features"][0]["properties"].update(change)
            self.assertFalse(sources.select_alerts(modified, NOW)["alerts"])
        for field in ("description", "instruction", "areaDesc", "severity"):
            modified = deepcopy(raw)
            modified["features"][0]["properties"][field] = {"invalid": True}
            with self.assertRaisesRegex(ValueError, "Invalid NWS alert text"):
                sources.select_alerts(modified, NOW)

    def test_actual_entrypoint_in_subprocess_and_radio_tagging(self):
        program = (
            "from unittest.mock import patch\n"
            "from scripts import water_lookup, flood_warn\n"
            f"data={snapshot(record())!r}\n"
            "with patch.object(water_lookup, 'snapshot', return_value=data):\n"
            " flood_warn.main()\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", program, "Sacramento"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NWS FLOOD WARNING", result.stdout)
        parts = responder.reply_parts("Tester", result.stdout, max_parts=1)
        self.assertTrue(
            all(p.startswith("@Tester ") and len(p.encode()) <= 150 for p in parts)
        )
        self.assertEqual(len(parts), 1)



if __name__ == "__main__":
    unittest.main()
