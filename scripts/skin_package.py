#!/usr/bin/env python3
"""Shared helpers for ChromaPaw skin packages."""

from __future__ import annotations

import re
import struct
from pathlib import Path, PurePosixPath


SKIN_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
SUPPORTED_BACKGROUND_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}
PREVIEW_DIMENSIONS = {
    "16:10": (960, 600),
    "16:9": (960, 540),
    "4:3": (840, 630),
}
REQUIRED_VARIANTS = {
    (mode, ratio) for mode in ("light", "dark") for ratio in PREVIEW_DIMENSIONS
}


class SkinPackageError(ValueError):
    """Raised when skin package content cannot be handled safely."""


def safe_relative_path(value: object, field: str) -> tuple[Path | None, str | None]:
    """Normalize a package-relative path or return a validation error."""
    if not isinstance(value, str) or not value.strip():
        return None, f"{field} must be a non-empty relative path"
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or re.match(r"^[A-Za-z]:", normalized):
        return None, f"{field} must be relative"
    if any(part in {"", ".", ".."} for part in pure.parts):
        return None, f"{field} must stay inside the package"
    return Path(*pure.parts), None


def path_is_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def png_dimensions(path: Path) -> tuple[int, int]:
    """Read PNG dimensions without decoding the complete image."""
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
    except OSError as exc:
        raise SkinPackageError(f"PNG cannot be read: {exc}") from exc
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise SkinPackageError("file is not a valid PNG header")
    return struct.unpack(">II", header[16:24])


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def relative_luminance(value: str) -> float:
    channels = []
    for channel in hex_to_rgb(value):
        normalized = channel / 255
        channels.append(
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)
