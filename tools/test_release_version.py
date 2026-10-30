"""Keep maintained installer and desktop release identities aligned."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from installers.desktop.version import VERSION
import build_data_installers
import build_installers


class ReleaseVersionTests(unittest.TestCase):
    def test_authoritative_package_and_builder_versions_agree(self):
        self.assertEqual(VERSION, "v0.9.8-beta")
        self.assertEqual(build_installers.VERSION, VERSION)
        self.assertEqual(build_data_installers.VERSION, VERSION)
        for package in ("meshcore_mqtt_service", "meshcore_mqtt_service_windows"):
            self.assertEqual((ROOT / package / "VERSION.txt").read_text().strip(), VERSION)

    def test_native_installer_and_launcher_metadata_agree(self):
        numeric = VERSION.removeprefix("v").split("-", 1)[0] + ".0"
        for name in ("installers/windows/ServiceHost.cs", "meshcore_mqtt_service_windows/Start-Service.cs"):
            source = (ROOT / name).read_text()
            self.assertIn('AssemblyInformationalVersion("' + VERSION + '")', source)
            self.assertIn('AssemblyFileVersion("' + numeric + '")', source)
        setup = (ROOT / "installers/windows/setup.iss").read_text()
        self.assertIn("AppVersion=" + VERSION, setup)
        self.assertIn("VersionInfoVersion=" + numeric, setup)
        self.assertIn("MeshCore-EMS-" + VERSION + "-windows-x64-setup", setup)
        self.assertIn("'" + numeric + "'", (ROOT / "installers/datasets/windows/build_tool.ps1").read_text())

    def test_current_badge_and_release_document_exist(self):
        self.assertIn(VERSION, (ROOT / "docs/assets/version-badge.svg").read_text())
        self.assertTrue((ROOT / ("RELEASE_" + VERSION + ".md")).is_file())


if __name__ == "__main__":
    unittest.main()
