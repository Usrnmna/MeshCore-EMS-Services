"""Shared optional recording controls; no storage, device or service operations."""
import copy
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit,
                             QPushButton, QWidget)


class HistorySettingsError(ValueError):
    """Invalid optional input that callers report without rejecting core edits."""


class HistorySettingsWidget(QWidget):
    """Collect one explicit history override independently of core channel edits."""
    changed = pyqtSignal()
    viewRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.registry = {}
        self.supported = False
        self._loading = False
        form = QFormLayout(self)
        self.savedLabel = QLabel("Recording settings have not been loaded.")
        self.savedLabel.setWordWrap(True); form.addRow(self.savedLabel)
        self.savedLabel.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(QLabel("Retention: rolling 24 hours (86400 seconds), based on local UTC reception."))
        self.observationLabel = QLabel("Service / database / latest reception: not observed. Open the viewer to read status.")
        self.observationLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.observationLabel.setWordWrap(True); form.addRow(self.observationLabel)
        self.databasePath = QLineEdit(); self.databasePath.setReadOnly(True)
        self.databasePath.setPlaceholderText("Database path has not been observed")
        form.addRow("Recording database", self.databasePath)
        self.copyPath = QPushButton("Copy path"); self.copyPath.setEnabled(False)
        self.copyPath.clicked.connect(lambda: QApplication.clipboard().setText(self.databasePath.text()))
        form.addRow(self.copyPath)
        self.applyCheck = QCheckBox("Apply recording settings")
        self.enabledCheck = QCheckBox("Record received channel messages for 24 hours")
        form.addRow(self.applyCheck); form.addRow(self.enabledCheck)
        self.sourceCombo = QComboBox()
        self.sourceCombo.addItem("Existing service channel", "service")
        self.sourceCombo.addItem("Recording-only channel reference", "recording")
        form.addRow("Source", self.sourceCombo)
        self.serviceChannel = QComboBox(); form.addRow("Service channel (ID / name / type)", self.serviceChannel)
        self.channelId = QLineEdit(); form.addRow("Recording-only stable ID", self.channelId)
        self.channelName = QLineEdit(); form.addRow("Exact channel name", self.channelName)
        self.channelType = QComboBox(); self.channelType.addItems(["public", "hashtag", "private", "existing"])
        form.addRow("Channel type", self.channelType)
        self.slot = QLineEdit(); form.addRow("Radio slot (optional)", self.slot)
        self.secretEnv = QLineEdit(); self.secretEnv.setPlaceholderText("MESHCORE_CHANNEL_KEY_NAME")
        form.addRow("Private credential reference", self.secretEnv)
        self.secretValue = QLineEdit(); self.secretValue.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("New recording-only key (blank preserves)", self.secretValue)
        self.clearSecret = QCheckBox("Clear this recording-only saved key"); form.addRow(self.clearSecret)
        self.viewButton = QPushButton("View recent messages"); self.viewButton.clicked.connect(self.viewRequested)
        form.addRow(self.viewButton)
        note = QLabel("References must already exist on the companion. Recording does not provision channels, export MQTT, create subscriptions or include direct messages.")
        note.setWordWrap(True); form.addRow(note)
        for check in (self.applyCheck, self.enabledCheck, self.clearSecret):
            check.toggled.connect(self._edited)
        for combo in (self.sourceCombo, self.serviceChannel, self.channelType):
            combo.currentIndexChanged.connect(self._edited)
        for edit in (self.channelId, self.channelName, self.slot, self.secretEnv, self.secretValue):
            edit.textChanged.connect(self._edited)
        self._enable_fields()

    def _edited(self, *args):
        self._enable_fields()
        if not self._loading:
            self.changed.emit()

    def observe(self, value):
        """Display a completed optional read, separately from pending saved settings."""
        path = value.get("database_path")
        self.databasePath.setText(path if isinstance(path, str) else "")
        self.copyPath.setEnabled(bool(self.databasePath.text()))
        latest = value.get("latest_received_at") or "no recent reception observed"
        self.observationLabel.setText("Service: " + str(value.get("service_state", "unknown"))
            + "\nDatabase: " + str(value.get("availability", "unknown"))
            + "\nLatest reception (UTC): " + str(latest)
            + "\nObserved (UTC): " + str(value.get("observed_at", "unknown")))

    def _enable_fields(self):
        """Capability affects only this optional surface, never its parent form."""
        self.applyCheck.setEnabled(self.supported)
        active = self.supported and self.applyCheck.isChecked()
        self.enabledCheck.setEnabled(active)
        enabled = active and self.enabledCheck.isChecked()
        self.sourceCombo.setEnabled(enabled)
        recording = self.sourceCombo.currentData() == "recording"
        self.serviceChannel.setEnabled(enabled and not recording)
        for field in (self.channelId, self.channelName, self.channelType, self.slot, self.secretEnv, self.secretValue, self.clearSecret):
            field.setEnabled(enabled and recording)
        for field in (self.secretEnv, self.secretValue, self.clearSecret):
            field.setEnabled(enabled and recording and self.channelType.currentText() == 'private')
        self.viewButton.setEnabled(self.supported)

    def set_registry(self, registry):
        """Refresh names/types while preserving a missing selection explicitly."""
        selected = self.serviceChannel.currentData()
        self.registry = copy.deepcopy(registry)
        self.serviceChannel.blockSignals(True)
        self.serviceChannel.clear(); self.serviceChannel.addItem("Choose a service channel…", None)
        for channel_id, channel in registry.items():
            self.serviceChannel.addItem(f"{channel_id} — {channel.get('name', '')} ({channel.get('type', '')})", channel_id)
        index = self.serviceChannel.findData(selected)
        if selected is not None and index < 0:
            self.serviceChannel.addItem(f"{selected} — missing from effective service registry", selected)
            index = self.serviceChannel.count() - 1
        self.serviceChannel.setCurrentIndex(max(0, index))
        self.serviceChannel.blockSignals(False)

    def load(self, settings, registry, supported):
        """Load safe saved values without overwriting explicit pending edits."""
        self._loading = True
        try:
            self.supported = bool(supported)
            self.set_registry(registry)
            settings = settings if isinstance(settings, dict) else {}
            self.savedLabel.setText("Saved recording: " + ("enabled" if settings.get("enabled") is True else "disabled") +
                                    (". History support unavailable; repair with a current installer." if not supported else "."))
            if not self.applyCheck.isChecked():
                self.enabledCheck.setChecked(settings.get("enabled") is True)
                recording = isinstance(settings.get("channel"), dict)
                self.sourceCombo.setCurrentIndex(1 if recording else 0)
                channel_id = settings.get("channel_id", "")
                channel_id = channel_id if isinstance(channel_id, str) else ""
                if recording:
                    channel = settings["channel"]
                    self.channelId.setText(channel_id)
                    self.channelName.setText(channel.get("name") if isinstance(channel.get("name"), str) else "")
                    self.channelType.setCurrentText(channel.get("type") if isinstance(channel.get("type"), str) else "public")
                    self.slot.setText(str(channel["slot"]) if type(channel.get("slot")) is int else "")
                    self.secretEnv.setText(channel.get("secret_env") if isinstance(channel.get("secret_env"), str) else "")
                else:
                    index = self.serviceChannel.findData(channel_id)
                    if channel_id and index < 0:
                        self.serviceChannel.addItem(f"{channel_id} — missing from effective service registry", channel_id)
                        index = self.serviceChannel.count() - 1
                    self.serviceChannel.setCurrentIndex(max(0, index))
            self._enable_fields()
        finally:
            self._loading = False

    def override(self):
        """Return an explicit override; disabled means save disabled, not preserve."""
        if not self.applyCheck.isChecked():
            return None
        if not self.supported:
            raise HistorySettingsError("Recording support is unavailable in this installation.")
        if not self.enabledCheck.isChecked():
            return {"enabled": False}
        if self.sourceCombo.currentData() == "service":
            selected = self.serviceChannel.currentData()
            if selected not in self.registry:
                raise HistorySettingsError("Select an existing service channel from the effective registry.")
            return {"enabled": True, "channel_id": selected}
        channel_id = self.channelId.text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", channel_id) or channel_id in self.registry:
            raise HistorySettingsError("Recording-only ID must be valid and distinct from service channels.")
        name = self.channelName.text()
        if not name or name != name.strip() or not name.isprintable() or len(name.encode("utf-8")) > 32:
            raise HistorySettingsError("Channel name must contain 1–32 printable UTF-8 bytes without surrounding spaces.")
        kind = self.channelType.currentText()
        if kind == "hashtag" and not name.startswith("#"):
            raise HistorySettingsError("Hashtag channel names must begin with #.")
        channel = {"name": name, "type": kind, "mqtt_export": False}
        if self.slot.text():
            try:
                slot = int(self.slot.text())
                if not 0 <= slot <= 255:
                    raise ValueError()
            except ValueError:
                raise HistorySettingsError("Radio slot must be an integer between 0 and 255.") from None
            channel["slot"] = slot
        if kind == "private":
            reference = self.secretEnv.text().strip()
            if not re.fullmatch(r"MESHCORE_CHANNEL_KEY_[A-Z0-9_]+", reference):
                raise HistorySettingsError("A private recording-only channel needs its credential reference.")
            channel["secret_env"] = reference
        return {"enabled": True, "channel_id": channel_id, "channel": channel}

    def credential_overrides(self):
        """Keep recording-only secret edits separate from mandatory credentials."""
        if (not self.applyCheck.isChecked() or not self.enabledCheck.isChecked()
                or self.sourceCombo.currentData() != 'recording' or self.channelType.currentText() != 'private'):
            return {}
        reference = self.secretEnv.text().strip()
        result = {}
        if self.secretValue.text():
            result["history_credentials"] = {reference: self.secretValue.text()}
        if self.clearSecret.isChecked():
            result["history_clear_credentials"] = [reference]
        return result
