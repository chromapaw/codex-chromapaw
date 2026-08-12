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
import tempfile
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
HOSTED_RUNTIME_DIR = "shortcut-runtime"
HOSTED_RUNTIME_SOURCES = (
    ("scripts/windows_skin_launcher.py", ROOT / "scripts" / "windows_skin_launcher.py"),
    ("scripts/windows_runtime.py", ROOT / "scripts" / "windows_runtime.py"),
    ("scripts/cdp_client.py", ROOT / "scripts" / "cdp_client.py"),
    ("scripts/skin_package.py", ROOT / "scripts" / "skin_package.py"),
    ("scripts/validate_skin_package.py", ROOT / "scripts" / "validate_skin_package.py"),
    ("scripts/theme_profile.py", ROOT / "scripts" / "theme_profile.py"),
)
HOSTED_BOOTSTRAP = '''#!/usr/bin/env python3
"""Stable entry point for the locally hosted ChromaPaw Windows runtime."""
from __future__ import annotations

import ctypes
import json
import os
import runpy
import sys
import hashlib
from pathlib import Path


def _fail(message: str) -> int:
    if os.name == "nt" and os.environ.get("CHROMAPAW_SUPPRESS_ERROR_DIALOG") != "1":
        try:
            ctypes.windll.user32.MessageBoxW(
                0, message, "ChromaPaw could not start Codex", 0x00000010
            )
        except Exception:
            pass
    return 1


def main() -> int:
    root = Path(__file__).resolve().parent
    try:
        state = json.loads((root / "current.json").read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("schemaVersion") != 1:
            raise RuntimeError("hosted runtime current pointer is invalid")
        generation_name = state.get("generation")
        if not isinstance(generation_name, str) or not generation_name.startswith("sha256-"):
            raise RuntimeError("hosted runtime generation metadata is invalid")
        generations_link = root / "generations"
        generations = generations_link.resolve()
        if generations_link.is_symlink() or generations.parent != root:
            raise RuntimeError("hosted runtime generations directory escaped its managed root")
        generation_link = generations_link / generation_name
        generation = generation_link.resolve()
        if generation_link.is_symlink() or generation.parent != generations:
            raise RuntimeError("hosted runtime generation escaped its managed directory")
        manifest = json.loads((generation / "manifest.json").read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("schemaVersion") != 1
            or manifest.get("generation") != generation_name
            or manifest.get("bundleHash") != state.get("bundleHash")
            or generation_name != f"sha256-{manifest.get('bundleHash')}"
        ):
            raise RuntimeError("hosted runtime manifest identity is invalid")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise RuntimeError("hosted runtime manifest file list is invalid")
        expected_files = set()
        canonical_entries = []
        for entry in files:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise RuntimeError("hosted runtime manifest entry is invalid")
            relative = entry["path"]
            parts = relative.split("/")
            digest = entry.get("sha256")
            if (
                not relative
                or "\\\\" in relative
                or any(part in ("", ".", "..") for part in parts)
                or relative == "manifest.json"
                or relative in expected_files
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise RuntimeError("hosted runtime manifest entry is invalid")
            expected_files.add(relative)
            source = generation.joinpath(*parts)
            target = source.resolve()
            if (
                source.is_symlink()
                or target == generation
                or generation not in target.parents
                or not target.is_file()
            ):
                raise RuntimeError("hosted runtime manifest path escaped its generation")
            actual_digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual_digest != digest:
                raise RuntimeError("hosted runtime file integrity check failed")
            canonical_entries.append((relative, actual_digest))
        actual_files = set()
        for candidate in generation.rglob("*"):
            if candidate.is_symlink():
                raise RuntimeError("hosted runtime generation contains a linked entry")
            if candidate.is_dir():
                continue
            if not candidate.is_file():
                raise RuntimeError("hosted runtime generation contains a non-file entry")
            relative = candidate.relative_to(generation).as_posix()
            if relative != "manifest.json":
                actual_files.add(relative)
        if actual_files != expected_files:
            raise RuntimeError("hosted runtime generation file set differs from its manifest")
        canonical = hashlib.sha256()
        for relative, digest in sorted(canonical_entries):
            canonical.update(relative.encode("utf-8"))
            canonical.update(b"\\0")
            canonical.update(digest.encode("ascii"))
            canonical.update(b"\\0")
        if canonical.hexdigest() != manifest.get("bundleHash"):
            raise RuntimeError("hosted runtime bundle identity is invalid")
        launcher = generation / "scripts" / "windows_skin_launcher.py"
        adapters = generation / "runtime" / "windows-adapters.json"
        if not launcher.is_file() or not adapters.is_file():
            raise RuntimeError("hosted runtime files are incomplete; reinstall the shortcuts")
        sys.dont_write_bytecode = True
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        sys.path.insert(0, str(launcher.parent))
        sys.argv = [str(launcher), "--adapters", str(adapters), *sys.argv[1:]]
        runpy.run_path(str(launcher), run_name="__main__")
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
'''


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
    if not isinstance(value, dict) or value.get("schemaVersion") not in (1, 2, 3, 4):
        raise RuntimeFailure("shortcut receipt is invalid")
    return value


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _restore_optional_bytes(path: Path, content: bytes | None) -> None:
    if content is None:
        if path.exists():
            path.unlink()
        return
    _atomic_bytes(path, content)


def _bundle_sources(adapters: Path) -> list[tuple[str, Path]]:
    return sorted(
        [*HOSTED_RUNTIME_SOURCES, ("runtime/windows-adapters.json", adapters)],
        key=lambda item: item[0],
    )


def _bundle_manifest(adapters: Path) -> dict[str, Any]:
    files = []
    digest = hashlib.sha256()
    for relative, source in _bundle_sources(adapters):
        if not source.is_file():
            raise RuntimeFailure(f"hosted runtime source is missing: {source}")
        file_hash = sha256_file(source)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
        files.append({"path": relative, "sha256": file_hash})
    bundle_hash = digest.hexdigest()
    return {
        "schemaVersion": 1,
        "bundleHash": bundle_hash,
        "generation": f"sha256-{bundle_hash}",
        "files": files,
    }


def _verify_generation(generation: Path, manifest: dict[str, Any]) -> None:
    if generation.is_symlink():
        raise RuntimeFailure("hosted runtime generation cannot be a linked directory")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeFailure("hosted runtime generation manifest file list is invalid")
    expected: set[str] = set()
    digest = hashlib.sha256()
    canonical_entries: list[tuple[str, str]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise RuntimeFailure("hosted runtime generation manifest entry is invalid")
        relative = entry.get("path")
        expected_hash = entry.get("sha256")
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or any(part in ("", ".", "..") for part in relative.split("/"))
            or relative == "manifest.json"
            or relative in expected
            or not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or any(character not in "0123456789abcdef" for character in expected_hash)
        ):
            raise RuntimeFailure("hosted runtime generation manifest entry is invalid")
        expected.add(relative)
        source = generation.joinpath(*relative.split("/"))
        target = source.resolve()
        resolved_generation = generation.resolve()
        if (
            source.is_symlink()
            or target == resolved_generation
            or resolved_generation not in target.parents
            or not target.is_file()
            or sha256_file(target) != expected_hash
        ):
            raise RuntimeFailure(f"hosted runtime generation is incomplete or changed: {target}")
        canonical_entries.append((relative, expected_hash))
    actual: set[str] = set()
    for candidate in generation.rglob("*"):
        if candidate.is_symlink():
            raise RuntimeFailure(
                f"hosted runtime generation contains a linked entry: {candidate}"
            )
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise RuntimeFailure(
                f"hosted runtime generation contains a non-file entry: {candidate}"
            )
        relative = candidate.relative_to(generation).as_posix()
        if relative != "manifest.json":
            actual.add(relative)
    if actual != expected:
        raise RuntimeFailure("hosted runtime generation file set differs from its manifest")
    for relative, expected_hash in sorted(canonical_entries):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(expected_hash.encode("ascii"))
        digest.update(b"\0")
    bundle_hash = digest.hexdigest()
    if (
        manifest.get("bundleHash") != bundle_hash
        or manifest.get("generation") != f"sha256-{bundle_hash}"
        or generation.name != manifest.get("generation")
    ):
        raise RuntimeFailure("hosted runtime generation bundle identity is invalid")


def _install_hosted_runtime(data_dir: Path, adapters: Path) -> dict[str, Any]:
    hosted_root = data_dir / HOSTED_RUNTIME_DIR
    generations = hosted_root / "generations"
    generations.mkdir(parents=True, exist_ok=True)
    manifest = _bundle_manifest(adapters)
    generation = generations / manifest["generation"]
    if generation.exists():
        if not generation.is_dir():
            raise RuntimeFailure(f"hosted runtime generation path is not a directory: {generation}")
        _verify_generation(generation, manifest)
    else:
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=generations))
        try:
            for (relative, source), entry in zip(_bundle_sources(adapters), manifest["files"]):
                target = staging.joinpath(*relative.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if sha256_file(target) != entry["sha256"]:
                    raise RuntimeFailure(f"hosted runtime copy verification failed: {target}")
            atomic_json(staging / "manifest.json", manifest)
            os.replace(staging, generation)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    _verify_generation(generation, manifest)

    bootstrap = hosted_root / "bootstrap.py"
    bootstrap_bytes = HOSTED_BOOTSTRAP.encode("utf-8")
    _atomic_bytes(bootstrap, bootstrap_bytes)
    current = {
        "schemaVersion": 1,
        "generation": manifest["generation"],
        "bundleHash": manifest["bundleHash"],
        "updatedAt": utc_now(),
    }
    atomic_json(hosted_root / "current.json", current)
    return {
        "root": str(hosted_root),
        "bootstrap": str(bootstrap),
        "bootstrapHash": hashlib.sha256(bootstrap_bytes).hexdigest(),
        "current": str(hosted_root / "current.json"),
        "generation": manifest["generation"],
        "generationDir": str(generation),
        "bundleHash": manifest["bundleHash"],
        "files": manifest["files"],
        "retainedAfterShortcutRemoval": True,
    }


def _hosted_runtime_status(receipt: dict[str, Any]) -> dict[str, Any]:
    hosted = receipt.get("hostedRuntime")
    if not isinstance(hosted, dict):
        return {"present": False, "matches": False}
    bootstrap = Path(str(hosted.get("bootstrap", ""))).resolve()
    current_path = Path(str(hosted.get("current", ""))).resolve()
    generation = Path(str(hosted.get("generationDir", ""))).resolve()
    bootstrap_matches = (
        bootstrap.is_file() and sha256_file(bootstrap) == hosted.get("bootstrapHash")
    )
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        current = None
    current_matches = (
        isinstance(current, dict)
        and current.get("generation") == hosted.get("generation")
        and current.get("bundleHash") == hosted.get("bundleHash")
    )
    files = hosted.get("files")
    files_match = isinstance(files, list) and bool(files)
    if files_match:
        for entry in files:
            if not isinstance(entry, dict):
                files_match = False
                break
            target = generation.joinpath(*str(entry.get("path", "")).split("/"))
            if not target.is_file() or sha256_file(target) != entry.get("sha256"):
                files_match = False
                break
    return {
        "present": bootstrap.exists() or current_path.exists() or generation.exists(),
        "matches": bootstrap_matches and current_matches and files_match,
        "bootstrapMatches": bootstrap_matches,
        "currentGenerationMatches": current_matches,
        "generationFilesMatch": files_match,
        "root": hosted.get("root"),
        "generation": hosted.get("generation"),
    }


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
        if receipt.get("mode") != "add" or receipt.get("schemaVersion") not in (3, 4):
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
    hosted_root = data_dir / HOSTED_RUNTIME_DIR
    hosted_snapshots = {
        path: path.read_bytes() if path.is_file() else None
        for path in (hosted_root / "bootstrap.py", hosted_root / "current.json")
    }
    hosted_runtime = _install_hosted_runtime(data_dir, adapters)
    hosted_bootstrap = Path(hosted_runtime["bootstrap"])
    arguments = subprocess.list2cmdline(
        [
            str(hosted_bootstrap),
            "--data-dir",
            str(data_dir),
            "--acknowledge-experimental-runtime",
        ]
    )
    result: dict[str, Any] | None = None
    try:
        installed_entries = []
        for kind, path in managed_paths.items():
            _write_shortcut(
                path,
                target=pythonw,
                arguments=arguments,
                working_directory=hosted_root,
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
        result = {
            "schemaVersion": 4,
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
            "launcher": str(hosted_bootstrap),
            "launcherHash": sha256_file(hosted_bootstrap),
            "adapterFile": str(Path(hosted_runtime["generationDir"]) / "runtime" / "windows-adapters.json"),
            "adapterFileHash": sha256_file(adapters),
            "hostedRuntime": hosted_runtime,
            "modifiesOriginalShortcut": False,
            "modifiesCodexApplicationFiles": False,
        }
        atomic_json(data_dir / RECEIPT_FILE, result)
    except Exception:
        for path, content in previous_bytes.items():
            _restore_optional_bytes(path, content)
        for path, content in hosted_snapshots.items():
            _restore_optional_bytes(path, content)
        raise
    assert result is not None
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
    result = _finalize_receipt(data_dir, receipt, "removed")
    if receipt.get("schemaVersion") == 4:
        result["hostedRuntimeRetained"] = receipt.get("hostedRuntime", {}).get("root")
        result["hostedRuntimeCleanupReason"] = (
            "retained so an in-flight launcher or monitor cannot be broken; "
            "a later shortcut installation can safely reuse or update it"
        )
        atomic_json(data_dir / "start-menu-shortcut.restored.json", result)
    return result


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
    hosted_status = (
        _hosted_runtime_status(receipt)
        if receipt.get("schemaVersion") == 4
        else {"present": False, "matches": True, "legacyReceipt": True}
    )
    everything_matches = shortcut_matches and original_matches and hosted_status["matches"]
    return {
        "ok": everything_matches,
        "status": "installed" if everything_matches else "drifted",
        "shortcuts": shortcut_results,
        "originalShortcut": str(original),
        "allShortcutSemanticsMatch": shortcut_matches,
        "originalShortcutSemanticMatches": original_matches,
        "hostedRuntime": hosted_status,
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
    install.add_argument(
        "--acknowledge-adds-start-menu-shortcut",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    install.add_argument("--acknowledge-adds-windows-shortcuts", action="store_true")
    install.add_argument(
        "--acknowledge-replaces-start-menu-shortcut",
        action="store_true",
        help=argparse.SUPPRESS,
    )
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
                acknowledged=args.acknowledge_adds_windows_shortcuts,
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
