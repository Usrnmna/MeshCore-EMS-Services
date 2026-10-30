"""Read-only history rendering and cancellation contracts, without host discovery."""
import importlib.util
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PyQt6.QtWidgets import QApplication
except ImportError:
    QApplication = None


class Session:
    def __init__(self):
        self.requests=[]; self.busy=False; self.cancelled=False; self.outcome=None
    def start(self, request):
        if self.busy: return False
        self.requests.append(request); self.busy=True; self.outcome={'state':'running'}
        return True
    def poll(self): return self.outcome
    def complete(self, value):
        self.busy=False; self.outcome={'state':'complete','result':value}
    def cancel_nowait(self): self.cancelled=True


@unittest.skipIf(QApplication is None, 'PyQt6 required')
class HistoryWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('installers.desktop.history_window'))
        from installers.desktop import history_window as gui
        self.gui=gui
        self.session=Session()
        self.window=gui.HistoryWindow('windows-x64',session=self.session)
        self.now=datetime.now(timezone.utc)
        self.session.complete({'settings':{'enabled':True,'channel_id':'events'},
            'service_state':'running','database_path':'local.sqlite3','availability':'available',
            'channels':[{'channel_id':'old','channel_name':'Previous','latest_received_at':self.now.isoformat()},
                        {'channel_id':'events','channel_name':'Private','latest_received_at':self.now.isoformat()}]})
        self.window.poll_result()

    def tearDown(self): self.window.close(); self.app.processEvents()

    def page(self, age=0, text='<script>unchanged</script>', cursor=None):
        return {'messages':[{'event_id':'one','received_at':(self.now-timedelta(seconds=age)).isoformat(),
            'channel_id':'events','channel_name':'Private','sender':None,'text':text,
            'sender_timestamp':1,'payload':{'text':text},'attributes':{},'device':{}}],
            'next_cursor':cursor, 'queried_at':self.now.isoformat(),
            'window_start':(self.now-timedelta(days=1)).isoformat(),'query_upper':self.now.isoformat()}

    def test_saved_target_and_literal_detail_are_read_only(self):
        self.assertEqual(self.window.channel.currentData(),'events')
        self.window.refresh()
        self.assertEqual(self.session.requests[-1]['action'],'page')
        self.session.complete(self.page()); self.window.poll_result()
        self.assertEqual(self.window.table.rowCount(),1)
        self.window.table.selectRow(0); self.app.processEvents()
        self.assertIn('<script>unchanged</script>',self.window.detail.toPlainText())
        self.assertTrue(self.window.detail.isReadOnly())

    def test_expiration_clears_selected_detail(self):
        self.window.refresh(); self.session.complete(self.page(age=86399)); self.window.poll_result()
        self.window.table.selectRow(0); self.app.processEvents()
        with patch.object(self.gui,'utc_now',return_value=self.now+timedelta(seconds=2)):
            self.window.expire_rows()
        self.assertEqual(self.window.table.rowCount(),0)
        self.assertEqual(self.window.detail.toPlainText(),'')

    def test_late_result_after_filter_change_is_ignored(self):
        self.window.refresh()
        self.window.channel.setCurrentIndex(self.window.channel.findData('old'))
        self.session.complete(self.page()); self.window.poll_result()
        self.assertEqual(self.window.table.rowCount(),0)

    def test_close_signals_cancel_without_waiting(self):
        self.window.refresh()
        self.assertTrue(self.session.busy)
        self.window.close()
        self.assertTrue(self.session.cancelled)
        self.assertTrue(self.session.busy)

    def test_paging_and_stale_error(self):
        self.window.refresh(); self.session.complete(self.page(cursor='next')); self.window.poll_result()
        self.window.load_older()
        self.assertEqual(self.session.requests[-1]['query']['cursor'],'next')
        self.session.busy=False; self.session.outcome={'state':'failed','error':'History unavailable'}
        self.window.poll_result()
        self.assertIn('stale',self.window.status.text().lower())
        self.assertEqual(self.window.table.rowCount(),1)

    def test_demo_never_creates_native_session(self):
        with patch('installers.desktop.history_window.native_session',side_effect=AssertionError('host access')):
            demo=self.gui.HistoryWindow('windows-x64',demo=True)
            demo.refresh()
            demo.poll_result()
            self.assertGreater(demo.table.rowCount(),0)
            demo.close()

    def test_reload_clears_previous_channel_page_and_cursor(self):
        self.window.channel.setCurrentIndex(self.window.channel.findData('old'))
        self.window.refresh(); self.session.complete(self.page(cursor='old-page')); self.window.poll_result()
        self.window.reload_channels()
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertIsNone(self.window._query)
        self.assertIsNone(self.window._cursor)
        self.session.complete({'settings': {'channel_id': 'events'}, 'channels': []})
        self.window.poll_result()
        self.assertEqual(self.window.channel.currentData(), 'events')
        self.assertFalse(self.window.older_button.isEnabled())

    def test_time_controls_really_use_utc_instead_of_local_time_with_a_utc_label(self):
        from PyQt6.QtCore import Qt
        for field in (self.window.start_time, self.window.end_time):
            self.assertEqual(field.timeSpec(), Qt.TimeSpec.UTC)
            self.assertEqual(field.text(), field.dateTime().toUTC().toString("yyyy-MM-dd HH:mm:ss 'UTC'"))


if __name__=='__main__': unittest.main()
