from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_skin_package import _cover, extract_palette, semantic_ui_palette  # noqa: E402
from skin_package import contrast_ratio  # noqa: E402


class SkinInputMatrixTests(unittest.TestCase):
    def test_common_shapes_modes_and_brightness_keep_preview_and_text_safe(self) -> None:
        cases = (
            ("landscape", "RGB", (160, 90), (55, 145, 220, 255)),
            ("portrait", "RGB", (90, 160), (235, 175, 80, 255)),
            ("ultrawide", "RGB", (240, 60), (65, 90, 130, 255)),
            ("dark", "RGB", (120, 80), (5, 12, 24, 255)),
            ("light", "RGB", (120, 80), (245, 248, 250, 255)),
            ("transparent", "RGBA", (96, 128), (40, 180, 160, 0)),
        )
        for name, mode, size, color in cases:
            with self.subTest(name=name):
                image = Image.new(mode, size, color[:3] if mode == "RGB" else color)
                if mode == "RGBA":
                    draw = ImageDraw.Draw(image)
                    draw.ellipse((12, 20, 84, 108), fill=(40, 180, 160, 255))
                covered = _cover(image, (960, 600))
                self.assertEqual(covered.size, (960, 600))
                self.assertEqual(covered.mode, "RGBA")
                palettes = extract_palette(image)
                for theme_mode in ("light", "dark"):
                    ui = semantic_ui_palette(palettes[theme_mode], theme_mode)
                    for role, surface_role in (
                        ("primaryText", "surface"),
                        ("secondaryText", "surface"),
                        ("mutedText", "surface"),
                        ("accentText", "surface"),
                        ("notificationText", "notificationSurface"),
                        ("notificationSecondaryText", "notificationSurface"),
                        ("notificationControlText", "notificationControlSurface"),
                        ("sidePanelText", "sidePanelSurface"),
                        ("sidePanelSecondaryText", "sidePanelSurface"),
                        ("sidePanelSectionText", "sidePanelSectionSurface"),
                        ("titleBarText", "titleBarSurface"),
                        ("titleBarSecondaryText", "titleBarSurface"),
                    ):
                        self.assertGreaterEqual(
                            contrast_ratio(ui[surface_role], ui[role]),
                            4.5,
                            f"{name} {theme_mode} {role}",
                        )


if __name__ == "__main__":
    unittest.main()
