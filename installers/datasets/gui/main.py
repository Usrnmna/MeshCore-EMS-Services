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
    if arguments[:1] == ["--desktop-worker"]:
        if len(arguments) != 2:
            raise ValueError("A desktop worker requires exactly one request file")
        from installers.desktop.authorization import worker_main
        return worker_main(arguments[1])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Simulated status and execution; no installation or discovery")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--smoke-test", action="store_true", help="With --demo, load the form and exit without host discovery")
    parser.add_argument("--smoke-report", type=Path, help="Write synthetic smoke results as JSON; requires --demo --smoke-test")
    parser.add_argument("--datasets-only", action="store_true", help="Open the independent Dataset Manager interface")
    from installers.desktop.version import VERSION
    location = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3] / "dist" / VERSION
    parser.add_argument("--installers", type=Path, default=location)
    args = parser.parse_args(arguments)
    if args.smoke_test and not args.demo:
        parser.error("--smoke-test requires --demo")
    if args.smoke_report and not args.smoke_test:
        parser.error("--smoke-report requires --smoke-test")
    from contextlib import nullcontext
    from PyQt6.QtWidgets import QApplication
    from installers.datasets.gui.window import DatasetWindow
    application = QApplication([sys.argv[0]])
    application.setApplicationName("MeshCore EMS Installation and Maintenance")
    if args.smoke_test:
        from installers.desktop.history_smoke import demo_guard, schedule_gui_smoke
    with demo_guard() if args.smoke_test else nullcontext([]) as violations:
        if args.datasets_only:
            dataset_folder = args.installers / "datasets" if (args.installers / "datasets").is_dir() else args.installers
            window = DatasetWindow(args.root.resolve(), dataset_folder.resolve(), native_target(), args.demo)
        else:
            from installers.desktop.unified_window import UnifiedWindow
            window = UnifiedWindow(args.root.resolve(), args.installers.resolve(), native_target(), args.demo)
        window.show()
        if args.smoke_test:
            schedule_gui_smoke(application, window, args.smoke_report, violations)
        return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
