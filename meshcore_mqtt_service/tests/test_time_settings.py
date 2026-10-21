"""Shared reply timezone, provider conversion, and subprocess environment contracts."""
import asyncio
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import responder
from scripts import time_settings as settings
from scripts import time_now
from scripts import nearby_river_stations as rivers

ROOT = Path(__file__).resolve().parents[1]


class TimeSettingsTests(unittest.TestCase):
    def test_pacific_default_and_dynamic_shared_override(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(settings.display_timezone().key, 'America/Los_Angeles')
        with patch.dict(os.environ, {'MESHCORE_TIMEZONE': 'America/Denver'}):
            self.assertEqual(settings.display_timezone().key, 'America/Denver')
            self.assertEqual(settings.display_timezone('UTC').key, 'UTC')

    def test_bad_saved_timezone_fails_validation(self):
        cfg = json.loads((ROOT/'config.json').read_text())['responder']
        for zone in ('bad/zone', '', ' PST ', 123, None):
            cfg['timezone'] = zone
            with self.subTest(zone=zone), self.assertRaises(ValueError):
                responder.validate_config(cfg, ROOT)

    def test_time_and_airnow_use_same_saved_zone(self):
        instant = datetime(2026, 9, 17, 10, tzinfo=timezone.utc)
        with patch.dict(os.environ, {'MESHCORE_TIMEZONE': 'America/Denver'}), \
                patch.object(time_now, 'datetime') as clock, patch('sys.stdout', new_callable=io.StringIO) as output:
            clock.now.return_value = instant
            time_now.main()
            self.assertEqual(settings.format_utc_observation('2026-09-17T10:00:00'), '2026-09-17 04:00 MDT')
        self.assertEqual(output.getvalue(), 'Current time: 2026-09-17 04:00:00 MDT\n')

    def test_unknown_source_time_is_not_fabricated(self):
        for value in ('Unknown', 'invalid', '', None):
            self.assertEqual(settings.format_utc_observation(value), 'Unknown')
            self.assertIsNone(rivers.parse_report_time(value))
        with self.assertRaises(ValueError):
            settings.format_timestamp(datetime(2026, 1, 1))

    def test_river_report_and_reading_follow_shared_zone(self):
        stations = [{'station_id': 'TEST1', 'station_name': 'River', 'distance_miles': 1,
                     'report_issued': '500 PM PDT Thu Sep 17 2026', 'river_stage_feet': 5,
                     'river_stage_history': [{'time': '05PM', 'stage_feet': 5}]}]
        with patch.dict(os.environ, {'MESHCORE_TIMEZONE': 'Asia/Tokyo'}):
            result = rivers.format_mesh_report(stations, 15)
        self.assertIn('2026-09-18 09:00 JST', result)
        self.assertIn('TEST1: 5ft; gauge; point flooding unknown.', result)

    def test_river_midnight_and_fall_dst_hour_resolution(self):
        issued = rivers.parse_report_time('100 AM PDT Thu Sep 17 2026')
        previous = rivers.reading_time('11PM', issued)
        self.assertEqual(previous.isoformat(), '2026-09-17T06:00:00+00:00')
        issued = rivers.parse_report_time('130 AM PST Sun Nov 01 2026')
        self.assertEqual(rivers.reading_time('01AM', issued).isoformat(), '2026-11-01T09:00:00+00:00')

    def test_every_child_gets_saved_zone_instead_of_ambient_value(self):
        cfg = json.loads((ROOT/'config.json').read_text())['responder']
        request = {'sender': 'Tester', 'channel_name': '#test', 'channel_index': 3,
                   'id': 'test', 'phrase': '!status'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'fixture.py').write_text('import os\nprint(os.environ["MESHCORE_TIMEZONE"])\n')
            with patch.dict(os.environ, {'MESHCORE_TIMEZONE': 'Asia/Tokyo'}):
                cfg['timezone'] = 'America/Denver'
                result, diagnostic = asyncio.run(responder.run_script(root, {'script': 'fixture.py'}, request, cfg))
                self.assertEqual(result.strip(), 'America/Denver')
                cfg.pop('timezone')
                result, diagnostic = asyncio.run(responder.run_script(root, {'script': 'fixture.py'}, request, cfg))
                self.assertEqual(result.strip(), 'America/Los_Angeles')


if __name__ == '__main__':
    unittest.main()
