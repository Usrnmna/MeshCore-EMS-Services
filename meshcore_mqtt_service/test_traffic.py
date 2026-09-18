"""Offline traffic-command integration tests; Caltrans HTTP responses are fixtures."""
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


class TrafficTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_routes_become_one_numeric_argument(self):
        for phrase, expected in [('!traffic 80', '80'), ('!traffic 005', '5'),
                                 ('!traffic 1', '1'), ('!traffic 999', '999')]:
            request = responder.parse_message(packet(phrase), 2, 'Bot', config(), time.time())
            self.assertEqual(request['command'], '!traffic')
            self.assertEqual(request['arguments'], [expected])
            self.assertIsNone(request['input_error'])

    async def test_bad_routes_reply_with_usage_without_running_script(self):
        for phrase in ['!traffic', '!traffic 0', '!traffic -1', '!traffic 1000', '!traffic I-80',
                       '!traffic 80 5', '!traffic 80; reboot', '!traffic --help', '!traffic 8.0']:
            with self.subTest(phrase=phrase):
                db = sqlite3.connect(':memory:')
                send = AsyncMock()
                bot = responder.Responder(service.ROOT, db, config(), 2, 'Bot', send)
                with patch.object(responder, 'run_script', new_callable=AsyncMock) as run:
                    self.assertTrue(bot.accept(packet(phrase)))
                    await bot.process_one()
                    run.assert_not_awaited()
                    self.assertEqual(send.await_args.args[0], 2)
                    self.assertTrue(send.await_args.args[1].startswith('@Alice Use !traffic'))
                db.close()

    async def test_command_and_channel_matching_remain_strict(self):
        cfg = config()
        for phrase in ['!trafficx 80', '!TRAFFIC 80', '!status extra']:
            self.assertIsNone(responder.parse_message(packet(phrase), 2, 'Bot', cfg, time.time()))
        self.assertIsNone(responder.parse_message(packet('!traffic 80'), 1, 'Bot', cfg, time.time()))
        self.assertEqual(responder.match_command('!aqi 37,-122', cfg['commands'])[1], ['37.0', '-122.0'])

    async def fixture_reply(self, body, network_error=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copyfile(service.ROOT / 'scripts/highway_info.py', root / 'highway_info.py')
            fixture = '''import io
from email.message import Message
from urllib.error import URLError
import highway_info as h
class Response(io.BytesIO):
    headers = Message()
def fetch(request, timeout):
    assert request.full_url.endswith('?roadnumber=80'), request.full_url
    if NETWORK_ERROR:
        raise URLError('fixture network failure')
    return Response(PAGE.encode('utf-8'))
h.urlopen = fetch
raise SystemExit(h.main())
'''
            page = '<html>This highway information is the latest reported<br>I 80<br>' + body + '<hr></html>'
            (root / 'fixture.py').write_text('PAGE=' + repr(page) + '\nNETWORK_ERROR=' + repr(network_error) + '\n' + fixture)
            cfg = config()
            cfg['commands']['!traffic']['script'] = 'fixture.py'
            db = sqlite3.connect(':memory:')
            send = AsyncMock()
            bot = responder.Responder(root, db, cfg, 2, 'Bot', send)
            self.assertTrue(bot.accept(packet('!traffic 80')))
            await bot.process_one()
            self.assertTrue(send.await_args_list)
            for call in send.await_args_list:
                self.assertEqual(call.args[0], 2)
                self.assertTrue(call.args[1].startswith('@Alice '))
                self.assertLessEqual(len(call.args[1].encode()), 150)
            result = ''.join(call.args[1][len('@Alice '):] for call in send.await_args_list)
            saved = json.loads(db.execute('SELECT context FROM bot_requests').fetchone()[0])
            self.assertEqual(saved['arguments'], ['80'])
            db.close()
            return result

    async def test_real_highway_script_clear_report_is_exact(self):
        reply = await self.fixture_reply('[Northern California]<br>No traffic restrictions are reported for this area.<br>')
        self.assertEqual(reply, 'No Traffic Restrictions Reported')

    async def test_real_highway_script_preserves_active_restrictions(self):
        reply = await self.fixture_reply(
            '[Northern California]<br>No traffic restrictions are reported for this area.<br>'
            '[Southern California]<br>The westbound connector is closed for construction Monday from 2300 hrs to 0600 hrs.<br>')
        self.assertIn('WB conn. is clsd for constr. Mon from 11P to 6A', reply)
        self.assertNotIn('No Traffic Restrictions Reported', reply)

    async def test_network_failure_is_not_reported_as_clear(self):
        reply = await self.fixture_reply('', network_error=True)
        self.assertEqual(reply, 'Caltrans traffic lookup unavailable. Please try again later.')


if __name__ == '__main__':
    unittest.main()
