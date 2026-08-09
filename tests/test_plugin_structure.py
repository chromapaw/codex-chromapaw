from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PluginStructureTests(unittest.TestCase):
    def test_manifest_and_skills_exist(self) -> None:
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], ROOT.name)
        self.assertEqual(manifest["license"], "Apache-2.0")
        self.assertEqual(manifest["skills"], "./skills/")
        for name in ("create-chromapaw-pet", "create-chromapaw-skin", "manage-chromapaw"):
            self.assertTrue((ROOT / "skills" / name / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
