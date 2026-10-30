"""History contracts use disposable stores and no radio or installed service."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class AvailabilityTests(unittest.TestCase):
    def test_module_available(self):
        self.assertIsNotNone(importlib.util.find_spec('channel_history'))


def settings(channel=None):
    import channel_history as h
    return h.validate_history_config({'channel_history': {
        'enabled': True, 'channel_id': 'events', 'channel': channel or {
            'name': '#falldetect', 'type': 'hashtag', 'mqtt_export': False}}})


class HistoryTests(unittest.TestCase):
    def setUp(self):
        import channel_history as h
        self.h = h
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'history' / 'channel_history.sqlite3'
        self.now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        self.clock = patch.object(h, '_now', return_value=self.now)
        self.clock_mock = self.clock.start()
        self.cfg = settings()
        self.binding = h.ChannelObservation(2, '#falldetect', self.cfg.identity, self.now)
        self.evidence = h.BindingEvidence('not_performed')
        self.workers = []

    def tearDown(self):
        for recorder in self.workers:
            recorder.stop_nowait()
            if recorder._thread:
                recorder._thread.join(2)  # Test cleanup only; production never joins.
        self.clock.stop()
        self.tmp.cleanup()

    def record(self, id='one', when=None, **payload):
        return dict(id=id, received_at=(when or self.now).isoformat(),
                    event='CHANNEL_MSG_RECV', payload=dict(channel_idx=2, text=' Alice: \x00雪 ', **payload),
                    attributes={'rssi': -70}, device={'transport': 'serial'})

    def recorder(self):
        r = self.h.ChannelHistoryRecorder(self.path, settings=self.cfg)
        r.observe_binding(self.binding)
        self.workers.append(r)
        return r

    def wait_count(self, r, count):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and r.status().committed < count:
            time.sleep(.01)
        self.assertEqual(r.status().committed, count, r.status())

    def test_configuration(self):
        h = self.h
        self.assertFalse(h.validate_history_config({}).enabled)
        for spec in ({'name':'Public','type':'public','mqtt_export':False},
                     {'name':'Ops','type':'existing','mqtt_export':False}):
            self.assertTrue(settings(spec).enabled)
        with patch.dict('os.environ', {'MESHCORE_CHANNEL_KEY_OPS': '01' * 16}):
            self.assertTrue(settings({'name':'Ops','type':'private','secret_env':'MESHCORE_CHANNEL_KEY_OPS','mqtt_export':False}).identity)
        for change in ({'enabled':1}, {'enabled':True, 'channel_id':'unknown'}, {'enabled':False, 'extra':1}):
            with self.assertRaises(ValueError):
                h.validate_history_config({'channel_history':change})
        with self.assertRaises(ValueError):
            h.validate_history_config({'responder': {'channels':{'events':{}}}, 'channel_history':{
                'enabled':True,'channel_id':'events','channel':{'name':'Public','type':'public','mqtt_export':False}}})

    def test_text_types_empty_bodies_and_stale_sender_time_are_not_filtered(self):
        r = self.recorder(); r.start()
        texts = ['', '!status', ' Alice: repeat ', '雪\x00']
        for kind, content in zip((0, 1, 2, 255), texts):
            event = self.record(str(kind), sender_timestamp=-1000, txt_type=kind)
            event['payload']['text'] = content
            self.assertEqual(r.offer_received(event, evidence=self.evidence), 'queued')
        self.wait_count(r, 4)
        rows = self.h.read_recent_messages(self.path, channel_id='events')
        self.assertEqual({row.payload['txt_type']: row.text for row in rows}, dict(zip((0, 1, 2, 255), texts)))
        self.assertTrue(all(row.sender_timestamp == -1000 for row in rows))

    def test_preservation_duplicate_restart_and_nonconsuming(self):
        r = self.recorder(); r.start()
        event = self.record(sender_timestamp=1, unknown={'bytes':b'\x00\xff'})
        self.assertEqual(r.offer_received(event, evidence=self.evidence), 'queued')
        self.wait_count(r, 1)
        r.offer_received(event, evidence=self.evidence)
        r.offer_received(self.record('two'), evidence=self.evidence)
        self.wait_count(r, 2)
        rows = self.h.read_recent_messages(self.path, channel_id='events')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].text, event['payload']['text'])
        self.assertEqual(rows[0].sender_timestamp, 1)
        self.assertIsNone(rows[0].sender)
        self.assertEqual(rows[0].payload['unknown']['bytes'], {'encoding':'hex','data':'00ff'})
        self.assertEqual(rows, self.h.read_recent_messages(self.path, channel_id='events'))
        r.stop_nowait(); r._thread.join(2)
        other = self.recorder(); other.start()
        other.offer_received(self.record('three'), evidence=self.evidence)
        self.wait_count(other, 1)
        self.assertEqual(len(self.h.read_recent_messages(self.path, channel_id='events')), 3)

    def test_boundary_and_idle_cleanup(self):
        r = self.recorder(); r.start()
        for id, delta in [('expired',timedelta(hours=-24)), ('inside',timedelta(hours=-24,microseconds=1)), ('now',timedelta()), ('future',timedelta(microseconds=1))]:
            r.offer_received(self.record(id, self.now+delta), evidence=self.evidence)
        self.wait_count(r, 4)
        rows = self.h.read_recent_messages(self.path, channel_id='events')
        self.assertEqual([x.event_id for x in rows], ['inside','now'])
        with patch.object(self.h, '_now', return_value=self.now+timedelta(days=2)):
            r._next_sweep = 0
            deadline = time.monotonic()+2
            import sqlite3
            while time.monotonic()<deadline:
                with closing(sqlite3.connect(self.path)) as db:
                    count = db.execute('select count(*) from channel_messages').fetchone()[0]
                if count == 0: break
                time.sleep(.01)
            self.assertEqual(count, 0)

    def test_selection_and_failed_core_evidence(self):
        r = self.recorder()
        for kind in ['CONTACT_MSG_RECV', 'BOT_REPLY', 'RX_LOG_DATA']:
            event = self.record(); event['event'] = kind
            self.assertEqual(r.offer_received(event, evidence=self.evidence), 'not_target')
        event = self.record(); event['payload']['channel_idx'] = 9
        self.assertEqual(r.offer_received(event, evidence=self.evidence), 'not_target')
        self.assertEqual(r.offer_received(self.record(), evidence=self.h.BindingEvidence('failed')), 'unverified')
        self.assertEqual(r.status().pending, 0)

    def test_limits_and_contended_stop_never_wait(self):
        r = self.recorder()
        with patch.object(self.h, 'MAX_RECORDS', 1):
            self.assertEqual(r.offer_received(self.record(), evidence=self.evidence), 'queued')
            self.assertEqual(r.offer_received(self.record('two'), evidence=self.evidence), 'full')
        event = self.record(); event['payload']['text'] = 'x' * 65537
        self.assertEqual(r.offer_received(event, evidence=self.evidence), 'oversized')
        r._lock.acquire()
        try:
            self.assertEqual(r.offer_received(self.record(), evidence=self.evidence), 'contended')
            self.assertEqual(r.stop_nowait().state, 'stopping')
        finally: r._lock.release()

    def test_reader_errors_and_sender_selection(self):
        with self.assertRaises(self.h.HistoryUnavailable):
            self.h.read_recent_messages(self.path, channel_id='events')
        self.assertFalse(self.path.exists())
        r = self.recorder(); r.start()
        event = self.record(); event['payload']['text'] = 'Alice: hello'
        r.offer_received(event, evidence=self.evidence); self.wait_count(r,1)
        self.assertEqual(len(self.h.read_recent_messages(self.path, channel_id='events', sender_prefix='Alice')),1)
        self.assertEqual(self.h.read_recent_messages(self.path, channel_id='events',sender='Alice'),[])
        with self.assertRaises(ValueError):
            self.h.read_recent_messages(self.path, channel_id='events',start=datetime(2020,1,1))

    def test_paging_and_catalog(self):
        r = self.recorder(); r.start()
        for i in range(205): r.offer_received(self.record(f'{i:03}'), evidence=self.evidence)
        self.wait_count(r,205)
        page = self.h.read_message_page(self.path, channel_id='events')
        self.assertEqual(len(page.messages),200)
        other = self.h.read_message_page(self.path, channel_id='events',cursor=page.next_cursor)
        self.assertEqual(len(other.messages),5)
        self.assertFalse(other.next_cursor)
        self.assertEqual(len({m.event_id for m in page.messages+other.messages}),205)
        self.assertEqual(self.h.list_recorded_channels(self.path)[0].channel_id,'events')
        with self.assertRaises(ValueError):
            self.h.read_message_page(self.path,channel_id='different',cursor=page.next_cursor)

    def test_page_byte_budget_preserves_whole_records_and_continuation(self):
        r = self.recorder(); r.start()
        for i in range(5):
            event = self.record(str(i)); event['payload']['text'] = '雪' * 100
            r.offer_received(event, evidence=self.evidence)
        self.wait_count(r, 5)
        with patch.object(self.h, 'MAX_PAGE_BYTES', 10000):
            cursor, rows = None, []
            while True:
                page = self.h.read_message_page(self.path, channel_id='events', cursor=cursor)
                rows.extend(page.messages)
                self.assertTrue(all(row.text == '雪' * 100 for row in page.messages))
                cursor = page.next_cursor
                if cursor is None: break
            self.assertEqual(len({row.event_id for row in rows}), 5)
        with patch.object(self.h, 'MAX_PAGE_BYTES', 1), self.assertRaises(self.h.HistoryUnavailable):
            self.h.read_message_page(self.path, channel_id='events')

    def test_new_commits_do_not_advance_an_existing_page_upper_bound(self):
        r = self.recorder(); r.start()
        for id in ('a', 'b', 'c'): r.offer_received(self.record(id), evidence=self.evidence)
        self.wait_count(r, 3)
        first = self.h.read_message_page(self.path, channel_id='events', page_size=2)
        later = self.now + timedelta(seconds=1)
        self.clock_mock.return_value = later
        r.offer_received(self.record('new', when=later), evidence=self.evidence); self.wait_count(r, 4)
        second = self.h.read_message_page(self.path, channel_id='events', cursor=first.next_cursor)
        self.assertEqual([row.event_id for row in second.messages], ['a'])
        self.assertEqual(self.h.read_message_page(self.path, channel_id='events').messages[0].event_id, 'new')

    def test_clock_corrections_report_without_changing_received_timestamps(self):
        r = self.recorder()
        with patch.object(self.h.time, 'monotonic', return_value=10): r._observe_clock()
        self.clock_mock.return_value = self.now + timedelta(hours=1)
        with patch.object(self.h.time, 'monotonic', return_value=11): r._observe_clock()
        self.assertEqual(r.status().clock_corrections, 1)
        self.clock_mock.return_value = self.now
        with patch.object(self.h.time, 'monotonic', return_value=12): r._observe_clock()
        self.assertEqual(r.status().clock_corrections, 2)

    def test_stalled_worker_does_not_prevent_process_exit(self):
        code = "import threading; from pathlib import Path; import channel_history as h; r=h.ChannelHistoryRecorder(Path('unused'),settings=h.HistorySettings(False,None,None)); r._run=lambda: threading.Event().wait(); r.start(); r.stop_nowait()"
        result = subprocess.run([sys.executable,'-B','-c',code],cwd=Path(__file__).resolve().parents[1],timeout=3,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_core_target_rejects_other_id_with_same_identity(self):
        self.cfg = self.h.HistorySettings(True,'events',dict(self.cfg.channel),self.cfg.identity,True)
        r = self.recorder()
        event = self.record(); event['payload']['channel_id'] = 'another'
        evidence = self.h.BindingEvidence('passed',self.binding)
        self.assertEqual(r.offer_received(event,evidence=evidence),'not_target')

    def test_slot_selection_applies_to_verified_core_observations(self):
        self.cfg = settings({'name':'#falldetect','type':'hashtag','slot':2,'mqtt_export':False})
        r = self.recorder()
        wrong = self.h.ChannelObservation(3,self.binding.name,self.binding.identity,self.now)
        event = self.record(); event['payload']['channel_idx']=3
        self.assertEqual(r.offer_received(event,evidence=self.h.BindingEvidence('passed',wrong)),'not_target')

    def test_byte_budget_and_snapshot_detachment(self):
        r = self.recorder()
        with patch.object(self.h,'MAX_PENDING_BYTES',1):
            self.assertEqual(r.offer_received(self.record(),evidence=self.evidence),'full')
        event = self.record()
        r.offer_received(event,evidence=self.evidence)
        event['payload']['text']='changed afterwards'
        r.start(); self.wait_count(r,1)
        self.assertNotEqual(self.h.read_recent_messages(self.path,channel_id='events')[0].text,'changed afterwards')

    def test_storage_fault_is_contained_and_recovery_bounded(self):
        r = self.recorder()
        r.offer_received(self.record(),evidence=self.evidence)
        with patch.object(r,'_open',side_effect=PermissionError('injected')) as opening:
            r.start()
            deadline=time.monotonic()+2
            while r.status().state=='initializing' and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(r.status().state,'unavailable')
            self.assertEqual(r.status().missed,1)
            self.assertEqual(r.offer_received(self.record('later'),evidence=self.evidence),'unavailable')
            time.sleep(.1)
            self.assertEqual(opening.call_count,1)
        r.stop_nowait()

    def test_low_disk_budget_retains_existing_records(self):
        r = self.recorder(); r.start()
        r.offer_received(self.record(),evidence=self.evidence); self.wait_count(r,1)
        with patch.object(self.h,'MAX_STORAGE_BYTES',1):
            r.offer_received(self.record('second'),evidence=self.evidence)
            deadline=time.monotonic()+2
            while r.status().state=='ready' and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(r.status().state,'unavailable')
        self.assertEqual([m.event_id for m in self.h.read_recent_messages(self.path,channel_id='events')],['one'])

    def test_conflicting_retry_does_not_overwrite_original(self):
        r=self.recorder(); r.start()
        r.offer_received(self.record(),evidence=self.evidence); self.wait_count(r,1)
        event=self.record(); event['payload']['text']='conflict'
        r.offer_received(event,evidence=self.evidence)
        deadline=time.monotonic()+2
        while r.status().state=='ready' and time.monotonic()<deadline: time.sleep(.01)
        self.assertEqual(r.status().state,'unavailable')
        self.assertEqual(self.h.read_recent_messages(self.path,channel_id='events')[0].text,' Alice: \x00雪 ')

    def test_restart_prunes_and_identity_pins_survive(self):
        r=self.recorder(); r.start()
        r.offer_received(self.record(),evidence=self.evidence); self.wait_count(r,1)
        r.stop_nowait(); r._thread.join(2)
        self.cfg=settings({'name':'#different','type':'hashtag','mqtt_export':False})
        other=self.recorder()
        other.observe_binding(self.h.ChannelObservation(2,'#different',self.cfg.identity,self.now))
        other.start(); other.offer_received(self.record('different'),evidence=self.evidence)
        deadline=time.monotonic()+2
        while other.status().state in ('initializing','ready') and time.monotonic()<deadline: time.sleep(.01)
        self.assertEqual(other.status().state,'unavailable')
        self.assertEqual(len(self.h.read_recent_messages(self.path,channel_id='events')),1)
        other.stop_nowait(); other._thread.join(2)
        with patch.object(self.h,'_now',return_value=self.now+timedelta(days=2)):
            db = other._open()
            try: self.assertEqual(db.execute('SELECT count(*) FROM channel_messages').fetchone()[0],0)
            finally: db.close()

    def test_query_ranges_clock_correction_and_cursor_expiration(self):
        r=self.recorder(); r.start()
        for i in range(3): r.offer_received(self.record(str(i),self.now-timedelta(hours=i)),evidence=self.evidence)
        self.wait_count(r,3)
        rows=self.h.read_recent_messages(self.path,channel_id='events',start=self.now-timedelta(hours=1),end=self.now)
        self.assertEqual([m.event_id for m in rows],['1'])
        page=self.h.read_message_page(self.path,channel_id='events',page_size=1)
        with patch.object(self.h,'_now',return_value=self.now+timedelta(days=2)):
            self.assertEqual(self.h.read_message_page(self.path,channel_id='events',cursor=page.next_cursor).messages,[])
        with patch.object(self.h,'_now',return_value=self.now-timedelta(hours=1)):
            self.assertEqual([m.event_id for m in self.h.read_recent_messages(self.path,channel_id='events')],['2','1'])

    def test_concurrent_process_reads_do_not_consume_or_lock_out_writer(self):
        r=self.recorder(); r.start()
        r.offer_received(self.record(),evidence=self.evidence); self.wait_count(r,1)
        code="from pathlib import Path; from datetime import datetime; import channel_history as h; h._now=lambda:datetime.fromisoformat(__import__('sys').argv[2]); [h.read_recent_messages(Path(__import__('sys').argv[1]),channel_id='events') for _ in range(50)]"
        child=subprocess.Popen([sys.executable,'-B','-c',code,str(self.path),self.now.isoformat()],cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            for i in range(40): r.offer_received(self.record(str(i)),evidence=self.evidence)
            self.wait_count(r,41)
            _, errors=child.communicate(timeout=5)
            self.assertEqual(child.returncode,0,errors)
            self.assertEqual(len(self.h.read_recent_messages(self.path,channel_id='events')),41)
        finally:
            if child.poll() is None: child.kill(); child.wait()

    def test_corrupt_and_incompatible_read_do_not_modify_store(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b'not a database')
        with self.assertRaises(self.h.HistoryUnavailable):
            self.h.read_recent_messages(self.path,channel_id='events')
        self.assertEqual(self.path.read_bytes(),b'not a database')

    def test_damaged_record_is_unavailable_not_an_empty_or_partial_result(self):
        r = self.recorder(); r.start()
        r.offer_received(self.record(), evidence=self.evidence); self.wait_count(r, 1)
        with closing(self.h.sqlite3.connect(self.path)) as db:
            db.execute("UPDATE channel_messages SET payload_json='invalid-json'"); db.commit()
        for read in (self.h.read_recent_messages, self.h.read_message_page):
            with self.subTest(read=read.__name__), self.assertRaises(self.h.HistoryUnavailable):
                read(self.path, channel_id='events')

    def test_incomplete_identity_observation_disables_existing_mode(self):
        self.cfg=settings({'name':'#falldetect','type':'existing','mqtt_export':False})
        r=self.recorder()
        r.observe_binding(self.h.ChannelObservation(2,'#falldetect','',self.now))
        self.assertEqual(r.offer_received(self.record(),evidence=self.evidence),'unverified')

    def test_stalled_diagnostics_does_not_hold_admission_or_stop_lock(self):
        r=self.recorder()
        entered, release=threading.Event(),threading.Event()
        def stalled():
            entered.set(); release.wait()
        with patch.object(r,'_report',side_effect=stalled):
            r.start()
            self.assertTrue(entered.wait(2))
            try:
                self.assertEqual(r.offer_received(self.record(),evidence=self.evidence),'queued')
                self.assertEqual(r.stop_nowait().state,'stopping')
            finally:
                release.set(); r._thread.join(2)


if __name__ == '__main__': unittest.main()
