"""Native child code search is independent of desktop interpreter/loader overrides."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installers.desktop.native_environment import clean_environment


class NativeEnvironmentTests(unittest.TestCase):
    def test_interpreter_loader_and_pip_code_overrides_are_not_inherited(self):
        unsafe = {key: "untrusted" for key in ("PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH_ORIG", "LD_LIBRARY_PATH", "PIP_TARGET", "PIP_INDEX_URL", "BASH_ENV", "PSModulePath")}
        with patch.dict(os.environ, unsafe):
            value = clean_environment()
        self.assertTrue(all(key not in value for key in unsafe if key != "PSModulePath"))
        self.assertNotIn("untrusted", value.get("PSModulePath", ""))
        self.assertEqual(value["PIP_CONFIG_FILE"], os.devnull)

    def test_fixed_native_paths_preserve_ordinary_locale_and_lease_context(self):
        with patch.dict(os.environ, {"PATH": "untrusted", "SystemRoot": "untrusted", "LANG": "C.UTF-8", "MESHCORE_MAINTENANCE_LEASE": "a" * 32}):
            value = clean_environment()
        self.assertNotIn("untrusted", value["PATH"])
        self.assertEqual(value["LANG"], "C.UTF-8")
        self.assertEqual(value["MESHCORE_MAINTENANCE_LEASE"], "a" * 32)
        if os.name == "nt":
            self.assertNotEqual(value["SystemRoot"], "untrusted")
            self.assertFalse(any(key != "SystemRoot" and key.upper() == "SYSTEMROOT" for key in value))

    def test_native_temporary_files_use_the_supplied_private_context(self):
        directory = str(Path.cwd() / ".build/private-native-fixture")
        with patch.dict(os.environ, {"TEMP": "untrusted", "TMP": "untrusted", "TMPDIR": "untrusted"}):
            value = clean_environment(directory)
        self.assertTrue(all(value[key] == directory for key in ("TEMP", "TMP", "TMPDIR")))


if __name__ == "__main__":
    unittest.main()
