"""Offline AirNow command tests: no credentials or live API required."""
import asyncio
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import responder
import service


def config():
    return json.loads((service.ROOT / 'config.json').read_text())['responder']


def packet(text):
    return {'channel_idx': 2, 'txt_type': 0, 'text': 'Alice: ' + text,
            'sender_timestamp': int(time.time())}


class AQITests(unittest.IsolatedAsyncioTestCase):
    async def test_coordinates_accept_spaces_or_comma(self):
        for message in ['!aqi 37.7749 -122.4194', '!aqi 37.7749, -122.4194', '!aqi 37.7749,-122.4194']:
            request = responder.parse_message(packet(message), 2, 'Bot', config(), time.time())
            self.assertEqual(request['command'], '!aqi')
            self.assertEqual(request['arguments'], ['37.7749', '-122.4194'])
            self.assertIsNone(request['input_error'])

    async def test_invalid_coordinates_and_injection_do_not_run(self):
        for message in ['!aqi', '!aqi 91 0', '!aqi 0 -181', '!aqi nan 1', '!aqi inf 2',
                        '!aqi 1 2 3', '!aqi 0 0; reboot', '!aqi --help', '!aqi 1,,2']:
            with self.subTest(message=message):
                db = sqlite3.connect(':memory:')
                send = AsyncMock()
                bot = responder.Responder(service.ROOT, db, config(), 2, 'Bot', send)
                with patch.object(responder, 'run_script', new_callable=AsyncMock) as run:
                    self.assertTrue(bot.accept(packet(message)))
                    await bot.process_one()
                    run.assert_not_awaited()
                    self.assertTrue(send.await_args.args[1].startswith('@Alice Use !aqi'))
                    self.assertEqual(send.await_args.args[0], 2)
                db.close()

    async def test_other_commands_stay_exact_and_channel_specific(self):
        cfg = config()
        for phrase in ['!aqix 1 2', '!AQI 1 2', '!status extra']:
            self.assertIsNone(responder.parse_message(packet(phrase), 2, 'Bot', cfg, time.time()))
        self.assertIsNone(responder.parse_message(packet('!aqi 1 2'), 1, 'Bot', cfg, time.time()))
        self.assertEqual(responder.match_command('!status', cfg['commands']), ('!status', [], None))

    async def test_real_airnow_program_subprocess_and_tagged_reply_with_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(service.ROOT / 'scripts/airnow_aqi.py', root / 'airnow_aqi.py')
            fixture = [{
                'Parameter': 'PM2.5', 'Latitude': 37.775, 'Longitude': -122.419,
                'AQI': 42, 'RawConcentration': 7.2, 'Unit': 'UG/M3',
                'Category': 1, 'SiteName': 'Fixture Station', 'FullAQSCode': 'TEST', 'UTC': '2026-09-17T10:00:00'
            }]
            (root / 'fixture.py').write_text(
                "import airnow_aqi as a\na.API_KEY='synthetic-test-key'\n"
                + 'a.api_get=lambda bbox: ' + repr(fixture) + '\nraise SystemExit(a.main())\n')
            cfg = copy.deepcopy(config())
            cfg['commands']['!aqi']['script'] = 'fixture.py'
            db = sqlite3.connect(':memory:')
            send = AsyncMock()
            bot = responder.Responder(root, db, cfg, 2, 'Bot', send)
            self.assertTrue(bot.accept(packet('!aqi 37.7749, -122.4194')))
            await bot.process_one()
            replies = [call.args[1] for call in send.await_args_list]
            self.assertTrue(replies)
            self.assertTrue(all(call.args[0] == 2 for call in send.await_args_list))
            self.assertTrue(all(text.startswith('@Alice ') for text in replies))
            combined = ''.join(text[len('@Alice '):] for text in replies)
            self.assertIn('AQI: 42', combined)
            self.assertIn('Fixture Station', combined)
            self.assertIn('Data status: Preliminary', combined)
            context = json.loads(db.execute('SELECT context FROM bot_requests').fetchone()[0])
            self.assertEqual(context['arguments'], ['37.7749', '-122.4194'])
            db.close()

    async def test_missing_key_returns_safe_useful_error(self):
        cfg = config()
        request = responder.parse_message(packet('!aqi 0 0'), 2, 'Bot', cfg, time.time())
        with patch.dict('os.environ', {'AIRNOW_API_KEY': ''}):
            reply, detail = await responder.run_script(service.ROOT, cfg['commands']['!aqi'], request, cfg)
        self.assertIn('AIRNOW_API_KEY', reply)
        self.assertIn('exit=1', detail)

    async def test_http_error_does_not_expose_response_or_key(self):
        from urllib.error import HTTPError
        path = service.ROOT / 'scripts/airnow_aqi.py'
        spec = importlib.util.spec_from_file_location('aqi_under_test', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        error = HTTPError('https://example.invalid/?API_KEY=secret-value', 403, 'denied', {}, io.BytesIO(b'secret-value'))
        with patch.object(module, 'urlopen', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                module.api_get('0,0,1,1')
            self.assertEqual(str(caught.exception), 'AirNow API error 403.')


if __name__ == '__main__':
    unittest.main()
