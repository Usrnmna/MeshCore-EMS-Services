"""Rebuild the two Qt 6.7.3 ARM64 image plugins against Debian 12 codecs.

The SDK supplies build headers and tools only. Installed applications retain
their pinned wheel Qt runtime. Downloads, source builds and notices stay inside
the selected work directory; no system packages or services are modified.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

QT_VERSION = "6.7.3"
SOURCE_NAME = "qtimageformats-everywhere-src-6.7.3.tar.xz"
SDK_NAME = "6.7.3-0-202409200836qtbase-Linux-Debian_11_6-GCC-Linux-Debian_11_6-AARCH64.7z"
ARCHIVES = {
    SOURCE_NAME: {
        "url": "https://download.qt.io/archive/qt/6.7/6.7.3/submodules/" + SOURCE_NAME,
        "sha256": "9fd58144081654c3373768dd96ead294023830927b14fe3d3c1ef641fb324753",
    },
    SDK_NAME: {
        "url": "https://download.qt.io/online/qtsdkrepository/linux_arm64/desktop/qt6_673/qt.qt6.673.linux_gcc_arm64/" + SDK_NAME,
        "sha256": "850f7d2b73c958ce80ef47a81c18f64d03d3be606637278d14acb8959e6dfe8c",
    },
}
CODEC_PACKAGES = {"libwebp-dev": "1.2.4-0.2+deb12u1", "libtiff-dev": "4.5.0-6+deb12u4"}
PLUGINS = {"libqwebp.so": {"libwebp.so.7", "libwebpdemux.so.2", "libwebpmux.so.3"},
           "libqtiff.so": {"libtiff.so.6"}}
SYSTEM_RUNTIME = {"libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2",
                  "librt.so.1", "libresolv.so.2", "libutil.so.1", "ld-linux-aarch64.so.1"}
PLUGIN_DIRECTORY = Path("_internal/PyQt6/Qt6/plugins/imageformats")
PLUGIN_RPATH = "$ORIGIN/../../lib:$ORIGIN/../../../.."
DEBIAN_DOCUMENTATION = Path("/usr/share/doc")


def run(arguments, *, env=None):
    """Run a checked argv command with deterministic English diagnostic output."""
    environment = dict(os.environ if env is None else env, LC_ALL="C")
    try:
        return subprocess.run([str(value) for value in arguments], check=True,
                              capture_output=True, text=True, env=environment).stdout
    except subprocess.CalledProcessError as error:
        # CMake and compiler failures often explain the cause only in captured
        # output. Preserve the exception type while making both streams visible.
        for output in (error.stdout, error.stderr):
            if output:
                print(output, file=sys.stderr, end="" if output.endswith("\n") else "\n")
        raise


def file_hash(path):
    """Hash file contents without depending on timestamps or archive metadata."""
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_host():
    """Reject another architecture or a glibc baseline newer than Bookworm."""
    libc, release = platform.libc_ver()
    if platform.system() != "Linux" or platform.machine().lower() not in {"aarch64", "arm64"}:
        raise ValueError("The image plugin build requires a native ARM64 Linux environment")
    if libc != "glibc" or not re.fullmatch(r"\d+\.\d+", release) or tuple(map(int, release.split("."))) > (2, 36):
        raise ValueError("The image plugin build requires glibc 2.36 or older")
    return {"machine": "AArch64", "libc": [libc, release]}


def package_record(name):
    """Record the installed Debian binary and corresponding source version."""
    fields = run(["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Architecture}\t${source:Package}\t${source:Version}", name]).strip().split("\t")
    if len(fields) != 5:
        raise ValueError("Incomplete Debian package metadata: " + name)
    return dict(zip(("package", "version", "architecture", "source", "source_version"), fields))


def check_codecs():
    """Require the reviewed Bookworm development packages before compiling."""
    records = {}
    for name, version in CODEC_PACKAGES.items():
        record = package_record(name)
        if record["version"] != version or record["architecture"] != "arm64":
            raise ValueError("Unexpected codec development package: " + repr(record))
        records[name] = record
    return records


def download(cache, name):
    """Fetch an official pinned archive, rejecting corrupt cached downloads."""
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / name
    if not destination.exists():
        partial = destination.with_name(destination.name + ".partial")
        with urllib.request.urlopen(ARCHIVES[name]["url"], timeout=120) as source, partial.open("wb") as output:
            shutil.copyfileobj(source, output)
        if file_hash(partial) != ARCHIVES[name]["sha256"]:
            partial.unlink()
            raise ValueError("Archive checksum mismatch: " + name)
        partial.replace(destination)
    if file_hash(destination) != ARCHIVES[name]["sha256"]:
        raise ValueError("Archive checksum mismatch: " + name)
    return destination


def elf_record(path):
    """Inspect native ELF architecture, SONAME, dependencies and glibc versions."""
    header = run(["readelf", "-h", path])
    if not re.search(r"Machine:\s+AArch64\b", header):
        raise ValueError("Expected an AArch64 ELF file: " + str(path))
    dynamic = run(["readelf", "-d", path])
    required = sorted(set(re.findall(r"\(NEEDED\).*?\[([^]]+)\]", dynamic)))
    sonames = re.findall(r"\(SONAME\).*?\[([^]]+)\]", dynamic)
    versions = {tuple(map(int, value.split("."))) for value in
                re.findall(r"\bGLIBC_(\d+\.\d+(?:\.\d+)?)\b", run(["readelf", "--version-info", path]))}
    if any(version > (2, 36) for version in versions):
        raise ValueError("ELF requires glibc newer than 2.36: " + str(path))
    return {"sha256": file_hash(path), "machine": "AArch64", "needed": required,
            "soname": sonames[0] if sonames else None,
            "maximum_glibc": ".".join(map(str, max(versions))) if versions else None}


def extract_sources(archive_path, destination):
    """Extract regular Qt source files without newer tarfile filter APIs.

    Preflight the entire archive before writing. Qt's pinned source archive has
    no links or special files; rejecting those types avoids link traversal and
    device creation on Python versions without extraction filters.
    """
    destination = Path(destination).resolve()
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        targets = []
        for member in members:
            relative = PurePosixPath(member.name)
            target = (destination / member.name).resolve()
            if (relative.is_absolute() or ".." in relative.parts or "\\" in member.name
                    or ":" in member.name or not target.is_relative_to(destination)
                    or not (member.isdir() or member.isreg())):
                raise ValueError("Unsafe Qt source archive member: " + member.name)
            targets.append((member, target))
        for member, target in targets:
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)


def validate_sdk_links(destination):
    """Require SDK links to resolve to existing entries inside the SDK tree.

    Walking does not follow directory symlinks. Each complete link chain is
    resolved strictly, rejecting loops, dangling links and boundary escapes.
    """
    destination = Path(destination).resolve()
    links = {}
    for directory, folders, files in os.walk(destination, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            if path.is_symlink():
                target = os.readlink(path)
                if Path(target).is_absolute() or "\\" in target or ":" in target:
                    raise ValueError("Unsafe absolute SDK link: " + str(path))
                try:
                    resolved = path.resolve(strict=True)
                except (OSError, RuntimeError) as error:
                    raise ValueError("Dangling or cyclic SDK link: " + str(path)) from error
                if not resolved.is_relative_to(destination):
                    raise ValueError("SDK link escapes its directory: " + str(path))
                links[path.relative_to(destination).as_posix()] = target
            elif not (path.is_dir() or path.is_file()):
                raise ValueError("Unsupported special SDK file: " + str(path))
    return dict(sorted(links.items()))


def extract_sdk(archive_path, destination):
    """Extract only the pinned official SDK and validate its original links.

    7-Zip 26 rejects even relative library symlink chains by default. Its source
    permits chains at level 10 while retaining path checks (level 20 disables
    them). Older releases used -snld without a numeric level, or no such gate.
    No SDK executable is used until all extracted link chains pass validation.
    """
    if file_hash(archive_path) != ARCHIVES[SDK_NAME]["sha256"]:
        raise ValueError("SDK archive checksum mismatch")
    destination = Path(destination)
    if destination.is_symlink() or any(destination.iterdir()):
        raise ValueError("SDK extraction requires an empty, non-symlink directory")
    help_text = run(["7z", "-h"])
    version = re.search(r"7-Zip[^\n]*?\b(\d+)\.(\d+)\b", help_text)
    if not version:
        raise ValueError("Cannot determine the installed 7-Zip version")
    major = int(version[1])
    arguments = ["7z", "x", archive_path, "-o" + str(destination), "-y"]
    if major >= 26:
        arguments.append("-snld10")
    elif major >= 21:
        arguments.append("-snld")
    run(arguments)
    return {"version": version[0], "command": [str(value) for value in arguments],
            "symlinks": validate_sdk_links(destination)}


def prepare(work: Path, cache: Path | None = None) -> Path:
    """Build exact-version plugins in a fresh work directory and return output.

    A completed, checksummed output may be reused. Partial build directories are
    intentionally not reused; choose another work directory after a failed build.
    """
    host = check_host()
    packages = check_codecs()
    work = Path(work).resolve()
    output = work / "prepared"
    if (output / "MANIFEST.json").is_file():
        verify_prepared(output, development_packages=packages)
        return output
    for program in ("cmake", "ninja", "g++", "pkg-config", "7z", "readelf", "patchelf"):
        if not shutil.which(program):
            raise ValueError("Required build tool is missing: " + program)
    work.mkdir(parents=True, exist_ok=True)
    cache = Path(cache).resolve() if cache else work / "downloads"
    source_archive = download(cache, SOURCE_NAME)
    sdk_archive = download(cache, SDK_NAME)
    sources, sdk, build = work / "sources", work / "sdk", work / "build"
    for path in (sources, sdk, build, output):
        path.mkdir(exist_ok=False)
    extract_sources(source_archive, sources)
    sdk_extraction = extract_sdk(sdk_archive, sdk)
    qt_cmake = list(sdk.rglob("bin/qt-cmake"))
    if len(qt_cmake) != 1:
        raise ValueError("Expected one Qt SDK qt-cmake entry point")
    source = sources / "qtimageformats-everywhere-src-6.7.3"
    commands = [
        [str(qt_cmake[0]), "-S", str(source), "-B", str(build), "-G", "Ninja",
         "-DCMAKE_BUILD_TYPE=Release", "-DINPUT_webp=system", "-DINPUT_tiff=system",
         "-DFEATURE_system_webp=ON", "-DFEATURE_system_tiff=ON", "-DBUILD_TESTING=OFF"],
        ["cmake", "--build", str(build), "--target", "QWebpPlugin", "QTiffPlugin"],
    ]
    for command in commands:
        run(command)
    plugins = {}
    for name, required in PLUGINS.items():
        candidates = list(build.rglob(name))
        if len(candidates) != 1:
            raise ValueError("Expected one compiled plugin: " + name)
        destination = output / name
        shutil.copy2(candidates[0], destination)
        command = ["patchelf", "--set-rpath", PLUGIN_RPATH, str(destination)]
        run(command)
        commands.append(command)
        record = elf_record(destination)
        if not required.issubset(record["needed"]):
            raise ValueError("Plugin did not link the Bookworm codec SONAMEs: " + name)
        plugins[name] = record
    notices = output / "licenses"
    shutil.copytree(source / "LICENSES", notices / "qtimageformats")
    attribution = ["Qt Image Formats " + QT_VERSION,
                   "Complete corresponding source: " + ARCHIVES[SOURCE_NAME]["url"], ""]
    for directory in ("webp", "tiff"):
        for path in sorted((source / "src/plugins/imageformats" / directory).glob("*")):
            if path.suffix in {".cpp", ".h"}:
                lines = path.read_text(encoding="utf-8").splitlines()
                attribution.extend([path.relative_to(source).as_posix()] + [
                    line for line in lines if "Copyright" in line or "SPDX-License-Identifier:" in line] + [""])
    (notices / "qtimageformats/NOTICES.txt").write_text("\n".join(attribution), encoding="utf-8")
    manifest = {"schema": 1, "qt_version": QT_VERSION, "host": host,
                "archives": ARCHIVES, "development_packages": packages,
                "recipe_sha256": file_hash(Path(__file__)),
                "sdk_extraction": sdk_extraction,
                "commands": commands, "plugins": plugins,
                "qtbase_source_url": "https://download.qt.io/archive/qt/6.7/6.7.3/submodules/qtbase-everywhere-src-6.7.3.tar.xz",
                "licenses": {p.relative_to(output).as_posix(): file_hash(p) for p in notices.rglob("*") if p.is_file()}}
    write_json(output / "MANIFEST.json", manifest)
    return output


def verify_prepared(prepared, development_packages=None):
    """Reject stale inputs, changed plugins, missing notices and malformed caches."""
    prepared = Path(prepared)
    manifest = json.loads((prepared / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("qt_version") != QT_VERSION or manifest.get("archives") != ARCHIVES:
        raise ValueError("Prepared image plugin provenance does not match the pinned inputs")
    if manifest.get("recipe_sha256") != file_hash(Path(__file__)):
        raise ValueError("Prepared image plugin build recipe changed; rebuild it")
    current_packages = check_codecs() if development_packages is None else development_packages
    if manifest.get("development_packages") != current_packages:
        raise ValueError("Prepared image plugin codec development packages changed; rebuild it")
    if set(manifest.get("plugins", {})) != set(PLUGINS) or not manifest.get("licenses"):
        raise ValueError("Prepared image plugin inventory is incomplete")
    for name, record in manifest["plugins"].items():
        if elf_record(prepared / name) != record or not PLUGINS[name].issubset(record["needed"]):
            raise ValueError("Prepared image plugin changed: " + name)
    for name, expected in manifest["licenses"].items():
        path = (prepared / name).resolve()
        if not path.is_relative_to(prepared.resolve()) or file_hash(path) != expected:
            raise ValueError("Prepared license changed: " + name)
    return manifest


def resolved_dependencies(path, internal):
    """Resolve through the bundle first and reject every missing ldd dependency."""
    environment = dict(os.environ)
    environment.pop("LD_PRELOAD", None)
    environment["LD_LIBRARY_PATH"] = os.pathsep.join((str(internal), str(internal / "PyQt6/Qt6/lib")))
    output = run(["ldd", path], env=environment)
    if "not found" in output:
        raise ValueError("Unresolved ELF dependency: " + output.strip())
    resolved = {}
    for line in output.splitlines():
        match = re.match(r"\s*(\S+)\s+=>\s+(/.+?)\s+\(0x[0-9a-fA-F]+\)", line)
        if match:
            resolved[match[1]] = Path(match[2]).resolve()
    return resolved


def library_package(path):
    """Find Debian provenance without guessing library-to-package associations."""
    path = Path(path)
    candidates = [path]
    if str(path).startswith("/usr/lib/"):
        candidates.append(Path(str(path)[4:]))
    for candidate in candidates:
        try:
            owners = run(["dpkg-query", "-S", candidate]).strip().splitlines()
        except subprocess.CalledProcessError:
            continue
        if len(owners) == 1 and ": " in owners[0]:
            return package_record(owners[0].split(": ", 1)[0])
    raise ValueError("No unique Debian package owns codec dependency: " + str(path))


def matching_system_library(soname, expected_sha256):
    """Attribute a preserved library only to a byte-identical system ELF.

    The dynamic linker's cache supplies candidate paths. Both the ELF SONAME
    and complete SHA-256 must match, so a familiar filename alone never assigns
    Debian provenance to a bundled or modified third-party library.
    """
    candidates = set()
    for line in run(["ldconfig", "-p"]).splitlines():
        match = re.match(r"\s*(\S+)\s+\([^)]*\)\s+=>\s+(/.+)$", line)
        if match and match[1] == soname:
            candidate = Path(match[2]).resolve()
            if candidate.as_posix().startswith(("/usr/lib/", "/lib/")):
                candidates.add(candidate)
    matches = []
    for candidate in sorted(candidates):
        try:
            record = elf_record(candidate)
        except ValueError:
            # A multiarch cache can contain another architecture's SONAME.
            continue
        if record["soname"] == soname and record["sha256"] == expected_sha256:
            matches.append(candidate)
    if not matches:
        raise ValueError("Cannot attribute preserved codec library to Debian: " + soname
                         + "; no system library matches both SONAME and SHA-256")
    if len(matches) != 1:
        raise ValueError("Ambiguous Debian attribution for preserved codec library: " + soname)
    return matches[0]


def install(bundle: Path, prepared: Path) -> dict:
    """Replace two frozen plugins and bundle their actual codec dependency closure.

    Existing libraries are never overwritten. The system loader and glibc stay
    on the target OS; all codec branches must resolve inside the final bundle.
    Call before computing the enclosing application bundle inventory.
    """
    check_host()
    manifest = verify_prepared(prepared)
    bundle, prepared = Path(bundle).resolve(), Path(prepared).resolve()
    internal = bundle / "_internal"
    destination = bundle / PLUGIN_DIRECTORY
    if not all((destination / name).is_file() for name in PLUGINS):
        raise ValueError("Both original frozen image plugins must exist")
    changes = {}
    for name in PLUGINS:
        changes[name] = {"original_sha256": file_hash(destination / name), "replacement_sha256": file_hash(prepared / name)}
        shutil.copy2(prepared / name, destination / name)
    queue = []
    for name, codecs in PLUGINS.items():
        resolved = resolved_dependencies(destination / name, internal)
        for codec in sorted(codecs):
            if codec not in resolved:
                raise ValueError("Codec could not be resolved: " + codec)
            queue.append((codec, resolved[codec]))
    libraries, checked = {}, set()
    notices = internal / "arm64-image-plugins/licenses"
    notices.mkdir(parents=True, exist_ok=True)
    shutil.copytree(prepared / "licenses", notices, dirs_exist_ok=True)
    while queue:
        soname, source = queue.pop(0)
        if soname in checked or soname in SYSTEM_RUNTIME:
            continue
        checked.add(soname)
        if soname.startswith("libQt"):
            raise ValueError("Codec closure unexpectedly depends on Qt: " + soname)
        record = elf_record(source)
        if record["soname"] != soname:
            raise ValueError("Codec SONAME mismatch: " + soname)
        if source.is_relative_to(internal):
            library = source
            record["preserved_existing"] = True
            package_source = matching_system_library(soname, record["sha256"])
        else:
            if not str(source).startswith(("/usr/lib/", "/lib/")):
                raise ValueError("Codec dependency is outside Debian system libraries: " + str(source))
            library = internal / soname
            if library.exists():
                raise ValueError("Refusing to overwrite an existing bundled library: " + soname)
            package_source = source
        package = library_package(package_source)
        if package["architecture"] != "arm64":
            raise ValueError("Codec package is not ARM64: " + soname)
        copyright_file = DEBIAN_DOCUMENTATION / package["package"].split(":")[0] / "copyright"
        copyright_target = notices / (package["package"].replace(":", "-") + ".copyright")
        shutil.copy2(copyright_file, copyright_target)
        if not record.get("preserved_existing"):
            shutil.copy2(source, library)
        record.update(package=package, system_source=str(package_source),
                      copyright=copyright_target.relative_to(bundle).as_posix())
        record["path"] = library.relative_to(bundle).as_posix()
        libraries[soname] = record
        resolved = resolved_dependencies(library, internal)
        for needed in record["needed"]:
            if needed not in SYSTEM_RUNTIME:
                if needed not in resolved:
                    raise ValueError("Codec dependency cannot be resolved: " + needed)
                queue.append((needed, resolved[needed]))
    # Re-resolve after the complete closure exists, using the installed files.
    for path in [destination / name for name in PLUGINS] + [bundle / r["path"] for r in libraries.values()]:
        resolved = resolved_dependencies(path, internal)
        for name in set(resolved) & checked:
            if not resolved[name].is_relative_to(internal):
                raise ValueError("Installed codec still resolves outside the bundle: " + name)
    provenance = {"build": manifest, "replacements": changes, "libraries": libraries,
                  "notices": {p.relative_to(bundle).as_posix(): file_hash(p) for p in notices.rglob("*") if p.is_file()}}
    write_json(internal / "arm64-image-plugins/PROVENANCE.json", provenance)
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Native Linux build work directory")
    parser.add_argument("--cache", type=Path, help="Optional verified archive cache")
    parser.add_argument("--bundle", type=Path, help="Install into this already frozen ARM64 application")
    arguments = parser.parse_args()
    prepared = prepare(arguments.output, arguments.cache)
    if arguments.bundle:
        install(arguments.bundle, prepared)
    print(prepared)


if __name__ == "__main__":
    main()
