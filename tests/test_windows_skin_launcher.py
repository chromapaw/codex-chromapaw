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
    def test_pending_request_uses_new_target_without_reading_obsolete_preference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with mock.patch.object(sys, "argv", ["launcher", "--acknowledge-experimental-runtime"]), mock.patch(
                "windows_skin_launcher.runtime_data_dir", return_value=data_dir
            ), mock.patch("windows_skin_launcher.runtime_status", return_value={"status": "inactive"}), mock.patch(
                "windows_skin_launcher.validate_pending", return_value={"executable": str(data_dir / "new.exe")}
            ), mock.patch("windows_skin_launcher._read_preference") as old, mock.patch(
                "windows_skin_launcher.running_pids", return_value=[]
            ), mock.patch("windows_skin_launcher.apply_pending", return_value={"ok": True}) as apply, mock.patch(
                "windows_skin_launcher.resume_runtime"
            ) as resume:
                self.assertEqual(windows_skin_launcher.main(), 0)
            old.assert_not_called()
            resume.assert_not_called()
            apply.assert_called_once()
            self.assertIn("launcher-pending-activation-success", (data_dir / "launcher.jsonl").read_text())

    def test_pending_cancel_does_not_consume_or_close(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with mock.patch.object(sys, "argv", ["launcher", "--acknowledge-experimental-runtime"]), mock.patch(
                "windows_skin_launcher.runtime_data_dir", return_value=data_dir
            ), mock.patch("windows_skin_launcher.runtime_status", return_value={"status": "inactive"}), mock.patch(
                "windows_skin_launcher.validate_pending", return_value={"executable": str(data_dir / "new.exe")}
            ), mock.patch("windows_skin_launcher.running_pids", return_value=[100]), mock.patch(
                "windows_skin_launcher._confirm_close_running", return_value=False
            ), mock.patch("windows_skin_launcher.close_matching_codex_processes") as close, mock.patch(
                "windows_skin_launcher.apply_pending"
            ) as apply:
                self.assertEqual(windows_skin_launcher.main(), 2)
            apply.assert_not_called()
            close.assert_not_called()

    def test_deleted_saved_executable_opens_current_official_app_without_adopting_skin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            preference = {"executable": str(data_dir / "deleted.exe"), "executableHash": "a" * 64}
            official = {"launched": True, "pid": 456, "skinApplied": False, "appVersion": "new"}
            with mock.patch("windows_skin_launcher._read_preference", return_value=preference), mock.patch(
                "windows_skin_launcher.launch_current_official_codex", return_value=official
            ) as launch, mock.patch("windows_skin_launcher.official_config_locale", return_value="zh-CN"), mock.patch(
                "windows_skin_launcher.select_adapter"
            ) as select:
                self.assertEqual(windows_skin_launcher._launch_verified_plain_codex(data_dir), official)
            launch.assert_called_once_with("zh-CN")
            select.assert_not_called()
            self.assertEqual(list(data_dir.iterdir()), [])

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

    def test_plain_fallback_preserves_configured_locale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            executable = data_dir / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture")
            process = mock.Mock(pid=123)
            with mock.patch(
                "windows_skin_launcher._read_preference",
                return_value={"executable": str(executable), "executableHash": "a" * 64},
            ), mock.patch(
                "windows_skin_launcher.sha256_file", return_value="a" * 64
            ), mock.patch(
                "windows_skin_launcher.codex_locale_status",
                return_value={"requested": "zh-CN", "valid": True},
            ), mock.patch(
                "windows_skin_launcher.subprocess.Popen", return_value=process
            ) as popen:
                result = windows_skin_launcher._launch_verified_plain_codex(data_dir)
            self.assertEqual(result["locale"], "zh-CN")
            self.assertEqual(
                popen.call_args.args[0], [str(executable.resolve()), "--lang=zh-CN"]
            )

    def test_plain_fallback_uses_verified_appx_activation_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            executable = data_dir / "OpenAI.Codex_26.901.1978.0_x64" / "app" / "ChatGPT.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"fixture")
            adapter_file = data_dir / "adapters.json"
            adapter_file.write_bytes(b"registry")
            process = mock.Mock(pid=456)
            strategy = {
                "kind": "appx-activation-manager",
                "appUserModelId": "OpenAI.Codex_2p2nqsd0c76g0!App",
            }
            preference = {
                "executable": str(executable),
                "executableHash": "a" * 64,
                "adapterFile": str(adapter_file),
                "adapterFileHash": "b" * 64,
                "adapterId": "fixture-appx",
            }
            with mock.patch(
                "windows_skin_launcher._read_preference", return_value=preference
            ), mock.patch(
                "windows_skin_launcher.sha256_file",
                side_effect=lambda path: "b" * 64 if Path(path).resolve() == adapter_file.resolve() else "a" * 64,
            ), mock.patch(
                "windows_skin_launcher.codex_locale_status",
                return_value={"requested": "zh-CN", "valid": True},
            ), mock.patch(
                "windows_skin_launcher.select_adapter",
                return_value={"id": "fixture-appx", "launchStrategy": strategy},
            ), mock.patch(
                "windows_skin_launcher._launch_packaged_codex", return_value=process
            ) as packaged, mock.patch("windows_skin_launcher.subprocess.Popen") as popen:
                result = windows_skin_launcher._launch_verified_plain_codex(data_dir)
            popen.assert_not_called()
            packaged.assert_called_once_with(executable.resolve(), ["--lang=zh-CN"], strategy)
            self.assertEqual(result["pid"], 456)


if __name__ == "__main__":
    unittest.main()
