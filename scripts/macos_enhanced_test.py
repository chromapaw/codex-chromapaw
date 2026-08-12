#!/usr/bin/env python3
"""Run real-macOS package, lifecycle, renderer, and screenshot compatibility gates."""

from __future__ import annotations

import argparse
import json
import platform
import plistlib
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

try:
    from .build_skin_package import build_package
    from .install_pet import install_pet
    from .macos_compat import build_preflight
    from .prepare_skin_request import build_request
    from .prepare_theme_profile import build_profile
    from .skin_package import contrast_ratio
    from .theme_profile import sha256_file
    from .validate_skin_package import validate_package
    from .pet_package import validate_pet_package
except ImportError:
    from build_skin_package import build_package  # type: ignore
    from install_pet import install_pet  # type: ignore
    from macos_compat import build_preflight  # type: ignore
    from prepare_skin_request import build_request  # type: ignore
    from prepare_theme_profile import build_profile  # type: ignore
    from skin_package import contrast_ratio  # type: ignore
    from theme_profile import sha256_file  # type: ignore
    from validate_skin_package import validate_package  # type: ignore
    from pet_package import validate_pet_package  # type: ignore


ROOT = Path(__file__).resolve().parents[1]


class EnhancedMacTestFailure(RuntimeError):
    """Raised when an enhanced compatibility gate fails."""


def _write_reference(path: Path) -> None:
    image = Image.new("RGB", (1600, 1000), (5, 21, 54))
    draw = ImageDraw.Draw(image)
    for y in range(image.height):
        progress = y / max(1, image.height - 1)
        color = (
            round(5 + 6 * progress),
            round(21 + 35 * progress),
            round(54 + 68 * progress),
        )
        draw.line((0, y, image.width, y), fill=color)
    for offset in range(-400, 1700, 120):
        draw.line((offset, 1000, offset + 720, 0), fill=(15, 76, 145), width=2)
    draw.ellipse((510, 90, 1090, 500), fill=(4, 25, 67), outline=(18, 102, 185), width=3)
    draw.ellipse((650, 190, 950, 370), fill=(7, 42, 96), outline=(37, 160, 215), width=3)
    draw.rounded_rectangle((390, 650, 1210, 980), radius=36, fill=(7, 41, 84), outline=(45, 174, 223), width=3)
    for x in range(450, 1160, 32):
        draw.line((x, 700, x, 930), fill=(20, 104, 160), width=1)
    for y in range(700, 940, 24):
        draw.line((430, y, 1170, y), fill=(20, 104, 160), width=1)
    draw.polygon(((760, 980), (840, 980), (800, 680)), fill=(65, 208, 239))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _build_skin(work: Path) -> tuple[Path, dict[str, Any]]:
    reference = work / "source" / "macos-digital-stage.png"
    _write_reference(reference)
    profile = build_profile(
        Namespace(
            image=reference,
            source_kind="full-environment",
            theme_name="macOS Digital Stage",
            visual_style="dimensional blue technology illustration",
            mood="focused and calm",
            identity_cue=["deep blue layered stage", "cyan grid light"],
            motif=["architectural frame", "digital grid", "soft cyan light"],
            avoid_element=["beach", "coral", "unrelated logos"],
            atmosphere="Deep blue ambient haze with restrained cyan illumination.",
            distant="A framed dark technology wall with subtle depth.",
            midground="A luminous digital platform behind the reading zone.",
            foreground="Low-detail framing around the outer safe edges.",
            safe_zone_guidance="Keep the central content and lower composer regions low detail.",
        )
    )
    request_dir = work / "skin-run"
    request_dir.mkdir(parents=True, exist_ok=True)
    profile_path = request_dir / "theme-profile.json"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    request = build_request(
        Namespace(
            image=reference,
            artwork=reference,
            theme_profile=profile_path,
            name="macOS Enhanced Test Skin",
            id="macos-enhanced-test-skin",
            description="A generated skin used by the real-macOS enhanced compatibility harness.",
            mode="adaptive",
            scene_brief=None,
            author="ChromaPaw deterministic CI fixture",
            license="CC0-1.0",
            source_url=None,
        )
    )
    request_path = request_dir / "skin-request.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    package = work / "skin-package"
    manifest = build_package(request_path, package, force=True)
    errors = validate_package(package)
    if errors:
        raise EnhancedMacTestFailure("generated skin failed validation: " + "; ".join(errors))
    return package, manifest


def _write_pet_atlas(path: Path, accent: tuple[int, int, int], label: str) -> None:
    atlas = Image.new("RGBA", (1536, 2288), (0, 0, 0, 0))
    draw = ImageDraw.Draw(atlas)
    for row in range(11):
        for column in range(8):
            left, top = column * 192, row * 208
            bounce = (column % 4) * 2
            draw.ellipse((left + 45, top + 151 - bounce, left + 147, top + 181 - bounce), fill=(0, 0, 0, 48))
            draw.rounded_rectangle((left + 54, top + 66 - bounce, left + 138, top + 158 - bounce), radius=30, fill=(*accent, 255), outline=(7, 20, 34, 255), width=5)
            draw.ellipse((left + 59, top + 26 - bounce, left + 133, top + 103 - bounce), fill=(240, 247, 250, 255), outline=(7, 20, 34, 255), width=5)
            draw.ellipse((left + 73, top + 50 - bounce, left + 87, top + 65 - bounce), fill=(7, 20, 34, 255))
            draw.ellipse((left + 105, top + 50 - bounce, left + 119, top + 65 - bounce), fill=(7, 20, 34, 255))
            draw.arc((left + 79, top + 61 - bounce, left + 113, top + 84 - bounce), 8, 172, fill=(7, 20, 34, 255), width=3)
            draw.line((left + 63, top + 101 - bounce, left + 35, top + 125 - bounce), fill=(7, 20, 34, 255), width=7)
            draw.line((left + 130, top + 101 - bounce, left + 157, top + 122 - bounce), fill=(7, 20, 34, 255), width=7)
            draw.rounded_rectangle((left + 61, top + 148 - bounce, left + 86, top + 180 - bounce), radius=8, fill=(7, 20, 34, 255))
            draw.rounded_rectangle((left + 106, top + 148 - bounce, left + 131, top + 180 - bounce), radius=8, fill=(7, 20, 34, 255))
            if column == 0 and row == 0:
                draw.text((left + 79, top + 112), label, fill=(255, 255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(path, optimize=True)


def _make_pet(package: Path, accent: tuple[int, int, int], label: str) -> None:
    package.mkdir(parents=True, exist_ok=True)
    sheet = package / "atlas.png"
    _write_pet_atlas(sheet, accent, label)
    (package / "pet.json").write_text(
        json.dumps(
            {
                "id": "macos-ci-pet",
                "displayName": "macOS CI Pet",
                "description": "A deterministic v2 pet for macOS lifecycle and overlay checks.",
                "spriteVersionNumber": 2,
                "spritesheetPath": "atlas.png",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    errors, _ = validate_pet_package(package)
    if errors:
        raise EnhancedMacTestFailure("pet fixture failed validation: " + "; ".join(errors))


def _exercise_pet_lifecycle(work: Path) -> tuple[Path, dict[str, Any]]:
    old_package = work / "pet-old"
    new_package = work / "pet-new"
    _make_pet(old_package, (58, 142, 190), "1")
    _make_pet(new_package, (32, 201, 168), "2")
    codex_home = work / "codex-home"
    first = install_pet(old_package, codex_home)
    destination = Path(first["destination"])
    old_hash = sha256_file(destination / "atlas.png")
    replacement = install_pet(new_package, codex_home, replace=True, backup_label="old")
    new_hash = sha256_file(destination / "atlas.png")
    if old_hash == new_hash:
        raise EnhancedMacTestFailure("pet replacement did not change the installed atlas")
    backup = Path(str(replacement["backup"]))
    restored = install_pet(backup, codex_home, replace=True, backup_label="before-restore")
    restored_hash = sha256_file(destination / "atlas.png")
    if restored_hash != old_hash:
        raise EnhancedMacTestFailure("pet restore did not recover the original atlas")
    errors, package = validate_pet_package(destination)
    if errors or package is None:
        raise EnhancedMacTestFailure("restored pet failed validation: " + "; ".join(errors))
    return destination, {
        "ok": True,
        "codexHome": str(codex_home),
        "firstInstall": first,
        "replacement": replacement,
        "restore": restored,
        "hashes": {"old": old_hash, "new": new_hash, "restored": restored_hash},
        "restoredPackageValid": True,
    }


def _make_app_bundle(work: Path) -> tuple[Path, Path]:
    app = work / "Codex.app"
    contents = app / "Contents"
    executable = contents / "MacOS" / "Codex"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    (contents / "Resources").mkdir(parents=True)
    (contents / "Resources" / "app.asar").write_bytes(b"chromapaw-macos-enhanced-fixture")
    (contents / "Frameworks" / "Electron Framework.framework").mkdir(parents=True)
    info = {
        "CFBundleIdentifier": "com.openai.codex.chromapaw-fixture",
        "CFBundleExecutable": "Codex",
        "CFBundleShortVersionString": "26.999.1",
        "CFBundleVersion": "9991",
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    registry = work / "macos-adapters.json"
    registry.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "platform": "darwin",
                "mode": "compatibility-probe",
                "activationImplemented": False,
                "adapters": [
                    {
                        "id": "macos-enhanced-ci-probe",
                        "appVersion": "26.999.1",
                        "bundleIdentifier": "com.openai.codex.chromapaw-fixture",
                        "executableName": "Codex",
                        "activationEnabled": False,
                        "testedTarget": "GitHub-hosted macOS deterministic Electron-shaped fixture",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return app, registry


def _screenshot_evidence(visual_report: dict[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for mode, result in visual_report["modes"].items():
        mode_evidence = {}
        for kind, screenshot_path in result["screenshots"].items():
            image = Image.open(screenshot_path)
            image.load()
            rgb = image.convert("RGB")
            extrema = rgb.getextrema()
            if not any(high > low for low, high in extrema):
                raise EnhancedMacTestFailure(f"{mode} {kind} screenshot is blank")
            item: dict[str, Any] = {
                "path": str(Path(screenshot_path).resolve()),
                "dimensions": list(image.size),
                "mode": image.mode,
                "sha256": sha256_file(Path(screenshot_path)),
                "nonBlank": True,
            }
            if kind == "overlay":
                alpha = image.convert("RGBA").getchannel("A")
                alpha_extrema = alpha.getextrema()
                histogram = alpha.histogram()
                total = image.width * image.height
                transparent_fraction = histogram[0] / total
                if alpha_extrema[0] != 0 or alpha_extrema[1] != 255 or transparent_fraction < 0.35:
                    raise EnhancedMacTestFailure(
                        f"{mode} overlay screenshot lacks a transparent desktop region"
                    )
                item["alphaExtrema"] = list(alpha_extrema)
                item["transparentPixelFraction"] = round(transparent_fraction, 4)
            mode_evidence[kind] = item
        evidence[mode] = mode_evidence
    return evidence


def run(output: Path, *, force: bool, allow_non_darwin: bool) -> dict[str, Any]:
    output = output.expanduser().resolve()
    if output.exists():
        if not force:
            raise EnhancedMacTestFailure(f"output already exists: {output}; pass --force")
        if output == ROOT or ROOT not in output.parents:
            raise EnhancedMacTestFailure("refusing to replace output outside the repository")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    host_is_darwin = sys.platform == "darwin"
    if not host_is_darwin and not allow_non_darwin:
        raise EnhancedMacTestFailure("enhanced macOS test must run on macOS")

    skin_package, skin_manifest = _build_skin(output)
    pet_package, pet_lifecycle = _exercise_pet_lifecycle(output)
    app, registry = _make_app_bundle(output)
    preflight = build_preflight(
        skin_package,
        app,
        registry,
        require_darwin=not allow_non_darwin,
    )
    if preflight["activationImplemented"] or preflight["activationEnabled"]:
        raise EnhancedMacTestFailure("macOS probe unexpectedly enabled activation")

    visual_dir = output / "visual"
    command = [
        "node",
        str(ROOT / "scripts" / "macos_visual_smoke.mjs"),
        "--root",
        str(ROOT),
        "--skin-package",
        str(skin_package),
        "--pet-package",
        str(pet_package),
        "--output",
        str(visual_dir),
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise EnhancedMacTestFailure(
            "visual smoke test failed: " + (completed.stderr.strip() or completed.stdout.strip())
        )
    visual_report = json.loads((visual_dir / "visual-report.json").read_text(encoding="utf-8"))
    screenshots = _screenshot_evidence(visual_report)

    ui_palettes = json.loads(
        (skin_package / "qa" / "skin-studio-report.json").read_text(encoding="utf-8")
    )["uiPalettes"]
    palette_contrast = {
        mode: {
            "sidePanelPrimary": round(
                contrast_ratio(palette["sidePanelSurface"], palette["sidePanelText"]), 2
            ),
            "sidePanelSecondary": round(
                contrast_ratio(
                    palette["sidePanelSurface"], palette["sidePanelSecondaryText"]
                ),
                2,
            ),
            "notificationTitle": round(
                contrast_ratio(
                    palette["notificationSurface"], palette["notificationText"]
                ),
                2,
            ),
        }
        for mode, palette in ui_palettes.items()
    }
    report = {
        "schemaVersion": 1,
        "ok": True,
        "host": {
            "platform": sys.platform,
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "macVersion": platform.mac_ver()[0] or None,
            "python": platform.python_version(),
            "isDarwin": host_is_darwin,
        },
        "coverage": {
            "realMacOSHost": host_is_darwin,
            "realSkinGeneration": True,
            "realPetFilesystemLifecycle": True,
            "realBundleMetadataProbe": True,
            "simulatedCodexRenderer": True,
            "realCodexApplication": False,
            "realCodexLogin": False,
            "liveSkinActivation": False,
        },
        "skin": {
            "package": str(skin_package),
            "id": skin_manifest["id"],
            "validation": "pass",
            "variantCount": len(skin_manifest["variants"]),
            "paletteContrast": palette_contrast,
        },
        "pet": pet_lifecycle,
        "macosProbe": preflight,
        "visual": visual_report,
        "screenshots": screenshots,
        "limitations": [
            "The harness is Electron-shaped but is not the signed, logged-in Codex application.",
            "Passing this suite does not enable or claim live macOS skin activation.",
            "A real Codex installation is still required for final main-window and pet-overlay acceptance.",
        ],
    }
    report_path = output / "macos-enhanced-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "report": str(report_path), "output": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "macos-enhanced")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--allow-non-darwin",
        action="store_true",
        help="Developer-only renderer check; reports that no real macOS host was used.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = run(
            args.output,
            force=args.force,
            allow_non_darwin=args.allow_non_darwin,
        )
    except (EnhancedMacTestFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["report"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
