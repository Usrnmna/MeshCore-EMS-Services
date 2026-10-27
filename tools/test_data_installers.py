"""Exercise dataset distribution boundaries and executable archive integrity."""

import io
import json
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_data_installers as build


@contextmanager
def workspace():
    """Keep ephemeral fixtures inside the repository's writable build directory."""
    path = build.ROOT / ".build" / ("test-data-installers-" + uuid.uuid4().hex)
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def stage_wrapper_lease_fixture(install_root):
    """Isolate argument/logging tests from privileged machine-wide lease state.

    These tests verify wrapper entry/exit and child diagnostics. Lease ownership,
    contention and recovery have separate maintenance-lock tests. This helper
    never creates a real lease or touches Program Files.
    """
    directory = install_root / "payload/installers/desktop"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "maintenance_lock.ps1").write_text("""param([int]$AcquireForProcess=0, [int]$ReleaseForProcess=0, [string]$TokenOutput='')
$script:FixtureMaintenanceEvents = Join-Path $PSScriptRoot 'lease-events.txt'
function Enter-MeshCoreMaintenance {
    [IO.File]::AppendAllText($script:FixtureMaintenanceEvents, "enter`n")
    return 'fixture-lease'
}
function Exit-MeshCoreMaintenance($Lease) {
    if ($Lease -ne 'fixture-lease') { throw 'Unexpected fixture lease' }
    [IO.File]::AppendAllText($script:FixtureMaintenanceEvents, "exit`n")
}
if ($AcquireForProcess) { [IO.File]::WriteAllText($TokenOutput, ('f' * 32)) }
""", encoding="utf-8")
    return directory / "lease-events.txt"


class DataInstallerTests(unittest.TestCase):
    def test_explicit_source_inventory_excludes_downloads_and_service_runtime(self):
        """Live collection pointers, databases and main-service installers never ship."""
        paths = build.source_inventory()
        self.assertIn("installers/datasets/manage.py", paths)
        self.assertIn("installers/datasets/adapters.py", paths)
        self.assertIn("data/usgs_water/local_review_rules.json", paths)
        self.assertIn("meshcore_mqtt_service/scripts/water_local.py", paths)
        self.assertFalse(any("/generations/" in path or "/snapshots/" in path for path in paths))
        self.assertFalse(any(path.endswith(("inventory.json", "current.json", ".sqlite")) for path in paths))
        self.assertNotIn("installers/linux/install.sh", paths)
        self.assertNotIn("meshcore_mqtt_service/service.py", paths)
        for generated in ("data/basin_plans/INVENTORY.md", "data/basin_plans/REVIEW.md",
                          "data/flood_impacts/REVIEW.md", "data/usgs_water/INVENTORY.md",
                          "data/usgs_water/OBSERVATIONS.md", "data/usgs_water/ROUTING.md",
                          "data/usgs_water/LINK_REVIEW.md"):
            self.assertNotIn(generated, paths)
        self.assertTrue(all((build.ROOT / path).is_file() for path in paths))

    def test_staging_has_only_selected_seed_and_complete_hashes(self):
        """A bundle owns one seed and every shipped file has an exact integrity entry."""
        with workspace() as folder:
            payload = Path(folder) / "payload"
            metadata = build.stage_payload(payload, "landslide")
            self.assertEqual({p.name for p in (payload / "seeds").iterdir()}, {"landslide"})
            for relative, expected in metadata["files"].items():
                self.assertEqual(build.digest((payload / relative).read_bytes()), expected, relative)
            all_files = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
            self.assertEqual(all_files, set(metadata["files"]) | {"PAYLOAD-MANIFEST.json"})
            identity = json.loads((payload / "DATA-PACKAGE.json").read_text())
            self.assertEqual(identity, {"dataset": "landslide", "version": build.VERSION,
                                        "capabilities": ["retain-data-v1", "maintenance-lock-v1", "dataset-lock-recovery-v1"]})

    def test_download_only_collections_have_no_bundled_snapshot(self):
        for dataset in ("basin_plans", "flood_impacts", "usgs_water", "satellites"):
            self.assertEqual(build.seed_inventory(dataset), [])

    def test_independent_version_is_carried_by_payload_and_artifact(self):
        """A collection release need not share the service's release version."""
        with workspace() as folder:
            payload = folder / "payload"
            with patch.object(build, "source_inventory", return_value=[]):
                metadata = build.stage_payload(payload, "satellites", version="v1.2.3-data.1")
            artifact = build.linux_installer(payload, folder, "satellites", "linux-x86_64", "v1.2.3-data.1")
            self.assertEqual(metadata["version"], "v1.2.3-data.1")
            self.assertIn("v1.2.3-data.1", artifact.name)
            self.assertEqual(json.loads((payload / "DATA-PACKAGE.json").read_bytes())["version"], "v1.2.3-data.1")

    def test_linux_archives_are_independent_and_extractable(self):
        """All collection/architecture pairs retain distinct metadata and readable files."""
        with workspace() as folder:
            root = Path(folder)
            payload = root / "payload"
            payload.mkdir()
            (payload / "dataset-id.txt").write_bytes(b"fixture\n")
            paths = []
            for dataset in build.DATASETS:
                for platform, architecture in build.PLATFORMS.items():
                    result = build.linux_installer(payload, root, dataset, platform)
                    paths.append(result)
                    header, body = result.read_bytes().split(b"__MESHCORE_DATA_PAYLOAD__\n", 1)
                    self.assertIn(build.digest(body).encode(), header)
                    self.assertIn(architecture.encode(), header)
                    self.assertIn(dataset.encode(), header)
                    self.assertNotIn(b"\r", header)
                    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
                        self.assertEqual(archive.extractfile("dataset-id.txt").read(), b"fixture\n")
            self.assertEqual(len(set(paths)), 16)

    def test_seed_original_bytes_are_not_reencoded(self):
        """GeoJSON and provenance originals retain their recorded byte checksums."""
        with workspace() as folder:
            root = Path(folder)
            source = root / "data/ebmud/originals/check.geojson"
            source.parent.mkdir(parents=True)
            original = b'{"source":"\xe9"}\r\n'
            source.write_bytes(original)
            with patch.object(build, "source_inventory", return_value=[]):
                build.stage_payload(root / "payload", "ebmud", root)
            self.assertEqual((root / "payload/seeds/ebmud/originals/check.geojson").read_bytes(), original)


@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell.exe"), "Windows PowerShell 5.1 required")
class WindowsMaintenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Compile the production entry point, not a substitute launcher."""
        cls.tool_workspace = workspace()
        cls.tool_folder = cls.tool_workspace.__enter__()
        try:
            cls.executable = build.compile_windows_tool(cls.tool_folder / "compiled")
        except Exception:
            cls.tool_workspace.__exit__(*sys.exc_info())
            raise

    @classmethod
    def tearDownClass(cls):
        cls.tool_workspace.__exit__(None, None, None)

    def run_powershell(self, script, *arguments):
        """Execute the actual Windows PowerShell host used by Inno Setup."""
        return subprocess.run([shutil.which("powershell.exe"), "-NoProfile", "-NonInteractive",
                               "-ExecutionPolicy", "Bypass", "-File", str(script), *arguments],
                              capture_output=True, text=True, timeout=45)

    def test_compiled_tool_resolves_own_directory_and_preserves_arguments_and_exit_codes(self):
        """Exercise real EXE invocation, stderr, quoting and source parity."""
        with workspace() as folder:
            app = folder / "Dataset Tools With Spaces"
            scripts = app / "payload/installers/datasets/windows"
            scripts.mkdir(parents=True)
            lease_events = stage_wrapper_lease_fixture(app)
            shutil.copy2(self.executable, app / "Dataset.exe")
            shutil.copy2(build.ROOT / "installers/datasets/windows/dataset.ps1", scripts / "dataset.ps1")
            (scripts.parent / "manage.py").write_text(
                "import json, sys\nprint(json.dumps(sys.argv[1:]))\n"
                "print('diagnostic from child', file=sys.stderr)\n"
                "raise SystemExit(7 if sys.argv[1] == 'update' else 0)\n", encoding="utf-8")
            root = folder / "Data With Spaces & Apostrophe's"
            (app / "runtime.json").write_text(json.dumps({"dataset": "ebmud", "root": str(root),
                                                         "python": sys.executable}), encoding="utf-8")
            candidate = 'a' * 32
            for action, extra, code in [('status', [], 0), ('update', ['-Resume', candidate], 7),
                                        ('uninstall', ['-Purge'], 0)]:
                result = subprocess.run([str(app / 'Dataset.exe'), action, *extra], cwd=folder,
                                        capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                expected = [action, '--dataset', 'ebmud', '--root', str(root), '--payload', str(app / 'payload')]
                if action == 'update':
                    expected += ['--resume', candidate]
                if action == 'uninstall':
                    expected += ['--purge']
                self.assertEqual(json.loads(result.stdout.strip()), expected)
                self.assertIn('diagnostic from child', result.stderr)
            self.assertEqual(lease_events.read_text().splitlines(), ['enter', 'exit', 'enter', 'exit'])
            source = self.run_powershell(scripts / 'dataset.ps1', 'status')
            self.assertEqual(source.returncode, 0, source.stdout + source.stderr)
            invalid = subprocess.run([str(app / 'Dataset.exe'), 'status', '-Purge'],
                                     capture_output=True, text=True, timeout=30)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn('valid only with uninstall', invalid.stderr)
            for arguments in (['unknown-action'], ['update', '-Resume', 'bad'], ['status', '-Unknown', 'value']):
                invalid = subprocess.run([str(app / 'Dataset.exe'), *arguments],
                                         capture_output=True, text=True, timeout=30)
                self.assertNotEqual(invalid.returncode, 0, (arguments, invalid.stdout, invalid.stderr))
            menu = subprocess.run([str(app / 'Dataset.exe')], input='0\n',
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(menu.returncode, 0, menu.stdout + menu.stderr)
            self.assertIn('MeshCore EMS Dataset', menu.stdout)
            (app / 'runtime.json').unlink()
            missing = subprocess.run([str(app / 'Dataset.exe'), 'status'], cwd=folder,
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(missing.returncode, 1)
            self.assertIn('runtime.json', missing.stderr)

    def test_runtime_settings_first_publish_repair_and_failure_are_atomic(self):
        """Exercise the shipped publication function under PS5 without bootstrap I/O."""
        with workspace() as folder:
            source = str(build.ROOT / "installers/datasets/windows/install.ps1").replace("'", "''")
            fixture = folder / "repair.ps1"
            fixture.write_text("""$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5) { throw 'Windows PowerShell 5 is required' }
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('__SOURCE__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Installer syntax error' }
$definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Publish-RuntimeSettings' }, $true)
Invoke-Expression $definition.Extent.Text
$settings = Join-Path $PSScriptRoot 'runtime.json'
$pending = Join-Path $PSScriptRoot 'runtime.next.json'
[IO.File]::WriteAllText($pending, 'first generation')
Publish-RuntimeSettings $pending $settings
if ([IO.File]::ReadAllText($settings) -ne 'first generation') { throw 'Initial publication failed' }
[IO.File]::WriteAllText($pending, 'replacement generation')
Publish-RuntimeSettings $pending $settings
if ([IO.File]::ReadAllText($settings) -ne 'replacement generation') { throw 'Repair publication failed' }
if (Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.previous') { throw 'Temporary backup was not removed' }
$failed = $false
try { Publish-RuntimeSettings $pending $settings } catch { $failed = $true }
if (-not $failed -or [IO.File]::ReadAllText($settings) -ne 'replacement generation') { throw 'Failed replacement changed valid settings' }
""".replace("__SOURCE__", source), encoding="utf-8")
            result = self.run_powershell(fixture)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_logged_operations_drain_large_output_and_propagate_failure(self):
        """Hidden setup helpers retain output and preserve child exit status."""
        with workspace() as folder:
            install_root = folder / "Maintenance Root With Spaces"
            scripts = install_root / "payload/installers/datasets/windows"
            scripts.mkdir(parents=True)
            lease_events = stage_wrapper_lease_fixture(install_root)
            runner = build.ROOT / "installers/datasets/windows/run_logged.ps1"
            (scripts / "install.ps1").write_text("""param([string]$InstallRoot,[string]$Root)
if ($PSVersionTable.PSVersion.Major -ne 5) { exit 99 }
[Console]::Out.WriteLine(('x' * 262144))
[Console]::Error.WriteLine('expected fixture acquisition failure')
exit 7
""", encoding="utf-8")
            failure = self.run_powershell(runner, "-Action", "install", "-InstallRoot", str(install_root),
                                          "-Root", str(folder / "Data Root With Spaces"))
            self.assertEqual(failure.returncode, 7, failure.stdout + failure.stderr)
            result = json.loads(next((install_root / "logs").glob("install-*.result.json")).read_text())
            self.assertEqual(result["exit_code"], 7)
            self.assertGreater(Path(result["stdout"]).stat().st_size, 262144)
            self.assertIn("expected fixture acquisition failure", Path(result["stderr"]).read_text())
            (scripts / "uninstall.ps1").write_text("""param([string]$InstallRoot,[switch]$Purge)
if (-not $Purge) { exit 8 }
[Console]::Out.WriteLine('successful fixture removal')
exit 0
""", encoding="utf-8")
            success = self.run_powershell(runner, "-Action", "uninstall", "-InstallRoot", str(install_root), "-Purge")
            self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
            result = json.loads(next((install_root / "logs").glob("uninstall-*.result.json")).read_text())
            self.assertEqual(result["exit_code"], 0)
            self.assertIn("successful fixture removal", Path(result["stdout"]).read_text())
            self.assertEqual(lease_events.read_text().splitlines(), ['enter', 'exit', 'enter', 'exit'])

    def test_missing_maintenance_script_records_nonzero_result(self):
        with workspace() as folder:
            runner = build.ROOT / "installers/datasets/windows/run_logged.ps1"
            lease_events = stage_wrapper_lease_fixture(folder)
            result = self.run_powershell(runner, "-Action", "install", "-InstallRoot", str(folder))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            status = json.loads(next((folder / "logs").glob("*.result.json")).read_text())
            self.assertEqual(status["exit_code"], 1)
            self.assertIn("maintenance script is missing", Path(status["stderr"]).read_text())
            self.assertEqual(lease_events.read_text().splitlines(), ['enter', 'exit'])

    @unittest.skipUnless((build.ROOT / ".build/inno/ISCC.exe").is_file(), "Local Inno compiler unavailable")
    def test_compiled_setup_failure_and_silent_uninstall_refusal_return_nonzero(self):
        """Compile the real callbacks with harmless scripts and an isolated user install."""
        with workspace() as folder:
            payload = folder / "payload"
            scripts = payload / "installers/datasets/windows"
            scripts.mkdir(parents=True)
            for filename in ("run_logged.ps1",):
                shutil.copy2(build.ROOT / "installers/datasets/windows" / filename, scripts / filename)
            stage_wrapper_lease_fixture(folder)
            shutil.copy2(build.ROOT / "LICENSE", payload / "LICENSE")
            for action in ("install", "uninstall"):
                (scripts / (action + ".ps1")).write_text("param([string]$InstallRoot)\nexit 7\n", encoding="utf-8")
            template = (build.ROOT / "installers/datasets/windows/setup.iss").read_text()
            # Retain the real Inno callbacks but isolate their lease worker and
            # token path from privileged machine state in this per-user fixture.
            include = (build.ROOT / "installers/desktop/maintenance_lock.iss").read_text()
            include = include.replace("{autopf}\\MeshCore-EMS-Maintenance\\inno-", "{tmp}\\fixture-inno-")
            (folder / "maintenance_lock.iss").write_text(include, encoding="utf-8")
            template = template.replace('..\\..\\desktop\\maintenance_lock.iss', 'maintenance_lock.iss')
            # The production callbacks remain unchanged; this fixture needs no
            # elevation and uses a unique per-user registration for test cleanup.
            template = template.replace("PrivilegesRequired=admin", "PrivilegesRequired=lowest")
            template = template.replace("DefaultGroupName=MeshCore EMS\\Datasets\\{#DatasetName}",
                                        "DefaultGroupName=MeshCore EMS Installer Test\\{#Dataset}")
            # A non-admin fixture must not touch the production shortcut namespace.
            template = template.replace('{commonprograms}\\MeshCore EMS Data', '{userprograms}\\MeshCore EMS Installer Test')
            fixture = folder / "setup.iss"
            fixture.write_text(template, encoding="utf-8")
            # Keep the AppId short enough that Inno does not hash/truncate its
            # uninstall registry key; production collection identifiers do too.
            dataset = "fixture-" + uuid.uuid4().hex[:12]
            compile_result = subprocess.run([str(build.ROOT / ".build/inno/ISCC.exe"),
                "/Qp", "/DPayloadDir=" + str(payload), "/DReleaseDir=" + str(folder),
                "/DDataset=" + dataset, "/DReleaseVersion=0.0.0", "/DMaintenanceExe=" + str(self.executable), str(fixture)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            setup = folder / ("MeshCore-EMS-Data-" + dataset + "-0.0.0-windows-x64-setup.exe")
            app = folder / "installed"
            uninstaller = app / "unins000.exe"
            try:
                failed = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                         "/DIR=" + str(app), "/LOG=" + str(folder / "setup.log")], timeout=45)
                self.assertEqual(failed.returncode, 20, (folder / 'setup.log').read_text(errors='replace'))
                self.assertTrue(uninstaller.is_file())
                self.assertTrue((app / 'Dataset.exe').is_file())
                import winreg
                labels = []
                for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                        try:
                            with winreg.OpenKey(hive,
                                    'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MeshCore-EMS-Data-' + dataset + '_is1',
                                    access=winreg.KEY_READ | view) as key:
                                labels.append(winreg.QueryValueEx(key, 'DisplayName')[0])
                        except FileNotFoundError:
                            pass
                self.assertTrue(labels, (folder / 'setup.log').read_text(errors='replace')[-9000:])
                self.assertEqual(set(labels), {'MeshCore EMS Dataset - ' + dataset})
                refused = subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                          "/LOG=" + str(folder / "refusal.log")], timeout=45)
                self.assertNotEqual(refused.returncode, 0)
                self.assertTrue(uninstaller.is_file(), "Refused removal must preserve maintenance tools")
            finally:
                if uninstaller.is_file():
                    (app / "payload/installers/datasets/windows/uninstall.ps1").write_text(
                        "param([string]$InstallRoot)\nexit 0\n", encoding="utf-8")
                    removed = subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=45)
                    self.assertEqual(removed.returncode, 0)
                    self.assertFalse((app / 'Dataset.exe').exists())


if __name__ == "__main__":
    unittest.main()
