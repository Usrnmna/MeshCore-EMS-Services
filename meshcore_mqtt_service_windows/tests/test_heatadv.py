"""Offline contracts for heat alerts, location rules, and actual responder subprocesses."""
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
from scripts import heat_adv as heat

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
COVERAGE = {'type': 'Feature', 'properties': {'forecastZone': 'https://api.weather.gov/zones/forecast/CAZ017'}}


def alert(event='Heat Advisory', **overrides):
    """Build an NWS-shaped zone alert with a fixed effective period for offline tests."""
    props = {'event': event, 'status': 'Actual', 'messageType': 'Alert',
             'effective': '2026-10-06T11:00:00Z', 'expires': '2026-10-06T14:00:00Z',
             'ends': None, 'onset': '2026-10-06T11:00:00Z'}
    props.update(overrides)
    return {'type': 'Feature', 'geometry': None, 'properties': props}


def collection(*features):
    """Wrap fixture alerts in the same collection returned by the NWS point query."""
    return {'type': 'FeatureCollection', 'features': list(features)}


class HeatTests(unittest.TestCase):
    def test_location_syntax(self):
        for text, expected in {
            '38.5816, -121.4944': ('coordinates', (38.5816, -121.4944), None),
            '38.5816 -121.4944': ('coordinates', (38.5816, -121.4944), None),
            '95814': ('zip', '95814', None),
            '02108-1234': ('zip', '02108', None),
            'Sacramento': ('city', 'Sacramento', 'California'),
            'Nevada City': ('city', 'Nevada City', 'California'),
            'Reno nv': ('city', 'Reno', 'Nevada'),
            'Reno, Nevada': ('city', 'Reno', 'Nevada'),
            'New York New York': ('city', 'New York', 'New York'),
        }.items():
            with self.subTest(text=text):
                self.assertEqual(heat.parse_location(text), expected)

    def test_invalid_inputs(self):
        for value in ('', '91 0', '0 -181', 'NaN 2', '1,,2', '--help', 'a; reboot', '1234'):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                heat.parse_location(value)
            self.assertNotIn('!uv', str(error.exception))

    def test_gps_bypasses_geocoder(self):
        with patch.object(heat, 'get_json') as get:
            self.assertEqual(heat.resolve_location(heat.parse_location('38 -121')), (38, -121))
        get.assert_not_called()

    def test_exact_city_zip_country_and_state_matching(self):
        reno = {'name': 'Reno', 'country_code': 'US', 'admin1': 'Nevada',
                'postcodes': ['89501'], 'latitude': 39.5296, 'longitude': -119.8138}
        other = {**reno, 'country_code': 'CA', 'population': 9999999}
        with patch.object(heat, 'get_json', return_value={'results': [other, reno]}) as get:
            self.assertEqual(heat.resolve_location(heat.parse_location('Reno NV')), (39.5296, -119.8138))
            self.assertEqual(get.call_args.args[1]['name'], 'Reno, Nevada')
            self.assertEqual(heat.resolve_location(heat.parse_location('89501')), (39.5296, -119.8138))
            for text in ('Reno', 'Reno CA', '89502', 'Ren NV'):
                with self.subTest(text=text), self.assertRaises(ValueError):
                    heat.resolve_location(heat.parse_location(text))

    def test_bad_geocoder_responses(self):
        place = {'name': 'Reno', 'country_code': 'US', 'admin1': 'Nevada',
                 'latitude': 39.5, 'longitude': -119.8}
        responses = [None, {'error': True}, {'results': None}, {'results': [None]}]
        responses += [{'results': [{**place, 'latitude': value}]}
                      for value in (True, None, '39.5', float('nan'), float('inf'), 91)]
        for data in responses:
            with self.subTest(data=data), patch.object(heat, 'get_json', return_value=data), \
                    self.assertRaises(RuntimeError):
                heat.resolve_location(heat.parse_location('Reno NV'))

    def test_order_deduplication_legacy_names_and_unrelated_alerts(self):
        data = collection(alert(), alert('Extreme Heat Watch'), alert('Extreme Heat Warning'),
                          alert('Excessive Heat Warning'), alert('Excessive Heat Watch'),
                          alert(), alert('Red Flag Warning'), alert('Flood Advisory'))
        self.assertEqual(heat.active_types(data, NOW),
                         ['Extreme Heat Warning', 'Extreme Heat Watch', 'Heat Advisory'])

    def test_expired_ended_cancelled_test_and_future_effective_are_excluded(self):
        for overrides in ({'expires': '2026-10-06T12:00:00Z'},
                          {'ends': '2026-10-06T11:59:00Z'}, {'status': 'Test'},
                          {'status': 'Exercise'}, {'status': 'Draft'}, {'status': 'System'},
                          {'messageType': 'Cancel'}, {'messageType': 'Ack'}, {'messageType': 'Error'},
                          {'effective': '2026-10-06T13:00:00Z'}):
            with self.subTest(overrides=overrides):
                self.assertEqual(heat.active_types(collection(alert(**overrides)), NOW), [])

    def test_future_onset_watch_is_included_as_soon_as_effective(self):
        self.assertEqual(heat.active_types(collection(alert('Extreme Heat Watch',
            onset='2026-10-07T00:00:00Z', messageType='Update')), NOW), ['Extreme Heat Watch'])

    def test_timezone_offsets(self):
        self.assertEqual(heat.active_types(collection(alert(
            effective='2026-10-06T04:00:00-07:00', expires='2026-10-06T07:00:00-07:00')), NOW),
            ['Heat Advisory'])

    def test_malformed_and_incomplete_alerts_cannot_mean_clear(self):
        for data in ({}, None, {'type': 'FeatureCollection'}, collection(None), collection({}),
                     collection(alert(event=None)), collection(alert(expires=None)),
                     collection(alert(expires='garbage')), collection(alert(status=None)),
                     collection(alert(messageType=None)), collection(alert(effective='2026-10-06T11:00:00')),
                     collection(alert(expires='2026-10-06T10:00:00Z')),
                     collection(alert(ends='2026-10-06T10:00:00Z')),
                     {**collection(), 'pagination': None},
                     {**collection(), 'pagination': {'next': 'https://api.weather.gov/alerts?cursor=x'}}):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                heat.active_types(data, NOW)

    def test_clear_reply_preserves_supplied_location_and_queries_point(self):
        for text in ('Sacramento', '95814', '38.5816, -121.4944', 'Reno NV', 'Reno, Nevada'):
            with patch.object(heat, 'resolve_location', return_value=(38.5816, -121.4944)), \
                    patch.object(heat, 'get_json', side_effect=[COVERAGE, collection()]) as get:
                self.assertEqual(heat.lookup('  ' + text + '  '), f'There is no Heat Advisories for {text}')
                self.assertEqual(get.call_args_list[0].args,
                                 ('https://api.weather.gov/points/38.5816,-121.4944',))
                self.assertEqual(get.call_args.args, ('https://api.weather.gov/alerts/active',
                    {'point': '38.5816,-121.4944', 'status': 'actual'}))

    def test_exact_requested_alert_replies_individually_and_together(self):
        cases = {
            'Extreme Heat Warning': 'Advisory: Extreme Heat Warning for 38 -121',
            'Extreme Heat Watch': 'Advisory: Extreme Heat Watch for 38 -121',
            'Heat Advisory': 'Heat Advisory for 38 -121',
        }
        for events in ([event] for event in cases):
            with self.subTest(events=events), \
                    patch.object(heat, 'get_json', side_effect=[COVERAGE, collection()]), \
                    patch.object(heat, 'active_types', return_value=events):
                self.assertEqual(heat.lookup('38 -121'), cases[events[0]])
        with patch.object(heat, 'get_json', side_effect=[COVERAGE, collection()]), \
                patch.object(heat, 'active_types', return_value=list(cases)):
            self.assertEqual(heat.lookup('38 -121'), '\n'.join(cases.values()))

    def test_missing_coverage_stops_before_alert_query(self):
        for coverage in (None, collection(), {'type': 'Feature', 'properties': {}}):
            with patch.object(heat, 'get_json', return_value=coverage) as get, \
                    self.assertRaises(RuntimeError):
                heat.lookup('0 0')
            self.assertEqual(get.call_count, 1)

    def test_network_and_http_failures_cannot_mean_clear(self):
        for error in (URLError('offline'), TimeoutError(), HTTPError('url', 503, 'error', {}, None),
                      HTTPError('url', 429, 'rate limit', {}, None),
                      HTTPError('url', 404, 'not found', {}, None)):
            with self.subTest(error=error), patch.object(heat, 'urlopen', side_effect=error), \
                    patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(heat.main(['!heatadv', '38', '-121']), 0)
                self.assertNotIn('There is no Heat Advisories', output.getvalue())
                self.assertTrue(output.getvalue().strip())

    def test_http_contract_and_invalid_json(self):
        with patch.object(heat, 'urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value = io.StringIO(json.dumps(collection()))
            heat.get_json(heat.NWS_ALERTS_URL, {'point': '38,-121'})
            request = urlopen.call_args.args[0]
            self.assertIn('point=38%2C-121', request.full_url)
            self.assertIn('HeatAdv', request.get_header('User-agent'))
            self.assertIn('application/geo+json', request.get_header('Accept'))
            self.assertEqual(urlopen.call_args.kwargs['timeout'], 12)
            urlopen.return_value.__enter__.return_value = io.StringIO('<html>unavailable</html>')
            with self.assertRaises(RuntimeError):
                heat.get_json(heat.NWS_ALERTS_URL)

    def test_cli_usage_and_command_prefix(self):
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(heat.main([]), 0)
        self.assertIn('Use !heatadv', output.getvalue())
        with patch.object(heat, 'lookup', return_value='Heat Advisory for Sacramento') as lookup, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(heat.main(['!heatadv', 'Sacramento']), 0)
        lookup.assert_called_once_with('Sacramento')
        self.assertEqual(output.getvalue(), 'Heat Advisory for Sacramento\n')

    def test_config_matching_and_usage(self):
        cfg = json.loads((ROOT / 'config.json').read_text())['responder']
        responder.validate_config(cfg, ROOT)
        self.assertEqual(cfg['commands']['!heatadv']['channels'], ['default'])
        for text in ('Sacramento', '95814', '38, -121', 'Reno Nevada'):
            self.assertEqual(responder.match_command('!heatadv ' + text, cfg['commands']),
                             ('!heatadv', [text], None))
        self.assertIn('!heatadv', responder.match_command('!heatadv', cfg['commands'])[2])
        self.assertIsNone(responder.match_command('!heatadvisory Sacramento', cfg['commands']))

    def test_real_subprocess_returns_every_alert_tagged_on_requesting_channel(self):
        cfg = json.loads((ROOT / 'config.json').read_text())['responder']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('heat_adv.py', 'uv_index.py'):
                shutil.copyfile(ROOT / 'scripts' / name, root / name)
            fixture = collection(*(alert(event, effective='2000-01-01T00:00:00Z',
                                        expires='2099-01-01T00:00:00Z') for event in heat.ALERT_REPLIES))
            (root / 'fixture.py').write_text(
                'import heat_adv as h\n'
                f'responses=iter({[COVERAGE, fixture]!r})\n'
                'h.get_json=lambda *args: next(responses)\nh.main()\n', encoding='utf-8')
            cfg['commands']['!heatadv']['script'] = 'fixture.py'
            db = sqlite3.connect(':memory:')
            self.addCleanup(db.close)
            send = AsyncMock()
            bot = responder.Responder(root, db, cfg, 3, 'Local Bot', send)
            sender = 'A' * 80
            self.assertTrue(bot.accept({'channel_idx': 3, 'txt_type': 0,
                'sender_timestamp': int(time.time()), 'text': f'{sender}: !heatadv 38 -121'}))
            asyncio.run(bot.process_one())
            parts = [call.args[1] for call in send.await_args_list]
            self.assertTrue(parts)
            self.assertLessEqual(len(parts), cfg['commands']['!heatadv']['max_reply_parts'])
            for call in send.await_args_list:
                self.assertEqual(call.args[0], 3)
                self.assertTrue(call.args[1].startswith('@' + sender + ' '))
                self.assertLessEqual(len(call.args[1].encode('utf-8')), 150)
            joined = ''.join(part[len(sender) + 2:] for part in parts)
            for reply in heat.ALERT_REPLIES.values():
                self.assertIn(reply.format(location='38 -121'), joined)
            self.assertNotIn('...', joined)
            self.assertEqual(db.execute('SELECT state FROM bot_requests').fetchone()[0], 'sent')


if __name__ == '__main__':
    unittest.main()
