"""Build online Windows x64 and Linux x86_64/ARM64 installers from this workspace.

Windows compilation needs the .NET Framework C# compiler and Inno Setup 6.7+.
Linux .run payloads are architecture-neutral source; architecture is checked at install.
No Python runtimes, pip wheels, environments or private state are embedded.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

from package_services import package_files, PACKAGES

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0-alpha"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_files():
    files = {ROOT / p for p in ("README.md", "RELEASE_NOTES.md", "INSTALL.md", "LICENSE")}
    for package in PACKAGES:
        files.update(package_files(package))
    for folder in ("satellite_database", "data", "installers", "tools"):
        for path in (ROOT / folder).rglob("*"):
            relative = path.relative_to(ROOT)
            if (not path.is_file() or any(p.startswith('.') or p in {'__pycache__', 'runtime'} for p in relative.parts)
                    or path.suffix in {'.pyc', '.pyo'} or path.name.endswith(('-wal', '-shm'))):
                continue
            files.add(path)
    return sorted(files)


def stage_payload(destination):
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for path in source_files():
        relative = path.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        # Linux scripts must have LF line endings even when built from Windows Git.
        if path.suffix in {'.sh', '.service'} or path.name == 'satellite-catalog':
            data = data.replace(b'\r\n', b'\n')
        target.write_bytes(data)
        manifest[relative.as_posix()] = sha(data)
    (destination / 'PAYLOAD-MANIFEST.json').write_text(
        json.dumps({'version': VERSION, 'files': manifest}, indent=2) + '\n', encoding='utf-8')


def linux_installer(payload, output, arch):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for path in sorted(payload.rglob('*')):
            if not path.is_file():
                continue
            data = path.read_bytes()
            entry = tarfile.TarInfo(path.relative_to(payload).as_posix())
            entry.size = len(data)
            entry.mode = 0o755 if path.suffix == '.sh' or path.name == 'satellite-catalog' else 0o644
            archive.addfile(entry, io.BytesIO(data))
    archive_bytes = buffer.getvalue()
    header = '''#!/usr/bin/env bash
set -euo pipefail
expected_arch="@ARCH@"
expected_sha="@SHA@"
case "${1:-}" in
    --help) echo 'MeshCore EMS v0.2.0-alpha online installer (@ARCH@)'
        echo 'sudo bash installer.run [--port DEVICE] [--channel NAME] [--no-start]'
        echo 'Inspection: bash installer.run --check | --extract EMPTY_DIRECTORY'; exit 0 ;;
esac
line=$(awk '/^__MESHCORE_PAYLOAD__$/{print NR+1; exit}' "$0")
actual_sha=$(tail -n +"$line" "$0" | sha256sum | cut -d ' ' -f1)
[[ $actual_sha == "$expected_sha" ]] || { echo 'Installer payload checksum mismatch.' >&2; exit 1; }
if [[ ${1:-} == --check ]]; then echo 'v0.2.0-alpha @ARCH@: payload checksum verified'; exit 0; fi
if [[ ${1:-} == --extract ]]; then
    destination=${2:?Specify an empty destination directory}
    mkdir -p -- "$destination"
    [[ -z $(ls -A -- "$destination") ]] || { echo 'Extraction directory must be empty.' >&2; exit 1; }
    tail -n +"$line" "$0" | tar -xz --no-same-owner -C "$destination"
    echo "Extracted workspace to $destination"; exit 0
fi
[[ $(uname -m) == "$expected_arch" ]] || { echo "Use the installer for $(uname -m), not $expected_arch." >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo 'Run the installer with sudo.' >&2; exit 1; }
temporary=$(mktemp -d /tmp/meshcore-ems.XXXXXXXX)
cleanup() { case "$temporary" in /tmp/meshcore-ems.*) rm -rf -- "$temporary" ;; esac; }
trap cleanup EXIT
tail -n +"$line" "$0" | tar -xz --no-same-owner -C "$temporary"
bash "$temporary/installers/linux/install.sh" "$@"
exit 0
__MESHCORE_PAYLOAD__
'''.replace('@ARCH@', arch).replace('@SHA@', sha(archive_bytes))
    label = 'raspberry-pi-arm64' if arch == 'aarch64' else 'linux-x86_64'
    path = output / f'MeshCore-EMS-v{VERSION}-{label}.run'
    path.write_bytes(header.encode() + archive_bytes)
    path.chmod(0o755)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', type=Path, default=ROOT / '.build/inno/ISCC.exe')
    parser.add_argument('--linux-only', action='store_true')
    args = parser.parse_args()
    output = ROOT / 'dist' / f'v{VERSION}'
    output.mkdir(parents=True, exist_ok=True)
    import uuid
    work = ROOT / '.build'
    work.mkdir(exist_ok=True)
    # Keep a unique build snapshot for audit/reproduction; never overwrite a live install.
    build = work / ('installers-' + uuid.uuid4().hex[:12])
    build.mkdir()
    payload = build / 'payload'
    stage_payload(payload)
    artifacts = [linux_installer(payload, output, arch) for arch in ('x86_64', 'aarch64')]
    if not args.linux_only:
        csc = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        subprocess.run([str(csc), '/nologo', '/target:exe', '/platform:x64',
                        '/r:System.ServiceProcess.dll', '/out:' + str(payload / 'MeshCoreEMS.Service.exe'),
                        str(ROOT / 'installers/windows/ServiceHost.cs')], check=True)
        manifest_path = payload / 'PAYLOAD-MANIFEST.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files']['MeshCoreEMS.Service.exe'] = sha((payload / 'MeshCoreEMS.Service.exe').read_bytes())
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        subprocess.run([str(args.iscc), '/Qp', '/DPayloadDir=' + str(payload),
                        '/DReleaseDir=' + str(output), str(ROOT / 'installers/windows/setup.iss')], check=True)
        artifacts.append(output / f'MeshCore-EMS-v{VERSION}-windows-x64-setup.exe')
    shutil.copy2(ROOT / 'INSTALL.md', output / 'INSTALL.md')
    shutil.copy2(ROOT / 'installers/VALIDATION.md', output / 'VALIDATION.md')
    (output / 'SHA256SUMS.txt').write_text(''.join(f'{sha(path.read_bytes())}  {path.name}\n' for path in artifacts), encoding='utf-8')
    bundle = output.parent / f'MeshCore-EMS-v{VERSION}-installers.zip'
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in artifacts + [output / name for name in ('INSTALL.md', 'VALIDATION.md', 'SHA256SUMS.txt')]:
            archive.write(path, path.name)
    bundle.with_suffix('.zip.sha256').write_text(f'{sha(bundle.read_bytes())}  {bundle.name}\n', encoding='utf-8')
    print('Payload snapshot:', payload)
    for path in artifacts:
        print(f'{path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)')
    print('Combined bundle:', bundle.relative_to(ROOT))


if __name__ == '__main__':
    main()
