from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import windows_pending_activation as pending


class PendingActivationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / "data"
        self.data.mkdir()
        self.package = self.root / "skin"
        self.exe = self.root / "ChatGPT.exe"
        self.adapters = self.root / "adapters.json"
        self.identity = {
            "package": str(self.package.resolve()), "packageId": "fixture",
            "executable": str(self.exe.resolve()), "appVersion": "26.901.2854.0",
            "adapterFile": str(self.adapters.resolve()), "adapterId": "fixture-adapter",
            **{key: "a" * 64 for key in ("manifestHash", "cssHash", "executableHash", "adapterFileHash")},
        }
        self.patches = [
            mock.patch.object(pending.runtime, "build_preflight", return_value=self.identity),
            mock.patch.object(pending.runtime, "_read_active", return_value=None),
            mock.patch.dict("os.environ", {"CHROMAPAW_HOSTED_GENERATION": "sha256-" + "b" * 64,
                                           "CHROMAPAW_HOSTED_BUNDLE_HASH": "b" * 64}),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def stage(self):
        return pending.prepare_activation(self.package, self.exe, self.data, self.adapters, acknowledged=True)

    def test_explicit_acknowledgement_is_required(self):
        with self.assertRaisesRegex(pending.runtime.RuntimeFailure, "acknowledgement"):
            pending.prepare_activation(self.package, self.exe, self.data, self.adapters, acknowledged=False)
        self.assertFalse((self.data / pending.PENDING_FILE).exists())

    def test_prepare_persists_intent_without_replacing_preference_or_launching(self):
        old = self.data / pending.runtime.PREFERENCE_FILE
        old.write_text('{"executable":"old-removed.exe"}', encoding="utf-8")
        before = old.read_bytes()
        with mock.patch.object(pending.runtime, "activate_runtime") as launch:
            result = self.stage()
        launch.assert_not_called()
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(result["status"], "pending-next-launch")
        self.assertEqual(pending.read_pending(self.data)["packageId"], "fixture")
        self.assertNotIn("port", pending.read_pending(self.data))

    def test_changed_css_or_previous_preference_refuses_launch(self):
        self.stage()
        with mock.patch.object(pending.runtime, "activate_runtime") as launch:
            with mock.patch.object(pending.runtime, "build_preflight", return_value={**self.identity, "cssHash": "c" * 64}):
                with self.assertRaisesRegex(pending.runtime.RuntimeFailure, "cssHash"):
                    pending.apply_pending(self.data, self.adapters, acknowledged=True, wait_seconds=1)
            (self.data / pending.runtime.PREFERENCE_FILE).write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(pending.runtime.RuntimeFailure, "preference"):
                pending.apply_pending(self.data, self.adapters, acknowledged=True, wait_seconds=1)
        launch.assert_not_called()

    def test_failed_activation_keeps_intent_for_next_launch(self):
        self.stage()
        with mock.patch.object(pending.runtime, "activate_runtime", side_effect=pending.runtime.RuntimeFailure("launch failed")):
            with self.assertRaisesRegex(pending.runtime.RuntimeFailure, "launch failed"):
                pending.apply_pending(self.data, self.adapters, acknowledged=True, wait_seconds=1)
        self.assertIsNotNone(pending.read_pending(self.data))

    def test_success_requires_verification_then_consumes_intent(self):
        self.stage()
        with mock.patch.object(pending.runtime, "activate_runtime", return_value={"status": "active"}) as launch, mock.patch.object(
            pending.runtime, "verify_runtime", return_value={"ok": True, "cssMatches": True}
        ) as verify:
            result = pending.apply_pending(self.data, self.adapters, acknowledged=True, wait_seconds=45)
        self.assertTrue(result["ok"])
        launch.assert_called_once_with(self.package, self.exe, self.data, self.adapters,
                                       acknowledged=True, profile_dir=None, allow_parallel_profile=False, wait_seconds=45)
        verify.assert_called_once_with(self.data)
        self.assertIsNone(pending.read_pending(self.data))
        self.assertEqual(json.loads((self.data / pending.RESULT_FILE).read_text())["status"], "active-verified")

    def test_verification_failure_does_not_lose_request(self):
        self.stage()
        with mock.patch.object(pending.runtime, "activate_runtime", return_value={"status": "active"}), mock.patch.object(
            pending.runtime, "verify_runtime", return_value={"ok": False}
        ):
            with self.assertRaisesRegex(pending.runtime.RuntimeFailure, "verification"):
                pending.apply_pending(self.data, self.adapters, acknowledged=True, wait_seconds=1)
        self.assertIsNotNone(pending.read_pending(self.data))

    def test_same_active_session_can_finish_pending_verification_without_relaunch(self):
        self.stage()
        with mock.patch.object(pending.runtime, "_read_active", return_value=self.identity), mock.patch.object(
            pending.runtime, "activate_runtime"
        ) as launch, mock.patch.object(pending.runtime, "verify_runtime", return_value={"ok": True}), mock.patch.object(
            pending.runtime, "resume_runtime", return_value={"ok": True, "status": "already-active"}
        ) as resume:
            pending.apply_pending(self.data, self.adapters, acknowledged=True, wait_seconds=1)
        launch.assert_not_called()
        resume.assert_called_once()
        self.assertIsNone(pending.read_pending(self.data))

    def test_different_active_session_and_runtime_generation_are_not_adopted(self):
        self.stage()
        with mock.patch.object(pending.runtime, "_read_active", return_value={**self.identity, "packageId": "other"}):
            with self.assertRaisesRegex(pending.runtime.RuntimeFailure, "active session"):
                pending.validate_pending(self.data, self.adapters)
        with mock.patch.dict("os.environ", {"CHROMAPAW_HOSTED_GENERATION": "sha256-" + "c" * 64}):
            with self.assertRaisesRegex(pending.runtime.RuntimeFailure, "generation"):
                pending.validate_pending(self.data, self.adapters)


if __name__ == "__main__":
    unittest.main()
