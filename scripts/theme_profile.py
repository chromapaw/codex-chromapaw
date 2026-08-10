#!/usr/bin/env python3
"""Shared validation helpers for ChromaPaw semantic theme profiles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SOURCE_KINDS = {"full-environment", "subject", "texture", "abstract", "logo"}
DEPTH_LAYERS = ("atmosphere", "distant", "midground", "foreground")
PROFILE_FIELDS = {
    "schemaVersion",
    "referenceSha256",
    "sourceKind",
    "themeName",
    "visualStyle",
    "mood",
    "identityCues",
    "motifs",
    "avoidElements",
    "depthPlan",
    "safeZoneGuidance",
}


class ThemeProfileError(ValueError):
    """Raised when a semantic theme profile violates the contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ThemeProfileError(f"{field} must be a string")
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > maximum:
        raise ThemeProfileError(f"{field} must contain 1 to {maximum} characters")
    return cleaned


def _text_list(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ThemeProfileError(f"{field} must contain {minimum} to {maximum} items")
    cleaned = [_text(item, f"{field}[{index}]", 120) for index, item in enumerate(value)]
    folded = [item.casefold() for item in cleaned]
    if len(set(folded)) != len(folded):
        raise ThemeProfileError(f"{field} must not contain duplicates")
    return cleaned


def validate_theme_profile(value: object) -> list[str]:
    try:
        normalize_theme_profile(value)
    except ThemeProfileError as exc:
        return [str(exc)]
    return []


def normalize_theme_profile(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ThemeProfileError("theme profile must be an object")
    missing = PROFILE_FIELDS - value.keys()
    if missing:
        raise ThemeProfileError(
            "theme profile is missing required fields: " + ", ".join(sorted(missing))
        )
    unknown = value.keys() - PROFILE_FIELDS
    if unknown:
        raise ThemeProfileError(
            "theme profile contains unsupported fields: " + ", ".join(sorted(unknown))
        )
    if value.get("schemaVersion") != 1:
        raise ThemeProfileError("theme profile schemaVersion must be 1")
    reference_hash = value.get("referenceSha256")
    if not isinstance(reference_hash, str) or len(reference_hash) != 64:
        raise ThemeProfileError("referenceSha256 must be a 64-character SHA-256 digest")
    try:
        int(reference_hash, 16)
    except ValueError as exc:
        raise ThemeProfileError("referenceSha256 must contain hexadecimal characters") from exc
    source_kind = value.get("sourceKind")
    if source_kind not in SOURCE_KINDS:
        raise ThemeProfileError(
            "sourceKind must be full-environment, subject, texture, abstract, or logo"
        )
    identity_cues = _text_list(value.get("identityCues"), "identityCues", minimum=1, maximum=12)
    motifs = _text_list(value.get("motifs"), "motifs", minimum=1, maximum=12)
    avoid = _text_list(value.get("avoidElements"), "avoidElements", minimum=0, maximum=12)
    overlap = sorted({item.casefold() for item in motifs} & {item.casefold() for item in avoid})
    if overlap:
        raise ThemeProfileError(
            "motifs and avoidElements contradict each other: " + ", ".join(overlap)
        )
    depth_plan = value.get("depthPlan")
    if not isinstance(depth_plan, dict):
        raise ThemeProfileError("depthPlan must be an object")
    if set(depth_plan) != set(DEPTH_LAYERS):
        raise ThemeProfileError(
            "depthPlan must contain atmosphere, distant, midground, and foreground"
        )
    normalized_depth = {
        layer: _text(depth_plan[layer], f"depthPlan.{layer}", 240) for layer in DEPTH_LAYERS
    }
    return {
        "schemaVersion": 1,
        "referenceSha256": reference_hash.lower(),
        "sourceKind": source_kind,
        "themeName": _text(value.get("themeName"), "themeName", 80),
        "visualStyle": _text(value.get("visualStyle"), "visualStyle", 120),
        "mood": _text(value.get("mood"), "mood", 120),
        "identityCues": identity_cues,
        "motifs": motifs,
        "avoidElements": avoid,
        "depthPlan": normalized_depth,
        "safeZoneGuidance": _text(value.get("safeZoneGuidance"), "safeZoneGuidance", 240),
    }


def load_theme_profile(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ThemeProfileError(f"theme profile cannot be read: {exc}") from exc
    return normalize_theme_profile(value)
