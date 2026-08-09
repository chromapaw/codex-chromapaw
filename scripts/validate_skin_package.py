#!/usr/bin/env python3
"""Validate the portable ChromaPaw skin package contract without dependencies."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_MODES = {"light", "dark", "adaptive"}
ASSET_EXTENSIONS = {
    "background": {".png", ".webp", ".jpg", ".jpeg"},
    "stylesheet": {".css"},
    "preview": {".png"},
}


def _asset_path(package_dir: Path, value: object, key: str) -> tuple[Path | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, f"assets.{key} must be a non-empty relative path"
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None, f"assets.{key} must stay inside the package"
    if path.suffix.lower() not in ASSET_EXTENSIONS[key]:
        return None, f"assets.{key} has an unsupported file extension"
    resolved = (package_dir / path).resolve()
    if package_dir.resolve() not in resolved.parents:
        return None, f"assets.{key} resolves outside the package"
    return resolved, None


def validate_package(package_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = package_dir / "skin.json"
    if not manifest_path.is_file():
        return ["skin.json is missing"]

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"skin.json cannot be read: {exc}"]

    if not isinstance(data, dict):
        return ["skin.json must contain a JSON object"]

    if data.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")

    skin_id = data.get("id")
    if not isinstance(skin_id, str) or not ID.fullmatch(skin_id) or len(skin_id) > 64:
        errors.append("id must be lower-case kebab-case and at most 64 characters")

    display_name = data.get("displayName")
    if not isinstance(display_name, str) or not 1 <= len(display_name) <= 80:
        errors.append("displayName must contain 1 to 80 characters")

    if data.get("mode") not in ALLOWED_MODES:
        errors.append("mode must be light, dark, or adaptive")

    assets = data.get("assets")
    if not isinstance(assets, dict):
        errors.append("assets must be an object")
    else:
        for key in ASSET_EXTENSIONS:
            resolved, error = _asset_path(package_dir, assets.get(key), key)
            if error:
                errors.append(error)
            elif resolved is not None and not resolved.is_file():
                errors.append(f"assets.{key} does not exist: {assets[key]}")

    theme = data.get("theme")
    if not isinstance(theme, dict):
        errors.append("theme must be an object")
    else:
        for key in ("surface", "ink", "accent"):
            value = theme.get(key)
            if not isinstance(value, str) or not HEX.fullmatch(value):
                errors.append(f"theme.{key} must be a six-digit hex color")
        opacity = theme.get("panelOpacity", 0.82)
        if isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not 0.35 <= opacity <= 1:
            errors.append("theme.panelOpacity must be between 0.35 and 1.0")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Directory containing skin.json")
    args = parser.parse_args()
    errors = validate_package(args.package.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {args.package.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
