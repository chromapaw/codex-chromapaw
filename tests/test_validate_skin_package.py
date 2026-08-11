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

from build_skin_package import build_package, semantic_ui_palette  # noqa: E402
from prepare_skin_request import build_request  # noqa: E402
from prepare_theme_profile import build_profile as build_theme_profile  # noqa: E402
from skin_package import contrast_ratio  # noqa: E402
from theme_profile import ThemeProfileError, normalize_theme_profile  # noqa: E402
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


def make_theme_profile(root: Path, image: Path, kind: str = "sky") -> tuple[dict, Path]:
    cases = {
        "sky": {
            "theme_name": "Open Blue Sky",
            "visual_style": "soft dimensional illustration",
            "mood": "fresh, airy, and optimistic",
            "identity_cue": ["clear blue gradient", "rounded white cloud shapes"],
            "motif": ["blue sky", "white clouds", "soft sunlight"],
            "avoid_element": ["ocean", "sand", "coral"],
            "atmosphere": "A luminous blue sky with gentle high-altitude haze.",
            "distant": "Small layered cloud banks and a faint bright horizon.",
            "midground": "Large soft clouds framing the quiet reading surface.",
            "foreground": "A few restrained cloud wisps at the outer corners.",
        },
        "comic": {
            "theme_name": "Graphic Comic Panels",
            "visual_style": "bold cel-shaded comic illustration",
            "mood": "energetic, playful, and crisp",
            "identity_cue": ["heavy ink outlines", "limited saturated colors"],
            "motif": ["halftone dots", "panel borders", "speed lines"],
            "avoid_element": ["photorealism", "ocean waves", "coral"],
            "atmosphere": "A flat graphic color field with subtle halftone texture.",
            "distant": "Oversized abstract comic panels behind the content area.",
            "midground": "Bold panel borders and readable cel-shaded shapes.",
            "foreground": "Restrained speed lines and ink accents near outer edges.",
        },
    }
    case = cases[kind]
    profile = build_theme_profile(
        Namespace(
            image=image,
            source_kind="full-environment",
            safe_zone_guidance="Keep the center and bottom input region calm and low detail.",
            **case,
        )
    )
    path = root / f"theme-profile-{kind}.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return profile, path


def make_v2_package(root: Path) -> Path:
    image = root / "sky.png"
    write_rgba_png(image, 96, 64)
    _, profile_path = make_theme_profile(root, image)
    request = build_request(
        Namespace(
            image=image,
            artwork=None,
            theme_profile=profile_path,
            name="Open Blue Sky",
            id="open-blue-sky",
            description="A fresh layered blue-sky workspace.",
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
            self.assertEqual(manifest["semanticProfile"]["themeName"], "Open Blue Sky")
            self.assertIn("white clouds", manifest["semanticProfile"]["motifs"])
            css = (package / "assets" / "theme.css").read_text(encoding="utf-8")
            self.assertIn('data-avatar-overlay-content-frame="true"', css)
            self.assertIn('background-image: url("./background.png")', css)
            self.assertIn(
                "--color-token-text-primary: var(--chromapaw-ink) !important",
                css,
            )
            self.assertIn(
                "--vscode-titleBar-activeForeground: var(--chromapaw-ink) !important",
                css,
            )
            self.assertIn(
                "--color-token-input-background: rgb(var(--chromapaw-surface-input-rgb)",
                css,
            )
            report = json.loads(
                (package / "qa" / "skin-studio-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(set(report["uiPalettes"]), {"light", "dark"})
            self.assertTrue(
                all(
                    check["status"] == "pass"
                    for check in report["checks"]
                    if "-ui-" in check["id"]
                )
            )

    def test_semantic_ui_palette_keeps_muted_and_accent_text_accessible(self) -> None:
        for mode, palette in (
            (
                "dark",
                {
                    "surface": "#081523",
                    "ink": "#F2F8F8",
                    "accent": "#0A49E0",
                    "panelOpacity": 0.82,
                },
            ),
            (
                "light",
                {
                    "surface": "#E9EBF0",
                    "ink": "#122A30",
                    "accent": "#093FC2",
                    "panelOpacity": 0.78,
                },
            ),
        ):
            ui = semantic_ui_palette(palette, mode)
            for role in ("primaryText", "secondaryText", "mutedText", "accentText"):
                self.assertGreaterEqual(
                    contrast_ratio(ui["surface"], ui[role]),
                    4.5,
                    f"{mode} {role}",
                )

    def test_non_beach_theme_profiles_remain_semantically_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind, expected, forbidden in (
                ("sky", "white clouds", "coral"),
                ("comic", "halftone dots", "ocean waves"),
            ):
                case_root = root / kind
                case_root.mkdir()
                image = case_root / f"{kind}.png"
                write_rgba_png(image, 96, 64)
                profile, profile_path = make_theme_profile(case_root, image, kind)
                request = build_request(
                    Namespace(
                        image=image,
                        artwork=None,
                        theme_profile=profile_path,
                        name=profile["themeName"],
                        id=None,
                        description=None,
                        mode="adaptive",
                        scene_brief=None,
                        author="Test artist",
                        license="CC0-1.0",
                        source_url=None,
                    )
                )
                request_path = case_root / "skin-request.json"
                request_path.write_text(json.dumps(request), encoding="utf-8")
                package = case_root / "package"
                build_package(request_path, package)
                manifest = json.loads((package / "skin.json").read_text(encoding="utf-8"))
                semantic = manifest["semanticProfile"]
                self.assertIn(expected, semantic["motifs"])
                self.assertNotIn(forbidden, semantic["motifs"])
                self.assertEqual(validate_package(package), [])

    def test_theme_profile_rejects_motif_avoid_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "sky.png"
            write_rgba_png(image, 32, 32)
            profile, _ = make_theme_profile(root, image)
            profile["avoidElements"].append("white clouds")
            with self.assertRaises(ThemeProfileError):
                normalize_theme_profile(profile)

    def test_skin_request_rejects_profile_for_different_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.png"
            second = root / "second.png"
            write_rgba_png(first, 32, 32)
            write_rgba_png(second, 33, 32)
            _, profile_path = make_theme_profile(root, first)
            with self.assertRaises(ValueError) as context:
                build_request(
                    Namespace(
                        image=second,
                        artwork=None,
                        theme_profile=profile_path,
                        name=None,
                        id=None,
                        description=None,
                        mode="adaptive",
                        scene_brief=None,
                        author="Test artist",
                        license="CC0-1.0",
                        source_url=None,
                    )
                )
            self.assertIn("does not match", str(context.exception))

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
