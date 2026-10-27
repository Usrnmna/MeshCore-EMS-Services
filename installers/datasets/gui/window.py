"""Qt controller; the maintained layout stays in main_window.ui."""

from pathlib import Path
import threading

from PyQt6 import uic
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QTreeWidgetItem

from .catalog import DATASETS, LABELS
from .discovery import demo_snapshot, inspect
from .privileges import execute_reviewed, inspect_with_authorization
from .planning import make_plan


class Task(QThread):
    """Run blocking discovery or a batch off the UI thread; return through signals."""

    result = pyqtSignal(object)
    error = pyqtSignal(str)
    message = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation(self.message.emit, self.progress.emit))
        except Exception as error:
            self.error.emit(str(error))


class DatasetWindow(QMainWindow):
    """Expose planning, confirmation and asynchronous execution over native tools."""

    def __init__(self, root, folder, target, demo=False):
        super().__init__()
        uic.loadUi(str(Path(__file__).with_name("main_window.ui")), self)
        self.target, self.demo = target, demo
        self.snapshot = self.plan = self.task = None
        self.cancel = threading.Event()
        self.dataRootEdit.setText(str(root))
        self.installerFolderEdit.setText(str(folder))
        self.modeLabel.setText(("DEMO — simulated states and actions; no installation, downloads or deletion. " if demo else "") +
                               target + " | Setup installs tools AND initial data; no separate tools-only mode.")
        self.dataRootEdit.textChanged.connect(self.invalidate)
        self.installerFolderEdit.textChanged.connect(self.invalidate)
        self.browseDataButton.clicked.connect(lambda: self.browse(self.dataRootEdit))
        self.browseInstallersButton.clicked.connect(lambda: self.browse(self.installerFolderEdit))
        self.refreshButton.clicked.connect(self.refresh)
        self.selectAllButton.clicked.connect(lambda: self.select_all(True))
        self.clearSelectionButton.clicked.connect(lambda: self.select_all(False))
        self.datasetTree.itemChanged.connect(self.invalidate)
        self.datasetTree.currentItemChanged.connect(self.show_details)
        for button, action in ((self.installSelectedButton, "install_selected"),
                               (self.uninstallSelectedButton, "uninstall_selected"),
                               (self.missingPackagesButton, "missing_packages"),
                               (self.missingDataButton, "missing_data"),
                               (self.uninstallAllButton, "uninstall_all")):
            button.clicked.connect(lambda checked=False, action=action: self.prepare(action))
        self.executeButton.clicked.connect(self.execute)
        self.cancelButton.clicked.connect(self.request_cancel)
        self.saveLogButton.clicked.connect(self.save_log)
        self.datasetTree.setColumnWidth(0, 195)
        self.datasetTree.setColumnWidth(1, 390)
        self.datasetTree.setColumnWidth(2, 180)
        QTimer.singleShot(0, self.refresh)

    def paths(self):
        """Reject ambiguous roots and unsupported wrapper characters before planning."""
        values = [self.dataRootEdit.text().strip(), self.installerFolderEdit.text().strip()]
        if any(not value or any(character in value for character in ('"', '\n', '\r', '\x00')) for value in values):
            raise ValueError("Enter paths without quotes or line breaks")
        paths = [Path(value).expanduser() for value in values]
        if not all(path.is_absolute() for path in paths):
            raise ValueError("Data root and installer folder must be absolute paths")
        return tuple(path.resolve() for path in paths)

    def browse(self, field):
        selected = QFileDialog.getExistingDirectory(self, "Choose directory", field.text())
        if selected:
            field.setText(selected)

    def invalidate(self, *args):
        self.plan = None
        self.executeButton.setEnabled(False)
        self.planText.setPlainText("Choose an operation to create a fresh plan for the current selection and locations.")

    def selected(self):
        return [self.datasetTree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole)
                for index in range(self.datasetTree.topLevelItemCount())
                if self.datasetTree.topLevelItem(index).checkState(0) == Qt.CheckState.Checked]

    def select_all(self, checked):
        for index in range(self.datasetTree.topLevelItemCount()):
            self.datasetTree.topLevelItem(index).setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def populate(self, snapshot):
        """Retain checkbox selections while replacing verified state and details."""
        checked = set(self.selected())
        self.snapshot = snapshot
        self.datasetTree.blockSignals(True)
        self.datasetTree.clear()
        for name, (label, description) in LABELS.items():
            state = snapshot.collections[name]
            package_status = state.package.state
            if state.package.root and state.package.root != snapshot.root:
                package_status += " (other root)"
            row = QTreeWidgetItem([label, description, ", ".join(LABELS[dep][0] for dep in DATASETS[name]) or "None",
                                  package_status, state.data])
            row.setData(0, Qt.ItemDataRole.UserRole, name)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked)
            detail = f"{name}\nTools: {state.package.prefix}\nRecorded data root: {state.package.root}\n{state.package.detail}\n{state.detail}"
            row.setData(0, Qt.ItemDataRole.UserRole + 1, detail)
            for column in range(5):
                row.setToolTip(column, detail)
            self.datasetTree.addTopLevelItem(row)
        self.datasetTree.blockSignals(False)

    def show_details(self, row, previous=None):
        if row:
            self.detailsLabel.setText(row.data(0, Qt.ItemDataRole.UserRole + 1))

    def busy(self, active, executing=False):
        for widget in (self.locationsGroup, self.selectionGroup, self.actionsGroup):
            widget.setEnabled(not active)
        self.executeButton.setEnabled(not active and self.plan is not None and bool(self.plan.operations) and not self.plan.blocked)
        self.cancelButton.setEnabled(active and executing)
        self.progressBar.setRange(0, 0 if active else 100)
        if not active:
            self.progressBar.setValue(0)

    def start(self, operation, receive, executing=False):
        """Keep each QThread alive until finished; all widget updates stay on the UI thread."""
        if self.task is not None:
            return
        self.busy(True, executing)
        task = Task(operation, self)
        self.task = task
        task.result.connect(receive)
        task.error.connect(self.failed)
        task.message.connect(self.log)
        task.progress.connect(self.progress)
        task.finished.connect(self.finished)
        task.start()

    def finished(self):
        task, self.task = self.task, None
        task.deleteLater()
        self.busy(False)
        self.statusbar.showMessage("Ready — review results or refresh status.")

    def failed(self, message):
        self.plan = None
        self.resultsText.setPlainText("Operation not completed:\n" + message)
        self.outputTabs.setCurrentWidget(self.resultsTab)
        self.log(message)

    def log(self, message):
        self.logText.appendPlainText(message.rstrip())
        self.statusbar.showMessage(message.strip().splitlines()[0][:180] if message.strip() else "Working…")

    def progress(self, complete, total):
        self.progressBar.setRange(0, max(total, 1))
        self.progressBar.setValue(complete)

    def scan(self, root, emit):
        return demo_snapshot(root, self.target) if self.demo else inspect_with_authorization(root, self.target, emit)

    def refresh(self):
        self.invalidate()
        try:
            root, _ = self.paths()
        except ValueError as error:
            self.failed(str(error))
            return
        self.start(lambda emit, progress: self.scan(root, emit), self.populate)

    def prepare(self, action):
        """Fresh discovery and artifact hashing precede every reviewable plan."""
        self.invalidate()
        try:
            root, folder = self.paths()
        except ValueError as error:
            self.failed(str(error))
            return
        selected = self.selected()
        def prepare(emit, progress):
            snapshot = self.scan(root, emit)
            return snapshot, make_plan(snapshot, action, selected, folder, demo=self.demo)
        self.start(prepare, self.show_plan)

    def show_plan(self, value):
        snapshot, plan = value
        self.populate(snapshot)
        self.plan = plan
        self.planText.setPlainText(plan.text())
        self.outputTabs.setCurrentWidget(self.planTab)

    def execute(self):
        """Confirm the reviewed batch once, then recheck it before any mutation."""
        plan = self.plan
        if plan is None or plan.blocked or not plan.operations or self.task is not None:
            return
        removing = plan.action.startswith("uninstall")
        names = ", ".join(LABELS[operation.dataset][0] for operation in plan.operations)
        message = ("SIMULATE " if self.demo else "Execute ") + ("removal" if removing else "installation") + " for: " + names + "?"
        if removing:
            message += "\nPackage tools and managed data will be removed under the displayed retention policy. Stop EMS through Service Setup and Maintenance first; active or unknown service state blocks removal."
        if QMessageBox.question(self, "Confirm reviewed batch", message,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        _, folder = self.paths()
        self.cancel.clear()
        self.outputTabs.setCurrentWidget(self.logTab)
        self.log(plan.text())
        self.start(lambda emit, progress: execute_reviewed(plan, folder, self.cancel, emit, progress), self.show_results, executing=True)

    def show_results(self, results):
        self.plan = None
        self.resultsText.setPlainText("\n\n".join(f"{item.dataset}: {item.outcome}\n{item.detail}" for item in results) or "No operations.")
        self.outputTabs.setCurrentWidget(self.resultsTab)
        self.detailsLabel.setText("The table shows the pre-operation snapshot. Refresh Status to inspect the completed batch.")

    def request_cancel(self):
        self.cancel.set()
        self.cancelButton.setEnabled(False)
        self.log("Cancellation requested. The current package and its verification will finish; no later package will start.")

    def save_log(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save log and results", "dataset-manager.log", "Log (*.log)")
        if filename:
            try:
                Path(filename).write_text(self.logText.toPlainText() + "\n\n" + self.resultsText.toPlainText(), encoding="utf-8")
            except OSError as error:
                QMessageBox.warning(self, "Cannot save log", str(error))

    def closeEvent(self, event):
        if self.task is not None:
            self.request_cancel()
            self.statusbar.showMessage("Wait for the current operation/check to finish before closing.")
            event.ignore()
        else:
            event.accept()
