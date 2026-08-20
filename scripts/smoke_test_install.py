#!/usr/bin/env python3
"""Install ChromaPaw into an isolated CODEX_HOME and verify discovery."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from .check_dependencies import HATCH_PET_REQUIRED_PYTHON_SCRIPTS, HATCH_PET_SCRIPT_CONTRACTS
except ImportError:
    from check_dependencies import (  # type: ignore
        HATCH_PET_REQUIRED_PYTHON_SCRIPTS,
        HATCH_PET_SCRIPT_CONTRACTS,
    )


PLUGIN_NAME = "codex-chromapaw"
MARKETPLACE_NAME = "chromapaw"
ROOT = Path(__file__).resolve().parents[1]


class SmokeTestError(RuntimeError):
    """Raised when an isolated plugin installation step fails."""


def run(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise SmokeTestError(
            f"command timed out after 120 seconds: {' '.join(command)}"
        ) from exc
    if completed.returncode != 0:
        rendered = " ".join(command)
        raise SmokeTestError(
            f"command failed ({completed.returncode}): {rendered}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeTestError(f"{label} is not valid UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SmokeTestError(f"{label} must contain a JSON object: {path}")
    return value


def marketplace_plugin_root(marketplace_root: Path) -> Path:
    """Resolve the candidate plugin from the selected marketplace snapshot."""
    root_manifest = marketplace_root / ".codex-plugin" / "plugin.json"
    if root_manifest.is_file():
        return marketplace_root

    marketplace_file = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    marketplace = load_json_object(marketplace_file, "marketplace manifest")
    for plugin in marketplace.get("plugins", []):
        if not isinstance(plugin, dict) or plugin.get("name") != PLUGIN_NAME:
            continue
        source = plugin.get("source")
        if not isinstance(source, dict) or source.get("source") != "local":
            break
        relative = source.get("path")
        if not isinstance(relative, str) or not relative:
            break
        candidate = (marketplace_root / relative).resolve()
        try:
            candidate.relative_to(marketplace_root.resolve())
        except ValueError as exc:
            raise SmokeTestError("marketplace plugin source escapes its snapshot root") from exc
        if (candidate / ".codex-plugin" / "plugin.json").is_file():
            return candidate
        break
    raise SmokeTestError("selected marketplace snapshot does not expose the ChromaPaw plugin")


def plugin_version(plugin_root: Path, label: str) -> str:
    manifest = load_json_object(plugin_root / ".codex-plugin" / "plugin.json", label)
    if manifest.get("name") != PLUGIN_NAME:
        raise SmokeTestError(f"{label} does not describe {PLUGIN_NAME}")
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise SmokeTestError(f"{label} has no plugin version")
    return version


def installed_plugin_from_result(
    installation: subprocess.CompletedProcess[str],
    codex_home: Path,
    expected_version: str,
) -> tuple[Path, str]:
    try:
        result = json.loads(installation.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeTestError("plugin installation did not return valid JSON") from exc
    if not isinstance(result, dict):
        raise SmokeTestError("plugin installation result must be a JSON object")
    installed_path = result.get("installedPath")
    reported_version = result.get("version")
    if not isinstance(installed_path, str) or not isinstance(reported_version, str):
        raise SmokeTestError("plugin installation result omitted installedPath or version")
    plugin_root = Path(installed_path).resolve()
    try:
        plugin_root.relative_to(codex_home.resolve())
    except ValueError as exc:
        raise SmokeTestError("installed plugin path escapes the isolated CODEX_HOME") from exc
    installed_version = plugin_version(plugin_root, "installed plugin manifest")
    if reported_version != installed_version:
        raise SmokeTestError(
            "plugin installation result version does not match the installed manifest: "
            f"{reported_version} != {installed_version}"
        )
    if installed_version != expected_version:
        raise SmokeTestError(
            "installed plugin version does not match the selected marketplace snapshot: "
            f"{installed_version} != {expected_version}"
        )
    return plugin_root, installed_version


def write_mock_hatch_pet(codex_home: Path) -> Path:
    root = codex_home / "skills" / "hatch-pet"
    skill = root / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\n"
        "name: hatch-pet\n"
        "description: Isolated compatible fixture for the ChromaPaw smoke test.\n"
        "---\n\n"
        "# Hatch Pet\n\n"
        "Call load_workspace_dependencies before scripts. Build imagegen-jobs.json, "
        "then package spriteVersionNumber: 2.\n",
        encoding="utf-8",
    )
    for relative in HATCH_PET_REQUIRED_PYTHON_SCRIPTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = HATCH_PET_SCRIPT_CONTRACTS[relative]["flags"]
        path.write_text(
            "def main():\n"
            f"    flags = {flags!r}\n"
            "    return len(flags)\n",
            encoding="utf-8",
        )
    return root


def stage_local_marketplace(plugin_root: Path, staging_root: Path) -> Path:
    """Copy the root-plugin marketplace into a clean temporary snapshot."""
    plugin_root = plugin_root.expanduser().resolve()
    if not (plugin_root / ".codex-plugin" / "plugin.json").is_file():
        raise SmokeTestError(f"local plugin source has no manifest: {plugin_root}")
    marketplace_root = staging_root.expanduser().resolve()
    shutil.copytree(
        plugin_root,
        marketplace_root,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "__pycache__",
            "*.pyc",
            "build",
            "dist",
            "generated",
            "outputs",
            "work",
        ),
    )
    marketplace_file = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    if not marketplace_file.is_file():
        raise SmokeTestError(f"local plugin source has no marketplace manifest: {plugin_root}")
    return marketplace_root


def smoke_test(
    codex: str,
    source: str,
    ref: str | None,
    codex_home: Path,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)

    marketplace_command = [codex, "plugin", "marketplace", "add", source, "--json"]
    if ref:
        marketplace_command.extend(("--ref", ref))
    marketplace = run(marketplace_command, env)
    try:
        marketplace_result = json.loads(marketplace.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeTestError("marketplace installation did not return valid JSON") from exc
    if not isinstance(marketplace_result, dict) or not isinstance(
        marketplace_result.get("installedRoot"), str
    ):
        raise SmokeTestError("marketplace installation result omitted installedRoot")
    selected_root = marketplace_plugin_root(Path(marketplace_result["installedRoot"]).resolve())
    expected_version = plugin_version(selected_root, "selected marketplace plugin manifest")
    installation = run(
        [codex, "plugin", "add", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}", "--json"],
        env,
    )
    listing = run([codex, "plugin", "list"], env)
    if PLUGIN_NAME not in listing.stdout or "installed, enabled" not in listing.stdout:
        raise SmokeTestError("plugin list did not report ChromaPaw as installed and enabled")

    plugin_root, installed_version = installed_plugin_from_result(
        installation, codex_home, expected_version
    )
    dependency_script = plugin_root / "scripts" / "check_dependencies.py"
    if not dependency_script.is_file():
        raise SmokeTestError("installed plugin is missing scripts/check_dependencies.py")

    missing = subprocess.run(
        [sys.executable, str(dependency_script), "--codex-home", str(codex_home), "--json"],
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if missing.returncode != 1 or json.loads(missing.stdout).get("ok") is not False:
        raise SmokeTestError("dependency checker did not block a missing hatch-pet skill")

    mock_hatch_pet = write_mock_hatch_pet(codex_home)
    ready = run(
        [sys.executable, str(dependency_script), "--codex-home", str(codex_home), "--json"],
        env,
    )
    if json.loads(ready.stdout).get("ok") is not True:
        raise SmokeTestError("dependency checker did not accept a compatible hatch-pet layout")

    return {
        "ok": True,
        "codexHome": str(codex_home),
        "marketplace": MARKETPLACE_NAME,
        "plugin": PLUGIN_NAME,
        "version": installed_version,
        "pluginRoot": str(plugin_root),
        "mockHatchPet": str(mock_hatch_pet),
        "marketplaceResult": marketplace.stdout.strip(),
        "installResult": installation.stdout.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codex",
        default=shutil.which("codex") or "codex",
        help="Codex CLI executable",
    )
    parser.add_argument(
        "--source",
        default="chromapaw/codex-chromapaw",
        help="Local path or Git marketplace source",
    )
    parser.add_argument("--ref", default="main", help="Git ref; pass an empty value for local sources")
    parser.add_argument("--codex-home", type=Path, help="Keep and reuse this isolated home")
    parser.add_argument("--json", action="store_true", help="Write a JSON result")
    args = parser.parse_args()

    try:
        with ExitStack() as stack:
            work_root = ROOT / "work"
            work_root.mkdir(exist_ok=True)
            if args.codex_home:
                home = args.codex_home.expanduser().resolve()
                home.mkdir(parents=True, exist_ok=True)
            else:
                temporary = stack.enter_context(
                    tempfile.TemporaryDirectory(prefix="chromapaw-codex-home-", dir=work_root)
                )
                home = Path(temporary).resolve()

            source = args.source
            ref = args.ref or None
            local_source = Path(source).expanduser()
            if local_source.is_dir():
                staging = Path(
                    stack.enter_context(
                        tempfile.TemporaryDirectory(
                            prefix="chromapaw-local-marketplace-", dir=work_root
                        )
                    )
                )
                source = str(stage_local_marketplace(local_source, staging))
                ref = None
            result = smoke_test(args.codex, source, ref, home)
    except (OSError, SmokeTestError, json.JSONDecodeError) as exc:
        result = {"ok": False, "error": str(exc)}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"OK: installed {PLUGIN_NAME}@{MARKETPLACE_NAME} in an isolated CODEX_HOME")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
