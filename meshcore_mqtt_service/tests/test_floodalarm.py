"""Simulated-clock tests: no 20-minute waits, live network calls, or radio transmissions."""
import asyncio
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from flood_alarm import ACKNOWLEDGMENT, CHECK_INTERVAL, MAX_AGE, FloodAlarms
import responder
import flood_alarm
from scripts import flood_warn

ROOT = Path(__file__).resolve().parents[1]


def status(*events):
    return {'events': list(events), 'text': flood_warn.format_status('Sacramento', events)}


class AlarmTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 1000000.0
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.read = AsyncMock(return_value=status())
        self.notify = AsyncMock()
        self.alarms = FloodAlarms(self.db, '#test', self.read, self.notify, lambda: self.now)
        self.sequence = 0

    def remember(self, command='!floodalarm', location='Sacramento', sender='Alice', acknowledge=True):
        self.sequence += 1
        request = {'id': str(self.sequence), 'sender': sender, 'arguments': [location],
                   'command': command, 'sender_timestamp': int(self.now)}
        self.assertEqual(self.alarms.remember(request, self.now), command == '!floodalarm')
        if acknowledge and command == '!floodalarm':
            self.alarms.acknowledge(request)
        return request

    async def test_warn_does_not_create_alarm_record(self):
        self.remember('!floodwarn')
        self.assertIsNone(self.alarms.row('Alice'))
        self.assertFalse(await self.alarms.check_one())
        self.read.assert_not_awaited()

    async def test_baseline_waits_for_ack_and_is_silent(self):
        request = self.remember(acknowledge=False)
        self.assertFalse(await self.alarms.check_one())
        self.alarms.acknowledge(request)
        self.assertTrue(await self.alarms.check_one())
        self.read.assert_awaited_once_with('Sacramento')
        self.notify.assert_not_awaited()
        self.assertEqual(self.alarms.row('Alice')['next_check'], self.now + CHECK_INTERVAL)

    async def test_twenty_minute_schedule_changes_and_clear(self):
        self.remember()
        await self.alarms.check_one()
        self.now += CHECK_INTERVAL - 1
        self.assertFalse(await self.alarms.check_one())
        self.now += 1
        self.read.return_value = status('Flood Watch')
        await self.alarms.check_one()
        self.assertEqual(self.notify.await_args.args[1], status('Flood Watch')['text'])
        self.now += CHECK_INTERVAL
        await self.alarms.check_one()  # Unchanged: quiet.
        self.assertEqual(self.notify.await_count, 1)
        self.now += CHECK_INTERVAL
        self.read.return_value = status()
        await self.alarms.check_one()
        self.assertEqual(self.notify.await_count, 2)
        self.assertEqual(self.notify.await_args.args[1], 'no flooding events declared for Sacramento')

    async def test_order_and_duplicates_are_not_changes(self):
        self.remember()
        self.read.return_value = status('Flood Warning', 'Flood Watch')
        await self.alarms.check_one()
        self.now += CHECK_INTERVAL
        self.read.return_value = status('Flood Watch', 'Flood Warning', 'Flood Watch')
        await self.alarms.check_one()
        self.notify.assert_not_awaited()

    async def test_four_hour_hard_cutoff_and_warn_cannot_restart_expired_alarm(self):
        self.remember()
        await self.alarms.check_one()
        self.now += MAX_AGE
        self.assertFalse(await self.alarms.check_one())
        self.assertFalse(self.alarms.row('Alice')['enabled'])
        self.remember('!floodwarn')
        self.assertFalse(await self.alarms.check_one())
        self.remember()
        self.assertTrue(await self.alarms.check_one())

    async def test_alarm_renews_active_alarm_and_changes_location_without_false_change(self):
        self.remember()
        await self.alarms.check_one()
        self.now += MAX_AGE - 1
        self.remember('!floodalarm', 'Reno NV')
        row = self.alarms.row('Alice')
        self.assertEqual(row['last_heard'], self.now)
        self.assertEqual(row['location'], 'Reno NV')
        self.assertIsNone(row['baseline'])
        self.read.return_value = status('Flood Watch')
        await self.alarms.check_one()
        self.notify.assert_not_awaited()
        self.read.assert_awaited_with('Reno NV')
        self.now += MAX_AGE
        self.assertFalse(await self.alarms.check_one())

    async def test_repeat_alarm_renews_one_row(self):
        self.remember()
        await self.alarms.check_one()
        self.now += 60
        self.remember()
        self.assertEqual(self.alarms.row('Alice')['last_heard'], self.now)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM flood_subscriptions').fetchone()[0], 1)
        self.assertEqual(self.alarms.row('Alice')['baseline'], '[]')
        self.assertFalse(await self.alarms.check_one())

    async def test_warn_leaves_running_alarm_and_deadline_unchanged(self):
        self.remember()
        await self.alarms.check_one()
        before = self.alarms.row('Alice')
        self.now += MAX_AGE - 1
        self.remember('!floodwarn', 'Reno NV')
        self.assertEqual(self.alarms.row('Alice'), before)
        self.now += 1
        self.assertFalse(await self.alarms.check_one())
        self.assertFalse(self.alarms.row('Alice')['enabled'])

    async def test_outage_keeps_good_baseline_and_reports_once_then_recovers(self):
        self.remember()
        self.read.return_value = status('Flood Warning')
        await self.alarms.check_one()
        self.read.side_effect = RuntimeError('Unavailable')
        for _ in range(2):
            self.now += CHECK_INTERVAL
            await self.alarms.check_one()
        self.assertEqual(self.notify.await_count, 1)
        self.assertEqual(json.loads(self.alarms.row('Alice')['baseline']), ['Flood Warning'])
        self.assertNotIn('no flooding', self.notify.await_args.args[1])
        self.now += CHECK_INTERVAL
        self.read.side_effect = None
        self.read.return_value = status()
        await self.alarms.check_one()
        self.assertEqual(self.notify.await_count, 2)
        self.assertIsNone(self.alarms.row('Alice')['error'])

    async def test_initial_failure_is_not_a_clear_baseline(self):
        self.remember()
        self.read.side_effect = RuntimeError('Unknown location')
        await self.alarms.check_one()
        self.assertIsNone(self.alarms.row('Alice')['baseline'])
        self.now += CHECK_INTERVAL
        self.read.side_effect = None
        self.read.return_value = status('Flood Warning')
        await self.alarms.check_one()
        self.assertEqual(self.notify.await_count, 1)  # Error only; first valid reading is baseline.

    async def test_inflight_result_discarded_on_expiry_or_new_location(self):
        for change_location in (False, True):
            self.remember()
            async def delayed(_):
                if change_location:
                    self.now += 1
                    self.remember(location='Reno NV')
                else:
                    self.now += MAX_AGE
                return status('Flood Watch')
            self.read.side_effect = delayed
            await self.alarms.check_one()
            self.assertIsNone(self.alarms.row('Alice')['baseline'])
            self.notify.assert_not_awaited()

    async def test_multiple_senders_and_channels_are_independent(self):
        self.remember(sender='Alice')
        self.remember(location='Reno NV', sender='Bob')
        other = FloodAlarms(self.db, '#other', self.read, self.notify, lambda: self.now)
        self.assertIsNone(other.row('Alice'))
        await self.alarms.check_one()
        await self.alarms.check_one()
        self.assertEqual([call.args[0] for call in self.read.await_args_list], ['Sacramento', 'Reno NV'])

    async def test_restart_preserves_expiry_baseline_and_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bridge.sqlite3'
            db = sqlite3.connect(path)
            original = FloodAlarms(db, '#test', self.read, self.notify, lambda: self.now)
            request = {'id': 'r', 'sender': 'Alice', 'arguments': ['Sacramento'],
                       'command': '!floodalarm', 'sender_timestamp': int(self.now)}
            original.remember(request, self.now)
            original.acknowledge(request)
            await original.check_one()
            db.close()
            db = sqlite3.connect(path)
            try:
                restarted = FloodAlarms(db, '#test', self.read, self.notify, lambda: self.now)
                self.assertFalse(await restarted.check_one())
                self.now += CHECK_INTERVAL
                self.read.return_value = status('Flood Watch')
                await restarted.check_one()
                self.notify.assert_awaited_once()
                self.now += MAX_AGE
                self.assertFalse(await restarted.check_one())
            finally:
                db.close()

    async def test_older_radio_call_does_not_replace_latest_location(self):
        old = self.remember()
        self.now += 60
        self.remember(location='Reno NV')
        self.assertFalse(self.alarms.remember(old, self.now))
        self.assertEqual(self.alarms.row('Alice')['location'], 'Reno NV')


class AlarmIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / 'config.json').read_text())['responder']
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.send = AsyncMock()
        self.bot = responder.Responder(ROOT, self.db, self.cfg, 3, 'Bot', self.send)

    def packet(self, phrase='!floodalarm Sacramento', sender='Alice'):
        return {'channel_idx': 3, 'txt_type': 0, 'sender_timestamp': int(time.time()),
                'text': f'{sender}: {phrase}'}

    async def test_exact_ack_without_weather_lookup_and_input_forms(self):
        responder.validate_config(self.cfg, ROOT)
        for location in ('38, -121', '95814', 'Sacramento', 'Reno NV', 'Reno Nevada'):
            matched = responder.match_command('!floodalarm ' + location, self.cfg['commands'])
            self.assertEqual(matched, ('!floodalarm', [location], None))
        with patch.object(responder, 'run_script', new_callable=AsyncMock) as run:
            self.assertTrue(self.bot.accept(self.packet()))
            await self.bot.process_one()
            run.assert_not_awaited()
        self.send.assert_awaited_once_with(3, '@Alice ' + ACKNOWLEDGMENT)
        self.assertTrue(self.bot.alarms.row('Alice')['ready'])

    async def test_only_alarm_command_replaces_location_and_resets_timer(self):
        """Exercise received commands, including ordinary !floodwarn replies, through the responder."""
        now = time.time()
        with patch.object(responder.time, 'time', return_value=now) as clock, \
                patch.object(responder, 'run_script', return_value=('One-shot flood reply', '')):
            self.assertTrue(self.bot.accept(self.packet('!floodwarn Sacramento')))
            await self.bot.process_one()
            self.assertIsNone(self.bot.alarms.row('Alice'))

            clock.return_value = now + 60
            self.assertTrue(self.bot.accept(self.packet('!floodalarm Sacramento')))
            await self.bot.process_one()
            original = self.bot.alarms.row('Alice')

            clock.return_value = now + 120
            self.assertTrue(self.bot.accept(self.packet('!floodwarn Reno NV')))
            await self.bot.process_one()
            self.assertEqual(self.bot.alarms.row('Alice'), original)
            self.send.assert_awaited_with(3, '@Alice One-shot flood reply')

            clock.return_value = now + 180
            self.assertTrue(self.bot.accept(self.packet('!floodalarm Reno NV')))
            await self.bot.process_one()
            updated = self.bot.alarms.row('Alice')
            self.assertEqual(updated['location'], 'Reno NV')
            self.assertEqual(updated['last_heard'], now + 180)
            self.assertTrue(updated['ready'])
            self.assertTrue(updated['enabled'])
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM flood_subscriptions').fetchone()[0], 1)
            self.send.assert_awaited_with(3, '@Alice ' + ACKNOWLEDGMENT)

    async def test_invalid_duplicate_wrong_channel_and_cooldown_do_not_renew(self):
        p = self.packet()
        self.bot.accept(p)
        before = self.bot.alarms.row('Alice')
        self.assertFalse(self.bot.accept(p))
        self.assertFalse(self.bot.accept(self.packet('!floodalarm Reno NV')))
        self.assertFalse(self.bot.accept({**self.packet(sender='Bob'), 'channel_idx': 4}))
        self.bot.accept(self.packet('!floodalarm 999 999', sender='Bob'))
        self.assertEqual(self.bot.alarms.row('Alice'), before)
        self.assertIsNone(self.bot.alarms.row('Bob'))
        await self.bot.process_one()
        await self.bot.process_one()
        self.assertNotIn(ACKNOWLEDGMENT, self.send.await_args.args[1])

    async def test_ack_worker_does_not_wait_for_slow_ordinary_lookup(self):
        started = asyncio.Event()
        release = asyncio.Event()
        async def slow(*_):
            started.set()
            await release.wait()
            return ('result', '')
        with patch.object(responder, 'run_script', side_effect=slow):
            self.bot.accept(self.packet('!uv Sacramento', sender='Bob'))
            work = asyncio.create_task(self.bot.process_one(alarm_only=False))
            try:
                await asyncio.wait_for(started.wait(), 1)
                self.bot.accept(self.packet())
                await asyncio.wait_for(self.bot.process_one(alarm_only=True), 1)
                self.send.assert_awaited_once_with(3, '@Alice ' + ACKNOWLEDGMENT)
            finally:
                release.set()
                await work

    async def test_guard_drops_expired_message_after_radio_wait(self):
        self.bot.accept(self.packet())
        await self.bot.process_one()
        reading = self.bot.alarms.row('Alice')
        sent = []
        async def delayed_send(channel, text, *, guard):
            self.bot.alarms.clock = lambda: reading['last_heard'] + MAX_AGE
            if guard():
                sent.append(text)
        self.bot.send = delayed_send
        await self.bot.send_flood_change(reading, 'Flood Watch')
        self.assertEqual(sent, [])

    async def test_structured_response_validation_and_no_false_clears(self):
        for output in ('not JSON', '{}', '{"error":"Offline"}', '{"events":null}', '{"events":["Unknown"]}'):
            with patch.object(responder, 'run_script', return_value=(output, '')), self.assertRaises(RuntimeError):
                await self.bot.read_flood_status('Sacramento')
        with patch.object(responder, 'run_script', return_value=('{"events":[]}', '')) as run:
            self.assertEqual(await self.bot.read_flood_status('Sacramento'), status())
            self.assertEqual(run.call_args.args[1]['args'], ['--snapshot'])

    async def test_snapshot_cli_contract(self):
        with patch.object(flood_warn, 'snapshot', return_value=status('Flood Watch')), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            flood_warn.main(['--snapshot', 'Sacramento'])
            self.assertEqual(json.loads(output.getvalue())['events'], ['Flood Watch'])
        with patch.object(flood_warn, 'snapshot', side_effect=RuntimeError('Offline')), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            flood_warn.main(['--snapshot', 'Sacramento'])
            self.assertEqual(json.loads(output.getvalue()), {'error': 'Offline'})

    async def test_running_service_ack_baseline_change_and_clean_shutdown(self):
        received_change = asyncio.Event()
        order = []
        async def send(channel, text, **kwargs):
            order.append('ack' if ACKNOWLEDGMENT in text else 'change')
            if 'Flood Watch' in text:
                received_change.set()
        async def read(location):
            order.append('read')
            return status() if order.count('read') == 1 else status('Flood Watch')
        self.bot.send = send
        self.bot.alarms.read_status = read
        self.bot.accept(self.packet())
        with patch.object(flood_alarm, 'CHECK_INTERVAL', .02), patch.object(flood_alarm, 'POLL_SECONDS', .01):
            task = asyncio.create_task(self.bot.run())
            try:
                await asyncio.wait_for(received_change.wait(), 2)
                self.assertEqual(order[:4], ['ack', 'read', 'read', 'change'])
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertTrue(task.cancelled())

    async def test_real_snapshot_subprocess(self):
        from test_floodwarn import COVERAGE, alert, collection
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / 'scripts'
            scripts.mkdir()
            shutil.copyfile(ROOT / 'scripts/flood_warn.py', scripts / 'flood_data.py')
            shutil.copyfile(ROOT / 'scripts/uv_index.py', scripts / 'uv_index.py')
            fixtures = [COVERAGE, collection(alert('Flood Watch', effective='2000-01-01T00:00:00Z',
                                                    expires='2099-01-01T00:00:00Z'))]
            (scripts / 'flood_warn.py').write_text(
                'import flood_data as f\n' + f'responses=iter({fixtures!r})\n'
                'f.get_json=lambda *args: next(responses)\nf.main()\n', encoding='utf-8')
            self.bot.root = root
            result = await self.bot.read_flood_status('38 -121')
            self.assertEqual(result['events'], ['Flood Watch'])
            self.assertIn('🟦', result['text'])


if __name__ == '__main__':
    unittest.main()
