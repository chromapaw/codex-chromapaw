#!/usr/bin/env python3
"""Run the repository checks that do not require a live Codex installation."""

from __future__ import annotations

import compileall
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
SKILLS = (
    "create-chromapaw-pet",
    "create-chromapaw-skin",
    "manage-chromapaw",
)
SCHEMA_CONTRACTS = (
    ("schemas/pet.schema.json", "tests/fixtures/schema/pet.json"),
    ("schemas/skin.schema.json", "tests/fixtures/schema/skin.json"),
    (
        "schemas/theme-profile.schema.json",
        "tests/fixtures/schema/theme-profile.json",
    ),
    (
        "schemas/windows-runtime-adapters.schema.json",
        "runtime/windows-adapters.json",
    ),
    (
        "schemas/macos-runtime-adapters.schema.json",
        "runtime/macos-adapters.json",
    ),
)
REPOSITORY_POLICY_FILES = (
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SUPPORT.md",
    "docs/GITHUB_MAINTAINER_SETUP.md",
    ".github/CODEOWNERS",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/dependabot.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/compatibility_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/macos-enhanced.yml",
    ".github/workflows/release.yml",
)
PINNED_ACTION = re.compile(r"^[^\s@]+/[^\s@]+@[0-9a-f]{40}$")


class ReleaseCheckError(RuntimeError):
    """Raised when repository release metadata is incomplete."""


def _load_json(relative: str) -> object:
    path = ROOT / relative
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCheckError(f"{relative} is not valid UTF-8 JSON: {exc}") from exc


def _json_path(parts: object) -> str:
    rendered = "$"
    for part in parts:
        rendered += f"[{part}]" if isinstance(part, int) else f".{part}"
    return rendered


def _validate_schema_value(
    schema: object,
    instance: object,
    *,
    schema_name: str,
    instance_name: str,
) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ReleaseCheckError(f"{schema_name} is not a valid JSON Schema: {exc.message}") from exc
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        raise ReleaseCheckError(
            f"{instance_name} violates {schema_name} at "
            f"{_json_path(error.absolute_path)}: {error.message}"
        )


def validate_schema_contracts() -> None:
    for schema_name, instance_name in SCHEMA_CONTRACTS:
        _validate_schema_value(
            _load_json(schema_name),
            _load_json(instance_name),
            schema_name=schema_name,
            instance_name=instance_name,
        )


def validate_repository_policies() -> None:
    for relative in REPOSITORY_POLICY_FILES:
        if not (ROOT / relative).is_file():
            raise ReleaseCheckError(f"{relative} is missing")

    github_root = ROOT / ".github"
    yaml_paths = sorted((*github_root.rglob("*.yml"), *github_root.rglob("*.yaml")))
    for path in yaml_paths:
        relative = path.relative_to(ROOT)
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ReleaseCheckError(f"{relative} is invalid YAML: {exc}") from exc
        if not isinstance(value, dict):
            raise ReleaseCheckError(f"{relative} must contain a YAML mapping")

    for workflow in sorted((github_root / "workflows").glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        for action in re.findall(r"^\s*uses:\s*([^\s#]+)", text, flags=re.MULTILINE):
            if action.startswith("./") or action.startswith("docker://"):
                continue
            if not PINNED_ACTION.fullmatch(action):
                raise ReleaseCheckError(
                    f"{workflow.relative_to(ROOT)} uses an unpinned action: {action}"
                )

    release_workflow = (github_root / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    for marker in (
        "scripts/release_check.py",
        "scripts/smoke_test_install.py",
        "actions/setup-node@",
        "@openai/codex@0.144.2",
        "sbom-action@",
        "gh release create",
    ):
        if marker not in release_workflow:
            raise ReleaseCheckError(f"release workflow is missing {marker}")


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
    if not isinstance(plugins, list):
        raise ReleaseCheckError("repository marketplace plugins must be a list")
    repository_plugin = next(
        (
            plugin
            for plugin in plugins
            if isinstance(plugin, dict) and plugin.get("name") == ROOT.name
        ),
        None,
    )
    if repository_plugin is None:
        raise ReleaseCheckError("repository marketplace does not expose codex-chromapaw")
    if repository_plugin.get("source") != {"source": "local", "path": "."}:
        raise ReleaseCheckError(
            "repository marketplace must resolve codex-chromapaw from its selected snapshot root"
        )

    validate_schema_contracts()
    validate_repository_policies()

    for skill in SKILLS:
        path = ROOT / "skills" / skill / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n") or f"name: {skill}\n" not in text:
            raise ReleaseCheckError(f"{path.relative_to(ROOT)} has invalid frontmatter")
        if "\ndescription:" not in text:
            raise ReleaseCheckError(f"{path.relative_to(ROOT)} has no description")
        closing = text.find("\n---", 4)
        if closing < 0:
            raise ReleaseCheckError(f"{path.relative_to(ROOT)} has unclosed frontmatter")
        try:
            frontmatter = yaml.safe_load(text[4:closing])
        except yaml.YAMLError as exc:
            raise ReleaseCheckError(
                f"{path.relative_to(ROOT)} has invalid YAML frontmatter: {exc}"
            ) from exc
        if not isinstance(frontmatter, dict) or set(frontmatter) - {
            "name",
            "description",
            "license",
            "allowed-tools",
            "metadata",
        }:
            raise ReleaseCheckError(
                f"{path.relative_to(ROOT)} has unsupported frontmatter fields"
            )
        agent = ROOT / "skills" / skill / "agents" / "openai.yaml"
        if agent.is_file():
            try:
                agent_value = yaml.safe_load(agent.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise ReleaseCheckError(
                    f"{agent.relative_to(ROOT)} is invalid YAML: {exc}"
                ) from exc
            if not isinstance(agent_value, dict) or not isinstance(
                agent_value.get("interface"), dict
            ):
                raise ReleaseCheckError(
                    f"{agent.relative_to(ROOT)} must contain interface metadata"
                )

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if len(re.findall(r"^## Unreleased\s*$", changelog, flags=re.MULTILINE)) != 1:
        raise ReleaseCheckError("CHANGELOG.md must contain exactly one Unreleased section")
    release_version = version.split("+", 1)[0]
    if not re.search(rf"^## {re.escape(release_version)}\b", changelog, flags=re.MULTILINE):
        raise ReleaseCheckError(f"CHANGELOG.md has no {release_version} release section")
    for relative in (
        "package.json",
        "package-lock.json",
        "scripts/macos_enhanced_test.py",
        "scripts/macos_visual_smoke.mjs",
        "tests/fixtures/macos-harness/index.html",
        "tests/fixtures/macos-harness/pet-overlay.html",
        "requirements-dev.txt",
    ):
        if not (ROOT / relative).is_file():
            raise ReleaseCheckError(f"{relative} is missing")
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
