#!/usr/bin/env python3
"""Reversible, version-gated ChromaPaw skin runtime for Windows Electron builds."""

from __future__ import annotations

import argparse
import base64
import contextlib
import ctypes
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    from .cdp_client import CdpEndpoint, CdpError, inject_css, remove_css, verify_css
    from .skin_package import path_is_inside, safe_relative_path
    from .validate_skin_package import validate_package
except ImportError:
    from cdp_client import CdpEndpoint, CdpError, inject_css, remove_css, verify_css  # type: ignore
    from skin_package import path_is_inside, safe_relative_path  # type: ignore
    from validate_skin_package import validate_package  # type: ignore


RUNTIME_VERSION = "0.4.0"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADAPTERS = ROOT / "runtime" / "windows-adapters.json"
ACTIVE_FILE = "active.json"
LOCK_FILE = ".runtime.lock"
STYLE_MARKER = 'data-avatar-overlay-content-frame="true"'
BACKGROUND_URL = re.compile(r"url\(\s*(['\"]?)\./background\.png\1\s*\)")
VOLATILE_CONFIG_KEYS = {"SKY_CUA_NATIVE_PIPE_DIRECTORY"}
APP_VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+){3}$")
SENSITIVE_RESULT_KEYS = {"sessionToken", "session"}


class RuntimeFailure(RuntimeError):
    """Raised when a runtime safety or compatibility gate fails."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    except OSError as exc:
        raise RuntimeFailure(f"file cannot be hashed: {path}: {exc}") from exc
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def runtime_data_dir(override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    explicit = os.environ.get("CHROMAPAW_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return (codex_home / "chromapaw" / "runtime" / "windows").resolve()


@contextlib.contextmanager
def runtime_lock(data_dir: Path) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = data_dir / LOCK_FILE
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeFailure(f"another ChromaPaw runtime operation is active: {lock}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()} time={utc_now()}\n".encode("utf-8"))
        os.close(descriptor)
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def load_adapters(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeFailure(f"runtime adapter file cannot be read: {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise RuntimeFailure("runtime adapter file must be a schemaVersion 1 object")
    adapters = data.get("adapters")
    if not isinstance(adapters, list) or not adapters:
        raise RuntimeFailure("runtime adapter file must contain adapters")
    transport = data.get("transport")
    if not isinstance(transport, dict) or (
        transport.get("kind") != "electron-cdp-loopback"
        or transport.get("host") != "127.0.0.1"
        or transport.get("port") != "ephemeral"
    ):
        raise RuntimeFailure(
            "runtime adapter transport must use an ephemeral Electron CDP endpoint on 127.0.0.1"
        )
    monitor = transport.get("backgroundMonitor")
    if not isinstance(monitor, dict) or monitor.get("enabled") is not True:
        raise RuntimeFailure("runtime adapter transport must disclose the enabled background monitor")
    interval = monitor.get("intervalSeconds")
    if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval != 1.0:
        raise RuntimeFailure("runtime adapter monitor interval must be exactly 1 second")
    seen_ids: set[str] = set()
    seen_targets: set[tuple[str, str]] = set()
    for adapter in adapters:
        if not isinstance(adapter, dict):
            raise RuntimeFailure("every runtime adapter must be an object")
        adapter_id = adapter.get("id")
        version = adapter.get("appVersion")
        executable_name = adapter.get("executableName")
        if not isinstance(adapter_id, str) or not adapter_id:
            raise RuntimeFailure("every runtime adapter must have a non-empty id")
        if adapter_id in seen_ids:
            raise RuntimeFailure(f"duplicate runtime adapter id: {adapter_id}")
        if not isinstance(version, str) or APP_VERSION_PATTERN.fullmatch(version) is None:
            raise RuntimeFailure(f"adapter {adapter_id} has an invalid appVersion")
        if not isinstance(executable_name, str) or not executable_name.lower().endswith(".exe"):
            raise RuntimeFailure(f"adapter {adapter_id} has an invalid executableName")
        target = (version, executable_name.lower())
        if target in seen_targets:
            raise RuntimeFailure(
                f"duplicate runtime adapter target: {version} {executable_name}"
            )
        if not isinstance(adapter.get("activationEnabled"), bool):
            raise RuntimeFailure(f"adapter {adapter_id} must declare activationEnabled")
        schemes = adapter.get("allowedTargetSchemes")
        if not isinstance(schemes, list) or not schemes or not all(
            isinstance(value, str) and value for value in schemes
        ):
            raise RuntimeFailure(f"adapter {adapter_id} has invalid target schemes")
        prefixes = adapter.get("browserProductPrefixes")
        if not isinstance(prefixes, list) or not prefixes or not all(
            isinstance(value, str) and value for value in prefixes
        ):
            raise RuntimeFailure(f"adapter {adapter_id} has invalid browser product prefixes")
        if not isinstance(adapter.get("testedTarget"), str) or not adapter["testedTarget"]:
            raise RuntimeFailure(f"adapter {adapter_id} must describe its tested target")
        seen_ids.add(adapter_id)
        seen_targets.add(target)
    return data


def detect_app_version(executable: Path) -> str | None:
    patterns = (
        re.compile(r"^app-(\d+(?:\.\d+){3})$", re.IGNORECASE),
        re.compile(r"^OpenAI\.Codex_(\d+(?:\.\d+){3})_", re.IGNORECASE),
    )
    for part in executable.resolve().parts:
        for pattern in patterns:
            match = pattern.match(part)
            if match:
                return match.group(1)
    return None


def select_adapter(
    executable: Path, adapter_path: Path = DEFAULT_ADAPTERS, *, require_enabled: bool = True
) -> dict[str, Any]:
    executable = executable.expanduser().resolve()
    if not executable.is_file():
        raise RuntimeFailure(f"Codex executable does not exist: {executable}")
    version = detect_app_version(executable)
    if version is None:
        raise RuntimeFailure("Codex application version could not be derived from the executable path")
    data = load_adapters(adapter_path)
    for adapter in data["adapters"]:
        if not isinstance(adapter, dict):
            continue
        if adapter.get("appVersion") != version:
            continue
        if str(adapter.get("executableName", "")).lower() != executable.name.lower():
            continue
        if require_enabled and adapter.get("activationEnabled") is not True:
            raise RuntimeFailure(
                f"adapter {adapter.get('id')} recognizes Codex {version}, but activation is disabled "
                "until isolated live verification passes"
            )
        schemes = adapter.get("allowedTargetSchemes")
        if not isinstance(schemes, list) or not schemes or not all(
            isinstance(value, str) and value for value in schemes
        ):
            raise RuntimeFailure(f"adapter {adapter.get('id')} has invalid target schemes")
        return adapter
    raise RuntimeFailure(
        f"Codex {version} is not supported by the exact-version Windows adapter list"
    )


def _discover_appx_install_locations() -> list[Path]:
    """Ask the package registry for Codex locations without touching WindowsApps."""
    if os.name != "nt":
        return []
    command = (
        "$ProgressPreference='SilentlyContinue'; "
        "Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue | "
        "ForEach-Object { $_.InstallLocation }"
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    return [Path(line.strip()) for line in completed.stdout.splitlines() if line.strip()]


def discover_executables(adapter_path: Path = DEFAULT_ADAPTERS) -> list[dict[str, Any]]:
    candidates: set[Path] = set()
    explicit = os.environ.get("CHROMAPAW_CODEX_EXE")
    if explicit:
        candidates.add(Path(explicit).expanduser())
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    for path in local.glob("Codex*/app-*/ChatGPT.exe"):
        candidates.add(path)
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    windows_apps = program_files / "WindowsApps"
    if windows_apps.is_dir():
        with contextlib.suppress(OSError):
            for path in windows_apps.glob("OpenAI.Codex_*/app/ChatGPT.exe"):
                candidates.add(path)
    for install_location in _discover_appx_install_locations():
        candidates.add(install_location / "app" / "ChatGPT.exe")

    results = []
    for path in sorted(candidates, key=lambda item: str(item).lower()):
        resolved = path.resolve()
        if not resolved.is_file():
            continue
        version = detect_app_version(resolved)
        adapter_id = None
        activation_enabled = False
        reason = None
        try:
            adapter = select_adapter(resolved, adapter_path, require_enabled=False)
            adapter_id = adapter.get("id")
            activation_enabled = adapter.get("activationEnabled") is True
        except RuntimeFailure as exc:
            reason = str(exc)
        results.append(
            {
                "executable": str(resolved),
                "appVersion": version,
                "adapterId": adapter_id,
                "activationEnabled": activation_enabled,
                "reason": reason,
            }
        )
    return results


def _windows_process_paths() -> dict[int, Path]:
    if os.name != "nt":
        return {}
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process_ids = (wintypes.DWORD * 8192)()
    bytes_returned = wintypes.DWORD()
    if not psapi.EnumProcesses(
        ctypes.byref(process_ids), ctypes.sizeof(process_ids), ctypes.byref(bytes_returned)
    ):
        return {}
    count = bytes_returned.value // ctypes.sizeof(wintypes.DWORD)
    results: dict[int, Path] = {}
    for pid in process_ids[:count]:
        if not pid:
            continue
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                results[int(pid)] = Path(buffer.value).resolve()
        finally:
            kernel32.CloseHandle(handle)
    return results


def running_pids(executable: Path) -> list[int]:
    expected = os.path.normcase(str(executable.resolve()))
    return sorted(
        pid
        for pid, path in _windows_process_paths().items()
        if os.path.normcase(str(path)) == expected
    )


def _package_asset(root: Path, value: object, field: str) -> Path:
    relative, error = safe_relative_path(value, field)
    if error or relative is None:
        raise RuntimeFailure(error or f"{field} is invalid")
    resolved = (root / relative).resolve()
    if not path_is_inside(root, resolved) or not resolved.is_file():
        raise RuntimeFailure(f"{field} does not resolve to a package file")
    return resolved


def compile_skin(package_dir: Path) -> dict[str, Any]:
    root = package_dir.expanduser().resolve()
    errors = validate_package(root)
    if errors:
        raise RuntimeFailure("skin package validation failed: " + "; ".join(errors))
    manifest_path = root / "skin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 2:
        raise RuntimeFailure("Windows runtime requires a Skin Studio schemaVersion 2 package")
    assets = manifest["assets"]
    stylesheet = _package_asset(root, assets.get("stylesheet"), "assets.stylesheet")
    background = _package_asset(root, assets.get("background"), "assets.background")
    css = stylesheet.read_text(encoding="utf-8")
    if STYLE_MARKER not in css:
        raise RuntimeFailure("stylesheet is missing the mandatory pet-overlay isolation guard")
    try:
        background_bytes = background.read_bytes()
    except OSError as exc:
        raise RuntimeFailure(f"background cannot be read: {exc}") from exc
    mime = mimetypes.guess_type(background.name)[0] or "application/octet-stream"
    if mime not in {"image/png", "image/webp", "image/jpeg"}:
        raise RuntimeFailure("background must be PNG, WebP, or JPEG")
    data_uri = f"data:{mime};base64,{base64.b64encode(background_bytes).decode('ascii')}"
    compiled, replacements = BACKGROUND_URL.subn(f'url("{data_uri}")', css)
    if replacements < 1:
        raise RuntimeFailure("stylesheet does not contain the expected package background URL")
    compiled += f"\n/* ChromaPaw runtime {RUNTIME_VERSION}; package {manifest['id']} */\n"
    css_hash = hashlib.sha256(compiled.encode("utf-8")).hexdigest()
    return {
        "packageDir": root,
        "manifest": manifest,
        "manifestHash": sha256_file(manifest_path),
        "stylesheet": stylesheet,
        "background": background,
        "css": compiled,
        "cssHash": css_hash,
    }


def choose_ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


def _validate_browser_identity(version: dict[str, Any], adapter: dict[str, Any]) -> None:
    browser = version.get("Browser")
    prefixes = adapter.get("browserProductPrefixes")
    if not isinstance(browser, str) or not isinstance(prefixes, list) or not any(
        browser.startswith(prefix) for prefix in prefixes if isinstance(prefix, str)
    ):
        raise RuntimeFailure(f"CDP browser identity is not accepted by adapter {adapter.get('id')}")
    websocket_url = version.get("webSocketDebuggerUrl")
    if not isinstance(websocket_url, str) or not websocket_url.startswith("ws://127.0.0.1:"):
        raise RuntimeFailure("CDP browser websocket is not bound to 127.0.0.1")


def wait_for_endpoint(
    endpoint: CdpEndpoint, adapter: dict[str, Any], timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            version = endpoint.version()
            _validate_browser_identity(version, adapter)
            return version
        except (CdpError, RuntimeFailure) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeFailure(f"Codex CDP endpoint did not become ready: {last_error}")


def _results_pass(results: list[dict[str, Any]], key: str) -> bool:
    return bool(results) and all(
        isinstance(item.get("result"), dict) and item["result"].get(key) is True
        for item in results
    )


def inject_until_ready(
    endpoint: CdpEndpoint,
    compiled: dict[str, Any],
    session_token: str,
    schemes: set[str],
    timeout: float,
    settle_seconds: float = 0.5,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last_results: list[dict[str, Any]] = []
    last_error: Exception | None = None
    stable_since: float | None = None
    stable_targets: set[str] = set()
    while time.monotonic() < deadline:
        try:
            last_results = inject_css(
                endpoint,
                str(compiled["css"]),
                str(compiled["cssHash"]),
                session_token,
                schemes,
            )
            if _results_pass(last_results, "applied"):
                target_ids = {str(item.get("targetId")) for item in last_results}
                now = time.monotonic()
                if target_ids != stable_targets:
                    stable_targets = target_ids
                    stable_since = now
                elif stable_since is not None and now - stable_since >= settle_seconds:
                    return last_results
            else:
                stable_since = None
                stable_targets = set()
        except CdpError as exc:
            last_error = exc
        time.sleep(0.4)
    raise RuntimeFailure(
        f"skin CSS could not be applied to every eligible Codex page: {last_error or last_results}"
    )


def _codex_config_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"


def create_backup(data_dir: Path, session_id: str, preflight: dict[str, Any]) -> dict[str, Any]:
    backup_dir = data_dir / "sessions" / session_id
    backup_dir.mkdir(parents=True, exist_ok=False)
    config = _codex_config_path().expanduser().resolve()
    config_backup = None
    config_hash = None
    if config.is_file():
        config_hash = sha256_file(config)
        config_backup_path = backup_dir / "config.toml.before"
        shutil.copy2(config, config_backup_path)
        config_backup = str(config_backup_path)
    snapshot = {
        "schemaVersion": 1,
        "createdAt": utc_now(),
        "runtimeVersion": RUNTIME_VERSION,
        "operation": "in-memory-css-injection",
        "modifiesApplicationFiles": False,
        "modifiesCodexConfig": False,
        "codexConfig": str(config),
        "codexConfigHash": config_hash,
        "codexConfigBackup": config_backup,
        "preflight": preflight,
    }
    atomic_json(backup_dir / "before.json", snapshot)
    return {"backupDir": str(backup_dir), **snapshot}


def _read_active(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / ACTIVE_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeFailure(f"active runtime state cannot be read: {exc}") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise RuntimeFailure("active runtime state is invalid")
    return value


def _append_history(data_dir: Path, event: dict[str, Any]) -> None:
    path = data_dir / "history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def build_preflight(
    package: Path,
    executable: Path,
    adapters: Path = DEFAULT_ADAPTERS,
    *,
    require_enabled: bool = True,
) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeFailure("the reversible skin runtime is Windows-only")
    executable = executable.expanduser().resolve()
    adapters = adapters.expanduser().resolve()
    adapter = select_adapter(executable, adapters, require_enabled=require_enabled)
    compiled = compile_skin(package)
    version = detect_app_version(executable)
    return {
        "ok": True,
        "runtimeVersion": RUNTIME_VERSION,
        "experimentalInterface": "Electron Chrome DevTools Protocol",
        "officialSkinApi": False,
        "executable": str(executable),
        "executableHash": sha256_file(executable),
        "appVersion": version,
        "adapterId": adapter["id"],
        "adapterFile": str(adapters),
        "adapterFileHash": sha256_file(adapters),
        "activationEnabled": adapter.get("activationEnabled") is True,
        "allowedTargetSchemes": adapter["allowedTargetSchemes"],
        "runningPids": running_pids(executable),
        "package": str(compiled["packageDir"]),
        "packageId": compiled["manifest"]["id"],
        "manifestHash": compiled["manifestHash"],
        "cssHash": compiled["cssHash"],
        "applicationFilesWillBeModified": False,
        "codexConfigWillBeModified": False,
        "transport": {"host": "127.0.0.1", "port": "ephemeral", "authenticated": False},
        "backgroundMonitor": {"enabled": True, "intervalSeconds": 1.0},
    }


def _adapter_for_state(state: dict[str, Any]) -> dict[str, Any]:
    adapter_file_value = state.get("adapterFile")
    expected_hash = state.get("adapterFileHash")
    if not isinstance(adapter_file_value, str) or not isinstance(expected_hash, str):
        raise RuntimeFailure("runtime state is missing the adapter identity")
    adapter_file = Path(adapter_file_value).expanduser().resolve()
    if sha256_file(adapter_file) != expected_hash:
        raise RuntimeFailure("runtime adapter file changed after activation")
    executable = Path(str(state.get("executable"))).expanduser().resolve()
    adapter = select_adapter(executable, adapter_file)
    if adapter.get("id") != state.get("adapterId"):
        raise RuntimeFailure("runtime adapter identity changed after activation")
    return adapter


def _launch_codex(
    executable: Path,
    port: int,
    profile_dir: Path | None,
) -> subprocess.Popen[bytes]:
    args = [
        str(executable),
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--remote-allow-origins=http://127.0.0.1:{port}",
    ]
    if profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        args.extend((f"--user-data-dir={profile_dir}", "--start-minimized"))
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        return subprocess.Popen(
            args,
            cwd=executable.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise RuntimeFailure(f"Codex could not be launched: {exc}") from exc


def _launch_monitor(data_dir: Path, session_id: str) -> subprocess.Popen[bytes]:
    args = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--data-dir",
        str(data_dir),
        "monitor",
        "--session-id",
        session_id,
    ]
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess, "CREATE_NO_WINDOW", 0
    )
    try:
        return subprocess.Popen(
            args,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise RuntimeFailure(f"runtime monitor could not be started: {exc}") from exc


def _terminate_process_tree(
    pid: object, executable: object, *, label: str, timeout: float = 10.0
) -> dict[str, Any]:
    if not isinstance(pid, int) or not isinstance(executable, str):
        raise RuntimeFailure(f"runtime state does not contain a valid {label} process")
    process_path = _windows_process_paths().get(pid)
    if process_path is None:
        return {"terminated": True, "reason": "already-exited", "pid": pid, "label": label}
    if os.path.normcase(str(process_path)) != os.path.normcase(str(Path(executable).resolve())):
        raise RuntimeFailure(f"refusing to terminate a {label} PID whose executable identity changed")
    completed = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and pid in _windows_process_paths():
        time.sleep(0.2)
    if pid in _windows_process_paths():
        raise RuntimeFailure(f"runtime {label} process {pid} did not stop")
    return {
        "terminated": True,
        "pid": pid,
        "label": label,
        "commandExitCode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _terminate_runtime_process(state: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    return _terminate_process_tree(
        state.get("pid"),
        state.get("executable"),
        label="Codex",
        timeout=timeout,
    )


def _terminate_monitor_process(state: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    return _terminate_process_tree(
        state.get("monitorPid"),
        state.get("monitorExecutable"),
        label="monitor",
        timeout=timeout,
    )


def monitor_runtime(data_dir: Path, session_id: str, interval: float = 1.0) -> int:
    """Keep newly-created Codex windows synchronized until the session stops."""
    log_path: Path | None = None
    try:
        state = _read_active(data_dir)
        if state is None or state.get("sessionId") != session_id:
            return 2
        log_path = Path(str(state["backupDir"])) / "monitor.jsonl"
        compiled = compile_skin(Path(str(state["package"])))
        if compiled["cssHash"] != state.get("cssHash"):
            raise RuntimeFailure("skin package changed after monitor startup")
        endpoint = CdpEndpoint(int(state["port"]), timeout=4.0)
        adapter = _adapter_for_state(state)
        _validate_browser_identity(endpoint.version(), adapter)
        schemes = set(state["allowedTargetSchemes"])
        session_token = str(state["sessionToken"])
        css_hash = str(state["cssHash"])
        last_target_ids: set[str] = set()
        while True:
            current = _read_active(data_dir)
            if current is None or current.get("sessionId") != session_id:
                return 0
            try:
                checks = verify_css(endpoint, css_hash, session_token, schemes)
                target_ids = {str(item.get("targetId")) for item in checks}
                needs_repair = not _results_pass(checks, "matches")
                if needs_repair:
                    applied = inject_css(
                        endpoint,
                        str(compiled["css"]),
                        css_hash,
                        session_token,
                        schemes,
                    )
                    if not _results_pass(applied, "applied"):
                        raise RuntimeFailure(f"monitor could not style every target: {applied}")
                    _append_history(
                        data_dir,
                        {
                            "time": utc_now(),
                            "event": "monitor-repaired-targets",
                            "sessionId": session_id,
                            "targetIds": sorted(target_ids),
                        },
                    )
                elif target_ids != last_target_ids:
                    _append_history(
                        data_dir,
                        {
                            "time": utc_now(),
                            "event": "monitor-observed-targets",
                            "sessionId": session_id,
                            "targetIds": sorted(target_ids),
                        },
                    )
                last_target_ids = target_ids
            except CdpError as exc:
                if not _windows_process_paths().get(int(state["pid"])):
                    return 0
                _append_history(
                    data_dir,
                    {
                        "time": utc_now(),
                        "event": "monitor-cdp-error",
                        "sessionId": session_id,
                        "error": str(exc),
                    },
                )
            time.sleep(max(0.5, interval))
    except Exception as exc:
        event = {
            "time": utc_now(),
            "event": "monitor-failed",
            "sessionId": session_id,
            "error": str(exc),
        }
        with contextlib.suppress(Exception):
            _append_history(data_dir, event)
        if log_path is not None:
            with contextlib.suppress(OSError):
                with log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        return 1


def activate_runtime(
    package: Path,
    executable: Path,
    data_dir: Path,
    adapters: Path,
    *,
    acknowledged: bool,
    profile_dir: Path | None,
    allow_parallel_profile: bool,
    wait_seconds: float,
) -> dict[str, Any]:
    if not acknowledged:
        raise RuntimeFailure(
            "activation requires --acknowledge-experimental-runtime because Codex has no official skin API"
        )
    with runtime_lock(data_dir):
        if _read_active(data_dir) is not None:
            raise RuntimeFailure("an active ChromaPaw Windows runtime session already exists")
        preflight = build_preflight(package, executable, adapters)
        if preflight["runningPids"] and not (profile_dir is not None and allow_parallel_profile):
            raise RuntimeFailure(
                "the selected Codex executable is already running; close it before activation, or use "
                "an isolated --profile-dir with --allow-parallel-profile for compatibility testing"
            )
        compiled = compile_skin(package)
        adapter = select_adapter(executable, adapters)
        session_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
        session_token = secrets.token_urlsafe(24)
        backup = create_backup(data_dir, session_id, preflight)
        port = choose_ephemeral_port()
        endpoint = CdpEndpoint(port, timeout=5.0)
        schemes = set(adapter["allowedTargetSchemes"])
        process: subprocess.Popen[bytes] | None = None
        try:
            process = _launch_codex(executable.expanduser().resolve(), port, profile_dir)
            browser = wait_for_endpoint(endpoint, adapter, wait_seconds)
            if process.poll() is not None:
                raise RuntimeFailure("runtime-launched Codex exited before activation completed")
            applied = inject_until_ready(
                endpoint,
                compiled,
                session_token,
                schemes,
                wait_seconds,
                settle_seconds=min(10.0, max(2.0, wait_seconds / 3)),
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                remove_css(endpoint, str(compiled["cssHash"]), session_token, schemes)
            failed_state: dict[str, Any] = {
                "schemaVersion": 1,
                "sessionId": session_id,
                "executable": str(executable.expanduser().resolve()),
                "backupDir": backup["backupDir"],
            }
            if process is not None:
                failed_state["pid"] = process.pid
                with contextlib.suppress(Exception):
                    _terminate_runtime_process(failed_state)
            config_status = _config_backup_status(failed_state)
            failure = {
                "schemaVersion": 1,
                "sessionId": session_id,
                "status": "activation-failed",
                "failedAt": utc_now(),
                "error": str(exc),
                "processLaunched": process is not None,
                "config": config_status,
            }
            atomic_json(Path(backup["backupDir"]) / "failure.json", failure)
            _append_history(data_dir, failure)
            raise RuntimeFailure(f"activation failed and was rolled back: {exc}") from exc

        if process is None:  # pragma: no cover - guarded by the try block
            raise RuntimeFailure("runtime launch returned no process")

        state = {
            "schemaVersion": 1,
            "runtimeVersion": RUNTIME_VERSION,
            "sessionId": session_id,
            "sessionToken": session_token,
            "status": "active",
            "startedAt": utc_now(),
            "pid": process.pid,
            "launchedByRuntime": True,
            "executable": preflight["executable"],
            "executableHash": preflight["executableHash"],
            "appVersion": preflight["appVersion"],
            "adapterId": preflight["adapterId"],
            "adapterFile": preflight["adapterFile"],
            "adapterFileHash": preflight["adapterFileHash"],
            "port": port,
            "allowedTargetSchemes": sorted(schemes),
            "browser": browser,
            "package": preflight["package"],
            "packageId": preflight["packageId"],
            "manifestHash": preflight["manifestHash"],
            "cssHash": preflight["cssHash"],
            "profileDir": str(profile_dir.resolve()) if profile_dir is not None else None,
            "backupDir": backup["backupDir"],
            "appliedTargets": applied,
            "applicationFilesModified": False,
            "codexConfigModified": False,
            "transportDisclosure": (
                f"Unauthenticated Chrome DevTools Protocol bound to 127.0.0.1:{port}; "
                "the port closes when the runtime-launched Codex process stops."
            ),
        }
        atomic_json(data_dir / ACTIVE_FILE, state)
        atomic_json(Path(backup["backupDir"]) / "active.json", state)
        monitor: subprocess.Popen[bytes] | None = None
        try:
            monitor = _launch_monitor(data_dir, session_id)
            state["monitorPid"] = monitor.pid
            state["monitorExecutable"] = str(Path(sys.executable).resolve())
            state["monitorExecutableHash"] = sha256_file(Path(sys.executable).resolve())
            state["monitorIntervalSeconds"] = 1.0
            state["backgroundMonitorDisclosure"] = (
                "A hidden local Python monitor checks the active loopback CDP targets once per second "
                "and injects CSS only when a new or unstyled Codex page appears."
            )
            atomic_json(data_dir / ACTIVE_FILE, state)
            atomic_json(Path(backup["backupDir"]) / "active.json", state)
            time.sleep(0.25)
            if monitor.poll() is not None:
                raise RuntimeFailure("background runtime monitor exited during startup")
        except Exception as exc:
            if monitor is not None and monitor.poll() is None:
                with contextlib.suppress(Exception):
                    _terminate_monitor_process(state)
            with contextlib.suppress(Exception):
                remove_css(endpoint, str(compiled["cssHash"]), session_token, schemes)
            with contextlib.suppress(Exception):
                _terminate_runtime_process(state)
            config_status = _config_backup_status(state)
            failure = {
                "schemaVersion": 1,
                "sessionId": session_id,
                "status": "activation-failed",
                "failedAt": utc_now(),
                "error": str(exc),
                "processLaunched": True,
                "config": config_status,
            }
            atomic_json(Path(backup["backupDir"]) / "failure.json", failure)
            _append_history(data_dir, failure)
            with contextlib.suppress(OSError):
                (data_dir / ACTIVE_FILE).unlink()
            raise RuntimeFailure(f"activation failed and was rolled back: {exc}") from exc
        _append_history(
            data_dir,
            {
                "time": utc_now(),
                "event": "activated",
                "sessionId": session_id,
                "packageId": state["packageId"],
                "appVersion": state["appVersion"],
                "port": port,
            },
        )
        return state


def verify_runtime(data_dir: Path, *, repair: bool = False) -> dict[str, Any]:
    with runtime_lock(data_dir):
        state = _read_active(data_dir)
        if state is None:
            raise RuntimeFailure("no active ChromaPaw Windows runtime session exists")
        executable = Path(str(state["executable"]))
        if sha256_file(executable) != state.get("executableHash"):
            raise RuntimeFailure("Codex executable hash changed after activation")
        pid = state.get("pid")
        process_path = _windows_process_paths().get(pid) if isinstance(pid, int) else None
        if process_path is None or os.path.normcase(str(process_path)) != os.path.normcase(
            str(executable.resolve())
        ):
            raise RuntimeFailure("runtime-launched Codex process is no longer running")
        monitor_pid = state.get("monitorPid")
        monitor_path = (
            _windows_process_paths().get(monitor_pid) if isinstance(monitor_pid, int) else None
        )
        monitor_expected = state.get("monitorExecutable")
        monitor_matches = (
            monitor_path is not None
            and isinstance(monitor_expected, str)
            and os.path.normcase(str(monitor_path))
            == os.path.normcase(str(Path(monitor_expected).resolve()))
        )
        if not monitor_matches:
            raise RuntimeFailure("background runtime monitor is no longer running")
        endpoint = CdpEndpoint(int(state["port"]), timeout=5.0)
        adapter = _adapter_for_state(state)
        browser = endpoint.version()
        _validate_browser_identity(browser, adapter)
        schemes = set(state["allowedTargetSchemes"])
        if repair:
            compiled = compile_skin(Path(str(state["package"])))
            if compiled["cssHash"] != state.get("cssHash"):
                raise RuntimeFailure("skin package changed after activation; restore before reactivating")
            inject_until_ready(
                endpoint,
                compiled,
                str(state["sessionToken"]),
                schemes,
                8.0,
                settle_seconds=0.5,
            )
        checks = verify_css(
            endpoint, str(state["cssHash"]), str(state["sessionToken"]), schemes
        )
        ok = _results_pass(checks, "matches")
        result = {
            "ok": ok,
            "status": "active" if ok else "verification-failed",
            "sessionId": state["sessionId"],
            "appVersion": state["appVersion"],
            "adapterId": state["adapterId"],
            "packageId": state["packageId"],
            "pid": state["pid"],
            "monitorPid": monitor_pid,
            "monitorMatches": monitor_matches,
            "transport": {"host": "127.0.0.1", "port": state["port"]},
            "targets": checks,
            "repaired": repair,
            "verifiedAt": utc_now(),
        }
        if ok:
            state["lastVerifiedAt"] = result["verifiedAt"]
            state["lastVerifiedTargets"] = checks
            atomic_json(data_dir / ACTIVE_FILE, state)
        return result


def _config_line_key(line: str) -> str | None:
    stripped = line.lstrip()
    if "=" not in stripped or stripped.startswith("#"):
        return None
    key = stripped.split("=", 1)[0].strip()
    return key if key in VOLATILE_CONFIG_KEYS else None


def restore_allowlisted_config(config: Path, backup: Path) -> dict[str, Any]:
    """Restore only known app-session keys when every other config line is unchanged."""
    try:
        current_lines = config.read_text(encoding="utf-8").splitlines(keepends=True)
        backup_lines = backup.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeError) as exc:
        return {"restored": False, "reason": f"config comparison failed: {exc}"}

    def normalized(lines: list[str]) -> list[str]:
        return [
            f"{key}=<chromapaw-volatile>\n" if (key := _config_line_key(line)) else line
            for line in lines
        ]

    if normalized(current_lines) != normalized(backup_lines):
        return {
            "restored": False,
            "reason": "non-volatile config content changed; user changes were preserved",
        }
    backup_values = {
        key: line for line in backup_lines if (key := _config_line_key(line)) is not None
    }
    if not backup_values:
        return {"restored": False, "reason": "no allowlisted volatile config keys were present"}
    restored_lines = [
        backup_values.get(key, line) if (key := _config_line_key(line)) else line
        for line in current_lines
    ]
    temporary = config.with_name(config.name + ".chromapaw-restore.tmp")
    try:
        temporary.write_text("".join(restored_lines), encoding="utf-8", newline="")
        shutil.copystat(config, temporary)
        os.replace(temporary, config)
    except OSError as exc:
        with contextlib.suppress(OSError):
            temporary.unlink()
        return {"restored": False, "reason": f"allowlisted config restore failed: {exc}"}
    return {
        "restored": True,
        "reason": "only allowlisted app-session config keys were restored",
        "keys": sorted(backup_values),
    }


def _config_backup_status(state: dict[str, Any]) -> dict[str, Any]:
    backup_path = Path(str(state["backupDir"])) / "before.json"
    before = json.loads(backup_path.read_text(encoding="utf-8"))
    config = Path(str(before["codexConfig"]))
    original_hash = before.get("codexConfigHash")
    current_hash = sha256_file(config) if config.is_file() else None
    restore_result = {"restored": False, "reason": "config was unchanged"}
    config_backup_value = before.get("codexConfigBackup")
    if (
        original_hash is not None
        and current_hash is not None
        and original_hash != current_hash
        and isinstance(config_backup_value, str)
    ):
        restore_result = restore_allowlisted_config(config, Path(config_backup_value))
        current_hash = sha256_file(config) if config.is_file() else None
    return {
        "path": str(config),
        "backup": before.get("codexConfigBackup"),
        "originalHash": original_hash,
        "currentHash": current_hash,
        "unchanged": original_hash == current_hash,
        **restore_result,
    }


def restore_runtime(data_dir: Path, *, operation: str = "restore") -> dict[str, Any]:
    with runtime_lock(data_dir):
        state = _read_active(data_dir)
        if state is None:
            raise RuntimeFailure("no active ChromaPaw Windows runtime session exists")
        monitor = _terminate_monitor_process(state)
        endpoint = CdpEndpoint(int(state["port"]), timeout=5.0)
        schemes = set(state["allowedTargetSchemes"])
        try:
            removed = remove_css(
                endpoint,
                str(state["cssHash"]),
                str(state["sessionToken"]),
                schemes,
            )
        except CdpError as exc:
            removed = []
            transport_error = str(exc)
        else:
            transport_error = None
            if not _results_pass(removed, "removed"):
                raise RuntimeFailure(
                    "refusing to stop because a target style marker no longer belongs to this session"
                )

        terminated = _terminate_runtime_process(state)
        deadline = time.monotonic() + 8.0
        transport_closed = False
        while time.monotonic() < deadline:
            try:
                endpoint.version()
            except CdpError:
                transport_closed = True
                break
            time.sleep(0.2)
        if not transport_closed:
            raise RuntimeFailure("runtime process stopped but the loopback debugging transport stayed open")

        config_status = _config_backup_status(state)
        final = {
            **state,
            "status": "restored" if operation == "restore" else "stopped",
            "endedAt": utc_now(),
            "operation": operation,
            "removedTargets": removed,
            "transportErrorBeforeTermination": transport_error,
            "transportClosed": transport_closed,
            "process": terminated,
            "monitor": monitor,
            "config": config_status,
        }
        backup_dir = Path(str(state["backupDir"]))
        atomic_json(backup_dir / "final.json", final)
        (data_dir / ACTIVE_FILE).unlink()
        _append_history(
            data_dir,
            {
                "time": utc_now(),
                "event": final["status"],
                "sessionId": state["sessionId"],
                "transportClosed": transport_closed,
            },
        )
        return final


def runtime_status(data_dir: Path) -> dict[str, Any]:
    state = _read_active(data_dir)
    if state is None:
        return {"ok": True, "status": "inactive", "dataDir": str(data_dir)}
    pid = state.get("pid")
    process_path = _windows_process_paths().get(pid) if isinstance(pid, int) else None
    process_matches = process_path is not None and os.path.normcase(str(process_path)) == os.path.normcase(
        str(Path(str(state.get("executable"))).resolve())
    )
    monitor_pid = state.get("monitorPid")
    monitor_path = _windows_process_paths().get(monitor_pid) if isinstance(monitor_pid, int) else None
    monitor_expected = state.get("monitorExecutable")
    monitor_matches = (
        monitor_path is not None
        and isinstance(monitor_expected, str)
        and os.path.normcase(str(monitor_path))
        == os.path.normcase(str(Path(monitor_expected).resolve()))
    )
    endpoint_reachable = False
    with contextlib.suppress(CdpError, ValueError, TypeError):
        CdpEndpoint(int(state["port"]), timeout=1.0).version()
        endpoint_reachable = True
    return {
        "ok": process_matches and endpoint_reachable and monitor_matches,
        "status": "active" if process_matches and endpoint_reachable and monitor_matches else "stale",
        "dataDir": str(data_dir),
        "sessionId": state.get("sessionId"),
        "packageId": state.get("packageId"),
        "appVersion": state.get("appVersion"),
        "pid": pid,
        "processMatches": process_matches,
        "monitorPid": monitor_pid,
        "monitorMatches": monitor_matches,
        "endpointReachable": endpoint_reachable,
        "transport": {"host": "127.0.0.1", "port": state.get("port")},
    }


def capture_runtime_screenshot(data_dir: Path, output: Path, acknowledged: bool) -> dict[str, Any]:
    if not acknowledged:
        raise RuntimeFailure(
            "capture requires --acknowledge-screenshot-may-contain-private-content"
        )
    state = _read_active(data_dir)
    if state is None:
        raise RuntimeFailure("no active ChromaPaw Windows runtime session exists")
    endpoint = CdpEndpoint(int(state["port"]), timeout=8.0)
    targets = endpoint.targets(set(state["allowedTargetSchemes"]))
    if not targets:
        raise RuntimeFailure("no eligible Codex page target is available for capture")
    target = next(
        (item for item in targets if "avatar-overlay" not in item.url.lower()), targets[0]
    )
    data = endpoint.capture_png(target)
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeFailure("captured screenshot is not a PNG")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return {
        "ok": True,
        "output": str(output),
        "targetId": target.id,
        "targetUrl": target.url,
        "bytes": len(data),
    }


def _print_result(value: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif isinstance(value, dict):
        print(value.get("status") or value.get("output") or "OK")
    else:
        print(value)


def redact_result(value: object) -> object:
    """Remove runtime session secrets from every user-facing result level."""
    if isinstance(value, dict):
        return {
            key: "<redacted>" if key in SENSITIVE_RESULT_KEYS else redact_result(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_result(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Override runtime state directory")
    parser.add_argument("--adapters", type=Path, default=DEFAULT_ADAPTERS)
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("discover", help="List local Codex executable candidates")

    preflight_parser = subparsers.add_parser("preflight", help="Validate package and target")
    preflight_parser.add_argument("package", type=Path)
    preflight_parser.add_argument("--executable", type=Path, required=True)

    activate_parser = subparsers.add_parser("activate", help="Launch and style a compatible Codex")
    activate_parser.add_argument("package", type=Path)
    activate_parser.add_argument("--executable", type=Path, required=True)
    activate_parser.add_argument("--profile-dir", type=Path)
    activate_parser.add_argument("--allow-parallel-profile", action="store_true")
    activate_parser.add_argument("--wait-seconds", type=float, default=30.0)
    activate_parser.add_argument("--acknowledge-experimental-runtime", action="store_true")

    verify_parser = subparsers.add_parser("verify", help="Verify or repair active targets")
    verify_parser.add_argument("--repair", action="store_true")

    subparsers.add_parser("status", help="Inspect active runtime state")
    subparsers.add_parser("stop", help="Remove CSS, stop launched Codex, and close CDP")
    subparsers.add_parser("restore", help="Restore the pre-activation state and close CDP")

    capture_parser = subparsers.add_parser("capture", help="Capture one active Codex page")
    capture_parser.add_argument("--output", type=Path, required=True)
    capture_parser.add_argument(
        "--acknowledge-screenshot-may-contain-private-content", action="store_true"
    )

    monitor_parser = subparsers.add_parser("monitor", help=argparse.SUPPRESS)
    monitor_parser.add_argument("--session-id", required=True)

    args = parser.parse_args()
    data_dir = runtime_data_dir(args.data_dir)
    adapters = args.adapters.expanduser().resolve()
    try:
        if args.command == "discover":
            result = {"ok": True, "candidates": discover_executables(adapters)}
        elif args.command == "preflight":
            result = build_preflight(args.package, args.executable, adapters)
        elif args.command == "activate":
            profile = args.profile_dir.expanduser().resolve() if args.profile_dir else None
            result = activate_runtime(
                args.package,
                args.executable,
                data_dir,
                adapters,
                acknowledged=args.acknowledge_experimental_runtime,
                profile_dir=profile,
                allow_parallel_profile=args.allow_parallel_profile,
                wait_seconds=args.wait_seconds,
            )
        elif args.command == "verify":
            result = verify_runtime(data_dir, repair=args.repair)
        elif args.command == "status":
            result = runtime_status(data_dir)
        elif args.command == "stop":
            result = restore_runtime(data_dir, operation="stop")
        elif args.command == "restore":
            result = restore_runtime(data_dir, operation="restore")
        elif args.command == "capture":
            result = capture_runtime_screenshot(
                data_dir,
                args.output,
                args.acknowledge_screenshot_may_contain_private_content,
            )
        elif args.command == "monitor":
            return monitor_runtime(data_dir, args.session_id)
        else:  # pragma: no cover
            raise RuntimeFailure(f"unsupported command: {args.command}")
    except (CdpError, OSError, RuntimeFailure, ValueError) as exc:
        result = {"ok": False, "command": args.command, "error": str(exc)}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    result = redact_result(result)
    _print_result(result, args.json)
    return 0 if not isinstance(result, dict) or result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
