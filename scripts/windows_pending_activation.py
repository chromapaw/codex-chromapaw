#!/usr/bin/env python3
"""Persist an explicitly reviewed activation for the next ChromaPaw click."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path

try:
    from . import windows_runtime as runtime
except ImportError:
    import windows_runtime as runtime

PENDING_FILE = "pending-skin-activation.json"
RESULT_FILE = "pending-skin-activation-result.json"
IDENTITY_FIELDS = (
    "package", "packageId", "manifestHash", "cssHash", "executable",
    "executableHash", "appVersion", "adapterId", "adapterFile", "adapterFileHash",
)


def _preference_hash(data_dir: Path) -> str | None:
    path = data_dir / runtime.PREFERENCE_FILE
    return runtime.sha256_file(path) if path.is_file() else None


def _hosted_identity() -> dict[str, str]:
    digest = os.environ.get("CHROMAPAW_HOSTED_BUNDLE_HASH", "")
    generation = os.environ.get("CHROMAPAW_HOSTED_GENERATION", "")
    if not runtime.SHA256_PATTERN.fullmatch(digest) or generation != "sha256-" + digest:
        raise runtime.RuntimeFailure("pending activation requires an exact reviewed hosted generation")
    return {"runtimeBundleHash": digest, "runtimeGeneration": generation}


def read_pending(data_dir: Path) -> dict | None:
    path = data_dir / PENDING_FILE
    if not path.exists():
        return None
    if path.is_symlink():
        raise runtime.RuntimeFailure("pending activation cannot be a linked file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise runtime.RuntimeFailure("pending activation cannot be read") from exc
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1
            or value.get("operation") != "activate" or value.get("acknowledged") is not True
            or not isinstance(value.get("requestId"), str)
            or any(not isinstance(value.get(key), str) or not value[key] for key in IDENTITY_FIELDS)):
        raise runtime.RuntimeFailure("pending activation metadata is invalid")
    return value


def prepare_activation(package: Path, executable: Path, data_dir: Path, adapters: Path,
                       *, acknowledged: bool) -> dict:
    if not acknowledged:
        raise runtime.RuntimeFailure("pending activation requires explicit experimental runtime acknowledgement")
    hosted = _hosted_identity()
    checked = runtime.build_preflight(package, executable, adapters)
    with runtime.runtime_lock(data_dir):
        if runtime._read_active(data_dir) is not None:
            raise runtime.RuntimeFailure("restore the existing skin session before preparing a new activation")
        if (data_dir / PENDING_FILE).exists():
            raise runtime.RuntimeFailure("a pending activation already exists; inspect it before replacing")
        value = {
            "schemaVersion": 1, "operation": "activate", "acknowledged": True,
            "requestId": secrets.token_hex(16), "preparedAt": runtime.utc_now(),
            "previousPreferenceHash": _preference_hash(data_dir),
            **{key: checked[key] for key in IDENTITY_FIELDS}, **hosted,
        }
        # This is an intent, not a successful activation: leave the old preference intact.
        runtime.atomic_json(data_dir / PENDING_FILE, value)
    return {"ok": True, "status": "pending-next-launch", "request": value,
            "requestFile": str(data_dir / PENDING_FILE), "skinApplied": False}


def validate_pending(data_dir: Path, adapters: Path) -> dict | None:
    value = read_pending(data_dir)
    if value is None:
        return None
    if any(value.get(key) != expected for key, expected in _hosted_identity().items()):
        raise runtime.RuntimeFailure("pending activation hosted generation changed")
    if Path(value["adapterFile"]).resolve() != adapters.resolve():
        raise runtime.RuntimeFailure("pending activation adapter path changed")
    checked = runtime.build_preflight(Path(value["package"]), Path(value["executable"]), adapters)
    for key in IDENTITY_FIELDS:
        if checked.get(key) != value[key]:
            raise runtime.RuntimeFailure("pending activation identity changed: " + key)
    active = runtime._read_active(data_dir)
    if active is not None:
        if any(active.get(key) != value[key] for key in IDENTITY_FIELDS):
            raise runtime.RuntimeFailure("pending activation does not own the current active session")
    elif _preference_hash(data_dir) != value.get("previousPreferenceHash"):
        raise runtime.RuntimeFailure("saved preference changed after activation was reviewed")
    return value


def apply_pending(data_dir: Path, adapters: Path, *, acknowledged: bool, wait_seconds: float) -> dict:
    if not acknowledged:
        raise runtime.RuntimeFailure("pending activation requires explicit runtime acknowledgement")
    value = validate_pending(data_dir, adapters)
    if value is None:
        raise runtime.RuntimeFailure("no pending activation exists")
    if runtime._read_active(data_dir) is None:
        runtime.activate_runtime(
            Path(value["package"]), Path(value["executable"]), data_dir, adapters,
            acknowledged=True, profile_dir=None, allow_parallel_profile=False, wait_seconds=wait_seconds,
        )
    else:
        # Activation may have committed before its caller exited. Resume verifies
        # a live matching session or safely recovers its ended process record.
        runtime.resume_runtime(data_dir, adapters, acknowledged=True, wait_seconds=wait_seconds)
    verified = runtime.verify_runtime(data_dir)
    if not verified.get("ok"):
        raise runtime.RuntimeFailure("pending activation verification did not pass; request retained")
    result = {"ok": True, "status": "active-verified", "requestId": value["requestId"],
              "packageId": value["packageId"], "appVersion": value["appVersion"],
              "verifiedAt": runtime.utc_now(), "verification": runtime.redact_result(verified)}
    with runtime.runtime_lock(data_dir):
        runtime.atomic_json(data_dir / RESULT_FILE, result)
        # A concurrent, different request must never be consumed accidentally.
        current = read_pending(data_dir)
        if current == value:
            (data_dir / PENDING_FILE).unlink()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--adapters", type=Path, default=runtime.DEFAULT_ADAPTERS)
    parser.add_argument("--acknowledge-experimental-runtime", action="store_true")
    args = parser.parse_args()
    try:
        result = prepare_activation(args.package, args.executable, runtime.runtime_data_dir(args.data_dir),
                                    args.adapters, acknowledged=args.acknowledge_experimental_runtime)
    except (OSError, ValueError, runtime.RuntimeFailure) as exc:
        runtime._print_result({"ok": False, "error": str(exc)}, True)
        return 1
    runtime._print_result(result, True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
