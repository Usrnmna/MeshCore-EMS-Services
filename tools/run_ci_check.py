"""Run a CI command, retain its combined output, and propagate its exit status.

Usage: python tools/run_ci_check.py REPORT COMMAND [ARGUMENT ...]
Reports are ordinary text files; commands execute directly without a shell.
"""
from pathlib import Path
import subprocess
import sys


def run_check(report, command):
    """Stream output to the console and report without converting failures to success."""
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open('wb') as output:
        header = f'Python: {sys.version}\nPlatform: {sys.platform}\nCommand: {command!r}\n'.encode()
        output.write(header)
        output.flush()
        try:
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as child:
                while chunk := child.stdout.read1(65536):
                    output.write(chunk)
                    output.flush()
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                status = child.wait()
        except OSError as error:
            output.write(f'Command could not start: {error}\n'.encode())
            raise
        output.write(f'\nExit status: {status}\n'.encode())
    return status if status >= 0 else 128 - status


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise SystemExit('Usage: run_ci_check.py REPORT COMMAND [ARGUMENT ...]')
    raise SystemExit(run_check(Path(sys.argv[1]), sys.argv[2:]))
