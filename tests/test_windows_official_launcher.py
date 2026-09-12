from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import windows_official_launcher as official


class OfficialCodexLauncherTests(unittest.TestCase):
    def test_child_uses_inbox_modules_not_inherited_powershell_core(self) -> None:
        with mock.patch.dict(os.environ, {"PSModulePath": "untrusted-core-modules"}):
            environment = official.official_powershell_environment()
            self.assertEqual(os.environ["PSModulePath"], "untrusted-core-modules")
        self.assertEqual(environment["PSModulePath"],
                         str(Path(official.official_powershell_path()).parent / "Modules"))

    def test_plain_launch_only_passes_validated_locale(self) -> None:
        response = {"skinApplied": False, "launched": True, "pid": 456,
                    "packageFamilyName": "OpenAI.Codex_2p2nqsd0c76g0",
                    "signatureStatus": "Valid", "appVersion": "26.901.2854.0"}
        with mock.patch.object(official, "os", SimpleNamespace(name="nt", environ={})), mock.patch(
            "windows_official_launcher.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=json.dumps(response)),
        ) as run:
            self.assertEqual(official.launch_current_official_codex("zh_CN"), response)
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["CHROMAPAW_OFFICIAL_LOCALE"], "zh-CN")
        self.assertEqual(environment["CHROMAPAW_OFFICIAL_LAUNCH"], "1")
        script = official._OFFICIAL_CODEX_SCRIPT
        for forbidden in ("remote-debugging", "user-data-dir", "Stop-Process", "taskkill"):
            self.assertNotIn(forbidden, script)
        self.assertIn("Get-AuthenticodeSignature", script)
        self.assertIn("Get-AppxPackageManifest", script)
        self.assertIn("SignatureKind", script)

    def test_probe_does_not_activate(self) -> None:
        response = {"skinApplied": False, "launched": False,
                    "packageFamilyName": "OpenAI.Codex_2p2nqsd0c76g0",
                    "signatureStatus": "Valid"}
        with mock.patch.object(official, "os", SimpleNamespace(name="nt", environ={})), mock.patch(
            "windows_official_launcher.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=json.dumps(response)),
        ) as run:
            official.probe_current_official_codex()
        self.assertEqual(run.call_args.kwargs["env"]["CHROMAPAW_OFFICIAL_LAUNCH"], "0")

    def test_invalid_locale_cannot_add_switches(self) -> None:
        with mock.patch.object(official, "os", SimpleNamespace(name="nt", environ={})), mock.patch(
            "windows_official_launcher.subprocess.run"
        ) as run:
            with self.assertRaises(official.OfficialCodexLaunchError):
                official.launch_current_official_codex("zh-CN --remote-debugging-port=1")
            run.assert_not_called()

    def test_unverified_or_non_store_response_fails_closed(self) -> None:
        for response in ({"skinApplied": True}, {"skinApplied": False, "signatureStatus": "UnknownError"}):
            with self.subTest(response=response), mock.patch.object(
                official, "os", SimpleNamespace(name="nt", environ={})
            ), mock.patch("windows_official_launcher.subprocess.run", return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(response)
            )):
                with self.assertRaises(official.OfficialCodexLaunchError):
                    official.probe_current_official_codex()

    def test_probe_error_is_not_a_success(self) -> None:
        with mock.patch.object(official, "os", SimpleNamespace(name="nt", environ={})), mock.patch(
            "windows_official_launcher.subprocess.run",
            return_value=SimpleNamespace(returncode=1, stderr="signature did not pass"),
        ):
            with self.assertRaisesRegex(official.OfficialCodexLaunchError, "signature did not pass"):
                official.launch_current_official_codex()

    def test_locale_read_does_not_mutate_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"CODEX_HOME": temporary}):
            path = Path(temporary) / "config.toml"
            for raw, expected in (("zh_CN", "zh-CN"), ("bad --switch", None)):
                content = f'[desktop]\nlocaleOverride = "{raw}"\n'
                path.write_text(content, encoding="utf-8")
                self.assertEqual(official.official_config_locale(), expected)
                self.assertEqual(path.read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
