from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_skin_package import validate_package


class SkinPackageValidationTests(unittest.TestCase):
    def make_package(self, root: Path) -> None:
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

    def test_valid_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_package(root)
            self.assertEqual(validate_package(root), [])

    def test_path_escape_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_package(root)
            manifest_path = root / "skin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["assets"]["background"] = "../outside.png"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(any("inside the package" in error for error in validate_package(root)))

    def test_invalid_color_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_package(root)
            manifest_path = root / "skin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["theme"]["accent"] = "coral"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(any("theme.accent" in error for error in validate_package(root)))


if __name__ == "__main__":
    unittest.main()
