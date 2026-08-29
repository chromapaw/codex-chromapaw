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
from typing import Any, Callable, Iterator

try:
    from .cdp_client import CdpEndpoint, CdpError, inject_css, remove_css, verify_css
    from .skin_package import path_is_inside, safe_relative_path
    from .validate_skin_package import validate_package
except ImportError:
    from cdp_client import CdpEndpoint, CdpError, inject_css, remove_css, verify_css  # type: ignore
    from skin_package import path_is_inside, safe_relative_path  # type: ignore
    from validate_skin_package import validate_package  # type: ignore


RUNTIME_VERSION = "0.4.10"
# Keep the compiled CSS identity stable across launcher-only runtime releases.
# Increment this only when the compiler output intentionally changes.
CSS_IDENTITY_VERSION = "0.4.8"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADAPTERS = ROOT / "runtime" / "windows-adapters.json"
ACTIVE_FILE = "active.json"
PREFERENCE_FILE = "preferred-skin.json"
LOCK_FILE = ".runtime.lock"
STYLE_MARKER = 'data-avatar-overlay-content-frame="true"'
BACKGROUND_URL = re.compile(r"url\(\s*(['\"]?)\./background\.png\1\s*\)")
VOLATILE_CONFIG_KEYS = {"SKY_CUA_NATIVE_PIPE_DIRECTORY"}
APP_VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+){3}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SENSITIVE_RESULT_KEYS = {"sessionToken", "session"}

ExecutableIdentityProbe = Callable[[Path], dict[str, Any]]


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


def _snapshot_optional_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeFailure(f"runtime transaction snapshot cannot be read: {path}: {exc}") from exc


def _restore_optional_file(path: Path, content: bytes | None) -> None:
    """Restore an exact pre-transaction file image without using atomic_json."""
    if content is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".rollback.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise RuntimeFailure(f"runtime transaction rollback cannot restore: {path}: {exc}") from exc


def _restore_state_pair(
    active_path: Path,
    backup_active_path: Path,
    state: dict[str, Any],
) -> None:
    content = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _restore_optional_file(active_path, content)
    _restore_optional_file(backup_active_path, content)


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
    """Serialize runtime mutations with an OS-owned advisory lock.

    The previous O_EXCL sentinel could survive a process crash and permanently
    block recovery.  Advisory byte locks are released by the operating system
    when the owning process exits, so a leftover metadata file is harmless.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = data_dir / LOCK_FILE
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_RDWR)
    except OSError as exc:
        raise RuntimeFailure(f"runtime operation lock cannot be opened: {lock}: {exc}") from exc
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
            raise RuntimeFailure(
                f"another ChromaPaw runtime operation is active: {lock}"
            ) from exc
        metadata = f"pid={os.getpid()} time={utc_now()}\n".encode("utf-8")
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


def load_adapters(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeFailure(f"runtime adapter file cannot be read: {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 2:
        raise RuntimeFailure("runtime adapter file must be a schemaVersion 2 object")
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
        identity = adapter.get("executableIdentity")
        if not isinstance(identity, dict):
            raise RuntimeFailure(f"adapter {adapter_id} must declare executableIdentity")
        for field in (
            "productName",
            "companyName",
            "fileDescription",
            "originalFilename",
            "internalName",
        ):
            if not isinstance(identity.get(field), str) or not identity[field].strip():
                raise RuntimeFailure(
                    f"adapter {adapter_id} executableIdentity must declare {field}"
                )
        file_version = identity.get("fileVersion")
        if file_version is not None and (
            not isinstance(file_version, str) or not file_version.strip()
        ):
            raise RuntimeFailure(
                f"adapter {adapter_id} executableIdentity has an invalid fileVersion"
            )
        allowed_hashes = identity.get("allowedSha256", [])
        if (
            not isinstance(allowed_hashes, list)
            or ("allowedSha256" in identity and not allowed_hashes)
            or not all(
                isinstance(value, str) and SHA256_PATTERN.fullmatch(value.lower())
                for value in allowed_hashes
            )
        ):
            raise RuntimeFailure(
                f"adapter {adapter_id} executableIdentity has invalid allowedSha256 values"
            )
        signature = identity.get("signature")
        if not isinstance(signature, dict):
            raise RuntimeFailure(
                f"adapter {adapter_id} executableIdentity must declare a signature policy"
            )
        statuses = signature.get("allowedStatuses")
        if not isinstance(statuses, list) or not statuses or not all(
            isinstance(value, str) and value.strip() for value in statuses
        ):
            raise RuntimeFailure(
                f"adapter {adapter_id} executableIdentity has invalid signature statuses"
            )
        signer_subject = signature.get("signerSubjectContains")
        if signer_subject is not None and (
            not isinstance(signer_subject, str) or not signer_subject.strip()
        ):
            raise RuntimeFailure(
                f"adapter {adapter_id} executableIdentity has an invalid signer subject"
            )
        if adapter.get("activationEnabled") is True:
            has_hash_pin = bool(allowed_hashes)
            has_signed_version_gate = (
                isinstance(file_version, str)
                and any(value.casefold() == "valid" for value in statuses)
                and isinstance(signer_subject, str)
                and bool(signer_subject.strip())
            )
            if not has_hash_pin and not has_signed_version_gate:
                raise RuntimeFailure(
                    f"enabled adapter {adapter_id} must pin an executable hash or require "
                    "a valid signer plus an exact PE fileVersion"
                )
        seen_ids.add(adapter_id)
        seen_targets.add(target)
    return data


def probe_executable_identity(executable: Path) -> dict[str, Any]:
    """Read PE version metadata and Authenticode identity from Windows.

    Runtime callers always use this operating-system probe. Unit tests on other
    platforms can inject an explicit probe into :func:`select_adapter`; there
    is deliberately no CLI switch or environment override for identity data.
    """

    executable = executable.expanduser().resolve()
    if not executable.is_file():
        raise RuntimeFailure(f"Codex executable does not exist: {executable}")
    if os.name != "nt":
        raise RuntimeFailure(
            "Windows PE executable identity cannot be verified on this operating system"
        )

    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$path = $env:CHROMAPAW_IDENTITY_PATH
$item = Get-Item -LiteralPath $path
$info = $item.VersionInfo
$signature = Get-AuthenticodeSignature -LiteralPath $path
[ordered]@{
  fileVersion = $info.FileVersion
  productVersion = $info.ProductVersion
  productName = $info.ProductName
  companyName = $info.CompanyName
  fileDescription = $info.FileDescription
  originalFilename = $info.OriginalFilename
  internalName = $info.InternalName
  signatureStatus = [string]$signature.Status
  signerSubject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
  signerThumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
} | ConvertTo-Json -Compress
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    environment = os.environ.copy()
    environment["CHROMAPAW_IDENTITY_PATH"] = str(executable)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            creationflags=creation_flags,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeFailure(f"Windows PE executable identity probe failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "PowerShell returned no diagnostic"
        raise RuntimeFailure(f"Windows PE executable identity probe failed: {detail}")
    try:
        identity = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeFailure("Windows PE executable identity probe returned invalid JSON") from exc
    if not isinstance(identity, dict):
        raise RuntimeFailure("Windows PE executable identity probe returned an invalid object")
    identity["sha256"] = sha256_file(executable)
    return identity


def _verify_executable_identity(
    executable: Path,
    adapter: dict[str, Any],
    probe: ExecutableIdentityProbe,
) -> dict[str, Any]:
    adapter_id = str(adapter.get("id"))
    expected = adapter.get("executableIdentity")
    if not isinstance(expected, dict):
        raise RuntimeFailure(f"adapter {adapter_id} is missing executable identity policy")
    try:
        actual = probe(executable)
    except RuntimeFailure:
        raise
    except Exception as exc:
        raise RuntimeFailure(f"Windows PE executable identity probe failed: {exc}") from exc
    if not isinstance(actual, dict):
        raise RuntimeFailure("Windows PE executable identity probe returned an invalid object")

    mismatches: list[str] = []
    for field in (
        "productName",
        "companyName",
        "fileDescription",
        "originalFilename",
        "internalName",
    ):
        expected_value = str(expected[field]).strip()
        actual_value = actual.get(field)
        if not isinstance(actual_value, str) or actual_value.strip().casefold() != expected_value.casefold():
            mismatches.append(field)
    expected_file_version = expected.get("fileVersion")
    if isinstance(expected_file_version, str):
        actual_file_version = actual.get("fileVersion")
        if (
            not isinstance(actual_file_version, str)
            or actual_file_version.strip().casefold()
            != expected_file_version.strip().casefold()
        ):
            mismatches.append("fileVersion")

    allowed_hashes = {
        value.lower() for value in expected.get("allowedSha256", []) if isinstance(value, str)
    }
    actual_hash = actual.get("sha256")
    if allowed_hashes and (
        not isinstance(actual_hash, str) or actual_hash.lower() not in allowed_hashes
    ):
        mismatches.append("sha256")

    signature = expected.get("signature", {})
    allowed_statuses = {
        value.casefold()
        for value in signature.get("allowedStatuses", [])
        if isinstance(value, str)
    }
    actual_status = actual.get("signatureStatus")
    if not isinstance(actual_status, str) or actual_status.casefold() not in allowed_statuses:
        mismatches.append("signatureStatus")
    signer_contains = signature.get("signerSubjectContains")
    if isinstance(signer_contains, str):
        actual_subject = actual.get("signerSubject")
        if (
            not isinstance(actual_subject, str)
            or signer_contains.casefold() not in actual_subject.casefold()
        ):
            mismatches.append("signerSubject")

    if mismatches:
        raise RuntimeFailure(
            f"adapter {adapter_id} rejected the executable identity: "
            + ", ".join(sorted(set(mismatches)))
        )
    return actual


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
    executable: Path,
    adapter_path: Path = DEFAULT_ADAPTERS,
    *,
    require_enabled: bool = True,
    _identity_probe: ExecutableIdentityProbe | None = None,
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
        identity = _verify_executable_identity(
            executable, adapter, _identity_probe or probe_executable_identity
        )
        selected = dict(adapter)
        selected["verifiedExecutableIdentity"] = identity
        return selected
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
            identity = adapter.get("verifiedExecutableIdentity")
        except RuntimeFailure as exc:
            reason = str(exc)
            identity = None
        results.append(
            {
                "executable": str(resolved),
                "appVersion": version,
                "adapterId": adapter_id,
                "activationEnabled": activation_enabled,
                "executableIdentity": identity,
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


def _windows_process_creation_times() -> dict[int, int]:
    """Return Windows process creation FILETIMEs keyed by PID.

    A PID and executable path are not a sufficient ownership proof because
    Windows can reuse a PID for a later process launched from the same path.
    FILETIME is stable for the lifetime of the process and changes on reuse.
    """
    if os.name != "nt":
        return {}
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process_ids = (wintypes.DWORD * 8192)()
    bytes_returned = wintypes.DWORD()
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    if not psapi.EnumProcesses(
        ctypes.byref(process_ids), ctypes.sizeof(process_ids), ctypes.byref(bytes_returned)
    ):
        return {}
    results: dict[int, int] = {}
    count = bytes_returned.value // ctypes.sizeof(wintypes.DWORD)
    for pid in process_ids[:count]:
        if not pid:
            continue
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            if kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                results[int(pid)] = (int(creation.dwHighDateTime) << 32) | int(
                    creation.dwLowDateTime
                )
        finally:
            kernel32.CloseHandle(handle)
    return results


def _record_process_creation_time(pid: int, *, label: str) -> int:
    created = _windows_process_creation_times().get(pid)
    if created is None:
        raise RuntimeFailure(f"runtime could not record the {label} process creation identity")
    return created


def _process_identity_status(
    pid: object,
    executable: object,
    creation_time: object = None,
    executable_hash: object = None,
) -> dict[str, Any]:
    """Inspect process ownership without mutating it.

    Creation time is required for newly-created 0.4.8 sessions.  It remains
    optional while reading older active.json files so they can still be safely
    restored using the previous exact-path gate.
    """
    if not isinstance(pid, int) or not isinstance(executable, str):
        return {
            "running": False,
            "pathMatches": False,
            "creationTimeMatches": False if creation_time is not None else None,
            "executableHashMatches": False if executable_hash is not None else None,
            "matches": False,
            "recordedCreationTime": creation_time,
            "actualCreationTime": None,
        }
    process_path = _windows_process_paths().get(pid)
    expected = Path(executable).expanduser().resolve()
    path_matches = process_path is not None and os.path.normcase(
        str(process_path)
    ) == os.path.normcase(str(expected))
    actual_creation = _windows_process_creation_times().get(pid) if process_path else None
    creation_matches = (
        actual_creation == creation_time if isinstance(creation_time, int) else None
    )
    hash_matches: bool | None = None
    if isinstance(executable_hash, str):
        try:
            hash_matches = sha256_file(expected) == executable_hash
        except RuntimeFailure:
            hash_matches = False
    matches = path_matches and creation_matches is not False and hash_matches is not False
    return {
        "running": process_path is not None,
        "pathMatches": path_matches,
        "creationTimeMatches": creation_matches,
        "executableHashMatches": hash_matches,
        "matches": matches,
        "recordedCreationTime": creation_time,
        "actualCreationTime": actual_creation,
    }


def running_pids(executable: Path) -> list[int]:
    expected = os.path.normcase(str(executable.resolve()))
    return sorted(
        pid
        for pid, path in _windows_process_paths().items()
        if os.path.normcase(str(path)) == expected
    )


def close_matching_codex_processes(
    executable: Path,
    *,
    acknowledged: bool,
    timeout: float = 12.0,
) -> dict[str, Any]:
    if not acknowledged:
        raise RuntimeFailure("closing a running Codex requires explicit user confirmation")
    if os.name != "nt":
        raise RuntimeFailure("closing a selected Codex process group is Windows-only")
    executable = executable.expanduser().resolve()
    expected = os.path.normcase(str(executable))
    initial = running_pids(executable)
    if not initial:
        return {"closed": False, "reason": "not-running", "pids": []}

    attempted: list[int] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = running_pids(executable)
        if not current:
            return {
                "closed": True,
                "reason": "user-confirmed-relaunch",
                "pids": initial,
                "attemptedPids": attempted,
            }
        paths = _windows_process_paths()
        for pid in current:
            path = paths.get(pid)
            if path is None:
                continue
            if os.path.normcase(str(path)) != expected:
                raise RuntimeFailure(
                    f"Codex process identity changed before close confirmation could be applied: {pid}"
                )
            attempted.append(pid)
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        time.sleep(0.2)
    remaining = running_pids(executable)
    raise RuntimeFailure(
        "the user-confirmed Codex process group did not close: "
        + ", ".join(str(pid) for pid in remaining)
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
    compiled += (
        f"\n/* ChromaPaw runtime {CSS_IDENTITY_VERSION}; package {manifest['id']} */\n"
    )
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


def _style_target_ids(results: list[dict[str, Any]], key: str) -> set[str]:
    return {
        str(item.get("targetId"))
        for item in results
        if isinstance(item.get("result"), dict) and item["result"].get(key) is True
    }


def _snapshot_runtime_css(
    endpoint: CdpEndpoint,
    css_hash: str,
    session_token: str,
    schemes: set[str],
) -> dict[str, Any]:
    """Read and validate the currently-owned stylesheet before hot mutation."""
    expression = """(() => {
  const style = document.getElementById("chromapaw-runtime-style");
  if (!style || !style.isConnected) return {owned: false, reason: "style-absent"};
  if (style.dataset.chromapawHash !== %s || style.dataset.chromapawSession !== %s) {
    return {owned: false, reason: "marker-identity-mismatch"};
  }
  return {owned: true, hash: style.dataset.chromapawHash, css: style.textContent || ""};
})()""" % (json.dumps(css_hash), json.dumps(session_token))
    snapshots: list[dict[str, Any]] = []
    for target in endpoint.targets(schemes):
        value = endpoint.evaluate(target, expression)
        snapshots.append({"targetId": target.id, "result": value})
    if not snapshots or any(
        not isinstance(item.get("result"), dict)
        or item["result"].get("owned") is not True
        or not isinstance(item["result"].get("css"), str)
        for item in snapshots
    ):
        raise RuntimeFailure(
            f"current CSS ownership could not be snapshotted for rollback: {snapshots}"
        )
    css_values = {str(item["result"]["css"]) for item in snapshots}
    if len(css_values) != 1:
        raise RuntimeFailure("eligible targets do not share one rollback-safe CSS value")
    css = next(iter(css_values))
    if hashlib.sha256(css.encode("utf-8")).hexdigest() != css_hash:
        raise RuntimeFailure("current CSS content does not match its recorded rollback hash")
    return {"css": css, "cssHash": css_hash, "targets": snapshots}


def _rollback_css_refresh(
    endpoint: CdpEndpoint,
    previous_snapshot: dict[str, Any],
    new_css_hash: str,
    session_token: str,
    schemes: set[str],
) -> list[dict[str, Any]]:
    """Compensate a failed hot refresh before persistent state is committed."""
    removed = remove_css(endpoint, new_css_hash, session_token, schemes)
    failed_removals = [
        item
        for item in removed
        if isinstance(item.get("result"), dict)
        and item["result"].get("reason") not in {None, "already-absent"}
        and item["result"].get("removed") is not True
    ]
    if failed_removals:
        raise RuntimeFailure(f"updated CSS could not be removed during rollback: {failed_removals}")
    restored = inject_css(
        endpoint,
        str(previous_snapshot["css"]),
        str(previous_snapshot["cssHash"]),
        session_token,
        schemes,
    )
    if not _results_pass(restored, "applied"):
        raise RuntimeFailure(f"previous CSS could not be restored during rollback: {restored}")
    return restored


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


def _read_preference(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / PREFERENCE_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeFailure(f"preferred skin state cannot be read: {exc}") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise RuntimeFailure("preferred skin state is invalid")
    required = {
        "package",
        "packageId",
        "manifestHash",
        "cssHash",
        "executable",
        "executableHash",
        "appVersion",
        "adapterId",
        "adapterFile",
        "adapterFileHash",
    }
    missing = sorted(
        key for key in required if not isinstance(value.get(key), str) or not value[key]
    )
    if missing:
        raise RuntimeFailure(
            "preferred skin state is missing required string fields: " + ", ".join(missing)
        )
    return value


def remember_preference(data_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    preference = {
        "schemaVersion": 1,
        "runtimeVersion": RUNTIME_VERSION,
        "configuredAt": utc_now(),
        "package": state["package"],
        "packageId": state["packageId"],
        "manifestHash": state["manifestHash"],
        "cssHash": state["cssHash"],
        "executable": state["executable"],
        "executableHash": state["executableHash"],
        "appVersion": state["appVersion"],
        "adapterId": state["adapterId"],
        "adapterFile": state["adapterFile"],
        "adapterFileHash": state["adapterFileHash"],
        "applicationFilesModified": False,
        "codexConfigModified": False,
    }
    for field in ("runtimeBundleHash", "runtimeGeneration"):
        value = state.get(field)
        if isinstance(value, str) and value:
            preference[field] = value
    atomic_json(data_dir / PREFERENCE_FILE, preference)
    return preference


def refresh_preference_for_runtime_update(
    data_dir: Path,
    adapters: Path = DEFAULT_ADAPTERS,
    *,
    acknowledged: bool,
) -> dict[str, Any]:
    if not acknowledged:
        raise RuntimeFailure(
            "refreshing a saved skin for a runtime update requires explicit acknowledgment"
        )
    with runtime_lock(data_dir):
        if _read_active(data_dir) is not None:
            raise RuntimeFailure(
                "an active runtime session owns the selected skin; restore it before refreshing"
            )
        preference = _read_preference(data_dir)
        if preference is None:
            raise RuntimeFailure("no preferred skin exists to refresh")
        preflight = build_preflight(
            Path(preference["package"]),
            Path(preference["executable"]),
            adapters.expanduser().resolve(),
        )
        immutable_fields = (
            "packageId",
            "manifestHash",
            "executableHash",
            "appVersion",
            "adapterId",
            "adapterFileHash",
        )
        changed = sorted(
            field
            for field in immutable_fields
            if preflight.get(field) != preference.get(field)
        )
        if changed:
            raise RuntimeFailure(
                "saved skin identity changed; run a new reviewed activation instead: "
                + ", ".join(changed)
            )
        previous_css_hash = preference["cssHash"]
        for field in ("runtimeBundleHash", "runtimeGeneration"):
            value = preference.get(field)
            if isinstance(value, str) and value:
                preflight[field] = value
        refreshed = remember_preference(data_dir, preflight)
        result = {
            "ok": True,
            "status": (
                "refreshed" if refreshed["cssHash"] != previous_css_hash else "unchanged"
            ),
            "packageId": refreshed["packageId"],
            "appVersion": refreshed["appVersion"],
            "previousRuntimeVersion": preference.get("runtimeVersion"),
            "runtimeVersion": refreshed["runtimeVersion"],
            "previousCssHash": previous_css_hash,
            "cssHash": refreshed["cssHash"],
            "immutableContinuity": {field: True for field in immutable_fields},
        }
        with contextlib.suppress(Exception):
            _append_history(
                data_dir,
                {
                    "time": utc_now(),
                    "event": "preferred-skin-runtime-refreshed",
                    "packageId": refreshed["packageId"],
                    "previousRuntimeVersion": preference.get("runtimeVersion"),
                    "runtimeVersion": refreshed["runtimeVersion"],
                    "cssHashChanged": refreshed["cssHash"] != previous_css_hash,
                },
            )
        return result


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
        "executableIdentity": adapter["verifiedExecutableIdentity"],
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


def _launch_monitor(
    data_dir: Path,
    session_id: str,
    expected_css_hash: str | None = None,
) -> subprocess.Popen[bytes]:
    args = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--data-dir",
        str(data_dir),
        "monitor",
        "--session-id",
        session_id,
    ]
    if expected_css_hash is not None:
        if not SHA256_PATTERN.fullmatch(expected_css_hash):
            raise RuntimeFailure("runtime monitor expected CSS hash is invalid")
        args.extend(("--expected-css-hash", expected_css_hash))
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
    pid: object,
    executable: object,
    *,
    label: str,
    timeout: float = 10.0,
    creation_time: object = None,
    executable_hash: object = None,
) -> dict[str, Any]:
    if not isinstance(pid, int) or not isinstance(executable, str):
        raise RuntimeFailure(f"runtime state does not contain a valid {label} process")
    identity = _process_identity_status(pid, executable, creation_time, executable_hash)
    if not identity["running"]:
        return {"terminated": True, "reason": "already-exited", "pid": pid, "label": label}
    if not identity["matches"]:
        changed = [
            key
            for key in ("pathMatches", "creationTimeMatches", "executableHashMatches")
            if identity.get(key) is False
        ]
        raise RuntimeFailure(
            f"refusing to terminate a {label} PID whose process identity changed: "
            + ", ".join(changed)
        )
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
        creation_time=state.get("processCreationTime"),
        executable_hash=state.get("executableHash"),
    )


def _terminate_monitor_process(state: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
    return _terminate_process_tree(
        state.get("monitorPid"),
        state.get("monitorExecutable"),
        label="monitor",
        timeout=timeout,
        creation_time=state.get("monitorCreationTime"),
        executable_hash=state.get("monitorExecutableHash"),
    )


def monitor_runtime(
    data_dir: Path,
    session_id: str,
    interval: float = 1.0,
    expected_css_hash: str | None = None,
    startup_wait_seconds: float = 5.0,
) -> int:
    """Keep newly-created Codex windows synchronized until the session stops."""
    log_path: Path | None = None
    try:
        state = _read_active(data_dir)
        if state is None or state.get("sessionId") != session_id:
            return 2
        log_path = Path(str(state["backupDir"])) / "monitor.jsonl"
        compiled = compile_skin(Path(str(state["package"])))
        compiled_css_hash = str(compiled["cssHash"])
        if expected_css_hash is not None:
            if not SHA256_PATTERN.fullmatch(expected_css_hash):
                raise RuntimeFailure("runtime monitor expected CSS hash is invalid")
            if compiled_css_hash != expected_css_hash:
                raise RuntimeFailure("reviewed CSS changed before monitor startup")
            deadline = time.monotonic() + max(0.5, startup_wait_seconds)
            while state.get("cssHash") != expected_css_hash:
                if time.monotonic() >= deadline:
                    raise RuntimeFailure("CSS refresh state was not committed before monitor startup")
                time.sleep(0.05)
                state = _read_active(data_dir)
                if state is None or state.get("sessionId") != session_id:
                    return 2
        elif compiled_css_hash != state.get("cssHash"):
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


def _record_activation_failure(
    data_dir: Path,
    backup_dir: Path,
    session_id: str,
    error: Exception,
    *,
    process_launched: bool,
    config_status: dict[str, Any],
    rollback_errors: list[str],
) -> None:
    """Persist activation diagnostics without replacing the primary failure."""
    failure = {
        "schemaVersion": 1,
        "sessionId": session_id,
        "status": "activation-failed",
        "failedAt": utc_now(),
        "error": str(error),
        "processLaunched": process_launched,
        "config": config_status,
        "rollbackErrors": rollback_errors,
    }
    with contextlib.suppress(Exception):
        atomic_json(backup_dir / "failure.json", failure)
    with contextlib.suppress(Exception):
        _append_history(data_dir, failure)


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
        active_path = data_dir / ACTIVE_FILE
        preference_path = data_dir / PREFERENCE_FILE
        active_before = _snapshot_optional_file(active_path)
        preference_before = _snapshot_optional_file(preference_path)
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
        backup_dir = Path(str(backup["backupDir"]))
        backup_active_path = backup_dir / ACTIVE_FILE
        backup_preference_path = backup_dir / PREFERENCE_FILE
        backup_active_before = _snapshot_optional_file(backup_active_path)
        backup_preference_before = _snapshot_optional_file(backup_preference_path)
        port = choose_ephemeral_port()
        endpoint = CdpEndpoint(port, timeout=5.0)
        schemes = set(adapter["allowedTargetSchemes"])
        process: subprocess.Popen[bytes] | None = None
        monitor: subprocess.Popen[bytes] | None = None
        state: dict[str, Any] | None = None
        css_applied = False
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
            css_applied = True
            if process is None:  # pragma: no cover - guarded by the launch call
                raise RuntimeFailure("runtime launch returned no process")
            process_creation_time = _record_process_creation_time(process.pid, label="Codex")
            state = {
                "schemaVersion": 1,
                "runtimeVersion": RUNTIME_VERSION,
                "sessionId": session_id,
                "sessionToken": session_token,
                "status": "active",
                "startedAt": utc_now(),
                "pid": process.pid,
                "processCreationTime": process_creation_time,
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
            hosted_bundle_hash = os.environ.get("CHROMAPAW_HOSTED_BUNDLE_HASH")
            hosted_generation = os.environ.get("CHROMAPAW_HOSTED_GENERATION")
            if (
                isinstance(hosted_bundle_hash, str)
                and SHA256_PATTERN.fullmatch(hosted_bundle_hash)
                and hosted_generation == f"sha256-{hosted_bundle_hash}"
            ):
                state["runtimeBundleHash"] = hosted_bundle_hash
                state["runtimeGeneration"] = hosted_generation
            atomic_json(active_path, state)
            atomic_json(backup_active_path, state)
            monitor = _launch_monitor(data_dir, session_id)
            state["monitorPid"] = monitor.pid
            state["monitorExecutable"] = str(Path(sys.executable).resolve())
            state["monitorExecutableHash"] = sha256_file(Path(sys.executable).resolve())
            state["monitorCreationTime"] = _record_process_creation_time(
                monitor.pid, label="monitor"
            )
            state["monitorIntervalSeconds"] = 1.0
            state["backgroundMonitorDisclosure"] = (
                "A hidden local Python monitor checks the active loopback CDP targets once per second "
                "and injects CSS only when a new or unstyled Codex page appears."
            )
            atomic_json(active_path, state)
            atomic_json(backup_active_path, state)
            time.sleep(0.25)
            if monitor.poll() is not None:
                raise RuntimeFailure("background runtime monitor exited during startup")
            preference = remember_preference(data_dir, state)
            atomic_json(backup_preference_path, preference)
        except Exception as exc:
            rollback_errors: list[str] = []
            failed_state: dict[str, Any] = state or {
                "schemaVersion": 1,
                "sessionId": session_id,
                "executable": str(executable.expanduser().resolve()),
                "executableHash": preflight["executableHash"],
                "backupDir": backup["backupDir"],
            }
            if process is not None and "pid" not in failed_state:
                failed_state["pid"] = process.pid
                failed_state["processCreationTime"] = _windows_process_creation_times().get(
                    process.pid
                )
            if monitor is not None and monitor.poll() is None:
                try:
                    _terminate_monitor_process(failed_state)
                except Exception as rollback_exc:
                    rollback_errors.append(f"monitor termination: {rollback_exc}")
            if css_applied:
                try:
                    remove_css(endpoint, str(compiled["cssHash"]), session_token, schemes)
                except Exception as rollback_exc:
                    rollback_errors.append(f"CSS removal: {rollback_exc}")
            if process is not None:
                try:
                    _terminate_runtime_process(failed_state)
                except Exception as rollback_exc:
                    rollback_errors.append(f"Codex termination: {rollback_exc}")
            try:
                config_status = _config_backup_status(failed_state)
            except Exception as rollback_exc:
                rollback_errors.append(f"config restore: {rollback_exc}")
                config_status = {
                    "unchanged": False,
                    "restored": False,
                    "reason": str(rollback_exc),
                }
            for path, content in (
                (active_path, active_before),
                (backup_active_path, backup_active_before),
                (preference_path, preference_before),
                (backup_preference_path, backup_preference_before),
            ):
                try:
                    _restore_optional_file(path, content)
                except Exception as rollback_exc:
                    rollback_errors.append(f"state restore {path}: {rollback_exc}")
            _record_activation_failure(
                data_dir,
                backup_dir,
                session_id,
                exc,
                process_launched=process is not None,
                config_status=config_status,
                rollback_errors=rollback_errors,
            )
            detail = (
                " (rollback warnings: " + "; ".join(rollback_errors) + ")"
                if rollback_errors
                else ""
            )
            raise RuntimeFailure(
                f"activation failed and was rolled back: {exc}{detail}"
            ) from exc
        with contextlib.suppress(Exception):
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
        process_identity = _process_identity_status(
            state.get("pid"),
            state.get("executable"),
            state.get("processCreationTime"),
            state.get("executableHash"),
        )
        if not process_identity["matches"]:
            raise RuntimeFailure("runtime-launched Codex process is no longer running")
        monitor_pid = state.get("monitorPid")
        monitor_identity = _process_identity_status(
            monitor_pid,
            state.get("monitorExecutable"),
            state.get("monitorCreationTime"),
            state.get("monitorExecutableHash"),
        )
        monitor_matches = monitor_identity["matches"]
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
            "processIdentity": process_identity,
            "monitorIdentity": monitor_identity,
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


def refresh_active_runtime_css(
    data_dir: Path,
    adapters: Path = DEFAULT_ADAPTERS,
    *,
    acknowledged: bool,
) -> dict[str, Any]:
    """Hot-refresh CSS for the same reviewed package without restarting Codex."""
    if not acknowledged:
        raise RuntimeFailure(
            "refreshing active skin CSS requires --acknowledge-runtime-update"
        )
    with runtime_lock(data_dir):
        state = _read_active(data_dir)
        if state is None:
            raise RuntimeFailure("no active ChromaPaw Windows runtime session exists")

        executable = Path(str(state["executable"])).expanduser().resolve()
        if sha256_file(executable) != state.get("executableHash"):
            raise RuntimeFailure("Codex executable hash changed after activation")
        process_identity = _process_identity_status(
            state.get("pid"),
            state.get("executable"),
            state.get("processCreationTime"),
            state.get("executableHash"),
        )
        if not process_identity["matches"]:
            raise RuntimeFailure("runtime-launched Codex process is no longer running")

        package = Path(str(state["package"])).expanduser().resolve()
        adapters = adapters.expanduser().resolve()
        preflight = build_preflight(package, executable, adapters)
        immutable_fields = (
            "packageId",
            "manifestHash",
            "executableHash",
            "appVersion",
            "adapterId",
            "adapterFileHash",
        )
        changed = sorted(
            field for field in immutable_fields if preflight.get(field) != state.get(field)
        )
        if changed:
            raise RuntimeFailure(
                "active skin identity changed; run a new reviewed activation instead: "
                + ", ".join(changed)
            )

        endpoint = CdpEndpoint(int(state["port"]), timeout=5.0)
        adapter = _adapter_for_state(state)
        browser = endpoint.version()
        _validate_browser_identity(browser, adapter)
        schemes = set(state["allowedTargetSchemes"])
        compiled = compile_skin(package)
        previous_css_hash = str(state["cssHash"])
        previous_snapshot = _snapshot_runtime_css(
            endpoint,
            previous_css_hash,
            str(state["sessionToken"]),
            schemes,
        )

        monitor_identity = _process_identity_status(
            state.get("monitorPid"),
            state.get("monitorExecutable"),
            state.get("monitorCreationTime"),
            state.get("monitorExecutableHash"),
        )
        old_monitor_was_running = monitor_identity["matches"]
        if monitor_identity["running"] and not monitor_identity["matches"]:
            raise RuntimeFailure("refusing to stop a monitor whose executable identity changed")
        if old_monitor_was_running:
            _terminate_monitor_process(state)

        session_token = str(state["sessionToken"])
        old_state = dict(state)
        backup_dir = Path(str(old_state["backupDir"]))
        active_path = data_dir / ACTIVE_FILE
        backup_active_path = backup_dir / ACTIVE_FILE
        preference_path = data_dir / PREFERENCE_FILE
        backup_preference_path = backup_dir / PREFERENCE_FILE
        preference_before = _snapshot_optional_file(preference_path)
        backup_preference_before = _snapshot_optional_file(backup_preference_path)
        monitor: subprocess.Popen[bytes] | None = None
        try:
            applied = inject_until_ready(
                endpoint,
                compiled,
                session_token,
                schemes,
                8.0,
                settle_seconds=0.5,
            )
            monitor = _launch_monitor(
                data_dir,
                str(state["sessionId"]),
                str(compiled["cssHash"]),
            )
            new_monitor = {
                "monitorPid": monitor.pid,
                "monitorExecutable": str(Path(sys.executable).resolve()),
                "monitorExecutableHash": sha256_file(Path(sys.executable).resolve()),
                "monitorCreationTime": _record_process_creation_time(
                    monitor.pid, label="monitor"
                ),
                "monitorIntervalSeconds": 1.0,
            }
            time.sleep(0.25)
            if monitor.poll() is not None:
                raise RuntimeFailure("background runtime monitor exited during restart")

            refreshed_at = utc_now()
            state.update(
                {
                    "runtimeVersion": RUNTIME_VERSION,
                    "cssHash": compiled["cssHash"],
                    "browser": browser,
                    "appliedTargets": applied,
                    "lastCssRefreshAt": refreshed_at,
                    **new_monitor,
                }
            )
            atomic_json(active_path, state)
            atomic_json(backup_active_path, state)
            preference = remember_preference(data_dir, state)
            atomic_json(backup_preference_path, preference)
        except Exception as exc:
            if monitor is not None and monitor.poll() is None:
                failed_monitor_state = {
                    **old_state,
                    "monitorPid": monitor.pid,
                    "monitorExecutable": str(Path(sys.executable).resolve()),
                    "monitorExecutableHash": sha256_file(Path(sys.executable).resolve()),
                    "monitorCreationTime": _windows_process_creation_times().get(monitor.pid),
                }
                with contextlib.suppress(Exception):
                    _terminate_monitor_process(failed_monitor_state)
            rollback_error: Exception | None = None
            try:
                _rollback_css_refresh(
                    endpoint,
                    previous_snapshot,
                    str(compiled["cssHash"]),
                    session_token,
                    schemes,
                )
            except Exception as rollback_exc:
                rollback_error = rollback_exc
            if old_monitor_was_running:
                try:
                    replacement = _launch_monitor(data_dir, str(old_state["sessionId"]))
                    old_state.update(
                        {
                            "monitorPid": replacement.pid,
                            "monitorExecutable": str(Path(sys.executable).resolve()),
                            "monitorExecutableHash": sha256_file(Path(sys.executable).resolve()),
                            "monitorCreationTime": _record_process_creation_time(
                                replacement.pid, label="monitor"
                            ),
                        }
                    )
                except Exception as monitor_exc:
                    rollback_error = rollback_error or monitor_exc
            try:
                _restore_state_pair(active_path, backup_active_path, old_state)
                _restore_optional_file(preference_path, preference_before)
                _restore_optional_file(backup_preference_path, backup_preference_before)
            except Exception as state_exc:
                rollback_error = rollback_error or state_exc
            detail = f"; rollback incomplete: {rollback_error}" if rollback_error else ""
            raise RuntimeFailure(f"active CSS refresh failed and was rolled back: {exc}{detail}") from exc
        changed_css = compiled["cssHash"] != previous_css_hash
        _append_history(
            data_dir,
            {
                "time": refreshed_at,
                "event": "active-skin-css-refreshed",
                "sessionId": state["sessionId"],
                "packageId": state["packageId"],
                "previousCssHash": previous_css_hash,
                "cssHash": compiled["cssHash"],
                "cssHashChanged": changed_css,
                "monitorRestarted": True,
            },
        )
        return {
            "ok": True,
            "status": "refreshed" if changed_css else "unchanged",
            "sessionId": state["sessionId"],
            "packageId": state["packageId"],
            "appVersion": state["appVersion"],
            "previousCssHash": previous_css_hash,
            "cssHash": compiled["cssHash"],
            "runtimeVersion": RUNTIME_VERSION,
            "monitorPid": state["monitorPid"],
            "monitorRestarted": True,
            "targets": applied,
            "immutableContinuity": {field: True for field in immutable_fields},
        }


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


def restore_runtime(
    data_dir: Path,
    *,
    operation: str = "restore",
    expected_session_id: str | None = None,
    recover_stale_identities: bool = False,
) -> dict[str, Any]:
    with runtime_lock(data_dir):
        state = _read_active(data_dir)
        if state is None:
            raise RuntimeFailure("no active ChromaPaw Windows runtime session exists")
        if expected_session_id is not None and state.get("sessionId") != expected_session_id:
            raise RuntimeFailure(
                "active runtime session changed before restore; refusing to restore a different session"
            )
        monitor_identity = _process_identity_status(
            state.get("monitorPid"),
            state.get("monitorExecutable"),
            state.get("monitorCreationTime"),
            state.get("monitorExecutableHash"),
        )
        if recover_stale_identities and not monitor_identity["matches"]:
            monitor = {
                "terminated": not monitor_identity["running"],
                "skipped": bool(monitor_identity["running"]),
                "reason": (
                    "recorded-monitor-pid-was-reused"
                    if monitor_identity["running"]
                    else "already-exited"
                ),
                "pid": state.get("monitorPid"),
                "label": "monitor",
                "identity": monitor_identity,
            }
        else:
            monitor = _terminate_monitor_process(state)

        process_identity = _process_identity_status(
            state.get("pid"),
            state.get("executable"),
            state.get("processCreationTime"),
            state.get("executableHash"),
        )
        process_owned = bool(process_identity["matches"])
        endpoint: CdpEndpoint | None = None
        removed: list[dict[str, Any]] = []
        if recover_stale_identities and not process_owned:
            transport_error = (
                "CSS removal skipped because the recorded Codex process no longer belongs "
                "to this ChromaPaw session"
            )
        else:
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
                transport_error = str(exc)
            else:
                transport_error = None
                if not _results_pass(removed, "removed"):
                    raise RuntimeFailure(
                        "refusing to stop because a target style marker no longer belongs to this session"
                    )

        if recover_stale_identities and not process_owned:
            terminated = {
                "terminated": not process_identity["running"],
                "skipped": bool(process_identity["running"]),
                "reason": (
                    "recorded-codex-pid-was-reused"
                    if process_identity["running"]
                    else "already-exited"
                ),
                "pid": state.get("pid"),
                "label": "Codex",
                "identity": process_identity,
            }
        else:
            terminated = _terminate_runtime_process(state)

        transport_closed: bool | None = None
        if process_owned and endpoint is not None:
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
                raise RuntimeFailure(
                    "runtime process stopped but the loopback debugging transport stayed open"
                )

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
            "staleIdentityRecovery": recover_stale_identities,
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
                "staleIdentityRecovery": recover_stale_identities,
                "processIdentitySkipped": bool(terminated.get("skipped")),
                "monitorIdentitySkipped": bool(monitor.get("skipped")),
            },
        )
        return final


def runtime_status(data_dir: Path) -> dict[str, Any]:
    state = _read_active(data_dir)
    if state is None:
        return {"ok": True, "status": "inactive", "dataDir": str(data_dir)}
    pid = state.get("pid")
    process_identity = _process_identity_status(
        pid,
        state.get("executable"),
        state.get("processCreationTime"),
        state.get("executableHash"),
    )
    monitor_pid = state.get("monitorPid")
    monitor_identity = _process_identity_status(
        monitor_pid,
        state.get("monitorExecutable"),
        state.get("monitorCreationTime"),
        state.get("monitorExecutableHash"),
    )
    legacy_session = not isinstance(state.get("processCreationTime"), int) or not isinstance(
        state.get("monitorCreationTime"), int
    )
    continuity: dict[str, bool | None] = {
        "adapterRegistryHashMatches": None,
        "packageManifestHashMatches": None,
        "compiledCssHashMatches": None,
        "adapterIdentityMatches": None,
        "browserIdentityMatches": None,
        "styleOwnershipMatches": None,
    }
    errors: list[str] = []
    adapter: dict[str, Any] | None = None
    adapter_file_value = state.get("adapterFile")
    if isinstance(adapter_file_value, str) and isinstance(state.get("adapterFileHash"), str):
        try:
            continuity["adapterRegistryHashMatches"] = (
                sha256_file(Path(adapter_file_value).expanduser().resolve())
                == state["adapterFileHash"]
            )
        except RuntimeFailure as exc:
            continuity["adapterRegistryHashMatches"] = False
            errors.append(str(exc))
    package_value = state.get("package")
    if isinstance(package_value, str):
        package = Path(package_value).expanduser().resolve()
        try:
            manifest = package / "skin.json"
            continuity["packageManifestHashMatches"] = (
                isinstance(state.get("manifestHash"), str)
                and sha256_file(manifest) == state["manifestHash"]
            )
            compiled = compile_skin(package)
            continuity["compiledCssHashMatches"] = compiled["cssHash"] == state.get("cssHash")
        except (OSError, RuntimeFailure, ValueError) as exc:
            continuity["packageManifestHashMatches"] = False
            continuity["compiledCssHashMatches"] = False
            errors.append(str(exc))
    endpoint_reachable = False
    style_checks: list[dict[str, Any]] = []
    try:
        endpoint = CdpEndpoint(int(state["port"]), timeout=1.0)
        browser = endpoint.version()
        endpoint_reachable = True
        if continuity["adapterRegistryHashMatches"] is True:
            try:
                adapter = _adapter_for_state(state)
                continuity["adapterIdentityMatches"] = True
                _validate_browser_identity(browser, adapter)
                continuity["browserIdentityMatches"] = True
            except (OSError, RuntimeFailure, ValueError) as exc:
                continuity["adapterIdentityMatches"] = False
                continuity["browserIdentityMatches"] = False
                errors.append(str(exc))
        if continuity["browserIdentityMatches"] is True:
            style_checks = verify_css(
                endpoint,
                str(state["cssHash"]),
                str(state["sessionToken"]),
                set(state["allowedTargetSchemes"]),
            )
            continuity["styleOwnershipMatches"] = _results_pass(style_checks, "matches")
    except (CdpError, OSError, RuntimeFailure, ValueError, TypeError) as exc:
        errors.append(str(exc))

    process_matches = process_identity["matches"]
    monitor_matches = monitor_identity["matches"]
    known_continuity = [value for value in continuity.values() if value is not None]
    required_continuity = bool(known_continuity) and all(
        value is True for value in known_continuity
    )
    ok = process_matches and endpoint_reachable and monitor_matches and required_continuity
    return {
        "ok": ok,
        "status": "active" if ok else "stale",
        "dataDir": str(data_dir),
        "sessionId": state.get("sessionId"),
        "packageId": state.get("packageId"),
        "appVersion": state.get("appVersion"),
        "pid": pid,
        "processMatches": process_matches,
        "processIdentity": process_identity,
        "monitorPid": monitor_pid,
        "monitorMatches": monitor_matches,
        "monitorIdentity": monitor_identity,
        "legacyProcessIdentity": legacy_session,
        "endpointReachable": endpoint_reachable,
        "continuity": continuity,
        "targets": style_checks,
        "errors": errors,
        "transport": {"host": "127.0.0.1", "port": state.get("port")},
    }


def resume_runtime(
    data_dir: Path,
    adapters: Path = DEFAULT_ADAPTERS,
    *,
    acknowledged: bool,
    wait_seconds: float = 30.0,
) -> dict[str, Any]:
    if not acknowledged:
        raise RuntimeFailure(
            "resume requires --acknowledge-experimental-runtime because Codex has no official skin API"
        )
    preference = _read_preference(data_dir)
    if preference is None:
        raise RuntimeFailure(
            "no preferred skin is saved; activate a validated package once before using resume"
        )

    status = runtime_status(data_dir)
    previous_status = str(status["status"])
    active = _read_active(data_dir)
    active_session_id: str | None = None
    if active is not None:
        session_value = active.get("sessionId")
        if not isinstance(session_value, str) or not session_value:
            raise RuntimeFailure(
                "active runtime state has no session identity; refusing an unguarded resume restore"
            )
        active_session_id = session_value
        status_session_id = status.get("sessionId")
        if not isinstance(status_session_id, str) or status_session_id != active_session_id:
            raise RuntimeFailure(
                "active runtime session changed during resume status inspection; retry resume"
            )
    if status.get("ok") and active is not None:
        same_package = os.path.normcase(str(Path(str(active.get("package"))).resolve())) == os.path.normcase(
            str(Path(preference["package"]).resolve())
        )
        same_executable = os.path.normcase(
            str(Path(str(active.get("executable"))).resolve())
        ) == os.path.normcase(str(Path(preference["executable"]).resolve()))
        if same_package and same_executable:
            return {
                **status,
                "status": "already-active",
                "resumed": False,
                "preferredPackageId": preference["packageId"],
            }
        raise RuntimeFailure(
            "a different healthy ChromaPaw runtime session is active; restore it before resuming the preferred skin"
        )

    restored = None
    if active is not None:
        restored = restore_runtime(
            data_dir,
            operation="restore",
            expected_session_id=active_session_id,
            recover_stale_identities=True,
        )

    executable = Path(preference["executable"]).expanduser().resolve()
    package = Path(preference["package"]).expanduser().resolve()
    adapters = adapters.expanduser().resolve()
    preflight = build_preflight(package, executable, adapters)
    continuity = {
        "executableHash": preflight["executableHash"] == preference["executableHash"],
        "manifestHash": preflight["manifestHash"] == preference["manifestHash"],
        "cssHash": preflight["cssHash"] == preference["cssHash"],
        "adapterFileHash": preflight["adapterFileHash"] == preference["adapterFileHash"],
        "adapterId": preflight["adapterId"] == preference["adapterId"],
        "appVersion": preflight["appVersion"] == preference["appVersion"],
    }
    changed = sorted(key for key, matches in continuity.items() if not matches)
    if changed:
        raise RuntimeFailure(
            "preferred skin continuity check failed; activate again after reviewing changes: "
            + ", ".join(changed)
        )

    state = activate_runtime(
        package,
        executable,
        data_dir,
        adapters,
        acknowledged=True,
        profile_dir=None,
        allow_parallel_profile=False,
        wait_seconds=wait_seconds,
    )
    return {
        **state,
        "resumed": True,
        "previousStatus": previous_status,
        "staleSessionRecovered": restored is not None,
        "continuity": continuity,
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
        payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        try:
            sys.stdout.write(payload)
        except UnicodeEncodeError:
            # One-shot launchers may inherit a legacy Windows console encoding.
            # Preserve structured output rather than failing after an otherwise
            # successful state transition.
            sys.stdout.buffer.write(payload.encode("utf-8"))
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

    resume_parser = subparsers.add_parser(
        "resume", help="Relaunch Codex with the last successfully activated skin"
    )
    resume_parser.add_argument("--wait-seconds", type=float, default=30.0)
    resume_parser.add_argument("--acknowledge-experimental-runtime", action="store_true")

    refresh_parser = subparsers.add_parser(
        "refresh-preference",
        help="Refresh the saved CSS identity after a reviewed runtime-only update",
    )
    refresh_parser.add_argument("--acknowledge-runtime-update", action="store_true")

    active_refresh_parser = subparsers.add_parser(
        "refresh-active-css",
        help="Hot-refresh CSS for the active reviewed skin without restarting Codex",
    )
    active_refresh_parser.add_argument("--acknowledge-runtime-update", action="store_true")

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
    monitor_parser.add_argument("--expected-css-hash")

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
        elif args.command == "resume":
            result = resume_runtime(
                data_dir,
                adapters,
                acknowledged=args.acknowledge_experimental_runtime,
                wait_seconds=args.wait_seconds,
            )
        elif args.command == "refresh-preference":
            result = refresh_preference_for_runtime_update(
                data_dir,
                adapters,
                acknowledged=args.acknowledge_runtime_update,
            )
        elif args.command == "refresh-active-css":
            result = refresh_active_runtime_css(
                data_dir,
                adapters,
                acknowledged=args.acknowledge_runtime_update,
            )
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
            return monitor_runtime(
                data_dir,
                args.session_id,
                expected_css_hash=args.expected_css_hash,
            )
        else:  # pragma: no cover
            raise RuntimeFailure(f"unsupported command: {args.command}")
    except (CdpError, OSError, RuntimeFailure, ValueError) as exc:
        result = {"ok": False, "command": args.command, "error": str(exc)}
        if args.json:
            _print_result(result, True)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    result = redact_result(result)
    _print_result(result, args.json)
    return 0 if not isinstance(result, dict) or result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
