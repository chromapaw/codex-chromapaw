from __future__ import annotations

import os
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from windows_shortcut import (  # noqa: E402
    RuntimeFailure,
    _write_shortcut,
    inspect_shortcut,
    install_shortcut,
    restore_shortcut,
    shortcut_semantic_hash,
    shortcut_status,
)


@unittest.skipUnless(os.name == "nt", "Windows shortcut integration test")
class WindowsShortcutTests(unittest.TestCase):
    def test_cli_hides_legacy_acknowledgements(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "windows_shortcut.py"), "install", "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--acknowledge-adds-windows-shortcuts", completed.stdout)
        self.assertNotIn("--acknowledge-adds-start-menu-shortcut", completed.stdout)
        self.assertNotIn("--acknowledge-replaces-start-menu-shortcut", completed.stdout)

    def test_install_and_restore_preserve_original_shortcut(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            original_semantic = shortcut_semantic_hash(inspect_shortcut(original_shortcut))
            shortcut = root / "Codex ChromaPaw.lnk"
            desktop_shortcut = root / "Desktop" / "Codex ChromaPaw.lnk"

            with self.assertRaises(RuntimeFailure):
                install_shortcut(
                    data_dir,
                    shortcut,
                    executable,
                    ROOT / "runtime" / "windows-adapters.json",
                    acknowledged=False,
                    original_shortcut=original_shortcut,
                    desktop_shortcut=desktop_shortcut,
                )

            installed = install_shortcut(
                data_dir,
                shortcut,
                executable,
                ROOT / "runtime" / "windows-adapters.json",
                acknowledged=True,
                original_shortcut=original_shortcut,
                desktop_shortcut=desktop_shortcut,
            )
            self.assertEqual(installed["status"], "installed")
            self.assertEqual(installed["schemaVersion"], 4)
            hosted = installed["hostedRuntime"]
            self.assertTrue(Path(hosted["bootstrap"]).is_file())
            self.assertTrue(Path(hosted["generationDir"]).is_dir())
            self.assertTrue(shortcut_status(data_dir)["hostedRuntime"]["matches"])
            self.assertEqual(shortcut_status(data_dir)["status"], "installed")
            self.assertTrue(inspect_shortcut(shortcut)["target"].lower().endswith("pythonw.exe"))
            self.assertTrue(
                inspect_shortcut(desktop_shortcut)["target"].lower().endswith("pythonw.exe")
            )
            shortcut_arguments = inspect_shortcut(shortcut)["arguments"]
            self.assertIn(str(Path(hosted["bootstrap"])), shortcut_arguments)
            self.assertNotIn(str(ROOT / "scripts" / "windows_skin_launcher.py"), shortcut_arguments)
            self.assertNotIn(str(ROOT / "runtime" / "windows-adapters.json"), shortcut_arguments)
            self.assertEqual(
                shortcut_semantic_hash(inspect_shortcut(original_shortcut)), original_semantic
            )

            # The hosted bootstrap imports the complete runtime closure without
            # relying on the repository/plugin-cache path or PYTHONPATH.
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            help_result = subprocess.run(
                [sys.executable, hosted["bootstrap"], "--help"],
                cwd=root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("--acknowledge-experimental-runtime", help_result.stdout)

            # Rewriting the same semantic fields may change binary tracking data,
            # but it must not invalidate ownership.
            managed = inspect_shortcut(shortcut)
            icon = Path(managed["iconLocation"].rsplit(",", 1)[0])
            _write_shortcut(
                shortcut,
                target=Path(managed["target"]),
                arguments=managed["arguments"],
                working_directory=Path(managed["workingDirectory"]),
                icon=icon,
                description=managed["description"],
            )
            self.assertEqual(shortcut_status(data_dir)["status"], "installed")

            restored = restore_shortcut(data_dir)
            self.assertEqual(restored["status"], "removed")
            self.assertFalse(shortcut.exists())
            self.assertFalse(desktop_shortcut.exists())
            self.assertTrue(original_shortcut.exists())
            self.assertTrue(Path(hosted["root"]).is_dir())
            self.assertEqual(restored["hostedRuntimeRetained"], hosted["root"])
            self.assertEqual(shortcut_status(data_dir)["status"], "not-installed")

    def test_hosted_launcher_failure_falls_back_without_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            installed = install_shortcut(
                data_dir,
                root / "Codex ChromaPaw.lnk",
                executable,
                ROOT / "runtime" / "windows-adapters.json",
                acknowledged=True,
                original_shortcut=original_shortcut,
                desktop_shortcut=root / "Desktop" / "Codex ChromaPaw.lnk",
            )
            generation = Path(installed["hostedRuntime"]["generationDir"])
            launcher = generation / "scripts" / "windows_skin_launcher.py"
            launcher.write_text("raise SystemExit(9)\n", encoding="utf-8")
            manifest_path = generation / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            import hashlib

            launcher_hash = hashlib.sha256(launcher.read_bytes()).hexdigest()
            next(
                entry
                for entry in manifest["files"]
                if entry["path"] == "scripts/windows_skin_launcher.py"
            )["sha256"] = launcher_hash
            canonical = hashlib.sha256()
            for entry in sorted(manifest["files"], key=lambda item: item["path"]):
                canonical.update(entry["path"].encode("utf-8"))
                canonical.update(b"\0")
                canonical.update(entry["sha256"].encode("ascii"))
                canonical.update(b"\0")
            bundle_hash = canonical.hexdigest()
            next_generation = generation.parent / f"sha256-{bundle_hash}"
            manifest["bundleHash"] = bundle_hash
            manifest["generation"] = next_generation.name
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            generation.rename(next_generation)
            current_path = Path(installed["hostedRuntime"]["current"])
            current_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "generation": next_generation.name,
                        "bundleHash": bundle_hash,
                    }
                ),
                encoding="utf-8",
            )
            preference = {
                "schemaVersion": 1,
                "package": "C:/fixture/skin",
                "packageId": "fixture",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
                "executable": str(executable),
                "executableHash": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "appVersion": "26.707.9981.0",
                "adapterId": "fixture-adapter",
                "adapterFile": str(ROOT / "runtime" / "windows-adapters.json"),
                "adapterFileHash": "d" * 64,
            }
            (data_dir / "preferred-skin.json").write_text(
                json.dumps(preference), encoding="utf-8"
            )

            with mock.patch("subprocess.Popen") as popen:
                popen.return_value.pid = 123
                # Run the generated bootstrap in process so the mock observes
                # the verified plain-Codex fallback without launching a fixture.
                namespace: dict[str, object] = {
                    "__name__": "bootstrap_test",
                    "__file__": installed["hostedRuntime"]["bootstrap"],
                }
                exec(
                    compile(
                        Path(installed["hostedRuntime"]["bootstrap"]).read_text(
                            encoding="utf-8"
                        ),
                        "bootstrap.py",
                        "exec",
                    ),
                    namespace,
                )
                with mock.patch.object(
                    sys,
                    "argv",
                    [
                        installed["hostedRuntime"]["bootstrap"],
                        "--data-dir",
                        str(data_dir),
                    ],
                ):
                    result = namespace["main"]()

            self.assertEqual(result, 0)
            popen.assert_called_once()

    def test_receipt_write_failure_rolls_back_shortcuts_and_hosted_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            shortcut = root / "Codex ChromaPaw.lnk"
            desktop_shortcut = root / "Desktop" / "Codex ChromaPaw.lnk"
            import windows_shortcut

            real_atomic_json = windows_shortcut.atomic_json

            def fail_receipt(path, value):
                if path.name == "start-menu-shortcut.json":
                    raise OSError("fixture receipt failure")
                return real_atomic_json(path, value)

            with mock.patch("windows_shortcut.atomic_json", side_effect=fail_receipt):
                with self.assertRaises(OSError):
                    install_shortcut(
                        data_dir,
                        shortcut,
                        executable,
                        ROOT / "runtime" / "windows-adapters.json",
                        acknowledged=True,
                        original_shortcut=original_shortcut,
                        desktop_shortcut=desktop_shortcut,
                    )

            self.assertFalse(shortcut.exists())
            self.assertFalse(desktop_shortcut.exists())
            self.assertFalse((data_dir / "start-menu-shortcut.json").exists())
            self.assertFalse((data_dir / "shortcut-runtime" / "current.json").exists())

    def test_incompatible_preference_refuses_pin_and_rolls_back_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            data_dir.mkdir()
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            shortcut = root / "Codex ChromaPaw.lnk"
            desktop_shortcut = root / "Desktop" / "Codex ChromaPaw.lnk"
            preference_path = data_dir / "preferred-skin.json"
            preference = {
                "schemaVersion": 1,
                "package": "C:/fixture/skin",
                "packageId": "fixture",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
                "executable": str(executable),
                "executableHash": "c" * 64,
                "appVersion": "26.707.9981.0",
                "adapterId": "fixture-adapter",
                "adapterFileHash": "d" * 64,
            }
            preference_path.write_text(json.dumps(preference), encoding="utf-8")
            mismatch = {**preference, "cssHash": "e" * 64}

            with mock.patch(
                "windows_shortcut.build_preflight", return_value=mismatch
            ), self.assertRaisesRegex(RuntimeFailure, "cssHash"):
                install_shortcut(
                    data_dir,
                    shortcut,
                    executable,
                    ROOT / "runtime" / "windows-adapters.json",
                    acknowledged=True,
                    original_shortcut=original_shortcut,
                    desktop_shortcut=desktop_shortcut,
                )

            self.assertFalse(shortcut.exists())
            self.assertFalse(desktop_shortcut.exists())
            self.assertFalse((data_dir / "start-menu-shortcut.json").exists())
            self.assertFalse((data_dir / "shortcut-runtime" / "current.json").exists())
            self.assertEqual(
                json.loads(preference_path.read_text(encoding="utf-8")), preference
            )

    def test_hosted_bootstrap_rejects_tampered_generation_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            installed = install_shortcut(
                data_dir,
                root / "Codex ChromaPaw.lnk",
                executable,
                ROOT / "runtime" / "windows-adapters.json",
                acknowledged=True,
                original_shortcut=original_shortcut,
                desktop_shortcut=root / "Desktop" / "Codex ChromaPaw.lnk",
            )
            launcher = (
                Path(installed["hostedRuntime"]["generationDir"])
                / "scripts"
                / "windows_skin_launcher.py"
            )
            launcher.write_text("raise SystemExit(77)\n", encoding="utf-8")

            environment = os.environ.copy()
            environment["CHROMAPAW_SUPPRESS_ERROR_DIALOG"] = "1"
            completed = subprocess.run(
                [sys.executable, installed["hostedRuntime"]["bootstrap"], "--help"],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1)

    def test_hosted_bootstrap_rejects_coherent_file_and_manifest_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            installed = install_shortcut(
                data_dir,
                root / "Codex ChromaPaw.lnk",
                executable,
                ROOT / "runtime" / "windows-adapters.json",
                acknowledged=True,
                original_shortcut=original_shortcut,
                desktop_shortcut=root / "Desktop" / "Codex ChromaPaw.lnk",
            )
            generation = Path(installed["hostedRuntime"]["generationDir"])
            launcher = generation / "scripts" / "windows_skin_launcher.py"
            marker = root / "tampered-launcher-ran"
            launcher.write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
                encoding="utf-8",
            )
            manifest_path = generation / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            import hashlib

            launcher_hash = hashlib.sha256(launcher.read_bytes()).hexdigest()
            next(
                entry
                for entry in manifest["files"]
                if entry["path"] == "scripts/windows_skin_launcher.py"
            )["sha256"] = launcher_hash
            # This was accepted before the bootstrap independently recomputed
            # the canonical bundle hash instead of trusting this manifest.
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            environment = os.environ.copy()
            environment["CHROMAPAW_SUPPRESS_ERROR_DIALOG"] = "1"
            completed = subprocess.run(
                [sys.executable, installed["hostedRuntime"]["bootstrap"], "--help"],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertFalse(marker.exists(), "tampered hosted launcher was executed")

    def test_hosted_bootstrap_rejects_unlisted_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            installed = install_shortcut(
                data_dir,
                root / "Codex ChromaPaw.lnk",
                executable,
                ROOT / "runtime" / "windows-adapters.json",
                acknowledged=True,
                original_shortcut=original_shortcut,
                desktop_shortcut=root / "Desktop" / "Codex ChromaPaw.lnk",
            )
            generation = Path(installed["hostedRuntime"]["generationDir"])
            (generation / "scripts" / "unlisted.py").write_text(
                "raise SystemExit(77)\n", encoding="utf-8"
            )

            environment = os.environ.copy()
            environment["CHROMAPAW_SUPPRESS_ERROR_DIALOG"] = "1"
            completed = subprocess.run(
                [sys.executable, installed["hostedRuntime"]["bootstrap"], "--help"],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1)

    def test_schema_two_receipt_migrates_to_desktop_and_start_menu(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            shortcut = root / "Codex ChromaPaw.lnk"
            desktop_shortcut = root / "Desktop" / "Codex ChromaPaw.lnk"
            installed = install_shortcut(
                data_dir,
                shortcut,
                executable,
                ROOT / "runtime" / "windows-adapters.json",
                acknowledged=True,
                original_shortcut=original_shortcut,
                desktop_shortcut=desktop_shortcut,
            )
            desktop_shortcut.unlink()
            start_entry = next(
                entry for entry in installed["shortcuts"] if entry["kind"] == "start-menu"
            )
            legacy_receipt = {
                **installed,
                "schemaVersion": 2,
                "shortcut": start_entry["path"],
                "installedSemanticHash": start_entry["installedSemanticHash"],
                "installedFileHashInformational": start_entry["installedFileHashInformational"],
            }
            legacy_receipt.pop("shortcuts")
            (data_dir / "start-menu-shortcut.json").write_text(
                json.dumps(legacy_receipt), encoding="utf-8"
            )

            migrated = install_shortcut(
                data_dir,
                shortcut,
                executable,
                ROOT / "runtime" / "windows-adapters.json",
                acknowledged=True,
                original_shortcut=original_shortcut,
                desktop_shortcut=desktop_shortcut,
            )
            self.assertEqual(migrated["schemaVersion"], 4)
            self.assertTrue(shortcut.exists())
            self.assertTrue(desktop_shortcut.exists())
            self.assertEqual(shortcut_status(data_dir)["status"], "installed")

    def test_reinstall_atomically_switches_generation_and_keeps_previous_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            shortcut = root / "Codex ChromaPaw.lnk"
            desktop_shortcut = root / "Desktop" / "Codex ChromaPaw.lnk"
            adapters = root / "windows-adapters.json"
            adapters.write_bytes((ROOT / "runtime" / "windows-adapters.json").read_bytes())

            first = install_shortcut(
                data_dir,
                shortcut,
                executable,
                adapters,
                acknowledged=True,
                original_shortcut=original_shortcut,
                desktop_shortcut=desktop_shortcut,
            )
            first_generation = Path(first["hostedRuntime"]["generationDir"])
            adapters.write_text(adapters.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            second = install_shortcut(
                data_dir,
                shortcut,
                executable,
                adapters,
                acknowledged=True,
                original_shortcut=original_shortcut,
                desktop_shortcut=desktop_shortcut,
            )
            second_generation = Path(second["hostedRuntime"]["generationDir"])

            self.assertNotEqual(first_generation, second_generation)
            self.assertTrue(first_generation.is_dir())
            self.assertTrue(second_generation.is_dir())
            current = json.loads(
                Path(second["hostedRuntime"]["current"]).read_text(encoding="utf-8")
            )
            self.assertEqual(current["generation"], second["hostedRuntime"]["generation"])
            self.assertEqual(shortcut_status(data_dir)["status"], "installed")

    def test_reinstall_keeps_reviewed_skin_pinned_to_previous_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            data_dir.mkdir()
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            shortcut = root / "Codex ChromaPaw.lnk"
            desktop_shortcut = root / "Desktop" / "Codex ChromaPaw.lnk"
            adapters = root / "windows-adapters.json"
            adapters.write_bytes((ROOT / "runtime" / "windows-adapters.json").read_bytes())
            preference_path = data_dir / "preferred-skin.json"
            preference_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "package": "C:/fixture/skin",
                        "packageId": "fixture",
                        "manifestHash": "a" * 64,
                        "cssHash": "b" * 64,
                        "executable": str(executable),
                        "executableHash": "c" * 64,
                        "appVersion": "26.707.9981.0",
                        "adapterId": "fixture-adapter",
                        "adapterFile": str(adapters),
                        "adapterFileHash": "d" * 64,
                    }
                ),
                encoding="utf-8",
            )

            preference = json.loads(preference_path.read_text(encoding="utf-8"))
            with mock.patch(
                "windows_shortcut.build_preflight", return_value=preference
            ):
                first = install_shortcut(
                    data_dir,
                    shortcut,
                    executable,
                    adapters,
                    acknowledged=True,
                    original_shortcut=original_shortcut,
                    desktop_shortcut=desktop_shortcut,
                )
            first_preference = json.loads(preference_path.read_text(encoding="utf-8"))
            self.assertEqual(
                first_preference["runtimeGeneration"], first["hostedRuntime"]["generation"]
            )

            adapters.write_text(adapters.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            second = install_shortcut(
                data_dir,
                shortcut,
                executable,
                adapters,
                acknowledged=True,
                original_shortcut=original_shortcut,
                desktop_shortcut=desktop_shortcut,
            )
            second_preference = json.loads(preference_path.read_text(encoding="utf-8"))

            self.assertNotEqual(
                first["hostedRuntime"]["generation"],
                second["hostedRuntime"]["generation"],
            )
            self.assertEqual(
                second_preference["runtimeGeneration"],
                first["hostedRuntime"]["generation"],
            )
            self.assertTrue(Path(first["hostedRuntime"]["generationDir"]).is_dir())

    def test_explicit_reviewed_runtime_upgrade_moves_pin_after_continuity_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            data_dir.mkdir()
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture executable")
            original_shortcut = root / "ChatGPT.lnk"
            _write_shortcut(
                original_shortcut,
                target=executable,
                arguments="",
                working_directory=executable.parent,
                icon=executable,
                description="ChatGPT",
            )
            shortcut = root / "Codex ChromaPaw.lnk"
            desktop_shortcut = root / "Desktop" / "Codex ChromaPaw.lnk"
            adapters = root / "windows-adapters.json"
            adapters.write_bytes((ROOT / "runtime" / "windows-adapters.json").read_bytes())
            preference_path = data_dir / "preferred-skin.json"
            preference = {
                "schemaVersion": 1,
                "package": "C:/fixture/skin",
                "packageId": "fixture",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
                "executable": str(executable),
                "executableHash": "c" * 64,
                "appVersion": "26.707.9981.0",
                "adapterId": "fixture-adapter",
                "adapterFileHash": "d" * 64,
            }
            preference_path.write_text(json.dumps(preference), encoding="utf-8")
            with mock.patch(
                "windows_shortcut.build_preflight", return_value=preference
            ):
                first = install_shortcut(
                    data_dir,
                    shortcut,
                    executable,
                    adapters,
                    acknowledged=True,
                    original_shortcut=original_shortcut,
                    desktop_shortcut=desktop_shortcut,
                )
                adapters.write_text(
                    adapters.read_text(encoding="utf-8") + "\n", encoding="utf-8"
                )
                second = install_shortcut(
                    data_dir,
                    shortcut,
                    executable,
                    adapters,
                    acknowledged=True,
                    upgrade_reviewed_runtime=True,
                    original_shortcut=original_shortcut,
                    desktop_shortcut=desktop_shortcut,
                )

            saved = json.loads(preference_path.read_text(encoding="utf-8"))
            self.assertNotEqual(
                first["hostedRuntime"]["generation"],
                second["hostedRuntime"]["generation"],
            )
            self.assertEqual(
                saved["runtimeGeneration"], second["hostedRuntime"]["generation"]
            )


if __name__ == "__main__":
    unittest.main()
