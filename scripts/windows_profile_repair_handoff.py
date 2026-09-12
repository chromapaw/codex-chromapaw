"""Wait for one verified Codex process, repair its sidebar index, and relaunch.

This helper never closes Codex.  It holds a handle to the exact process selected
by the caller, waits for that process to exit normally, performs the explicitly
acknowledged profile repair, and opens the signed Store Codex application.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path

try:
    from .windows_official_launcher import launch_current_official_codex, official_config_locale
    from .windows_profile_repair import repair_sidebar_profile
except ImportError:  # pragma: no cover - direct script execution
    from windows_official_launcher import launch_current_official_codex, official_config_locale
    from windows_profile_repair import repair_sidebar_profile


class HandoffError(RuntimeError):
    pass


def _wait_for_verified_process(pid: int, executable: Path) -> None:
    if os.name != "nt":
        raise HandoffError("sidebar repair handoff is Windows-only")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    synchronize = 0x00100000
    query_limited_information = 0x1000
    handle = kernel32.OpenProcess(
        synchronize | query_limited_information, False, pid
    )
    if not handle:
        error = ctypes.get_last_error()
        if error in (87, 1168):
            return
        raise HandoffError(f"could not open Codex process {pid}: Windows error {error}")
    try:
        capacity = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(capacity)):
            raise HandoffError(
                f"could not verify Codex process {pid}: Windows error {ctypes.get_last_error()}"
            )
        if Path(buffer.value).resolve() != executable.resolve():
            raise HandoffError("Codex process identity changed before sidebar repair handoff")
        result = kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
        if result != 0:
            raise HandoffError(f"waiting for Codex process failed: Windows result {result}")
    finally:
        kernel32.CloseHandle(handle)


def _write_failure(codex_home: Path, exc: BaseException) -> Path:
    path = codex_home / "chromapaw" / "sidebar-repair-handoff-error.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "ok": False,
        "error": str(exc),
        "type": type(exc).__name__,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--wait-executable", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--acknowledge-repairs-project-sidebar", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_repairs_project_sidebar:
        print("ERROR: explicit sidebar repair acknowledgement is required", file=sys.stderr)
        return 1
    codex_home = args.codex_home.expanduser().resolve()
    try:
        _wait_for_verified_process(args.wait_pid, args.wait_executable)
        repair_sidebar_profile(codex_home, acknowledged=True)
        launch_current_official_codex(locale=official_config_locale())
        return 0
    except Exception as exc:  # detached helper must leave a durable diagnostic
        _write_failure(codex_home, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
