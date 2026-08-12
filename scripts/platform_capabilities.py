#!/usr/bin/env python3
"""Report ChromaPaw generation, installation, and activation capabilities."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

try:
    from .check_dependencies import check_dependencies, resolve_codex_home
    from .macos_compat import discover_apps
except ImportError:
    from check_dependencies import check_dependencies, resolve_codex_home  # type: ignore
    from macos_compat import discover_apps  # type: ignore


ROOT = Path(__file__).resolve().parents[1]


def report_capabilities(codex_home: Path) -> dict[str, Any]:
    dependencies = check_dependencies(codex_home)
    platform = sys.platform
    skin_generation_implemented = all(
        path.is_file()
        for path in (
            ROOT / "scripts" / "prepare_theme_profile.py",
            ROOT / "scripts" / "prepare_skin_request.py",
            ROOT / "scripts" / "build_skin_package.py",
            ROOT / "scripts" / "validate_skin_package.py",
        )
    )
    pillow_available = importlib.util.find_spec("PIL") is not None
    skin_generation_ready = skin_generation_implemented and pillow_available
    pet_generation_ready = bool(dependencies["dependencies"]["hatch-pet"]["available"])
    windows_candidates: list[dict[str, Any]] = []
    if platform == "win32":
        try:
            from windows_runtime import discover_executables  # type: ignore

            windows_candidates = discover_executables()
        except (ImportError, OSError, RuntimeError, ValueError):
            windows_candidates = []
    macos_candidates = discover_apps() if platform == "darwin" else []
    enabled_windows = [
        candidate
        for candidate in windows_candidates
        if candidate.get("activationEnabled") is True
    ]
    return {
        "ok": skin_generation_ready,
        "reportGenerated": True,
        "readinessSemantics": (
            "ok means the deterministic skin-package workflow is locally ready; "
            "inspect workflowReadiness for pet and combined readiness"
        ),
        "workflowReadiness": {
            "skin": skin_generation_ready,
            "pet": pet_generation_ready,
            "allOneImageWorkflows": skin_generation_ready and pet_generation_ready,
        },
        "platform": platform,
        "oneImageWorkflow": {
            "skinGeneration": {
                "implemented": skin_generation_implemented,
                "ready": skin_generation_ready,
                "pillowAvailable": pillow_available,
                "semanticProfileRequired": True,
                "contentRule": "motifs come from the uploaded image and user intent, never a fixed scene template",
                "deterministicPackagingReady": skin_generation_ready,
                "sceneGeneration": {
                    "requiredWhen": (
                        "the upload is not a full environment or a salient subject "
                        "overlaps the reading/input safe zone"
                    ),
                    "availability": "host-capability-not-programmatically-detectable",
                },
                "sceneExpansion": (
                    "requires Codex image generation when the upload is not a full "
                    "environment or a salient subject overlaps the reading/input safe zone"
                ),
            },
            "petGeneration": {
                "implemented": True,
                "ready": pet_generation_ready,
                "dependency": "hatch-pet",
                "dependencyPath": dependencies["dependencies"]["hatch-pet"]["path"],
                "dependencyValidation": dependencies["dependencies"]["hatch-pet"].get(
                    "validation"
                ),
            },
        },
        "petInstallation": {
            "implementation": "portable Python/CODEX_HOME workflow",
            "selection": "implemented with config backup and conflict detection",
            "visibilityVerification": "real Codex acceptance test still required",
            "windows": "implemented",
            "macos": "implementation present; real-device validation required",
        },
        "skinActivation": {
            "officialPublicApi": False,
            "windows": {
                "mode": "experimental exact-version adapter",
                "candidates": windows_candidates,
                "enabledCandidates": len(enabled_windows),
            },
            "macos": {
                "mode": "read-only compatibility probe",
                "activationImplemented": False,
                "candidates": macos_candidates,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = report_capabilities(resolve_codex_home(args.codex_home))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        skin = result["oneImageWorkflow"]["skinGeneration"]
        pet = result["oneImageWorkflow"]["petGeneration"]
        print(
            f"skin-generation={'ready' if skin['ready'] else 'dependency-missing'}; "
            f"pet-generation={'ready' if pet['ready'] else 'dependency-missing'}; "
            f"platform={result['platform']}"
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
