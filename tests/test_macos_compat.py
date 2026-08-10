from __future__ import annotations

import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from macos_compat import (  # noqa: E402
    MacCompatibilityFailure,
    build_preflight,
    inspect_app_bundle,
    load_adapters,
)

try:
    from tests.test_validate_skin_package import make_v2_package  # type: ignore  # noqa: E402
except ImportError:
    from test_validate_skin_package import make_v2_package  # type: ignore  # noqa: E402


def make_app_bundle(root: Path, *, version: str = "26.900.1") -> Path:
    app = root / "Codex.app"
    contents = app / "Contents"
    executable = contents / "MacOS" / "Codex"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"macos-codex-fixture")
    resources = contents / "Resources"
    resources.mkdir()
    (resources / "app.asar").write_bytes(b"fixture")
    (contents / "Frameworks" / "Electron Framework.framework").mkdir(parents=True)
    info = {
        "CFBundleIdentifier": "com.openai.codex",
        "CFBundleExecutable": "Codex",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": "9001",
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    return app


def write_registry(path: Path, adapters: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "platform": "darwin",
                "mode": "compatibility-probe",
                "activationImplemented": False,
                "adapters": adapters,
            }
        ),
        encoding="utf-8",
    )


class MacCompatibilityTests(unittest.TestCase):
    def test_inspects_fixture_bundle_without_modification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = make_app_bundle(Path(directory))
            before = (app / "Contents" / "MacOS" / "Codex").read_bytes()
            bundle = inspect_app_bundle(app)
            self.assertEqual(bundle["bundleIdentifier"], "com.openai.codex")
            self.assertEqual(bundle["appVersion"], "26.900.1")
            self.assertEqual(bundle["executableName"], "Codex")
            self.assertTrue(bundle["electronSignals"]["appAsar"])
            self.assertTrue(bundle["electronSignals"]["electronFramework"])
            self.assertEqual(
                (app / "Contents" / "MacOS" / "Codex").read_bytes(),
                before,
            )

    def test_preflight_is_probe_only_without_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = make_app_bundle(root)
            package_root = root / "skin"
            package_root.mkdir()
            package = make_v2_package(package_root)
            result = build_preflight(package, app, require_darwin=False)
            self.assertTrue(result["ok"])
            self.assertTrue(result["generationSupported"])
            self.assertFalse(result["activationImplemented"])
            self.assertFalse(result["activationEnabled"])
            self.assertIsNone(result["adapterId"])
            self.assertTrue(result["semanticProfilePresent"])
            self.assertFalse(result["applicationFilesWillBeModified"])

    def test_exact_probe_adapter_never_enables_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = make_app_bundle(root)
            package_root = root / "skin"
            package_root.mkdir()
            package = make_v2_package(package_root)
            registry = root / "macos-adapters.json"
            write_registry(
                registry,
                [
                    {
                        "id": "fixture-probe",
                        "appVersion": "26.900.1",
                        "bundleIdentifier": "com.openai.codex",
                        "executableName": "Codex",
                        "activationEnabled": False,
                        "testedTarget": "metadata-only fixture",
                    }
                ],
            )
            result = build_preflight(
                package,
                app,
                registry,
                require_darwin=False,
            )
            self.assertEqual(result["adapterId"], "fixture-probe")
            self.assertFalse(result["activationEnabled"])
            self.assertIn("not implemented", result["reason"])

    def test_registry_rejects_activation_in_probe_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "macos-adapters.json"
            write_registry(
                registry,
                [
                    {
                        "id": "unsafe",
                        "appVersion": "1.0",
                        "bundleIdentifier": "com.openai.codex",
                        "executableName": "Codex",
                        "activationEnabled": True,
                        "testedTarget": "none",
                    }
                ],
            )
            with self.assertRaises(MacCompatibilityFailure):
                load_adapters(registry)

    def test_missing_executable_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = make_app_bundle(Path(directory))
            (app / "Contents" / "MacOS" / "Codex").unlink()
            with self.assertRaises(MacCompatibilityFailure) as context:
                inspect_app_bundle(app)
            self.assertIn("does not exist", str(context.exception))


if __name__ == "__main__":
    unittest.main()
