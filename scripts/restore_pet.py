#!/usr/bin/env python3
"""Restore a pet from ChromaPaw's managed backup directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from install_pet import install_pet, resolve_codex_home
from pet_package import PetPackageError


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_backup(value: Path, codex_home: Path) -> Path:
    pets_root = (codex_home / "pets").resolve()
    backup_root = (pets_root / ".chromapaw-backups").resolve()
    if not _inside(pets_root, backup_root) or backup_root.parent != pets_root:
        raise PetPackageError("managed backup directory escapes the Codex pets directory")
    candidate = value.expanduser()
    if not candidate.is_absolute():
        candidate = backup_root / candidate
    candidate = candidate.resolve()
    if not _inside(backup_root, candidate):
        raise PetPackageError("backup must be inside .chromapaw-backups")
    if not candidate.is_dir():
        raise PetPackageError(f"backup does not exist: {candidate}")
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Backup directory name or full path")
    parser.add_argument("--codex-home", type=Path, help="Defaults to CODEX_HOME or ~/.codex")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Back up and replace the currently installed pet",
    )
    parser.add_argument("--json", action="store_true", help="Write a JSON result")
    args = parser.parse_args()

    try:
        codex_home = resolve_codex_home(args.codex_home)
        backup = resolve_backup(args.backup, codex_home)
        result = install_pet(
            backup,
            codex_home,
            replace=args.replace,
            backup_label="before-restore",
        )
        result["restoredFrom"] = str(backup)
    except (OSError, PetPackageError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"RESTORED: {result['destination']}")
        print(f"SOURCE: {result['restoredFrom']}")
        if result["backup"]:
            print(f"PREVIOUS VERSION BACKUP: {result['backup']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
