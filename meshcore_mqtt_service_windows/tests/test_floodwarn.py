"""Offline flood alerts, location handling, and tagged radio reply regression tests."""
import asyncio
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError, URLError

import responder
from scripts import flood_warn as flood

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
COVERAGE = {'type': 'Feature', 'properties': {'forecastZone': 'https://api.weather.gov/zones/forecast/CAZ017'}}


def alert(event='Flash Flood Warning', **overrides):
    props = {'event': event, 'status': 'Actual', 'messageType': 'Alert',
             'effective': '2026-09-21T11:00:00Z', 'expires': '2026-09-21T14:00:00Z',
             'ends': None, 'onset': '2026-09-21T11:00:00Z'}
    props.update(overrides)
    return {'type': 'Feature', 'geometry': None, 'properties': props}


def collection(*features):
    return {'type': 'FeatureCollection', 'features': list(features)}


class FloodTests(unittest.TestCase):
    def test_locations(self):
        for text, expected in {
            '38.5816, -121.4944': ('coordinates', (38.5816, -121.4944), None),
            '38.5816 -121.4944': ('coordinates', (38.5816, -121.4944), None),
            '95814': ('zip', '95814', None),
            '02108-1234': ('zip', '02108', None),
            'Sacramento': ('city', 'Sacramento', 'California'),
            'Reno nv': ('city', 'Reno', 'Nevada'),
            'Reno, Nevada': ('city', 'Reno', 'Nevada'),
            'New York New York': ('city', 'New York', 'New York'),
            'Nevada City': ('city', 'Nevada City', 'California'),
        }.items():
            with self.subTest(text=text):
                self.assertEqual(flood.parse_location(text), expected)

    def test_invalid_inputs(self):
        for value in ('', '91 0', '0 -181', 'NaN 2', '1,,2', '--help', 'a; reboot', '1234'):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                flood.parse_location(value)
            self.assertNotIn('!uv', str(error.exception))

    def test_city_and_zip_resolution(self):
        reno = {'name': 'Reno', 'country_code': 'US', 'admin1': 'Nevada',
                'postcodes': ['89501'], 'latitude': 39.5296, 'longitude': -119.8138}
        with patch.object(flood, 'get_json', return_value={'results': [reno]}) as get:
            self.assertEqual(flood.resolve_location(flood.parse_location('Reno NV')), (39.5296, -119.8138))
            self.assertEqual(get.call_args.args[1]['name'], 'Reno, Nevada')
            self.assertEqual(flood.resolve_location(flood.parse_location('89501')), (39.5296, -119.8138))
            for value in ('Reno', '89502', 'Ren NV'):
                with self.assertRaises(ValueError):
                    flood.resolve_location(flood.parse_location(value))

    def test_bad_geocoder_responses(self):
        for data in (None, {'error': True}, {'results': None}, {'results': [None]},
                     {'results': [{'name': 'Reno', 'country_code': 'US', 'admin1': 'Nevada',
                                   'latitude': True, 'longitude': -120}]}):
            with patch.object(flood, 'get_json', return_value=data), self.assertRaises(RuntimeError):
                flood.resolve_location(flood.parse_location('Reno NV'))

    def test_types_order_deduplication_and_unrelated_alerts(self):
        data = collection(alert('Flood Watch'), alert('Flood Warning'),
                          alert('Flood Advisory'), alert(), alert(), alert('Wind Advisory'))
        self.assertEqual(flood.active_types(data, NOW), list(flood.ALERTS))

    def test_expired_cancelled_test_and_future_effective_are_excluded(self):
        for overrides in ({'expires': '2026-09-21T12:00:00Z'},
                          {'ends': '2026-09-21T11:59:00Z'}, {'status': 'Test'},
                          {'status': 'Exercise'}, {'messageType': 'Cancel'},
                          {'effective': '2026-09-21T13:00:00Z'}):
            with self.subTest(overrides=overrides):
                self.assertEqual(flood.active_types(collection(alert(**overrides)), NOW), [])

    def test_watch_future_onset_and_updated_alert_are_included(self):
        self.assertEqual(flood.active_types(collection(alert('Flood Watch',
            onset='2026-09-22T00:00:00Z', messageType='Update')), NOW), ['Flood Watch'])

    def test_timezone_offsets(self):
        self.assertEqual(flood.active_types(collection(alert(
            effective='2026-09-21T04:00:00-07:00', expires='2026-09-21T07:00:00-07:00')), NOW),
            ['Flash Flood Warning'])

    def test_invalid_and_incomplete_alert_data_cannot_mean_clear(self):
        for data in ({}, None, {'type': 'FeatureCollection'}, collection(None), collection({}),
                     collection(alert(event=None)), collection(alert(expires=None)),
                     collection(alert(expires='garbage')), collection(alert(status=None)),
                     collection(alert(messageType=None)), collection(alert(effective='2026-09-21T11:00:00')),
                     {**collection(), 'pagination': {'next': 'https://api.weather.gov/alerts?cursor=x'}}):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                flood.active_types(data, NOW)

    def test_no_events_preserves_user_location_and_queries_point(self):
        for value in ('Sacramento', '95814', '38.5816, -121.4944', 'Reno NV'):
            with patch.object(flood, 'resolve_location', return_value=(38.5816, -121.4944)), \
                    patch.object(flood, 'get_json', side_effect=[COVERAGE, collection()]) as get:
                self.assertEqual(flood.lookup(value), f'no flooding events declared for {value}')
                self.assertEqual(get.call_args.args, ('https://api.weather.gov/alerts/active',
                    {'point': '38.5816,-121.4944', 'status': 'actual'}))

    def test_exact_requested_output(self):
        with patch.object(flood, 'get_json', side_effect=[COVERAGE, collection()]), \
                patch.object(flood, 'active_types', return_value=list(flood.ALERTS)):
            self.assertEqual(flood.lookup('38 -121'),
                '38 -121:\n'
                'Flash Flood Warning 🟥 - Life-threatening flash flooding is imminent or occurring. Move to higher ground immediately.\n'
                'Flood Warning 🟧 - Flooding is imminent or occurring. Take necessary precautions now.\n'
                'Flood Advisory 🟨 - Minor flooding expected. May cause inconvenience but not typically life-threatening.\n'
                'Flood Watch 🟦 - Conditions favorable for flooding. Stay alert and be ready to take action.')

    def test_missing_coverage_does_not_mean_clear(self):
        with patch.object(flood, 'get_json', return_value=collection()), self.assertRaises(RuntimeError):
            flood.lookup('0 0')

    def test_network_errors_are_availability_replies(self):
        for error in (URLError('offline'), TimeoutError(), HTTPError('url', 503, 'error', {}, None),
                      HTTPError('url', 429, 'rate limit', {}, None)):
            with patch.object(flood, 'urlopen', side_effect=error), \
                    patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(flood.main(['!floodwarn', '38', '-121']), 0)
                self.assertNotIn('no flooding', output.getvalue())
                self.assertTrue(output.getvalue().strip())

    def test_http_contract(self):
        with patch.object(flood, 'urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value = io.StringIO(json.dumps(collection()))
            flood.get_json('https://api.weather.gov/alerts/active', {'point': '38,-121'})
            request = urlopen.call_args.args[0]
            self.assertIn('point=38%2C-121', request.full_url)
            self.assertIn('FloodWarn', request.get_header('User-agent'))
            self.assertEqual(urlopen.call_args.kwargs['timeout'], 12)

    def test_config_matching_and_usage(self):
        cfg = json.loads((ROOT / 'config.json').read_text())['responder']
        responder.validate_config(cfg, ROOT)
        for value in ('Sacramento', '95814', '38, -121', 'Reno Nevada'):
            self.assertEqual(responder.match_command('!floodwarn ' + value, cfg['commands']),
                             ('!floodwarn', [value], None))
        self.assertIn('!floodwarn', responder.match_command('!floodwarn', cfg['commands'])[2])
        self.assertIsNone(responder.match_command('!floodwarnx Sacramento', cfg['commands']))
        self.assertIn('!uv', responder.match_command('!uv', cfg['commands'])[2])
        cfg['commands']['!floodwarn']['max_reply_parts'] = 0
        with self.assertRaises(ValueError):
            responder.validate_config(cfg, ROOT)

    def test_real_subprocess_emoji_output_and_all_types_survive_channel_splitting(self):
        cfg = json.loads((ROOT / 'config.json').read_text())['responder']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('flood_warn.py', 'uv_index.py'):
                shutil.copyfile(ROOT / 'scripts' / name, root / name)
            fixture = collection(*(alert(event, effective='2000-01-01T00:00:00Z',
                                        expires='2099-01-01T00:00:00Z') for event in flood.ALERTS))
            (root / 'fixture.py').write_text(
                'import flood_warn as f\n'
                f'responses=iter({[COVERAGE, fixture]!r})\n'
                'f.get_json=lambda *args: next(responses)\nf.main()\n', encoding='utf-8')
            cfg['commands']['!floodwarn']['script'] = 'fixture.py'
            db = sqlite3.connect(':memory:')
            self.addCleanup(db.close)
            send = AsyncMock()
            bot = responder.Responder(root, db, cfg, 3, 'Local Bot', send)
            # Worst-case permitted sender length verifies the per-command part limit.
            sender = 'A' * 80
            self.assertTrue(bot.accept({'channel_idx': 3, 'txt_type': 0,
                'sender_timestamp': int(time.time()), 'text': f'{sender}: !floodwarn 38 -121'}))
            asyncio.run(bot.process_one())
            parts = [call.args[1] for call in send.await_args_list]
            self.assertGreater(len(parts), 4)
            self.assertLessEqual(len(parts), 12)
            for call in send.await_args_list:
                self.assertEqual(call.args[0], 3)
                self.assertTrue(call.args[1].startswith('@' + sender + ' '))
                self.assertLessEqual(len(call.args[1].encode('utf-8')), 150)
            joined = ''.join(part[len(sender) + 2:] for part in parts)
            for event, (emoji, description) in flood.ALERTS.items():
                self.assertIn(f'{event} {emoji} - {description}', joined)
            self.assertNotIn('...', joined)
            self.assertEqual(db.execute('SELECT state FROM bot_requests').fetchone()[0], 'sent')


if __name__ == '__main__':
    unittest.main()
