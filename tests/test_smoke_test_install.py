from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_test_install import PLUGIN_NAME, stage_local_marketplace  # noqa: E402


class SmokeTestInstallTests(unittest.TestCase):
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
            self.assertEqual(plugin["source"]["path"], f"./plugins/{PLUGIN_NAME}")
            staged = result / "plugins" / PLUGIN_NAME
            self.assertTrue((staged / ".codex-plugin" / "plugin.json").is_file())
            self.assertFalse((staged / ".git").exists())
            self.assertFalse((staged / "work").exists())
            self.assertFalse((staged / "outputs").exists())


if __name__ == "__main__":
    unittest.main()
