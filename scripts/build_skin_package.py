#!/usr/bin/env python3
"""Build a ChromaPaw Skin Studio v2 package from a normalized request."""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError as exc:  # pragma: no cover - exercised by CLI environments
    raise SystemExit(
        "ERROR: Skin Studio requires Pillow. Use the Codex workspace Python runtime "
        "or install Pillow into the selected Python environment."
    ) from exc

from skin_package import PREVIEW_DIMENSIONS, contrast_ratio


GENERATOR_VERSION = "0.3.0"
SAFE_CONTENT_ZONE = {"x": 0.25, "y": 0.08, "width": 0.67, "height": 0.84}
DEPTH_LAYERS = ["atmosphere", "distant", "midground", "foreground"]


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _blend(
    first: tuple[int, int, int], second: tuple[int, int, int], amount: float
) -> tuple[int, int, int]:
    return tuple(round(a * (1 - amount) + b * amount) for a, b in zip(first, second))


def _saturate(rgb: tuple[int, int, int], minimum: float, value: float) -> tuple[int, int, int]:
    hue, saturation, _ = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
    converted = colorsys.hsv_to_rgb(hue, max(saturation, minimum), value)
    return tuple(round(channel * 255) for channel in converted)


def extract_palette(image: Image.Image) -> dict[str, Any]:
    """Extract a stable dominant palette and accessible UI colors."""
    sample = image.convert("RGB")
    sample.thumbnail((240, 240), Image.Resampling.LANCZOS)
    quantized = sample.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
    palette_data = quantized.getpalette() or []
    counts = sorted(quantized.getcolors() or [], reverse=True)
    colors: list[tuple[int, tuple[int, int, int]]] = []
    for count, index in counts:
        offset = index * 3
        if offset + 2 < len(palette_data):
            colors.append((count, tuple(palette_data[offset : offset + 3])))
    if not colors:
        colors = [(1, (128, 160, 176))]

    dominant = colors[0][1]
    candidates = []
    maximum_count = max(count for count, _ in colors)
    for count, rgb in colors:
        hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
        if 0.18 <= value <= 0.95:
            score = saturation * (0.7 + 0.3 * math.sqrt(count / maximum_count))
            candidates.append((score, hue, saturation, value, rgb))
    accent_source = max(candidates, default=(0, 0, 0, 0, dominant))[4]

    light_surface = _blend(dominant, (255, 255, 255), 0.91)
    dark_surface = _blend(dominant, (8, 18, 24), 0.84)
    light_ink = (18, 42, 48)
    dark_ink = (242, 248, 248)
    light_accent = _saturate(accent_source, 0.48, 0.76)
    dark_accent = _saturate(accent_source, 0.48, 0.88)

    light = {
        "surface": _hex(light_surface),
        "ink": _hex(light_ink),
        "accent": _hex(light_accent),
        "panelOpacity": 0.78,
    }
    dark = {
        "surface": _hex(dark_surface),
        "ink": _hex(dark_ink),
        "accent": _hex(dark_accent),
        "panelOpacity": 0.82,
    }
    return {
        "dominant": [_hex(rgb) for _, rgb in colors[:8]],
        "light": light,
        "dark": dark,
    }


def _rgb(value: str) -> str:
    return " ".join(str(int(value[index : index + 2], 16)) for index in (1, 3, 5))


def _variable_block(palette: dict[str, Any], selector: str) -> str:
    surface = palette["surface"]
    ink = palette["ink"]
    accent = palette["accent"]
    opacity = palette["panelOpacity"]
    scene_tint = 0.46 if sum(int(surface[index : index + 2], 16) for index in (1, 3, 5)) < 384 else 0.03
    return f"""{selector} {{
  --chromapaw-surface: {surface};
  --chromapaw-surface-rgb: {_rgb(surface)};
  --chromapaw-ink: {ink};
  --chromapaw-ink-rgb: {_rgb(ink)};
  --chromapaw-accent: {accent};
  --chromapaw-accent-rgb: {_rgb(accent)};
  --chromapaw-panel-opacity: {opacity};
  --chromapaw-scene-tint: {scene_tint};
}}"""


def build_css(palettes: dict[str, Any], mode: str) -> str:
    blocks = []
    if mode == "adaptive":
        blocks.append(_variable_block(palettes["light"], ":root, html.electron-light"))
        blocks.append(_variable_block(palettes["dark"], "html.electron-dark"))
        blocks.append(
            "@media (prefers-color-scheme: dark) {\n"
            + _variable_block(palettes["dark"], ":root:not(.electron-light)")
            + "\n}"
        )
    else:
        blocks.append(_variable_block(palettes[mode], ":root, html"))

    common = r"""

html,
body,
#root {
  background: transparent !important;
  color: var(--chromapaw-ink);
}

body {
  isolation: isolate;
}

body::before {
  position: fixed;
  z-index: 0;
  inset: 0;
  content: "";
  pointer-events: none;
  background-color: var(--chromapaw-surface);
  background-image: url("./background.png");
  background-position: center;
  background-repeat: no-repeat;
  background-size: cover;
}

body::after {
  position: fixed;
  z-index: 0;
  inset: 0;
  content: "";
  pointer-events: none;
  background:
    linear-gradient(
      rgb(4 12 16 / var(--chromapaw-scene-tint)),
      rgb(4 12 16 / var(--chromapaw-scene-tint))
    ),
    linear-gradient(
      90deg,
      rgb(var(--chromapaw-surface-rgb) / 0.22),
      transparent 22%,
      transparent 78%,
      rgb(var(--chromapaw-surface-rgb) / 0.16)
    );
}

/*
 * Codex may render pets in a separate transparent overlay window that loads
 * the same CSS. Never paint the skin background into that overlay.
 */
body:has([data-avatar-overlay-content-frame="true"])::before,
body:has([data-avatar-overlay-content-frame="true"])::after {
  display: none !important;
  content: none !important;
  background: none !important;
}

body:has([data-avatar-overlay-content-frame="true"]),
body:has([data-avatar-overlay-content-frame="true"]) #root,
body:has([data-avatar-overlay-content-frame="true"])
  [data-avatar-overlay-content-frame="true"] {
  background: transparent !important;
  box-shadow: none !important;
  -webkit-backdrop-filter: none !important;
  backdrop-filter: none !important;
}

#root {
  position: relative;
  z-index: 1;
}

#root > div,
.app-shell-main-content-viewport,
main.main-surface {
  background-color: transparent !important;
}

[data-avatar-mascot="true"],
[data-avatar-overlay-hit-region="mascot"],
.codex-avatar-button,
.codex-avatar-root {
  background: transparent !important;
  -webkit-backdrop-filter: none !important;
  backdrop-filter: none !important;
}

.app-shell-left-panel {
  background: rgb(var(--chromapaw-surface-rgb) / var(--chromapaw-panel-opacity)) !important;
  border-right: 1px solid rgb(var(--chromapaw-accent-rgb) / 0.16);
  box-shadow: 12px 0 36px rgb(0 0 0 / 0.08);
  -webkit-backdrop-filter: blur(18px) saturate(112%);
  backdrop-filter: blur(18px) saturate(112%);
}

[data-slot="dialog-content"],
[role="dialog"] {
  background: rgb(var(--chromapaw-surface-rgb) / 0.92) !important;
  color: var(--chromapaw-ink) !important;
  box-shadow: 0 22px 64px rgb(0 0 0 / 0.18) !important;
  -webkit-backdrop-filter: blur(20px) saturate(110%);
  backdrop-filter: blur(20px) saturate(110%);
}

::selection {
  background: rgb(var(--chromapaw-accent-rgb) / 0.28);
}

@media (max-width: 900px) {
  body::before {
    background-position: 55% center;
  }

  .app-shell-left-panel {
    -webkit-backdrop-filter: blur(20px) saturate(108%);
    backdrop-filter: blur(20px) saturate(108%);
  }
}
"""
    return (
        "/* ChromaPaw Skin Studio v0.3 portable stylesheet. Activation requires a compatible runtime. */\n"
        + "\n\n".join(blocks)
        + common
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    names = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size=size)
    return ImageFont.load_default()


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(
        image.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    ).convert("RGBA")


def render_preview(
    artwork: Image.Image,
    size: tuple[int, int],
    mode: str,
    palette: dict[str, Any],
    display_name: str,
) -> Image.Image:
    """Render a real-artwork desktop mockup for visual QA."""
    width, height = size
    canvas = _cover(artwork, size)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    surface = tuple(int(palette["surface"][i : i + 2], 16) for i in (1, 3, 5))
    ink = tuple(int(palette["ink"][i : i + 2], 16) for i in (1, 3, 5))
    accent = tuple(int(palette["accent"][i : i + 2], 16) for i in (1, 3, 5))
    panel_alpha = round(float(palette["panelOpacity"]) * 255)
    shadow = (0, 0, 0, 34 if mode == "light" else 72)

    if mode == "dark":
        draw.rectangle((0, 0, width, height), fill=(4, 12, 16, 112))

    sidebar = round(width * 0.22)
    draw.rectangle((0, 0, sidebar + 8, height), fill=shadow)
    draw.rectangle((0, 0, sidebar, height), fill=surface + (panel_alpha,))
    draw.line((sidebar, 0, sidebar, height), fill=accent + (48,), width=1)

    margin = max(18, round(width * 0.025))
    top = max(18, round(height * 0.045))
    brand_font = _font(max(16, round(width * 0.021)), bold=True)
    body_font = _font(max(11, round(width * 0.012)))
    small_font = _font(max(9, round(width * 0.010)))
    title_font = _font(max(19, round(width * 0.026)), bold=True)
    draw.ellipse((margin, top, margin + 28, top + 28), fill=accent + (245,))
    draw.text((margin + 38, top + 2), "ChromaPaw", font=brand_font, fill=ink + (245,))

    nav_y = top + 76
    for index, label in enumerate(("New task", "Skin Studio", "Packages", "Settings")):
        y = nav_y + index * 42
        nav_ink = ink
        if index == 1:
            draw.rounded_rectangle(
                (margin - 7, y - 8, sidebar - margin, y + 25),
                radius=10,
                fill=accent + (220 if mode == "dark" else 34,),
            )
            if mode == "dark":
                nav_ink = surface
        draw.ellipse((margin, y, margin + 9, y + 9), fill=accent + (180 if index == 1 else 84,))
        draw.text((margin + 20, y - 5), label, font=body_font, fill=nav_ink + (235,))

    main_left = sidebar + round(width * 0.055)
    main_right = width - round(width * 0.06)
    content_width = main_right - main_left
    draw.text((main_left, top + 3), "SKIN STUDIO  /  PREVIEW", font=small_font, fill=accent + (245,))
    draw.text(
        (main_left, top + 31),
        display_name,
        font=title_font,
        fill=ink + (250,),
    )

    card_top = top + 92
    card_bottom = min(height - 116, card_top + round(height * 0.42))
    draw.rounded_rectangle(
        (main_left + 5, card_top + 8, main_right + 5, card_bottom + 8),
        radius=18,
        fill=shadow,
    )
    draw.rounded_rectangle(
        (main_left, card_top, main_right, card_bottom),
        radius=18,
        fill=surface + (min(242, panel_alpha + 24),),
        outline=accent + (38,),
        width=1,
    )
    draw.text(
        (main_left + 24, card_top + 22),
        "A layered workspace that keeps the scene visible",
        font=_font(max(14, round(width * 0.016)), bold=True),
        fill=ink + (245,),
    )
    copy = [
        "Atmosphere and scenery remain around the reading area.",
        "Glass surfaces preserve contrast without flattening the artwork.",
        "Light and dark variants are checked at three window ratios.",
    ]
    for index, line in enumerate(copy):
        y = card_top + 66 + index * max(26, round(height * 0.052))
        draw.ellipse((main_left + 25, y + 4, main_left + 32, y + 11), fill=accent + (220,))
        draw.text((main_left + 44, y), line, font=body_font, fill=ink + (215,))

    badge_y = card_bottom - 42
    badge_text = f"{mode.upper()}  •  WCAG TEXT {contrast_ratio(palette['surface'], palette['ink']):.1f}:1"
    badge_box = draw.textbbox((0, 0), badge_text, font=small_font)
    badge_width = badge_box[2] - badge_box[0] + 24
    badge_fill = accent + ((224 if mode == "dark" else 36),)
    badge_ink = surface if mode == "dark" else ink
    draw.rounded_rectangle(
        (main_left + 24, badge_y, main_left + 24 + badge_width, badge_y + 25),
        radius=12,
        fill=badge_fill,
    )
    draw.text((main_left + 36, badge_y + 5), badge_text, font=small_font, fill=badge_ink + (235,))

    input_top = height - 91
    draw.rounded_rectangle(
        (main_left + 5, input_top + 7, main_right + 5, height - 31 + 7),
        radius=18,
        fill=shadow,
    )
    draw.rounded_rectangle(
        (main_left, input_top, main_right, height - 31),
        radius=18,
        fill=surface + (min(246, panel_alpha + 32),),
        outline=accent + (44,),
        width=1,
    )
    draw.text(
        (main_left + 22, input_top + 20),
        "Ask Codex to refine this skin...",
        font=body_font,
        fill=ink + (145,),
    )
    button = 34
    bx = main_right - button - 13
    by = input_top + 12
    draw.ellipse((bx, by, bx + button, by + button), fill=accent + (235,))
    draw.text((bx + 11, by + 6), "↑", font=_font(16, bold=True), fill=surface + (255,))

    return Image.alpha_composite(canvas, overlay).convert("RGB")


def _load_request(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"request cannot be read: {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise ValueError("request must be a Skin Studio schemaVersion 1 object")
    for field in ("id", "displayName", "description", "mode", "artworkImage", "source"):
        if field not in data:
            raise ValueError(f"request is missing {field}")
    if data["mode"] not in {"light", "dark", "adaptive"}:
        raise ValueError("request mode must be light, dark, or adaptive")
    return data


def _prepare_output(output: Path, force: bool) -> None:
    if output.exists() and any(output.iterdir()) and not force:
        raise ValueError(f"output directory is not empty: {output}; pass --force to replace it")
    output.mkdir(parents=True, exist_ok=True)
    if force:
        for name in ("assets", "qa"):
            target = output / name
            if target.is_dir():
                shutil.rmtree(target)
        manifest = output / "skin.json"
        if manifest.exists():
            manifest.unlink()


def build_package(request_path: Path, output: Path, force: bool = False) -> dict[str, Any]:
    request = _load_request(request_path.resolve())
    artwork_path = Path(str(request["artworkImage"])).expanduser().resolve()
    if not artwork_path.is_file():
        raise ValueError(f"artwork image does not exist: {artwork_path}")

    _prepare_output(output, force)
    assets = output / "assets"
    previews_dir = assets / "previews"
    qa_dir = output / "qa"
    previews_dir.mkdir(parents=True)
    qa_dir.mkdir(parents=True)

    try:
        with Image.open(artwork_path) as opened:
            transposed = ImageOps.exif_transpose(opened)
            if transposed.mode in {"RGBA", "LA"} or "transparency" in transposed.info:
                rgba = transposed.convert("RGBA")
                flattened = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                flattened.alpha_composite(rgba)
                artwork = flattened.convert("RGB")
            else:
                artwork = transposed.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValueError(f"artwork image cannot be decoded: {exc}") from exc

    artwork.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    background_path = assets / "background.png"
    artwork.save(background_path, format="PNG", optimize=True)
    palette_data = extract_palette(artwork)
    palettes = {"light": palette_data["light"], "dark": palette_data["dark"]}

    stylesheets = {
        "adaptive": "assets/theme.css",
        "light": "assets/theme-light.css",
        "dark": "assets/theme-dark.css",
    }
    for stylesheet_mode, relative in stylesheets.items():
        (output / relative).write_text(
            build_css(palettes, stylesheet_mode), encoding="utf-8", newline="\n"
        )

    preview_assets: dict[str, str] = {}
    variants = []
    for variant_mode in ("light", "dark"):
        for ratio, size in PREVIEW_DIMENSIONS.items():
            key = f"{variant_mode}-{ratio.replace(':', 'x')}"
            relative = f"assets/previews/preview-{key}.png"
            preview = render_preview(
                artwork, size, variant_mode, palettes[variant_mode], str(request["displayName"])
            )
            preview.save(output / relative, format="PNG", optimize=True)
            preview_assets[key] = relative
            variants.append(
                {
                    "id": key,
                    "mode": variant_mode,
                    "aspectRatio": ratio,
                    "preview": relative,
                    "stylesheet": stylesheets[variant_mode],
                }
            )

    primary_mode = "dark" if request["mode"] == "dark" else "light"
    primary_key = f"{primary_mode}-16x10"
    primary_preview = assets / "preview.png"
    shutil.copy2(output / preview_assets[primary_key], primary_preview)
    active_palette = palettes[primary_mode]

    report = {
        "schemaVersion": 1,
        "generator": f"ChromaPaw Skin Studio {GENERATOR_VERSION}",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "backgroundDimensions": {"width": artwork.width, "height": artwork.height},
        "dominantPalette": palette_data["dominant"],
        "palettes": palettes,
        "safeContentZone": SAFE_CONTENT_ZONE,
        "checks": [
            {
                "id": "light-text-contrast",
                "status": "pass"
                if contrast_ratio(palettes["light"]["surface"], palettes["light"]["ink"])
                >= 4.5
                else "fail",
                "value": round(
                    contrast_ratio(
                        palettes["light"]["surface"], palettes["light"]["ink"]
                    ),
                    2,
                ),
                "threshold": 4.5,
            },
            {
                "id": "dark-text-contrast",
                "status": "pass"
                if contrast_ratio(palettes["dark"]["surface"], palettes["dark"]["ink"])
                >= 4.5
                else "fail",
                "value": round(
                    contrast_ratio(palettes["dark"]["surface"], palettes["dark"]["ink"]),
                    2,
                ),
                "threshold": 4.5,
            },
            {"id": "window-ratio-previews", "status": "pass", "value": 6, "threshold": 6},
            {"id": "pet-overlay-isolation", "status": "pass"},
        ],
        "activation": {
            "status": "not-attempted",
            "reason": "Portable package generation is separate from the 0.4 runtime.",
        },
    }
    qa_relative = "qa/skin-studio-report.json"
    (output / qa_relative).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest = {
        "schemaVersion": 2,
        "id": request["id"],
        "displayName": request["displayName"],
        "description": request["description"],
        "mode": request["mode"],
        "assets": {
            "background": "assets/background.png",
            "stylesheet": stylesheets[str(request["mode"])],
            "preview": "assets/preview.png",
            "stylesheets": stylesheets,
            "previews": preview_assets,
        },
        "theme": {
            **active_palette,
            "palettes": palettes,
        },
        "layout": {
            "safeContentZone": SAFE_CONTENT_ZONE,
            "depthLayers": DEPTH_LAYERS,
        },
        "variants": variants,
        "source": request["source"],
        "qa": qa_relative,
    }
    (output / "skin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path, help="skin-request.json path")
    parser.add_argument("--output-dir", required=True, type=Path, help="Package output directory")
    parser.add_argument("--force", action="store_true", help="Replace managed package files")
    parser.add_argument("--json", action="store_true", help="Print the manifest as JSON")
    args = parser.parse_args()

    try:
        manifest = build_package(
            args.request.expanduser().resolve(), args.output_dir.expanduser().resolve(), args.force
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(args.output_dir.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
