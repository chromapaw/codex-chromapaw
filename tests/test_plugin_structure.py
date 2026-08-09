from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PluginStructureTests(unittest.TestCase):
    def test_manifest_and_skills_exist(self) -> None:
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], ROOT.name)
        self.assertEqual(manifest["version"], "0.2.0")
        self.assertEqual(manifest["license"], "Apache-2.0")
        self.assertEqual(manifest["skills"], "./skills/")
        for name in ("create-chromapaw-pet", "create-chromapaw-skin", "manage-chromapaw"):
            self.assertTrue((ROOT / "skills" / name / "SKILL.md").is_file())

    def test_pet_mvp_assets_exist(self) -> None:
        expected = (
            "schemas/pet.schema.json",
            "scripts/pet_package.py",
            "scripts/prepare_pet_request.py",
            "scripts/validate_pet_package.py",
            "scripts/install_pet.py",
            "scripts/restore_pet.py",
            "skills/create-chromapaw-pet/references/pet-mvp.md",
        )
        for relative in expected:
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
