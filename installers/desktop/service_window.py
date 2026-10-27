"""Separate service setup window; dataset installation remains in its own application."""
from pathlib import Path
import hashlib
import json
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from installers.datasets.gui.window import Task
from .service_backend import CREDENTIALS, select_installer, validate_settings


class ServiceWindow(QMainWindow):
    """Collect graphical settings and show native worker outcomes without blocking Qt."""

    settingsChanged = pyqtSignal()

    def __init__(self, folder, target, demo=False, embedded=False):
        super().__init__()
        self.folder, self.target, self.demo = Path(folder), target, demo
        self.task = None
        self.pending_action = None
        self.loaded_channels = None
        self.loaded_mqtt = None
        self.setWindowTitle("MeshCore EMS — Service Setup" + (" — DEMO" if demo else ""))
        self.resize(940, 780)
        central = QWidget(); self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        notice = QLabel(("DEMO: no host discovery, authorization or native operations.\n" if demo else "") +
            "Install required datasets with the separate Dataset Manager first. This window installs and manages services only.\n"
            "Radio channels must already exist. Firmware, node Wi-Fi and radio channels are never changed here.")
        notice.setWordWrap(True); layout.addWidget(notice)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        setup = QWidget(); self.tabs.addTab(setup, "Service setup")
        form = QFormLayout(setup)
        folder_row = QWidget(); folder_layout = QHBoxLayout(folder_row); folder_layout.setContentsMargins(0, 0, 0, 0)
        self.folderEdit = QLineEdit(str(folder)); folder_layout.addWidget(self.folderEdit)
        browse = QPushButton("Browse…"); browse.clicked.connect(self.browse); folder_layout.addWidget(browse)
        form.addRow("Service installer folder", folder_row)
        self.transport = QComboBox()
        for label, value in (("Preserve installed settings (new: USB auto)", ""), ("USB serial", "serial"), ("Wi-Fi / TCP", "tcp"), ("Bluetooth LE (paired in OS)", "ble")):
            self.transport.addItem(label, value)
        form.addRow("Companion connection", self.transport)
        self.serial = QLineEdit("auto"); form.addRow("USB port", self.serial)
        self.tcpHost = QLineEdit(); self.tcpHost.setPlaceholderText("Node IP or host name")
        form.addRow("TCP node", self.tcpHost)
        self.tcpPort = QSpinBox(); self.tcpPort.setRange(1, 65535); self.tcpPort.setValue(5000)
        form.addRow("TCP port", self.tcpPort)
        self.ble = QLineEdit(); self.ble.setPlaceholderText("AA:BB:CC:DD:EE:FF — pair through OS settings first")
        form.addRow("BLE address", self.ble)
        self.channel = QLineEdit(); self.channel.setPlaceholderText("Blank preserves installed/default channels")
        form.addRow("Single channel name", self.channel)
        self.startCheck = QCheckBox("Start service after successful installation/settings validation")
        self.startCheck.setChecked(True); form.addRow(self.startCheck)
        form.addRow(QLabel("Use Refresh status to load saved non-secret settings. Blank credential fields preserve saved values."))
        self.credentials = QTableWidget(3, 3); self.credentials.setHorizontalHeaderLabels(["Credential name", "New value (blank preserves)", "Clear saved value"])
        header = self.credentials.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for row, name in enumerate(sorted(CREDENTIALS)):
            self.add_credential(row, name)
        form.addRow("Optional credentials", self.credentials)
        private_row = QWidget(); private_layout = QHBoxLayout(private_row); private_layout.setContentsMargins(0,0,0,0)
        self.privateName = QLineEdit(); self.privateName.setPlaceholderText("MESHCORE_CHANNEL_KEY_NAME")
        private_layout.addWidget(self.privateName)
        add = QPushButton("Add private-channel credential"); add.clicked.connect(self.add_private); private_layout.addWidget(add)
        form.addRow(private_row)
        advanced = QWidget(); self.tabs.addTab(advanced, "Advanced channels / MQTT")
        advance = QFormLayout(advanced)
        self.channelsCheck = QCheckBox("Apply the channel registry and command assignments shown below")
        advance.addRow(self.channelsCheck)
        self.channelsEdit = QPlainTextEdit(); self.channelsEdit.setPlaceholderText('{"channels": {"default": {"name": "#autatestbot", "type": "hashtag", "mqtt_export": true}}, "command_channels": {"!status": ["default"]}}')
        advance.addRow("Channel registry", self.channelsEdit)
        self.importChannels = QPushButton("Import channel settings file…"); self.importChannels.clicked.connect(self.import_channels)
        advance.addRow(self.importChannels)
        advance.addRow(QLabel("Private channels use secret_env credential names; enter their secret values on the Service setup tab.\nThe registry editor changes service configuration only and never programs radio slots."))
        self.mqttCheck = QCheckBox("Apply MQTT connection settings (otherwise preserve installed settings)")
        advance.addRow(self.mqttCheck)
        self.mqttHost = QLineEdit("127.0.0.1"); advance.addRow("MQTT host", self.mqttHost)
        self.mqttPort = QSpinBox(); self.mqttPort.setRange(1,65535); self.mqttPort.setValue(1884 if target == "windows-x64" else 1883)
        advance.addRow("MQTT port", self.mqttPort)
        self.mqttTLS = QCheckBox("Use TLS for an external broker"); advance.addRow(self.mqttTLS)
        self.localBroker = QCheckBox("Use bundled local broker"); self.localBroker.setChecked(True); advance.addRow(self.localBroker)
        self.results = QPlainTextEdit(); self.results.setReadOnly(True); self.results.document().setMaximumBlockCount(5000)
        self.tabs.addTab(self.results, "Results and diagnostics")
        actions = QHBoxLayout(); layout.addLayout(actions)
        self.buttons = []
        for label, action in (("Install / Repair", "install"), ("Save settings", "configure"), ("Refresh status", "status"), ("Start", "start"), ("Stop", "stop"), ("Diagnostics", "diagnostics"), ("Uninstall services", "uninstall")):
            button = QPushButton(label); button.clicked.connect(lambda checked=False, value=action: self.execute(value))
            actions.addWidget(button); self.buttons.append(button)
        save = QPushButton("Save displayed diagnostics…"); save.clicked.connect(self.save); layout.addWidget(save)
        self.transport.currentIndexChanged.connect(self.connection_fields)
        self.connection_fields()
        if embedded:
            # The unified controller owns review and execution. Reuse only the
            # settings widgets; no second set of native-operation controls is
            # exposed inside the coordinated workflow.
            notice.hide()
            folder_row.hide(); form.labelForField(folder_row).hide()
            self.channel.hide(); form.labelForField(self.channel).hide()
            self.startCheck.hide()
            self.channelsCheck.hide(); self.channelsEdit.hide(); self.importChannels.hide()
            advance.labelForField(self.channelsEdit).hide()
            self.tabs.removeTab(self.tabs.indexOf(self.results))
            for button in self.buttons:
                button.hide()
            save.hide()

    def connection_fields(self):
        kind = self.transport.currentData()
        self.serial.setEnabled(kind == "serial")
        self.tcpHost.setEnabled(kind == "tcp"); self.tcpPort.setEnabled(kind == "tcp")
        self.ble.setEnabled(kind == "ble")

    def add_credential(self, row, name):
        """Password widgets prevent secret values appearing in the table or result logs."""
        item = QTableWidgetItem(name); item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.credentials.setItem(row, 0, item)
        field = QLineEdit(); field.setEchoMode(QLineEdit.EchoMode.Password)
        field.textChanged.connect(self.settingsChanged.emit)
        self.credentials.setCellWidget(row, 1, field)
        check = QCheckBox(); self.credentials.setCellWidget(row, 2, check)
        check.toggled.connect(self.settingsChanged.emit)

    def add_private(self):
        name = self.privateName.text().strip()
        try:
            validate_settings({"credentials": {name: ""}})
            if not name.startswith("MESHCORE_CHANNEL_KEY_"):
                raise ValueError("Use a MESHCORE_CHANNEL_KEY_... credential name")
            if any(self.credentials.item(row,0).text() == name for row in range(self.credentials.rowCount())):
                return
            row = self.credentials.rowCount(); self.credentials.insertRow(row); self.add_credential(row, name)
            self.privateName.clear()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid private-channel credential", str(error))

    def browse(self):
        selected = QFileDialog.getExistingDirectory(self, "Choose service installer folder", self.folderEdit.text())
        if selected:
            self.folderEdit.setText(selected)

    def import_channels(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import channel registry", "", "JSON (*.json)")
        if filename:
            try:
                value = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
                validate_settings({"channels": value})
                self.channelsEdit.setPlainText(json.dumps(value, indent=2)); self.channelsCheck.setChecked(True)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Cannot import channel settings", str(error))

    def settings(self):
        """Collect only explicit overrides so saved settings survive ordinary upgrades."""
        result = {}
        kind = self.transport.currentData()
        if kind:
            result["transport"] = kind
            if kind == "serial":
                result["serial_port"] = self.serial.text().strip()
            elif kind == "tcp":
                result.update(tcp_host=self.tcpHost.text().strip(), tcp_port=self.tcpPort.value())
            else:
                result["ble_address"] = self.ble.text().strip()
        if self.channel.text().strip():
            result["channel"] = self.channel.text().strip()
        if self.channelsCheck.isChecked():
            result["channels"] = json.loads(self.channelsEdit.toPlainText())
        if self.mqttCheck.isChecked():
            result["mqtt"] = {"host":self.mqttHost.text().strip(), "port":self.mqttPort.value(), "tls":self.mqttTLS.isChecked(), "local_broker":self.localBroker.isChecked()}
        credentials, clears = {}, []
        for row in range(self.credentials.rowCount()):
            name = self.credentials.item(row, 0).text()
            value = self.credentials.cellWidget(row, 1).text()
            if value:
                credentials[name] = value
            if self.credentials.cellWidget(row, 2).isChecked():
                clears.append(name)
        result.update(credentials=credentials, clear_credentials=clears)
        return validate_settings(result)

    def execute(self, action):
        """Review scope once before authorization; perform no native work in demo mode."""
        if self.task is not None:
            return
        try:
            request = {"kind":"service", "action":action, "target":self.target}
            if action in {"install", "configure"}:
                request.update(settings=self.settings(), start=self.startCheck.isChecked())
            if action == "install" and not self.demo:
                folder = Path(self.folderEdit.text()).expanduser()
                if not folder.is_absolute():
                    raise ValueError("Select an absolute service installer folder")
                artifact = select_installer(folder, self.target)
                with artifact.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                request.update(folder=str(folder.resolve()), artifact_sha256=digest)
            if action in {"install", "configure", "uninstall"}:
                message = {"install":"Install/repair services using the checked installer? Datasets remain independent.",
                           "configure":"Stop services and save the displayed settings? Existing configuration and runtime data will be backed up.",
                           "uninstall":"Remove services and their native service package? Configuration, credentials, datasets, runtime databases and recovery material will be retained."}[action]
                if self.demo:
                    message = "SIMULATE: " + message
                if QMessageBox.question(self, "Confirm service operation", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return
            def operation(emit, progress):
                if self.demo:
                    emit("Demo: simulated " + action + "; no host discovery or native operations")
                    return {"status":"Demo — service stopped", "detail":"Simulation only"}
                from .authorization import run_authorized
                return run_authorized(request, emit)
            self.pending_action = action
            self.results.clear(); self.tabs.setCurrentWidget(self.results)
            self.task = Task(operation, self)
            self.task.message.connect(self.results.appendPlainText)
            self.task.result.connect(self.completed)
            self.task.error.connect(self.failed)
            self.task.finished.connect(self.finished)
            for button in self.buttons:
                button.setEnabled(False)
            self.tabs.widget(0).setEnabled(False); self.tabs.widget(1).setEnabled(False)
            self.task.start()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Service operation unavailable", str(error))

    def completed(self, result):
        self.results.appendPlainText(json.dumps(result, indent=2))
        # Only non-secret values return from the worker. Fields become overrides
        # only if explicitly selected, preserving upgrade behavior.
        value = result.get("settings", {})
        if value:
            if not self.channelsCheck.isChecked():
                self.channelsEdit.setPlainText(json.dumps(value.get("channels", {}), indent=2))
            for name in value.get("credential_names", []):
                if name.startswith("MESHCORE_CHANNEL_KEY_") and not any(self.credentials.item(row,0).text() == name for row in range(self.credentials.rowCount())):
                    row=self.credentials.rowCount(); self.credentials.insertRow(row); self.add_credential(row,name)
            connection = value.get("connection", {})
            if not self.transport.currentData():
                self.serial.setText(value.get("serial_port", "auto"))
                self.tcpHost.setText(connection.get("host", "")); self.tcpPort.setValue(connection.get("port",5000))
                self.ble.setText(connection.get("address", ""))
            mqtt=value.get("mqtt",{})
            if not self.mqttCheck.isChecked():
                self.mqttHost.setText(mqtt.get("host","127.0.0.1")); self.mqttPort.setValue(mqtt.get("port",1884 if self.target=="windows-x64" else 1883))
                self.mqttTLS.setChecked(mqtt.get("tls",False)); self.localBroker.setChecked(mqtt.get("local_broker",True))
        if self.pending_action in {"install", "configure"}:
            for row in range(self.credentials.rowCount()):
                self.credentials.cellWidget(row,1).clear(); self.credentials.cellWidget(row,2).setChecked(False)

    def failed(self, error):
        self.results.appendPlainText("Operation did not complete:\n" + error + "\nInstalled files and recovery material may remain. Review diagnostics before retrying.")

    def finished(self):
        task, self.task = self.task, None
        task.deleteLater()
        for button in self.buttons:
            button.setEnabled(True)
        self.tabs.widget(0).setEnabled(True); self.tabs.widget(1).setEnabled(True)

    def save(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save displayed diagnostics", "service-diagnostics.log", "Log (*.log)")
        if filename:
            try:
                Path(filename).write_text(self.results.toPlainText(),encoding="utf-8")
            except OSError as error:
                QMessageBox.warning(self,"Cannot save diagnostics",str(error))

    def closeEvent(self, event):
        if self.task is not None:
            QMessageBox.information(self,"Operation in progress","Wait for the current native operation and verification to finish before closing.")
            event.ignore()
        else:
            event.accept()
