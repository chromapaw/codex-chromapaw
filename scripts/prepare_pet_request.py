#!/usr/bin/env python3
"""Normalize one reference image and animation intent into a ChromaPaw pet request."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path


SUPPORTED_IMAGES = {".png", ".webp", ".jpg", ".jpeg"}
STYLE_PRESETS = {
    "auto",
    "pixel",
    "plush",
    "clay",
    "sticker",
    "flat-vector",
    "3d-toy",
    "painterly",
    "brand-inspired",
}


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


def build_request(args: argparse.Namespace) -> dict[str, object]:
    source = args.image.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"source image does not exist: {source}")
    if source.suffix.lower() not in SUPPORTED_IMAGES:
        raise ValueError("source image must be PNG, WebP, JPG, or JPEG")

    raw_name = args.name or source.stem
    display_name = clean_text(raw_name, "name", 80)
    pet_id = slugify(args.id or display_name)
    if args.id and pet_id != args.id:
        raise ValueError("id must already be lower-case kebab-case")

    description = clean_text(
        args.description or f"A custom Codex pet based on {display_name}.",
        "description",
        240,
    )
    intents = {
        "idle": clean_text(args.idle_action, "idle action", 240),
        "working": clean_text(args.working_action, "working action", 240),
        "waiting": clean_text(args.waiting_action, "waiting action", 240),
        "ready": clean_text(args.ready_action, "ready action", 240),
        "failed": clean_text(args.failed_action, "failed action", 240),
    }
    intent_summary = "; ".join(f"{key}: {value}" for key, value in intents.items())

    return {
        "schemaVersion": 1,
        "id": pet_id,
        "displayName": display_name,
        "description": description,
        "sourceImage": str(source),
        "style": args.style,
        "animationIntent": intents,
        "hatchPetHandoff": {
            "reference": str(source),
            "petName": display_name,
            "description": description,
            "stylePreset": args.style,
            "petNotes": (
                "Preserve the source character's identity and signature props. "
                f"Requested state intent — {intent_summary}. "
                "Map these intentions onto the closest supported Codex v2 rows without "
                "weakening hatch-pet validation or inventing unsupported runtime states."
            ),
        },
        "target": {
            "kind": "codex-local-pet",
            "spriteVersionNumber": 2,
            "atlas": {
                "columns": 8,
                "rows": 11,
                "cellWidth": 192,
                "cellHeight": 208,
                "width": 1536,
                "height": 2288,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path, help="Reference image")
    parser.add_argument("--name", help="Display name; defaults to the image filename")
    parser.add_argument("--id", help="Optional lower-case kebab-case package id")
    parser.add_argument("--description", help="One-sentence pet description")
    parser.add_argument("--style", choices=sorted(STYLE_PRESETS), default="auto")
    parser.add_argument("--idle-action", default="Breathe, blink, and make a subtle calm motion.")
    parser.add_argument("--working-action", default="Work with focused, readable body language.")
    parser.add_argument("--waiting-action", default="Ask expectantly for user input or approval.")
    parser.add_argument("--ready-action", default="Celebrate task completion with a compact dance.")
    parser.add_argument("--failed-action", default="React with a clear but gentle disappointed pose.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--force", action="store_true", help="Replace an existing request file")
    args = parser.parse_args()

    try:
        request = build_request(args)
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / "pet-request.json"
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
