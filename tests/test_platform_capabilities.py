from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import platform_capabilities  # noqa: E402


class PlatformCapabilitiesTests(unittest.TestCase):
    def test_generation_and_activation_are_reported_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            platform_capabilities.sys,
            "platform",
            "linux",
        ), mock.patch.object(
            platform_capabilities.importlib.util,
            "find_spec",
            return_value=object(),
        ):
            report = platform_capabilities.report_capabilities(Path(directory))
            self.assertTrue(report["ok"])
            self.assertTrue(report["reportGenerated"])
            self.assertTrue(report["workflowReadiness"]["skin"])
            self.assertFalse(report["workflowReadiness"]["pet"])
            self.assertFalse(report["workflowReadiness"]["allOneImageWorkflows"])
            self.assertIn("skin-package", report["readinessSemantics"])
            self.assertTrue(
                report["oneImageWorkflow"]["skinGeneration"]["implemented"]
            )
            self.assertTrue(report["oneImageWorkflow"]["skinGeneration"]["ready"])
            self.assertTrue(
                report["oneImageWorkflow"]["skinGeneration"][
                    "deterministicPackagingReady"
                ]
            )
            self.assertIn(
                "safe zone",
                report["oneImageWorkflow"]["skinGeneration"]["sceneGeneration"][
                    "requiredWhen"
                ],
            )
            self.assertTrue(
                report["oneImageWorkflow"]["skinGeneration"][
                    "semanticProfileRequired"
                ]
            )
            self.assertFalse(report["oneImageWorkflow"]["petGeneration"]["ready"])
            self.assertFalse(
                report["skinActivation"]["macos"]["activationImplemented"]
            )
            self.assertEqual(report["skinActivation"]["windows"]["candidates"], [])
            self.assertIn("selection", report["petInstallation"])
            self.assertIn("visibilityVerification", report["petInstallation"])

    def test_missing_pillow_makes_skin_workflow_and_top_level_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            platform_capabilities.sys,
            "platform",
            "linux",
        ), mock.patch.object(
            platform_capabilities.importlib.util,
            "find_spec",
            return_value=None,
        ):
            report = platform_capabilities.report_capabilities(Path(directory))

        self.assertFalse(report["ok"])
        self.assertFalse(report["workflowReadiness"]["skin"])
        self.assertFalse(report["workflowReadiness"]["allOneImageWorkflows"])
        skin = report["oneImageWorkflow"]["skinGeneration"]
        self.assertTrue(skin["implemented"])
        self.assertFalse(skin["pillowAvailable"])
        self.assertFalse(skin["ready"])
        self.assertFalse(skin["deterministicPackagingReady"])


if __name__ == "__main__":
    unittest.main()
