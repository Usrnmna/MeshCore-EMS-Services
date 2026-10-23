"""Run the editable dataset GUI from source or a native PyInstaller distribution."""

import argparse
from pathlib import Path
import sys

# Direct Python invocation and frozen imports use the same package modules.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from installers.datasets.manage import default_root
from installers.datasets.gui.discovery import native_target


def main(argv=None):
    """Parse paths and demo mode before loading Qt; --help needs no Qt runtime."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Simulated status and execution; no installation or discovery")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--smoke-test", action="store_true", help="With --demo, load the form and exit without host discovery")
    location = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3] / "dist/v0.9.6-beta"
    parser.add_argument("--installers", type=Path, default=location / "datasets")
    args = parser.parse_args(argv)
    if args.smoke_test and not args.demo:
        parser.error("--smoke-test requires --demo")
    from PyQt6.QtWidgets import QApplication
    from installers.datasets.gui.window import DatasetWindow
    application = QApplication([sys.argv[0]])
    application.setApplicationName("MeshCore EMS Dataset Manager")
    window = DatasetWindow(args.root.resolve(), args.installers.resolve(), native_target(), args.demo)
    window.show()
    if args.smoke_test:
        from PyQt6.QtCore import QTimer
        timer = QTimer(application)
        def check():
            if window.task is None:
                application.exit(0 if window.datasetTree.topLevelItemCount() == 8 else 1)
        timer.timeout.connect(check)
        timer.start(100)
        QTimer.singleShot(30000, lambda: application.exit(2))
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
