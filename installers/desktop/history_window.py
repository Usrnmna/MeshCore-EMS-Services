"""Read-only channel history presentation, independent of installer maintenance.

Only a bounded current page lives in the UI. Optional read sessions never occupy
the installer's task, perform service controls, or join during window closure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from PyQt6.QtCore import QDateTime, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDateTimeEdit, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QAbstractItemView,
)


def utc_now():
    return datetime.now(timezone.utc)


def native_session():
    """Reuse one optional session per application; imports are lazy and contained."""
    application = QApplication.instance()
    if not hasattr(application, '_channel_history_session'):
        from .history_process import HistoryReadSession
        application._channel_history_session = HistoryReadSession()
    return application._channel_history_session


class _DemoSession:
    """Synthetic catalog/pages with no installed-state or authorization access."""
    busy = False

    def __init__(self):
        self.result = None

    def start(self, request):
        now = utc_now().isoformat()
        if request['action'] == 'catalog':
            value = {'settings': {'enabled': True, 'channel_id': 'demo'},
                     'service_state': 'synthetic', 'database_path': '(synthetic demo)',
                     'availability': 'available', 'channels': [
                         {'channel_id': 'demo', 'channel_name': '#demo', 'latest_received_at': now}]}
        else:
            value = {'messages': [{'event_id': 'demo-reception', 'received_at': now,
                'channel_id': 'demo', 'channel_name': '#demo', 'sender': None,
                'text': 'Example: synthetic channel message', 'sender_timestamp': None,
                'payload': {}, 'attributes': {}, 'device': {}}], 'next_cursor': None,
                'queried_at': now, 'query_upper': now,
                'window_start': (utc_now()-timedelta(days=1)).isoformat()}
        self.result = {'state': 'complete', 'result': value}
        return True

    def poll(self): return self.result

    def cancel_nowait(self):
        self.result = {'state': 'cancelled'}


class _MessageDetail(QPlainTextEdit):
    """Recheck expiration before copying or opening a text context menu."""
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.parent().expire_rows()
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        self.parent().expire_rows()
        super().contextMenuEvent(event)


class HistoryWindow(QWidget):
    """Shared viewer for native desktop entry points; session supports injection."""
    catalogObserved = pyqtSignal(dict)
    def __init__(self, target, parent=None, demo=False, *, session=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.target = target
        self._generation = 0
        self._pending_token = None
        self._action = None
        self._rows = []
        self._cursor = None
        self._query = None
        self._rendering = False
        self._closed = False
        self.setWindowTitle('Recent channel messages — read only')
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        self.summary = QLabel('Reading saved configuration…')
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        form = QFormLayout()
        self.channel = QComboBox()
        self.range = QComboBox()
        self.range.addItems(['Last 24 hours', 'Last hour', 'Custom UTC range'])
        self.start_time, self.end_time = QDateTimeEdit(), QDateTimeEdit()
        for field, value in ((self.start_time, utc_now()-timedelta(hours=1)), (self.end_time, utc_now())):
            field.setTimeSpec(Qt.TimeSpec.UTC)
            field.setDateTime(QDateTime.fromSecsSinceEpoch(int(value.timestamp()), Qt.TimeSpec.UTC))
            field.setDisplayFormat("yyyy-MM-dd HH:mm:ss 'UTC'")
            field.setCalendarPopup(True)
            field.setEnabled(False)
        self.sender_kind = QComboBox()
        self.sender_kind.addItems(['Any sender', 'Structured sender', 'Literal sender prefix'])
        self.sender = QLineEdit()
        self.sender.setEnabled(False)
        self.sender.setPlaceholderText('Literal prefix is text matching, not verified identity')
        form.addRow('Recorded channel', self.channel)
        form.addRow('Reception window', self.range)
        form.addRow('From (inclusive)', self.start_time)
        form.addRow('To (exclusive)', self.end_time)
        form.addRow('Sender selector', self.sender_kind)
        form.addRow('Sender value', self.sender)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton('Refresh')
        self.older_button = QPushButton('Load older')
        self.catalog_button = QPushButton('Reload channels')
        for button in (self.refresh_button, self.older_button, self.catalog_button): actions.addWidget(button)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Received (UTC)', 'Channel', 'Sender', 'Message'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        for index, width in enumerate((210, 150, 140)):
            self.table.setColumnWidth(index, width)
        layout.addWidget(self.table)
        self.detail = _MessageDetail(self)
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText('Select a message to view its complete text and supplied metadata.')
        layout.addWidget(self.detail)
        self.status = QLabel('')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh_button.clicked.connect(self.refresh)
        self.older_button.clicked.connect(self.load_older)
        self.catalog_button.clicked.connect(self.reload_channels)
        self.table.itemSelectionChanged.connect(self.show_detail)
        for signal in (self.channel.currentIndexChanged, self.range.currentIndexChanged,
                       self.sender_kind.currentIndexChanged, self.sender.textChanged,
                       self.start_time.dateTimeChanged, self.end_time.dateTimeChanged):
            signal.connect(self.filters_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll_result)
        self.timer.start()
        self.expiration = QTimer(self)
        self.expiration.setInterval(1000)
        self.expiration.timeout.connect(self.expire_rows)
        self.expiration.start()
        application = QApplication.instance()
        application.aboutToQuit.connect(self.stop_reads)
        application.applicationStateChanged.connect(self.expire_rows)
        try:
            self.session = session if session is not None else (_DemoSession() if demo else native_session())
        except Exception:
            self.session = None
            self.status.setText('History viewer support is unavailable. Installer operations remain available.')
        self.reload_channels()
        if demo:
            self.poll_result()

    def _buttons(self):
        busy = bool(self.session and self.session.busy)
        self.refresh_button.setEnabled(bool(self.session) and not busy and self.channel.currentData() is not None)
        self.older_button.setEnabled(bool(self._cursor) and not busy)
        self.catalog_button.setEnabled(bool(self.session) and not busy)

    def _submit(self, action, query):
        """Start an optional read and bind its result to the current UI selection."""
        if self.session is None or self._closed: return
        request = {'schema': 1, 'kind': 'history', 'target': self.target, 'action': action, 'query': query}
        try:
            if not self.session.start(request):
                self.status.setText('A previous history read is still finishing. Installer operations remain available.')
                return
            self._action, self._pending_token = action, self._generation
            self._session_generation = getattr(self.session, 'generation', None)
            self.status.setText('Reading channel history…')
        except Exception:
            self.status.setText('History read could not start. Installer operations remain available.')
        self._buttons()

    def reload_channels(self):
        """Refresh saved targets without retaining an older channel's cached page."""
        self._generation += 1
        self._rows, self._cursor, self._query = [], None, None
        self._draw()
        self._submit('catalog', {})

    def filters_changed(self, *args):
        """Invalidate pending replies and cached detail when query selectors change."""
        self._generation += 1
        self.start_time.setEnabled(self.range.currentIndex() == 2)
        self.end_time.setEnabled(self.range.currentIndex() == 2)
        self.sender.setEnabled(self.sender_kind.currentIndex() != 0)
        self._rows, self._cursor, self._query = [], None, None
        self._draw()
        if self.session is not None and self.session.busy:
            self.session.cancel_nowait()
        self._buttons()

    def refresh(self):
        """Read the newest page using explicit UTC and mutually exclusive senders."""
        if self.channel.currentData() is None:
            self.status.setText('Select a recorded channel.'); return
        query = {'channel_id': self.channel.currentData(), 'page_size': 200}
        if self.range.currentIndex() == 1:
            query['start'] = (utc_now()-timedelta(hours=1)).isoformat()
        elif self.range.currentIndex() == 2:
            query['start'] = datetime.fromtimestamp(self.start_time.dateTime().toSecsSinceEpoch(), timezone.utc).isoformat()
            query['end'] = datetime.fromtimestamp(self.end_time.dateTime().toSecsSinceEpoch(), timezone.utc).isoformat()
            if query['start'] >= query['end']:
                self.status.setText('The custom start must precede its end.'); return
        if self.sender_kind.currentIndex():
            query['sender' if self.sender_kind.currentIndex() == 1 else 'sender_prefix'] = self.sender.text()
        self._cursor, self._query = None, query
        self._generation += 1
        self._submit('page', query)

    def load_older(self):
        if self._cursor and self._query:
            self._submit('page', dict(self._query, cursor=self._cursor))

    def poll_result(self):
        if self._closed or self.session is None: return
        try:
            outcome = self.session.poll()
            self._buttons()
            if not outcome or outcome.get('state') == 'running' or self._pending_token is None: return
            token, self._pending_token = self._pending_token, None
            if token != self._generation: return
            if self._session_generation is not None and outcome.get('generation') != self._session_generation: return
            if outcome.get('state') != 'complete':
                self.expire_rows()
                prefix = 'Displayed page is stale. ' if self._rows else ''
                self.status.setText(prefix + str(outcome.get('error') or 'History read cancelled.'))
                return
            result = outcome['result']
            if self._action == 'catalog': self._catalog(result)
            else: self._page(result)
        except Exception:
            self.status.setText(('Displayed page is stale. ' if self._rows else '')+'History response unavailable.')
        self._buttons()

    def _catalog(self, result):
        """Render saved and observed states separately without implying recorder health."""
        result = dict(result)
        result.setdefault('observed_at', utc_now().isoformat())
        result.setdefault('latest_received_at', max((item.get('latest_received_at', '') for item in result.get('channels', [])), default=None))
        self.catalogObserved.emit(result)
        saved = result.get('settings') or {}
        selected = saved.get('channel_id')
        self.channel.blockSignals(True)
        self.channel.clear()
        for item in result.get('channels', []):
            id = item['channel_id']
            label = f"{item['channel_name']} ({id})" + (' — current' if id == selected else ' — previous')
            self.channel.addItem(label, id)
        if selected and self.channel.findData(selected) < 0:
            self.channel.addItem(f'{selected} — no recent records', selected)
        self.channel.setCurrentIndex(self.channel.findData(selected) if selected else -1)
        self.channel.blockSignals(False)
        self.summary.setText('Saved recording: '+('enabled' if saved.get('enabled') else 'disabled')+
            '\nService state: '+str(result.get('service_state','unknown'))+
            '\nDatabase: '+str(result.get('database_path','unavailable'))+
            '\nLatest reception (UTC): '+str(result.get('latest_received_at') or 'none in current window')+
            '\nObserved (UTC): '+result['observed_at'])
        availability = result.get('availability', 'unknown')
        self.status.setText('Choose a channel and select Refresh.' if availability == 'available' else str(availability))

    def _page(self, result):
        """Replace the bounded page, retaining complete records and its continuation."""
        rows = result['messages']
        if not isinstance(rows, list) or len(rows)>200 or len(json.dumps(result).encode())>2*1024*1024:
            raise ValueError('Page exceeds viewer budget')
        self._rows, self._cursor = rows, result.get('next_cursor')
        self._retain_current()
        self._draw()
        self.status.setText(('No matching messages.' if not self._rows else f'{len(self._rows)} messages. ')+
                            ('Older matches remain.' if self._cursor else ''))

    def _retain_current(self):
        now = utc_now()
        lower = now-timedelta(hours=24)
        self._rows = [row for row in self._rows if lower < datetime.fromisoformat(row['received_at']) <= now]

    def expire_rows(self, *args):
        """Clear expired cached records and selected detail even during quiet periods."""
        if self._closed or self._rendering: return
        before = len(self._rows)
        self._retain_current()
        if len(self._rows) != before:
            self._draw()
            if not self._rows: self.status.setText('The retention window advanced. Select Refresh.')

    def _draw(self):
        self._rendering = True
        try:
            self.detail.clear()
            self.table.setRowCount(0)
            self.table.setRowCount(len(self._rows))
            for index, row in enumerate(self._rows):
                values = [datetime.fromisoformat(row['received_at']).strftime('%Y-%m-%d %H:%M:%S'), row.get('channel_name') or row['channel_id'],
                          row.get('sender') if row.get('sender') is not None else 'Not supplied',
                          (row.get('text') or '')[:100]]
                for column, value in enumerate(values):
                    self.table.setItem(index,column,QTableWidgetItem(str(value)))
        finally:
            self._rendering = False

    def show_detail(self):
        """Show complete supplied content as inert text after rechecking expiration."""
        if self._rendering: return
        self.expire_rows()
        index = self.table.currentRow()
        if 0 <= index < len(self._rows):
            row = self._rows[index]
            self.detail.setPlainText((row.get('text') or '')+'\n\nSupplied metadata:\n'+
                                     json.dumps(row, ensure_ascii=False, indent=2))
        else: self.detail.clear()

    def stop_reads(self):
        """Invalidate the view and signal cancellation without waiting for a helper."""
        self._closed = True
        self._generation += 1
        self.timer.stop(); self.expiration.stop()
        self._rows = []; self._draw()
        if self.session is not None:
            try: self.session.cancel_nowait()
            except Exception: pass

    def closeEvent(self, event):
        self.stop_reads()
        event.accept()

    def showEvent(self, event):
        self._closed = False
        self.timer.start(); self.expiration.start()
        self.expire_rows()
        super().showEvent(event)
