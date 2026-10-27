"""Start the independent desktop service setup/maintenance window."""
from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main(argv=None):
    """Handle native workers before importing Qt; demo never discovers the host."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) == 2 and arguments[0] == "--desktop-worker":
        from installers.desktop.authorization import worker_main
        return worker_main(arguments[1])
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installers", type=Path)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(arguments)
    if args.smoke_test and not args.demo:
        parser.error("--smoke-test requires --demo")
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from installers.datasets.gui.discovery import native_target
    from installers.desktop.service_window import ServiceWindow
    location = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2] / "dist/v0.9.6-beta"
    folder = args.installers or (location / "service-installers" if getattr(sys, "frozen", False) else location)
    if args.installers is None and not folder.is_dir() and (location.parent / "dataset-manager/service-installers").is_dir():
        folder = location.parent / "dataset-manager/service-installers"
    application = QApplication([sys.argv[0]])
    application.setApplicationName("MeshCore EMS Service Setup")
    window = ServiceWindow(folder.resolve(), native_target(), demo=args.demo)
    window.show()
    if args.smoke_test:
        QTimer.singleShot(100, application.quit)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
