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

from install_pet import install_pet  # noqa: E402
from pet_package import PetPackageError, validate_pet_package  # noqa: E402
from prepare_pet_request import build_request  # noqa: E402
from restore_pet import resolve_backup  # noqa: E402


def _chunk(name: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + name
        + payload
        + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)
    )


def write_rgba_png(path: Path, width: int, height: int, value: int = 0) -> None:
    pixel = bytes([value, value, value, 255])
    row = b"\x00" + pixel * width
    payload = zlib.compress(row * height, level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", payload)
        + _chunk(b"IEND", b"")
    )


def write_vp8x_webp(path: Path, width: int, height: int) -> None:
    payload = b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (
        height - 1
    ).to_bytes(3, "little")
    chunk = b"VP8X" + struct.pack("<I", len(payload)) + payload
    riff_size = 4 + len(chunk)
    path.write_bytes(b"RIFF" + struct.pack("<I", riff_size) + b"WEBP" + chunk)


def write_vp8l_webp(
    path: Path, width: int, height: int, filler_size: int = 1024 * 1024
) -> None:
    dimensions = (width - 1) | ((height - 1) << 14)
    payload = b"\x2f" + struct.pack("<I", dimensions) + (b"\x00" * filler_size)
    padding = b"\x00" if len(payload) % 2 else b""
    chunk = b"VP8L" + struct.pack("<I", len(payload)) + payload + padding
    riff_size = 4 + len(chunk)
    path.write_bytes(b"RIFF" + struct.pack("<I", riff_size) + b"WEBP" + chunk)


def make_package(
    root: Path,
    *,
    display_name: str = "Basket Buddy",
    width: int = 1536,
    height: int = 2288,
    value: int = 0,
) -> Path:
    root.mkdir(parents=True)
    manifest = {
        "id": "basket-buddy",
        "displayName": display_name,
        "description": "A basketball-loving custom Codex pet.",
        "spriteVersionNumber": 2,
        "spritesheetPath": "spritesheet.png",
    }
    (root / "pet.json").write_text(json.dumps(manifest), encoding="utf-8")
    write_rgba_png(root / "spritesheet.png", width, height, value)
    return root


class PetPackageTests(unittest.TestCase):
    def test_valid_v2_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = make_package(Path(temporary) / "package")
            errors, package = validate_pet_package(package_dir)
            self.assertEqual(errors, [])
            self.assertIsNotNone(package)
            self.assertEqual((package.width, package.height), (1536, 2288))

    def test_wrong_atlas_dimensions_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = make_package(Path(temporary) / "package", height=1872)
            errors, package = validate_pet_package(package_dir)
            self.assertIsNone(package)
            self.assertTrue(any("1536x2288" in error for error in errors))

    def test_valid_vp8x_webp_dimensions_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = make_package(Path(temporary) / "package")
            (package_dir / "spritesheet.png").unlink()
            write_vp8x_webp(package_dir / "spritesheet.webp", 1536, 2288)
            manifest_path = package_dir / "pet.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["spritesheetPath"] = "spritesheet.webp"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            errors, package = validate_pet_package(package_dir)
            self.assertEqual(errors, [])
            self.assertIsNotNone(package)

    def test_large_vp8l_webp_dimensions_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = make_package(Path(temporary) / "package")
            (package_dir / "spritesheet.png").unlink()
            spritesheet = package_dir / "spritesheet.webp"
            write_vp8l_webp(spritesheet, 1536, 2288)
            self.assertGreater(spritesheet.stat().st_size, 1024 * 1024)
            manifest_path = package_dir / "pet.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["spritesheetPath"] = "spritesheet.webp"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors, package = validate_pet_package(package_dir)

            self.assertEqual(errors, [])
            self.assertIsNotNone(package)
            self.assertEqual((package.width, package.height), (1536, 2288))

    def test_truncated_large_webp_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = make_package(Path(temporary) / "package")
            (package_dir / "spritesheet.png").unlink()
            spritesheet = package_dir / "spritesheet.webp"
            write_vp8l_webp(spritesheet, 1536, 2288)
            spritesheet.write_bytes(spritesheet.read_bytes()[:-1])
            manifest_path = package_dir / "pet.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["spritesheetPath"] = "spritesheet.webp"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors, package = validate_pet_package(package_dir)

            self.assertIsNone(package)
            self.assertTrue(any("truncated WebP" in error for error in errors))

    def test_path_escape_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_dir = make_package(root / "package")
            manifest_path = package_dir / "pet.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["spritesheetPath"] = "../spritesheet.png"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            errors, package = validate_pet_package(package_dir)
            self.assertIsNone(package)
            self.assertTrue(any("inside the package" in error for error in errors))

    def test_unknown_manifest_field_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = make_package(Path(temporary) / "package")
            manifest_path = package_dir / "pet.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["unexpected"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            errors, package = validate_pet_package(package_dir)
            self.assertIsNone(package)
            self.assertTrue(any("unsupported fields" in error for error in errors))

    def test_install_replace_backup_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = make_package(root / "first", display_name="First", value=10)
            second = make_package(root / "second", display_name="Second", value=20)
            codex_home = root / "codex-home"

            result = install_pet(first, codex_home)
            destination = Path(result["destination"])
            self.assertEqual(
                json.loads((destination / "pet.json").read_text(encoding="utf-8"))[
                    "displayName"
                ],
                "First",
            )
            with self.assertRaises(PetPackageError):
                install_pet(second, codex_home)

            replacement = install_pet(second, codex_home, replace=True)
            backup = Path(replacement["backup"])
            self.assertTrue(backup.is_dir())
            self.assertEqual(
                json.loads((destination / "pet.json").read_text(encoding="utf-8"))[
                    "displayName"
                ],
                "Second",
            )

            resolved_backup = resolve_backup(Path(backup.name), codex_home.resolve())
            restored = install_pet(
                resolved_backup,
                codex_home,
                replace=True,
                backup_label="before-restore",
            )
            self.assertIsNotNone(restored["backup"])
            self.assertEqual(
                json.loads((destination / "pet.json").read_text(encoding="utf-8"))[
                    "displayName"
                ],
                "First",
            )

    def test_prepare_request_preserves_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "篮球小黄人.png"
            image.write_bytes(b"reference")
            request = build_request(
                Namespace(
                    image=image,
                    name="篮球小黄人",
                    id=None,
                    description=None,
                    style="auto",
                    idle_action="轻轻拍球",
                    working_action="一边工作一边拍篮球",
                    waiting_action="抱球等待确认",
                    ready_action="用篮球跳舞",
                    failed_action="抱着篮球失落地坐下",
                )
            )
            self.assertRegex(str(request["id"]), r"^chromapaw-[0-9a-f]{8}$")
            self.assertEqual(
                request["animationIntent"]["working"], "一边工作一边拍篮球"
            )
            self.assertEqual(request["animationIntent"]["ready"], "用篮球跳舞")


if __name__ == "__main__":
    unittest.main()
