"""Graphical coordination over independently owned native installer backends.

This controller reuses the Dataset Manager's selection conventions and worker
thread, and the independent Service Setup's settings widgets. It submits intent
to the shared planner rather than constructing privileged commands.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QTabWidget,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from installers.datasets.gui.catalog import DATASETS, LABELS
from installers.datasets.gui.window import Task
from .service_window import ServiceWindow


def prepare(intent, emit, demo=False):
    """Load the orchestration backend lazily so Qt remains separate from workers."""
    from .unified_backend import prepare as backend_prepare
    return backend_prepare(intent, emit, demo=demo)


def execute_reviewed(plan, cancel, emit, demo=False):
    """Execute only the reviewed operation through the native authorization path."""
    from .unified_backend import execute_reviewed as backend_execute
    return backend_execute(plan, cancel, emit, demo=demo)


class UnifiedWindow(QMainWindow):
    """Offer component selection, local integration settings and one reviewed plan."""

    def __init__(self, root, folder, target, demo=False):
        super().__init__()
        self.target, self.demo = target, demo
        self.task = self.plan = None
        self.snapshot = {}
        self.cancel = threading.Event()
        self.pending_programs = []
        self.removed_programs = set()
        self._redactions = set()
        self._root_dirty = False
        self._loading_root = False
        self._refresh_again = False
        self.setWindowTitle("MeshCore EMS — Installation and Maintenance" + (" — DEMO" if demo else ""))
        self.resize(1120, 860)
        central = QWidget(); self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        notice = QLabel(("DEMO — no host discovery or native operations.\n" if demo else "") +
            "One reviewed operation; independently owned packages, runtimes and uninstallers. "
            "Configuration, credentials, custom programs and recovery data are retained by default.")
        notice.setWordWrap(True); outer.addWidget(notice)
        self.tabs = QTabWidget(); outer.addWidget(self.tabs)
        self._overview(root, folder)
        self._components()
        self._connections(folder)
        self._channels()
        self._programs()
        self.planText = QPlainTextEdit(); self.planText.setReadOnly(True)
        self.tabs.addTab(self.planText, "Review")
        self.resultsText = QPlainTextEdit(); self.resultsText.setReadOnly(True)
        self.resultsText.document().setMaximumBlockCount(6000)
        self.tabs.addTab(self.resultsText, "Progress / recovery")
        self.progressBar = QProgressBar(); outer.addWidget(self.progressBar)
        buttons = QHBoxLayout(); outer.addLayout(buttons)
        self.refreshButton = QPushButton("Refresh status"); self.refreshButton.clicked.connect(self.refresh)
        self.reviewButton = QPushButton("Review selected operation"); self.reviewButton.clicked.connect(self.review)
        self.executeButton = QPushButton("Execute reviewed operation"); self.executeButton.clicked.connect(self.execute)
        self.executeButton.setEnabled(False)
        self.cancelButton = QPushButton("Cancel after current step"); self.cancelButton.clicked.connect(self.request_cancel)
        self.cancelButton.setEnabled(False)
        diagnostics = QPushButton("Diagnostics"); diagnostics.clicked.connect(self.diagnostics)
        history = QPushButton("Recovery history"); history.clicked.connect(self.recovery_history)
        recover = QPushButton("Recover interrupted maintenance"); recover.clicked.connect(self.recover_maintenance)
        save = QPushButton("Save displayed report…"); save.clicked.connect(self.save_report)
        self.actionButtons = [self.refreshButton, self.reviewButton, self.executeButton, diagnostics, history, recover, save]
        for button in [self.refreshButton, self.reviewButton, self.executeButton, self.cancelButton]:
            buttons.addWidget(button)
        reports = QHBoxLayout(); outer.addLayout(reports)
        for button in (diagnostics, history, recover, save):
            reports.addWidget(button)
        self._connect_invalidation()
        self.serviceForm.settingsChanged.connect(self.invalidate)
        QTimer.singleShot(0, self.refresh)

    def _overview(self, root, folder):
        page = QWidget(); form = QFormLayout(page); self.tabs.addTab(page, "Overview")
        self.statusLabel = QLabel("Status has not been inspected."); self.statusLabel.setWordWrap(True)
        form.addRow(self.statusLabel)
        self.dataRootEdit = QLineEdit(str(root)); self.installerFolderEdit = QLineEdit(str(folder))
        for label, field in (("Shared dataset root", self.dataRootEdit), ("Installer folder", self.installerFolderEdit)):
            row = QWidget(); layout = QHBoxLayout(row); layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(field); button = QPushButton("Browse…")
            button.clicked.connect(lambda checked=False, edit=field: self.browse(edit)); layout.addWidget(button)
            form.addRow(label, row)
        self.rootChoices = QComboBox()
        self.rootChoices.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.rootChoices.setMinimumContentsLength(32)
        self.rootChoices.addItem("Choose a discovered root…", None)
        self.rootChoices.currentIndexChanged.connect(self.choose_discovered_root)
        form.addRow("Discovered dataset roots", self.rootChoices)
        self.rootChoicesLabel = form.labelForField(self.rootChoices)
        self.rootHintLabel = QLabel("Discovery suggestions do not activate data or establish ownership. Multiple roots require an explicit graphical choice.")
        self.rootHintLabel.setWordWrap(True); form.addRow(self.rootHintLabel)
        self.rootChoices.hide(); self.rootChoicesLabel.hide(); self.rootHintLabel.hide()
        self.applyDataRoot = QCheckBox("Apply this dataset root to service consumers")
        form.addRow(self.applyDataRoot)
        form.addRow(QLabel("Root changes do not move datasets. Existing package records at another root require a separate review."))
        boundary = QLabel("Saved connection settings configure this computer only. USB connections, OS Bluetooth pairing and privilege approval may be required.\n"
            "Firmware, node Wi-Fi, channel slots and device resets are never changed. External broker administration is outside this interface.\n"
            "Scheduling and subscriptions remain owned by the service. Changed channel identities or assignments can make stored subscriptions ineligible.")
        boundary.setWordWrap(True); form.addRow(boundary)

    def _components(self):
        page = QWidget(); layout = QVBoxLayout(page); self.tabs.addTab(page, "Components")
        form = QFormLayout(); layout.addLayout(form)
        self.serviceAction = QComboBox()
        for label, value in (("Keep service package and settings", "keep"), ("Install / update / repair service package", "install"),
                ("Save local integration settings", "configure"), ("Validate local configuration (offline)", "validate"),
                ("Check companion / channel references (read-only; stops service)", "check_connection"),
                ("Start service", "start"), ("Stop service / disconnect devices", "stop"),
                ("Deconfigure interface-owned settings (retain package)", "deconfigure"),
                ("Uninstall service package (retain configuration and data)", "uninstall")):
            self.serviceAction.addItem(label, value)
        form.addRow("Service operation", self.serviceAction)
        self.startup = QComboBox()
        for label, value in (("Preserve existing startup policy", "preserve"), ("Manual startup", "manual"),
                             ("Automatic startup after validation", "automatic"), ("Disabled", "disabled")):
            self.startup.addItem(label, value)
        form.addRow("Startup policy", self.startup)
        self.startCheck = QCheckBox("Start eligible service after successful validation")
        form.addRow(self.startCheck)
        self.datasetAction = QComboBox()
        for label, value in (("Keep datasets and maintenance packages", "keep"), ("Install selected datasets / repair missing tools", "install"),
                ("Recover a reviewed interrupted dataset operation (retain data)", "recover"),
                ("Repair selected maintenance packages (retain valid data)", "repair"),
                ("Verify selected managed datasets", "verify"), ("Update selected datasets", "update"),
                ("Rollback selected datasets where available", "rollback"),
                ("Uninstall selected maintenance packages; retain datasets", "remove_tools"),
                ("Remove selected managed datasets and maintenance packages", "remove_data")):
            self.datasetAction.addItem(label, value)
        form.addRow("Dataset operation", self.datasetAction)
        self.datasetTree = QTreeWidget()
        self.datasetTree.setHeaderLabels(["Dataset", "Purpose", "Package installed", "Data present / verified"])
        self.datasetTree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for name, (label, description) in LABELS.items():
            row = QTreeWidgetItem([label, description, "Unknown", "Unknown"])
            row.setData(0, Qt.ItemDataRole.UserRole, name)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Unchecked)
            self.datasetTree.addTopLevelItem(row)
        layout.addWidget(self.datasetTree)
        warning = QLabel("Datasets are optional unless selected features need them. Dependencies are expanded for installation; dependent removals are never selected silently.\n"
            "Shipped Python command programs belong to the service package. Their Enabled and channel controls change local registration, not package ownership.\n"
            "Purge is not offered here. Shared OS dependencies, external brokers, custom code and unowned files are retained.")
        warning.setWordWrap(True); layout.addWidget(warning)

    def _connections(self, folder):
        # Reparent only the settings surface. The hidden standalone window stays
        # alive as its controller; its operation controls are hidden in embedded mode.
        self.serviceForm = ServiceWindow(folder, self.target, self.demo, embedded=True)
        content = self.serviceForm.takeCentralWidget()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content)
        self.tabs.addTab(scroll, "Connections / credentials")

    def _channels(self):
        page = QWidget(); layout = QVBoxLayout(page); self.tabs.addTab(page, "Channels / applications")
        self.applyChannels = QCheckBox("Apply local channel references and command assignments")
        layout.addWidget(self.applyChannels)
        self.channelTable = QTableWidget(0, 6)
        self.channelTable.setHorizontalHeaderLabels(["Stable ID", "Channel name", "Type", "Slot (optional)", "Credential reference", "MQTT export"])
        self.channelTable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.channelTable)
        buttons = QHBoxLayout(); layout.addLayout(buttons)
        add = QPushButton("Add channel reference"); add.clicked.connect(lambda: self.add_channel())
        remove = QPushButton("Remove selected local reference"); remove.clicked.connect(self.remove_channel)
        buttons.addWidget(add); buttons.addWidget(remove)
        self.applyCommands = QCheckBox("Apply command enablement shown below")
        layout.addWidget(self.applyCommands)
        self.commandTable = QTableWidget(0, 4)
        self.commandTable.setHorizontalHeaderLabels(["Command / enabled", "Channel IDs (comma-separated)", "Program", "Owner"])
        self.commandTable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.commandTable)
        text = QLabel("These are local references and assignments; radio slots are not programmed. Channel IDs refer to rows above.\n"
            "A private channel uses its credential reference, with the key entered on Connections / credentials.\n"
            "Disabling a command preserves its program file. Service-owned scheduling and subscriptions are unchanged; eligibility is re-evaluated by the service.")
        text.setWordWrap(True); layout.addWidget(text)

    def _programs(self):
        page = QWidget(); form = QFormLayout(page); self.tabs.addTab(page, "Custom programs")
        self.programName = QLineEdit(); self.programName.setPlaceholderText("!custom")
        self.programChannels = QLineEdit(); self.programChannels.setPlaceholderText("default")
        form.addRow("Command phrase", self.programName); form.addRow("Channel IDs (comma-separated)", self.programChannels)
        self.programInput = QComboBox()
        for label, value in (("No message arguments", "none"), ("Coordinates", "coordinates"),
                ("Route number", "route_number"), ("Location", "location"), ("GIS query", "gis_query"),
                ("Fire query", "fire_query"), ("Landslide query", "slide_query"), ("Water query", "water_query")):
            self.programInput.addItem(label, value)
        form.addRow("Message input", self.programInput)
        add = QPushButton("Choose Python program to register…"); add.clicked.connect(self.choose_program)
        form.addRow(add)
        self.programList = QPlainTextEdit(); self.programList.setReadOnly(True); form.addRow("Pending changes", self.programList)
        self.unregisterName = QComboBox(); self.unregisterName.setEditable(True)
        self.unregisterName.setPlaceholderText("Existing custom command phrase")
        form.addRow("Deregister command", self.unregisterName)
        remove = QPushButton("Add deregistration (retain program file)"); remove.clicked.connect(self.unregister_program)
        form.addRow(remove)
        clear = QPushButton("Clear pending program changes"); clear.clicked.connect(self.clear_programs); form.addRow(clear)
        warning = QLabel("Each custom command retains its own Python entry point. Selected source is hash-checked and statically validated before registration; it is never executed with installer privileges.\n"
            "No dependency installation is performed. External imports may require dependencies already present in the service runtime. Deregistration preserves custom files.")
        warning.setWordWrap(True); form.addRow(warning)

    def _connect_invalidation(self):
        """Any selected setting change consumes the preceding review."""
        for edit in self.findChildren(QLineEdit):
            edit.textChanged.connect(self.invalidate)
        self.dataRootEdit.textChanged.connect(self.root_edited)
        for check in self.findChildren(QCheckBox):
            check.toggled.connect(self.invalidate)
        for combo in self.findChildren(QComboBox):
            combo.currentIndexChanged.connect(self.invalidate)
        for table in (self.channelTable, self.commandTable):
            table.itemChanged.connect(self.invalidate)
        self.datasetTree.itemChanged.connect(self.invalidate)
        self.serviceForm.tcpPort.valueChanged.connect(self.invalidate)
        self.serviceForm.mqttPort.valueChanged.connect(self.invalidate)

    def invalidate(self, *args):
        self.plan = None
        self.executeButton.setEnabled(False)
        self.planText.setPlainText("Review the current selection and settings before execution.")

    def root_edited(self):
        """Distinguish an explicit location choice from initial installed discovery."""
        if not self._loading_root:
            self._root_dirty = True

    def browse(self, field):
        selected = QFileDialog.getExistingDirectory(self, "Choose directory", field.text())
        if selected:
            field.setText(selected)

    @staticmethod
    def ids(text):
        """Parse graphical comma-separated stable IDs without accepting commands."""
        return [value.strip() for value in text.split(",") if value.strip()]

    def selected(self):
        return [self.datasetTree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(self.datasetTree.topLevelItemCount())
                if self.datasetTree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]

    def intent(self, status_only=False):
        """Collect only explicit overrides; package owners validate their schemas."""
        root = Path(self.dataRootEdit.text().strip()).expanduser()
        folder = Path(self.installerFolderEdit.text().strip()).expanduser()
        if not root.is_absolute() or not folder.is_absolute():
            raise ValueError("Choose absolute data and installer directories")
        settings = {} if status_only else self.serviceForm.settings()
        if not status_only and self.applyDataRoot.isChecked():
            settings["dataset_root"] = str(root)
        if not status_only and self.applyChannels.isChecked():
            channels = {}
            for row in range(self.channelTable.rowCount()):
                key, name, kind, slot, secret = [self.channelTable.item(row, col).text().strip() for col in range(5)]
                if not key or key in channels:
                    raise ValueError("Each channel reference needs a unique stable ID")
                spec = {"name": name, "type": kind, "mqtt_export": self.channelTable.cellWidget(row, 5).isChecked()}
                if slot:
                    try:
                        spec["slot"] = int(slot)
                    except ValueError as error:
                        raise ValueError("Channel slot must be an integer or blank") from error
                if secret:
                    spec["secret_env"] = secret
                channels[key] = spec
            assignments = {self.commandTable.item(row, 0).text(): self.ids(self.commandTable.item(row, 1).text())
                           for row in range(self.commandTable.rowCount())}
            settings["channels"] = {"channels": channels, "command_channels": assignments}
        if not status_only and self.applyCommands.isChecked():
            settings["commands"] = {self.commandTable.item(row, 0).text():
                self.commandTable.item(row, 0).checkState() == Qt.CheckState.Checked
                for row in range(self.commandTable.rowCount())}
        if not status_only and (self.pending_programs or self.removed_programs):
            settings["programs"] = {"register": list(self.pending_programs), "unregister": sorted(self.removed_programs)}
        return {"target": self.target, "root": str(root), "folder": str(folder),
            "dataset_action": "keep" if status_only else self.datasetAction.currentData(),
            "datasets": [] if status_only else self.selected(),
            "service_action": "keep" if status_only else self.serviceAction.currentData(),
            "settings": settings, "startup": "preserve" if status_only else self.startup.currentData(),
            "start": False if status_only else self.startCheck.isChecked()}

    def add_channel(self, key="", spec=None):
        """Append a local reference; no device interaction occurs."""
        spec = spec or {}; row = self.channelTable.rowCount(); self.channelTable.insertRow(row)
        values = [key, spec.get("name", ""), spec.get("type", "existing"), str(spec.get("slot", "")), spec.get("secret_env", "")]
        for col, value in enumerate(values):
            self.channelTable.setItem(row, col, QTableWidgetItem(value))
        exported = QCheckBox(); exported.setChecked(spec.get("mqtt_export", False))
        exported.toggled.connect(self.invalidate); self.channelTable.setCellWidget(row, 5, exported)
        self.invalidate()

    def remove_channel(self):
        row = self.channelTable.currentRow()
        if row >= 0:
            self.channelTable.removeRow(row); self.invalidate()

    def choose_program(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Choose dedicated Python program", "", "Python (*.py)")
        if filename:
            try:
                path = Path(filename)
                if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".py":
                    raise ValueError("Choose a regular Python source file")
                if path.stat().st_size > 128 * 1024:
                    raise ValueError("Custom program exceeds the 128 KiB source limit")
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                name = self.programName.text().strip()
                if not name:
                    raise ValueError("Enter a command phrase before choosing its program")
                self.pending_programs = [value for value in self.pending_programs if value["name"] != name]
                self.pending_programs.append({"name": name, "source": str(path.absolute()), "sha256": digest,
                    "channels": self.ids(self.programChannels.text()), "input": self.programInput.currentData()})
                self._program_changes()
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Program registration unavailable", str(error))

    def unregister_program(self):
        name = self.unregisterName.currentText().strip()
        if name:
            self.removed_programs.add(name); self._program_changes()

    def clear_programs(self):
        self.pending_programs.clear(); self.removed_programs.clear(); self._program_changes()

    def _program_changes(self):
        self.programList.setPlainText("\n".join(["Register " + value["name"] + " from " + value["source"] for value in self.pending_programs]
            + ["Deregister " + name + "; retain source file" for name in sorted(self.removed_programs)]))
        self.invalidate()

    def refresh(self):
        self.invalidate()
        try:
            intent = self.intent(status_only=True)
        except ValueError as error:
            self.failed(str(error)); return
        self.start_task(lambda emit: prepare(intent, emit, demo=self.demo), self.show_status)

    def review(self):
        self.invalidate()
        try:
            intent = self.intent()
        except (OSError, ValueError) as error:
            self.failed(str(error)); return
        self.start_task(lambda emit: prepare(intent, emit, demo=self.demo), self.show_plan)

    def show_status(self, plan):
        self.populate(plan.get("snapshot", {}))
        service = plan.get("snapshot", {}).get("service", {})
        data_root = service.get("settings", {}).get("dataset_root")
        suggestions = service.get("retained_roots", [])
        if not data_root and len(suggestions) == 1:
            data_root = suggestions[0].get("root")
        if data_root and not self._root_dirty and Path(data_root).is_absolute() and data_root != self.dataRootEdit.text():
            self._loading_root = True
            self.dataRootEdit.setText(data_root)
            self._loading_root = False
            # The initial discovery used the default root. Rescan the discovered
            # configured root before displaying its dataset state as current.
            self._refresh_again = True
        self.statusLabel.setText(self.statusLabel.text() + ("\n" + "\n".join(plan.get("blocked", [])) if plan.get("blocked") else ""))

    def choose_discovered_root(self):
        """Make an explicit local root choice; service configuration stays opt-in."""
        root = self.rootChoices.currentData()
        if root:
            self.dataRootEdit.setText(root)
            self._root_dirty = True
            self.refresh()

    def show_plan(self, plan):
        self.populate(plan.get("snapshot", {}))
        self.plan = plan
        self.planText.setPlainText(self.redacted(plan["text"]))
        self.tabs.setCurrentWidget(self.planText)

    def populate(self, snapshot):
        """Load safe status without replacing explicit, unsaved form overrides."""
        self.snapshot = snapshot
        service = snapshot.get("service", {})
        self.rootChoices.blockSignals(True)
        self.rootChoices.clear(); self.rootChoices.addItem("Choose a discovered root…", None)
        suggestions = service.get("retained_roots", [])
        for suggestion in suggestions:
            root = suggestion.get("root")
            if not isinstance(root, str) or not Path(root).is_absolute():
                continue
            names = ", ".join(suggestion.get("datasets", []))
            self.rootChoices.addItem(root + (" — " + names if names else ""), root)
            self.rootChoices.setItemData(self.rootChoices.count() - 1, root + "\n" + suggestion.get("verification", "Advisory discovery; verification required"), Qt.ItemDataRole.ToolTipRole)
            if root == self.dataRootEdit.text():
                self.rootChoices.setCurrentIndex(self.rootChoices.count() - 1)
        self.rootChoices.blockSignals(False)
        visible = self.rootChoices.count() > 1
        for widget in (self.rootChoices, self.rootChoicesLabel, self.rootHintLabel):
            widget.setVisible(visible)
        self.statusLabel.setText(f"Target: {self.target}\nService package installed: {service.get('installed', 'unknown')} | "
            f"Runtime: {service.get('status', 'unknown')} | Startup: {service.get('startup', 'unknown')}\n"
            "Package installation, runtime enablement and dataset presence are separate states.")
        self.serviceForm.completed({"settings": service.get("settings", {})})
        datasets = snapshot.get("datasets", {}).get("collections", {})
        self.datasetTree.blockSignals(True)
        for row in range(self.datasetTree.topLevelItemCount()):
            item = self.datasetTree.topLevelItem(row); value = datasets.get(item.data(0, Qt.ItemDataRole.UserRole), {})
            package = value.get("package", {})
            item.setText(2, package.get("state", "unknown")); item.setText(3, value.get("data", "unknown"))
        self.datasetTree.blockSignals(False)
        settings = service.get("settings", {})
        previous_program = self.unregisterName.currentText()
        self.unregisterName.blockSignals(True)
        self.unregisterName.clear()
        self.unregisterName.addItems(sorted(name for name, spec in settings.get("commands", {}).items()
            if spec.get("owner") == "operator-program"))
        self.unregisterName.setCurrentText(previous_program)
        self.unregisterName.blockSignals(False)
        if not self.applyChannels.isChecked():
            self.channelTable.blockSignals(True); self.channelTable.setRowCount(0)
            for key, spec in settings.get("channels", {}).get("channels", {}).items():
                self.add_channel(key, spec)
            self.channelTable.blockSignals(False)
        if not self.applyChannels.isChecked() and not self.applyCommands.isChecked():
            self.commandTable.blockSignals(True); self.commandTable.setRowCount(0)
            for name, spec in sorted(settings.get("commands", {}).items()):
                row = self.commandTable.rowCount(); self.commandTable.insertRow(row)
                item = QTableWidgetItem(name)
                item.setFlags((item.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
                item.setCheckState(Qt.CheckState.Checked if spec.get("enabled", bool(spec.get("channels"))) else Qt.CheckState.Unchecked)
                self.commandTable.setItem(row, 0, item)
                for col, text in enumerate((", ".join(spec.get("channels", [])), spec.get("script", ""), spec.get("owner", "service-package")), 1):
                    value = QTableWidgetItem(text)
                    if col > 1:
                        value.setFlags(value.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.commandTable.setItem(row, col, value)
            self.commandTable.blockSignals(False)

    def execute(self):
        plan = self.plan
        if plan is None or plan.get("blocked") or not plan.get("steps") or self.task is not None:
            return
        if QMessageBox.question(self, "Execute reviewed operation",
                ("SIMULATE: " if self.demo else "") + "Execute the displayed plan? Each native package retains its own ownership. "
                "Cancellation takes effect at safe boundaries; completed steps may remain after a failure.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.cancel.clear()
        self.plan = None; self.tabs.setCurrentWidget(self.resultsText)
        self.start_task(lambda emit: execute_reviewed(plan, self.cancel, emit, demo=self.demo), self.completed, executing=True)

    def start_task(self, operation, receive, executing=False):
        if self.task is not None:
            return
        self.busy(True, executing)
        self.task = Task(lambda emit, progress: operation(emit), self)
        self.task.result.connect(receive); self.task.error.connect(self.failed)
        self._redactions.update(self.entered_secrets())
        self.task.message.connect(self.log); self.task.finished.connect(self.finished)
        self.task.start()

    def busy(self, active, executing=False):
        for index in range(self.tabs.count() - 2):
            self.tabs.widget(index).setEnabled(not active)
        for button in self.actionButtons:
            button.setEnabled(not active)
        self.executeButton.setEnabled(not active and self.plan is not None and not self.plan.get("blocked") and bool(self.plan.get("steps")))
        self.cancelButton.setEnabled(active and executing)
        self.progressBar.setRange(0, 0 if active else 100)

    def finished(self):
        task, self.task = self.task, None
        task.deleteLater(); self.busy(False)
        if self._refresh_again:
            self._refresh_again = False
            QTimer.singleShot(0, self.refresh)

    def failed(self, message):
        self.invalidate()
        self.log("Operation did not complete:\n" + message +
            "\nCompleted operations, retained files and recovery material may remain. Refresh status, inspect diagnostics and review a new plan before retrying.")
        self.tabs.setCurrentWidget(self.resultsText)

    def completed(self, result):
        self.invalidate()
        self.log(json.dumps(result, indent=2, default=str))
        self.tabs.setCurrentWidget(self.resultsText)
        self.statusLabel.setText("The displayed component states preceded execution. Refresh status before another operation.")
        for row in range(self.serviceForm.credentials.rowCount()):
            self.serviceForm.credentials.cellWidget(row, 1).clear()
            self.serviceForm.credentials.cellWidget(row, 2).setChecked(False)
        self.clear_programs()

    def entered_secrets(self):
        """Keep current password values out of displayed errors and progress."""
        return {self.serviceForm.credentials.cellWidget(row, 1).text()
                for row in range(self.serviceForm.credentials.rowCount())
                if self.serviceForm.credentials.cellWidget(row, 1).text()}

    def redacted(self, message):
        text = str(message)
        for value in sorted(self._redactions | self.entered_secrets(), key=len, reverse=True):
            text = text.replace(value, "[redacted]")
        return text

    def log(self, message):
        self.resultsText.appendPlainText(self.redacted(message))

    def request_cancel(self):
        self.cancel.set(); self.cancelButton.setEnabled(False)
        self.resultsText.appendPlainText("Cancellation requested. The active native operation and its verification must finish before remaining steps stop.")

    def diagnostics(self):
        def inspect(emit):
            if self.demo:
                return {"diagnostics": "Demo only; no host logs were read."}
            from .authorization import run_authorized
            return run_authorized({"kind": "service", "action": "diagnostics", "target": self.target}, emit)
        self.start_task(inspect, lambda value: (self.log(json.dumps(value, indent=2)), self.tabs.setCurrentWidget(self.resultsText)))

    def recovery_history(self):
        """Inspect fixed-location operation journals without choosing privileged paths."""
        def inspect(emit):
            if self.demo:
                return {"history": [], "detail": "Demo only; no recovery journals were read."}
            from .unified_backend import recovery_history
            return recovery_history(self.target, emit)
        self.start_task(inspect, lambda value: (self.log(json.dumps(value, indent=2)), self.tabs.setCurrentWidget(self.resultsText)))

    def recover_maintenance(self):
        """Explicitly confirm bounded orphan recovery; never clear dataset locks."""
        if QMessageBox.question(self, "Recover interrupted maintenance",
                "Inspect and release an orphaned maintenance lease only if its owner, participants and potential native tools have exited? "
                "Live or unknown processes block recovery. Evidence, dataset locks and retained data remain. Refresh and review a new operation afterward.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.invalidate()
        def recover(emit):
            if self.demo:
                return {"released": False, "detail": "Demo only; no maintenance lease inspected or changed."}
            from .unified_backend import recover_maintenance
            return recover_maintenance(self.target, emit)
        self.start_task(recover, lambda value: (self.log(json.dumps(value, indent=2)), self.tabs.setCurrentWidget(self.resultsText)))

    def save_report(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save displayed installation report", "meshcore-maintenance.log", "Log (*.log)")
        if filename:
            try:
                Path(filename).write_text(self.planText.toPlainText() + "\n\n" + self.resultsText.toPlainText(), encoding="utf-8")
            except OSError as error:
                QMessageBox.warning(self, "Report could not be saved", str(error))

    def closeEvent(self, event):
        if self.task is not None:
            self.request_cancel(); event.ignore()
        else:
            self.serviceForm.close(); event.accept()
