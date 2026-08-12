#!/usr/bin/env python3
"""Describe the explicit, non-mutating handoff after skin or pet generation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from pet_package import validate_pet_package
from validate_skin_package import validate_package


def _platform_name(value: str) -> str:
    if value != "auto":
        return value
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _codex_home(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def skin_guidance(package: Path, manifest: dict[str, Any], platform: str) -> dict[str, Any]:
    supported_candidate = platform == "windows"
    next_step: dict[str, Any]
    if supported_candidate:
        next_step = {
            "userMessage": "应用这个皮肤",
            "actionAfterMessage": "read-only-runtime-preflight",
            "appliesImmediately": False,
            "laterExperimentalConfirmationRequired": True,
            "explanation": (
                "ChromaPaw will first show the exact executable, version, adapter, "
                "processes, and runtime behavior. Activation happens only after a "
                "second explicit experimental-runtime confirmation."
            ),
        }
    else:
        next_step = {
            "userMessage": None,
            "actionAfterMessage": None,
            "appliesImmediately": False,
            "laterExperimentalConfirmationRequired": False,
            "explanation": (
                "The portable package is ready, but this platform currently has no "
                "supported live skin activation path."
            ),
        }
    treatment = manifest.get("layout", {}).get("visualTreatment", {})
    return {
        "ok": True,
        "assetType": "skin",
        "status": "generated-not-active",
        "package": str(package),
        "id": manifest.get("id"),
        "displayName": manifest.get("displayName"),
        "platform": platform,
        "liveActivationCandidate": supported_candidate,
        "visualTreatment": treatment,
        "nextStep": next_step,
    }


def pet_guidance(
    package: Path,
    manifest: dict[str, Any],
    codex_home: Path,
) -> dict[str, Any]:
    pet_id = str(manifest.get("id"))
    destination = (codex_home / "pets" / pet_id).resolve()
    replacement = destination.exists()
    confirmation = (
        f"同意替换安装宠物 {pet_id}" if replacement else "安装这个宠物"
    )
    return {
        "ok": True,
        "assetType": "pet",
        "status": "generated-not-installed",
        "package": str(package),
        "id": pet_id,
        "displayName": manifest.get("displayName"),
        "destination": str(destination),
        "replacementRequired": replacement,
        "nextStep": {
            "userMessage": confirmation,
            "actionAfterMessage": "backup-and-replace" if replacement else "install",
            "appliesImmediately": False,
            "explicitConfirmationRequired": True,
            "backupRequired": replacement,
        },
    }


def build_guidance(
    asset_type: str,
    package: Path,
    platform: str,
    codex_home: Path,
) -> dict[str, Any]:
    resolved = package.expanduser().resolve()
    if asset_type == "skin":
        errors = validate_package(resolved)
        if errors:
            raise ValueError("skin package validation failed: " + "; ".join(errors))
        manifest = json.loads((resolved / "skin.json").read_text(encoding="utf-8"))
        return skin_guidance(resolved, manifest, platform)

    errors, validated = validate_pet_package(resolved)
    if errors or validated is None:
        raise ValueError("pet package validation failed: " + "; ".join(errors))
    return pet_guidance(resolved, validated.manifest, codex_home)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_type", choices=("skin", "pet"))
    parser.add_argument("package", type=Path)
    parser.add_argument(
        "--platform", choices=("auto", "windows", "macos", "linux"), default="auto"
    )
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = build_guidance(
            args.asset_type,
            args.package,
            _platform_name(args.platform),
            _codex_home(args.codex_home),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"READY: {result['displayName']} ({result['status']})")
        message = result["nextStep"].get("userMessage")
        if message:
            print(f"CONFIRM WITH: {message}")
        print(result["nextStep"].get("explanation", "No state change has been made."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
