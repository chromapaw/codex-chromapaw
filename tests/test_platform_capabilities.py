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
        ):
            report = platform_capabilities.report_capabilities(Path(directory))
            self.assertTrue(report["ok"])
            self.assertTrue(
                report["oneImageWorkflow"]["skinGeneration"]["implemented"]
            )
            self.assertTrue(report["oneImageWorkflow"]["skinGeneration"]["ready"])
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


if __name__ == "__main__":
    unittest.main()
