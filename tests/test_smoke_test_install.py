from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_test_install import (  # noqa: E402
    PLUGIN_NAME,
    SmokeTestError,
    installed_plugin_from_result,
    isolated_environment,
    marketplace_plugin_root,
    stage_local_marketplace,
    verify_installed_content,
    verify_plugin_listing,
)


class SmokeTestInstallTests(unittest.TestCase):
    def installed_listing(self, **changes: object) -> str:
        entry = {
            "pluginId": "codex-chromapaw@chromapaw",
            "name": PLUGIN_NAME,
            "marketplaceName": "chromapaw",
            "version": "0.4.8",
            "installed": True,
            "enabled": True,
        }
        entry.update(changes)
        return json.dumps({"installed": [entry], "available": []})

    def test_structured_listing_accepts_exact_enabled_version(self) -> None:
        verify_plugin_listing(self.installed_listing(), "0.4.8")

    def test_structured_listing_rejects_false_success(self) -> None:
        for change in (
            {"version": "0.4.7"}, {"enabled": False}, {"installed": False},
            {"enabled": "true"}, {"installed": 1}, {"name": "other"},
            {"marketplaceName": "other"}, {"pluginId": "codex-chromapaw@other"},
        ):
            with self.subTest(change=change), self.assertRaises(SmokeTestError):
                verify_plugin_listing(self.installed_listing(**change), "0.4.8")

    def test_structured_listing_rejects_invalid_missing_and_duplicate_entries(self) -> None:
        entry = json.loads(self.installed_listing())["installed"][0]
        for value in (
            "not json", "[]", "{}", '{"installed": {}}',
            json.dumps({"installed": [], "available": [entry]}),
            json.dumps({"installed": [entry, entry]}),
        ):
            with self.subTest(value=value), self.assertRaises(SmokeTestError):
                verify_plugin_listing(value, "0.4.8")

    def test_isolated_environment_removes_external_dependency_override(self) -> None:
        with mock.patch.dict(os.environ, {"CHROMAPAW_HATCH_PET_DIR": "external-skill"}):
            env = isolated_environment(Path("isolated-home"))
            self.assertNotIn("CHROMAPAW_HATCH_PET_DIR", env)
            self.assertEqual(env["CODEX_HOME"], "isolated-home")
            self.assertEqual(os.environ["CHROMAPAW_HATCH_PET_DIR"], "external-skill")

    def test_local_marketplace_stages_current_plugin_without_worktree_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary) / "marketplace"
            result = stage_local_marketplace(ROOT, staging)
            marketplace = json.loads(
                (result / ".agents" / "plugins" / "marketplace.json").read_text(
                    encoding="utf-8"
                )
            )
            plugin = marketplace["plugins"][0]
            self.assertEqual(plugin["name"], PLUGIN_NAME)
            self.assertEqual(plugin["source"]["source"], "local")
            self.assertEqual(plugin["source"]["path"], ".")
            staged = result
            self.assertTrue((staged / ".codex-plugin" / "plugin.json").is_file())
            self.assertEqual(marketplace_plugin_root(result), staged)
            self.assertFalse((staged / ".git").exists())
            self.assertFalse((staged / "work").exists())
            self.assertFalse((staged / "outputs").exists())
            self.assertFalse((staged / "node_modules").exists())
            self.assertFalse((staged / "artifacts").exists())
            self.assertGreater(verify_installed_content(ROOT, staged), 0)

    def test_content_check_rejects_stale_code_with_the_same_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            installed = Path(temporary) / "installed"
            for root in (source, installed):
                (root / ".codex-plugin").mkdir(parents=True)
                (root / ".codex-plugin" / "plugin.json").write_text(
                    json.dumps({"name": PLUGIN_NAME, "version": "0.4.8"}), encoding="utf-8"
                )
                (root / "runtime.py").write_text("new code", encoding="utf-8")
            self.assertEqual(verify_installed_content(source, installed), 2)
            (installed / "runtime.py").write_text("old code", encoding="utf-8")
            with self.assertRaisesRegex(SmokeTestError, r"changed=\['runtime.py'\]"):
                verify_installed_content(source, installed)

    def test_content_check_reports_missing_and_unexpected_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            installed = Path(temporary) / "installed"
            source.mkdir()
            installed.mkdir()
            (source / "recovery.py").write_text("required", encoding="utf-8")
            (installed / "obsolete.py").write_text("stale", encoding="utf-8")
            with self.assertRaisesRegex(
                SmokeTestError, r"missing=\['recovery.py'\], unexpected=\['obsolete.py'\]"
            ):
                verify_installed_content(source, installed)

    def test_staging_excludes_local_dependencies_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            (source / ".codex-plugin").mkdir(parents=True)
            (source / ".codex-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
            (source / ".agents" / "plugins").mkdir(parents=True)
            (source / ".agents" / "plugins" / "marketplace.json").write_text("{}", encoding="utf-8")
            for directory in ("node_modules", "artifacts", ".pytest_cache"):
                (source / directory).mkdir()
                (source / directory / "private.txt").write_text("local only", encoding="utf-8")
            staged = stage_local_marketplace(source, Path(temporary) / "staged")
            for directory in ("node_modules", "artifacts", ".pytest_cache"):
                self.assertFalse((staged / directory).exists())
            self.assertEqual(verify_installed_content(source, staged), 2)

    def test_staging_refuses_recursive_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / ".codex-plugin").mkdir()
            (source / ".codex-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(SmokeTestError, "outside the distributable source"):
                stage_local_marketplace(source, source / "nested")

    def test_install_result_rejects_a_version_from_another_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            installed = home / "plugins" / "cache" / "chromapaw" / PLUGIN_NAME / "0.4.6"
            manifest = installed / ".codex-plugin" / "plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps({"name": PLUGIN_NAME, "version": "0.4.6"}),
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {"installedPath": str(installed), "version": "0.4.6"}
                ),
                stderr="",
            )
            with self.assertRaisesRegex(
                SmokeTestError,
                "does not match the selected marketplace snapshot",
            ):
                installed_plugin_from_result(completed, home, "0.4.7")


if __name__ == "__main__":
    unittest.main()
