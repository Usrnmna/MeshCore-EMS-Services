"""Start the independent desktop service setup/maintenance window."""
from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main(argv=None):
    """Handle native workers before importing Qt; demo never discovers the host."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--history-smoke-helper"]:
        if len(arguments) != 2:
            raise ValueError("A synthetic history helper accepts one fixed mode")
        from installers.desktop.history_smoke import helper_main
        return helper_main(arguments[1])
    if arguments[:1] in (["--history-read"], ["--history-session"]):
        if len(arguments) != 1:
            raise ValueError("History helpers accept no path or program arguments")
        from installers.desktop.history_process import helper_main
        return helper_main(arguments[0].removeprefix("--history-"))
    if len(arguments) == 2 and arguments[0] == "--desktop-worker":
        from installers.desktop.authorization import worker_main
        return worker_main(arguments[1])
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installers", type=Path)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--smoke-report", type=Path, help="Write synthetic smoke results as JSON; requires --demo --smoke-test")
    args = parser.parse_args(arguments)
    if args.smoke_test and not args.demo:
        parser.error("--smoke-test requires --demo")
    if args.smoke_report and not args.smoke_test:
        parser.error("--smoke-report requires --smoke-test")
    from contextlib import nullcontext
    from PyQt6.QtWidgets import QApplication
    from installers.datasets.gui.discovery import native_target
    from installers.desktop.service_window import ServiceWindow
    from installers.desktop.version import VERSION
    location = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2] / "dist" / VERSION
    folder = args.installers or (location / "service-installers" if getattr(sys, "frozen", False) else location)
    if args.installers is None and not folder.is_dir() and (location.parent / "dataset-manager/service-installers").is_dir():
        folder = location.parent / "dataset-manager/service-installers"
    application = QApplication([sys.argv[0]])
    application.setApplicationName("MeshCore EMS Service Setup")
    if args.smoke_test:
        from installers.desktop.history_smoke import demo_guard, schedule_gui_smoke
    with demo_guard() if args.smoke_test else nullcontext([]) as violations:
        window = ServiceWindow(folder.resolve(), native_target(), demo=args.demo)
        window.show()
        if args.smoke_test:
            schedule_gui_smoke(application, window, args.smoke_report, violations)
        return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
