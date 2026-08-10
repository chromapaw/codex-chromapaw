#!/usr/bin/env python3
"""Validate ChromaPaw v1 and Skin Studio v2 packages without dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .skin_package import (
        HEX_COLOR,
        PREVIEW_DIMENSIONS,
        REQUIRED_VARIANTS,
        SKIN_ID,
        SUPPORTED_BACKGROUND_EXTENSIONS,
        SkinPackageError,
        contrast_ratio,
        path_is_inside,
        png_dimensions,
        safe_relative_path,
    )
except ImportError:
    from skin_package import (  # type: ignore
        HEX_COLOR,
        PREVIEW_DIMENSIONS,
        REQUIRED_VARIANTS,
        SKIN_ID,
        SUPPORTED_BACKGROUND_EXTENSIONS,
        SkinPackageError,
        contrast_ratio,
        path_is_inside,
        png_dimensions,
        safe_relative_path,
    )

try:
    from .theme_profile import validate_theme_profile
except ImportError:
    from theme_profile import validate_theme_profile  # type: ignore


ALLOWED_MODES = {"light", "dark", "adaptive"}
V1_FIELDS = {"schemaVersion", "id", "displayName", "description", "mode", "assets", "theme", "source"}
V2_FIELDS = V1_FIELDS | {"layout", "variants", "qa", "semanticProfile"}


def _check_fields(
    value: dict[str, Any], required: set[str], allowed: set[str], field: str, errors: list[str]
) -> None:
    missing = sorted(required - value.keys())
    if missing:
        errors.append(f"{field} is missing required fields: {', '.join(missing)}")
    unknown = sorted(value.keys() - allowed)
    if unknown:
        errors.append(f"{field} contains unsupported fields: {', '.join(unknown)}")


def _resolve_asset(
    root: Path,
    value: object,
    field: str,
    extensions: set[str],
    errors: list[str],
) -> Path | None:
    relative, path_error = safe_relative_path(value, field)
    if path_error:
        errors.append(path_error)
        return None
    assert relative is not None
    if relative.suffix.lower() not in extensions:
        errors.append(f"{field} has an unsupported file extension")
        return None
    resolved = (root / relative).resolve()
    if not path_is_inside(root, resolved):
        errors.append(f"{field} resolves outside the package")
        return None
    if not resolved.is_file():
        errors.append(f"{field} does not exist: {value}")
        return None
    return resolved


def _validate_identity(data: dict[str, Any], errors: list[str]) -> None:
    skin_id = data.get("id")
    if not isinstance(skin_id, str) or not SKIN_ID.fullmatch(skin_id) or len(skin_id) > 64:
        errors.append("id must be lower-case kebab-case and at most 64 characters")
    display_name = data.get("displayName")
    if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 80:
        errors.append("displayName must contain 1 to 80 non-whitespace characters")
    description = data.get("description")
    if description is not None and (
        not isinstance(description, str) or not 1 <= len(description.strip()) <= 240
    ):
        errors.append("description must contain 1 to 240 non-whitespace characters")
    if data.get("mode") not in ALLOWED_MODES:
        errors.append("mode must be light, dark, or adaptive")


def _validate_palette(
    value: object, field: str, errors: list[str], *, require_contrast: bool = True
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return
    _check_fields(
        value,
        {"surface", "ink", "accent", "panelOpacity"},
        {"surface", "ink", "accent", "panelOpacity"},
        field,
        errors,
    )
    for key in ("surface", "ink", "accent"):
        color = value.get(key)
        if not isinstance(color, str) or not HEX_COLOR.fullmatch(color):
            errors.append(f"{field}.{key} must be a six-digit hex color")
    opacity = value.get("panelOpacity")
    if isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not 0.35 <= opacity <= 1:
        errors.append(f"{field}.panelOpacity must be between 0.35 and 1.0")
    surface = value.get("surface")
    ink = value.get("ink")
    if require_contrast and isinstance(surface, str) and HEX_COLOR.fullmatch(surface) and isinstance(ink, str) and HEX_COLOR.fullmatch(ink):
        ratio = contrast_ratio(surface, ink)
        if ratio < 4.5:
            errors.append(f"{field} text contrast must be at least 4.5:1; found {ratio:.2f}:1")


def _validate_source(value: object, required: bool, errors: list[str]) -> None:
    if value is None and not required:
        return
    if not isinstance(value, dict):
        errors.append("source must be an object")
        return
    required_fields = {"author", "license"} if required else set()
    _check_fields(value, required_fields, {"author", "license", "url"}, "source", errors)
    limits = {"author": 100, "license": 80}
    for key, maximum in limits.items():
        text = value.get(key)
        if text is not None and (
            not isinstance(text, str) or not 1 <= len(text.strip()) <= maximum
        ):
            errors.append(f"source.{key} must contain 1 to {maximum} characters")
    url = value.get("url")
    if url is not None:
        parsed = urlparse(url) if isinstance(url, str) else None
        if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append("source.url must be an absolute HTTP or HTTPS URL")


def _validate_v1(root: Path, data: dict[str, Any], errors: list[str]) -> None:
    _check_fields(
        data,
        {"schemaVersion", "id", "displayName", "mode", "assets", "theme"},
        V1_FIELDS,
        "skin.json",
        errors,
    )
    assets = data.get("assets")
    if not isinstance(assets, dict):
        errors.append("assets must be an object")
    else:
        _check_fields(
            assets,
            {"background", "stylesheet", "preview"},
            {"background", "stylesheet", "preview"},
            "assets",
            errors,
        )
        _resolve_asset(root, assets.get("background"), "assets.background", SUPPORTED_BACKGROUND_EXTENSIONS, errors)
        _resolve_asset(root, assets.get("stylesheet"), "assets.stylesheet", {".css"}, errors)
        _resolve_asset(root, assets.get("preview"), "assets.preview", {".png"}, errors)

    theme = data.get("theme")
    if not isinstance(theme, dict):
        errors.append("theme must be an object")
    else:
        allowed = {"surface", "ink", "accent", "panelOpacity"}
        _check_fields(theme, {"surface", "ink", "accent"}, allowed, "theme", errors)
        normalized = dict(theme)
        normalized.setdefault("panelOpacity", 0.82)
        _validate_palette(normalized, "theme", errors, require_contrast=False)
    _validate_source(data.get("source"), False, errors)


def _validate_preview(
    root: Path,
    value: object,
    field: str,
    ratio: str,
    errors: list[str],
) -> Path | None:
    path = _resolve_asset(root, value, field, {".png"}, errors)
    if path is None:
        return None
    try:
        found = png_dimensions(path)
    except SkinPackageError as exc:
        errors.append(f"{field} is invalid: {exc}")
        return None
    expected = PREVIEW_DIMENSIONS[ratio]
    if found != expected:
        errors.append(f"{field} must be exactly {expected[0]}x{expected[1]}; found {found[0]}x{found[1]}")
    return path


def _validate_v2(root: Path, data: dict[str, Any], errors: list[str]) -> None:
    _check_fields(
        data,
        {
            "schemaVersion",
            "id",
            "displayName",
            "description",
            "mode",
            "assets",
            "theme",
            "layout",
            "variants",
            "source",
            "qa",
        },
        V2_FIELDS,
        "skin.json",
        errors,
    )

    if "semanticProfile" in data:
        errors.extend(
            f"semanticProfile: {error}"
            for error in validate_theme_profile(data.get("semanticProfile"))
        )

    preview_values: dict[str, str] = {}
    stylesheet_values: dict[str, str] = {}
    assets = data.get("assets")
    if not isinstance(assets, dict):
        errors.append("assets must be an object")
    else:
        allowed = {"background", "stylesheet", "preview", "stylesheets", "previews"}
        _check_fields(assets, allowed, allowed, "assets", errors)
        _resolve_asset(root, assets.get("background"), "assets.background", SUPPORTED_BACKGROUND_EXTENSIONS, errors)
        _resolve_asset(root, assets.get("stylesheet"), "assets.stylesheet", {".css"}, errors)
        _validate_preview(root, assets.get("preview"), "assets.preview", "16:10", errors)

        stylesheets = assets.get("stylesheets")
        if not isinstance(stylesheets, dict):
            errors.append("assets.stylesheets must be an object")
        else:
            _check_fields(
                stylesheets,
                {"light", "dark", "adaptive"},
                {"light", "dark", "adaptive"},
                "assets.stylesheets",
                errors,
            )
            for mode in ("light", "dark", "adaptive"):
                value = stylesheets.get(mode)
                _resolve_asset(root, value, f"assets.stylesheets.{mode}", {".css"}, errors)
                if isinstance(value, str):
                    stylesheet_values[mode] = value

            active_mode = data.get("mode")
            if active_mode in ALLOWED_MODES and assets.get("stylesheet") != stylesheet_values.get(active_mode):
                errors.append(f"assets.stylesheet must match assets.stylesheets.{active_mode}")

        previews = assets.get("previews")
        expected_keys = {
            f"{mode}-{ratio.replace(':', 'x')}"
            for mode in ("light", "dark")
            for ratio in PREVIEW_DIMENSIONS
        }
        if not isinstance(previews, dict):
            errors.append("assets.previews must be an object")
        else:
            _check_fields(previews, expected_keys, expected_keys, "assets.previews", errors)
            for mode in ("light", "dark"):
                for ratio in PREVIEW_DIMENSIONS:
                    key = f"{mode}-{ratio.replace(':', 'x')}"
                    value = previews.get(key)
                    _validate_preview(root, value, f"assets.previews.{key}", ratio, errors)
                    if isinstance(value, str):
                        preview_values[key] = value

            if assets.get("preview") != "assets/preview.png":
                errors.append("assets.preview must point to assets/preview.png")

    theme = data.get("theme")
    if not isinstance(theme, dict):
        errors.append("theme must be an object")
    else:
        allowed = {"surface", "ink", "accent", "panelOpacity", "palettes"}
        _check_fields(theme, allowed, allowed, "theme", errors)
        _validate_palette({key: theme.get(key) for key in ("surface", "ink", "accent", "panelOpacity")}, "theme", errors)
        palettes = theme.get("palettes")
        if not isinstance(palettes, dict):
            errors.append("theme.palettes must be an object")
        else:
            _check_fields(palettes, {"light", "dark"}, {"light", "dark"}, "theme.palettes", errors)
            _validate_palette(palettes.get("light"), "theme.palettes.light", errors)
            _validate_palette(palettes.get("dark"), "theme.palettes.dark", errors)

    layout = data.get("layout")
    if not isinstance(layout, dict):
        errors.append("layout must be an object")
    else:
        _check_fields(
            layout,
            {"safeContentZone", "depthLayers"},
            {"safeContentZone", "depthLayers"},
            "layout",
            errors,
        )
        zone = layout.get("safeContentZone")
        if not isinstance(zone, dict):
            errors.append("layout.safeContentZone must be an object")
        else:
            keys = {"x", "y", "width", "height"}
            _check_fields(zone, keys, keys, "layout.safeContentZone", errors)
            for key in keys:
                number = zone.get(key)
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not 0 <= number <= 1:
                    errors.append(f"layout.safeContentZone.{key} must be between 0 and 1")
            if all(isinstance(zone.get(key), (int, float)) and not isinstance(zone.get(key), bool) for key in keys):
                if zone["width"] <= 0 or zone["height"] <= 0:
                    errors.append("layout.safeContentZone width and height must be greater than 0")
                if zone["x"] + zone["width"] > 1 or zone["y"] + zone["height"] > 1:
                    errors.append("layout.safeContentZone must remain inside the canvas")
        layers = layout.get("depthLayers")
        expected_layers = ["atmosphere", "distant", "midground", "foreground"]
        if layers != expected_layers:
            errors.append("layout.depthLayers must list atmosphere, distant, midground, and foreground in order")

    variants = data.get("variants")
    found_pairs: set[tuple[str, str]] = set()
    found_ids: set[str] = set()
    if not isinstance(variants, list):
        errors.append("variants must be an array")
    else:
        for index, variant in enumerate(variants):
            field = f"variants[{index}]"
            if not isinstance(variant, dict):
                errors.append(f"{field} must be an object")
                continue
            keys = {"id", "mode", "aspectRatio", "preview", "stylesheet"}
            _check_fields(variant, keys, keys, field, errors)
            variant_id = variant.get("id")
            if not isinstance(variant_id, str) or not SKIN_ID.fullmatch(variant_id):
                errors.append(f"{field}.id must be lower-case kebab-case")
            elif variant_id in found_ids:
                errors.append(f"{field}.id is duplicated: {variant_id}")
            else:
                found_ids.add(variant_id)
            mode = variant.get("mode")
            ratio = variant.get("aspectRatio")
            if mode not in {"light", "dark"}:
                errors.append(f"{field}.mode must be light or dark")
            if ratio not in PREVIEW_DIMENSIONS:
                errors.append(f"{field}.aspectRatio must be 16:10, 16:9, or 4:3")
            if mode in {"light", "dark"} and ratio in PREVIEW_DIMENSIONS:
                pair = (mode, ratio)
                if pair in found_pairs:
                    errors.append(f"{field} duplicates the {mode} {ratio} variant")
                found_pairs.add(pair)
                expected_key = f"{mode}-{ratio.replace(':', 'x')}"
                if preview_values.get(expected_key) != variant.get("preview"):
                    errors.append(f"{field}.preview must match assets.previews.{expected_key}")
                if stylesheet_values.get(mode) != variant.get("stylesheet"):
                    errors.append(f"{field}.stylesheet must match assets.stylesheets.{mode}")
    missing_pairs = sorted(REQUIRED_VARIANTS - found_pairs)
    if missing_pairs:
        errors.append(
            "variants is missing required combinations: "
            + ", ".join(f"{mode} {ratio}" for mode, ratio in missing_pairs)
        )

    _validate_source(data.get("source"), True, errors)
    qa_path = _resolve_asset(root, data.get("qa"), "qa", {".json"}, errors)
    if qa_path is not None:
        try:
            report = json.loads(qa_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"qa report cannot be read: {exc}")
        else:
            if not isinstance(report, dict) or report.get("schemaVersion") != 1:
                errors.append("qa report must be a schemaVersion 1 object")
            else:
                checks = report.get("checks")
                if not isinstance(checks, list) or not checks:
                    errors.append("qa report checks must be a non-empty array")
                elif any(not isinstance(check, dict) or check.get("status") != "pass" for check in checks):
                    errors.append("qa report contains a check that did not pass")


def validate_package(package_dir: Path) -> list[str]:
    errors: list[str] = []
    root = package_dir.resolve()
    manifest_path = root / "skin.json"
    if not manifest_path.is_file():
        return ["skin.json is missing"]
    if not path_is_inside(root, manifest_path.resolve()):
        return ["skin.json resolves outside the package"]
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"skin.json cannot be read: {exc}"]
    if not isinstance(data, dict):
        return ["skin.json must contain a JSON object"]

    version = data.get("schemaVersion")
    if version not in {1, 2}:
        return ["schemaVersion must be 1 or 2"]
    _validate_identity(data, errors)
    if version == 1:
        _validate_v1(root, data, errors)
    else:
        _validate_v2(root, data, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Directory containing skin.json")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    args = parser.parse_args()
    package = args.package.expanduser().resolve()
    errors = validate_package(package)
    if args.json:
        print(json.dumps({"ok": not errors, "package": str(package), "errors": errors}, indent=2))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
    else:
        print(f"OK: {package}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
