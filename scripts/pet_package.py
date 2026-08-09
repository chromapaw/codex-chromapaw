#!/usr/bin/env python3
"""Shared, dependency-free helpers for ChromaPaw pet packages."""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


PET_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ATLAS_WIDTH = 1536
ATLAS_HEIGHT = 2288
CELL_WIDTH = 192
CELL_HEIGHT = 208
SUPPORTED_ATLAS_EXTENSIONS = {".png", ".webp"}
REQUIRED_MANIFEST_KEYS = {
    "id",
    "displayName",
    "description",
    "spriteVersionNumber",
    "spritesheetPath",
}


class PetPackageError(ValueError):
    """Raised when a pet package cannot be read safely."""


@dataclass(frozen=True)
class ValidatedPetPackage:
    package_dir: Path
    manifest_path: Path
    manifest: dict[str, Any]
    spritesheet_path: Path
    spritesheet_relative_path: Path
    width: int
    height: int

    @property
    def pet_id(self) -> str:
        return str(self.manifest["id"])


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def safe_relative_path(value: object, field: str) -> tuple[Path | None, str | None]:
    """Return a normalized relative path or a validation error."""
    if not isinstance(value, str) or not value.strip():
        return None, f"{field} must be a non-empty relative path"
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or re.match(r"^[A-Za-z]:", normalized):
        return None, f"{field} must be relative"
    if any(part in {"", ".", ".."} for part in pure.parts):
        return None, f"{field} must stay inside the package"
    return Path(*pure.parts), None


def _png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise PetPackageError("spritesheet is not a valid PNG header")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _uint24_le(data: bytes) -> int:
    return data[0] | (data[1] << 8) | (data[2] << 16)


def _webp_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise PetPackageError("spritesheet is not a valid WebP container")

    offset = 12
    while offset + 8 <= len(data):
        chunk_type = data[offset : offset + 4]
        chunk_size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        payload_start = offset + 8
        payload_end = payload_start + chunk_size
        if payload_end > len(data):
            raise PetPackageError("spritesheet contains a truncated WebP chunk")
        payload = data[payload_start:payload_end]

        if chunk_type == b"VP8X":
            if len(payload) < 10:
                raise PetPackageError("spritesheet contains a truncated VP8X header")
            return _uint24_le(payload[4:7]) + 1, _uint24_le(payload[7:10]) + 1
        if chunk_type == b"VP8L":
            if len(payload) < 5 or payload[0] != 0x2F:
                raise PetPackageError("spritesheet contains an invalid VP8L header")
            bits = struct.unpack("<I", payload[1:5])[0]
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk_type == b"VP8 ":
            if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
                raise PetPackageError("spritesheet contains an invalid VP8 frame header")
            width = struct.unpack("<H", payload[6:8])[0] & 0x3FFF
            height = struct.unpack("<H", payload[8:10])[0] & 0x3FFF
            return width, height

        offset = payload_end + (chunk_size % 2)

    raise PetPackageError("spritesheet WebP dimensions could not be found")


def image_dimensions(path: Path) -> tuple[int, int]:
    """Read PNG or WebP dimensions without decoding the full image."""
    try:
        with path.open("rb") as stream:
            data = stream.read(1024 * 1024)
    except OSError as exc:
        raise PetPackageError(f"spritesheet cannot be read: {exc}") from exc
    if path.suffix.lower() == ".png":
        return _png_dimensions(data)
    if path.suffix.lower() == ".webp":
        return _webp_dimensions(data)
    raise PetPackageError("spritesheet must be PNG or WebP")


def validate_pet_package(package_dir: Path) -> tuple[list[str], ValidatedPetPackage | None]:
    """Validate a desktop Codex v2 pet package."""
    errors: list[str] = []
    root = package_dir.resolve()
    manifest_path = root / "pet.json"
    if not manifest_path.is_file():
        return ["pet.json is missing"], None
    if not _inside(root, manifest_path.resolve()):
        return ["pet.json resolves outside the package"], None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"pet.json cannot be read: {exc}"], None
    if not isinstance(manifest, dict):
        return ["pet.json must contain a JSON object"], None

    missing = sorted(REQUIRED_MANIFEST_KEYS - manifest.keys())
    if missing:
        errors.append(f"pet.json is missing required fields: {', '.join(missing)}")
    unknown = sorted(manifest.keys() - REQUIRED_MANIFEST_KEYS)
    if unknown:
        errors.append(f"pet.json contains unsupported fields: {', '.join(unknown)}")

    pet_id = manifest.get("id")
    if not isinstance(pet_id, str) or not PET_ID.fullmatch(pet_id) or len(pet_id) > 64:
        errors.append("id must be lower-case kebab-case and at most 64 characters")

    display_name = manifest.get("displayName")
    if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 80:
        errors.append("displayName must contain 1 to 80 non-whitespace characters")

    description = manifest.get("description")
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 240:
        errors.append("description must contain 1 to 240 non-whitespace characters")

    if manifest.get("spriteVersionNumber") != 2:
        errors.append("spriteVersionNumber must be 2")

    relative_sheet, path_error = safe_relative_path(
        manifest.get("spritesheetPath"), "spritesheetPath"
    )
    spritesheet: Path | None = None
    if path_error:
        errors.append(path_error)
    elif relative_sheet is not None:
        if relative_sheet.suffix.lower() not in SUPPORTED_ATLAS_EXTENSIONS:
            errors.append("spritesheetPath must point to a PNG or WebP file")
        spritesheet = (root / relative_sheet).resolve()
        if not _inside(root, spritesheet):
            errors.append("spritesheetPath resolves outside the package")
        elif not spritesheet.is_file():
            errors.append(f"spritesheet does not exist: {manifest.get('spritesheetPath')}")

    width = height = 0
    if spritesheet is not None and spritesheet.is_file() and _inside(root, spritesheet):
        try:
            width, height = image_dimensions(spritesheet)
        except PetPackageError as exc:
            errors.append(str(exc))
        else:
            if (width, height) != (ATLAS_WIDTH, ATLAS_HEIGHT):
                errors.append(
                    "spritesheet must be exactly "
                    f"{ATLAS_WIDTH}x{ATLAS_HEIGHT}; found {width}x{height}"
                )

    if errors or relative_sheet is None or spritesheet is None:
        return errors, None
    return errors, ValidatedPetPackage(
        package_dir=root,
        manifest_path=manifest_path,
        manifest=manifest,
        spritesheet_path=spritesheet,
        spritesheet_relative_path=relative_sheet,
        width=width,
        height=height,
    )
