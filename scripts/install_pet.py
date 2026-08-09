#!/usr/bin/env python3
"""Safely install a validated ChromaPaw pet into a Codex home directory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pet_package import PetPackageError, ValidatedPetPackage, validate_pet_package


def resolve_codex_home(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def _is_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _is_link_like(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _remove_staging_dir(pets_root: Path, staging: Path) -> None:
    resolved_root = pets_root.resolve()
    resolved_staging = staging.resolve()
    if (
        staging.exists()
        and _is_inside(resolved_root, resolved_staging)
        and resolved_staging.parent == resolved_root
        and resolved_staging.name.startswith(".chromapaw-stage-")
    ):
        shutil.rmtree(resolved_staging)


def _stage_package(package: ValidatedPetPackage, pets_root: Path) -> Path:
    staging = Path(tempfile.mkdtemp(prefix=".chromapaw-stage-", dir=pets_root))
    try:
        shutil.copy2(package.manifest_path, staging / "pet.json")
        target_sheet = staging / package.spritesheet_relative_path
        target_sheet.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package.spritesheet_path, target_sheet)
        staged_errors, _ = validate_pet_package(staging)
        if staged_errors:
            raise PetPackageError(
                "staged package failed validation: " + "; ".join(staged_errors)
            )
    except Exception:
        _remove_staging_dir(pets_root, staging)
        raise
    return staging


def install_pet(
    package_dir: Path,
    codex_home: Path,
    *,
    replace: bool = False,
    backup_label: str | None = None,
) -> dict[str, Any]:
    errors, package = validate_pet_package(package_dir)
    if errors or package is None:
        raise PetPackageError("package validation failed: " + "; ".join(errors))

    home = codex_home.expanduser().resolve()
    pets_root = home / "pets"
    pets_root.mkdir(parents=True, exist_ok=True)
    pets_root = pets_root.resolve()
    destination = pets_root / package.pet_id
    if not _is_inside(pets_root, destination):
        raise PetPackageError("resolved pet destination escapes the Codex pets directory")
    if _is_link_like(destination):
        raise PetPackageError("refusing to replace a linked pet directory")
    if destination.exists() and not destination.is_dir():
        raise PetPackageError("pet destination exists but is not a directory")
    if destination.exists() and not replace:
        raise PetPackageError(
            f"pet already exists: {destination}; pass --replace to back it up and replace it"
        )

    staging = _stage_package(package, pets_root)
    backup: Path | None = None
    try:
        if destination.exists():
            backup_root = pets_root / ".chromapaw-backups"
            backup_root.mkdir(parents=True, exist_ok=True)
            backup_root = backup_root.resolve()
            if not _is_inside(pets_root, backup_root) or backup_root.parent != pets_root:
                raise PetPackageError("managed backup directory escapes the Codex pets directory")
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            suffix = f"-{backup_label}" if backup_label else ""
            backup = backup_root / f"{package.pet_id}-{timestamp}{suffix}"
            destination.replace(backup)
        try:
            staging.replace(destination)
        except Exception:
            if backup is not None and backup.exists() and not destination.exists():
                backup.replace(destination)
            raise
    finally:
        _remove_staging_dir(pets_root, staging)

    return {
        "ok": True,
        "id": package.pet_id,
        "destination": str(destination),
        "backup": str(backup) if backup is not None else None,
        "spriteVersionNumber": 2,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Validated directory containing pet.json")
    parser.add_argument("--codex-home", type=Path, help="Defaults to CODEX_HOME or ~/.codex")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Back up and replace an existing pet with the same id",
    )
    parser.add_argument("--json", action="store_true", help="Write a JSON result")
    args = parser.parse_args()

    try:
        result = install_pet(
            args.package.expanduser().resolve(),
            resolve_codex_home(args.codex_home),
            replace=args.replace,
        )
    except (OSError, PetPackageError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"INSTALLED: {result['destination']}")
        if result["backup"]:
            print(f"BACKUP: {result['backup']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
