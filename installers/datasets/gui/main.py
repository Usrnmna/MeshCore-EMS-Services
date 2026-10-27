"""Run unified graphical maintenance, with independent dataset-only mode available."""

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
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--desktop-worker"]:
        if len(arguments) != 2:
            raise ValueError("A desktop worker requires exactly one request file")
        from installers.desktop.authorization import worker_main
        return worker_main(arguments[1])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Simulated status and execution; no installation or discovery")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--smoke-test", action="store_true", help="With --demo, load the form and exit without host discovery")
    parser.add_argument("--datasets-only", action="store_true", help="Open the independent Dataset Manager interface")
    location = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3] / "dist/v0.9.6-beta"
    parser.add_argument("--installers", type=Path, default=location)
    args = parser.parse_args(arguments)
    if args.smoke_test and not args.demo:
        parser.error("--smoke-test requires --demo")
    from PyQt6.QtWidgets import QApplication
    from installers.datasets.gui.window import DatasetWindow
    application = QApplication([sys.argv[0]])
    application.setApplicationName("MeshCore EMS Installation and Maintenance")
    if args.datasets_only:
        dataset_folder = args.installers / "datasets" if (args.installers / "datasets").is_dir() else args.installers
        window = DatasetWindow(args.root.resolve(), dataset_folder.resolve(), native_target(), args.demo)
    else:
        from installers.desktop.unified_window import UnifiedWindow
        window = UnifiedWindow(args.root.resolve(), args.installers.resolve(), native_target(), args.demo)
    window.show()
    if args.smoke_test:
        from PyQt6.QtCore import QTimer
        timer = QTimer(application)
        def check():
            if window.task is None:
                ready = window.datasetTree.topLevelItemCount() == 8 and (args.datasets_only or bool(window.snapshot))
                application.exit(0 if ready else 1)
        timer.timeout.connect(check)
        timer.start(100)
        QTimer.singleShot(30000, lambda: application.exit(2))
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
