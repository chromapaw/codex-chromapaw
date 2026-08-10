#!/usr/bin/env python3
"""Discover and preflight macOS Codex app bundles without enabling skin activation."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import plistlib
import sys
from pathlib import Path
from typing import Any

try:
    from .validate_skin_package import validate_package
except ImportError:
    from validate_skin_package import validate_package  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADAPTERS = ROOT / "runtime" / "macos-adapters.json"


class MacCompatibilityFailure(RuntimeError):
    """Raised when a macOS bundle or compatibility registry is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_adapters(path: Path = DEFAULT_ADAPTERS) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MacCompatibilityFailure(f"macOS adapter registry cannot be read: {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise MacCompatibilityFailure("macOS adapter registry must be a schemaVersion 1 object")
    if (
        data.get("platform") != "darwin"
        or data.get("mode") != "compatibility-probe"
        or data.get("activationImplemented") is not False
    ):
        raise MacCompatibilityFailure(
            "macOS registry must remain a compatibility probe until live activation is implemented"
        )
    adapters = data.get("adapters")
    if not isinstance(adapters, list):
        raise MacCompatibilityFailure("macOS adapter registry adapters must be an array")
    seen_ids: set[str] = set()
    seen_targets: set[tuple[str, str, str]] = set()
    required = {
        "id",
        "appVersion",
        "bundleIdentifier",
        "executableName",
        "activationEnabled",
        "testedTarget",
    }
    for adapter in adapters:
        if not isinstance(adapter, dict) or set(adapter) != required:
            raise MacCompatibilityFailure("every macOS adapter must contain the exact probe fields")
        if adapter["activationEnabled"] is not False:
            raise MacCompatibilityFailure("macOS activation cannot be enabled in probe-only mode")
        if not all(isinstance(adapter[field], str) and adapter[field] for field in required - {"activationEnabled"}):
            raise MacCompatibilityFailure("macOS adapter string fields must be non-empty")
        if adapter["id"] in seen_ids:
            raise MacCompatibilityFailure(f"duplicate macOS adapter id: {adapter['id']}")
        target = (
            adapter["appVersion"],
            adapter["bundleIdentifier"],
            adapter["executableName"],
        )
        if target in seen_targets:
            raise MacCompatibilityFailure("duplicate macOS adapter target")
        seen_ids.add(adapter["id"])
        seen_targets.add(target)
    return data


def inspect_app_bundle(app: Path) -> dict[str, Any]:
    app = app.expanduser().resolve()
    if not app.is_dir() or app.suffix.lower() != ".app":
        raise MacCompatibilityFailure(f"macOS application bundle does not exist: {app}")
    info_path = app / "Contents" / "Info.plist"
    try:
        with info_path.open("rb") as stream:
            info = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise MacCompatibilityFailure(f"Info.plist cannot be read: {exc}") from exc
    if not isinstance(info, dict):
        raise MacCompatibilityFailure("Info.plist must contain a dictionary")
    bundle_id = info.get("CFBundleIdentifier")
    executable_name = info.get("CFBundleExecutable")
    short_version = info.get("CFBundleShortVersionString")
    build_version = info.get("CFBundleVersion")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise MacCompatibilityFailure("Info.plist is missing CFBundleIdentifier")
    if not isinstance(executable_name, str) or not executable_name:
        raise MacCompatibilityFailure("Info.plist is missing CFBundleExecutable")
    app_version = short_version if isinstance(short_version, str) and short_version else build_version
    if not isinstance(app_version, str) or not app_version:
        raise MacCompatibilityFailure("Info.plist is missing an application version")
    executable = (app / "Contents" / "MacOS" / executable_name).resolve()
    if not executable.is_file():
        raise MacCompatibilityFailure(f"bundle executable does not exist: {executable}")
    resources = app / "Contents" / "Resources"
    frameworks = app / "Contents" / "Frameworks"
    electron_signals = {
        "appAsar": (resources / "app.asar").is_file(),
        "electronFramework": any(
            candidate.name == "Electron Framework.framework"
            for candidate in frameworks.glob("*.framework")
        )
        if frameworks.is_dir()
        else False,
    }
    return {
        "app": str(app),
        "infoPlist": str(info_path),
        "bundleIdentifier": bundle_id,
        "appVersion": app_version,
        "buildVersion": build_version if isinstance(build_version, str) else None,
        "executableName": executable_name,
        "executable": str(executable),
        "executableHash": sha256_file(executable),
        "electronSignals": electron_signals,
    }


def select_adapter(bundle: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any] | None:
    for adapter in registry["adapters"]:
        if (
            adapter["appVersion"] == bundle["appVersion"]
            and adapter["bundleIdentifier"] == bundle["bundleIdentifier"]
            and adapter["executableName"] == bundle["executableName"]
        ):
            return adapter
    return None


def candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.environ.get("CHROMAPAW_MACOS_CODEX_APP")
    if explicit:
        candidates.append(Path(explicit))
    for base in (Path("/Applications"), Path.home() / "Applications"):
        candidates.extend((base / name) for name in ("ChatGPT.app", "Codex.app"))
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates:
        key = str(candidate.expanduser()).casefold()
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def discover_apps(registry_path: Path = DEFAULT_ADAPTERS) -> list[dict[str, Any]]:
    registry = load_adapters(registry_path)
    results = []
    for candidate in candidate_paths():
        if not candidate.expanduser().is_dir():
            continue
        try:
            bundle = inspect_app_bundle(candidate)
            adapter = select_adapter(bundle, registry)
            results.append(
                {
                    **bundle,
                    "adapterId": adapter["id"] if adapter else None,
                    "activationEnabled": False,
                    "reason": (
                        "macOS activation is not implemented or live-verified"
                        if adapter
                        else "no exact macOS compatibility adapter exists"
                    ),
                }
            )
        except MacCompatibilityFailure as exc:
            results.append(
                {
                    "app": str(candidate.expanduser()),
                    "activationEnabled": False,
                    "reason": str(exc),
                }
            )
    return results


def build_preflight(
    package: Path,
    app: Path,
    registry_path: Path = DEFAULT_ADAPTERS,
    *,
    require_darwin: bool = True,
) -> dict[str, Any]:
    if require_darwin and sys.platform != "darwin":
        raise MacCompatibilityFailure("macOS compatibility preflight must run on macOS")
    package = package.expanduser().resolve()
    errors = validate_package(package)
    if errors:
        raise MacCompatibilityFailure("skin package validation failed: " + "; ".join(errors))
    registry_path = registry_path.expanduser().resolve()
    registry = load_adapters(registry_path)
    bundle = inspect_app_bundle(app)
    adapter = select_adapter(bundle, registry)
    manifest = json.loads((package / "skin.json").read_text(encoding="utf-8"))
    return {
        "ok": True,
        "platform": "darwin",
        "mode": "compatibility-probe",
        "hostEligible": sys.platform == "darwin",
        "generationSupported": True,
        "activationImplemented": False,
        "activationEnabled": False,
        "reason": (
            "exact adapter found, but macOS activation is not implemented or live-verified"
            if adapter
            else "no exact macOS adapter exists; collect this report on a Mac before implementation"
        ),
        "adapterId": adapter["id"] if adapter else None,
        "adapterRegistry": str(registry_path),
        "adapterRegistryHash": sha256_file(registry_path),
        "bundle": bundle,
        "package": str(package),
        "packageId": manifest.get("id"),
        "packageSchemaVersion": manifest.get("schemaVersion"),
        "semanticProfilePresent": isinstance(manifest.get("semanticProfile"), dict),
        "applicationFilesWillBeModified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapters", type=Path, default=DEFAULT_ADAPTERS)
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("discover", help="Discover candidate macOS app bundles")
    preflight = subparsers.add_parser("preflight", help="Collect a read-only compatibility report")
    preflight.add_argument("package", type=Path)
    preflight.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "discover":
            result = {
                "ok": True,
                "platform": sys.platform,
                "hostEligible": sys.platform == "darwin",
                "activationImplemented": False,
                "candidates": discover_apps(args.adapters),
            }
        else:
            result = build_preflight(args.package, args.app, args.adapters)
    except (MacCompatibilityFailure, OSError, ValueError) as exc:
        result = {"ok": False, "command": args.command, "error": str(exc)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get("reason") or result.get("error") or "OK")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
