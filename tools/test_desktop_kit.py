"""Offline desktop packaging contracts; no native installer is executed."""

import json
import ctypes
import ctypes.util
import os
from pathlib import Path
import sys
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_dataset_gui as gui


class DesktopKitTests(unittest.TestCase):
    def test_supported_linux_kit_rejects_unknown_or_newer_build_glibc(self):
        import build_desktop_kit as kit
        self.assertTrue(hasattr(kit, "validate_linux_baseline"))
        for record in ({}, {"build_libc": ["glibc", "2.39"]}):
            with self.subTest(record=record), self.assertRaisesRegex(ValueError, "glibc"):
                kit.validate_linux_baseline(record, "linux-x86_64")
        kit.validate_linux_baseline({"build_libc": ["glibc", "2.36"]}, "linux-x86_64")
        kit.validate_linux_baseline({}, "windows-x64")

    def test_kit_instructions_are_self_contained_and_platform_specific(self):
        import build_desktop_kit as kit
        self.assertTrue(hasattr(kit, "start_guide"), "The extracted kit needs standalone instructions")
        for target in kit.TARGETS:
            guide = kit.start_guide(target)
            self.assertIn("Dataset Manager", guide)
            self.assertIn("Service Setup", guide)
            self.assertNotIn("../INSTALL.md", guide)
            self.assertNotIn("python tools/", guide)
            self.assertIn(".exe" if target == "windows-x64" else "Allow Launching", guide)

    def test_incompatible_qt_environment_is_rejected(self):
        with patch.object(gui, "version", return_value="6.11.0"):
            with self.assertRaisesRegex(ValueError, "dependency versions"):
                gui.verify_gui_dependencies()

    @unittest.skipUnless(sys.platform == "linux", "GLib desktop command parser is exercised on Linux")
    def test_desktop_launcher_handles_spaces_and_apostrophes(self):
        """Parse the actual key-file and Exec layers before launching a harmless fixture."""
        import build_desktop_kit as kit
        glib = ctypes.CDLL(ctypes.util.find_library("glib-2.0"))
        glib.g_key_file_new.restype = ctypes.c_void_p
        glib.g_key_file_load_from_data.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_void_p)
        glib.g_key_file_get_string.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p)
        glib.g_key_file_get_string.restype = ctypes.c_char_p
        glib.g_shell_parse_argv.argtypes = (ctypes.c_char_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.POINTER(ctypes.c_char_p)), ctypes.c_void_p)
        glib.g_key_file_free.argtypes = (ctypes.c_void_p,)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Kit with spaces and operator's files"
            app = root / "dataset-manager" / gui.APP_NAME
            app.parent.mkdir(parents=True)
            app.write_text("#!/bin/sh\nprintf 'fixture-launched'\n")
            app.chmod(0o755)
            launcher = root / "1-Datasets.desktop"
            contents = kit.desktop_entry("Dataset", "dataset-manager/" + gui.APP_NAME).encode()
            launcher.write_bytes(contents)
            key = glib.g_key_file_new()
            try:
                self.assertTrue(glib.g_key_file_load_from_data(key, contents, len(contents), 0, None))
                command = glib.g_key_file_get_string(key, b"Desktop Entry", b"Exec", None)
                self.assertIsNotNone(command)
                argc, argv = ctypes.c_int(), ctypes.POINTER(ctypes.c_char_p)()
                self.assertTrue(glib.g_shell_parse_argv(command, ctypes.byref(argc), ctypes.byref(argv), None))
                arguments = [argv[index].decode() for index in range(argc.value)]
                arguments = [str(launcher) if value == "%k" else value for value in arguments]
                result = subprocess.run(arguments, check=True, capture_output=True, text=True)
                self.assertEqual(result.stdout, "fixture-launched")
            finally:
                glib.g_key_file_free(key)

    def test_service_gui_has_distinct_entry_point_and_identity(self):
        self.assertTrue(hasattr(gui, "build_service"), "Separate service GUI builder is required")

    def test_gui_source_inventory_covers_privileged_workers(self):
        self.assertTrue(hasattr(gui, "source_files"), "Build records must identify compiled worker sources")
        if hasattr(gui, "source_files"):
            names = {p.relative_to(gui.ROOT).as_posix() for p in gui.source_files()}
            self.assertIn("installers/desktop/authorization.py", names)
            for name in ('backend', 'process', 'state', 'widgets', 'window'):
                self.assertIn('installers/desktop/history_' + name + '.py', names)
            for package in ('meshcore_mqtt_service', 'meshcore_mqtt_service_windows'):
                for name in ('config.json', 'channel_history.py', 'channels.py'):
                    self.assertIn(package + '/' + name, names)
                self.assertFalse(json.loads((gui.ROOT / package / 'config.json').read_text())['channel_history']['enabled'])
            self.assertFalse(any('runtime' in Path(name).parts or name.endswith(('.sqlite3', '-wal', '-shm')) for name in names))

    def test_incoming_history_capability_matches_staged_preview_schema(self):
        import build_installers
        from artifact_provenance import write_provenance
        from installers.desktop.service_backend import incoming_history_supported
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [gui.ROOT / 'meshcore_mqtt_service' / name for name in ('config.json', 'channels.py', 'channel_history.py')]
            with patch.object(build_installers, 'source_files', return_value=sources):
                build_installers.stage_payload(root / 'payload')
            capabilities = json.loads((root / 'payload/DESKTOP-CAPABILITIES.json').read_text())['capabilities']
            self.assertIn('channel-history-v1', capabilities)
            artifact = root / 'fixture.run'; artifact.write_bytes(b'not executable')
            record = json.loads(write_provenance(artifact, 'service', sources, root=gui.ROOT, target='linux-x86_64').read_text())
            self.assertEqual(record['capabilities'], capabilities)
            self.assertTrue(incoming_history_supported(record, 'linux-x86_64'))
            record['source_sha256']['meshcore_mqtt_service/channels.py'] = '0' * 64
            self.assertFalse(incoming_history_supported(record, 'linux-x86_64'))

    def test_archive_retains_executable_modes_without_chmod_commands(self):
        import build_desktop_kit as kit
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "kit with spaces"
            root.mkdir()
            binary = root / gui.APP_NAME
            binary.write_bytes(b"fixture")
            binary.chmod(0o755)
            artifact = kit.make_archive(root, "linux-x86_64")
            with tarfile.open(artifact) as archive:
                self.assertEqual(archive.getmember(root.name + "/" + gui.APP_NAME).mode & 0o111, 0o111)

    def test_foreign_gui_is_rejected_before_copying(self):
        import build_desktop_kit as kit
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "BUILD.json").write_text(json.dumps({"target": "raspberry-pi-arm64"}))
            with self.assertRaisesRegex(ValueError, "target"):
                kit.verify_gui(root, "windows-x64", "dataset")

    def test_changed_sources_invalidate_installer_provenance(self):
        import artifact_provenance as provenance
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.py"
            source.write_text("before")
            artifact = root / "setup.exe"
            artifact.write_bytes(b"installer")
            provenance.write_provenance(artifact, "service", [source], root=root, target="windows-x64")
            provenance.verify_provenance(artifact, "service", [source], root=root, target="windows-x64")
            source.write_text("after")
            with self.assertRaisesRegex(ValueError, "source"):
                provenance.verify_provenance(artifact, "service", [source], root=root, target="windows-x64")

    def test_changed_artifact_is_rejected_even_when_sources_match(self):
        import artifact_provenance as provenance
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.py"
            source.write_text("source")
            artifact = root / "setup.exe"
            artifact.write_bytes(b"installer")
            provenance.write_provenance(artifact, "service", [source], root=root, target="windows-x64")
            artifact.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "artifact"):
                provenance.verify_provenance(artifact, "service", [source], root=root, target="windows-x64")

    def test_manifest_traversal_and_external_links_are_rejected(self):
        import build_desktop_kit as kit
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundle"
            root.mkdir()
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                kit.checked_child(root, "../outside")

    def test_gui_inventory_rejects_modified_worker_binary(self):
        import build_desktop_kit as kit
        import artifact_provenance as provenance
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / (gui.APP_NAME + ".exe")
            app.write_bytes(b"fresh")
            record = {"target": "windows-x64", "app": "dataset", "source_sha256": {},
                      "bundle_sha256": {app.name: provenance.file_hash(app)}}
            (root / "BUILD.json").write_text(json.dumps(record))
            with patch.object(gui, "source_hashes", return_value={}):
                kit.verify_gui(root, "windows-x64", "dataset")
                app.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "changed"):
                    kit.verify_gui(root, "windows-x64", "dataset")


if __name__ == "__main__":
    unittest.main()
