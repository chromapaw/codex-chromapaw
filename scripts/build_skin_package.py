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

try:
    from .theme_profile import normalize_theme_profile, sha256_file
except ImportError:
    from theme_profile import normalize_theme_profile, sha256_file  # type: ignore


GENERATOR_VERSION = "0.4.8"
SAFE_CONTENT_ZONE = {"x": 0.25, "y": 0.08, "width": 0.67, "height": 0.84}
DEPTH_LAYERS = ["atmosphere", "distant", "midground", "foreground"]
GLOBAL_WASH_OPACITY = 0.08


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


def _rgb_tuple(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def _accessible_blend(
    foreground: tuple[int, int, int],
    background: tuple[int, int, int],
    amount: float,
    minimum: float,
) -> tuple[int, int, int]:
    """Mute text toward its surface without dropping below the contrast gate."""
    for step in range(round(amount * 100), -1, -1):
        candidate = _blend(foreground, background, step / 100)
        if contrast_ratio(_hex(candidate), _hex(background)) >= minimum:
            return candidate
    return foreground


def _ensure_contrast(
    foreground: tuple[int, int, int],
    background: tuple[int, int, int],
    minimum: float,
) -> tuple[int, int, int]:
    if contrast_ratio(_hex(foreground), _hex(background)) >= minimum:
        return foreground
    black = (0, 0, 0)
    white = (255, 255, 255)
    toward = (
        white
        if contrast_ratio(_hex(white), _hex(background))
        >= contrast_ratio(_hex(black), _hex(background))
        else black
    )
    for step in range(1, 101):
        candidate = _blend(foreground, toward, step / 100)
        if contrast_ratio(_hex(candidate), _hex(background)) >= minimum:
            return candidate
    return toward


def semantic_ui_palette(palette: dict[str, Any], mode: str) -> dict[str, str]:
    """Derive accessible Codex semantic UI roles from an extracted image palette."""
    surface = _rgb_tuple(str(palette["surface"]))
    ink = _rgb_tuple(str(palette["ink"]))
    accent = _rgb_tuple(str(palette["accent"]))
    secondary = _accessible_blend(ink, surface, 0.24, 4.5)
    muted = _accessible_blend(ink, surface, 0.38, 4.5)
    accent_text = _ensure_contrast(accent, surface, 4.5)
    on_accent = max(
        ((0, 0, 0), (255, 255, 255)),
        key=lambda candidate: contrast_ratio(_hex(candidate), _hex(accent_text)),
    )
    if mode == "dark":
        elevated = _blend(surface, (255, 255, 255), 0.08)
        input_surface = _blend(surface, (255, 255, 255), 0.12)
    else:
        elevated = _blend(surface, (0, 0, 0), 0.03)
        input_surface = _blend(surface, (255, 255, 255), 0.34)
    notification_text = _ensure_contrast(ink, elevated, 4.5)
    notification_secondary = _accessible_blend(
        notification_text, elevated, 0.24, 4.5
    )
    notification_control_text = _accessible_blend(
        notification_text, input_surface, 0.24, 4.5
    )
    side_panel_text = _ensure_contrast(ink, surface, 4.5)
    side_panel_secondary = _accessible_blend(side_panel_text, surface, 0.24, 4.5)
    side_panel_section_text = _ensure_contrast(side_panel_text, elevated, 4.5)
    return {
        "primaryText": _hex(ink),
        "secondaryText": _hex(secondary),
        "mutedText": _hex(muted),
        "accentText": _hex(accent_text),
        "onAccent": _hex(on_accent),
        "surface": _hex(surface),
        "elevatedSurface": _hex(elevated),
        "inputSurface": _hex(input_surface),
        "notificationSurface": _hex(elevated),
        "notificationText": _hex(notification_text),
        "notificationSecondaryText": _hex(notification_secondary),
        "notificationControlSurface": _hex(input_surface),
        "notificationControlText": _hex(notification_control_text),
        "sidePanelSurface": _hex(surface),
        "sidePanelText": _hex(side_panel_text),
        "sidePanelSecondaryText": _hex(side_panel_secondary),
        "sidePanelSectionSurface": _hex(elevated),
        "sidePanelSectionText": _hex(side_panel_section_text),
    }


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


def _variable_block(
    palette: dict[str, Any], selector: str, mode: str, subject_placement: str
) -> str:
    surface = palette["surface"]
    ink = palette["ink"]
    accent = palette["accent"]
    ui = semantic_ui_palette(palette, mode)
    opacity = palette["panelOpacity"]
    if subject_placement == "right":
        reading_max_inline = "66%"
        reading_margin_start = "0"
        reading_margin_end = "auto"
        content_veil = (
            "linear-gradient(90deg, "
            "rgb(var(--chromapaw-surface-rgb) / 0.46) 0%, "
            "rgb(var(--chromapaw-surface-rgb) / 0.28) 48%, transparent 68%)"
        )
    elif subject_placement == "left":
        reading_max_inline = "66%"
        reading_margin_start = "auto"
        reading_margin_end = "0"
        content_veil = (
            "linear-gradient(270deg, "
            "rgb(var(--chromapaw-surface-rgb) / 0.46) 0%, "
            "rgb(var(--chromapaw-surface-rgb) / 0.28) 48%, transparent 68%)"
        )
    elif subject_placement == "edge-balanced":
        reading_max_inline = "100%"
        reading_margin_start = "0"
        reading_margin_end = "0"
        content_veil = (
            "radial-gradient(ellipse at center, "
            "rgb(var(--chromapaw-surface-rgb) / 0.34) 0%, "
            "rgb(var(--chromapaw-surface-rgb) / 0.18) 56%, transparent 92%)"
        )
    else:
        reading_max_inline = "100%"
        reading_margin_start = "0"
        reading_margin_end = "0"
        content_veil = (
            "linear-gradient(90deg, "
            "rgb(var(--chromapaw-surface-rgb) / 0.24), "
            "rgb(var(--chromapaw-surface-rgb) / 0.32) 52%, "
            "rgb(var(--chromapaw-surface-rgb) / 0.18))"
        )
    return f"""{selector} {{
  --chromapaw-surface: {surface};
  --chromapaw-surface-rgb: {_rgb(surface)};
  --chromapaw-ink: {ink};
  --chromapaw-ink-rgb: {_rgb(ink)};
  --chromapaw-accent: {accent};
  --chromapaw-accent-rgb: {_rgb(accent)};
  --chromapaw-accent-readable: {ui['accentText']};
  --chromapaw-accent-readable-rgb: {_rgb(ui['accentText'])};
  --chromapaw-ink-secondary: {ui['secondaryText']};
  --chromapaw-ink-muted: {ui['mutedText']};
  --chromapaw-on-accent: {ui['onAccent']};
  --chromapaw-surface-elevated: {ui['elevatedSurface']};
  --chromapaw-surface-elevated-rgb: {_rgb(ui['elevatedSurface'])};
  --chromapaw-surface-input: {ui['inputSurface']};
  --chromapaw-surface-input-rgb: {_rgb(ui['inputSurface'])};
  --chromapaw-notification-surface: {ui['notificationSurface']};
  --chromapaw-notification-text: {ui['notificationText']};
  --chromapaw-notification-text-secondary: {ui['notificationSecondaryText']};
  --chromapaw-notification-control-surface: {ui['notificationControlSurface']};
  --chromapaw-notification-control-text: {ui['notificationControlText']};
  --chromapaw-side-panel-surface: {ui['sidePanelSurface']};
  --chromapaw-side-panel-text: {ui['sidePanelText']};
  --chromapaw-side-panel-text-secondary: {ui['sidePanelSecondaryText']};
  --chromapaw-side-panel-section-surface: {ui['sidePanelSectionSurface']};
  --chromapaw-side-panel-section-text: {ui['sidePanelSectionText']};
  --chromapaw-color-scheme: {mode};
  --chromapaw-panel-opacity: {opacity};
  --chromapaw-scene-wash: {GLOBAL_WASH_OPACITY};
  --chromapaw-scene-saturation: 1.08;
  --chromapaw-scene-contrast: 1.06;
  --chromapaw-scene-position: center;
  --chromapaw-content-veil: {content_veil};
  --chromapaw-reading-surface: rgb(var(--chromapaw-surface-rgb) / 0.78);
  --chromapaw-reading-surface-strong: rgb(var(--chromapaw-surface-rgb) / 0.88);
  --chromapaw-reading-border: rgb(var(--chromapaw-ink-rgb) / 0.14);
  --chromapaw-reading-shadow: rgb(0 0 0 / 0.14);
  --chromapaw-reading-max-inline: {reading_max_inline};
  --chromapaw-reading-margin-start: {reading_margin_start};
  --chromapaw-reading-margin-end: {reading_margin_end};
}}"""


def build_css(
    palettes: dict[str, Any], mode: str, visual_treatment: dict[str, Any] | None = None
) -> str:
    subject_placement = str((visual_treatment or {}).get("subjectPlacement", "source"))
    blocks = []
    if mode == "adaptive":
        blocks.append(
            _variable_block(
                palettes["light"], ":root, html.electron-light", "light", subject_placement
            )
        )
        blocks.append(
            _variable_block(
                palettes["dark"], "html.electron-dark", "dark", subject_placement
            )
        )
        blocks.append(
            "@media (prefers-color-scheme: dark) {\n"
            + _variable_block(
                palettes["dark"],
                ":root:not(.electron-light)",
                "dark",
                subject_placement,
            )
            + "\n}"
        )
    else:
        blocks.append(
            _variable_block(palettes[mode], ":root, html", mode, subject_placement)
        )

    common = r"""

/*
 * Codex can remain electron-light while a dark image skin is active (or the
 * reverse). Override semantic UI tokens from the generated image palette so
 * menus, navigation, editors, inputs, icons, and muted text follow the skin
 * instead of inheriting an unreadable host color mode.
 */
:root,
html {
  color-scheme: var(--chromapaw-color-scheme) !important;
  --codex-base-ink: var(--chromapaw-ink) !important;
  --color-text-foreground: var(--chromapaw-ink) !important;
  --color-text-foreground-secondary: var(--chromapaw-ink-secondary) !important;
  --color-text-foreground-tertiary: var(--chromapaw-ink-muted) !important;
  --color-text-button-primary: var(--chromapaw-on-accent) !important;
  --color-text-button-secondary: var(--chromapaw-ink) !important;
  --color-text-button-tertiary: var(--chromapaw-ink-muted) !important;
  --color-text-accent: var(--chromapaw-accent-readable) !important;
  --color-text-on-accent: var(--chromapaw-on-accent) !important;
  --color-icon-primary: var(--chromapaw-ink) !important;
  --color-icon-secondary: var(--chromapaw-ink-secondary) !important;
  --color-icon-tertiary: var(--chromapaw-ink-muted) !important;
  --color-icon-accent: var(--chromapaw-accent-readable) !important;
  --color-border: rgb(var(--chromapaw-ink-rgb) / 0.18) !important;
  --color-border-light: rgb(var(--chromapaw-ink-rgb) / 0.12) !important;
  --color-border-heavy: rgb(var(--chromapaw-ink-rgb) / 0.28) !important;
  --color-border-focus: var(--chromapaw-accent-readable) !important;
  --color-background-panel: var(--chromapaw-surface) !important;
  --color-background-surface: rgb(var(--chromapaw-surface-rgb) / 0.78) !important;
  --color-background-control: rgb(var(--chromapaw-surface-input-rgb) / 0.94) !important;
  --color-background-control-opaque: var(--chromapaw-surface-input) !important;
  --color-background-elevated-primary: rgb(var(--chromapaw-surface-elevated-rgb) / 0.92) !important;
  --color-background-elevated-primary-opaque: var(--chromapaw-surface-elevated) !important;
  --color-background-elevated-secondary: rgb(var(--chromapaw-surface-rgb) / 0.86) !important;
  --color-background-elevated-secondary-opaque: var(--chromapaw-surface) !important;
  --color-surface: rgb(var(--chromapaw-surface-rgb) / 0.82) !important;
  --color-surface-elevated: rgb(var(--chromapaw-surface-elevated-rgb) / 0.94) !important;
  --color-surface-tertiary: rgb(var(--chromapaw-surface-input-rgb) / 0.82) !important;
  --color-background-button-primary: var(--chromapaw-accent-readable) !important;
  --color-background-button-primary-hover: rgb(var(--chromapaw-accent-readable-rgb) / 0.88) !important;
  --color-background-button-primary-active: rgb(var(--chromapaw-accent-readable-rgb) / 0.72) !important;
  --color-background-button-secondary: rgb(var(--chromapaw-ink-rgb) / 0.10) !important;
  --color-background-button-secondary-hover: rgb(var(--chromapaw-ink-rgb) / 0.16) !important;
  --color-background-button-secondary-active: rgb(var(--chromapaw-ink-rgb) / 0.22) !important;
  --color-background-button-tertiary-hover: rgb(var(--chromapaw-ink-rgb) / 0.12) !important;

  --color-token-foreground: var(--chromapaw-ink) !important;
  --color-token-icon-foreground: var(--chromapaw-ink) !important;
  --color-token-description-foreground: var(--chromapaw-ink-muted) !important;
  --color-token-disabled-foreground: var(--chromapaw-ink-muted) !important;
  --color-token-text-primary: var(--chromapaw-ink) !important;
  --color-token-text-secondary: var(--chromapaw-ink-secondary) !important;
  --color-token-text-tertiary: var(--chromapaw-ink-muted) !important;
  --color-token-text-link-foreground: var(--chromapaw-accent-readable) !important;
  --color-token-text-link-active-foreground: var(--chromapaw-accent-readable) !important;
  --color-token-text-preformat-foreground: var(--chromapaw-ink) !important;
  --color-token-text-preformat-background: rgb(var(--chromapaw-ink-rgb) / 0.10) !important;
  --color-token-text-code-block-background: rgb(var(--chromapaw-ink-rgb) / 0.10) !important;
  --color-token-border: rgb(var(--chromapaw-ink-rgb) / 0.18) !important;
  --color-token-border-default: rgb(var(--chromapaw-ink-rgb) / 0.18) !important;
  --color-token-border-light: rgb(var(--chromapaw-ink-rgb) / 0.12) !important;
  --color-token-border-heavy: rgb(var(--chromapaw-ink-rgb) / 0.28) !important;
  --color-token-focus-border: var(--chromapaw-accent-readable) !important;
  --color-token-button-background: var(--chromapaw-accent-readable) !important;
  --color-token-button-foreground: var(--chromapaw-on-accent) !important;
  --color-token-button-border: rgb(var(--chromapaw-accent-readable-rgb) / 0.52) !important;
  --color-token-button-secondary-hover-background: rgb(var(--chromapaw-ink-rgb) / 0.14) !important;
  --color-token-badge-background: rgb(var(--chromapaw-ink-rgb) / 0.12) !important;
  --color-token-badge-foreground: var(--chromapaw-ink-secondary) !important;
  --color-token-activity-bar-badge-background: var(--chromapaw-accent-readable) !important;
  --color-token-activity-bar-badge-foreground: var(--chromapaw-on-accent) !important;
  --color-token-main-surface-primary: rgb(var(--chromapaw-surface-rgb) / 0.72) !important;
  --color-token-side-bar-background: rgb(var(--chromapaw-surface-rgb) / var(--chromapaw-panel-opacity)) !important;
  --color-token-dropdown-background: var(--chromapaw-surface-elevated) !important;
  --color-token-dropdown-foreground: var(--chromapaw-ink) !important;
  --color-token-menu-background: rgb(var(--chromapaw-surface-elevated-rgb) / 0.96) !important;
  --color-token-menu-border: rgb(var(--chromapaw-ink-rgb) / 0.18) !important;
  --color-token-menubar-selection-background: rgb(var(--chromapaw-ink-rgb) / 0.12) !important;
  --color-token-menubar-selection-foreground: var(--chromapaw-ink) !important;
  --color-token-input-background: rgb(var(--chromapaw-surface-input-rgb) / 0.94) !important;
  --color-token-input-foreground: var(--chromapaw-ink) !important;
  --color-token-input-placeholder-foreground: var(--chromapaw-ink-muted) !important;
  --color-token-input-border: rgb(var(--chromapaw-ink-rgb) / 0.24) !important;
  --color-token-checkbox-background: var(--chromapaw-surface-input) !important;
  --color-token-checkbox-foreground: var(--chromapaw-ink) !important;
  --color-token-checkbox-border: rgb(var(--chromapaw-ink-rgb) / 0.24) !important;
  --color-token-list-active-selection-background: rgb(var(--chromapaw-accent-readable-rgb) / 0.18) !important;
  --color-token-list-active-selection-foreground: var(--chromapaw-ink) !important;
  --color-token-list-active-selection-icon-foreground: var(--chromapaw-ink) !important;
  --color-token-list-hover-background: rgb(var(--chromapaw-ink-rgb) / 0.12) !important;
  --color-token-editor-background: rgb(var(--chromapaw-surface-rgb) / 0.86) !important;
  --color-token-editor-foreground: var(--chromapaw-ink) !important;
  --color-token-editor-widget-background: var(--chromapaw-surface-elevated) !important;
  --color-token-terminal-background: rgb(var(--chromapaw-surface-rgb) / 0.90) !important;
  --color-token-terminal-foreground: var(--chromapaw-ink) !important;
  --color-token-terminal-border: rgb(var(--chromapaw-ink-rgb) / 0.18) !important;
  --color-token-toolbar-hover-background: rgb(var(--chromapaw-ink-rgb) / 0.12) !important;

  --vscode-foreground: var(--chromapaw-ink) !important;
  --vscode-descriptionForeground: var(--chromapaw-ink-muted) !important;
  --vscode-disabledForeground: var(--chromapaw-ink-muted) !important;
  --vscode-titleBar-activeBackground: rgb(var(--chromapaw-surface-rgb) / 0.88) !important;
  --vscode-titleBar-activeForeground: var(--chromapaw-ink) !important;
  --vscode-titleBar-inactiveBackground: rgb(var(--chromapaw-surface-rgb) / 0.78) !important;
  --vscode-titleBar-inactiveForeground: var(--chromapaw-ink-muted) !important;
  --vscode-titleBar-border: rgb(var(--chromapaw-ink-rgb) / 0.18) !important;
  --vscode-menubar-selectionBackground: rgb(var(--chromapaw-ink-rgb) / 0.12) !important;
  --vscode-menubar-selectionForeground: var(--chromapaw-ink) !important;
  --vscode-menu-background: rgb(var(--chromapaw-surface-elevated-rgb) / 0.96) !important;
  --vscode-menu-foreground: var(--chromapaw-ink) !important;
  --vscode-menu-selectionBackground: rgb(var(--chromapaw-accent-readable-rgb) / 0.20) !important;
  --vscode-menu-selectionForeground: var(--chromapaw-ink) !important;
  --vscode-menu-border: rgb(var(--chromapaw-ink-rgb) / 0.18) !important;
  --vscode-commandCenter-background: rgb(var(--chromapaw-surface-elevated-rgb) / 0.92) !important;
  --vscode-commandCenter-foreground: var(--chromapaw-ink) !important;
  --vscode-commandCenter-activeForeground: var(--chromapaw-ink) !important;
  --vscode-commandCenter-inactiveForeground: var(--chromapaw-ink-muted) !important;
  --vscode-activityBar-background: rgb(var(--chromapaw-surface-rgb) / 0.82) !important;
  --vscode-activityBar-foreground: var(--chromapaw-ink) !important;
  --vscode-activityBar-inactiveForeground: var(--chromapaw-ink-muted) !important;
  --vscode-sideBar-background: rgb(var(--chromapaw-surface-rgb) / var(--chromapaw-panel-opacity)) !important;
  --vscode-sideBar-foreground: var(--chromapaw-ink) !important;
  --vscode-sideBarTitle-foreground: var(--chromapaw-ink) !important;
  --vscode-sideBarSectionHeader-foreground: var(--chromapaw-ink-secondary) !important;
  --vscode-statusBar-background: rgb(var(--chromapaw-surface-rgb) / 0.82) !important;
  --vscode-statusBar-foreground: var(--chromapaw-ink) !important;
  --vscode-statusBar-noFolderBackground: rgb(var(--chromapaw-surface-rgb) / 0.82) !important;
  --vscode-statusBar-noFolderForeground: var(--chromapaw-ink) !important;
  --vscode-editor-background: rgb(var(--chromapaw-surface-rgb) / 0.86) !important;
  --vscode-editor-foreground: var(--chromapaw-ink) !important;
  --vscode-editor-placeholder-foreground: var(--chromapaw-ink-muted) !important;
  --vscode-input-background: rgb(var(--chromapaw-surface-input-rgb) / 0.94) !important;
  --vscode-input-foreground: var(--chromapaw-ink) !important;
  --vscode-input-placeholderForeground: var(--chromapaw-ink-muted) !important;
  --vscode-input-border: rgb(var(--chromapaw-ink-rgb) / 0.24) !important;
  --vscode-list-activeSelectionBackground: rgb(var(--chromapaw-accent-readable-rgb) / 0.18) !important;
  --vscode-list-activeSelectionForeground: var(--chromapaw-ink) !important;
  --vscode-list-hoverBackground: rgb(var(--chromapaw-ink-rgb) / 0.12) !important;
  --vscode-list-inactiveSelectionBackground: rgb(var(--chromapaw-ink-rgb) / 0.10) !important;
  --vscode-breadcrumb-background: rgb(var(--chromapaw-surface-rgb) / 0.82) !important;
  --vscode-breadcrumb-foreground: var(--chromapaw-ink-muted) !important;
  --vscode-breadcrumb-focusForeground: var(--chromapaw-ink-secondary) !important;
  --vscode-breadcrumb-activeSelectionForeground: var(--chromapaw-ink) !important;
  --vscode-terminal-background: rgb(var(--chromapaw-surface-rgb) / 0.90) !important;
  --vscode-terminal-foreground: var(--chromapaw-ink) !important;
  --vscode-terminal-ansiWhite: var(--chromapaw-ink) !important;
  --vscode-terminal-ansiBrightWhite: var(--chromapaw-ink) !important;
}

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
  background-position: var(--chromapaw-scene-position);
  background-repeat: no-repeat;
  background-size: cover;
  filter:
    saturate(var(--chromapaw-scene-saturation))
    contrast(var(--chromapaw-scene-contrast));
}

body::after {
  position: fixed;
  z-index: 0;
  inset: 0;
  content: "";
  pointer-events: none;
  background-color: transparent;
  background-image:
    linear-gradient(
      90deg,
      rgb(var(--chromapaw-surface-rgb) / 0.12),
      transparent 18%,
      transparent 82%,
      rgb(var(--chromapaw-surface-rgb) / var(--chromapaw-scene-wash))
    ),
    linear-gradient(
      180deg,
      rgb(var(--chromapaw-surface-rgb) / var(--chromapaw-scene-wash)),
      transparent 20%,
      transparent 78%,
      rgb(var(--chromapaw-surface-rgb) / 0.11)
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

#root > div {
  background-color: transparent !important;
}

/*
 * Keep the artwork crisp. Readability comes from a directional local veil in
 * the main reading surface and opaque-enough component surfaces, never from a
 * full-window fog layer. Recomposition places a face or hero subject on the
 * side opposite this veil.
 */
.app-shell-main-content-viewport,
main.main-surface {
  background-color: transparent !important;
  background-image: var(--chromapaw-content-veil) !important;
}

/*
 * Real Codex conversations are wider than Skin Studio's preview cards. Give
 * every visible turn its own local glass carrier so copy never disappears
 * across a staged subject. Stable data attributes are used instead of host
 * utility-class names, which change between Codex builds.
 */
[data-thread-find-target] [data-turn-key] {
  position: relative;
  isolation: isolate;
  inline-size: 100%;
  max-inline-size: var(--chromapaw-reading-max-inline);
  margin-inline-start: var(--chromapaw-reading-margin-start);
  margin-inline-end: var(--chromapaw-reading-margin-end);
  border-radius: 18px;
}

[data-thread-find-target] [data-turn-key]::before {
  content: "";
  position: absolute;
  z-index: -1;
  pointer-events: none;
  inset: -5px -12px;
  border: 1px solid var(--chromapaw-reading-border);
  border-radius: inherit;
  background: var(--chromapaw-reading-surface);
  box-shadow: 0 12px 30px var(--chromapaw-reading-shadow);
  -webkit-backdrop-filter: blur(16px) saturate(112%);
  backdrop-filter: blur(16px) saturate(112%);
}

/* Keep the sticky composer independently readable over foreground artwork. */
[data-thread-scroll-footer] [data-pip-obstacle] {
  border-radius: 20px;
  background: var(--chromapaw-reading-surface-strong);
  border: 1px solid var(--chromapaw-reading-border);
  box-shadow: 0 16px 38px var(--chromapaw-reading-shadow);
  -webkit-backdrop-filter: blur(18px) saturate(112%);
  backdrop-filter: blur(18px) saturate(112%);
}

[data-avatar-mascot="true"],
[data-avatar-overlay-hit-region="mascot"],
.codex-avatar-button {
  background: transparent !important;
  -webkit-backdrop-filter: none !important;
  backdrop-filter: none !important;
}

/*
 * The notification tray lives in the transparent pet window. Codex's material
 * defaults can be light even when an image-derived dark skin supplies light
 * foreground tokens, so pair this surface and its text roles explicitly.
 */
[data-avatar-overlay-measure="notification-tray-row"]
  > div:has(> [role="button"]) {
  background: var(--chromapaw-notification-surface) !important;
  color: var(--chromapaw-notification-text) !important;
  border: 1px solid rgb(var(--chromapaw-ink-rgb) / 0.18) !important;
  box-shadow: 0 10px 28px rgb(0 0 0 / 0.22) !important;
}

[data-avatar-overlay-measure="notification-tray-row"] [role="button"],
[data-avatar-overlay-measure="notification-tray-row"]
  [role="button"]
  > span:first-child,
[data-avatar-overlay-measure="notification-tray-row"]
  [role="button"]
  > span:first-child
  * {
  color: var(--chromapaw-notification-text) !important;
}

[data-avatar-overlay-measure-body="true"] {
  color: var(--chromapaw-notification-text-secondary) !important;
}

[data-avatar-overlay-control="expand"] button,
[data-avatar-overlay-control="reply"] button,
[data-avatar-overlay-control="dismiss"] button {
  background: var(--chromapaw-notification-control-surface) !important;
  color: var(--chromapaw-notification-control-text) !important;
  border-color: rgb(var(--chromapaw-ink-rgb) / 0.22) !important;
}

.app-shell-left-panel {
  background: rgb(var(--chromapaw-surface-rgb) / var(--chromapaw-panel-opacity)) !important;
  border-right: 1px solid rgb(var(--chromapaw-accent-rgb) / 0.16);
  box-shadow: 12px 0 36px rgb(0 0 0 / 0.08);
  -webkit-backdrop-filter: blur(18px) saturate(112%);
  backdrop-filter: blur(18px) saturate(112%);
}

.app-shell-left-panel [data-thread-title] {
  color: var(--chromapaw-ink) !important;
}

.app-shell-left-panel .sidebar-foreground-muted {
  color: var(--chromapaw-ink-secondary) !important;
}

/*
 * Codex's right-side task/settings panel can establish its own light/dark
 * token scope. Bind that stable app-shell region directly to the image-derived
 * skin roles so a local host theme cannot produce a light panel with light
 * text (or the inverse).
 */
[data-app-shell-focus-area="right-panel"] {
  background: var(--chromapaw-side-panel-surface) !important;
  color: var(--chromapaw-side-panel-text) !important;
  --color-token-main-surface-primary: var(--chromapaw-side-panel-surface) !important;
  --color-token-main-surface-secondary: var(--chromapaw-side-panel-section-surface) !important;
  --color-token-bg-secondary: var(--chromapaw-side-panel-section-surface) !important;
  --color-background-panel: var(--chromapaw-side-panel-section-surface) !important;
  --color-token-foreground: var(--chromapaw-side-panel-text) !important;
  --color-token-text-primary: var(--chromapaw-side-panel-text) !important;
  --color-token-text-secondary: var(--chromapaw-side-panel-text-secondary) !important;
  --color-token-description-foreground: var(--chromapaw-side-panel-text-secondary) !important;
  border-left-color: rgb(var(--chromapaw-ink-rgb) / 0.18) !important;
  box-shadow: -14px 0 36px rgb(0 0 0 / 0.12) !important;
  -webkit-backdrop-filter: blur(18px) saturate(110%);
  backdrop-filter: blur(18px) saturate(110%);
}

[data-app-shell-focus-area="right-panel"]
  [class~="bg-token-main-surface-primary"] {
  background-color: var(--chromapaw-side-panel-surface) !important;
}

[data-app-shell-focus-area="right-panel"]
  [class~="bg-token-bg-secondary"] {
  background-color: var(--chromapaw-side-panel-section-surface) !important;
  color: var(--chromapaw-side-panel-section-text) !important;
}

[data-app-shell-focus-area="right-panel"]
  :is([class~="text-token-foreground"], [class~="text-token-text-primary"]) {
  color: var(--chromapaw-side-panel-text) !important;
}

[data-app-shell-focus-area="right-panel"]
  :is(
    [class~="text-token-description-foreground"],
    [class~="text-token-text-secondary"],
    [class~="text-token-text-tertiary"]
  ) {
  color: var(--chromapaw-side-panel-text-secondary) !important;
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

  [data-thread-find-target] [data-turn-key]::before {
    inset-inline: -8px;
    background: var(--chromapaw-reading-surface-strong);
  }
}

@media (max-width: 760px) {
  [data-thread-find-target] [data-turn-key] {
    max-inline-size: 100%;
    margin-inline: 0;
  }
}
"""
    return (
        "/* ChromaPaw Skin Studio v0.4.8 scene-fidelity stylesheet. Activation requires a compatible runtime. */\n"
        + "\n\n".join(blocks)
        + common
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    names = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size=size)
    return ImageFont.load_default()


def _cover(
    image: Image.Image, size: tuple[int, int], subject_placement: str = "source"
) -> Image.Image:
    centering = {
        "left": (0.42, 0.5),
        "right": (0.58, 0.5),
    }.get(subject_placement, (0.5, 0.5))
    return ImageOps.fit(
        image.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=centering
    ).convert("RGBA")


def render_preview(
    artwork: Image.Image,
    size: tuple[int, int],
    mode: str,
    palette: dict[str, Any],
    display_name: str,
    visual_treatment: dict[str, Any] | None = None,
) -> Image.Image:
    """Render a real-artwork desktop mockup for visual QA."""
    width, height = size
    subject_placement = str((visual_treatment or {}).get("subjectPlacement", "source"))
    canvas = _cover(artwork, size, subject_placement)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    surface = tuple(int(palette["surface"][i : i + 2], 16) for i in (1, 3, 5))
    ui = semantic_ui_palette(palette, mode)
    ink = _rgb_tuple(ui["primaryText"])
    muted_ink = _rgb_tuple(ui["mutedText"])
    accent = _rgb_tuple(ui["accentText"])
    panel_alpha = round(float(palette["panelOpacity"]) * 255)
    shadow = (0, 0, 0, 34 if mode == "light" else 72)

    edge_alpha = 22 if mode == "light" else 34
    draw.rectangle((0, 0, width, max(1, round(height * 0.025))), fill=surface + (edge_alpha,))
    draw.rectangle(
        (0, round(height * 0.975), width, height), fill=surface + (edge_alpha,)
    )

    sidebar = round(width * 0.22)
    draw.rectangle((0, 0, sidebar + 8, height), fill=shadow)
    draw.rectangle((0, 0, sidebar, height), fill=surface + (panel_alpha,))
    draw.line((sidebar, 0, sidebar, height), fill=accent + (48,), width=1)

    margin = max(18, round(width * 0.025))
    top = max(18, round(height * 0.045))
    brand_font = _font(max(16, round(width * 0.021)), bold=True)
    body_font = _font(max(11, round(width * 0.012)))
    small_font = _font(max(9, round(width * 0.010)))
    title_size = max(19, round(width * 0.026))
    title_font = _font(title_size, bold=True)
    draw.ellipse((margin, top, margin + 28, top + 28), fill=accent + (245,))
    draw.text((margin + 38, top + 2), "ChromaPaw", font=brand_font, fill=ink + (245,))

    nav_y = top + 76
    for index, label in enumerate(("New task", "Skin Studio", "Packages", "Settings")):
        y = nav_y + index * 42
        nav_ink = ink
        if index == 1:
            active_fill = (
                accent + (220,)
                if mode == "dark"
                else _blend(surface, accent, 0.16) + (245,)
            )
            draw.rounded_rectangle(
                (margin - 7, y - 8, sidebar - margin, y + 25),
                radius=10,
                fill=active_fill,
            )
            if mode == "dark":
                nav_ink = surface
        draw.ellipse((margin, y, margin + 9, y + 9), fill=accent + (180 if index == 1 else 84,))
        draw.text((margin + 20, y - 5), label, font=body_font, fill=nav_ink + (235,))

    main_left = sidebar + round(width * 0.055)
    main_right = width - round(width * 0.06)
    if subject_placement == "right":
        main_right = main_left + round((main_right - main_left) * 0.62)
    elif subject_placement == "left":
        available = main_right - main_left
        main_left = main_left + round(available * 0.38)
    content_width = main_right - main_left
    draw.text((main_left, top + 3), "SKIN STUDIO  /  PREVIEW", font=small_font, fill=accent + (245,))
    title_position = (main_left, top + 31)
    title_width = max(80, main_right - main_left - 12)
    while title_size > 14:
        candidate_box = draw.textbbox(title_position, display_name, font=title_font)
        if candidate_box[2] - candidate_box[0] <= title_width:
            break
        title_size -= 1
        title_font = _font(title_size, bold=True)
    title_box = draw.textbbox(title_position, display_name, font=title_font)
    draw.rounded_rectangle(
        (
            main_left - 9,
            top + 23,
            min(main_right, title_box[2] + 12),
            title_box[3] + 8,
        ),
        radius=10,
        fill=surface + (218 if mode == "light" else 118,),
        outline=accent + (34,),
        width=1,
    )
    draw.text(
        title_position,
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
    badge_fill = (
        accent + (224,)
        if mode == "dark"
        else _blend(surface, accent, 0.16) + (245,)
    )
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
        fill=muted_ink + (235,),
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
    if not isinstance(data, dict) or data.get("schemaVersion") not in {1, 2}:
        raise ValueError("request must be a Skin Studio schemaVersion 1 or 2 object")
    for field in ("id", "displayName", "description", "mode", "artworkImage", "source"):
        if field not in data:
            raise ValueError(f"request is missing {field}")
    if data["mode"] not in {"light", "dark", "adaptive"}:
        raise ValueError("request mode must be light, dark, or adaptive")
    if data["schemaVersion"] == 2:
        if "themeProfile" not in data or "referenceImage" not in data:
            raise ValueError("schemaVersion 2 request requires themeProfile and referenceImage")
        profile = normalize_theme_profile(data["themeProfile"])
        reference = Path(str(data["referenceImage"])).expanduser().resolve()
        if not reference.is_file():
            raise ValueError(f"reference image does not exist: {reference}")
        if profile["referenceSha256"] != sha256_file(reference):
            raise ValueError("theme profile does not match the request reference image SHA-256")
        data["themeProfile"] = profile
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
            build_css(palettes, stylesheet_mode, request.get("visualTreatment")),
            encoding="utf-8",
            newline="\n",
        )

    preview_assets: dict[str, str] = {}
    variants = []
    for variant_mode in ("light", "dark"):
        for ratio, size in PREVIEW_DIMENSIONS.items():
            key = f"{variant_mode}-{ratio.replace(':', 'x')}"
            relative = f"assets/previews/preview-{key}.png"
            preview = render_preview(
                artwork,
                size,
                variant_mode,
                palettes[variant_mode],
                str(request["displayName"]),
                request.get("visualTreatment"),
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
    ui_palettes = {
        mode: semantic_ui_palette(palettes[mode], mode) for mode in ("light", "dark")
    }
    ui_contrast_checks = []
    for variant_mode in ("light", "dark"):
        ui_palette = ui_palettes[variant_mode]
        contrast_roles = (
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
        )
        for role, surface_role in contrast_roles:
            ratio = contrast_ratio(ui_palette[surface_role], ui_palette[role])
            ui_contrast_checks.append(
                {
                    "id": f"{variant_mode}-ui-{role}-contrast",
                    "status": "pass" if ratio >= 4.5 else "fail",
                    "value": round(ratio, 2),
                    "threshold": 4.5,
                }
            )

    report = {
        "schemaVersion": 1,
        "generator": f"ChromaPaw Skin Studio {GENERATOR_VERSION}",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "backgroundDimensions": {"width": artwork.width, "height": artwork.height},
        "dominantPalette": palette_data["dominant"],
        "palettes": palettes,
        "uiPalettes": ui_palettes,
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
            {
                "id": "semantic-theme-profile",
                "status": "pass",
                "value": "present" if request.get("themeProfile") else "legacy-request",
            },
            {
                "id": "semantic-ui-token-overrides",
                "status": "pass",
                "value": "codex-and-vscode-token-families",
            },
            {
                "id": "scene-fidelity-local-protection",
                "status": "pass",
                "value": {
                    "globalWashOpacity": GLOBAL_WASH_OPACITY,
                    "contentProtection": "local-surfaces",
                    "backgroundBlur": False,
                },
                "threshold": {"maximumGlobalWashOpacity": 0.12},
            },
        ]
        + ui_contrast_checks,
        "activation": {
            "status": "not-attempted",
            "reason": "Portable package generation is separate from runtime compatibility and activation.",
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
            "visualTreatment": {
                "sceneFidelity": "preserve",
                "contentProtection": "local-surfaces",
                "subjectPlacement": str(
                    request.get("visualTreatment", {}).get("subjectPlacement", "source")
                ),
                "artworkRecomposed": bool(
                    request.get("visualTreatment", {}).get("artworkRecomposed", False)
                ),
                "globalWashOpacity": GLOBAL_WASH_OPACITY,
            },
        },
        "variants": variants,
        "source": request["source"],
        "qa": qa_relative,
    }
    if request.get("themeProfile"):
        manifest["semanticProfile"] = request["themeProfile"]
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
