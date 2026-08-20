from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PluginStructureTests(unittest.TestCase):
    def test_manifest_and_skills_exist(self) -> None:
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], ROOT.name)
        self.assertEqual(manifest["version"].split("+", 1)[0], "0.4.7")
        self.assertRegex(manifest["version"], r"^0\.4\.7(?:\+codex\.[0-9a-z-]+)?$")
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
        self.assertEqual(plugin["source"], {"source": "local", "path": "."})
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
            "scripts/pet_selection.py",
            "scripts/restore_pet.py",
            "scripts/check_dependencies.py",
            "scripts/audit_pets.py",
            "scripts/smoke_test_install.py",
            "skills/create-chromapaw-pet/references/pet-mvp.md",
        )
        for relative in expected:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_skin_studio_assets_exist(self) -> None:
        expected = (
            "schemas/skin.schema.json",
            "schemas/theme-profile.schema.json",
            "scripts/skin_package.py",
            "scripts/theme_profile.py",
            "scripts/prepare_theme_profile.py",
            "scripts/prepare_skin_request.py",
            "scripts/build_skin_package.py",
            "scripts/validate_skin_package.py",
            "scripts/post_generation_guidance.py",
            "skills/create-chromapaw-skin/references/skin-package.md",
            "skills/create-chromapaw-skin/references/theme-profile.md",
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
            "scripts/windows_skin_launcher.py",
            "scripts/windows_shortcut.py",
            "tests/test_windows_runtime.py",
            "tests/test_windows_skin_launcher.py",
            "docs/WINDOWS_RUNTIME_BETA.md",
        )
        for relative in expected:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_cross_platform_probe_assets_exist(self) -> None:
        expected = (
            "runtime/macos-adapters.json",
            "schemas/macos-runtime-adapters.schema.json",
            "scripts/macos_compat.py",
            "scripts/platform_capabilities.py",
            "tests/test_macos_compat.py",
            "tests/test_platform_capabilities.py",
            "docs/MACOS_COMPATIBILITY.md",
        )
        for relative in expected:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_macos_enhanced_harness_assets_exist(self) -> None:
        for relative in (
            ".github/workflows/macos-enhanced.yml",
            "package.json",
            "package-lock.json",
            "scripts/macos_enhanced_test.py",
            "scripts/macos_visual_smoke.mjs",
            "tests/fixtures/macos-harness/host.css",
            "tests/fixtures/macos-harness/layout.css",
            "tests/fixtures/macos-harness/index.html",
            "tests/fixtures/macos-harness/pet-overlay.html",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)
        workflow = (ROOT / ".github" / "workflows" / "macos-enhanced.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("macos-15-intel", workflow)
        self.assertIn("os: macos-15", workflow)
        self.assertIn("scripts/macos_enhanced_test.py", workflow)
        self.assertIn("actions/upload-artifact", workflow)

    def test_release_automation_assets_exist(self) -> None:
        expected = (
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
            ".github/dependabot.yml",
            "scripts/release_check.py",
            "requirements-dev.txt",
            "docs/RELEASE_CHECKLIST.md",
            "tests/test_audit_pets.py",
            "tests/test_skin_input_matrix.py",
            "tests/test_smoke_test_install.py",
        )
        for relative in expected:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_repository_community_assets_exist(self) -> None:
        expected = (
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "SUPPORT.md",
            "docs/GITHUB_MAINTAINER_SETUP.md",
            ".github/CODEOWNERS",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/ISSUE_TEMPLATE/config.yml",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/compatibility_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
        )
        for relative in expected:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_workflows_pin_remote_actions_to_commits(self) -> None:
        import re

        action_pattern = re.compile(r"^[^\s@]+/[^\s@]+@[0-9a-f]{40}$")
        for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            text = workflow.read_text(encoding="utf-8")
            for action in re.findall(r"^\s*uses:\s*([^\s#]+)", text, flags=re.MULTILINE):
                if action.startswith("./") or action.startswith("docker://"):
                    continue
                self.assertRegex(action, action_pattern, f"{workflow.name}: {action}")


if __name__ == "__main__":
    unittest.main()
