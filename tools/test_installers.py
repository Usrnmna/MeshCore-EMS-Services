"""Validate upgrade preservation and release payload boundaries without OS installation."""

import importlib.util
from contextlib import closing, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_installers

spec = importlib.util.spec_from_file_location(
    "installer_configure", ROOT / "installers/configure.py"
)
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class InstallerTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux") and getattr(os, "geteuid", lambda: -1)() == 0,
                         "Native Linux root permission integration test")
    def test_private_venv_is_readable_by_service_account_without_write_access(self):
        """Run a real interpreter as the service identity through restricted runtime directories."""
        import grp
        import pwd
        import stat
        try:
            account = pwd.getpwnam("meshcore-ems")
            group = grp.getgrnam("meshcore-ems")
        except KeyError:
            self.skipTest("Native service installation account is required")
        source = (ROOT / "installers/linux/install.sh").read_text()
        start = source.index("grant_service_venv_access() {")
        function = source[start:source.index("\n}", start) + 2]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o755)
            environment = root / ".venv"
            binary = environment / "bin"
            library = environment / "lib"
            binary.mkdir(parents=True)
            library.mkdir()
            for directory in (environment, binary, library):
                directory.chmod(0o700)
            module = library / "permission_fixture.py"
            module.write_text("VALUE = 42\n")
            module.chmod(0o600)
            sentinel = root / "outside-runtime"
            sentinel.write_text("outside bytes")
            sentinel.chmod(0o600)
            (library / "outside-link").symlink_to(sentinel)
            target = Path("/usr/bin/python3").resolve()
            (binary / "python").symlink_to(target)
            before = {path: (path.stat().st_uid, path.stat().st_gid, stat.S_IMODE(path.stat().st_mode))
                      for path in (sentinel, target)}
            subprocess.run(["bash", "-eu", "-c", function + '\ngrant_service_venv_access "$1"',
                            "permissions-test", str(environment)], check=True, capture_output=True, text=True)
            for path in (environment, binary, library, module):
                metadata = path.stat()
                self.assertEqual(metadata.st_uid, 0)
                self.assertEqual(metadata.st_gid, group.gr_gid)
                self.assertEqual(stat.S_IMODE(metadata.st_mode) & 0o027, 0)
            for path, expected in before.items():
                metadata = path.stat()
                self.assertEqual((metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)), expected)
            command = ["runuser", "-u", "meshcore-ems", "--", str(binary / "python"), "-B", "-c",
                       "import os,sys; sys.path.insert(0,sys.argv[1]); import permission_fixture; "
                       "print(os.geteuid(),permission_fixture.VALUE); "
                       "assert not os.access(sys.argv[2],os.W_OK)", str(library), str(module)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(completed.stdout.strip(), f"{account.pw_uid} 42")

    @unittest.skipUnless(sys.platform == "win32", "Windows ACL integration test")
    def test_private_installation_grants_service_read_without_replacing_owner_permissions(self):
        """Actual ACL changes cover existing protected descendants in a private custom install."""
        with tempfile.TemporaryDirectory() as folder:
            script = r'''
param([string]$Installer, [string]$Root)
$ErrorActionPreference = 'Stop'
$owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
$private = New-Object System.Security.AccessControl.DirectorySecurity
$private.SetAccessRuleProtection($true, $false)
$private.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($owner, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
Set-Acl -LiteralPath $Root -AclObject $private
$nested = Join-Path $Root 'python\Lib'
New-Item -ItemType Directory -Path $nested -Force | Out-Null
$file = Join-Path $nested 'reader.py'
[IO.File]::WriteAllText($file, 'preserved bytes')
# Protected descendants cannot depend on inheritance from the installation root.
Set-Acl -LiteralPath $nested -AclObject $private
$before = Get-Acl -LiteralPath $file
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Installer, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Installer PowerShell parsing failed' }
$function = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Grant-ServiceApplicationReadAccess'}, $true)
if ($null -eq $function) { throw 'Application ACL helper was not found' }
. ([ScriptBlock]::Create($function.Extent.Text))
Grant-ServiceApplicationReadAccess -ApplicationRoot $Root
foreach ($path in @($Root, $nested, $file)) {
    $acl = Get-Acl -LiteralPath $path
    $rules = $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
    $read = [Security.AccessControl.FileSystemRights]::ReadAndExecute
    if (-not ($rules | Where-Object {$_.IdentityReference.Value -eq 'S-1-5-19' -and $_.AccessControlType -eq 'Allow' -and ($_.FileSystemRights -band $read) -eq $read})) { throw "Missing LocalService RX: $path" }
    if (-not ($rules | Where-Object {$_.IdentityReference.Value -eq $owner.Value -and $_.FileSystemRights -eq 'FullControl'})) { throw "Owner rights changed: $path" }
    if ($rules | Where-Object {$_.IdentityReference.Value -eq 'S-1-5-19' -and ($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::WriteData)}) { throw "Service received write access: $path" }
}
if ([IO.File]::ReadAllText($file) -ne 'preserved bytes') { throw 'Application bytes changed' }
'''
            probe = Path(folder) / "acl-probe.ps1"
            probe.write_text(script, encoding="utf-8")
            application = Path(folder) / "private application"
            application.mkdir()
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(probe),
                 "-Installer", str(ROOT / "installers/windows/install.ps1"), "-Root", str(application)],
                capture_output=True, text=True, timeout=60,
                env=dict(os.environ, PSModulePath=str(Path(os.environ["SystemRoot"]) /
                                                      "System32/WindowsPowerShell/v1.0/Modules")),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staged_payload_hashes_match_generated_files(self):
        """Generated metadata and normalized source retain their recorded byte hashes."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "example.sh"
            source.write_bytes(b"#!/bin/sh\r\nexit 0\r\n")
            payload = root / "payload"
            with patch.object(build_installers, "ROOT", root), \
                    patch.object(build_installers, "source_files", return_value=[source]):
                build_installers.stage_payload(payload)
            manifest = json.loads((payload / "PAYLOAD-MANIFEST.json").read_text())
            self.assertEqual((payload / "example.sh").read_bytes(), b"#!/bin/sh\nexit 0\n")
            for relative, expected in manifest["files"].items():
                with self.subTest(file=relative):
                    self.assertEqual(build_installers.sha((payload / relative).read_bytes()), expected)

    def _build_fixture(self, root, output=None):
        """Build tiny source archives through the real CLI and capture reporting.

        Preserve the supplied root spelling so alias tests exercise production
        normalization rather than hiding the mismatch inside the fixture.
        """
        (root / "installers").mkdir()
        (root / "INSTALL.md").write_text("Installation guide")
        (root / "installers/VALIDATION.md").write_text("Validation guide")
        arguments = ["build_installers.py", "--linux-only"]
        if output is not None:
            arguments += ["--output", str(output)]
        captured = io.StringIO()
        with patch.object(build_installers, "ROOT", root), \
                patch.object(build_installers, "source_files", return_value=[root / "INSTALL.md"]), \
                patch.object(build_installers, "stage_payload", side_effect=lambda path: path.mkdir()), \
                patch.object(sys, "argv", arguments), redirect_stdout(captured):
            build_installers.main()
        return captured.getvalue()

    def test_build_distributes_os_installers_separately(self):
        """A release build emits architecture-specific installers without an aggregate archive."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            output = self._build_fixture(root)
            release = root / "dist" / build_installers.VERSION
            self.assertEqual(len(list(release.glob("*.run"))), 2)
            self.assertEqual(len((release / "SHA256SUMS.txt").read_text().splitlines()), 2)
            self.assertEqual(len(list(release.glob("*.provenance.json"))), 2)
            self.assertEqual(list((root / "dist").rglob("*.zip")), [])
            for artifact in release.glob("*.run"):
                self.assertIn(f"{artifact.relative_to(root)} ({artifact.stat().st_size:,} bytes)", output)

    def test_build_reports_external_output_directory_as_absolute_paths(self):
        """An explicitly selected output outside ROOT must not fail final reporting."""
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder).resolve()
            root = workspace / "source project"
            root.mkdir()
            destination = workspace / "external output with spaces"
            output = self._build_fixture(root, destination)
            artifacts = list(destination.glob("*.run"))
            self.assertEqual(len(artifacts), 2)
            for artifact in artifacts:
                self.assertIn(f"{artifact.resolve()} ({artifact.stat().st_size:,} bytes)", output)
                self.assertTrue(artifact.with_name(artifact.name + ".provenance.json").is_file())

    @unittest.skipUnless(os.name == "nt", "Windows short/long path aliases")
    def test_build_reports_short_root_alias_relative_to_canonical_root(self):
        """A real 8.3 ROOT and resolved long output refer to the same directory."""
        from test_dataset_manager import windows_short_path

        with tempfile.TemporaryDirectory(prefix="Installer paths with spaces ") as folder:
            root = Path(folder).resolve()
            alias = windows_short_path(root)
            self.assertEqual(alias.resolve(), root)
            output = self._build_fixture(alias)
            artifacts = list((root / "dist" / build_installers.VERSION).glob("*.run"))
            self.assertEqual(len(artifacts), 2)
            for artifact in artifacts:
                self.assertIn(f"{artifact.relative_to(root)} ({artifact.stat().st_size:,} bytes)", output)

    @unittest.skipUnless(os.name == "nt", "Windows junction path alias")
    def test_build_reports_junction_root_relative_to_canonical_root(self):
        """Exercise canonical reporting even when the volume has no 8.3 aliases."""
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder).resolve()
            root = workspace / "source project with spaces"
            root.mkdir()
            alias = workspace / "project alias"
            command = "New-Item -ItemType Junction -Path '{}' -Target '{}' -ErrorAction Stop | Out-Null".format(
                str(alias).replace("'", "''"), str(root).replace("'", "''"))
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            try:
                self.assertEqual(alias.resolve(), root)
                output = self._build_fixture(alias)
                artifacts = list((root / "dist" / build_installers.VERSION).glob("*.run"))
                self.assertEqual(len(artifacts), 2)
                for artifact in artifacts:
                    self.assertIn(f"{artifact.relative_to(root)} ({artifact.stat().st_size:,} bytes)", output)
            finally:
                alias.rmdir()

    def test_release_versions_agree_across_platforms_and_installers(self):
        """Current release metadata must agree without rewriting historical release notes."""
        version = build_installers.VERSION
        self.assertEqual(version, "v0.9.6-beta")
        numeric = version.removeprefix("v").split("-")[0] + ".0"
        for package in build_installers.PACKAGES:
            self.assertEqual((ROOT / package / "VERSION.txt").read_text().strip(), version)
        for name in ("installers/windows/ServiceHost.cs", "meshcore_mqtt_service_windows/Start-Service.cs"):
            source = (ROOT / name).read_text()
            self.assertIn(f'AssemblyVersion("{numeric}")', source)
            self.assertIn(f'AssemblyInformationalVersion("{version}")', source)
        wizard = (ROOT / "installers/windows/setup.iss").read_text()
        self.assertIn("AppVersion=" + version, wizard)
        self.assertIn("VersionInfoVersion=" + numeric, wizard)
        self.assertIn("MeshCore-EMS-" + version + "-windows-x64-setup", wizard)
        for name in ("installers/windows/install.ps1", "installers/linux/install.sh"):
            self.assertIn(version, (ROOT / name).read_text())

    def test_landslide_programs_ship_separately_from_dataset_references(self):
        """Service packages contain commands; independent data packages own references."""
        import package_services
        workspace_files = set(build_installers.source_files())
        required = {"landslide_service.py", "LANDSLIDE_GUIDE.md", "tests/test_landslide.py"}
        required.update("scripts/" + name + ".py" for name in ("slidewarn", "slidealarm", "slideinfo"))
        for package in package_services.PACKAGES:
            standalone_files = set(package_services.package_files(package))
            for name in required:
                path = ROOT / package / name
                self.assertIn(path, standalone_files)
                self.assertIn(path, workspace_files)
            self.assertFalse(any("data/landslide/" in p.as_posix() for p in standalone_files))
            self.assertFalse(any("data/wildfire/" in p.as_posix() for p in standalone_files))

    def test_upgrade_adds_landslide_commands_without_assigning_existing_channels(self):
        """New command registrations preserve the administrator's existing channel routing."""
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as folder:
                root, state, config = self.fixture(folder)
                package = root / "meshcore_mqtt_service"
                if platform == "windows":
                    package = root / "meshcore_mqtt_service_windows"
                    shutil.copytree(root / "meshcore_mqtt_service", package)
                configure.configure(root, state, config, platform)
                defaults = json.loads((package / "config.json").read_text())
                shipped = json.loads((ROOT / "meshcore_mqtt_service/config.json").read_text())
                for name in ("slidewarn", "slidealarm", "slideinfo"):
                    defaults["responder"]["commands"]["!" + name] = shipped["responder"]["commands"]["!" + name]
                    shutil.copyfile(ROOT / "meshcore_mqtt_service/scripts" / (name + ".py"),
                                    package / "scripts" / (name + ".py"))
                configure.write_json(package / "config.json", defaults)
                configure.configure(root, state, config, platform)
                updated = json.loads((config / "config.json").read_text())["responder"]
                for name in ("slidewarn", "slidealarm", "slideinfo"):
                    self.assertEqual(updated["commands"]["!" + name]["channels"], [])
                    self.assertEqual(updated["commands"]["!" + name]["script"], "scripts/" + name + ".py")

    def test_download_only_policy_excludes_generated_water_but_keeps_curated_inputs(self):
        rules = build_installers.water_download_rules()
        for path in ("data/usgs_water/routing/generation/routing.sqlite",
                     "data/basin_plans/snapshots/generation/features.geojson.gz",
                     "data/flood_impacts/observations/generation/report.json",
                     "data/usgs_water/observations.json"):
            self.assertTrue(build_installers.download_only(Path(path), rules), path)
        for path in ("data/usgs_water/local_review_rules.json",
                     "data/usgs_water/scripts/example.json",
                     "data/wildfire/zones.geojson",
                     "data/ebmud/sources.json"):
            self.assertFalse(build_installers.download_only(Path(path), rules), path)
        paths = {p.relative_to(ROOT).as_posix() for p in build_installers.source_files()}
        self.assertNotIn("data/wildfire/zones.geojson", paths)
        self.assertIn("data/usgs_water/local_review_rules.json", paths)
        self.assertFalse(any(p.startswith("data/usgs_water/routing/") for p in paths))

    def test_named_channel_override_accepts_public_and_private_radio_names(self):
        """The legacy name option must not apply the shipped hashtag key rule to other names."""
        for name in ("Public", "Operations"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root, state, config = self.fixture(folder)
                source = root / "meshcore_mqtt_service/config.json"
                defaults = json.loads(source.read_text())
                bot = defaults["responder"]
                bot.pop("channel_name")
                bot["channels"] = {
                    "default": {"name": "#default", "type": "hashtag", "mqtt_export": True}
                }
                for command in bot["commands"].values():
                    command["channels"] = ["default"]
                configure.write_json(source, defaults)
                configure.configure(root, state, config, "linux", channel=name)
                selected = json.loads((config / "config.json").read_text())["responder"][
                    "channels"
                ]["default"]
                self.assertEqual((selected["name"], selected["type"]), (name, "existing"))

    def fixture(self, folder):
        work = Path(folder)
        root, state, config = work / "app", work / "state", work / "config"
        package = root / "meshcore_mqtt_service"
        (package / "scripts").mkdir(parents=True)
        (root / "satellite_database").mkdir()
        (root / "data/satellites").mkdir(parents=True)
        for name in ("channels.py", "responder.py", "flood_alarm.py", "radio_connection.py", "wildfire_service.py", "landslide_service.py"):
            shutil.copy2(ROOT / "meshcore_mqtt_service" / name, package / name)
        defaults = json.loads((ROOT / "meshcore_mqtt_service/config.json").read_text())
        defaults["responder"].pop("channels", None)
        defaults["responder"]["channel_name"] = "#custom"
        defaults["responder"]["commands"] = {
            "!status": {"script": "scripts/status.py", "args": []},
            "!snowpack": {"script": "scripts/snowpack.py", "args": []},
        }
        for name in ("status.py", "snowpack.py"):
            (package / "scripts" / name).write_text('print("test")\n')
        shutil.copyfile(ROOT / "meshcore_mqtt_service/scripts/time_settings.py", package / "scripts/time_settings.py")
        shutil.copyfile(ROOT / "meshcore_mqtt_service/scripts/wildfire_settings.py", package / "scripts/wildfire_settings.py")
        for source in (ROOT / "meshcore_mqtt_service/scripts").glob("landslide_*.py"):
            shutil.copyfile(source, package / "scripts" / source.name)
        # Configuration imports the flood worker and its water helpers; fixture commands remain isolated.
        for source in (ROOT / "meshcore_mqtt_service/scripts").glob("water_*.py"):
            shutil.copyfile(source, package / "scripts" / source.name)
        for name in ("flood_warn.py", "uv_index.py", "response_text.py"):
            shutil.copyfile(ROOT / "meshcore_mqtt_service/scripts" / name, package / "scripts" / name)
        configure.write_json(package / "config.json", defaults)
        shutil.copy2(ROOT / "meshcore_mqtt_service/scripts/dataset_paths.py",
                     root / "meshcore_mqtt_service/scripts/dataset_paths.py")
        (root / "satellite_database/settings.json").write_text("{}")
        (root / "data/satellites/satellites.sqlite3").write_bytes(b"supplied-reference")
        return root, state, config

    def test_upgrade_preserves_config_credentials_and_refreshed_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root, state, config = self.fixture(folder)
            configure.configure(root, state, config, "linux", "/dev/ttyUSB0")
            current = json.loads((config / "config.json").read_text())
            current["responder"]["channels"]["default"]["name"] = "custom"
            current["responder"]["commands"]["!status"]["timeout"] = 99
            current["responder"]["wildfire"]["incident_interval"] = 600
            current["responder"]["landslide"]["subscription_hours"] = 2
            del current["responder"]["commands"]["!snowpack"]
            configure.write_json(config / "config.json", current)
            configure.write_json(config / "environment.json", {"AIRNOW_API_KEY": "kept-test-key"})
            (state / "data/satellites").mkdir(parents=True)
            (state / "data/satellites/satellites.sqlite3").write_bytes(b"operator-refreshed")
            with closing(sqlite3.connect(state / "runtime/bridge.sqlite3")) as database:
                database.execute("PRAGMA journal_mode=WAL")
                database.execute("CREATE TABLE queued (message TEXT)")
                database.execute("INSERT INTO queued VALUES (?)", ("private message",))
                database.commit()
                configure.configure(root, state, config, "linux", "/dev/ttyACM0")
            updated = json.loads((config / "config.json").read_text())
            self.assertEqual(updated["serial_port"], "/dev/ttyACM0")
            self.assertEqual(updated["responder"]["wildfire"]["incident_interval"], 600)
            self.assertEqual(updated["responder"]["landslide"]["subscription_hours"], 2)
            self.assertEqual(updated["responder"]["channels"]["default"]["name"], "custom")
            self.assertEqual(
                updated["responder"]["commands"]["!status"],
                current["responder"]["commands"]["!status"],
            )
            self.assertEqual(updated["responder"]["commands"]["!snowpack"]["channels"], [])
            self.assertEqual(
                (state / "data/satellites/satellites.sqlite3").read_bytes(), b"operator-refreshed"
            )
            for path in (
                state / "runtime/bridge.sqlite3",
                next((state / "backups").glob("*/bridge.sqlite3")),
            ):
                with closing(sqlite3.connect(path)) as database:
                    self.assertEqual(
                        database.execute("SELECT message FROM queued").fetchone(),
                        ("private message",),
                    )
            self.assertEqual(
                json.loads((config / "environment.json").read_text())["AIRNOW_API_KEY"],
                "kept-test-key",
            )
            self.assertEqual(
                json.loads((config / "config.before-install.json").read_text()), current
            )

    def test_upgrade_preserves_shared_reply_timezone(self):
        """An installed display-zone override must survive either platform's upgrade."""
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as folder:
                root, state, config = self.fixture(folder)
                package = root / "meshcore_mqtt_service"
                defaults = json.loads((package / "config.json").read_text())
                shipped = json.loads((ROOT / "meshcore_mqtt_service/config.json").read_text())
                defaults["responder"]["commands"]["!lightning"] = shipped["responder"]["commands"]["!lightning"]
                (package / "scripts/lightning.py").write_text('print("test")\n')
                configure.write_json(package / "config.json", defaults)
                if platform == "windows":
                    shutil.copytree(package, root / "meshcore_mqtt_service_windows")
                configure.configure(root, state, config, platform)
                current = json.loads((config / "config.json").read_text())
                current["responder"]["timezone"] = "America/Denver"
                configure.write_json(config / "config.json", current)
                configure.configure(root, state, config, platform)
                updated = json.loads((config / "config.json").read_text())
                self.assertEqual(updated["responder"]["timezone"], "America/Denver")
                self.assertEqual(updated["responder"]["commands"]["!lightning"]["args"], [])

    def test_legacy_upgrade_assigns_existing_and_added_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            root, state, config = self.fixture(folder)
            old = json.loads((root / "meshcore_mqtt_service/config.json").read_text())
            del old["responder"]["commands"]["!snowpack"]
            config.mkdir()
            configure.write_json(config / "config.json", old)
            configure.configure(root, state, config, "linux", "/dev/ttyUSB0")
            result = json.loads((config / "config.json").read_text())["responder"]
            self.assertNotIn("channel_name", result)
            self.assertEqual(result["channels"]["default"]["name"], "#custom")
            self.assertEqual(
                [entry["channels"] for entry in result["commands"].values()],
                [["default"], ["default"]],
            )
            self.assertEqual(
                json.loads(next((state / "backups").glob("*/config.json")).read_text()), old
            )

    def test_import_public_private_assignments_and_ambiguous_override(self):
        with tempfile.TemporaryDirectory() as folder:
            root, state, config = self.fixture(folder)
            imported = Path(folder) / "channels.json"
            values = {
                "channels": {
                    "public": {"name": "Public", "type": "public", "mqtt_export": True},
                    "ops": {
                        "name": "Operations",
                        "type": "private",
                        "secret_env": "MESHCORE_CHANNEL_KEY_OPS",
                        "mqtt_export": False,
                    },
                },
                "command_channels": {"!status": ["ops"], "!snowpack": ["public", "ops"]},
            }
            configure.write_json(imported, values)
            configure.configure(
                root, state, config, "linux", "/dev/ttyUSB0", channels_config=imported
            )
            saved = (config / "config.json").read_bytes()
            result = json.loads(saved)["responder"]
            self.assertEqual(result["channels"], values["channels"])
            self.assertEqual(result["commands"]["!status"]["channels"], ["ops"])
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                configure.configure(
                    root, state, config, "linux", "/dev/ttyUSB0", channel="#different"
                )
            self.assertEqual((config / "config.json").read_bytes(), saved)
            for assignments in ({"!typo": ["ops"]}, {"!status": ["missing"]}):
                values["command_channels"] = assignments
                configure.write_json(imported, values)
                with self.assertRaises(ValueError):
                    configure.configure(
                        root, state, config, "linux", "/dev/ttyUSB0", channels_config=imported
                    )
                self.assertEqual((config / "config.json").read_bytes(), saved)

    def test_import_rejects_inline_keys_without_writing_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root, state, config = self.fixture(folder)
            imported = Path(folder) / "channels.json"
            configure.write_json(
                imported,
                {
                    "channels": {
                        "ops": {
                            "name": "Ops",
                            "type": "private",
                            "secret_env": "MESHCORE_CHANNEL_KEY_OPS",
                            "key": "00112233445566778899aabbccddeeff",
                        }
                    },
                    "command_channels": {"!status": ["ops"], "!snowpack": []},
                },
            )
            with self.assertRaises(ValueError):
                configure.configure(
                    root, state, config, "linux", "/dev/ttyUSB0", channels_config=imported
                )
            self.assertFalse((config / "config.json").exists())

    def test_disabled_responder_still_validates_private_channel_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root, state, config = self.fixture(folder)
            source = root / "meshcore_mqtt_service/config.json"
            defaults = json.loads(source.read_text())
            defaults["responder"]["enabled"] = False
            configure.write_json(source, defaults)
            imported = Path(folder) / "channels.json"
            configure.write_json(
                imported,
                {
                    "channels": {"ops": {"name": "Ops", "type": "private", "mqtt_export": False}},
                    "command_channels": {"!status": ["ops"], "!snowpack": []},
                },
            )
            with self.assertRaisesRegex(ValueError, "secret_env"):
                configure.configure(
                    root, state, config, "linux", "/dev/ttyUSB0", channels_config=imported
                )
            self.assertFalse((config / "config.json").exists())

    def test_single_channel_override_preserves_private_security_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root, state, config = self.fixture(folder)
            imported = Path(folder) / "channels.json"
            private = {
                "name": "Ops",
                "type": "private",
                "mqtt_export": False,
                "secret_env": "MESHCORE_CHANNEL_KEY_OPS",
            }
            configure.write_json(
                imported,
                {
                    "channels": {"ops": private},
                    "command_channels": {"!status": ["ops"], "!snowpack": []},
                },
            )
            configure.configure(
                root, state, config, "linux", "/dev/ttyUSB0", channels_config=imported
            )
            configure.configure(root, state, config, "linux", "/dev/ttyUSB0", channel="Operations")
            result = json.loads((config / "config.json").read_text())["responder"]
            self.assertEqual(result["channels"], {"ops": dict(private, name="Operations")})
            self.assertEqual(result["commands"]["!status"]["channels"], ["ops"])
            self.assertEqual(result["commands"]["!snowpack"]["channels"], [])

    def test_installed_program_directory_and_operator_code_survive_upgrade(self):
        with tempfile.TemporaryDirectory() as folder:
            root, state, config = self.fixture(folder)
            configure.configure(root, state, config, "linux", "/dev/ttyUSB0")
            current = json.loads((config / "config.json").read_text())
            programs = config / "programs"
            self.assertEqual(current["responder"]["program_directory"], str(programs.resolve()))
            source = programs / "operator.py"
            source.write_text('print("operator program")\n')
            # A separately managed absolute directory is also preserved on upgrade.
            custom = Path(folder) / "custom-programs"
            custom.mkdir()
            current["responder"]["program_directory"] = str(custom.resolve())
            configure.write_json(config / "config.json", current)
            configure.configure(root, state, config, "linux", "/dev/ttyUSB0")
            updated = json.loads((config / "config.json").read_text())
            self.assertEqual(updated["responder"]["program_directory"], str(custom.resolve()))
            self.assertEqual(source.read_text(), 'print("operator program")\n')

    def test_auto_port_is_default_and_explicit_port_remains_available(self):
        with tempfile.TemporaryDirectory() as folder:
            root, state, config = self.fixture(folder)
            configure.configure(root, state, config, "linux")
            self.assertEqual(
                json.loads((config / "config.json").read_text())["serial_port"], "auto"
            )
            configure.configure(root, state, config, "linux", "/dev/ttyUSB9")
            self.assertEqual(
                json.loads((config / "config.json").read_text())["serial_port"], "/dev/ttyUSB9"
            )
            # Upgrades using defaults opt into ongoing detection, not an old tty number.
            configure.configure(root, state, config, "linux", "AUTO")
            self.assertEqual(
                json.loads((config / "config.json").read_text())["serial_port"], "auto"
            )

    def test_transport_upgrades_preserve_settings_and_allow_explicit_switches(self):
        """No installer options reset a configured endpoint; switching drops old fields."""
        with tempfile.TemporaryDirectory() as folder:
            root, state, config = self.fixture(folder)
            configure.configure(root, state, config, "linux", tcp_host="192.168.1.50")
            path = config / "config.json"
            connection = json.loads(path.read_text())["connection"]
            self.assertEqual(connection, {"type": "tcp", "host": "192.168.1.50", "port": 5000})
            configure.configure(root, state, config, "linux")
            self.assertEqual(json.loads(path.read_text())["connection"], connection)
            configure.configure(root, state, config, "linux", tcp_port=5010)
            self.assertEqual(json.loads(path.read_text())["connection"]["port"], 5010)
            configure.configure(root, state, config, "linux", ble_address="AA:BB:CC:DD:EE:FF")
            self.assertEqual(
                json.loads(path.read_text())["connection"],
                {"type": "ble", "address": "AA:BB:CC:DD:EE:FF"},
            )
            configure.configure(root, state, config, "linux")
            self.assertEqual(json.loads(path.read_text())["connection"]["type"], "ble")
            saved = path.read_bytes()
            for options in (
                {"transport": "tcp"},
                {"tcp_host": "invalid"},
                {"tcp_host": "192.168.1.50", "port": "auto"},
                {"ble_address": "invalid"},
                {"tcp_host": "192.168.1.50", "tcp_port": 0},
            ):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    configure.configure(root, state, config, "linux", **options)
                self.assertEqual(path.read_bytes(), saved)
            configure.configure(root, state, config, "linux", port="/dev/ttyUSB9")
            configure.configure(root, state, config, "linux")
            result = json.loads(path.read_text())
            self.assertEqual(result["connection"], {"type": "serial"})
            self.assertEqual(result["serial_port"], "/dev/ttyUSB9")

    def test_installer_entrypoints_offer_auto_and_fixed_port_overrides(self):
        wizard = (ROOT / "installers/windows/setup.iss").read_text()
        windows = (ROOT / "installers/windows/install.ps1").read_text()
        linux = (ROOT / "installers/linux/install.sh").read_text()
        self.assertIn("{param:SERIALPORT|auto}", wizard)
        self.assertIn("LowerCase(Value) = 'auto'", wizard)
        self.assertIn("[string]$SerialPort,", windows)
        self.assertIn("auto|COM[1-9][0-9]*", windows)
        self.assertIn("port=''", linux)
        self.assertIn("--port) port=${2:?Missing serial device}", linux)
        self.assertIn("$port == auto ||", linux)
        self.assertNotIn("Companion serial device: ", linux)

    def test_complete_payload_excludes_development_and_private_state(self):
        paths = {p.relative_to(ROOT).as_posix() for p in build_installers.source_files()}
        for required in (
            "LICENSE",
            "INSTALL.md",
            "docs/README.md",
            "docs/ARCHITECTURE.md",
            "docs/DEVELOPMENT.md",
            "RELEASE_v0.9.6-beta.md",
            "AGENTS.md",
            ".gitignore",
            ".gitattributes",
            "docs/assets/readme-hero.svg",
            "docs/assets/version-badge.svg",
            "docs/assets/commands-badge.svg",
            "docs/assets/offline-gis-badge.svg",
            "archive/README.md",
            "satellite_database/satellite_db.py",
            "meshcore_mqtt_service/service_runner.py",
            "meshcore_mqtt_service_windows/service_runner.py",
        ):
            self.assertIn(required, paths)
        for excluded in ("data/satellites/satellites.sqlite3", "data/ebmud/trails.geojson",
                         "meshcore_mqtt_service/data/wildfire/zones.geojson",
                         "meshcore_mqtt_service_windows/data/landslide/stations.json"):
            self.assertNotIn(excluded, paths)
        for path in paths:
            if path.startswith("archive/"):
                # Include public recovery guidance without distributing recovery data.
                self.assertEqual(path, "archive/README.md")
                continue
            self.assertFalse(
                set(Path(path).parts)
                & {
                    ".venv",
                    ".venv-linux",
                    ".build",
                    ".git",
                    "runtime",
                    "dist",
                    "archive",
                    "__pycache__",
                },
                path,
            )

    def test_shared_service_runner_is_identical(self):
        for name in (
            "service_runner.py",
            "radio_connection.py",
            "tests/test_service_runner.py",
            "tests/test_radio_connection.py",
        ):
            self.assertEqual(
                (ROOT / "meshcore_mqtt_service" / name).read_bytes(),
                (ROOT / "meshcore_mqtt_service_windows" / name).read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
