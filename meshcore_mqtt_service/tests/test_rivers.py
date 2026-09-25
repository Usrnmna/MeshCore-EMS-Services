"""Offline river-command tests with synthetic CDEC and NOAA responses."""
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import responder
import service


def config():
    return json.loads((service.ROOT / 'config.json').read_text())['responder']


def packet(phrase):
    return {'channel_idx': 2, 'txt_type': 0, 'text': 'Alice: ' + phrase,
            'sender_timestamp': int(time.time())}


class RiversTests(unittest.IsolatedAsyncioTestCase):
    async def test_gps_formats_and_other_commands(self):
        cfg = config()
        for text in ['!rivers 39 -121', '!rivers 39,-121', '!rivers 39, -121']:
            request = responder.parse_message(packet(text), 2, 'Bot', cfg, time.time())
            self.assertEqual(request['command'], '!rivers')
            self.assertEqual(request['arguments'], ['39.0', '-121.0'])
            self.assertIsNone(request['input_error'])
        self.assertEqual(responder.match_command('!aqi 39 -121', cfg['commands'])[1], ['39.0', '-121.0'])
        self.assertEqual(responder.match_command('!traffic 80', cfg['commands'])[1], ['80'])

    async def test_invalid_coordinates_do_not_execute(self):
        for text in ['!rivers', '!rivers 39', '!rivers 91 0', '!rivers 0 -181',
                     '!rivers nan 0', '!rivers 39 -121; reboot', '!rivers 39 -121 --radius 999']:
            db = sqlite3.connect(':memory:')
            send = AsyncMock()
            bot = responder.Responder(service.ROOT, db, config(), 2, 'Bot', send)
            with patch.object(responder, 'run_script', new_callable=AsyncMock) as run:
                self.assertTrue(bot.accept(packet(text)))
                await bot.process_one()
                run.assert_not_awaited()
                self.assertEqual(send.await_args.args[0], 2)
                self.assertTrue(send.await_args.args[1].startswith('@Alice Use !rivers'))
            db.close()

    async def test_channel_and_command_remain_exact(self):
        cfg = config()
        for text in ['!riversx 39 -121', '!RIVERS 39 -121', '!status extra']:
            self.assertIsNone(responder.parse_message(packet(text), 2, 'Bot', cfg, time.time()))
        self.assertIsNone(responder.parse_message(packet('!rivers 39 -121'), 3, 'Bot', cfg, time.time()))

    async def fixture_reply(self, empty=False, failure=False, as_json=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copyfile(service.ROOT / 'scripts/nearby_river_stations.py', root / 'nearby_river_stations.py')
            source = '''import nearby_river_stations as r
REPORT = '<pre>: 500 PM PDT Thu Sep 17 2026\\n01PM 02PM 03PM 04PM 05PM\\nNEAR1 : Near River 10 / 20 : 1 / 2 / 3 / 4 / 5\\nNEAR2 : Other River / 41.3 : 1 / 2 / 3 / 4 / +\\nFAR01 : Far River 50 / 60 : 1 / 2 / 3 / 4 / 5</pre>'
def get_text(url, timeout):
    if FAILURE:
        raise RuntimeError('fixture network failure')
    assert timeout == 15
    return REPORT
def get_json(url, params, timeout):
    # Proves the command's coordinates reached the actual program instead of defaults.
    assert params['bbox.ymin'] < 39 < params['bbox.ymax']
    assert params['bbox.xmin'] < -121 < params['bbox.xmax']
    return {'gauges': [] if EMPTY else [
        {'lid':'near1','latitude':39.01,'longitude':-121},
        {'lid':'near2','latitude':39.02,'longitude':-121},
        {'lid':'far01','latitude':40,'longitude':-121}]}
r._get_text=get_text
r._get_json=get_json
raise SystemExit(r.main())
'''
            (root / 'fixture.py').write_text(f'EMPTY={empty!r}\nFAILURE={failure!r}\n' + source)
            cfg = config()
            cfg['commands']['!rivers']['script'] = 'fixture.py'
            if as_json:
                cfg['commands']['!rivers']['args'].remove('--mesh-text')
                request = responder.parse_message(packet('!rivers 39 -121'), 2, 'Bot', cfg, time.time())
                output, detail = await responder.run_script(root, cfg['commands']['!rivers'], request, cfg)
                return json.loads(output)
            db = sqlite3.connect(':memory:')
            send = AsyncMock()
            bot = responder.Responder(root, db, cfg, 2, 'Bot', send)
            self.assertTrue(bot.accept(packet('!rivers 39 -121')))
            await bot.process_one()
            self.assertTrue(send.await_args_list)
            for call in send.await_args_list:
                self.assertEqual(call.args[0], 2)
                self.assertTrue(call.args[1].startswith('@Alice '))
                self.assertLessEqual(len(call.args[1].encode()), 150)
            result = ''.join(call.args[1][len('@Alice '):] for call in send.await_args_list)
            db.close()
            return result

    async def test_real_script_tagged_nearest_stations_and_missing_readings(self):
        text = await self.fixture_reply()
        self.assertIn('NEAR1 Near River', text)
        self.assertIn('stage 5 ft at 05PM; AS 10 ft, FS 20 ft', text)
        self.assertIn('stage N/A at 05PM; AS N/A, FS 41.3 ft', text)
        self.assertIn('500 PM PDT Thu Sep 17 2026', text)
        self.assertNotIn('Far River', text)
        self.assertLess(text.index('NEAR1'), text.index('NEAR2'))

    async def test_empty_result_is_explicit(self):
        self.assertEqual(await self.fixture_reply(empty=True), 'No matching river stations found within 15 mi.')

    async def test_failure_is_not_an_empty_result(self):
        self.assertEqual(await self.fixture_reply(failure=True), 'River station lookup unavailable. Please try again later.')

    async def test_default_json_retains_original_rows_and_history(self):
        data = await self.fixture_reply(as_json=True)
        self.assertEqual([row['station_id'] for row in data], ['NEAR1', 'NEAR2'])
        self.assertIn('NEAR1 : Near River', data[0]['raw_report_line'])
        self.assertEqual(len(data[0]['river_stage_history']), 5)
        self.assertIsNone(data[1]['river_stage_feet'])
        self.assertIsNone(data[1]['action_stage_feet'])
        self.assertEqual(data[1]['minor_flood_stage_feet'], 41.3)


if __name__ == '__main__':
    unittest.main()
