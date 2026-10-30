"""Protect CI failure reporting, job coverage, and dependency update boundaries."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class CiConfigurationTests(unittest.TestCase):
    def test_matrix_permissions_and_failure_reports(self):
        workflow = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'push', 'pull_request', 'workflow_dispatch'})
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        matrix = workflow['jobs']['services']['strategy']['matrix']
        self.assertEqual(matrix['python'], ['3.11', '3.13'])
        self.assertEqual(matrix['package'], ['meshcore_mqtt_service', 'meshcore_mqtt_service_windows'])
        for job in workflow['jobs'].values():
            self.assertEqual(job['strategy']['matrix']['os'], ['ubuntu-latest', 'windows-latest'])
            self.assertEqual(job['strategy']['fail-fast'], 'false')
            self.assertNotIn('continue-on-error', job)
            reports = []
            for step in job['steps']:
                self.assertNotIn('continue-on-error', step)
                if 'uses' in step:
                    self.assertRegex(step['uses'], r'^[\w/-]+@[0-9a-f]{40}$')
                    if step['uses'].startswith('actions/checkout@'):
                        self.assertEqual(step['with']['persist-credentials'], 'false')
                    if step['uses'].startswith('actions/upload-artifact@'):
                        reports.append(step)
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]['if'], 'always()')
            self.assertEqual(reports[0]['with']['path'], '.build/ci-reports/*.log')
            self.assertEqual(reports[0]['with']['include-hidden-files'], 'true')

    def test_manifest_coverage_and_dependency_groups(self):
        bot = yaml.safe_load((ROOT / '.github/dependabot.yml').read_text())
        pip = next(item for item in bot['updates'] if item['package-ecosystem'] == 'pip')
        tracked = subprocess.check_output(['git', 'ls-files', '*requirements*.txt'], cwd=ROOT, text=True).splitlines()
        tracked.append('.github/requirements-ci.txt')
        for name in tracked:
            self.assertIn('/' + Path(name).parent.as_posix(), pip['directories'])
        self.assertNotIn('ignore', pip)
        self.assertEqual(pip['groups']['qt-runtime']['patterns'], ['PyQt6*', 'pyqt6*'])
        self.assertEqual(pip['groups']['shared-python-dependencies']['group-by'], 'dependency-name')
        workflow = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
        steps = workflow['jobs']['documentation-and-tools']['steps']
        cache = next(step['with']['cache-dependency-path'] for step in steps if step.get('uses', '').startswith('actions/setup-python@')).splitlines()
        manifest = ROOT / '.github/requirements-ci.txt'
        self.assertIn('.github/requirements-ci.txt', cache)
        for include in re.findall(r'^-r (.+)$', manifest.read_text(), re.MULTILINE):
            path = (manifest.parent / include).resolve()
            self.assertTrue(path.is_file())
            self.assertIn(path.relative_to(ROOT).as_posix(), cache)

    def test_report_runner_preserves_output_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'nested/result.log'
            for status in (0, 7):
                with self.subTest(status=status):
                    result = subprocess.run([sys.executable, str(ROOT / 'tools/run_ci_check.py'), str(report),
                        sys.executable, '-c', f"import sys; print('stdout proof'); print('stderr proof', file=sys.stderr); sys.exit({status})"], capture_output=True)
                    self.assertEqual(result.returncode, status)
                    for expected in (b'stdout proof', b'stderr proof'):
                        self.assertIn(expected, result.stdout)
                        self.assertIn(expected, report.read_bytes())
                    self.assertIn(f'Exit status: {status}', report.read_text())


if __name__ == '__main__':
    unittest.main()
