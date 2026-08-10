#!/usr/bin/env python3
"""Install ChromaPaw into an isolated CODEX_HOME and verify discovery."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PLUGIN_NAME = "codex-chromapaw"
MARKETPLACE_NAME = "chromapaw"


class SmokeTestError(RuntimeError):
    """Raised when an isolated plugin installation step fails."""


def run(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
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
    for relative in (
        "SKILL.md",
        "scripts/prepare_pet_run.py",
        "scripts/assemble_extended_atlas.py",
        "scripts/validate_atlas.py",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# isolated smoke-test fixture\n", encoding="utf-8")
    return root


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
        if args.codex_home:
            home = args.codex_home.expanduser().resolve()
            home.mkdir(parents=True, exist_ok=True)
            result = smoke_test(args.codex, args.source, args.ref or None, home)
        else:
            with tempfile.TemporaryDirectory(prefix="chromapaw-codex-home-") as temporary:
                result = smoke_test(
                    args.codex,
                    args.source,
                    args.ref or None,
                    Path(temporary).resolve(),
                )
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
