"""Exercise actual Qt decoding and fail-closed packaged image verification."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from installers.desktop import image_smoke
from tools import test_packaged_history as packaged


class ImageSmokeTests(unittest.TestCase):
    def test_successful_decodes_return_cleanly_in_a_fresh_process(self):
        # The TIFF handler uses its borrowed QBuffer during destruction. A
        # subprocess makes a native lifetime regression a reported test failure.
        script = """
import json
from installers.desktop.image_smoke import verify_image_decoding
print(json.dumps(verify_image_decoding()))
"""
        result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(set(json.loads(result.stdout)), {"webp", "tiff"})

    def test_fixed_images_decode_to_known_dimensions_and_pixels(self):
        results = image_smoke.verify_image_decoding()
        self.assertEqual(set(results), {"webp", "tiff"})
        for result in results.values():
            self.assertEqual((result["width"], result["height"]), (3, 2))
            self.assertEqual(result["rgba_pixels"], [
                [255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255],
                [0, 0, 0, 255], [255, 255, 255, 255], [255, 255, 0, 255]])

    def test_missing_native_decoders_fail_for_each_fixed_format(self):
        # A fresh process is required because Qt caches loaded native plugins.
        # Empty search paths disable the actual plugins without mocking a reader.
        script = """
import sys
from PyQt6.QtCore import QCoreApplication
from installers.desktop.image_smoke import decode_fixture
application = QCoreApplication([])
QCoreApplication.setLibraryPaths([])
try:
    decode_fixture(sys.argv[1])
except AssertionError as error:
    print(str(error))
    raise SystemExit(7)
raise SystemExit(0)
"""
        for image_format in ("webp", "tiff"):
            with self.subTest(image_format=image_format):
                result = subprocess.run([sys.executable, "-c", script, image_format],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                    timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                self.assertIn(image_format + " decoding failed", result.stdout)

    def test_fixture_selection_rejects_arbitrary_inputs(self):
        for value in ("png", "../example.webp", "/tmp/example.tiff", b"webp"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                image_smoke.decode_fixture(value)

    def test_packaged_verifier_rejects_missing_or_incomplete_decode_evidence(self):
        for report in ({}, {"checks": ["webp_decode_pixels", "tiff_decode_pixels"]},
                       {"image_decoding": {"webp": {"width": 3, "height": 2}}}):
            with self.subTest(report=report), self.assertRaises(AssertionError):
                packaged.require_image_decoding(report)

    def test_packaged_verifier_accepts_real_decodes_and_rejects_wrong_pixels(self):
        report = {"checks": ["webp_decode_pixels", "tiff_decode_pixels"],
                  "image_decoding": image_smoke.verify_image_decoding()}
        packaged.require_image_decoding(report)
        report["image_decoding"]["tiff"]["rgba_pixels"][0] = [0, 0, 0, 255]
        with self.assertRaises(AssertionError):
            packaged.require_image_decoding(report)

    def test_frozen_linux_library_validation_rejects_external_codec_paths(self):
        root = Path(__file__).resolve().parents[1] / ".build" / "synthetic-frozen"
        libraries = {"webp_plugin": [str(root / "libqwebp.so")],
                     "tiff_plugin": [str(root / "libqtiff.so")],
                     "webp_codec": [str(root / "libwebp.so.7")],
                     "tiff_codec": [str(root / "libtiff.so.6")]}
        image_smoke._validate_loaded_libraries(libraries, root, require_codecs=True)
        libraries["webp_codec"] = [str(root.parent / "build-only" / "libwebp.so.7")]
        with self.assertRaisesRegex(AssertionError, "outside the frozen application"):
            image_smoke._validate_loaded_libraries(libraries, root, require_codecs=True)

    def test_arm64_library_validation_requires_both_dynamic_codecs(self):
        libraries = {"webp_plugin": ["libqwebp.so"], "tiff_plugin": ["libqtiff.so"],
                     "webp_codec": [], "tiff_codec": []}
        image_smoke._validate_loaded_libraries(libraries, None, require_codecs=False)
        with self.assertRaisesRegex(AssertionError, "webp_codec"):
            image_smoke._validate_loaded_libraries(libraries, None, require_codecs=True)

    def test_frozen_library_bind_alias_requires_matching_device_and_inode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "bundle"
            plugins = root / "PyQt6/Qt6/plugins/imageformats"
            plugins.mkdir(parents=True)
            libraries, identities = {}, {}
            for kind, name in (("webp_plugin", "libqwebp.so"), ("tiff_plugin", "libqtiff.so")):
                candidate = plugins / name
                candidate.write_bytes(b"Synthetic identity fixture; no executable code")
                metadata = candidate.stat()
                alias = str(Path(temporary) / "host-bind-alias" / name)
                libraries[kind] = [alias]
                identities[alias] = {"device": metadata.st_dev, "inode": metadata.st_ino}
            evidence = image_smoke._validate_loaded_libraries(libraries, root,
                require_codecs=False, mapped_identities=identities)
            self.assertEqual(len(evidence), 2)
            for item in evidence:
                self.assertEqual(item["raw_mapped_path"], libraries[item["kind"]][0])
                self.assertTrue(Path(item["bundled_path"]).is_relative_to(root.resolve()))
                self.assertEqual(item["identity_proof"]["method"], "device_inode")
                self.assertEqual(item["identity_proof"]["mapped_inode"],
                                 item["identity_proof"]["bundled_inode"])
            identities[libraries["webp_plugin"][0]]["device"] += 1
            with self.assertRaisesRegex(AssertionError, "device/inode mismatch"):
                image_smoke._validate_loaded_libraries(libraries, root,
                    require_codecs=False, mapped_identities=identities)

    def test_external_library_same_name_and_bytes_cannot_pass_as_bundle_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "bundle"
            plugins = root / "PyQt6/Qt6/plugins/imageformats"
            plugins.mkdir(parents=True)
            candidate = plugins / "libqwebp.so"
            candidate.write_bytes(b"Identical bytes are insufficient proof")
            external = Path(temporary) / "libqwebp.so"
            external.write_bytes(candidate.read_bytes())
            metadata = external.stat()
            libraries = {"webp_plugin": [str(external)], "tiff_plugin": [str(plugins / "libqtiff.so")]}
            identities = {str(external): {"device": metadata.st_dev, "inode": metadata.st_ino}}
            with self.assertRaisesRegex(AssertionError, "outside the frozen application"):
                image_smoke._validate_loaded_libraries(libraries, root,
                    require_codecs=False, mapped_identities=identities)

    def test_bundle_alias_rejects_symlink_to_an_external_matching_inode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "bundle"
            root.mkdir()
            external = Path(temporary) / "external-codec"
            external.write_bytes(b"Synthetic identity fixture")
            try:
                (root / "libtiff.so.6").symlink_to(external)
            except OSError as error:
                self.skipTest("Native symlink fixture is unavailable: " + str(error))
            metadata = external.stat()
            alias = str(Path(temporary) / "host-alias" / "libtiff.so.6")
            with self.assertRaisesRegex(AssertionError, "outside the frozen application"):
                image_smoke._bundled_library_evidence("tiff_codec", alias, root.resolve(),
                    {"device": metadata.st_dev, "inode": metadata.st_ino})


if __name__ == "__main__":
    unittest.main()
