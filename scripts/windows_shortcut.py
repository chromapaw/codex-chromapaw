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
import time
from pathlib import Path
from typing import Any

try:
    from .windows_official_launcher import OfficialCodexLaunchError, probe_current_official_codex
    from .windows_runtime import (
        RuntimeFailure,
        atomic_json,
        build_preflight,
        runtime_data_dir,
        select_adapter,
        sha256_file,
        utc_now,
    )
except ImportError:
    from windows_official_launcher import OfficialCodexLaunchError, probe_current_official_codex
    from windows_runtime import (  # type: ignore
        RuntimeFailure,
        atomic_json,
        build_preflight,
        runtime_data_dir,
        select_adapter,
        sha256_file,
        utc_now,
    )


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "windows_skin_launcher.py"
RECEIPT_FILE = "start-menu-shortcut.json"
SHORTCUT_DESCRIPTION = "Launch Codex with the last validated ChromaPaw skin"
HOSTED_RUNTIME_DIR = "shortcut-runtime"
HOSTED_RUNTIME_SOURCES = (
    ("scripts/windows_pending_activation.py", ROOT / "scripts" / "windows_pending_activation.py"),
    ("scripts/windows_profile_repair.py", ROOT / "scripts" / "windows_profile_repair.py"),
    ("scripts/windows_skin_launcher.py", ROOT / "scripts" / "windows_skin_launcher.py"),
    ("scripts/windows_runtime.py", ROOT / "scripts" / "windows_runtime.py"),
    ("scripts/cdp_client.py", ROOT / "scripts" / "cdp_client.py"),
    ("scripts/skin_package.py", ROOT / "scripts" / "skin_package.py"),
    ("scripts/validate_skin_package.py", ROOT / "scripts" / "validate_skin_package.py"),
    ("scripts/theme_profile.py", ROOT / "scripts" / "theme_profile.py"),
    ("scripts/windows_official_launcher.py", ROOT / "scripts" / "windows_official_launcher.py"),
)
HOSTED_BOOTSTRAP = '''#!/usr/bin/env python3
"""Stable entry point for the locally hosted ChromaPaw Windows runtime."""
from __future__ import annotations

import ctypes
import json
import os
import runpy
import subprocess
import sys
import hashlib
from pathlib import Path


# CHROMAPAW_OFFICIAL_LAUNCHER


def _fail(message: str) -> int:
    if os.name == "nt" and os.environ.get("CHROMAPAW_SUPPRESS_ERROR_DIALOG") != "1":
        try:
            ctypes.windll.user32.MessageBoxW(
                0, message, "ChromaPaw could not start Codex", 0x00000010
            )
        except Exception:
            pass
    return 1


def _explicit_data_dir_from_arguments() -> Path | None:
    try:
        index = sys.argv.index("--data-dir")
        return Path(sys.argv[index + 1]).expanduser().resolve()
    except (ValueError, IndexError):
        explicit = os.environ.get("CHROMAPAW_DATA_DIR")
        return Path(explicit).expanduser().resolve() if explicit else None


def _fallback_saved_codex(message: str) -> bool:
    """Keep the shortcut useful without trusting a changed executable."""
    try:
        data_dir = _explicit_data_dir_from_arguments()
        if data_dir is None:
            return False
        preference = json.loads(
            (data_dir / "preferred-skin.json").read_text(encoding="utf-8")
        )
        executable = Path(str(preference["executable"])).expanduser().resolve()
        expected_hash = preference.get("executableHash")
        if not executable.is_file() or not isinstance(expected_hash, str):
            return False
        digest = hashlib.sha256()
        with executable.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_hash:
            return False
        process = subprocess.Popen(
            [str(executable)],
            cwd=executable.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        log = data_dir / "launcher.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8", newline="\\n") as stream:
            stream.write(
                json.dumps(
                    {
                        "event": "bootstrap-fallback-plain-codex",
                        "error": message,
                        "pid": process.pid,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\\n"
            )
        return True
    except Exception:
        return False


def _fallback_plain_codex(message: str) -> bool:
    if _fallback_saved_codex(message):
        return True
    try:
        data_dir = _explicit_data_dir_from_arguments()
        if data_dir is None:
            return False
        preference = json.loads((data_dir / "preferred-skin.json").read_text(encoding="utf-8"))
        if not isinstance(preference, dict) or not isinstance(preference.get("executable"), str):
            return False
        official = launch_current_official_codex(official_config_locale())
        try:
            with (data_dir / "launcher.jsonl").open("a", encoding="utf-8", newline="\\n") as stream:
                stream.write(json.dumps({
                    "event": "bootstrap-fallback-current-official-codex",
                    "error": message,
                    "fallback": official,
                    "guidance": "Codex opened without a skin; the saved skin needs compatibility review.",
                }, ensure_ascii=False, separators=(",", ":")) + "\\n")
        except OSError:
            pass
        return True
    except Exception:
        return False


def main() -> int:
    root = Path(__file__).resolve().parent
    try:
        current = json.loads((root / "current.json").read_text(encoding="utf-8"))
        state = current
        data_dir = _explicit_data_dir_from_arguments()
        preference = None
        pending = None
        sidebar_pending = None
        if data_dir is not None:
            preference_path = data_dir / "preferred-skin.json"
            try:
                preference = json.loads(preference_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                preference = None
            pending_path = data_dir / "pending-skin-activation.json"
            if pending_path.exists():
                if pending_path.is_symlink():
                    raise RuntimeError("pending activation cannot be a linked file")
                pending = json.loads(pending_path.read_text(encoding="utf-8"))
                if (not isinstance(pending, dict) or pending.get("schemaVersion") != 1
                        or pending.get("operation") != "activate" or pending.get("acknowledged") is not True):
                    raise RuntimeError("pending activation metadata is invalid")
            sidebar_path = data_dir / "pending-sidebar-profile-repair.json"
            if sidebar_path.exists():
                if sidebar_path.is_symlink():
                    raise RuntimeError("pending sidebar repair cannot be a linked file")
                sidebar_pending = json.loads(sidebar_path.read_text(encoding="utf-8"))
                if (not isinstance(sidebar_pending, dict) or sidebar_pending.get("schemaVersion") != 1
                        or sidebar_pending.get("operation") != "repair-sidebar"
                        or sidebar_pending.get("acknowledged") is not True):
                    raise RuntimeError("pending sidebar repair metadata is invalid")
        # A reviewed fresh activation takes precedence over an obsolete saved skin.
        # All bundle files are verified below; the launcher rechecks every target identity.
        selected = pending if pending is not None else (
            sidebar_pending if sidebar_pending is not None else preference
        )
        if isinstance(selected, dict):
            pinned_generation = selected.get("runtimeGeneration")
            pinned_bundle_hash = selected.get("runtimeBundleHash")
            if (
                isinstance(pinned_generation, str)
                and isinstance(pinned_bundle_hash, str)
                and pinned_generation == f"sha256-{pinned_bundle_hash}"
            ):
                state = {
                    "schemaVersion": 1,
                    "generation": pinned_generation,
                    "bundleHash": pinned_bundle_hash,
                }
            elif pending is not None or sidebar_pending is not None:
                raise RuntimeError("pending operation hosted generation is invalid")
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
        os.environ["CHROMAPAW_HOSTED_GENERATION"] = generation_name
        os.environ["CHROMAPAW_HOSTED_BUNDLE_HASH"] = str(manifest["bundleHash"])
        sys.path.insert(0, str(launcher.parent))
        quiet_recovery = []
        if pending is None and sidebar_pending is None and isinstance(preference, dict) and not Path(str(preference.get("executable", ""))).is_file():
            quiet_recovery = ["--no-error-dialog"]
        sys.argv = [str(launcher), "--adapters", str(adapters), *quiet_recovery, *sys.argv[1:]]
        runpy.run_path(str(launcher), run_name="__main__")
        return 0
    except SystemExit as exc:
        try:
            code = int(exc.code or 0)
        except (TypeError, ValueError):
            code = 1
        # Code 2 means the user declined a restart, not a launch failure.
        if code in (0, 2) or not _fallback_plain_codex(f"hosted launcher exited with code {code}"):
            return code
        return 0
    except Exception as exc:
        if _fallback_plain_codex(str(exc)):
            return 0
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
'''
HOSTED_BOOTSTRAP = HOSTED_BOOTSTRAP.replace(
    "# CHROMAPAW_OFFICIAL_LAUNCHER",
    (ROOT / "scripts" / "windows_official_launcher.py").read_text(encoding="utf-8"),
)


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
            _publish_hosted_generation(staging, generation, manifest)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
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


def _publish_hosted_generation(
    staging: Path,
    generation: Path,
    manifest: dict[str, Any],
    *,
    attempts: int = 5,
) -> None:
    """Publish an immutable runtime directory despite short Windows file locks."""
    for attempt in range(attempts):
        if generation.exists():
            if not generation.is_dir():
                raise RuntimeFailure(
                    f"hosted runtime generation path is not a directory: {generation}"
                )
            _verify_generation(generation, manifest)
            return
        try:
            os.replace(staging, generation)
            return
        except OSError as exc:
            transient = isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {
                5,
                32,
                33,
            }
            if not transient or attempt + 1 >= attempts:
                raise RuntimeFailure(
                    f"hosted runtime generation could not be published: {generation}: {exc}"
                ) from exc
            time.sleep(0.05 * (2**attempt))
    raise RuntimeFailure(f"hosted runtime generation could not be published: {generation}")


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


def _bind_preference_to_hosted_runtime(
    data_dir: Path,
    hosted_runtime: dict[str, Any],
    *,
    upgrade_reviewed_runtime: bool = False,
) -> dict[str, Any] | None:
    """Pin a reviewed skin to one immutable hosted runtime generation."""
    preference_path = data_dir / "preferred-skin.json"
    if not preference_path.is_file():
        return None
    try:
        preference = json.loads(preference_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeFailure(f"preferred skin state cannot be read: {exc}") from exc
    if not isinstance(preference, dict) or preference.get("schemaVersion") != 1:
        raise RuntimeFailure("preferred skin state is invalid")
    existing_generation = preference.get("runtimeGeneration")
    existing_hash = preference.get("runtimeBundleHash")
    if isinstance(existing_generation, str) or isinstance(existing_hash, str):
        if existing_generation != f"sha256-{existing_hash}":
            raise RuntimeFailure("preferred skin runtime generation identity is invalid")
        if not upgrade_reviewed_runtime:
            return preference
    generation = hosted_runtime.get("generation")
    bundle_hash = hosted_runtime.get("bundleHash")
    if generation != f"sha256-{bundle_hash}":
        raise RuntimeFailure("hosted runtime generation identity is invalid")
    generation_dir = Path(str(hosted_runtime.get("generationDir", ""))).resolve()
    preflight = build_preflight(
        Path(str(preference.get("package", ""))),
        Path(str(preference.get("executable", ""))),
        generation_dir / "runtime" / "windows-adapters.json",
    )
    continuity_fields = (
        "executableHash",
        "manifestHash",
        "cssHash",
        "adapterFileHash",
        "adapterId",
        "appVersion",
    )
    changed = sorted(
        field for field in continuity_fields if preflight.get(field) != preference.get(field)
    )
    if changed:
        raise RuntimeFailure(
            "preferred skin does not match the hosted runtime candidate; "
            "activate it again after reviewing changes: " + ", ".join(changed)
        )
    preference["runtimeGeneration"] = generation
    preference["runtimeBundleHash"] = bundle_hash
    preference["runtimePinnedAt"] = utc_now()
    atomic_json(preference_path, preference)
    return preference


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
    upgrade_reviewed_runtime: bool = False,
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

    selected_adapter = select_adapter(executable, adapters)
    launch_strategy = selected_adapter.get("launchStrategy", {"kind": "direct"})
    is_packaged_app = launch_strategy.get("kind") == "appx-activation-manager"
    original_observed = "present" if original_shortcut.is_file() else "absent"
    original_semantic_hash: str | None = None
    if original_observed == "present":
        original = inspect_shortcut(original_shortcut)
        if (
            not is_packaged_app
            and shortcut_semantics(original)["target"]
            != _normalize_path(str(executable))
        ):
            raise RuntimeFailure(
                "the existing ChatGPT shortcut does not target the selected Codex executable"
            )
        original_semantic_hash = shortcut_semantic_hash(original)
    elif not is_packaged_app:
        raise RuntimeFailure(
            "the original ChatGPT shortcut is missing for the selected standalone Codex executable"
        )

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
    preference_path = data_dir / "preferred-skin.json"
    preference_snapshot = (
        preference_path.read_bytes() if preference_path.is_file() else None
    )
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
        _bind_preference_to_hosted_runtime(
            data_dir,
            hosted_runtime,
            upgrade_reviewed_runtime=upgrade_reviewed_runtime,
        )
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
            "originalShortcutObservedAtInstall": original_observed,
            "originalShortcutTargetRequired": not is_packaged_app,
            "target": str(pythonw),
            "arguments": arguments,
            "selectedExecutable": str(executable),
            "selectedExecutableHash": sha256_file(executable),
            "selectedAdapterId": selected_adapter["id"],
            "launchStrategy": launch_strategy,
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
        _restore_optional_bytes(preference_path, preference_snapshot)
        raise
    assert result is not None
    return result


def repair_shortcut_launcher(
    data_dir: Path, adapters: Path, *, acknowledged: bool,
) -> dict[str, Any]:
    """Repair ordinary startup without adopting a new skin/executable identity."""
    if not acknowledged:
        raise RuntimeFailure("launcher repair requires --acknowledge-repairs-windows-launcher")
    if os.name != "nt":
        raise RuntimeFailure("Windows launcher repair is Windows-only")
    data_dir = data_dir.expanduser().resolve()
    receipt = _load_receipt(data_dir)
    if not receipt or receipt.get("schemaVersion") != 4 or receipt.get("mode") != "add":
        raise RuntimeFailure("launcher repair requires an existing managed hosted shortcut receipt")
    if not shortcut_status(data_dir)["ok"]:
        raise RuntimeFailure("managed shortcut or hosted runtime ownership changed; refusing repair")
    try:
        official = probe_current_official_codex()
    except OfficialCodexLaunchError as exc:
        raise RuntimeFailure(str(exc)) from exc
    hosted_root = data_dir / HOSTED_RUNTIME_DIR
    paths = (hosted_root / "bootstrap.py", hosted_root / "current.json", data_dir / RECEIPT_FILE)
    snapshots = {path: path.read_bytes() if path.is_file() else None for path in paths}
    preference = data_dir / "preferred-skin.json"
    preference_before = preference.read_bytes() if preference.is_file() else None
    try:
        hosted = _install_hosted_runtime(data_dir, adapters.expanduser().resolve())
        repaired = {
            **receipt,
            "launcherRepairedAt": utc_now(),
            "launcher": hosted["bootstrap"],
            "launcherHash": hosted["bootstrapHash"],
            "adapterFile": str(Path(hosted["generationDir"]) / "runtime" / "windows-adapters.json"),
            "adapterFileHash": sha256_file(adapters),
            "hostedRuntime": hosted,
            "plainOfficialFallback": official,
        }
        atomic_json(data_dir / RECEIPT_FILE, repaired)
        after = shortcut_status(data_dir)
        if not after["ok"]:
            raise RuntimeFailure("repaired launcher failed ownership verification")
        preference_after = preference.read_bytes() if preference.is_file() else None
        if preference_after != preference_before:
            raise RuntimeFailure("saved skin changed concurrently; launcher repair was rolled back")
        return {
            "ok": True, "status": "launcher-repaired", "skinPreferenceChanged": False,
            "shortcutsChanged": False, "skinActivated": False,
            "officialCodex": official, "verification": after,
        }
    except Exception:
        for path, content in snapshots.items():
            _restore_optional_bytes(path, content)
        # Never overwrite a concurrent preference update.
        raise


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
    original_observed = receipt.get("originalShortcutObservedAtInstall")
    original_unmanaged = original_observed == "absent"
    if original_unmanaged:
        # Packaged Codex installs may expose only a StartApps identity and no
        # filesystem .lnk. ChromaPaw neither creates nor owns that entry.
        original_matches = True
    else:
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
        "originalShortcutPresent": original.is_file(),
        "originalShortcutUnmanaged": original_unmanaged,
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
        "--upgrade-reviewed-runtime",
        action="store_true",
        help=(
            "move an existing reviewed skin to the newly installed immutable runtime only "
            "after all continuity identities match"
        ),
    )
    install.add_argument(
        "--acknowledge-replaces-start-menu-shortcut",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    subparsers.add_parser("restore")
    subparsers.add_parser("status")
    repair = subparsers.add_parser("repair-launcher")
    repair.add_argument("--adapters", type=Path, default=ROOT / "runtime" / "windows-adapters.json")
    repair.add_argument("--acknowledge-repairs-windows-launcher", action="store_true")

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
                upgrade_reviewed_runtime=args.upgrade_reviewed_runtime,
                original_shortcut=args.original_shortcut,
                desktop_shortcut=args.desktop_shortcut,
            )
        elif args.command == "restore":
            result = restore_shortcut(data_dir)
        elif args.command == "repair-launcher":
            result = repair_shortcut_launcher(
                data_dir, args.adapters,
                acknowledged=args.acknowledge_repairs_windows_launcher,
            )
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
