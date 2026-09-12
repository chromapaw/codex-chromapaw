from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import windows_profile_repair as repair


def _fixture_home(root: Path) -> Path:
    home = root / ".codex"
    home.mkdir()
    (home / ".codex-global-state.json").write_text(json.dumps({
        "electron-saved-workspace-roots": [
            r"C:\work\alpha", r"D:\work\beta", r"C:\work\alpha",
        ]
    }), encoding="utf-8")
    connection = sqlite3.connect(home / "state_5.sqlite")
    connection.executescript("""
        CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT, metadata TEXT,
            position INTEGER, created_at_ms INTEGER, updated_at_ms INTEGER);
        CREATE TABLE project_roots (project_id TEXT, position INTEGER, path TEXT);
        CREATE TABLE threads (id TEXT PRIMARY KEY, cwd TEXT, created_at INTEGER,
            project_id TEXT, archived INTEGER DEFAULT 0);
        INSERT INTO threads VALUES ('t1', '\\\\?\\C:\\work\\alpha', 1, NULL, 0);
        INSERT INTO threads VALUES ('t2', '\\\\?\\C:\\work\\alpha\\child', 2, NULL, 0);
        INSERT INTO threads VALUES ('t3', 'D:\\work\\beta', 3, NULL, 0);
        INSERT INTO threads VALUES ('t4', 'C:\\elsewhere', 4, NULL, 0);
    """)
    connection.commit()
    connection.close()
    return home


class WindowsProfileRepairTests(unittest.TestCase):
    def test_pending_repair_is_backed_by_exact_official_identity_and_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = _fixture_home(root).resolve()
            data = root / "runtime"
            data.mkdir()
            app = root / "app"
            (app / "resources").mkdir(parents=True)
            (app / "ChatGPT.exe").write_bytes(b"app")
            (app / "resources/codex.exe").write_bytes(b"cli")
            official = {"executable": str(app / "ChatGPT.exe"), "appVersion": "26.1.2.3",
                        "packageFamilyName": "OpenAI.Codex_2p2nqsd0c76g0", "signatureStatus": "Valid"}
            inspected = repair.inspect_sidebar_profile(home)
            with mock.patch("windows_profile_repair.probe_current_official_codex", return_value=official), mock.patch.dict(
                "os.environ", {"CHROMAPAW_HOSTED_GENERATION": "sha256-" + "b" * 64,
                               "CHROMAPAW_HOSTED_BUNDLE_HASH": "b" * 64}
            ):
                prepared = repair.prepare_sidebar_repair(home, data, acknowledged=True)
                self.assertEqual(prepared["status"], "pending-next-launch")
                self.assertEqual(repair.inspect_sidebar_profile(home), inspected)
                with mock.patch("windows_profile_repair.repair_sidebar_profile", return_value={"ok": True}) as execute, mock.patch(
                    "windows_profile_repair.inspect_sidebar_profile",
                    side_effect=[inspected, {**inspected, "status": "ready"}],
                ):
                    applied = repair.apply_prepared_sidebar_repair(home, data)
            execute.assert_called_once_with(home, acknowledged=True)
            self.assertTrue(applied["ok"])
            self.assertFalse((data / repair.PENDING_SIDEBAR_FILE).exists())

    def test_pending_repair_requires_explicit_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(repair.ProfileRepairError, "acknowledgement"):
                repair.prepare_sidebar_repair(Path(temporary), Path(temporary) / "runtime", acknowledged=False)

    def test_inspection_maps_only_saved_roots_without_reading_thread_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = _fixture_home(Path(temporary))
            with mock.patch("windows_profile_repair.Path.is_dir", return_value=True):
                result = repair.inspect_sidebar_profile(home)
            self.assertEqual(result["status"], "migration-needed")
            self.assertEqual(result["legacySavedRootCount"], 2)
            self.assertEqual([p["threadCount"] for p in result["legacyProjects"]], [2, 1])
            self.assertEqual([p["unassignedThreadCount"] for p in result["legacyProjects"]], [2, 1])
            self.assertNotIn("title", json.dumps(result))

    def test_repair_requires_explicit_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = _fixture_home(Path(temporary))
            with self.assertRaisesRegex(repair.ProfileRepairError, "requires --acknowledge"):
                repair.repair_sidebar_profile(home, acknowledged=False)

    def test_verified_cli_must_be_inside_official_app_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "app"
            (app / "resources").mkdir(parents=True)
            (app / "ChatGPT.exe").write_bytes(b"chatgpt")
            (app / "resources" / "codex.exe").write_bytes(b"codex")
            cli, digest = repair._verified_codex_cli({"executable": str(app / "ChatGPT.exe")})
            self.assertEqual(cli, (app / "resources" / "codex.exe").resolve())
            self.assertEqual(len(digest), 64)

    def test_sidebar_index_repair_preserves_legacy_ids_and_maps_server_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = _fixture_home(Path(temporary)).resolve()
            state_path = home / ".codex-global-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["active-workspace-roots"] = [r"D:\work\beta"]
            state["project-order"] = []
            state["local-projects"] = {}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            candidates = [
                {"root": r"C:\work\alpha", "name": "alpha"},
                {"root": r"D:\work\beta", "name": "beta"},
            ]
            server_projects = [
                {"id": "server-alpha", "name": "alpha", "createdAt": 10,
                 "updatedAt": 11, "roots": [{"path": r"C:\work\alpha"}]},
                {"id": "server-beta", "name": "beta", "createdAt": 20,
                 "updatedAt": 21, "roots": [{"path": r"D:\work\beta"}]},
            ]

            result = repair._repair_sidebar_index(home, candidates, server_projects)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            alpha_id = repair._legacy_project_id(r"C:\work\alpha")
            beta_id = repair._legacy_project_id(r"D:\work\beta")
            identity = f"local:{home}"

            self.assertEqual(updated["project-order"], [alpha_id, beta_id])
            self.assertEqual(updated["local-projects"][alpha_id]["rootPaths"],
                             [r"C:\work\alpha"])
            self.assertEqual(
                updated["app-server-project-id-by-legacy-project-id-by-host"]
                [identity][beta_id], "server-beta"
            )
            self.assertEqual(updated["selected-project"], {
                "type": "local", "projectId": beta_id,
            })
            self.assertEqual(len(result["indexed"]), 2)


if __name__ == "__main__":
    unittest.main()
