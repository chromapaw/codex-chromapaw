#!/usr/bin/env python3
"""Validate a local Codex v2 pet package without third-party dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pet_package import validate_pet_package


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Directory containing pet.json")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write a machine-readable validation result",
    )
    args = parser.parse_args()

    errors, package = validate_pet_package(args.package)
    result = {
        "ok": not errors,
        "package": str(args.package.resolve()),
        "errors": errors,
    }
    if package is not None:
        result.update(
            {
                "id": package.pet_id,
                "spritesheet": str(package.spritesheet_path),
                "dimensions": [package.width, package.height],
                "spriteVersionNumber": 2,
            }
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
    else:
        print(
            f"OK: {package.pet_id} ({package.width}x{package.height}, v2) "
            f"at {package.package_dir}"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
