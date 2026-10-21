"""Triggered subscription responses using real poll/queue callbacks and offline feeds."""
import copy
import os
import re
from pathlib import Path
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from responder import reply_parts
from flood_alarm import FloodAlarms
from wildfire_service import WildfireAlarms
from landslide_service import LandslideAlarms
from test_floodalarm import NOW, sample
from test_flood_notifications import hazard
from test_wildfire import snapshot as fire_snapshot, GUID
from test_landslide import snapshot as slide_snapshot, feature


async def triggered_examples():
    """Enroll, acknowledge, mutate source snapshots, and capture actual notifications.

    Returned records also generate documentation examples. No network or radio
    transport is used; each service owns its normal baseline and queue processing.
    """
    examples = []
    for kind in ('flood', 'fire', 'slide'):
        now = NOW
        event = 'Initial'
        sent = []
        flood_events, flood_state, slide_records = {}, 'no_flooding', []
        fire_data = fire_snapshot()

        async def read(*args):
            if kind == 'flood':
                return sample(now, events=copy.deepcopy(flood_events), state=flood_state)
            if kind == 'fire':
                return copy.deepcopy(fire_data)
            return slide_snapshot(now, copy.deepcopy(slide_records))

        async def notify(reading, text):
            sent.append((event, text))

        with closing(sqlite3.connect(':memory:')) as db:
            cls = {'flood': FloodAlarms, 'fire': WildfireAlarms, 'slide': LandslideAlarms}[kind]
            kwargs = {'monotonic': lambda: now} if kind == 'flood' else {}
            alarms = cls(db, 'default', 'fixture', {}, read, notify, lambda: True,
                         clock=lambda: now, **kwargs)
            argument = {'flood': 'conditions Sacramento CA', 'fire': 'on CAZ001',
                        'slide': 'on Pasadena CA'}[kind]
            command = '!' + kind + 'alarm'
            request = dict(sender='Alice', command=command, arguments=[argument],
                           id=kind, sender_timestamp=now)
            if not alarms.remember(request, now):
                raise AssertionError('Enrollment request was rejected')
            text, error = await alarms.control(request)
            if error or not alarms.row('Alice')['enabled']:
                raise AssertionError(text)
            alarms.acknowledge(request)
            if kind == 'flood':
                while await alarms.send_one():
                    now += 6
            sent.clear()
            events = {'flood': ('New flash warning', 'Major gauge threshold', 'Alert unlisted'),
                      'fire': ('New Red Flag Warning', 'Containment updated', 'Alert unlisted'),
                      'slide': ('New landslide mention', 'Qualified mention updated', 'Alert unlisted')}[kind]
            for event in events:
                now += 301
                if kind == 'flood':
                    if event == events[0]:
                        flood_events = {'a': hazard('a', event='Flash Flood Warning', urgency='Unknown')}
                    elif event == events[1]:
                        flood_state = 'major'
                    else:
                        flood_events = {}
                elif kind == 'fire':
                    if event == events[0]:
                        fire_data['alerts'] = {'red': dict(event='Red Flag Warning', digest='new')}
                    elif event == events[1]:
                        fire_data['incidents'][GUID]['containment'] = 20
                    else:
                        fire_data['alerts'] = {}
                else:
                    if event == events[0]:
                        slide_records = [feature()]
                    elif event == events[1]:
                        slide_records = [feature(headline='Weather statement',
                            description='Debris flows are not expected.', instruction='Watch for mudslides.')]
                    else:
                        slide_records = []
                previous = len(sent)
                await alarms.check_one()
                if kind == 'flood':
                    while await alarms.send_one():
                        now += 6
                if len(sent) == previous:
                    raise AssertionError(command + ': no triggered notification for ' + event)
            examples.extend((command, label, body) for label, body in sent)
    return examples


class TriggeredResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_documented_notifications_match_service_callbacks(self):
        document = (Path(__file__).resolve().parents[1] / 'RESPONSE_EXAMPLES.md').read_text(encoding='utf-8')
        with patch.dict(os.environ, {'MESHCORE_SENDER': 'Alice', 'MESHCORE_TIMEZONE': 'America/Los_Angeles'}):
            examples = await triggered_examples()
            section = document.split('## Triggered subscription notifications\n', 1)[1].split('\n## ', 1)[0]
            documented = re.findall(r'```text\n(.*?)\n```', section, re.S)
            self.assertEqual(documented, [reply_parts('Alice', body, max_parts=1)[0]
                                          for _, _, body in examples])
            for command, event, _ in examples:
                self.assertIn(command + ' — ' + event, section)

    async def test_triggered_notifications_preserve_hazards_and_uncertainty(self):
        expected = {
            ('!floodalarm', 'New flash warning'): ('FLASH FLOOD WARNING', 'Move to higher ground now', 'Priority unknown'),
            ('!floodalarm', 'Major gauge threshold'): ('1 gauge: major flooding', 'not point flooding'),
            ('!floodalarm', 'Alert unlisted'): ('missing', 'cancellation unconfirmed'),
            ('!firealarm', 'New Red Flag Warning'): ('Red Flag Warning',),
            ('!firealarm', 'Containment updated'): ('containment now 20%.',),
            ('!firealarm', 'Alert unlisted'): ('unlisted', 'status unconfirmed'),
            ('!slidealarm', 'New landslide mention'): ('Flash Flood Warning', 'landslide mention'),
            ('!slidealarm', 'Qualified mention updated'): ('qualified mention only',),
            ('!slidealarm', 'Alert unlisted'): ('cancellation unconfirmed', 'Not an all-clear'),
        }
        for sender in ('Alice', 'a' * 80, '温' * 26):
            with patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                examples = await triggered_examples()
            seen = set()
            for command, event, body in examples:
                with self.subTest(sender=sender, command=command, event=event):
                    parts = reply_parts(sender, body, max_parts=1)
                    self.assertEqual(len(parts), 1)
                    self.assertLessEqual(len(parts[0].encode()), 150)
                    self.assertNotIn('Unable to return', parts[0])
                    self.assertNotIn('monitoring set', parts[0])
                    if command == '!floodalarm' and event == 'Alert unlisted':
                        self.assertIn('cancellation unconfirmed', parts[0])
                        self.assertNotIn('No active NWS flood alerts', parts[0])
                    self.assertNotIn('major=1', parts[0])
                    if command == '!floodalarm' and event == 'Major gauge threshold':
                        self.assertNotIn('A Example', parts[0])
                        if sender == 'Alice':
                            self.assertIn('Example upstream gauge [ID A]', parts[0])
                            self.assertIn('USGS unavailable', parts[0])
                    self.assertEqual(parts[0].count('('), parts[0].count(')'))
                    # A poll can also emit a separate state-restoration notice.
                    required = expected[(command, event)]
                    if all(phrase in parts[0] for phrase in required):
                        seen.add((command, event))
            self.assertEqual(seen, set(expected))


if __name__ == '__main__':
    unittest.main()
