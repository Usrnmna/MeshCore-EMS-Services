"""Validate upgrade preservation and release payload boundaries without OS installation."""

import importlib.util
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_installers

spec = importlib.util.spec_from_file_location(
    "installer_configure", ROOT / "installers/configure.py"
)
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class InstallerTests(unittest.TestCase):
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
        for name in ("channels.py", "responder.py", "flood_alarm.py", "radio_connection.py"):
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
        configure.write_json(package / "config.json", defaults)
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
            del current["responder"]["commands"]["!snowpack"]
            configure.write_json(config / "config.json", current)
            configure.write_json(config / "environment.json", {"AIRNOW_API_KEY": "kept-test-key"})
            (state / "data/satellites/satellites.sqlite3").write_bytes(b"operator-refreshed")
            with closing(sqlite3.connect(state / "runtime/bridge.sqlite3")) as database:
                database.execute("PRAGMA journal_mode=WAL")
                database.execute("CREATE TABLE queued (message TEXT)")
                database.execute("INSERT INTO queued VALUES (?)", ("private message",))
                database.commit()
                configure.configure(root, state, config, "linux", "/dev/ttyACM0")
            updated = json.loads((config / "config.json").read_text())
            self.assertEqual(updated["serial_port"], "/dev/ttyACM0")
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
            "data/satellites/satellites.sqlite3",
            "data/ebmud/trails.geojson",
            "satellite_database/satellite_db.py",
            "meshcore_mqtt_service/service_runner.py",
            "meshcore_mqtt_service_windows/service_runner.py",
        ):
            self.assertIn(required, paths)
        for path in paths:
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
