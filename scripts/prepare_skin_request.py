#!/usr/bin/env python3
"""Normalize one reference image into a ChromaPaw Skin Studio request."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

try:
    from .theme_profile import load_theme_profile, sha256_file
except ImportError:
    from theme_profile import load_theme_profile, sha256_file  # type: ignore


SUPPORTED_IMAGES = {".png", ".webp", ".jpg", ".jpeg"}


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")[:64]
    if slug:
        return slug
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"chromapaw-{digest}"


def clean_text(value: str, field: str, maximum: int) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError(f"{field} cannot be empty")
    if len(cleaned) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return cleaned


def _image_path(value: Path, field: str) -> Path:
    path = value.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{field} does not exist: {path}")
    if path.suffix.lower() not in SUPPORTED_IMAGES:
        raise ValueError(f"{field} must be PNG, WebP, JPG, or JPEG")
    return path


def build_request(args: argparse.Namespace) -> dict[str, object]:
    reference = _image_path(args.image, "reference image")
    artwork = _image_path(args.artwork or args.image, "artwork image")
    profile = load_theme_profile(args.theme_profile.expanduser().resolve())
    if profile["referenceSha256"] != sha256_file(reference):
        raise ValueError("theme profile does not match the reference image SHA-256")
    display_name = clean_text(args.name or reference.stem, "name", 80)
    skin_id = slugify(args.id or display_name)
    if args.id and skin_id != args.id:
        raise ValueError("id must already be lower-case kebab-case")

    description = clean_text(
        args.description or f"A layered Codex skin based on {display_name}.",
        "description",
        240,
    )
    scene_brief = clean_text(
        args.scene_brief
        or (
            f"Create the {profile['themeName']} environment in {profile['visualStyle']} style with "
            f"a {profile['mood']} mood. Preserve these motifs: {', '.join(profile['motifs'])}. "
            f"Avoid unrelated elements: {', '.join(profile['avoidElements']) or 'none specified'}."
        ),
        "scene brief",
        500,
    )

    source: dict[str, str] = {
        "author": clean_text(args.author, "author", 100),
        "license": clean_text(args.license, "license", 80),
    }
    if args.source_url:
        source["url"] = clean_text(args.source_url, "source URL", 500)

    return {
        "schemaVersion": 2,
        "id": skin_id,
        "displayName": display_name,
        "description": description,
        "mode": args.mode,
        "referenceImage": str(reference),
        "artworkImage": str(artwork),
        "sceneBrief": scene_brief,
        "themeProfile": profile,
        "source": source,
        "target": {
            "kind": "chromapaw-portable-skin",
            "skinSchemaVersion": 2,
            "ratios": ["16:10", "16:9", "4:3"],
            "modes": ["light", "dark"],
            "activation": "separate-runtime-required",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path, help="Original reference image")
    parser.add_argument(
        "--artwork",
        type=Path,
        help="Approved expanded scene; defaults to the original reference image",
    )
    parser.add_argument(
        "--theme-profile",
        required=True,
        type=Path,
        help="Validated theme-profile.json derived from the same reference image",
    )
    parser.add_argument("--name", help="Display name; defaults to the reference filename")
    parser.add_argument("--id", help="Optional lower-case kebab-case package id")
    parser.add_argument("--description", help="One-sentence skin description")
    parser.add_argument("--mode", choices=("light", "dark", "adaptive"), default="adaptive")
    parser.add_argument("--scene-brief", help="Scene expansion and composition notes")
    parser.add_argument("--author", default="User-provided reference")
    parser.add_argument("--license", default="Unspecified")
    parser.add_argument("--source-url")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--force", action="store_true", help="Replace an existing request file")
    args = parser.parse_args()

    try:
        request = build_request(args)
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / "skin-request.json"
        if output.exists() and not args.force:
            raise ValueError(f"request already exists: {output}; pass --force to replace it")
        output.write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
