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


def find_installed_plugin(codex_home: Path) -> Path:
    for manifest in codex_home.rglob("plugin.json"):
        if manifest.parent.name != ".codex-plugin":
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if data.get("name") == PLUGIN_NAME:
            return manifest.parent.parent
    raise SmokeTestError("installed ChromaPaw plugin manifest was not found")


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
    """Create a temporary marketplace whose plugin source is the current worktree."""
    plugin_root = plugin_root.expanduser().resolve()
    if not (plugin_root / ".codex-plugin" / "plugin.json").is_file():
        raise SmokeTestError(f"local plugin source has no manifest: {plugin_root}")
    marketplace_root = staging_root.expanduser().resolve()
    staged_plugin = marketplace_root / "plugins" / PLUGIN_NAME
    shutil.copytree(
        plugin_root,
        staged_plugin,
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
    marketplace_file.parent.mkdir(parents=True)
    marketplace_file.write_text(
        json.dumps(
            {
                "name": MARKETPLACE_NAME,
                "interface": {"displayName": "ChromaPaw local smoke test"},
                "plugins": [
                    {
                        "name": PLUGIN_NAME,
                        "source": {
                            "source": "local",
                            "path": f"./plugins/{PLUGIN_NAME}",
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Creativity",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
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
    installation = run(
        [codex, "plugin", "add", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}", "--json"],
        env,
    )
    listing = run([codex, "plugin", "list"], env)
    if PLUGIN_NAME not in listing.stdout or "installed, enabled" not in listing.stdout:
        raise SmokeTestError("plugin list did not report ChromaPaw as installed and enabled")

    plugin_root = find_installed_plugin(codex_home)
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
