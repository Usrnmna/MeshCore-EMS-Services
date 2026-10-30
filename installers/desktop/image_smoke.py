"""Decode fixed synthetic images through the application's native Qt plugins.

The six opaque RGB pixels were encoded once with Qt 6.7.3: lossless WebP
(quality 100) and uncompressed TIFF. The embedded bytes require no encoder,
external file, network access, or additional imaging library at runtime.
"""
import base64
import os
from pathlib import Path
import platform
import stat
import sys


FIXTURES = {
    "webp": "UklGRjIAAABXRUJQVlA4TCYAAAAvAkAAAC8gEEjaH3qN+RcQFPk/2vwHskXCBgIBylhxxSAR/Y/5Ag==",
    "tiff": (
        "SUkqABoAAAD/AAAA/wAAAP8AAAD//////wAOAAABAwABAAAAAwAAAAEBAwABAAAAAgAA"
        "AAIBAwADAAAA2AAAAAMBAwABAAAAAQAAAAYBAwABAAAAAgAAABEBBAABAAAACAAAABIB"
        "AwABAAAAAQAAABUBAwABAAAAAwAAABYBBAABAAAAcRwHABcBBAABAAAAEgAAABoBBQAB"
        "AAAAyAAAABsBBQABAAAA0AAAABwBAwABAAAAAQAAACgBAwABAAAAAgAAAAAAAABkAAAA"
        "AQAAAGQAAAABAAAACAAIAAgA"
    ),
}
EXPECTED_PIXELS = [
    [255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255],
    [0, 0, 0, 255], [255, 255, 255, 255], [255, 255, 0, 255],
]


def decode_fixture(image_format):
    """Decode one allowlisted in-memory fixture and verify every opaque pixel.

    Null images, incorrect dimensions, and altered pixels fail the smoke. A
    plugin's presence in supportedImageFormats alone is insufficient evidence.
    """
    if image_format not in FIXTURES:
        raise ValueError("Unknown synthetic image format")
    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtGui import QImageReader

    buffer = QBuffer()
    buffer.setData(base64.b64decode(FIXTURES[image_format], validate=True))
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        raise AssertionError("Synthetic image buffer could not be opened")
    reader = None
    try:
        reader = QImageReader(buffer, image_format.encode("ascii"))
        decoded = reader.read()
        if decoded.isNull():
            raise AssertionError(image_format + " decoding failed: " + reader.errorString())
        if (decoded.width(), decoded.height()) != (3, 2):
            raise AssertionError(image_format + " decoded dimensions differ from the 3x2 fixture")
        pixels = [list(decoded.pixelColor(x, y).getRgb()) for y in range(2) for x in range(3)]
        if pixels != EXPECTED_PIXELS:
            raise AssertionError(image_format + " decoded pixels differ from the synthetic fixture")
        return {"width": decoded.width(), "height": decoded.height(), "rgba_pixels": pixels}
    finally:
        # QImageReader borrows the device. The TIFF handler can access it while
        # being destroyed, so release the reader before closing its QBuffer.
        del reader
        buffer.close()


def verify_image_decoding():
    """Return pixel evidence only after both required native decoders succeed."""
    return {image_format: decode_fixture(image_format) for image_format in FIXTURES}


def _bundled_library_evidence(kind, raw_path, root, mapped_identity):
    """Prove a mapped library belongs to the bundle, including bind-mount aliases.

    An outside mapping can refer to the same file through a host bind path.
    Only a matching device and inode at the fixed bundled location establishes
    that equivalence; matching names or file contents cannot establish it.
    """
    candidate = Path(raw_path).resolve()
    alias = not candidate.is_relative_to(root)
    if alias:
        directory = root / "PyQt6/Qt6/plugins/imageformats" if kind.endswith("_plugin") else root
        candidate = (directory / Path(raw_path).name).resolve()
    if not candidate.is_relative_to(root) or (alias and mapped_identity is None):
        raise AssertionError("Image library loaded outside the frozen application: " + raw_path)
    proof = {"method": "resolved_path"}
    if mapped_identity is not None:
        try:
            metadata = candidate.stat()
        except OSError as error:
            raise AssertionError("Image library has no accessible bundled identity: " + raw_path) from error
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_ino <= 0
                or (metadata.st_dev, metadata.st_ino) !=
                   (mapped_identity["device"], mapped_identity["inode"])):
            raise AssertionError("Image library loaded outside the frozen application; "
                                 "device/inode mismatch: " + raw_path)
        proof = {"method": "device_inode", "mapped_device": mapped_identity["device"],
                 "mapped_inode": mapped_identity["inode"], "bundled_device": metadata.st_dev,
                 "bundled_inode": metadata.st_ino}
    return {"kind": kind, "raw_mapped_path": raw_path, "bundled_path": str(candidate),
            "bind_alias": alias, "identity_proof": proof}


def _validate_loaded_libraries(libraries, frozen_root, *, require_codecs, mapped_identities=None):
    """Require decoder mappings and keep frozen Linux dependencies inside the app.

    ARM64 uses dynamic codec libraries. Other Linux builds may link codecs into
    the plugins; any separate codec library that is loaded is still checked.
    """
    required = ["webp_plugin", "tiff_plugin"]
    if require_codecs:
        required.extend(["webp_codec", "tiff_codec"])
    for kind in required:
        if not libraries.get(kind):
            raise AssertionError("Decoded image has no loaded " + kind + " evidence")
    evidence = []
    if frozen_root is not None:
        root = Path(frozen_root).resolve()
        for kind, paths in libraries.items():
            for path in paths:
                identity = (mapped_identities or {}).get(path)
                evidence.append(_bundled_library_evidence(kind, path, root, identity))
    return evidence


def loaded_image_libraries():
    """Read Linux mappings after decoding and verify frozen plugin/codec origins.

    Only the fixed process maps file is read. No caller-selected file, executable,
    library search path, or environment override is accepted by the smoke.
    """
    if not sys.platform.startswith("linux"):
        return {}
    libraries = {"webp_plugin": [], "tiff_plugin": [], "webp_codec": [], "tiff_codec": []}
    mapped_identities = {}
    for line in Path("/proc/self/maps").read_text(encoding="utf-8").splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) != 6 or not fields[5].startswith("/"):
            continue
        path = fields[5]
        name = Path(path).name
        if name == "libqwebp.so":
            kind = "webp_plugin"
        elif name == "libqtiff.so":
            kind = "tiff_plugin"
        elif name.startswith("libwebp") and ".so" in name:
            kind = "webp_codec"
        elif name.startswith("libtiff") and ".so" in name:
            kind = "tiff_codec"
        else:
            continue
        major, minor = (int(part, 16) for part in fields[3].split(":"))
        identity = {"device": os.makedev(major, minor), "inode": int(fields[4])}
        if path in mapped_identities and mapped_identities[path] != identity:
            raise AssertionError("Loaded image library has inconsistent mapped identities: " + path)
        mapped_identities[path] = identity
        if path not in libraries[kind]:
            libraries[kind].append(path)
    frozen = bool(getattr(sys, "frozen", False))
    frozen_root = Path(sys._MEIPASS).resolve() if frozen else None
    evidence = _validate_loaded_libraries(libraries, frozen_root, mapped_identities=mapped_identities,
        require_codecs=platform.machine().lower() in ("aarch64", "arm64"))
    return {"source": "/proc/self/maps", "libraries": libraries,
            "library_files": evidence, "mapped_identities": mapped_identities,
            "frozen_root": str(frozen_root) if frozen else None,
            "verified_within_frozen_root": frozen}
