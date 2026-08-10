from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PluginStructureTests(unittest.TestCase):
    def test_manifest_and_skills_exist(self) -> None:
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], ROOT.name)
        self.assertEqual(manifest["version"], "0.4.0")
        self.assertEqual(manifest["license"], "Apache-2.0")
        self.assertEqual(manifest["skills"], "./skills/")
        for name in ("create-chromapaw-pet", "create-chromapaw-skin", "manage-chromapaw"):
            self.assertTrue((ROOT / "skills" / name / "SKILL.md").is_file())

    def test_repo_marketplace_points_to_root_plugin(self) -> None:
        path = ROOT / ".agents" / "plugins" / "marketplace.json"
        marketplace = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(marketplace["name"], "chromapaw")
        self.assertEqual(marketplace["interface"]["displayName"], "ChromaPaw")
        self.assertEqual(len(marketplace["plugins"]), 1)
        plugin = marketplace["plugins"][0]
        self.assertEqual(plugin["name"], "codex-chromapaw")
        self.assertEqual(plugin["source"]["source"], "url")
        self.assertEqual(
            plugin["source"]["url"],
            "https://github.com/chromapaw/codex-chromapaw.git",
        )
        self.assertEqual(plugin["source"]["ref"], "main")
        self.assertEqual(plugin["policy"]["installation"], "AVAILABLE")
        self.assertEqual(plugin["policy"]["authentication"], "ON_INSTALL")
        self.assertEqual(plugin["category"], "Creativity")

    def test_pet_mvp_assets_exist(self) -> None:
        expected = (
            "schemas/pet.schema.json",
            "scripts/pet_package.py",
            "scripts/prepare_pet_request.py",
            "scripts/validate_pet_package.py",
            "scripts/install_pet.py",
            "scripts/restore_pet.py",
            "scripts/check_dependencies.py",
            "scripts/smoke_test_install.py",
            "skills/create-chromapaw-pet/references/pet-mvp.md",
        )
        for relative in expected:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_skin_studio_assets_exist(self) -> None:
        expected = (
            "schemas/skin.schema.json",
            "scripts/skin_package.py",
            "scripts/prepare_skin_request.py",
            "scripts/build_skin_package.py",
            "scripts/validate_skin_package.py",
            "skills/create-chromapaw-skin/references/skin-package.md",
            "docs/SKIN_STUDIO_MVP.md",
            "requirements-skin.txt",
        )
        for relative in expected:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_windows_runtime_beta_assets_exist(self) -> None:
        expected = (
            "runtime/windows-adapters.json",
            "schemas/windows-runtime-adapters.schema.json",
            "scripts/cdp_client.py",
            "scripts/windows_runtime.py",
            "tests/test_windows_runtime.py",
            "docs/WINDOWS_RUNTIME_BETA.md",
        )
        for relative in expected:
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
