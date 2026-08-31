from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_test_install import (  # noqa: E402
    PLUGIN_NAME,
    SmokeTestError,
    installed_plugin_from_result,
    marketplace_plugin_root,
    stage_local_marketplace,
)


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
            self.assertEqual(plugin["source"]["path"], ".")
            staged = result
            self.assertTrue((staged / ".codex-plugin" / "plugin.json").is_file())
            self.assertEqual(marketplace_plugin_root(result), staged)
            self.assertFalse((staged / ".git").exists())
            self.assertFalse((staged / "work").exists())
            self.assertFalse((staged / "outputs").exists())

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
