#!/usr/bin/env python3
"""Check whether the external visual-generation dependencies are available."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


HATCH_PET_REQUIRED_FILES = (
    "SKILL.md",
    "scripts/prepare_pet_run.py",
    "scripts/assemble_extended_atlas.py",
    "scripts/validate_atlas.py",
)


def resolve_codex_home(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def hatch_pet_candidates(
    codex_home: Path, explicit: Path | None = None
) -> list[Path]:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser().resolve())

    configured = os.environ.get("CHROMAPAW_HATCH_PET_DIR")
    if configured:
        candidates.append(Path(configured).expanduser().resolve())

    candidates.extend(
        (
            codex_home / "skills" / "hatch-pet",
            codex_home / "skills" / ".system" / "hatch-pet",
        )
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def inspect_hatch_pet(candidate: Path) -> dict[str, Any]:
    missing = [
        relative
        for relative in HATCH_PET_REQUIRED_FILES
        if not (candidate / relative).is_file()
    ]
    return {
        "path": str(candidate),
        "available": not missing,
        "missing": missing,
    }


def check_dependencies(
    codex_home: Path, hatch_pet_dir: Path | None = None
) -> dict[str, Any]:
    checked = [
        inspect_hatch_pet(candidate)
        for candidate in hatch_pet_candidates(codex_home, hatch_pet_dir)
    ]
    selected = next((item for item in checked if item["available"]), None)
    ok = selected is not None
    return {
        "ok": ok,
        "codexHome": str(codex_home),
        "dependencies": {
            "hatch-pet": {
                "available": ok,
                "path": selected["path"] if selected else None,
                "requiredFiles": list(HATCH_PET_REQUIRED_FILES),
                "checked": checked,
            }
        },
        "message": (
            "hatch-pet is ready for ChromaPaw pet generation."
            if ok
            else "hatch-pet is required for visual generation and QA. Install a compatible "
            "hatch-pet skill, update Codex if it is provided by your distribution, or set "
            "CHROMAPAW_HATCH_PET_DIR to a compatible local skill directory."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, help="Defaults to CODEX_HOME or ~/.codex")
    parser.add_argument(
        "--hatch-pet-dir",
        type=Path,
        help="Explicit compatible hatch-pet skill directory",
    )
    parser.add_argument("--json", action="store_true", help="Write a JSON result")
    args = parser.parse_args()

    result = check_dependencies(
        resolve_codex_home(args.codex_home),
        args.hatch_pet_dir,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        prefix = "OK" if result["ok"] else "MISSING"
        print(f"{prefix}: {result['message']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
