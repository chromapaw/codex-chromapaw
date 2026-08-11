#!/usr/bin/env python3
"""Audit installed Codex pets without changing or removing any package."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from pet_package import PetPackageError, image_dimensions, safe_relative_path, validate_pet_package


def resolve_codex_home(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".codex")


def _legacy_dimensions(root: Path, manifest: dict[str, Any]) -> list[int] | None:
    relative, error = safe_relative_path(manifest.get("spritesheetPath"), "spritesheetPath")
    if error or relative is None:
        return None
    path = (root / relative).resolve()
    try:
        if path.is_file() and path.is_relative_to(root):
            return list(image_dimensions(path))
    except (OSError, PetPackageError):
        pass
    return None


def audit_pet(path: Path) -> dict[str, Any]:
    root = path.expanduser().resolve()
    errors, package = validate_pet_package(root)
    if package is not None:
        return {
            "name": root.name,
            "path": str(root),
            "status": "valid-v2",
            "id": package.pet_id,
            "dimensions": [package.width, package.height],
            "errors": [],
            "action": "none",
        }

    manifest: dict[str, Any] = {}
    manifest_path = root / "pet.json"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            manifest = value
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    dimensions = _legacy_dimensions(root, manifest)
    legacy = manifest.get("spriteVersionNumber") == 1 or dimensions == [1536, 1872]
    return {
        "name": root.name,
        "path": str(root),
        "status": "legacy-v1" if legacy else "invalid",
        "id": manifest.get("id"),
        "dimensions": dimensions,
        "errors": errors,
        "action": (
            "upgrade through hatch-pet to an 8x11 v2 package or remove it manually after review"
            if legacy
            else "repair or remove it manually after reviewing the validation errors"
        ),
    }


def audit_pets(codex_home: Path) -> dict[str, Any]:
    home = codex_home.expanduser().resolve()
    pets_root = home / "pets"
    entries = []
    if pets_root.is_dir():
        entries = [
            audit_pet(path)
            for path in sorted(pets_root.iterdir(), key=lambda item: item.name.casefold())
            if path.is_dir() and not path.name.startswith(".")
        ]
    issue_count = sum(entry["status"] != "valid-v2" for entry in entries)
    return {
        "ok": True,
        "codexHome": str(home),
        "petsRoot": str(pets_root),
        "petCount": len(entries),
        "validV2Count": len(entries) - issue_count,
        "issueCount": issue_count,
        "releaseReady": issue_count == 0,
        "pets": entries,
        "modifiesFiles": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--allow-issues",
        action="store_true",
        help="Return success after reporting legacy or invalid pets",
    )
    args = parser.parse_args()
    result = audit_pets(resolve_codex_home(args.codex_home))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for pet in result["pets"]:
            print(f"{pet['status']}: {pet['name']} ({pet['path']})")
        print(
            f"Audited {result['petCount']} pets: {result['validV2Count']} valid v2, "
            f"{result['issueCount']} requiring review"
        )
    return 0 if result["releaseReady"] or args.allow_issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
