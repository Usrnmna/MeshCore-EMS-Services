"""Offline lightning contracts: 24h boundaries, chance wording, zones, and bot replies."""
import asyncio
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

import responder
from scripts import lightning as lightning

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
POINT = {'type': 'Feature', 'properties': {
    'forecastGridData': 'https://api.weather.gov/gridpoints/STO/41,68'}}


def weather(coverage=None, kind=None, attributes=None):
    return {'weather': kind, 'coverage': coverage, 'attributes': attributes or [],
            'intensity': None, 'visibility': {'value': None}}


def row(value, start=NOW, duration='P1D'):
    return {'validTime': f'{start.isoformat()}/{duration}', 'value': value}


def grid(*rows, now=NOW, **layers):
    return {'type': 'Feature', 'properties': {'updateTime': now.isoformat(),
            'weather': {'values': list(rows) or [row([weather()], start=now)]}, **layers}}


def alert(event='Severe Thunderstorm Warning', **overrides):
    props = {'event': event, 'status': 'Actual', 'messageType': 'Alert',
             'effective': NOW.isoformat(), 'onset': NOW.isoformat(),
             'expires': (NOW + timedelta(hours=3)).isoformat(), 'ends': None,
             'headline': '', 'description': '', 'instruction': ''}
    props.update(overrides)
    return {'type': 'Feature', 'geometry': None, 'properties': props}


def alerts(*features):
    return {'type': 'FeatureCollection', 'features': list(features)}


class LightningTests(unittest.TestCase):
    def test_location_contract(self):
        cases = {'38.5, -121.4': ('coordinates', (38.5, -121.4), None),
                 '38.5 -121.4': ('coordinates', (38.5, -121.4), None),
                 '95814': ('zip', '95814', None), '02108-1234': ('zip', '02108', None),
                 'Sacramento': ('city', 'Sacramento', 'California'),
                 'Reno NV': ('city', 'Reno', 'Nevada'),
                 'Reno, Nevada': ('city', 'Reno', 'Nevada')}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(lightning.parse_location(text), expected)
        for text in ('', '91 0', '0 -181', 'nan 2', '--help', 'a; reboot'):
            with self.subTest(text=text), self.assertRaises(ValueError) as error:
                lightning.parse_location(text)
            self.assertNotIn('!uv', str(error.exception))

    def test_geocoder_uses_lightning_transport_and_state(self):
        place = {'name': 'Reno', 'country_code': 'US', 'admin1': 'Nevada',
                 'latitude': 39.5, 'longitude': -119.8, 'postcodes': ['89501']}
        for text in ('Reno NV', 'Reno Nevada', '89501'):
            with patch.object(lightning, 'get_json', side_effect=[{'results': [place]}, POINT, alerts(), grid()]):
                self.assertEqual(lightning.lookup(text, NOW), f'No Lightning expected for {text} in the next 24h')
        with patch.object(lightning, 'get_json', return_value={'results': [place]}), self.assertRaises(ValueError):
            lightning.lookup('Reno', NOW)

    def test_clear_reply_preserves_location_and_point_query(self):
        with patch.object(lightning, 'get_json', side_effect=[POINT, alerts(), grid()]) as get:
            self.assertEqual(lightning.lookup(' 38.5816,   -121.4944 ', NOW),
                             'No Lightning expected for 38.5816, -121.4944 in the next 24h')
        self.assertEqual(get.call_args_list[1].args, (lightning.NWS_ALERTS_URL,
                         {'point': '38.5816,-121.4944', 'status': 'actual'}))

    def test_slight_chance_and_percentage_both_appear_in_pacific(self):
        data = grid(row([weather('slight_chance', 'thunderstorms')]), probabilityOfThunder={'values': [row(15)]})
        with patch.object(lightning, 'get_json', side_effect=[POINT, alerts(), data]): result = lightning.lookup('38 -121', NOW)
        self.assertIn('15% thunderstorm chance', result)
        self.assertIn('slight chance thunderstorms', result)
        self.assertIn('PDT', result)
        self.assertNotIn('Lightning Strike Warning', result)
        self.assertLessEqual(len(('@Reader '+result).encode()), 150)

    def test_every_stated_coverage_is_preserved(self):
        for chance in ('slight_chance', 'chance', 'likely', 'isolated', 'scattered', 'definite'):
            with self.subTest(chance=chance):
                result = lightning.forecast_windows(grid(row([weather(chance, 'thunderstorms')])), NOW)
                self.assertEqual(result[0][2], chance.replace('_', ' ') + ' thunderstorms')

    def test_even_one_percent_counts_but_rain_percentage_does_not(self):
        self.assertEqual(lightning.forecast_windows(grid(probabilityOfPrecipitation={'values': [row(100)]}), NOW), [])
        self.assertEqual(lightning.forecast_windows(grid(probabilityOfThunder={'values': [row(1)]}), NOW)[0][2],
                         '1% thunderstorm chance')

    def test_dry_thunderstorms_and_lightning_activity_levels(self):
        data = grid(row([weather('isolated', 'thunderstorms', ['dry_thunderstorms'])]))
        self.assertIn('dry thunderstorms', lightning.forecast_windows(data, NOW)[0][2])
        for value in range(1, 7):
            with self.subTest(value=value):
                result = lightning.forecast_windows(grid(lightningActivityLevel={'values': [row(value)]}), NOW)
                self.assertEqual(bool(result), value > 1)
                if value == 6:
                    self.assertIn('dry lightning', result[0][2])

    def test_window_excludes_past_and_exactly_24h_start_and_clips_end(self):
        data = grid(row([weather('chance', 'thunderstorms')], NOW - timedelta(hours=1), 'PT1H'),
                    row([weather()], NOW, 'PT23H'),
                    row([weather('slight_chance', 'thunderstorms')], NOW + timedelta(hours=23), 'PT2H'),
                    row([weather('likely', 'thunderstorms')], NOW + timedelta(hours=24), 'PT2H'))
        self.assertEqual(lightning.forecast_windows(data, NOW),
                         [(NOW + timedelta(hours=23), NOW + timedelta(hours=24), 'slight chance thunderstorms')])

    def test_stale_partial_gapped_or_invalid_forecast_never_clear(self):
        cases = [None, {}, grid(now=NOW - timedelta(hours=13)),
                 grid(row([weather()], duration='PT23H')),
                 grid(row([weather()], duration='PT1H'), row([weather()], NOW + timedelta(hours=2))),
                 grid(row(None)), grid(row([{}])), grid(row([weather()], duration='P0D')),
                 grid(now=NOW + timedelta(hours=1))]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                lightning.forecast_windows(data, NOW)

    def test_optional_absent_null_or_empty_layers_are_not_required(self):
        for layers in ({}, {'probabilityOfThunder': {'values': []}},
                       {'probabilityOfThunder': {'values': [row(None)]}},
                       {'lightningActivityLevel': {'values': []}}):
            self.assertEqual(lightning.forecast_windows(grid(**layers), NOW), [])

    def test_invalid_numeric_layers_fail(self):
        for name, values in {'probabilityOfThunder': [True, -1, 101, '10', float('nan')],
                             'lightningActivityLevel': [0, 7, 1.5]}.items():
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(RuntimeError):
                    lightning.forecast_windows(grid(**{name: {'values': [row(value)]}}), NOW)

    def test_fire_alert_needs_lightning_and_keeps_qualifier(self):
        for event in ('Red Flag Warning', 'Fire Weather Watch', 'Special Weather Statement', 'Special Marine Warning'):
            data = alerts(alert(event, description='Slight chance of dry thunderstorms with lightning.'))
            result = lightning.alert_windows(data, NOW)
            self.assertEqual(result[0][2], event + ': slight chance')
        self.assertEqual(lightning.alert_windows(alerts(alert('Red Flag Warning',
            description='Strong winds and low humidity.')), NOW), [])

    def test_negations_and_instruction_boilerplate_do_not_trigger(self):
        for description in ('No thunderstorms expected.', 'No chance of lightning.',
                            'LIGHTNING...None.', 'Thunderstorms are not expected.',
                            'Lightning is no longer expected.',
                            'Strong winds. PRECAUTIONARY/PREPAREDNESS ACTIONS... Lightning can cause fires.'):
            with self.subTest(description=description):
                data = alerts(alert('Red Flag Warning', description=description,
                                    instruction='Stay indoors when thunder roars.'))
                self.assertEqual(lightning.alert_windows(data, NOW), [])

    def test_positive_lightning_not_hidden_by_no_rain(self):
        result = lightning.alert_windows(alerts(alert('Red Flag Warning',
            description='No rain expected; isolated dry lightning is possible.')), NOW)
        self.assertIn('possible', result[0][2])

    def test_alert_onset_not_issue_time_and_end_not_early_product_expiration(self):
        data = alerts(alert('Severe Thunderstorm Watch', onset=(NOW + timedelta(hours=4)).isoformat(),
                            ends=(NOW + timedelta(hours=8)).isoformat()))
        result = lightning.alert_windows(data, NOW)
        self.assertEqual(result[0][:2], (NOW + timedelta(hours=4), NOW + timedelta(hours=8)))
        self.assertIn('chance not stated', result[0][2])

    def test_irrelevant_cancelled_test_expired_and_future_alerts_excluded(self):
        for change in ({'status': 'Test'}, {'messageType': 'Cancel'}, {'expires': NOW.isoformat()},
                       {'onset': (NOW + timedelta(hours=24)).isoformat(),
                        'ends': (NOW + timedelta(hours=30)).isoformat()}, {'event': 'Heat Advisory'}):
            self.assertEqual(lightning.alert_windows(alerts(alert(**change)), NOW), [])

    def test_incomplete_malformed_alerts_never_clear(self):
        for data in ({}, None, alerts(None), alerts(alert(expires=None)), alerts(alert(status=None)),
                     {**alerts(), 'pagination': {'next': 'more'}},
                     alerts(alert(onset=(NOW + timedelta(hours=4)).isoformat()))):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                lightning.alert_windows(data, NOW)

    def test_merged_windows_keep_changing_chances_and_clear_gaps(self):
        hour = timedelta(hours=1)
        merged = lightning.merge_windows([(NOW, NOW+hour, 'slight chance'),
            (NOW+hour, NOW+2*hour, 'slight chance'), (NOW, NOW+hour, 'slight chance'),
            (NOW+3*hour, NOW+4*hour, 'likely')])
        self.assertEqual(merged, [(NOW, NOW+2*hour, ('slight chance',)),
                                  (NOW+3*hour, NOW+4*hour, ('likely',))])

    def test_pacific_dst_transition_and_timezone_override(self):
        start = lightning.timestamp('2026-11-01T08:30:00Z')
        end = lightning.timestamp('2026-11-01T10:30:00Z')
        self.assertEqual(lightning.format_window(start, end, ZoneInfo('America/Los_Angeles')),
                         '2026-11-01 01:30 PDT-02:30 PST')
        start = lightning.timestamp('2026-03-08T09:30:00Z')
        end = lightning.timestamp('2026-03-08T11:30:00Z')
        self.assertEqual(lightning.format_window(start, end, ZoneInfo('America/Los_Angeles')),
                         '2026-03-08 01:30 PST-04:30 PDT')
        with patch.object(lightning, 'get_json', side_effect=[POINT, alerts(alert()), grid()]):
            result = lightning.lookup('38 -121', NOW, 'America/New_York')
        self.assertIn('08:00 EDT-Oct 08 11:00 EDT', result)

    def test_elapsed_24_hours_across_dst(self):
        now = datetime(2026, 11, 1, 0, tzinfo=ZoneInfo('America/Los_Angeles'))
        utc = now.astimezone(timezone.utc)
        data = grid(row([weather('chance', 'thunderstorms')], utc), now=utc)
        with patch.object(lightning, 'get_json', side_effect=[POINT, alerts(), data]):
            result = lightning.lookup('38 -121', now)
        self.assertIn('Nov 01 00:00 PDT-Nov 01 23:00 PST', result)

    def test_invalid_timezone_stops_before_network(self):
        with patch.object(lightning, 'get_json') as get, self.assertRaises(ValueError):
            lightning.lookup('38 -121', NOW, 'Not/AZone')
        get.assert_not_called()

    def test_request_time_uses_original_sender_time(self):
        with patch.dict(os.environ, {'MESHCORE_REQUEST_ID': 'request'}), \
                patch('sys.stdin', io.StringIO(json.dumps({'sender_timestamp': NOW.timestamp()}))):
            self.assertEqual(lightning.request_time(), NOW)
        with patch.dict(os.environ, {'MESHCORE_REQUEST_ID': 'request'}), \
                patch('sys.stdin', io.StringIO('{}')), self.assertRaises(RuntimeError):
            lightning.request_time()
        with patch.dict(os.environ, {}, clear=True), patch('sys.stdin') as stdin:
            self.assertLess(abs((lightning.request_time()-datetime.now(timezone.utc)).total_seconds()), 2)
        stdin.read.assert_not_called()

    def test_http_network_errors_and_no_point_coverage_never_clear(self):
        for error in (URLError('offline'), TimeoutError(), HTTPError('url', 503, 'bad', {}, None),
                      HTTPError('url', 429, 'limit', {}, None), HTTPError('url', 404, 'missing', {}, None)):
            with patch.object(lightning, 'urlopen', side_effect=error), \
                    patch('sys.stdout', new_callable=io.StringIO) as output:
                lightning.main(['38', '-121'])
            self.assertNotIn('No Lightning', output.getvalue())
        for point in ({}, {'properties': {}}, {'properties': {'forecastGridData': 'http://evil.test'}}):
            with patch.object(lightning, 'get_json', return_value=point) as get, self.assertRaises(RuntimeError):
                lightning.lookup('38 -121', NOW)
            self.assertEqual(get.call_count, 1)

    def test_main_timezone_args_and_usage(self):
        with patch.object(lightning, 'request_time', return_value=NOW), \
                patch.object(lightning, 'lookup', return_value='reply') as lookup, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(lightning.main(['--timezone', 'America/Denver', 'Reno', 'NV']), 0)
        lookup.assert_called_once_with('Reno NV', now=NOW, timezone_name='America/Denver')
        self.assertEqual(output.getvalue(), 'reply\n')
        for args in ([], ['!lightning'], ['--timezone']):
            with patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(lightning.main(args), 0)
            self.assertIn('!lightning', output.getvalue())

    def test_known_hazard_survives_other_source_outage(self):
        thunder = grid(row([weather('slight_chance', 'thunderstorms')]))
        for responses in ([POINT, alerts(alert()), RuntimeError('offline')],
                          [POINT, RuntimeError('offline'), thunder]):
            with self.subTest(responses=responses), patch.object(lightning, 'get_json', side_effect=responses):
                result = lightning.lookup('38 -121', NOW)
            self.assertIn('NWS', result)
            self.assertIn('Data incomplete.', result)

    def test_partial_empty_result_never_means_clear(self):
        for responses in ([POINT, alerts(), RuntimeError('offline')],
                          [POINT, RuntimeError('offline'), grid()],
                          [POINT, RuntimeError('offline'), RuntimeError('offline')]):
            with self.subTest(responses=responses), patch.object(lightning, 'get_json', side_effect=responses), \
                    self.assertRaises(RuntimeError):
                lightning.lookup('38 -121', NOW)

    def test_responder_registration_and_input_validation(self):
        config = json.loads((ROOT/'config.json').read_text())['responder']
        responder.validate_config(config, ROOT)
        self.assertEqual(config['commands']['!lightning']['args'], [])
        self.assertEqual(config['timezone'], 'America/Los_Angeles')
        for location in ('Sacramento', '95814', '38, -121', 'Reno Nevada'):
            self.assertEqual(responder.match_command('!lightning '+location, config['commands']),
                             ('!lightning', [location], None))
        self.assertIsNone(responder.match_command('!lightnings Sacramento', config['commands']))
        self.assertIn('!lightning', responder.match_command('!lightning', config['commands'])[2])

    def test_real_subprocess_preserves_config_zone_chance_sender_and_channel(self):
        config = json.loads((ROOT/'config.json').read_text())['responder']
        spec = config['commands']['!lightning']
        config['timezone'] = 'America/New_York'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(ROOT/'scripts/response_text.py', root/'response_text.py')
            for name in ('lightning.py', 'heat_adv.py', 'uv_index.py', 'time_settings.py'):
                shutil.copyfile(ROOT/'scripts'/name, root/name)
            now = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=120)
            forecast = grid(row([weather('slight_chance', 'thunderstorms')], now), now=now)
            (root/'fixture.py').write_text('import lightning as l\n'
                f'responses=iter({[POINT, alerts(), forecast]!r})\n'
                'l.get_json=lambda *args: next(responses)\nl.main()\n', encoding='utf-8')
            spec['script'] = 'fixture.py'
            db = sqlite3.connect(':memory:')
            self.addCleanup(db.close)
            send = AsyncMock()
            bot = responder.Responder(root, db, config, 3, 'Local Bot', send)
            sender = 'A'*80
            self.assertTrue(bot.accept({'channel_idx': 3, 'txt_type': 0,
                'sender_timestamp': int(now.timestamp()), 'text': f'{sender}: !lightning 38 -121'}))
            asyncio.run(bot.process_one())
            parts = [call.args[1] for call in send.await_args_list]
            self.assertTrue(parts)
            for call in send.await_args_list:
                self.assertEqual(call.args[0], 3)
                self.assertTrue(call.args[1].startswith('@'+sender+' '))
                self.assertLessEqual(len(call.args[1].encode('utf-8')), 150)
            joined = ''.join(part[len(sender)+2:] for part in parts)
            self.assertIn('slight chance thunderstorms', joined)
            self.assertEqual(len(parts), 1)
            self.assertNotIn('...', joined)
            self.assertEqual(db.execute('SELECT state FROM bot_requests').fetchone()[0], 'sent')


if __name__ == '__main__':
    unittest.main()
