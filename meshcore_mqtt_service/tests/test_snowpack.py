"""Snowpack source validation and full tagged-responder regression tests."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from urllib.error import URLError

import responder
from scripts import snowpack as snow

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 23, 2, tzinfo=timezone.utc)
POINT = {'properties': {'county': 'https://api.weather.gov/zones/county/CAC057',
                       'forecastGridData': 'https://api.weather.gov/gridpoints/REV/31,100'}}
HTML = '''<table id="station_table"><tr><th>ID</th><th>Station Name</th>
<th>Longitude</th><th>Latitude</th></tr>
<tr><td><a>FAR</a></td><td>Far Peak</td><td>-121</td><td>40</td></tr>
<tr><td><a>ABC</a></td><td>Snow &amp; Creek</td><td>-120</td><td>39</td></tr></table>'''


def observation(**changes):
    row = {'stationId': 'ABC', 'SENSOR_NUM': 18, 'durCode': 'H', 'units': 'INCHES',
           'dataFlag': ' ', 'obsDate': '2026-9-22 17:00', 'value': 12}
    row.update(changes)
    return row


def forecast(value=25.4, **changes):
    props = {'updateTime': NOW.isoformat(), 'snowfallAmount': {'uom': 'wmoUnit:mm',
             'values': [{'validTime': (NOW+timedelta(hours=i)).isoformat()+'/PT6H',
                         'value': value} for i in range(0, 24, 6)]}}
    props.update(changes)
    return {'properties': props}


class SnowpackTests(unittest.TestCase):
    def test_locations(self):
        for text, expected in {
            '39, -120': ('coordinates', (39, -120), None),
            '39 -120': ('coordinates', (39, -120), None),
            '96161-1234': ('zip', '96161', None),
            'Truckee': ('city', 'Truckee', 'California'),
            'South Lake Tahoe CA': ('city', 'South Lake Tahoe', 'California'),
            'Nevada City, California': ('city', 'Nevada City', 'California'),
        }.items():
            self.assertEqual(snow.parse_location(text), expected)

    def test_invalid_and_out_of_state_input(self):
        for text in ('', '91, 0', '0, -181', 'NaN, 0', '1234', 'a; reboot', '--help', 'Reno NV'):
            with self.subTest(text=text), self.assertRaises(ValueError) as exc:
                snow.parse_location(text)
            self.assertNotIn('!uv', str(exc.exception))

    def test_california_city_zip_resolution(self):
        rows = [{'name': 'Truckee', 'admin1': 'California', 'country_code': 'US',
                 'latitude': 39, 'longitude': -120, 'postcodes': ['96161']}]
        with patch.object(snow, 'get_json', return_value={'results': rows}):
            for text in ('Truckee', '96161'):
                self.assertEqual(snow.resolve_location(snow.parse_location(text)), (39, -120))
            for text in ('Truc', '89501'):
                with self.assertRaises(ValueError):
                    snow.resolve_location(snow.parse_location(text))
            rows[0]['admin1'] = 'Nevada'
            with self.assertRaises(ValueError):
                snow.resolve_location(snow.parse_location('96161'))

    def test_invalid_geocoder(self):
        for data in (None, {'error': True}, {'results': [None]}, {'results': None}):
            with patch.object(snow, 'get_json', return_value=data), self.assertRaises(RuntimeError):
                snow.resolve_location(snow.parse_location('Truckee'))

    def test_catalog_and_distance(self):
        stations = snow.parse_stations(HTML)
        self.assertEqual(stations[1]['name'], 'Snow & Creek')
        self.assertEqual(snow.distance_miles(39, -120, stations[1]), 0)
        self.assertAlmostEqual(snow.distance_miles(38, -120, stations[1]), 69.0934, places=3)
        self.assertGreater(snow.distance_miles(39, -120, stations[0]), 80)

    def test_invalid_catalog_cannot_select_farther_station(self):
        for html in ('', HTML.replace('station_table', 'other'), HTML.replace('Latitude', 'Height'),
                     HTML.replace('<td>39</td>', '<td>nan</td>'), HTML.replace('<td>39</td>', '')):
            with self.assertRaises(RuntimeError):
                snow.parse_stations(html)

    def test_latest_valid_reading_with_zero_and_missing_sentinel(self):
        rows = [observation(value=0), observation(obsDate='2026-9-22 16:00', value=12),
                observation(obsDate='2026-9-22 18:00', value=-9999)]
        self.assertEqual(snow.current_depth(rows, 'ABC', NOW), 0)
        self.assertEqual(snow.current_depth(list(reversed(rows)), 'ABC', NOW), 0)

    def test_missing_stale_future_flagged_wrong_sensor_or_units(self):
        for changes in ({'value': None}, {'value': -1}, {'value': True}, {'value': float('nan')},
                        {'value': '12'}, {'obsDate': 'bad'}, {'obsDate': '2026-9-21 16:00'},
                        {'obsDate': '2026-9-23 16:00'}, {'units': 'MM'}, {'SENSOR_NUM': 3},
                        {'durCode': 'M'}, {'stationId': 'ZZZ'}, {'dataFlag': 'R'}):
            with self.subTest(changes=changes):
                self.assertIsNone(snow.current_depth([observation(**changes)], 'ABC', NOW))
        self.assertIsNone(snow.current_depth([], 'ABC', NOW))

    def test_conservative_pacific_offset_freshness(self):
        self.assertIsNone(snow.current_depth([observation(obsDate='2026-9-21 18:30')], 'ABC', NOW))
        self.assertIsNone(snow.current_depth([observation(obsDate='2026-9-22 19:00')], 'ABC', NOW))
        self.assertEqual(snow.current_depth([observation(obsDate='2026-9-22 18:00')], 'ABC', NOW), 12)
        winter = datetime(2026, 1, 2, 2, tzinfo=timezone.utc)
        self.assertEqual(snow.current_depth([observation(obsDate='2026-1-1 17:00')], 'ABC', winter), 12)

    def test_forecast_inches_zero_and_units(self):
        self.assertAlmostEqual(snow.snowfall_24h(forecast(), NOW), 4)
        self.assertEqual(snow.snowfall_24h(forecast(0), NOW), 0)
        for unit, value in [('wmoUnit:cm', 2.54), ('wmoUnit:m', .0254), ('wmoUnit:in', 1)]:
            data = forecast(value)
            data['properties']['snowfallAmount']['uom'] = unit
            self.assertAlmostEqual(snow.snowfall_24h(data, NOW), 4)

    def test_rolling_24h_prorates_boundary_bins(self):
        data = forecast()
        values = data['properties']['snowfallAmount']['values']
        values[:] = [{'validTime': (NOW+timedelta(hours=i)).isoformat()+'/PT6H', 'value': 25.4}
                     for i in (-2, 4, 10, 16, 22)]
        values[0]['value'] = 50.8
        self.assertAlmostEqual(snow.snowfall_24h(data, NOW), 4+4/6)

    def test_duration_and_explicit_end_support(self):
        for duration in ('P1D', 'PT24H', 'PT1440M', 'PT86400S', 'P0DT24H', (NOW+timedelta(days=1)).isoformat()):
            self.assertEqual(snow.interval(NOW.isoformat()+'/'+duration), (NOW, NOW+timedelta(days=1)))
        for duration in ('P', 'PT', 'PT0H', 'P1M', '-PT1H'):
            with self.assertRaises(ValueError):
                snow.interval(NOW.isoformat()+'/'+duration)

    def test_incomplete_overlapping_null_or_stale_forecast_is_unavailable(self):
        cases = [None, {}, forecast(None), forecast(-1), forecast(float('nan')), forecast(True),
                 forecast(updateTime=(NOW-timedelta(days=2)).isoformat()),
                 forecast(updateTime=(NOW+timedelta(hours=2)).isoformat())]
        for edit in ('gap', 'overlap', 'empty', 'badunit', 'badtime'):
            data = forecast()
            layer = data['properties']['snowfallAmount']
            if edit == 'gap': layer['values'].pop(1)
            if edit == 'overlap': layer['values'].append(deepcopy(layer['values'][0]))
            if edit == 'empty': layer['values'] = []
            if edit == 'badunit': layer['uom'] = 'inches-ish'
            if edit == 'badtime': layer['values'][0]['validTime'] = 'bad'
            cases.append(data)
        for data in cases:
            with self.subTest(data=data):
                self.assertIsNone(snow.snowfall_24h(data, NOW))

    def test_exact_reply_and_forecast_at_user_point(self):
        with patch.object(snow, 'get_text', return_value=HTML), \
                patch.object(snow, 'get_json', side_effect=[POINT, [observation()], forecast()]) as get:
            self.assertEqual(snow.lookup('39, -120', NOW),
                'Snowpack: Current: 12in | Next 24h: 4in | Station: Snow & Creek 0.0mi.')
            self.assertEqual(get.call_args_list[0].args[0], 'https://api.weather.gov/points/39.0000,-120.0000')
            self.assertEqual(get.call_args_list[1].args[1]['Stations'], 'ABC')
            self.assertEqual(get.call_args_list[-1].args[0], POINT['properties']['forecastGridData'])

    def test_partial_outages_keep_other_value_and_nearest_station(self):
        for depth, prediction, expected in [([], forecast(), 'Current: unavailable | Next 24h: 4in'),
              ([observation()], RuntimeError('offline'), 'Current: 12in | Next 24h: unavailable'),
              (RuntimeError('offline'), forecast(), 'Current: unavailable | Next 24h: 4in')]:
            with patch.object(snow, 'get_text', return_value=HTML), \
                    patch.object(snow, 'get_json', side_effect=[POINT, depth, prediction]):
                result = snow.lookup('39 -120', NOW)
                self.assertIn(expected, result)
                self.assertIn('Snow & Creek 0.0mi.', result)

    def test_california_coverage_and_grid_url_validation(self):
        for county, grid in [('https://api.weather.gov/zones/county/NVC031', POINT['properties']['forecastGridData']),
                             ('', ''), (POINT['properties']['county'], 'https://example.com/data')]:
            with patch.object(snow, 'get_json', return_value={'properties': {'county': county, 'forecastGridData': grid}}), \
                    self.assertRaises((ValueError, RuntimeError)):
                snow.lookup('39 -120', NOW)

    def test_inch_formatting(self):
        for value, expected in [(0, '0in'), (12, '12in'), (12.25, '12.2in'), (.01, '<0.1in'), (None, 'unavailable')]:
            self.assertEqual(snow.inches(value), expected)

    def test_http_contract_and_cli_failure(self):
        with patch.object(snow, 'urlopen') as open_url:
            open_url.return_value.__enter__.return_value = io.BytesIO(b'[]')
            self.assertEqual(snow.get_json(snow.OBS_URL, {'Stations': 'ABC'}), [])
            self.assertIn('Stations=ABC', open_url.call_args.args[0].full_url)
            self.assertEqual(open_url.call_args.kwargs['timeout'], 10)
        with patch.object(snow, 'urlopen', side_effect=URLError('offline')), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(snow.main(['!snowpack', '39, -120']), 0)
            self.assertIn('unavailable', output.getvalue())
            self.assertNotIn('0in', output.getvalue())

    def test_config_matching_and_usage(self):
        cfg = json.loads((ROOT/'config.json').read_text())['responder']
        responder.validate_config(cfg, ROOT)
        for location in ('39, -120', '96161', 'Truckee', 'South Lake Tahoe CA'):
            self.assertEqual(responder.match_command('!snowpack '+location, cfg['commands']),
                             ('!snowpack', [location], None))
        self.assertIn('!snowpack', responder.match_command('!snowpack', cfg['commands'])[2])
        self.assertIsNone(responder.match_command('!snowpackx Truckee', cfg['commands']))

    def test_real_subprocess_and_same_channel_sender_prefix(self):
        cfg = json.loads((ROOT/'config.json').read_text())['responder']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('snowpack.py', 'uv_index.py'):
                shutil.copyfile(ROOT/'scripts'/name, root/name)
            (root/'fixture.py').write_text(
                'import snowpack as s\n'
                f's.get_text=lambda *a: {HTML!r}\n'
                f'replies=iter({[POINT, [observation()], forecast()]!r})\n'
                's.get_json=lambda *a: next(replies)\n'
                'lookup=s.lookup\n'
                f's.lookup=lambda text: lookup(text, s.datetime.fromisoformat({NOW.isoformat()!r}))\n'
                's.main()\n', encoding='utf-8')
            cfg['commands']['!snowpack']['script'] = 'fixture.py'
            db = sqlite3.connect(':memory:')
            self.addCleanup(db.close)
            send = AsyncMock()
            bot = responder.Responder(root, db, cfg, 3, 'Local Bot', send)
            self.assertTrue(bot.accept({'channel_idx': 3, 'txt_type': 0,
                'sender_timestamp': int(time.time()), 'text': 'Alice: !snowpack 39, -120'}))
            asyncio.run(bot.process_one())
            send.assert_awaited_once_with(3,
                '@Alice Snowpack: Current: 12in | Next 24h: 4in | Station: Snow & Creek 0.0mi.')
            self.assertEqual(db.execute('SELECT state FROM bot_requests').fetchone()[0], 'sent')


if __name__ == '__main__':
    unittest.main()
