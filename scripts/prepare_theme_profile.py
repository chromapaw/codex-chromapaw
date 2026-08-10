#!/usr/bin/env python3
"""Create a validated semantic theme profile from Codex image analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .theme_profile import normalize_theme_profile, sha256_file
except ImportError:
    from theme_profile import normalize_theme_profile, sha256_file  # type: ignore


SUPPORTED_IMAGES = {".png", ".webp", ".jpg", ".jpeg"}


def build_profile(args: argparse.Namespace) -> dict[str, object]:
    image = args.image.expanduser().resolve()
    if not image.is_file():
        raise ValueError(f"reference image does not exist: {image}")
    if image.suffix.lower() not in SUPPORTED_IMAGES:
        raise ValueError("reference image must be PNG, WebP, JPG, or JPEG")
    return normalize_theme_profile(
        {
            "schemaVersion": 1,
            "referenceSha256": sha256_file(image),
            "sourceKind": args.source_kind,
            "themeName": args.theme_name,
            "visualStyle": args.visual_style,
            "mood": args.mood,
            "identityCues": args.identity_cue,
            "motifs": args.motif,
            "avoidElements": args.avoid_element,
            "depthPlan": {
                "atmosphere": args.atmosphere,
                "distant": args.distant,
                "midground": args.midground,
                "foreground": args.foreground,
            },
            "safeZoneGuidance": args.safe_zone_guidance,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument(
        "--source-kind",
        required=True,
        choices=("full-environment", "subject", "texture", "abstract", "logo"),
    )
    parser.add_argument("--theme-name", required=True)
    parser.add_argument("--visual-style", required=True)
    parser.add_argument("--mood", required=True)
    parser.add_argument("--identity-cue", action="append", required=True)
    parser.add_argument("--motif", action="append", required=True)
    parser.add_argument("--avoid-element", action="append", default=[])
    parser.add_argument("--atmosphere", required=True)
    parser.add_argument("--distant", required=True)
    parser.add_argument("--midground", required=True)
    parser.add_argument("--foreground", required=True)
    parser.add_argument("--safe-zone-guidance", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        profile = build_profile(args)
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / "theme-profile.json"
        if output.exists() and not args.force:
            raise ValueError(f"theme profile already exists: {output}; pass --force to replace it")
        output.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
