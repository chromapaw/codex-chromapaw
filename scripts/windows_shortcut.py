#!/usr/bin/env python3
"""Install, inspect, or remove reversible ChromaPaw Windows shortcuts."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from .windows_runtime import RuntimeFailure, atomic_json, runtime_data_dir, sha256_file, utc_now
except ImportError:
    from windows_runtime import (  # type: ignore
        RuntimeFailure,
        atomic_json,
        runtime_data_dir,
        sha256_file,
        utc_now,
    )


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "windows_skin_launcher.py"
RECEIPT_FILE = "start-menu-shortcut.json"
SHORTCUT_DESCRIPTION = "Launch Codex with the last validated ChromaPaw skin"


def _programs_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeFailure("APPDATA is unavailable; the Start Menu shortcut cannot be located")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def default_shortcut_path() -> Path:
    return _programs_dir() / "Codex ChromaPaw.lnk"


def default_desktop_shortcut_path() -> Path:
    if os.name != "nt":
        raise RuntimeFailure("the Windows Desktop folder is unavailable on this platform")
    buffer = ctypes.create_unicode_buffer(32768)
    # CSIDL_DESKTOPDIRECTORY resolves redirected and OneDrive-backed Desktop folders.
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buffer)
    if result != 0 or not buffer.value:
        raise RuntimeFailure("the Windows Desktop folder could not be located")
    return Path(buffer.value) / "Codex ChromaPaw.lnk"


def default_original_shortcut_path() -> Path:
    return _programs_dir() / "ChatGPT.lnk"


def _powershell(command: str, env_values: dict[str, str]) -> str:
    env = os.environ.copy()
    env.update(env_values)
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown PowerShell error"
        raise RuntimeFailure(f"Windows shortcut operation failed: {detail}")
    return completed.stdout.strip()


def inspect_shortcut(path: Path) -> dict[str, str]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise RuntimeFailure(f"Windows shortcut does not exist: {path}")
    output = _powershell(
        "$w=New-Object -ComObject WScript.Shell;"
        "$s=$w.CreateShortcut($env:CHROMAPAW_SHORTCUT);"
        "[pscustomobject]@{target=$s.TargetPath;arguments=$s.Arguments;"
        "workingDirectory=$s.WorkingDirectory;iconLocation=$s.IconLocation;"
        "description=$s.Description}|ConvertTo-Json -Compress",
        {"CHROMAPAW_SHORTCUT": str(path)},
    )
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeFailure("Windows shortcut metadata could not be decoded") from exc
    if not isinstance(value, dict):
        raise RuntimeFailure("Windows shortcut metadata is invalid")
    return {str(key): str(item or "") for key, item in value.items()}


def _normalize_path(value: str) -> str:
    if not value:
        return ""
    return os.path.normcase(str(Path(value).expanduser().resolve()))


def shortcut_semantics(metadata: dict[str, str]) -> dict[str, str]:
    icon_path, separator, icon_index = metadata.get("iconLocation", "").rpartition(",")
    if not separator:
        icon_path, icon_index = metadata.get("iconLocation", ""), ""
    return {
        "target": _normalize_path(metadata.get("target", "")),
        "arguments": metadata.get("arguments", ""),
        "workingDirectory": _normalize_path(metadata.get("workingDirectory", "")),
        "iconPath": _normalize_path(icon_path),
        "iconIndex": icon_index.strip(),
        "description": metadata.get("description", ""),
    }


def shortcut_semantic_hash(metadata: dict[str, str]) -> str:
    payload = json.dumps(
        shortcut_semantics(metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _pythonw_path() -> Path:
    current = Path(sys.executable).resolve()
    candidate = current.with_name("pythonw.exe")
    if os.name == "nt" and candidate.is_file():
        return candidate
    raise RuntimeFailure("pythonw.exe is required for a windowless ChromaPaw shortcut")


def _write_shortcut(
    path: Path,
    *,
    target: Path,
    arguments: str,
    working_directory: Path,
    icon: Path,
    description: str = SHORTCUT_DESCRIPTION,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _powershell(
        "$w=New-Object -ComObject WScript.Shell;"
        "$s=$w.CreateShortcut($env:CHROMAPAW_SHORTCUT);"
        "$s.TargetPath=$env:CHROMAPAW_TARGET;"
        "$s.Arguments=$env:CHROMAPAW_ARGUMENTS;"
        "$s.WorkingDirectory=$env:CHROMAPAW_WORKDIR;"
        "$s.IconLocation=$env:CHROMAPAW_ICON + ',0';"
        "$s.Description=$env:CHROMAPAW_DESCRIPTION;"
        "$s.Save()",
        {
            "CHROMAPAW_SHORTCUT": str(path),
            "CHROMAPAW_TARGET": str(target),
            "CHROMAPAW_ARGUMENTS": arguments,
            "CHROMAPAW_WORKDIR": str(working_directory),
            "CHROMAPAW_ICON": str(icon),
            "CHROMAPAW_DESCRIPTION": description,
        },
    )


def _load_receipt(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / RECEIPT_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeFailure(f"shortcut receipt cannot be read: {exc}") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") not in (1, 2, 3):
        raise RuntimeFailure("shortcut receipt is invalid")
    return value


def _finalize_receipt(data_dir: Path, receipt: dict[str, Any], status: str) -> dict[str, Any]:
    result = {**receipt, "status": status, "restoredAt": utc_now()}
    atomic_json(data_dir / "start-menu-shortcut.restored.json", result)
    (data_dir / RECEIPT_FILE).unlink()
    return result


def _restore_legacy_replacement(data_dir: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    shortcut = Path(str(receipt.get("shortcut", ""))).resolve()
    backup = Path(str(receipt.get("backup", ""))).resolve()
    if not shortcut.is_file() or not backup.is_file():
        raise RuntimeFailure("legacy shortcut or its original backup is missing")
    if sha256_file(backup) != receipt.get("originalHash"):
        raise RuntimeFailure("the original shortcut backup changed")
    current_semantic = shortcut_semantic_hash(inspect_shortcut(shortcut))
    original_semantic = shortcut_semantic_hash(inspect_shortcut(backup))
    if current_semantic == original_semantic:
        return _finalize_receipt(data_dir, receipt, "already-restored-by-application")

    installed = shortcut_semantics(inspect_shortcut(shortcut))
    expected_target = _normalize_path(str(receipt.get("target", "")))
    expected_arguments = str(receipt.get("arguments", ""))
    if installed["target"] != expected_target or installed["arguments"] != expected_arguments:
        raise RuntimeFailure(
            "the legacy shortcut is neither the ChromaPaw entry nor the original entry"
        )
    shutil.copy2(backup, shortcut)
    if shortcut_semantic_hash(inspect_shortcut(shortcut)) != original_semantic:
        raise RuntimeFailure("legacy shortcut restoration verification failed")
    return _finalize_receipt(data_dir, receipt, "restored")


def install_shortcut(
    data_dir: Path,
    shortcut: Path,
    executable: Path,
    adapters: Path,
    *,
    acknowledged: bool,
    original_shortcut: Path | None = None,
    desktop_shortcut: Path | None = None,
) -> dict[str, Any]:
    if not acknowledged:
        raise RuntimeFailure(
            "shortcut installation requires --acknowledge-adds-windows-shortcuts"
        )
    if os.name != "nt":
        raise RuntimeFailure("the ChromaPaw Windows shortcuts are Windows-only")
    data_dir = data_dir.expanduser().resolve()
    shortcut = shortcut.expanduser().resolve()
    original_shortcut = (original_shortcut or default_original_shortcut_path()).expanduser().resolve()
    desktop_shortcut = (desktop_shortcut or default_desktop_shortcut_path()).expanduser().resolve()
    executable = executable.expanduser().resolve()
    adapters = adapters.expanduser().resolve()
    if shortcut.suffix.lower() != ".lnk" or shortcut.parent != original_shortcut.parent:
        raise RuntimeFailure("the ChromaPaw shortcut must stay in the same Start Menu directory")
    if shortcut == original_shortcut:
        raise RuntimeFailure("ChromaPaw must use a separate shortcut and cannot replace ChatGPT.lnk")
    if desktop_shortcut.suffix.lower() != ".lnk":
        raise RuntimeFailure("the ChromaPaw Desktop shortcut must be a .lnk file")
    if desktop_shortcut in (shortcut, original_shortcut):
        raise RuntimeFailure("the Desktop, Start Menu, and original shortcuts must be separate")
    if not executable.is_file() or not LAUNCHER.is_file() or not adapters.is_file():
        raise RuntimeFailure("launcher, adapter registry, and selected Codex executable must exist")

    original = inspect_shortcut(original_shortcut)
    if shortcut_semantics(original)["target"] != _normalize_path(str(executable)):
        raise RuntimeFailure(
            "the existing ChatGPT shortcut does not target the selected Codex executable"
        )
    original_semantic_hash = shortcut_semantic_hash(original)

    receipt = _load_receipt(data_dir)
    if receipt is not None and receipt.get("schemaVersion") == 1:
        raise RuntimeFailure("restore the legacy replacement receipt before adding the new shortcut")
    managed_paths = {
        "start-menu": shortcut,
        "desktop": desktop_shortcut,
    }
    previous_bytes: dict[Path, bytes | None] = {}
    if receipt is None:
        for path in managed_paths.values():
            if path.exists():
                raise RuntimeFailure(f"refusing to overwrite an unmanaged shortcut: {path}")
            previous_bytes[path] = None
    elif receipt.get("schemaVersion") == 2:
        if receipt.get("mode") != "add" or str(shortcut) != receipt.get("shortcut"):
            raise RuntimeFailure("the installed Start Menu shortcut differs from the receipt")
        if not shortcut.is_file() or shortcut_semantic_hash(
            inspect_shortcut(shortcut)
        ) != receipt.get("installedSemanticHash"):
            raise RuntimeFailure("the installed Start Menu shortcut changed outside ChromaPaw")
        if desktop_shortcut.exists():
            raise RuntimeFailure(f"refusing to overwrite an unmanaged shortcut: {desktop_shortcut}")
        previous_bytes[shortcut] = shortcut.read_bytes()
        previous_bytes[desktop_shortcut] = None
    else:
        if receipt.get("mode") != "add" or receipt.get("schemaVersion") != 3:
            raise RuntimeFailure("the installed shortcuts differ from the existing receipt")
        receipt_entries = receipt.get("shortcuts")
        if not isinstance(receipt_entries, list):
            raise RuntimeFailure("the shortcut receipt entries are invalid")
        expected = {
            str(entry.get("kind")): entry
            for entry in receipt_entries
            if isinstance(entry, dict)
        }
        for kind, path in managed_paths.items():
            entry = expected.get(kind)
            if not entry or str(path) != entry.get("path"):
                raise RuntimeFailure(f"the installed {kind} shortcut differs from the receipt")
            if not path.is_file() or shortcut_semantic_hash(
                inspect_shortcut(path)
            ) != entry.get("installedSemanticHash"):
                raise RuntimeFailure(f"the installed {kind} shortcut changed outside ChromaPaw")
            previous_bytes[path] = path.read_bytes()

    pythonw = _pythonw_path()
    arguments = subprocess.list2cmdline(
        [
            str(LAUNCHER),
            "--data-dir",
            str(data_dir),
            "--adapters",
            str(adapters),
            "--acknowledge-experimental-runtime",
        ]
    )
    try:
        installed_entries = []
        for kind, path in managed_paths.items():
            _write_shortcut(
                path,
                target=pythonw,
                arguments=arguments,
                working_directory=ROOT,
                icon=executable,
            )
            installed = inspect_shortcut(path)
            if shortcut_semantics(installed)["target"] != _normalize_path(
                str(pythonw)
            ) or installed["arguments"] != arguments:
                raise RuntimeFailure(f"{kind} shortcut semantic verification failed")
            installed_entries.append(
                {
                    "kind": kind,
                    "path": str(path),
                    "installedSemanticHash": shortcut_semantic_hash(installed),
                    "installedFileHashInformational": sha256_file(path),
                }
            )
    except Exception:
        for path, content in previous_bytes.items():
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                path.write_bytes(content)
        raise

    result = {
        "schemaVersion": 3,
        "mode": "add",
        "status": "installed",
        "installedAt": utc_now(),
        "shortcuts": installed_entries,
        "originalShortcut": str(original_shortcut),
        "originalShortcutSemanticHash": original_semantic_hash,
        "target": str(pythonw),
        "arguments": arguments,
        "selectedExecutable": str(executable),
        "selectedExecutableHash": sha256_file(executable),
        "launcher": str(LAUNCHER),
        "launcherHash": sha256_file(LAUNCHER),
        "adapterFile": str(adapters),
        "adapterFileHash": sha256_file(adapters),
        "modifiesOriginalShortcut": False,
        "modifiesCodexApplicationFiles": False,
    }
    atomic_json(data_dir / RECEIPT_FILE, result)
    return result


def restore_shortcut(data_dir: Path) -> dict[str, Any]:
    data_dir = data_dir.expanduser().resolve()
    receipt = _load_receipt(data_dir)
    if receipt is None:
        raise RuntimeFailure("no ChromaPaw Windows shortcut receipt exists")
    if receipt.get("schemaVersion") == 1:
        return _restore_legacy_replacement(data_dir, receipt)
    if receipt.get("mode") != "add":
        raise RuntimeFailure("unsupported shortcut receipt mode")
    if receipt.get("schemaVersion") == 2:
        entries = [
            {
                "kind": "start-menu",
                "path": receipt.get("shortcut"),
                "installedSemanticHash": receipt.get("installedSemanticHash"),
            }
        ]
    else:
        entries = receipt.get("shortcuts")
        if not isinstance(entries, list) or not entries:
            raise RuntimeFailure("the managed shortcut receipt entries are invalid")
    verified: list[tuple[Path, bytes]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeFailure("the managed shortcut receipt entries are invalid")
        path = Path(str(entry.get("path", ""))).resolve()
        if not path.is_file() or shortcut_semantic_hash(
            inspect_shortcut(path)
        ) != entry.get("installedSemanticHash"):
            raise RuntimeFailure(
                f"the managed {entry.get('kind', 'Windows')} shortcut changed; refusing to remove any shortcut"
            )
        verified.append((path, path.read_bytes()))
    removed: list[tuple[Path, bytes]] = []
    try:
        for path, content in verified:
            path.unlink()
            removed.append((path, content))
            if path.exists():
                raise RuntimeFailure(f"the managed ChromaPaw shortcut could not be removed: {path}")
    except Exception:
        for path, content in removed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        raise
    return _finalize_receipt(data_dir, receipt, "removed")


def shortcut_status(data_dir: Path) -> dict[str, Any]:
    data_dir = data_dir.expanduser().resolve()
    receipt = _load_receipt(data_dir)
    if receipt is None:
        return {"ok": True, "status": "not-installed", "dataDir": str(data_dir)}
    if receipt.get("schemaVersion") == 1:
        return {
            "ok": False,
            "status": "legacy-replacement-receipt",
            "shortcut": receipt.get("shortcut"),
            "backup": receipt.get("backup"),
        }
    original = Path(str(receipt.get("originalShortcut", ""))).resolve()
    if receipt.get("schemaVersion") == 2:
        entries = [
            {
                "kind": "start-menu",
                "path": receipt.get("shortcut"),
                "installedSemanticHash": receipt.get("installedSemanticHash"),
            }
        ]
    else:
        entries = receipt.get("shortcuts") if isinstance(receipt.get("shortcuts"), list) else []
    shortcut_results = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = Path(str(entry.get("path", ""))).resolve()
        matches = path.is_file() and shortcut_semantic_hash(
            inspect_shortcut(path)
        ) == entry.get("installedSemanticHash")
        shortcut_results.append(
            {"kind": entry.get("kind"), "path": str(path), "semanticMatches": matches}
        )
    shortcut_matches = bool(shortcut_results) and all(
        entry["semanticMatches"] for entry in shortcut_results
    )
    original_matches = original.is_file() and shortcut_semantic_hash(
        inspect_shortcut(original)
    ) == receipt.get("originalShortcutSemanticHash")
    return {
        "ok": shortcut_matches and original_matches,
        "status": "installed" if shortcut_matches and original_matches else "drifted",
        "shortcuts": shortcut_results,
        "originalShortcut": str(original),
        "allShortcutSemanticsMatch": shortcut_matches,
        "originalShortcutSemanticMatches": original_matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install")
    install.add_argument("--shortcut", type=Path, default=default_shortcut_path())
    install.add_argument("--desktop-shortcut", type=Path, default=default_desktop_shortcut_path())
    install.add_argument("--original-shortcut", type=Path, default=default_original_shortcut_path())
    install.add_argument("--executable", type=Path, required=True)
    install.add_argument("--adapters", type=Path, default=ROOT / "runtime" / "windows-adapters.json")
    install.add_argument("--acknowledge-adds-start-menu-shortcut", action="store_true")
    install.add_argument("--acknowledge-adds-windows-shortcuts", action="store_true")
    install.add_argument("--acknowledge-replaces-start-menu-shortcut", action="store_true")
    subparsers.add_parser("restore")
    subparsers.add_parser("status")

    args = parser.parse_args()
    data_dir = runtime_data_dir(args.data_dir)
    try:
        if args.command == "install":
            result = install_shortcut(
                data_dir,
                args.shortcut,
                args.executable,
                args.adapters,
                acknowledged=(
                    args.acknowledge_adds_start_menu_shortcut
                    or args.acknowledge_adds_windows_shortcuts
                    or args.acknowledge_replaces_start_menu_shortcut
                ),
                original_shortcut=args.original_shortcut,
                desktop_shortcut=args.desktop_shortcut,
            )
        elif args.command == "restore":
            result = restore_shortcut(data_dir)
        else:
            result = shortcut_status(data_dir)
    except (OSError, RuntimeFailure, ValueError) as exc:
        result = {"ok": False, "command": args.command, "error": str(exc)}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get("status", "OK"))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
