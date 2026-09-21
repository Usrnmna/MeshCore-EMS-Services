"""Offline UV parsing, API contract, and command integration tests."""
import asyncio
import io
import json
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch

import responder
from scripts import uv_index as uv

ROOT = Path(__file__).resolve().parent

class UVTests(unittest.TestCase):
    def test_locations(self):
        cases = {
            '38.58, -121.49': ('coordinates', (38.58, -121.49), None),
            '-38.58 -121.49': ('coordinates', (-38.58, -121.49), None),
            '95814': ('zip', '95814', None),
            '02108-1234': ('zip', '02108', None),
            'Sacramento': ('city', 'Sacramento', 'California'),
            'Reno NV': ('city', 'Reno', 'Nevada'),
            'Reno, Nevada': ('city', 'Reno', 'Nevada'),
            'Albany new york': ('city', 'Albany', 'New York'),
            'Virginia Beach VA': ('city', 'Virginia Beach', 'Virginia'),
            'Nevada City': ('city', 'Nevada City', 'California'),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(uv.parse_location(text), expected)

    def test_invalid_inputs(self):
        for text in ('', '91 0', '0 -181', 'nan 1', 'inf 2', '1,,2', '--help', '0 0; reboot', '1234'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                uv.parse_location(text)

    def test_risk_boundaries(self):
        for value, expected in ((0, 'Low'), (2.9, 'Low'), (3, 'Moderate'),
                                (5.9, 'Moderate'), (6, 'High'), (7.9, 'High'),
                                (8, 'Very-High'), (10.9, 'Very-High'), (11, 'Extreme')):
            self.assertEqual(uv.risk_level(value), expected)
        for value in (-1, None, True, '3', float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                uv.risk_level(value)

    def test_current_not_forecast(self):
        with patch.object(uv, 'get_json', return_value={
                'ok': True, 'now': {'uvi': 6.5}, 'forecast': [{'uvi': 11}]}):
            self.assertEqual(uv.lookup('38 -121'), 'UV Index: 6.5 High')

    def test_state_filter_and_zip(self):
        result = {'name': 'Reno', 'admin1': 'Nevada', 'country_code': 'US',
                  'latitude': 39.5, 'longitude': -119.8, 'postcodes': ['89501']}
        with patch.object(uv, 'get_json', return_value={'results': [result]}) as get:
            self.assertEqual(uv.resolve_location(uv.parse_location('Reno NV')), (39.5, -119.8))
            self.assertEqual(get.call_args.args[1]['name'], 'Reno, Nevada')
            self.assertEqual(uv.resolve_location(uv.parse_location('89501')), (39.5, -119.8))
            with self.assertRaises(ValueError):
                uv.resolve_location(uv.parse_location('Reno'))

    def test_missing_reading_and_errors(self):
        for response in ({'ok': False}, {'ok': True}, {'ok': True, 'now': {'uvi': None}}):
            with patch.object(uv, 'get_json', return_value=response), patch('sys.stdout', new_callable=io.StringIO) as out:
                uv.main(['38', '-121'])
                self.assertNotIn('UV Index: 0', out.getvalue())
                self.assertTrue(out.getvalue().strip())

    def test_config_and_matching(self):
        cfg = json.loads((ROOT / 'config.json').read_text())['responder']
        responder.validate_config(cfg, ROOT)
        for text in ('!uv Sacramento', '!uv 95814', '!uv 38, -121', '!uv Reno NV'):
            command, args, error = responder.match_command(text, cfg['commands'])
            self.assertEqual(command, '!uv')
            self.assertEqual(args, [text[4:]])
            self.assertIsNone(error)
        self.assertIsNotNone(responder.match_command('!uv', cfg['commands'])[2])
        self.assertIsNone(responder.match_command('!uvx Sacramento', cfg['commands']))

    def test_subprocess_reply(self):
        cfg = json.loads((ROOT / 'config.json').read_text())['responder']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(ROOT / 'scripts/uv_index.py', root / 'uv_index.py')
            (root / 'fixture.py').write_text("import uv_index as uv\nuv.get_json=lambda *args: {'ok': True, 'now': {'uvi': 8.2}}\nuv.main()\n")
            request = {'arguments': ['38, -121'], 'sender': 'Alice', 'channel_name': '#autatestbot',
                       'channel_index': 2, 'id': 'test', 'phrase': '!uv 38, -121'}
            reply, detail = asyncio.run(responder.run_script(root, {'script': 'fixture.py'}, request, cfg))
            self.assertEqual(responder.reply_parts('Alice', reply), ['@Alice UV Index: 8.2 Very-High'])
            self.assertEqual(detail, '')

if __name__ == '__main__':
    unittest.main()
