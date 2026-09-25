"""Validate upgrade preservation and release payload boundaries without OS installation."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_installers
spec = importlib.util.spec_from_file_location('installer_configure', ROOT / 'installers/configure.py')
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class InstallerTests(unittest.TestCase):
    def test_upgrade_preserves_config_credentials_and_refreshed_database(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            root, state, config = work / 'app', work / 'state', work / 'config'
            (root / 'meshcore_mqtt_service').mkdir(parents=True)
            (root / 'satellite_database').mkdir()
            (root / 'data/satellites').mkdir(parents=True)
            defaults = {'responder': {'channel_name': 'default', 'commands': {'!status': {}, '!snowpack': {}}}}
            (root / 'meshcore_mqtt_service/config.json').write_text(json.dumps(defaults))
            (root / 'satellite_database/settings.json').write_text('{}')
            (root / 'data/satellites/satellites.sqlite3').write_bytes(b'supplied-reference')
            configure.configure(root, state, config, 'linux', '/dev/ttyUSB0')
            current = json.loads((config / 'config.json').read_text())
            current['responder']['channel_name'] = 'custom'
            current['responder']['commands']['!status'] = {'timeout': 99}
            del current['responder']['commands']['!snowpack']
            configure.write_json(config / 'config.json', current)
            configure.write_json(config / 'environment.json', {'AIRNOW_API_KEY': 'kept-test-key'})
            (state / 'data/satellites/satellites.sqlite3').write_bytes(b'operator-refreshed')
            (state / 'runtime/bridge.sqlite3').write_bytes(b'operator-runtime')
            configure.configure(root, state, config, 'linux', '/dev/ttyACM0')
            updated = json.loads((config / 'config.json').read_text())
            self.assertEqual(updated['serial_port'], '/dev/ttyACM0')
            self.assertEqual(updated['responder']['channel_name'], 'custom')
            self.assertEqual(updated['responder']['commands']['!status'], {'timeout': 99})
            self.assertIn('!snowpack', updated['responder']['commands'])
            self.assertEqual((state / 'data/satellites/satellites.sqlite3').read_bytes(), b'operator-refreshed')
            self.assertEqual((state / 'runtime/bridge.sqlite3').read_bytes(), b'operator-runtime')
            self.assertEqual(json.loads((config / 'environment.json').read_text())['AIRNOW_API_KEY'], 'kept-test-key')
            self.assertEqual(json.loads((config / 'config.before-install.json').read_text()), current)

    def test_complete_payload_excludes_development_and_private_state(self):
        paths = {p.relative_to(ROOT).as_posix() for p in build_installers.source_files()}
        for required in ('LICENSE', 'INSTALL.md', 'data/satellites/satellites.sqlite3',
                         'data/ebmud/trails.geojson', 'satellite_database/satellite_db.py',
                         'meshcore_mqtt_service/service_runner.py',
                         'meshcore_mqtt_service_windows/service_runner.py'):
            self.assertIn(required, paths)
        for path in paths:
            self.assertFalse(set(Path(path).parts) & {'.venv', '.venv-linux', '.build', '.git', 'runtime', 'dist', 'archive', '__pycache__'}, path)

    def test_shared_service_runner_is_identical(self):
        for name in ('service_runner.py', 'tests/test_service_runner.py'):
            self.assertEqual((ROOT / 'meshcore_mqtt_service' / name).read_bytes(),
                             (ROOT / 'meshcore_mqtt_service_windows' / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
