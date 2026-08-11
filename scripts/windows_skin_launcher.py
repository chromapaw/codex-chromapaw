#!/usr/bin/env python3
"""Quiet Windows entry point that resumes the last validated ChromaPaw skin."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import sys
from pathlib import Path


CONFIRMATION_FLAGS = (
    0x00000004  # MB_YESNO
    | 0x00000030  # MB_ICONWARNING
    | 0x00000100  # MB_DEFBUTTON2 (No)
    | 0x00002000  # MB_TASKMODAL
    | 0x00010000  # MB_SETFOREGROUND
    | 0x00040000  # MB_TOPMOST
)

try:
    from .windows_runtime import (
        DEFAULT_ADAPTERS,
        RuntimeFailure,
        _read_preference,
        close_matching_codex_processes,
        redact_result,
        resume_runtime,
        running_pids,
        runtime_data_dir,
        runtime_status,
        utc_now,
    )
except ImportError:
    from windows_runtime import (  # type: ignore
        DEFAULT_ADAPTERS,
        RuntimeFailure,
        _read_preference,
        close_matching_codex_processes,
        redact_result,
        resume_runtime,
        running_pids,
        runtime_data_dir,
        runtime_status,
        utc_now,
    )


def _append_log(data_dir: Path, value: dict[str, object]) -> None:
    path = data_dir / "launcher.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def _show_error(message: str) -> None:
    if os.name != "nt":
        return
    with contextlib.suppress(Exception):
        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            0,
            message,
            "ChromaPaw could not start Codex",
            0x00000010,
        )


def _confirm_close_running(executable: Path, pids: list[int]) -> bool:
    if os.name != "nt":
        return False
    message = (
        "Codex is still running in the background.\n\n"
        "To restore the ChromaPaw skin, Codex must close completely and reopen. "
        "Unsaved work in this Codex instance could be lost.\n\n"
        f"Executable:\n{executable}\n\n"
        f"Matching processes: {len(pids)}\n\n"
        "Close this exact Codex process group and continue?"
    )
    try:
        result = ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            0,
            message,
            "ChromaPaw needs to restart Codex",
            CONFIRMATION_FLAGS,
        )
    except Exception:
        return False
    return result == 6


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--adapters", type=Path, default=DEFAULT_ADAPTERS)
    parser.add_argument("--wait-seconds", type=float, default=30.0)
    parser.add_argument("--acknowledge-experimental-runtime", action="store_true")
    parser.add_argument("--no-error-dialog", action="store_true")
    args = parser.parse_args()

    data_dir = runtime_data_dir(args.data_dir)
    try:
        close_result = None
        status = runtime_status(data_dir)
        if status.get("status") != "active":
            preference = _read_preference(data_dir)
            if preference is None:
                raise RuntimeFailure(
                    "no preferred skin is saved; activate a validated package once before using the launcher"
                )
            executable = Path(preference["executable"]).expanduser().resolve()
            pids = running_pids(executable)
            if pids:
                if args.no_error_dialog or not _confirm_close_running(executable, pids):
                    event = {
                        "time": utc_now(),
                        "event": "launcher-cancelled-running-codex",
                        "executable": str(executable),
                        "matchingProcessCount": len(pids),
                    }
                    _append_log(data_dir, event)
                    return 2
                close_result = close_matching_codex_processes(
                    executable,
                    acknowledged=True,
                )
        result = resume_runtime(
            data_dir,
            args.adapters.expanduser().resolve(),
            acknowledged=args.acknowledge_experimental_runtime,
            wait_seconds=args.wait_seconds,
        )
        event = {
            "time": utc_now(),
            "event": "launcher-success",
            "userConfirmedClose": redact_result(close_result),
            "result": redact_result(result),
        }
        _append_log(data_dir, event)
        return 0
    except (OSError, RuntimeFailure, ValueError) as exc:
        event = {
            "time": utc_now(),
            "event": "launcher-failed",
            "error": str(exc),
        }
        with contextlib.suppress(OSError):
            _append_log(data_dir, event)
        if not args.no_error_dialog:
            _show_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
