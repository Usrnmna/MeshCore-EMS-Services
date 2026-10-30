"""Protect offline coverage and publication boundaries in the maintained workflow.

Install .github/requirements-ci.txt to parse the workflow with PyYAML. BaseLoader
retains GitHub Actions' `on` key and Boolean-like scalars without YAML 1.1 coercion.
"""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
SUPPORTED_RUNNERS = {"ubuntu-latest", "windows-latest", "ubuntu-24.04-arm"}
HISTORY_SUITES = {
    "test_history_backend", "test_history_widgets", "test_history_window",
    "test_history_process", "test_history_state", "test_history_optional_isolation",
    "test_desktop_authorization", "test_desktop_service", "test_desktop_service_window", "test_unified_backend",
    "test_unified_window", "test_unified_service",
}
PUBLICATION_SUITES = {
    "tools.test_repository_configuration", "tools.test_ci_configuration",
    "tools.test_distribution_policy", "tools.test_release_version",
}


class CIConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        cls.jobs = cls.workflow["jobs"]

    def test_read_only_permissions_and_pinned_actions_remain_in_effect(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(self.workflow["on"]), {"push", "pull_request", "workflow_dispatch"})
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertNotIn("permissions", job)
                for step in job["steps"]:
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"^[\w-]+/[\w-]+@[0-9a-f]{40}$")
                        self.assertNotIn("upload", step["uses"])

    def test_every_checkout_omits_local_planning_without_persisting_credentials(self):
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                checkout = [step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")]
                self.assertEqual(len(checkout), 1)
                settings = checkout[0]["with"]
                self.assertEqual(settings["persist-credentials"], "false")
                self.assertEqual(settings["sparse-checkout-cone-mode"], "false")
                self.assertEqual(settings["sparse-checkout"].splitlines(), ["/*", "!/docs/superpowers/"])

    def test_service_matrix_covers_both_packages_and_supported_python_versions(self):
        matrix = self.jobs["services"]["strategy"]["matrix"]
        self.assertEqual(set(matrix["os"]), SUPPORTED_RUNNERS)
        self.assertEqual(set(matrix["python"]), {"3.11", "3.13"})
        self.assertEqual(set(matrix["package"]), {"meshcore_mqtt_service", "meshcore_mqtt_service_windows"})
        steps = self.jobs["services"]["steps"]
        self.assertTrue(any(step.get("working-directory") == "${{ matrix.package }}" and
                            step.get("run") == 'python -m unittest discover -s tests -p "test_*.py"'
                            for step in steps))
        for package in matrix["package"]:
            self.assertTrue((ROOT / package / "tests/test_channel_history.py").is_file())
            self.assertTrue((ROOT / package / "tests/test_command_programs.py").is_file())

    def test_tools_require_offscreen_qt_and_discover_history_authorization_suites(self):
        job = self.jobs["documentation-and-tools"]
        self.assertEqual(set(job["strategy"]["matrix"]["os"]), SUPPORTED_RUNNERS)
        self.assertEqual(job["env"]["QT_QPA_PLATFORM"], "offscreen")
        commands = [step.get("run", "") for step in job["steps"]]
        self.assertTrue(any("QApplication([])" in command and "app.platformName() == 'offscreen'" in command
                            for command in commands))
        suites = [step for step in job["steps"]
                  if 'python -m unittest discover -s tools -p "test_*.py"' in step.get("run", "")]
        self.assertEqual({step["if"] for step in suites}, {"runner.os == 'Windows'", "runner.os != 'Windows'"})
        windows = next(step for step in suites if step["if"] == "runner.os == 'Windows'")
        self.assertEqual(windows["shell"], "powershell")
        self.assertIn("exit $LASTEXITCODE", windows["run"])
        for module in HISTORY_SUITES:
            with self.subTest(module=module):
                self.assertTrue((ROOT / "tools" / (module + ".py")).is_file())

    def test_documentation_release_versions_and_exclusions_have_explicit_gates(self):
        steps = self.jobs["documentation-and-tools"]["steps"]
        commands = "\n".join(step.get("run", "") for step in steps)
        self.assertIn("python tools/check_documentation.py", commands)
        invoked = set(re.findall(r"\btools\.test_[a-z_]+\b", commands))
        self.assertTrue(PUBLICATION_SUITES <= invoked, PUBLICATION_SUITES - invoked)
        self.assertIn("-r .github/requirements-ci.txt", commands)
        self.assertIn("-r installers/datasets/gui/requirements.txt", commands)
        self.assertIn("python -m pip check", commands)
        for module in PUBLICATION_SUITES:
            self.assertTrue((ROOT / (module.replace(".", "/") + ".py")).is_file(), module)

    def test_frozen_desktop_builds_and_helpers_run_on_every_tooling_platform(self):
        """Require actual executables and synthetic smoke without release publication."""
        job = self.jobs["documentation-and-tools"]
        self.assertEqual(set(job["strategy"]["matrix"]["os"]), SUPPORTED_RUNNERS)
        steps = job["steps"]
        self.assertTrue(any(step.get("run") ==
                            "python -m pip install -r installers/datasets/gui/requirements-build.txt"
                            for step in steps))
        smoke = next(step for step in steps if step.get("id") == "frozen-desktop")
        self.assertNotIn("if", smoke)
        self.assertEqual(smoke["shell"], "python {0}")
        self.assertLessEqual(int(smoke["timeout-minutes"]), 20)
        command = smoke["run"]
        compile(command, "ci-frozen-desktop", "exec")
        for required in ("from installers.desktop.version import VERSION", "tools/build_dataset_gui.py",
                         "MeshCore-EMS-Dataset-Manager", "MeshCore-EMS-Service-Setup", "--service",
                         "tools/test_packaged_history.py", "--expected-version", "--include-datasets-only",
                         "tools/build_installers.py", "--linux-only", "PAYLOAD-MANIFEST.json",
                         "DESKTOP-CAPABILITIES.json", "channel-history-v1"):
            self.assertIn(required, command)
        self.assertNotIn("--python", command, "Frozen evidence must not substitute a source entry point")
        self.assertTrue((ROOT / "tools/test_packaged_history.py").is_file())

    def test_arm64_plugins_are_prepared_before_source_checks_and_frozen_uses_bookworm(self):
        steps = self.jobs["documentation-and-tools"]["steps"]
        preparation = next(index for index, step in enumerate(steps)
                           if "arm64_gui_ci.py prepare" in step.get("run", ""))
        self.assertEqual(steps[preparation]["if"], "runner.os == 'Linux' && runner.arch == 'ARM64'")
        self.assertIn("libwebp7 libwebpdemux2 libwebpmux3 libtiff6", steps[preparation]["run"])
        for index, step in enumerate(steps):
            if "QApplication([])" in step.get("run", "") or 'discover -s tools' in step.get("run", ""):
                self.assertLess(preparation, index)
        frozen = next(step["run"] for step in steps if step.get("id") == "frozen-desktop")
        self.assertIn("platform.system() == 'Linux' and platform.machine().lower() in {'aarch64', 'arm64'}", frozen)
        self.assertIn("'.github/scripts/arm64_gui_ci.py', 'frozen'", frozen)


class ARM64CIHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / ".github/scripts/arm64_gui_ci.py"
        spec = importlib.util.spec_from_file_location("arm64_gui_ci", path)
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)

    def test_container_is_temporary_and_does_not_forward_source_plugin_paths(self):
        with mock.patch.dict(os.environ, {"QT_PLUGIN_PATH": "/host/plugins", "LD_LIBRARY_PATH": "/host/libs"}):
            command = self.helper.container_command("frozen", 1001, 1001)
        self.assertEqual(command[:5], ["docker", "run", "--rm", "--platform", "linux/arm64"])
        self.assertIn("python:3.13-bookworm", command)
        self.assertEqual(command[-3:], ["1001", "1001", "frozen"])
        for forbidden in ("QT_PLUGIN_PATH", "LD_LIBRARY_PATH", "--privileged", "--publish"):
            self.assertFalse(any(forbidden in argument for argument in command))
        self.assertIn('exec setpriv --reuid="$1" --regid="$2" --clear-groups', self.helper.BOOTSTRAP)
        self.assertIn("libwebp-dev=1.2.4-0.2+deb12u1", self.helper.BOOTSTRAP)
        self.assertIn("libtiff-dev=4.5.0-6+deb12u4", self.helper.BOOTSTRAP)

    def test_container_rejects_root_or_arbitrary_modes(self):
        for mode, uid, gid in (("frozen", 0, 0), ("arbitrary", 1001, 1001), ("prepare", 1001, -1)):
            with self.subTest(mode=mode, uid=uid, gid=gid), self.assertRaises(ValueError):
                self.helper.container_command(mode, uid, gid)

    def test_source_preparation_reuses_builder_cache_and_copies_only_rebuilt_plugins(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(self.helper, "ROOT", Path(temporary)), \
                mock.patch.object(sys, "path", list(sys.path)):
            prepared = Path(temporary) / "prepared"
            prepared.mkdir()
            for name in ("libqwebp.so", "libqtiff.so", "MANIFEST.json"):
                (prepared / name).write_text(name, encoding="utf-8")
            builder = mock.Mock(PLUGINS={"libqwebp.so": {}, "libqtiff.so": {}})
            builder.file_hash.return_value = "a" * 64
            builder.prepare.return_value = prepared
            with mock.patch.dict(sys.modules, {"build_arm64_image_plugins": builder}):
                self.helper.prepare_source_plugins()
            builder.prepare.assert_called_once_with(Path(temporary) / ".build/arm64-image-plugins-aaaaaaaaaaaa")
            destination = Path(temporary) / self.helper.SOURCE_PLUGINS / "imageformats"
            self.assertEqual({path.name for path in destination.iterdir()}, {"libqwebp.so", "libqtiff.so"})
            for path in destination.iterdir():
                self.assertEqual(path.read_text(encoding="utf-8"), path.name)

    def test_frozen_builds_both_executables_and_clears_external_qt_search(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(self.helper, "ROOT", Path(temporary)), \
                mock.patch.object(self.helper, "run") as run, \
                mock.patch.object(self.helper, "verify_service_payloads") as verify, \
                mock.patch.dict(os.environ, {"QT_PLUGIN_PATH": "/source/plugins", "LD_LIBRARY_PATH": "/source/libs"}):
            self.helper.verify_frozen()
            self.assertNotIn("QT_PLUGIN_PATH", os.environ)
            self.assertNotIn("LD_LIBRARY_PATH", os.environ)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(len(commands), 5)
            self.assertEqual(commands[0][1], "tools/build_dataset_gui.py")
            self.assertEqual(commands[2][-1], "--service")
            for command, app in ((commands[1], "MeshCore-EMS-Dataset-Manager"),
                                 (commands[3], "MeshCore-EMS-Service-Setup")):
                self.assertEqual(command[1], "tools/test_packaged_history.py")
                executable = command[command.index("--application") + 1]
                self.assertEqual(executable.parts[-2:], (app, app))
                self.assertNotIn("--python", command)
            self.assertIn("--include-datasets-only", commands[1])
            self.assertNotIn("--include-datasets-only", commands[3])
            self.assertEqual(commands[4][1:3], ["tools/build_installers.py", "--linux-only"])
            verify.assert_called_once()

    def test_build_failure_stops_smoke_and_does_not_become_success(self):
        failure = subprocess.CalledProcessError(9, ["builder"])
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(self.helper, "ROOT", Path(temporary)), \
                mock.patch.object(self.helper, "run", side_effect=failure) as run, \
                mock.patch.object(self.helper, "verify_service_payloads") as verify, mock.patch.dict(os.environ):
            with self.assertRaises(subprocess.CalledProcessError):
                self.helper.verify_frozen()
            run.assert_called_once()
            verify.assert_not_called()

    def test_service_payload_verification_checks_corruption_and_capabilities(self):
        def artifact_bytes(capabilities):
            files = {"DESKTOP-CAPABILITIES.json": json.dumps({"capabilities": capabilities}).encode()}
            manifest = {"version": "test", "files": {
                name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
            files["PAYLOAD-MANIFEST.json"] = json.dumps(manifest).encode()
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w:gz") as archive:
                for name, value in files.items():
                    entry = tarfile.TarInfo(name)
                    entry.size = len(value)
                    archive.addfile(entry, io.BytesIO(value))
            payload = output.getvalue()
            return ('expected_sha="' + hashlib.sha256(payload).hexdigest() + '"').encode() + b"\n__MESHCORE_PAYLOAD__\n" + payload

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            good = artifact_bytes(["channel-history-v1"])
            for name in ("first.run", "second.run"):
                (directory / name).write_bytes(good)
            self.helper.verify_service_payloads(directory, "test")
            (directory / "second.run").write_bytes(good + b"corruption")
            with self.assertRaises(AssertionError):
                self.helper.verify_service_payloads(directory, "test")
            (directory / "second.run").write_bytes(artifact_bytes([]))
            with self.assertRaises(AssertionError):
                self.helper.verify_service_payloads(directory, "test")


if __name__ == "__main__":
    unittest.main()
