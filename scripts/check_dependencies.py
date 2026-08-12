#!/usr/bin/env python3
"""Check whether external visual-generation dependencies are compatible."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


HATCH_PET_CONTRACT_VERSION = 1
HATCH_PET_SKILL_NAME = "hatch-pet"
HATCH_PET_REQUIRED_PYTHON_SCRIPTS = (
    "scripts/prepare_pet_run.py",
    "scripts/compose_atlas.py",
    "scripts/extract_strip_frames.py",
    "scripts/inspect_frames.py",
    "scripts/make_contact_sheet.py",
    "scripts/despill_chroma_edges.py",
    "scripts/compose_cardinal_anchor_strip.py",
    "scripts/extract_cardinal_anchors.py",
    "scripts/derive_running_left_from_running_right.py",
    "scripts/assemble_extended_atlas.py",
    "scripts/make_direction_qa_sheet.py",
    "scripts/make_direction_blind_qa_sheet.py",
    "scripts/validate_direction_blind_verdicts.py",
    "scripts/combine_direction_blind_verdicts.py",
    "scripts/measure_direction_continuity.py",
    "scripts/render_animation_previews.py",
    "scripts/validate_atlas.py",
)
HATCH_PET_REQUIRED_FILES = ("SKILL.md", *HATCH_PET_REQUIRED_PYTHON_SCRIPTS)
HATCH_PET_CAPABILITY_FILES = {
    "skillContract": ("SKILL.md",),
    "runPreparation": ("scripts/prepare_pet_run.py",),
    "atlasAssembly": (
        "scripts/compose_atlas.py",
        "scripts/extract_strip_frames.py",
        "scripts/despill_chroma_edges.py",
        "scripts/assemble_extended_atlas.py",
    ),
    "lookDirections": (
        "scripts/compose_cardinal_anchor_strip.py",
        "scripts/extract_cardinal_anchors.py",
        "scripts/derive_running_left_from_running_right.py",
        "scripts/assemble_extended_atlas.py",
    ),
    "structuralQa": (
        "scripts/inspect_frames.py",
        "scripts/validate_atlas.py",
    ),
    "visualQa": (
        "scripts/make_contact_sheet.py",
        "scripts/render_animation_previews.py",
    ),
    "directionQa": (
        "scripts/make_direction_qa_sheet.py",
        "scripts/measure_direction_continuity.py",
    ),
    "blindDirectionQa": (
        "scripts/make_direction_blind_qa_sheet.py",
        "scripts/validate_direction_blind_verdicts.py",
        "scripts/combine_direction_blind_verdicts.py",
    ),
}
HATCH_PET_REQUIRED_SKILL_MARKERS = (
    "load_workspace_dependencies",
    "imagegen-jobs.json",
    "spriteVersionNumber: 2",
)
HATCH_PET_SCRIPT_CONTRACTS = {
    "scripts/prepare_pet_run.py": {"functions": ("main",), "flags": ("--reference", "--output-dir")},
    "scripts/compose_atlas.py": {"functions": ("main",), "flags": ("--output", "--webp-output")},
    "scripts/extract_strip_frames.py": {"functions": ("main",), "flags": ("--output-dir", "--states")},
    "scripts/inspect_frames.py": {"functions": ("main",), "flags": ("--frames-root", "--json-out")},
    "scripts/make_contact_sheet.py": {"functions": ("main",), "flags": ("--output",)},
    "scripts/despill_chroma_edges.py": {"functions": ("main",), "flags": ("--output", "--json-out")},
    "scripts/compose_cardinal_anchor_strip.py": {"functions": ("main",), "flags": ("--anchors-dir", "--output")},
    "scripts/extract_cardinal_anchors.py": {"functions": ("main",), "flags": ("--strip", "--output-dir")},
    "scripts/derive_running_left_from_running_right.py": {"functions": ("main",), "flags": ("--run-dir",)},
    "scripts/assemble_extended_atlas.py": {"functions": ("main",), "flags": ("--base-atlas", "--output")},
    "scripts/make_direction_qa_sheet.py": {"functions": ("main",), "flags": ("--output",)},
    "scripts/make_direction_blind_qa_sheet.py": {"functions": ("main",), "flags": ("--answer-key", "--output")},
    "scripts/validate_direction_blind_verdicts.py": {"functions": ("main",), "flags": ("--answer-key", "--verdicts")},
    "scripts/combine_direction_blind_verdicts.py": {"functions": ("main",), "flags": ("--verdicts", "--json-out")},
    "scripts/measure_direction_continuity.py": {"functions": ("main",), "flags": ("--json-out",)},
    "scripts/render_animation_previews.py": {"functions": ("main",), "flags": ("--frames-root", "--output-dir")},
    "scripts/validate_atlas.py": {"functions": ("main",), "flags": ("--json-out", "--require-v2")},
}


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


def _issue(code: str, path: str, message: str, **details: Any) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    issue.update(details)
    return issue


def _frontmatter_metadata(path: Path) -> tuple[dict[str, str | None], list[dict[str, Any]]]:
    metadata: dict[str, str | None] = {"name": None, "description": None}
    issues: list[dict[str, Any]] = []
    try:
        source = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        issues.append(_issue("skill_read_error", "SKILL.md", str(exc)))
        return metadata, issues

    lines = source.splitlines()
    if not lines or lines[0].strip() != "---":
        issues.append(
            _issue(
                "skill_frontmatter_missing",
                "SKILL.md",
                "SKILL.md must start with YAML frontmatter",
            )
        )
        return metadata, issues

    try:
        closing = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration:
        issues.append(
            _issue(
                "skill_frontmatter_unclosed",
                "SKILL.md",
                "SKILL.md frontmatter has no closing delimiter",
            )
        )
        return metadata, issues

    values: dict[str, list[str]] = {"name": [], "description": []}
    for line in lines[1:closing]:
        if line[:1].isspace():
            continue
        match = re.match(r"^(name|description)\s*:\s*(.*?)\s*$", line)
        if match:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1].strip()
            values[match.group(1)].append(value)

    for field, found in values.items():
        if len(found) > 1:
            issues.append(
                _issue(
                    "skill_metadata_duplicate",
                    "SKILL.md",
                    f"frontmatter field {field!r} must appear exactly once",
                    field=field,
                )
            )
        if found:
            metadata[field] = found[0]

    if metadata["name"] != HATCH_PET_SKILL_NAME:
        issues.append(
            _issue(
                "skill_name_mismatch",
                "SKILL.md",
                f"frontmatter name must be {HATCH_PET_SKILL_NAME!r}",
                expected=HATCH_PET_SKILL_NAME,
                actual=metadata["name"],
            )
        )
    if not metadata["description"]:
        issues.append(
            _issue(
                "skill_description_missing",
                "SKILL.md",
                "frontmatter description must be a non-empty scalar",
            )
        )
    for marker in HATCH_PET_REQUIRED_SKILL_MARKERS:
        if marker not in source:
            issues.append(
                _issue(
                    "skill_capability_marker_missing",
                    "SKILL.md",
                    f"SKILL.md is missing required workflow marker {marker!r}",
                    marker=marker,
                )
            )
    return metadata, issues


def _inspect_python_script(path: Path, relative: str) -> list[dict[str, Any]]:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return [_issue("python_read_error", relative, str(exc))]
    if not source.strip():
        return [
            _issue(
                "empty_python_script",
                relative,
                "required Python script must not be empty",
            )
        ]
    try:
        tree = ast.parse(source, str(path))
    except (SyntaxError, ValueError) as exc:
        return [
            _issue(
                "python_compile_error",
                relative,
                str(exc),
                line=getattr(exc, "lineno", None),
                offset=getattr(exc, "offset", None),
            )
        ]
    contracts = HATCH_PET_SCRIPT_CONTRACTS.get(relative, {})
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    issues = []
    for function in contracts.get("functions", ()):
        if function not in functions:
            issues.append(
                _issue(
                    "python_contract_function_missing",
                    relative,
                    f"required workflow function {function!r} is missing",
                    function=function,
                )
            )
    for flag in contracts.get("flags", ()):
        if flag not in string_literals:
            issues.append(
                _issue(
                    "python_contract_flag_missing",
                    relative,
                    f"required CLI flag {flag!r} is missing",
                    flag=flag,
                )
            )
    return issues


def inspect_hatch_pet(candidate: Path) -> dict[str, Any]:
    missing = [
        relative
        for relative in HATCH_PET_REQUIRED_FILES
        if not (candidate / relative).is_file()
    ]
    issues = [
        _issue("missing_required_file", relative, "required file is missing")
        for relative in missing
    ]

    metadata: dict[str, str | None] = {"name": None, "description": None}
    metadata_issues: list[dict[str, Any]] = []
    if "SKILL.md" not in missing:
        metadata, metadata_issues = _frontmatter_metadata(candidate / "SKILL.md")
        issues.extend(metadata_issues)
    else:
        metadata_issues = [
            next(issue for issue in issues if issue["path"] == "SKILL.md")
        ]

    python_issues: list[dict[str, Any]] = []
    for relative in HATCH_PET_REQUIRED_PYTHON_SCRIPTS:
        if relative not in missing:
            python_issues.extend(_inspect_python_script(candidate / relative, relative))
    issues.extend(python_issues)

    issues_by_path: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        issues_by_path.setdefault(issue["path"], []).append(issue)
    capabilities: dict[str, dict[str, Any]] = {}
    for name, required_files in HATCH_PET_CAPABILITY_FILES.items():
        capability_issues = [
            issue
            for relative in required_files
            for issue in issues_by_path.get(relative, [])
        ]
        capabilities[name] = {
            "available": not capability_issues,
            "requiredFiles": list(required_files),
            "issues": capability_issues,
        }

    python_missing_issues = [
        issue
        for issue in issues
        if issue["path"] in HATCH_PET_REQUIRED_PYTHON_SCRIPTS
        and issue["code"] == "missing_required_file"
    ]
    python_validation_issues = [*python_missing_issues, *python_issues]
    validation = {
        "contractVersion": HATCH_PET_CONTRACT_VERSION,
        "valid": not issues,
        "issues": issues,
        "skillMetadata": {
            "valid": not metadata_issues,
            "expectedName": HATCH_PET_SKILL_NAME,
            "name": metadata["name"],
            "description": metadata["description"],
            "issues": metadata_issues,
        },
        "pythonScripts": {
            "valid": not python_validation_issues,
            "required": list(HATCH_PET_REQUIRED_PYTHON_SCRIPTS),
            "issues": python_validation_issues,
        },
    }
    return {
        "path": str(candidate),
        "exists": candidate.is_dir(),
        "available": validation["valid"],
        "missing": missing,
        "validation": validation,
        "capabilities": capabilities,
    }


def check_dependencies(
    codex_home: Path, hatch_pet_dir: Path | None = None
) -> dict[str, Any]:
    checked = [
        inspect_hatch_pet(candidate)
        for candidate in hatch_pet_candidates(codex_home, hatch_pet_dir)
    ]
    selected = next((item for item in checked if item["available"]), None)
    best = selected or next((item for item in checked if item["exists"]), checked[0])
    ok = selected is not None
    return {
        "ok": ok,
        "codexHome": str(codex_home),
        "dependencies": {
            "hatch-pet": {
                "available": ok,
                "path": selected["path"] if selected else None,
                "contract": {
                    "version": HATCH_PET_CONTRACT_VERSION,
                    "skillName": HATCH_PET_SKILL_NAME,
                    "requiredFiles": list(HATCH_PET_REQUIRED_FILES),
                    "requiredPythonScripts": list(HATCH_PET_REQUIRED_PYTHON_SCRIPTS),
                    "requiredSkillMarkers": list(HATCH_PET_REQUIRED_SKILL_MARKERS),
                    "scriptContracts": HATCH_PET_SCRIPT_CONTRACTS,
                },
                "requiredFiles": list(HATCH_PET_REQUIRED_FILES),
                "validation": best["validation"],
                "capabilities": best["capabilities"],
                "checked": checked,
            }
        },
        "message": (
            "hatch-pet is ready for ChromaPaw pet generation."
            if ok
            else "hatch-pet is required for visual generation and QA. Install a compatible "
            "hatch-pet skill, update Codex if it is provided by your distribution, or set "
            "CHROMAPAW_HATCH_PET_DIR to a compatible local skill directory. See "
            "dependencies.hatch-pet.validation.issues for the exact incompatibilities."
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
