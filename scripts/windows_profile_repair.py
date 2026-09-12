"""Repair the Windows Codex project sidebar after the app-server migration.

The repair imports only the legacy saved workspace roots and their existing
thread ids through the current Codex app-server ``project/import`` method, then
rebuilds the Electron project index consumed by the sidebar.  It does not copy
Chromium profiles, authentication data, or conversation text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import secrets
from pathlib import Path, PureWindowsPath
from typing import Any

try:
    from .windows_official_launcher import OfficialCodexLaunchError, probe_current_official_codex
except ImportError:  # pragma: no cover - direct script execution
    from windows_official_launcher import OfficialCodexLaunchError, probe_current_official_codex


class ProfileRepairError(RuntimeError):
    pass


PENDING_SIDEBAR_FILE = "pending-sidebar-profile-repair.json"
SIDEBAR_RESULT_FILE = "pending-sidebar-profile-repair-result.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_windows_path(value: str) -> str:
    normalized = value
    if normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    return ntpath.normpath(normalized).casefold()


def _inside_windows_root(candidate: str, root: str) -> bool:
    candidate_key = _normalize_windows_path(candidate)
    root_key = _normalize_windows_path(root).rstrip("\\/")
    return candidate_key == root_key or candidate_key.startswith(root_key + "\\")


def _load_global_state(codex_home: Path) -> dict[str, Any]:
    path = codex_home / ".codex-global-state.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProfileRepairError(f"could not read Codex global state: {exc}") from exc
    if not isinstance(value, dict):
        raise ProfileRepairError("Codex global state is not a JSON object")
    return value


def _saved_roots(state: dict[str, Any]) -> list[str]:
    raw = state.get("electron-saved-workspace-roots", [])
    if not isinstance(raw, list):
        raise ProfileRepairError("legacy saved workspace roots are malformed")
    roots: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str) or not PureWindowsPath(value).is_absolute():
            raise ProfileRepairError("legacy saved workspace root is not an absolute Windows path")
        key = _normalize_windows_path(value)
        if key not in seen:
            roots.append(ntpath.normpath(value))
            seen.add(key)
    return roots


def _legacy_project_id(root: str) -> str:
    """Return the deterministic id used by Codex's legacy project migration."""
    return "local-" + hashlib.sha256(root.encode("utf-8")).hexdigest()[:32]


def _database_projects(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute("""
        SELECT p.id, p.name, p.position, p.created_at_ms, p.updated_at_ms,
               r.path, r.position AS root_position
          FROM projects AS p
          LEFT JOIN project_roots AS r ON r.project_id = p.id
         ORDER BY p.position, p.created_at_ms, r.position
    """).fetchall()
    projects: dict[str, dict[str, Any]] = {}
    for row in rows:
        project_id = str(row["id"])
        project = projects.setdefault(project_id, {
            "id": project_id,
            "name": str(row["name"]),
            "position": int(row["position"]),
            "createdAt": int(row["created_at_ms"]),
            "updatedAt": int(row["updated_at_ms"]),
            "roots": [],
        })
        if isinstance(row["path"], str):
            project["roots"].append({"path": row["path"]})
    return list(projects.values())


def _project_for_root(projects: list[dict[str, Any]], root: str) -> dict[str, Any] | None:
    key = _normalize_windows_path(root)
    for project in projects:
        if key in _project_root_keys([project]):
            return project
    return None


def _sidebar_index_snapshot(state: dict[str, Any], codex_home: Path,
                            roots: list[str],
                            database_projects: list[dict[str, Any]]) -> dict[str, Any]:
    raw_projects = state.get("local-projects")
    local_projects = raw_projects if isinstance(raw_projects, dict) else {}
    identity = f"local:{codex_home}"
    raw_mappings = state.get("app-server-project-id-by-legacy-project-id-by-host")
    mappings_by_host = raw_mappings if isinstance(raw_mappings, dict) else {}
    raw_host_mapping = mappings_by_host.get(identity)
    host_mapping = raw_host_mapping if isinstance(raw_host_mapping, dict) else {}
    entries: list[dict[str, Any]] = []
    for root in roots:
        legacy_id = _legacy_project_id(root)
        server_project = _project_for_root(database_projects, root)
        server_id = server_project.get("id") if server_project else None
        entries.append({
            "root": root,
            "legacyProjectId": legacy_id,
            "serverProjectId": server_id,
            "localProjectCached": legacy_id in local_projects,
            "mappingMatches": isinstance(server_id, str)
            and host_mapping.get(legacy_id) == server_id,
        })
    return {
        "sidebarLocalProjectCount": len(local_projects),
        "sidebarIndexedSavedRootCount": sum(
            entry["localProjectCached"] and entry["mappingMatches"] for entry in entries
        ),
        "sidebarIndexEntries": entries,
        "migrationIdentity": identity,
    }


def _database_snapshot(codex_home: Path, roots: list[str], *,
                       include_thread_ids: bool = False) -> dict[str, Any]:
    database = codex_home / "state_5.sqlite"
    if not database.is_file():
        raise ProfileRepairError(f"Codex state database does not exist: {database}")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            project_count = int(connection.execute("SELECT count(*) FROM projects").fetchone()[0])
            thread_count = int(connection.execute("SELECT count(*) FROM threads").fetchone()[0])
            unassigned_count = int(connection.execute(
                "SELECT count(*) FROM threads WHERE project_id IS NULL"
            ).fetchone()[0])
            rows = connection.execute(
                "SELECT id, cwd, project_id FROM threads ORDER BY created_at, id"
            ).fetchall()
            database_projects = _database_projects(connection)
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ProfileRepairError(f"could not inspect Codex state database: {exc}") from exc

    projects = []
    for position, root in enumerate(roots):
        matched = [row for row in rows
                   if isinstance(row["cwd"], str) and _inside_windows_root(row["cwd"], root)]
        thread_ids = [str(row["id"]) for row in matched if row["project_id"] is None]
        project = {
            "root": root,
            "name": ntpath.basename(root.rstrip("\\/")) or root,
            "position": position,
            "threadCount": len(matched),
            "unassignedThreadCount": len(thread_ids),
            "rootExists": Path(root).is_dir(),
        }
        if include_thread_ids:
            project["threadIds"] = thread_ids
        server_project = _project_for_root(database_projects, root)
        project["serverProjectId"] = server_project.get("id") if server_project else None
        projects.append(project)
    return {
        "database": str(database.resolve()),
        "projectCount": project_count,
        "threadCount": thread_count,
        "unassignedThreadCount": unassigned_count,
        "legacyProjects": projects,
        "databaseProjects": database_projects,
    }


def inspect_sidebar_profile(codex_home: Path, *,
                            _include_thread_ids: bool = False) -> dict[str, Any]:
    codex_home = codex_home.expanduser().resolve()
    state = _load_global_state(codex_home)
    roots = _saved_roots(state)
    snapshot = _database_snapshot(
        codex_home, roots, include_thread_ids=_include_thread_ids
    )
    sidebar = _sidebar_index_snapshot(
        state, codex_home, roots, snapshot["databaseProjects"]
    )
    if roots and snapshot["projectCount"] == 0:
        status = "migration-needed"
    elif roots and sidebar["sidebarIndexedSavedRootCount"] < len(roots):
        status = "sidebar-index-missing"
    else:
        status = "ready"
    return {
        "ok": True,
        "status": status,
        "codexHome": str(codex_home),
        "legacySavedRootCount": len(roots),
        **snapshot,
        **sidebar,
    }


def _backup_profile(codex_home: Path) -> dict[str, Any]:
    backup_root = (codex_home / "chromapaw" / "backups" / "sidebar-profile").resolve()
    declared_root = codex_home.resolve()
    if os.path.commonpath((str(backup_root), str(declared_root))) != str(declared_root):
        raise ProfileRepairError("profile backup directory escapes CODEX_HOME")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = backup_root / f"repair-{stamp}-{os.getpid()}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    source_db = codex_home / "state_5.sqlite"
    backup_db = backup_dir / "state_5.sqlite.before"
    source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True, timeout=10)
    destination = sqlite3.connect(backup_db)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    global_state = codex_home / ".codex-global-state.json"
    backup_global = backup_dir / ".codex-global-state.json.before"
    shutil.copy2(global_state, backup_global)
    result = {
        "directory": str(backup_dir),
        "database": str(backup_db),
        "databaseSha256": _sha256(backup_db),
        "globalState": str(backup_global),
        "globalStateSha256": _sha256(backup_global),
    }
    (backup_dir / "before.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def _verified_codex_cli(official: dict[str, Any]) -> tuple[Path, str]:
    executable_value = official.get("executable")
    if not isinstance(executable_value, str):
        raise ProfileRepairError("official Codex probe did not return an executable")
    executable = Path(executable_value).resolve()
    expected = (executable.parent / "resources" / "codex.exe").resolve()
    if expected.parent != (executable.parent / "resources").resolve() or not expected.is_file():
        raise ProfileRepairError("official Codex app-server executable is missing")
    return expected, _sha256(expected)


class _AppServerClient:
    def __init__(self, codex_cli: Path, codex_home: Path):
        self._codex_home = codex_home.resolve()
        self._temporary = tempfile.TemporaryDirectory(prefix="chromapaw-profile-repair-")
        copied = Path(self._temporary.name) / "codex.exe"
        shutil.copy2(codex_cli, copied)
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(codex_home)
        self._process = subprocess.Popen(
            [str(copied), "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
        self._next_id = 1

    def __enter__(self) -> "_AppServerClient":
        try:
            response = self.call("initialize", {
                "clientInfo": {"name": "chromapaw-profile-repair", "version": "0.4.8"},
                "capabilities": {"experimentalApi": True},
            })
            reported_home = response.get("codexHome")
            if (response.get("platformOs") != "windows" or not isinstance(reported_home, str)
                    or Path(reported_home).resolve() != self._codex_home):
                raise ProfileRepairError("Codex app-server identity or CODEX_HOME did not match")
            return self
        except Exception:
            self._close()
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        stderr = self._close()
        if exc_type is None and self._process.returncode not in (0, None):
            raise ProfileRepairError(stderr.strip() or "Codex app-server exited unexpectedly")

    def _close(self) -> str:
        process = self._process
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        stderr = process.stderr.read() if process.stderr else ""
        self._temporary.cleanup()
        return stderr

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        process = self._process
        if not process.stdin or not process.stdout:
            raise ProfileRepairError("Codex app-server pipes are unavailable")
        request_id = self._next_id
        self._next_id += 1
        process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params},
                                       separators=(",", ":")) + "\n")
        process.stdin.flush()
        while True:
            line = process.stdout.readline()
            if not line:
                stderr = process.stderr.read() if process.stderr else ""
                raise ProfileRepairError(stderr.strip() or "Codex app-server closed unexpectedly")
            try:
                response = json.loads(line)
            except ValueError:
                continue
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise ProfileRepairError(f"Codex app-server {method} failed: {response['error']}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise ProfileRepairError(f"Codex app-server {method} returned an invalid result")
            return result


def _project_root_keys(projects: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for project in projects:
        roots = project.get("roots")
        if not isinstance(roots, list):
            continue
        for root in roots:
            if isinstance(root, dict) and isinstance(root.get("path"), str):
                result.add(_normalize_windows_path(root["path"]))
    return result


def _timestamp(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return fallback


def _atomic_write_global_state(path: Path, state: dict[str, Any]) -> None:
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump(state, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _repair_sidebar_index(codex_home: Path, candidates: list[dict[str, Any]],
                          server_projects: list[dict[str, Any]]) -> dict[str, Any]:
    """Recreate the legacy-id cache used by the renderer without touching threads."""
    state_path = codex_home / ".codex-global-state.json"
    state = _load_global_state(codex_home)
    raw_local_projects = state.get("local-projects")
    local_projects = dict(raw_local_projects) if isinstance(raw_local_projects, dict) else {}
    raw_mappings = state.get("app-server-project-id-by-legacy-project-id-by-host")
    mappings = dict(raw_mappings) if isinstance(raw_mappings, dict) else {}
    identity = f"local:{codex_home}"
    raw_host_mapping = mappings.get(identity)
    host_mapping = dict(raw_host_mapping) if isinstance(raw_host_mapping, dict) else {}
    now = int(time.time() * 1000)
    indexed: list[dict[str, Any]] = []

    for position, candidate in enumerate(candidates):
        root = candidate["root"]
        server_project = _project_for_root(server_projects, root)
        if server_project is None or not isinstance(server_project.get("id"), str):
            raise ProfileRepairError(f"no app-server project exists for saved root: {root}")
        legacy_id = _legacy_project_id(root)
        server_id = server_project["id"]
        previous = local_projects.get(legacy_id)
        previous = previous if isinstance(previous, dict) else {}
        created_at = _timestamp(
            server_project.get("createdAt"),
            _timestamp(previous.get("createdAt"), now - position),
        )
        updated_at = _timestamp(
            server_project.get("updatedAt"),
            _timestamp(previous.get("updatedAt"), created_at),
        )
        name = server_project.get("name")
        if not isinstance(name, str) or not name.strip():
            name = candidate["name"]
        local_projects[legacy_id] = {
            "id": legacy_id,
            "name": name,
            "rootPaths": [root],
            "createdAt": created_at,
            "updatedAt": updated_at,
        }
        host_mapping[legacy_id] = server_id
        indexed.append({
            "root": root,
            "legacyProjectId": legacy_id,
            "serverProjectId": server_id,
        })

    mappings[identity] = host_mapping
    state["local-projects"] = local_projects
    state["app-server-project-id-by-legacy-project-id-by-host"] = mappings
    candidate_ids = [entry["legacyProjectId"] for entry in indexed]
    existing_order = state.get("project-order")
    existing_order = existing_order if isinstance(existing_order, list) else []
    state["project-order"] = candidate_ids + [
        value for value in existing_order
        if isinstance(value, str) and value not in candidate_ids and value in local_projects
    ]

    selected = state.get("selected-project")
    selected_id = selected.get("projectId") if isinstance(selected, dict) else None
    if selected_id not in local_projects and candidate_ids:
        active_roots = state.get("active-workspace-roots")
        active_roots = active_roots if isinstance(active_roots, list) else []
        active_keys = {
            _normalize_windows_path(value) for value in active_roots if isinstance(value, str)
        }
        preferred = next(
            (entry["legacyProjectId"] for entry in indexed
             if _normalize_windows_path(entry["root"]) in active_keys),
            candidate_ids[0],
        )
        state["selected-project"] = {"type": "local", "projectId": preferred}

    _atomic_write_global_state(state_path, state)
    return {"identity": identity, "indexed": indexed}


def repair_sidebar_profile(codex_home: Path, *, acknowledged: bool) -> dict[str, Any]:
    if not acknowledged:
        raise ProfileRepairError(
            "sidebar repair requires --acknowledge-repairs-project-sidebar"
        )
    before = inspect_sidebar_profile(codex_home, _include_thread_ids=True)
    candidates = [project for project in before["legacyProjects"] if project["rootExists"]]
    if not candidates:
        raise ProfileRepairError("no existing legacy saved workspace roots are available to import")

    official = probe_current_official_codex()
    codex_cli, codex_cli_hash = _verified_codex_cli(official)
    backup = _backup_profile(codex_home.expanduser().resolve())
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    verified_projects = before["databaseProjects"]
    missing_candidates = [
        project for project in candidates
        if _project_for_root(verified_projects, project["root"]) is None
    ]
    if missing_candidates:
        with _AppServerClient(codex_cli, codex_home.expanduser().resolve()) as client:
            listed = client.call("project/list", {})
            projects = listed.get("data", [])
            if not isinstance(projects, list):
                raise ProfileRepairError("Codex app-server project list is malformed")
            existing_roots = _project_root_keys(projects)
            for project in candidates:
                root = project["root"]
                if _normalize_windows_path(root) in existing_roots:
                    skipped.append({"root": root, "reason": "already-imported"})
                    continue
                key_hash = hashlib.sha256(_normalize_windows_path(root).encode("utf-8")).hexdigest()
                response = client.call("project/import", {
                    "idempotencyKey": f"chromapaw-sidebar-repair-v1-{key_hash}",
                    "name": project["name"],
                    "roots": [{"path": root}],
                    "threads": project["threadIds"],
                    "metadata": {"migrationSource": "chromapaw-legacy-saved-workspace"},
                })
                created = response.get("project")
                if not isinstance(created, dict) or not isinstance(created.get("id"), str):
                    raise ProfileRepairError("Codex app-server did not confirm the imported project")
                imported.append({
                    "id": created["id"], "name": created.get("name", project["name"]),
                    "root": root, "threadCount": project["threadCount"],
                })
                existing_roots.add(_normalize_windows_path(root))
            verified = client.call("project/list", {})
            verified_projects = verified.get("data", [])
            if not isinstance(verified_projects, list):
                raise ProfileRepairError("Codex app-server verification list is malformed")
    else:
        skipped.extend({
            "root": project["root"], "reason": "already-imported"
        } for project in candidates)

    missing = [project["root"] for project in candidates
               if _project_for_root(verified_projects, project["root"]) is None]
    if missing:
        raise ProfileRepairError(f"project verification failed for: {missing}")
    sidebar_index = _repair_sidebar_index(
        codex_home.expanduser().resolve(), candidates, verified_projects
    )

    after = inspect_sidebar_profile(codex_home)
    if after["status"] != "ready":
        raise ProfileRepairError(
            f"sidebar index verification failed with status: {after['status']}"
        )
    receipt = {
        "ok": True,
        "status": "repaired",
        "codexHome": before["codexHome"],
        "officialCodex": {
            "executable": official.get("executable"),
            "appVersion": official.get("appVersion"),
            "packageFamilyName": official.get("packageFamilyName"),
            "signatureStatus": official.get("signatureStatus"),
            "codexCliSha256": codex_cli_hash,
        },
        "backup": backup,
        "imported": imported,
        "skipped": skipped,
        "sidebarIndex": sidebar_index,
        "before": {key: before[key] for key in (
            "projectCount", "threadCount", "unassignedThreadCount", "legacySavedRootCount"
        )},
        "after": {key: after[key] for key in (
            "projectCount", "threadCount", "unassignedThreadCount", "legacySavedRootCount"
        )},
        "restartRequired": True,
    }
    receipt_path = Path(backup["directory"]) / "result.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt["receipt"] = str(receipt_path)
    return receipt


def _hosted_identity() -> dict[str, str]:
    digest = os.environ.get("CHROMAPAW_HOSTED_BUNDLE_HASH", "")
    generation = os.environ.get("CHROMAPAW_HOSTED_GENERATION", "")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) \
            or generation != "sha256-" + digest:
        raise ProfileRepairError("sidebar repair requires an exact reviewed hosted generation")
    return {"runtimeBundleHash": digest, "runtimeGeneration": generation}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _pending_projects(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return [{"root": entry["root"], "legacyProjectId": entry["legacyProjectId"],
             "serverProjectId": entry["serverProjectId"]}
            for entry in snapshot["sidebarIndexEntries"]]


def prepare_sidebar_repair(codex_home: Path, data_dir: Path, *, acknowledged: bool) -> dict[str, Any]:
    if not acknowledged:
        raise ProfileRepairError("sidebar repair requires explicit acknowledgement")
    codex_home = codex_home.expanduser().resolve()
    data_dir = data_dir.expanduser().resolve()
    pending_path = data_dir / PENDING_SIDEBAR_FILE
    if pending_path.exists():
        raise ProfileRepairError("a pending sidebar repair already exists")
    before = inspect_sidebar_profile(codex_home)
    if before["status"] == "ready":
        raise ProfileRepairError("the sidebar project index is already ready")
    official = probe_current_official_codex()
    executable = Path(str(official["executable"])).resolve()
    codex_cli, codex_cli_hash = _verified_codex_cli(official)
    request = {
        "schemaVersion": 1, "operation": "repair-sidebar", "acknowledged": True,
        "requestId": secrets.token_hex(16), "preparedAt": int(time.time() * 1000),
        "codexHome": str(codex_home), "projects": _pending_projects(before),
        "officialExecutable": str(executable), "officialExecutableHash": _sha256(executable),
        "officialAppVersion": official.get("appVersion"),
        "officialPackageFamilyName": official.get("packageFamilyName"),
        "codexCli": str(codex_cli), "codexCliHash": codex_cli_hash, **_hosted_identity(),
    }
    _atomic_json(pending_path, request)
    return {"ok": True, "status": "pending-next-launch", "request": request,
            "requestFile": str(pending_path), "profileModified": False}


def read_prepared_sidebar_repair(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / PENDING_SIDEBAR_FILE
    if not path.exists():
        return None
    if path.is_symlink():
        raise ProfileRepairError("pending sidebar repair cannot be a linked file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProfileRepairError("pending sidebar repair cannot be read") from exc
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1
            or value.get("operation") != "repair-sidebar" or value.get("acknowledged") is not True
            or not isinstance(value.get("requestId"), str) or not isinstance(value.get("projects"), list)):
        raise ProfileRepairError("pending sidebar repair metadata is invalid")
    return value


def apply_prepared_sidebar_repair(codex_home: Path, data_dir: Path) -> dict[str, Any]:
    request = read_prepared_sidebar_repair(data_dir)
    if request is None:
        raise ProfileRepairError("no pending sidebar repair exists")
    if request.get("codexHome") != str(codex_home.expanduser().resolve()):
        raise ProfileRepairError("pending sidebar repair CODEX_HOME changed")
    if any(request.get(k) != v for k, v in _hosted_identity().items()):
        raise ProfileRepairError("pending sidebar repair hosted generation changed")
    official = probe_current_official_codex()
    executable = Path(str(official["executable"])).resolve()
    cli, cli_hash = _verified_codex_cli(official)
    current_official = {
        "officialExecutable": str(executable), "officialExecutableHash": _sha256(executable),
        "officialAppVersion": official.get("appVersion"),
        "officialPackageFamilyName": official.get("packageFamilyName"),
        "codexCli": str(cli), "codexCliHash": cli_hash,
    }
    for key, value in current_official.items():
        if request.get(key) != value:
            raise ProfileRepairError("pending sidebar repair official identity changed: " + key)
    before = inspect_sidebar_profile(codex_home)
    if _pending_projects(before) != request["projects"]:
        raise ProfileRepairError("pending sidebar repair project identities changed")
    repaired = repair_sidebar_profile(codex_home, acknowledged=True)
    after = inspect_sidebar_profile(codex_home)
    if after["status"] != "ready":
        raise ProfileRepairError("sidebar repair verification did not pass")
    result = {"ok": True, "status": "repaired-verified", "requestId": request["requestId"],
              "projects": request["projects"], "repair": repaired}
    _atomic_json(data_dir / SIDEBAR_RESULT_FILE, result)
    if read_prepared_sidebar_repair(data_dir) == request:
        (data_dir / PENDING_SIDEBAR_FILE).unlink()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--codex-home", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    repair = subparsers.add_parser("repair")
    repair.add_argument("--acknowledge-repairs-project-sidebar", action="store_true")
    prepare = subparsers.add_parser("prepare-next-launch")
    prepare.add_argument("--data-dir", type=Path, required=True)
    prepare.add_argument("--acknowledge-repairs-project-sidebar", action="store_true")
    apply_pending = subparsers.add_parser("apply-pending")
    apply_pending.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "status":
            result = inspect_sidebar_profile(args.codex_home)
        elif args.command == "repair":
            result = repair_sidebar_profile(
                args.codex_home,
                acknowledged=args.acknowledge_repairs_project_sidebar,
            )
        elif args.command == "prepare-next-launch":
            result = prepare_sidebar_repair(
                args.codex_home, args.data_dir,
                acknowledged=args.acknowledge_repairs_project_sidebar,
            )
        else:
            result = apply_prepared_sidebar_repair(args.codex_home, args.data_dir)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["status"])
        return 0
    except (ProfileRepairError, OfficialCodexLaunchError, OSError,
            sqlite3.Error, subprocess.SubprocessError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
