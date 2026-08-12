from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from post_generation_guidance import pet_guidance, skin_guidance  # noqa: E402


class PostGenerationGuidanceTests(unittest.TestCase):
    def test_windows_skin_waits_for_preflight_and_second_confirmation(self) -> None:
        result = skin_guidance(
            Path("C:/skin").resolve(),
            {
                "id": "clear-hero",
                "displayName": "Clear Hero",
                "layout": {
                    "visualTreatment": {
                        "sceneFidelity": "preserve",
                        "globalWashOpacity": 0.08,
                    }
                },
            },
            "windows",
            windows_candidates=[
                {
                    "executable": "C:/Codex/app-1.2.3.4/ChatGPT.exe",
                    "appVersion": "1.2.3.4",
                    "adapterId": "fixture-enabled",
                    "activationEnabled": True,
                }
            ],
        )
        self.assertEqual(result["status"], "generated-not-active")
        self.assertEqual(result["nextStep"]["userMessage"], "应用这个皮肤")
        self.assertFalse(result["nextStep"]["appliesImmediately"])
        self.assertTrue(result["nextStep"]["laterExperimentalConfirmationRequired"])
        self.assertEqual(result["runtimeReadiness"]["enabledCandidateCount"], 1)

    def test_windows_skin_does_not_offer_activation_for_disabled_adapter(self) -> None:
        result = skin_guidance(
            Path("C:/skin").resolve(),
            {"id": "clear-hero", "displayName": "Clear Hero", "layout": {}},
            "windows",
            windows_candidates=[
                {
                    "executable": "C:/WindowsApps/Codex/ChatGPT.exe",
                    "appVersion": "26.803.10989.0",
                    "adapterId": None,
                    "activationEnabled": False,
                    "reason": "unsupported exact version",
                }
            ],
        )
        self.assertFalse(result["liveActivationCandidate"])
        self.assertIsNone(result["nextStep"]["userMessage"])
        self.assertEqual(
            result["runtimeReadiness"]["status"],
            "no-enabled-exact-version-adapter",
        )

    def test_macos_skin_does_not_offer_unsupported_activation(self) -> None:
        result = skin_guidance(
            Path("/tmp/skin").resolve(),
            {"id": "clear-hero", "displayName": "Clear Hero", "layout": {}},
            "macos",
        )
        self.assertFalse(result["liveActivationCandidate"])
        self.assertIsNone(result["nextStep"]["userMessage"])

    def test_pet_requires_separate_install_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = pet_guidance(
                root / "package",
                {"id": "basket-buddy", "displayName": "Basket Buddy"},
                root / "codex-home",
            )
            self.assertEqual(result["status"], "generated-not-installed")
            self.assertEqual(result["nextStep"]["userMessage"], "安装这个宠物")
            self.assertFalse(result["replacementRequired"])
            self.assertTrue(result["nextStep"]["selectsInstalledPet"])
            self.assertTrue(result["nextStep"]["restartMayBeRequired"])
            self.assertEqual(
                result["nextStep"]["actionAfterMessage"], "install-and-select"
            )

    def test_pet_replacement_names_id_and_requires_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "codex-home" / "pets" / "basket-buddy"
            destination.mkdir(parents=True)
            result = pet_guidance(
                root / "package",
                {"id": "basket-buddy", "displayName": "Basket Buddy"},
                root / "codex-home",
            )
            self.assertTrue(result["replacementRequired"])
            self.assertEqual(
                result["nextStep"]["userMessage"],
                "同意替换安装宠物 basket-buddy",
            )
            self.assertTrue(result["nextStep"]["backupRequired"])
            self.assertEqual(
                result["nextStep"]["actionAfterMessage"],
                "backup-replace-and-select",
            )


if __name__ == "__main__":
    unittest.main()
