from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import windows_skin_launcher  # noqa: E402


class WindowsSkinLauncherTests(unittest.TestCase):
    def test_restart_confirmation_is_topmost_and_defaults_to_no(self) -> None:
        flags = windows_skin_launcher.CONFIRMATION_FLAGS
        self.assertTrue(flags & 0x00000004)  # MB_YESNO
        self.assertTrue(flags & 0x00000100)  # MB_DEFBUTTON2
        self.assertTrue(flags & 0x00010000)  # MB_SETFOREGROUND
        self.assertTrue(flags & 0x00040000)  # MB_TOPMOST

    def test_inactive_runtime_prompts_before_closing_matching_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            executable = Path("C:/fixture/app-26.707.9981.0/ChatGPT.exe")
            with mock.patch.object(sys, "argv", ["windows_skin_launcher.py"]), mock.patch(
                "windows_skin_launcher.runtime_data_dir", return_value=data_dir
            ), mock.patch(
                "windows_skin_launcher.runtime_status",
                return_value={"ok": True, "status": "inactive"},
            ), mock.patch(
                "windows_skin_launcher._read_preference",
                return_value={"executable": str(executable)},
            ), mock.patch(
                "windows_skin_launcher.running_pids", return_value=[101, 102]
            ), mock.patch(
                "windows_skin_launcher._confirm_close_running", return_value=True
            ) as confirm, mock.patch(
                "windows_skin_launcher.close_matching_codex_processes",
                return_value={"closed": True, "pids": [101, 102]},
            ) as close, mock.patch(
                "windows_skin_launcher.resume_runtime",
                return_value={"ok": True, "status": "active"},
            ) as resume:
                result = windows_skin_launcher.main()
            self.assertEqual(result, 0)
            confirm.assert_called_once()
            close.assert_called_once_with(executable.resolve(), acknowledged=True)
            resume.assert_called_once()

    def test_cancelled_restart_does_not_close_or_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with mock.patch.object(sys, "argv", ["windows_skin_launcher.py"]), mock.patch(
                "windows_skin_launcher.runtime_data_dir", return_value=data_dir
            ), mock.patch(
                "windows_skin_launcher.runtime_status",
                return_value={"ok": True, "status": "inactive"},
            ), mock.patch(
                "windows_skin_launcher._read_preference",
                return_value={"executable": "C:/fixture/ChatGPT.exe"},
            ), mock.patch(
                "windows_skin_launcher.running_pids", return_value=[101]
            ), mock.patch(
                "windows_skin_launcher._confirm_close_running", return_value=False
            ), mock.patch(
                "windows_skin_launcher.close_matching_codex_processes"
            ) as close, mock.patch("windows_skin_launcher.resume_runtime") as resume:
                result = windows_skin_launcher.main()
            self.assertEqual(result, 2)
            close.assert_not_called()
            resume.assert_not_called()

    def test_active_runtime_never_prompts_or_closes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with mock.patch.object(sys, "argv", ["windows_skin_launcher.py"]), mock.patch(
                "windows_skin_launcher.runtime_data_dir", return_value=data_dir
            ), mock.patch(
                "windows_skin_launcher.runtime_status",
                return_value={"ok": True, "status": "active"},
            ), mock.patch(
                "windows_skin_launcher._confirm_close_running"
            ) as confirm, mock.patch(
                "windows_skin_launcher.close_matching_codex_processes"
            ) as close, mock.patch(
                "windows_skin_launcher.resume_runtime",
                return_value={"ok": True, "status": "already-active"},
            ):
                result = windows_skin_launcher.main()
            self.assertEqual(result, 0)
            confirm.assert_not_called()
            close.assert_not_called()

    def test_runtime_failure_opens_verified_plain_codex_without_error_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with mock.patch.object(sys, "argv", ["windows_skin_launcher.py"]), mock.patch(
                "windows_skin_launcher.runtime_data_dir", return_value=data_dir
            ), mock.patch(
                "windows_skin_launcher.runtime_status",
                return_value={"ok": True, "status": "inactive"},
            ), mock.patch(
                "windows_skin_launcher._read_preference",
                return_value={"executable": "C:/fixture/ChatGPT.exe"},
            ), mock.patch(
                "windows_skin_launcher.running_pids", return_value=[]
            ), mock.patch(
                "windows_skin_launcher.resume_runtime",
                side_effect=windows_skin_launcher.RuntimeFailure("cssHash changed"),
            ), mock.patch(
                "windows_skin_launcher._launch_verified_plain_codex",
                return_value={"launched": True, "pid": 123},
            ) as fallback, mock.patch(
                "windows_skin_launcher._show_error"
            ) as show_error:
                result = windows_skin_launcher.main()

            self.assertEqual(result, 0)
            fallback.assert_called_once_with(data_dir)
            show_error.assert_not_called()
            event = (data_dir / "launcher.jsonl").read_text(encoding="utf-8")
            self.assertIn("launcher-fallback-plain-codex", event)
            self.assertIn("cssHash changed", event)


if __name__ == "__main__":
    unittest.main()
