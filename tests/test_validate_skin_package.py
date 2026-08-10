from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import zlib
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_skin_package import build_package  # noqa: E402
from prepare_skin_request import build_request  # noqa: E402
from validate_skin_package import validate_package  # noqa: E402


def _chunk(name: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + name
        + payload
        + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)
    )


def write_rgba_png(path: Path, width: int, height: int) -> None:
    rows = []
    for y in range(height):
        row = bytearray(b"\x00")
        for x in range(width):
            row.extend((70 + x * 2 % 150, 150 + y * 2 % 90, 190, 255))
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(b"".join(rows), level=9))
        + _chunk(b"IEND", b"")
    )


def make_v1_package(root: Path) -> None:
    (root / "assets").mkdir()
    (root / "assets" / "background.png").write_bytes(b"png")
    (root / "assets" / "theme.css").write_text("body {}", encoding="utf-8")
    (root / "assets" / "preview.png").write_bytes(b"png")
    manifest = {
        "schemaVersion": 1,
        "id": "summer-beach",
        "displayName": "Summer Beach",
        "mode": "light",
        "assets": {
            "background": "assets/background.png",
            "stylesheet": "assets/theme.css",
            "preview": "assets/preview.png",
        },
        "theme": {
            "surface": "#F7FCF9",
            "ink": "#173F46",
            "accent": "#FF7F66",
            "panelOpacity": 0.82,
        },
    }
    (root / "skin.json").write_text(json.dumps(manifest), encoding="utf-8")


def make_v2_package(root: Path) -> Path:
    image = root / "beach.png"
    write_rgba_png(image, 96, 64)
    request = build_request(
        Namespace(
            image=image,
            artwork=None,
            name="Fresh Beach",
            id="fresh-beach",
            description="A fresh layered beach workspace.",
            mode="adaptive",
            scene_brief=None,
            author="Test artist",
            license="CC0-1.0",
            source_url=None,
        )
    )
    request_path = root / "skin-request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    package = root / "package"
    build_package(request_path, package)
    return package


class SkinPackageValidationTests(unittest.TestCase):
    def test_legacy_v1_package_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_v1_package(root)
            self.assertEqual(validate_package(root), [])

    def test_legacy_v1_does_not_gain_v2_contrast_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_v1_package(root)
            manifest_path = root / "skin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["theme"]["surface"] = "#FFFFFF"
            manifest["theme"]["ink"] = "#EEEEEE"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(validate_package(root), [])

    def test_skin_studio_v2_builder_and_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = make_v2_package(Path(directory))
            self.assertEqual(validate_package(package), [])
            manifest = json.loads((package / "skin.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schemaVersion"], 2)
            self.assertEqual(len(manifest["variants"]), 6)
            self.assertEqual(len(manifest["assets"]["previews"]), 6)
            css = (package / "assets" / "theme.css").read_text(encoding="utf-8")
            self.assertIn('data-avatar-overlay-content-frame="true"', css)
            self.assertIn('background-image: url("./background.png")', css)

    def test_path_escape_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_v1_package(root)
            manifest_path = root / "skin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["assets"]["background"] = "../outside.png"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(any("inside the package" in error for error in validate_package(root)))

    def test_invalid_color_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_v1_package(root)
            manifest_path = root / "skin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["theme"]["accent"] = "coral"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(any("theme.accent" in error for error in validate_package(root)))

    def test_v2_safe_zone_must_remain_inside_canvas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = make_v2_package(Path(directory))
            manifest_path = package / "skin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["layout"]["safeContentZone"]["x"] = 0.8
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(any("remain inside" in error for error in validate_package(package)))

    def test_v2_requires_all_mode_ratio_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = make_v2_package(Path(directory))
            manifest_path = package / "skin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["variants"] = manifest["variants"][:-1]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(any("missing required combinations" in error for error in validate_package(package)))

    def test_v2_rejects_wrong_preview_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = make_v2_package(Path(directory))
            write_rgba_png(package / "assets" / "previews" / "preview-light-16x10.png", 320, 200)
            self.assertTrue(any("960x600" in error for error in validate_package(package)))

    def test_v2_rejects_failed_qa_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = make_v2_package(Path(directory))
            report_path = package / "qa" / "skin-studio-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["checks"][0]["status"] = "fail"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            self.assertTrue(any("did not pass" in error for error in validate_package(package)))


if __name__ == "__main__":
    unittest.main()
