"""Offline failure and dependency-closure tests for the ARM64 image repair."""

import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_arm64_image_plugins as plugins


class ImagePluginBuildTests(unittest.TestCase):
    def test_sdk_extraction_selects_minimum_chained_link_option(self):
        for version, option in (("26.02", "-snld10"), ("25.01", "-snld"), ("16.02", None)):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                with patch.object(plugins, "file_hash", return_value=plugins.ARCHIVES[plugins.SDK_NAME]["sha256"]), \
                        patch.object(plugins, "run", side_effect=["7-Zip [64] " + version, ""]) as run:
                    record = plugins.extract_sdk(Path("sdk.7z"), Path(directory))
                    command = run.call_args.args[0]
                    if option:
                        self.assertIn(option, command)
                    else:
                        self.assertFalse(any(str(value).startswith("-snld") for value in command))
                    self.assertNotIn("-snld20", command)
                    self.assertEqual(record["symlinks"], {})

    def test_sdk_extraction_rejects_changed_archive_before_invoking_tool(self):
        with patch.object(plugins, "file_hash", return_value="changed"), patch.object(plugins, "run") as run:
            with self.assertRaisesRegex(ValueError, "checksum"):
                plugins.extract_sdk(Path("sdk.7z"), Path("sdk"))
            run.assert_not_called()

    def test_sdk_link_validation_accepts_internal_chain_and_rejects_unsafe_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / "sdk"
            sdk.mkdir()
            (sdk / "libQt.so.6.7.3").write_bytes(b"fixture")
            try:
                (sdk / "libQt.so.6").symlink_to("libQt.so.6.7.3")
                (sdk / "libQt.so").symlink_to("libQt.so.6")
            except OSError as error:
                self.skipTest("Symbolic link creation unavailable: " + str(error))
            self.assertEqual(plugins.validate_sdk_links(sdk), {
                "libQt.so": "libQt.so.6", "libQt.so.6": "libQt.so.6.7.3"})
            (root / "outside").write_bytes(b"outside")
            # Windows may reject a POSIX relative link while resolving it;
            # either diagnostic must fail closed before the SDK can be used.
            escape_message = "escapes|Dangling" if sys.platform == "win32" else "escapes"
            for target, message in (("../outside", escape_message), (str(root / "outside"), "absolute"),
                                    ("missing", "Dangling"), ("bad", "cyclic")):
                with self.subTest(target=target):
                    (sdk / "bad").symlink_to(target)
                    try:
                        with self.assertRaisesRegex(ValueError, message):
                            plugins.validate_sdk_links(sdk)
                    finally:
                        (sdk / "bad").unlink()

    def test_failed_command_exposes_both_diagnostic_streams(self):
        error = subprocess.CalledProcessError(1, ["cmake"], output="configure context\n", stderr="missing dependency\n")
        with patch.object(plugins.subprocess, "run", side_effect=error), patch.object(plugins.sys, "stderr", io.StringIO()) as stream:
            with self.assertRaises(subprocess.CalledProcessError):
                plugins.run(["cmake"])
            self.assertIn("configure context", stream.getvalue())
            self.assertIn("missing dependency", stream.getvalue())

    def test_source_extraction_rejects_traversal_links_and_devices_before_writing(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE),
                           ("source/link", tarfile.SYMTYPE), ("source/hardlink", tarfile.LNKTYPE),
                           ("source/device", tarfile.CHRTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive_path = root / "fixture.tar"
                with tarfile.open(archive_path, "w") as archive:
                    valid = tarfile.TarInfo("source/valid.txt")
                    valid.size = 2
                    archive.addfile(valid, io.BytesIO(b"ok"))
                    invalid = tarfile.TarInfo(name)
                    invalid.type = kind
                    invalid.linkname = "../../outside"
                    archive.addfile(invalid)
                output = root / "output"
                output.mkdir()
                with self.assertRaisesRegex(ValueError, "Unsafe Qt source"):
                    plugins.extract_sources(archive_path, output)
                self.assertEqual(list(output.iterdir()), [])

    def test_source_extraction_retains_regular_file_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "fixture.tar"
            with tarfile.open(archive_path, "w") as archive:
                entry = tarfile.TarInfo("source/nested/input.cpp")
                entry.size = 4
                entry.mode = 0o644
                archive.addfile(entry, io.BytesIO(b"code"))
            plugins.extract_sources(archive_path, root / "output")
            self.assertEqual((root / "output/source/nested/input.cpp").read_bytes(), b"code")

    def test_host_rejects_wrong_architecture_and_newer_glibc(self):
        with patch.object(plugins.platform, "system", return_value="Linux"), \
                patch.object(plugins.platform, "machine", return_value="x86_64"), \
                patch.object(plugins.platform, "libc_ver", return_value=("glibc", "2.36")):
            with self.assertRaisesRegex(ValueError, "ARM64"):
                plugins.check_host()
        with patch.object(plugins.platform, "system", return_value="Linux"), \
                patch.object(plugins.platform, "machine", return_value="aarch64"), \
                patch.object(plugins.platform, "libc_ver", return_value=("glibc", "2.39")):
            with self.assertRaisesRegex(ValueError, "glibc"):
                plugins.check_host()

    def test_codec_packages_require_exact_version_and_architecture(self):
        for record in ({"version": "1.5.0", "architecture": "arm64"},
                       {"version": "1.2.4-0.2+deb12u1", "architecture": "amd64"}):
            with self.subTest(record=record), patch.object(plugins, "package_record", return_value=record):
                with self.assertRaisesRegex(ValueError, "Unexpected codec"):
                    plugins.check_codecs()

    def test_corrupt_cached_archive_fails_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / plugins.SOURCE_NAME).write_bytes(b"corrupted")
            with patch.object(plugins.urllib.request, "urlopen") as network:
                with self.assertRaisesRegex(ValueError, "checksum"):
                    plugins.download(cache, plugins.SOURCE_NAME)
                network.assert_not_called()

    def test_elf_rejects_wrong_machine_and_glibc(self):
        with patch.object(plugins, "run", return_value="Machine: X86-64"):
            with self.assertRaisesRegex(ValueError, "AArch64"):
                plugins.elf_record(Path("fixture.so"))
        with patch.object(plugins, "run", side_effect=["Machine: AArch64", "", "Name: GLIBC_2.38"]):
            with self.assertRaisesRegex(ValueError, "newer than"):
                plugins.elf_record(Path("fixture.so"))

    def test_ldd_missing_dependency_fails_and_search_path_is_bundle_scoped(self):
        with patch.object(plugins, "run", return_value="libwebp.so.7 => not found") as run:
            with self.assertRaisesRegex(ValueError, "Unresolved"):
                plugins.resolved_dependencies(Path("plugin.so"), Path("/bundle/_internal"))
            environment = run.call_args.kwargs["env"]
            self.assertNotIn("LD_PRELOAD", environment)
            self.assertEqual(environment["LD_LIBRARY_PATH"], plugins.os.pathsep.join((
                str(Path("/bundle/_internal")), str(Path("/bundle/_internal/PyQt6/Qt6/lib")))))

    def test_ldd_preserves_paths_with_spaces(self):
        path = "/codec space/libwebp.so.7"
        with patch.object(plugins, "run", return_value=f"libwebp.so.7 => {path} (0x00000000123)\n"):
            self.assertEqual(plugins.resolved_dependencies(Path(path), Path("/codec space")),
                             {"libwebp.so.7": Path(path).resolve()})

    def test_debian_owner_uses_usrmerge_fallback_without_guessing(self):
        with patch.object(plugins, "Path", PurePosixPath), patch.object(plugins, "run", side_effect=[
                subprocess.CalledProcessError(1, ["dpkg-query"]),
                "libfoo1:arm64: /lib/aarch64-linux-gnu/libfoo.so.1\n"]), \
                patch.object(plugins, "package_record", return_value={"package": "libfoo1:arm64"}) as record:
            self.assertEqual(plugins.library_package(Path("/usr/lib/aarch64-linux-gnu/libfoo.so.1")),
                             {"package": "libfoo1:arm64"})
            record.assert_called_once_with("libfoo1:arm64")

    def test_prepared_cache_rejects_unpinned_archive_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = Path(directory)
            (prepared / "MANIFEST.json").write_text(json.dumps({
                "schema": 1, "qt_version": "6.7.3", "archives": {}}))
            with self.assertRaisesRegex(ValueError, "pinned inputs"):
                plugins.verify_prepared(prepared)

    def test_prepared_cache_rejects_changed_recipe_or_codec_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = Path(directory)
            manifest = {"schema": 1, "qt_version": plugins.QT_VERSION, "archives": plugins.ARCHIVES,
                        "recipe_sha256": "old recipe", "development_packages": {"old": "codec"}}
            plugins.write_json(prepared / "MANIFEST.json", manifest)
            with self.assertRaisesRegex(ValueError, "recipe changed"):
                plugins.verify_prepared(prepared, development_packages={"new": "codec"})
            manifest["recipe_sha256"] = plugins.file_hash(Path(plugins.__file__))
            plugins.write_json(prepared / "MANIFEST.json", manifest)
            with self.assertRaisesRegex(ValueError, "packages changed"):
                plugins.verify_prepared(prepared, development_packages={"new": "codec"})

    def test_preserved_library_attribution_requires_matching_hash_and_soname(self):
        listing = "libwebp.so.7 (libc6,AArch64) => /usr/lib/aarch64-linux-gnu/libwebp.so.7.1.5\n"
        candidate = Path("/usr/lib/aarch64-linux-gnu/libwebp.so.7.1.5")
        for soname, digest, accepted in (("libwebp.so.7", "expected", True),
                                         ("libwebp.so.7", "changed", False),
                                         ("libwebp.so.6", "expected", False)):
            with self.subTest(soname=soname, digest=digest), \
                    patch.object(plugins, "run", return_value=listing), \
                    patch.object(Path, "resolve", lambda path: path), \
                    patch.object(plugins, "elf_record", return_value={"soname": soname, "sha256": digest}):
                if accepted:
                    self.assertEqual(plugins.matching_system_library("libwebp.so.7", "expected"), candidate)
                else:
                    with self.assertRaisesRegex(ValueError, "no system library matches"):
                        plugins.matching_system_library("libwebp.so.7", "expected")

    def test_install_preserves_existing_closure_and_replaces_only_two_plugins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, prepared = root / "bundle", root / "prepared"
            imageformats = bundle / plugins.PLUGIN_DIRECTORY
            imageformats.mkdir(parents=True)
            (prepared / "licenses/qtimageformats").mkdir(parents=True)
            (prepared / "licenses/qtimageformats/LGPL-3.0-only.txt").write_text("fixture license")
            untouched = imageformats / "libqjpeg.so"
            untouched.write_bytes(b"original jpeg")
            codec_names = set().union(*plugins.PLUGINS.values())
            internal = bundle / "_internal"
            for name in codec_names | {"libstdc++.so.6"}:
                (internal / name).write_bytes(("existing " + name).encode())
            for name in plugins.PLUGINS:
                (imageformats / name).write_bytes(b"old plugin")
                (prepared / name).write_bytes(b"rebuilt plugin")

            def elf(path):
                return {"sha256": plugins.file_hash(path), "machine": "AArch64", "soname": path.name,
                        "needed": ["libstdc++.so.6", "libc.so.6"] if path.name in codec_names else ["libc.so.6"]}

            def resolved(path, _internal):
                needed = plugins.PLUGINS.get(path.name, {"libstdc++.so.6"} if path.name in codec_names else set())
                return {name: internal / name for name in needed}

            before = {p.name: p.read_bytes() for p in internal.glob("*.so.*")}
            documentation = root / "debian-documentation"
            (documentation / "fixture-codec").mkdir(parents=True)
            (documentation / "fixture-codec/copyright").write_text("Debian copyright fixture")
            package = {"package": "fixture-codec:arm64", "version": "1.2.4-0.2+deb12u1",
                       "architecture": "arm64", "source": "libwebp", "source_version": "1.2.4-0.2+deb12u1"}
            with patch.object(plugins, "check_host"), patch.object(plugins, "verify_prepared", return_value={}), \
                    patch.object(plugins, "elf_record", side_effect=elf), \
                    patch.object(plugins, "DEBIAN_DOCUMENTATION", documentation), \
                    patch.object(plugins, "matching_system_library", side_effect=lambda name, digest: Path("/usr/lib/aarch64-linux-gnu") / name) as matching, \
                    patch.object(plugins, "library_package", return_value=package), \
                    patch.object(plugins, "resolved_dependencies", side_effect=resolved):
                record = plugins.install(bundle, prepared)
            self.assertEqual(set(record["libraries"]), codec_names | {"libstdc++.so.6"})
            self.assertTrue(all(value["preserved_existing"] for value in record["libraries"].values()))
            self.assertEqual(matching.call_count, len(codec_names) + 1)
            for name, library in record["libraries"].items():
                self.assertEqual(library["package"], package)
                self.assertEqual((bundle / library["copyright"]).read_text(), "Debian copyright fixture")
                self.assertEqual(library["sha256"], plugins.file_hash(internal / name))
            self.assertEqual(before, {p.name: p.read_bytes() for p in internal.glob("*.so.*")})
            self.assertEqual(untouched.read_bytes(), b"original jpeg")
            for name in plugins.PLUGINS:
                self.assertEqual((imageformats / name).read_bytes(), b"rebuilt plugin")
            provenance = json.loads((internal / "arm64-image-plugins/PROVENANCE.json").read_text())
            self.assertEqual(provenance, record)


if __name__ == "__main__":
    unittest.main()
