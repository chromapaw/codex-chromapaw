#!/usr/bin/env python3
"""Run the repository checks that do not require a live Codex installation."""

from __future__ import annotations

import compileall
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
SKILLS = (
    "create-chromapaw-pet",
    "create-chromapaw-skin",
    "manage-chromapaw",
)


class ReleaseCheckError(RuntimeError):
    """Raised when repository release metadata is incomplete."""


def _load_json(relative: str) -> object:
    path = ROOT / relative
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCheckError(f"{relative} is not valid UTF-8 JSON: {exc}") from exc


def validate_repository() -> str:
    manifest = _load_json(".codex-plugin/plugin.json")
    if not isinstance(manifest, dict) or manifest.get("name") != ROOT.name:
        raise ReleaseCheckError("plugin name must match the repository directory")
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise ReleaseCheckError("plugin version must be semantic-version shaped")

    marketplace = _load_json(".agents/plugins/marketplace.json")
    if not isinstance(marketplace, dict) or marketplace.get("name") != "chromapaw":
        raise ReleaseCheckError("repository marketplace name must be chromapaw")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or not any(
        isinstance(plugin, dict) and plugin.get("name") == ROOT.name for plugin in plugins
    ):
        raise ReleaseCheckError("repository marketplace does not expose codex-chromapaw")

    for relative in (
        "schemas/pet.schema.json",
        "schemas/skin.schema.json",
        "schemas/theme-profile.schema.json",
        "schemas/windows-runtime-adapters.schema.json",
        "schemas/macos-runtime-adapters.schema.json",
        "runtime/windows-adapters.json",
        "runtime/macos-adapters.json",
    ):
        _load_json(relative)

    for skill in SKILLS:
        path = ROOT / "skills" / skill / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n") or f"name: {skill}\n" not in text:
            raise ReleaseCheckError(f"{path.relative_to(ROOT)} has invalid frontmatter")
        if "\ndescription:" not in text:
            raise ReleaseCheckError(f"{path.relative_to(ROOT)} has no description")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## {re.escape(version)}\b", changelog, flags=re.MULTILINE):
        raise ReleaseCheckError(f"CHANGELOG.md has no {version} release section")
    if not (ROOT / ".github" / "workflows" / "ci.yml").is_file():
        raise ReleaseCheckError(".github/workflows/ci.yml is missing")
    return version


def main() -> int:
    try:
        version = validate_repository()
    except (OSError, UnicodeError, ReleaseCheckError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not compileall.compile_dir(ROOT / "scripts", quiet=1):
        print("ERROR: script compilation failed", file=sys.stderr)
        return 1
    if not compileall.compile_dir(ROOT / "tests", quiet=1):
        print("ERROR: test compilation failed", file=sys.stderr)
        return 1

    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode
    print(f"Release checks passed for codex-chromapaw {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
