#!/usr/bin/env python3
"""Safely inspect and update Codex's selected desktop pet."""

from __future__ import annotations

import copy
import contextlib
import hashlib
import math
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pet_package import PET_ID, PetPackageError

try:
    import tomllib as _tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    try:
        import tomli as _tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover - safe failure is tested indirectly
        _tomllib = None  # type: ignore[assignment]


DESKTOP_TABLE = re.compile(r"^\s*\[\s*desktop\s*\]\s*(?:#.*)?$")
ANY_TABLE = re.compile(r"^\s*\[.*\]\s*(?:#.*)?$")
SELECTED_KEY = re.compile(
    r'''^(?P<prefix>\s*selected-avatar-id\s*=\s*)'''
    r'''(?P<value>"(?:[^"\\\r\n]|\\.)*"|'[^'\r\n]*')'''
    r"(?P<suffix>\s*(?:#.*)?)(?P<newline>\r?\n)?$"
)
_MISSING = object()
SELECTION_LOCK_FILE = ".chromapaw-pet-selection.lock"


@contextlib.contextmanager
def selection_lock(codex_home: Path):
    """Serialize cooperating ChromaPaw config edits with a crash-safe OS lock.

    The metadata file is intentionally retained. The operating system owns the
    actual byte lock and releases it when a process exits, so stale text never
    blocks a later operation.
    """

    home = codex_home.expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    path = home / SELECTION_LOCK_FILE
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR)
    except OSError as exc:
        raise PetPackageError(f"pet selection lock cannot be opened: {path}: {exc}") from exc
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size < 1:
                    os.write(descriptor, b"\0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except (OSError, BlockingIOError) as exc:
            raise PetPackageError(
                f"another ChromaPaw pet selection operation is active: {path}"
            ) from exc
        metadata = (
            f"pid={os.getpid()} time={datetime.now(timezone.utc).isoformat()}\n"
        ).encode("utf-8")
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, metadata)
        os.fsync(descriptor)
        yield
    finally:
        if locked:
            with contextlib.suppress(OSError):
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _stat_identity(path: Path) -> tuple[int, int, int, int]:
    status = path.stat(follow_symlinks=False)
    return (status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns)


def _read_config_snapshot(config: Path) -> tuple[bytes, tuple[int, int, int, int]]:
    if config.is_symlink() or not config.is_file():
        raise PetPackageError("refusing to edit a linked or non-file Codex config")
    before = _stat_identity(config)
    payload = config.read_bytes()
    after = _stat_identity(config)
    if before != after or len(payload) != after[2]:
        raise PetPackageError(
            "Codex config changed while pet selection was reading it; no selection was written"
        )
    return payload, after


def _config_matches_snapshot(
    config: Path,
    *,
    existed: bool,
    payload: bytes,
    identity: tuple[int, int, int, int] | None,
) -> bool:
    if config.is_symlink():
        return False
    if not existed:
        return not config.exists()
    if not config.is_file() or identity is None:
        return False
    try:
        before = _stat_identity(config)
        current = config.read_bytes()
        after = _stat_identity(config)
    except OSError:
        return False
    return before == identity == after and current == payload


def selected_avatar_id(pet_id: str) -> str:
    if not PET_ID.fullmatch(pet_id) or len(pet_id) > 64:
        raise PetPackageError("pet id is not safe for Codex selection")
    return f"custom:{pet_id}"


def _decode_config(payload: bytes) -> tuple[str, bool]:
    has_bom = payload.startswith(b"\xef\xbb\xbf")
    try:
        return payload.decode("utf-8-sig"), has_bom
    except UnicodeDecodeError as exc:
        raise PetPackageError(f"Codex config is not valid UTF-8: {exc}") from exc


def _parse_toml(text: str) -> dict[str, Any]:
    if _tomllib is None:
        raise PetPackageError(
            "safe Codex config editing requires Python 3.11+ or the tomli backport"
        )
    try:
        value = _tomllib.loads(text)
    except _tomllib.TOMLDecodeError as exc:
        raise PetPackageError(f"Codex config is not valid TOML: {exc}") from exc
    if not isinstance(value, dict):  # Defensive: TOML documents always decode to a dict.
        raise PetPackageError("Codex config did not decode to a TOML document")
    return value


def _desktop_selection(
    document: dict[str, Any],
) -> tuple[bool, bool, str | None]:
    desktop = document.get("desktop", _MISSING)
    if desktop is _MISSING:
        return False, False, None
    if not isinstance(desktop, dict):
        raise PetPackageError(
            "Codex config desktop must be a TOML table before ChromaPaw can edit it"
        )
    selected = desktop.get("selected-avatar-id", _MISSING)
    if selected is _MISSING:
        return True, False, None
    if not isinstance(selected, str):
        raise PetPackageError(
            "desktop selected-avatar-id must be a string before ChromaPaw can edit it"
        )
    return True, True, selected


def _semantic_equal(left: Any, right: Any) -> bool:
    """Compare parsed TOML while treating two NaN values as equivalent."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _semantic_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _semantic_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, float) and math.isnan(left) and math.isnan(right):
        return True
    return bool(left == right)


def _selection_result(
    config: Path, config_exists: bool, document: dict[str, Any]
) -> dict[str, Any]:
    _, _, value = _desktop_selection(document)
    return {
        "config": str(config),
        "configExists": config_exists,
        "selectedAvatarId": value,
    }


def _coordination_result() -> dict[str, Any]:
    return {
        "scope": "CODEX_HOME",
        "mechanism": "os-advisory-lock-and-pre-replace-snapshot-check",
        "externalUnlockedWriterAbsoluteCas": False,
    }


def _desktop_bounds(lines: list[str]) -> tuple[int | None, int]:
    starts = [index for index, line in enumerate(lines) if DESKTOP_TABLE.match(line)]
    if len(starts) > 1:
        raise PetPackageError("Codex config contains more than one [desktop] table")
    if not starts:
        return None, len(lines)
    start = starts[0]
    end = next(
        (index for index in range(start + 1, len(lines)) if ANY_TABLE.match(lines[index])),
        len(lines),
    )
    return start, end


def inspect_selection(config: Path) -> dict[str, Any]:
    config = config.expanduser().absolute()
    if config.exists() and (config.is_symlink() or not config.is_file()):
        raise PetPackageError("refusing to inspect a linked or non-file Codex config")
    if not config.is_file():
        return {
            "config": str(config),
            "configExists": False,
            "selectedAvatarId": None,
        }
    text, _ = _decode_config(config.read_bytes())
    return _selection_result(config, True, _parse_toml(text))


def _render_selection(
    text: str, avatar_id: str, document: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    start, end = _desktop_bounds(lines)
    desktop_exists, selection_exists, _ = _desktop_selection(document)
    entry = f'selected-avatar-id = "{avatar_id}"{newline}'
    if start is None:
        if desktop_exists:
            raise PetPackageError(
                "Codex config uses an equivalent desktop TOML declaration that "
                "ChromaPaw cannot safely edit in place"
            )
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        if lines and lines[-1].strip():
            lines.append(newline)
        lines.extend((f"[desktop]{newline}", entry))
    else:
        if not desktop_exists:
            raise PetPackageError(
                "Codex config desktop syntax could not be matched safely"
            )
        matches = [
            index
            for index in range(start + 1, end)
            if SELECTED_KEY.match(lines[index])
        ]
        if len(matches) > 1:
            raise PetPackageError(
                "Codex config contains duplicate desktop selected-avatar-id keys"
            )
        if selection_exists and not matches:
            raise PetPackageError(
                "Codex config uses an equivalent selected-avatar-id TOML key that "
                "ChromaPaw cannot safely edit in place"
            )
        if not selection_exists and matches:
            raise PetPackageError(
                "Codex config selected-avatar-id syntax could not be matched safely"
            )
        if matches:
            match = SELECTED_KEY.match(lines[matches[0]])
            if match is None:  # Already selected by the same expression above.
                raise PetPackageError(
                    "Codex config selected-avatar-id syntax could not be matched safely"
                )
            lines[matches[0]] = (
                f'{match.group("prefix")}"{avatar_id}"'
                f'{match.group("suffix")}{match.group("newline") or ""}'
            )
        else:
            lines.insert(end, entry)

    rendered = "".join(lines)
    expected = copy.deepcopy(document)
    desktop = expected.setdefault("desktop", {})
    if not isinstance(desktop, dict):  # Already rejected by _desktop_selection.
        raise PetPackageError("Codex config desktop is not a TOML table")
    desktop["selected-avatar-id"] = avatar_id
    rendered_document = _parse_toml(rendered)
    if not _semantic_equal(rendered_document, expected):
        raise PetPackageError(
            "refusing to write Codex config because the TOML edit changed unrelated settings"
        )
    return rendered, expected


def _select_pet_locked(codex_home: Path, pet_id: str) -> dict[str, Any]:
    home = codex_home.expanduser().resolve()
    config = home / "config.toml"
    avatar_id = selected_avatar_id(pet_id)
    if config.exists() and (config.is_symlink() or not config.is_file()):
        raise PetPackageError("refusing to edit a linked or non-file Codex config")
    original_exists = config.is_file()
    original_identity: tuple[int, int, int, int] | None = None
    if original_exists:
        original, original_identity = _read_config_snapshot(config)
    else:
        original = b""
    text, has_bom = _decode_config(original)
    document = _parse_toml(text)
    before = _selection_result(config, original_exists, document)
    if before["selectedAvatarId"] == avatar_id:
        return {
            **before,
            "selectedAvatarId": avatar_id,
            "changed": False,
            "backup": None,
            "backupSha256": None,
            "coordination": _coordination_result(),
        }

    rendered, expected_document = _render_selection(text, avatar_id, document)
    payload = rendered.encode("utf-8")
    if has_bom:
        payload = b"\xef\xbb\xbf" + payload

    home.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    backup_hash: str | None = None
    if config.is_file():
        backup_root = home / "pets" / ".chromapaw-config-backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_root / f"config-{timestamp}.toml"
        backup.write_bytes(original)
        shutil.copystat(config, backup)
        backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()

    temporary: Path | None = None
    wrote_config = False
    try:
        if not _config_matches_snapshot(
            config,
            existed=original_exists,
            payload=original,
            identity=original_identity,
        ):
            raise PetPackageError(
                "Codex config changed during pet selection; no selection was written"
            )
        fd, name = tempfile.mkstemp(prefix=".chromapaw-config-", dir=home)
        os.close(fd)
        temporary = Path(name)
        temporary.write_bytes(payload)
        if config.is_file():
            shutil.copystat(config, temporary)
        # Recheck immediately before replacement. This serializes all cooperating
        # ChromaPaw writers and catches unlocked external changes in the practical
        # write window. It is deliberately not described as an absolute CAS:
        # software that ignores this advisory lock can still race the final replace.
        if not _config_matches_snapshot(
            config,
            existed=original_exists,
            payload=original,
            identity=original_identity,
        ):
            raise PetPackageError(
                "Codex config changed immediately before pet selection; no selection was written"
            )
        os.replace(temporary, config)
        temporary = None
        wrote_config = True
        actual_text, _ = _decode_config(config.read_bytes())
        actual_document = _parse_toml(actual_text)
        if not _semantic_equal(actual_document, expected_document):
            raise PetPackageError(
                "Codex config did not retain the verified TOML pet selection edit"
            )
        after = _selection_result(config, True, actual_document)
        if after["selectedAvatarId"] != avatar_id:
            raise PetPackageError("Codex config did not retain the selected pet")
    except Exception:
        if wrote_config:
            current = config.read_bytes() if config.is_file() else None
            if current != payload:
                raise PetPackageError(
                    "Codex config changed after pet selection; user changes were preserved"
                )
            if original_exists:
                rollback = config.with_name(config.name + ".chromapaw-pet-rollback.tmp")
                rollback.write_bytes(original)
                os.replace(rollback, config)
            else:
                config.unlink(missing_ok=True)
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return {
        **after,
        "changed": True,
        "previousSelectedAvatarId": before["selectedAvatarId"],
        "backup": str(backup) if backup is not None else None,
        "backupSha256": backup_hash,
        "coordination": _coordination_result(),
    }


def select_pet(codex_home: Path, pet_id: str) -> dict[str, Any]:
    home = codex_home.expanduser().resolve()
    with selection_lock(home):
        return _select_pet_locked(home, pet_id)
