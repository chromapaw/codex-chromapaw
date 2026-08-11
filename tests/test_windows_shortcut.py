from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from pathlib import Path


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
            self.assertEqual(installed["schemaVersion"], 3)
            self.assertEqual(shortcut_status(data_dir)["status"], "installed")
            self.assertTrue(inspect_shortcut(shortcut)["target"].lower().endswith("pythonw.exe"))
            self.assertTrue(
                inspect_shortcut(desktop_shortcut)["target"].lower().endswith("pythonw.exe")
            )
            self.assertEqual(
                shortcut_semantic_hash(inspect_shortcut(original_shortcut)), original_semantic
            )

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
            self.assertEqual(shortcut_status(data_dir)["status"], "not-installed")

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
            self.assertEqual(migrated["schemaVersion"], 3)
            self.assertTrue(shortcut.exists())
            self.assertTrue(desktop_shortcut.exists())
            self.assertEqual(shortcut_status(data_dir)["status"], "installed")


if __name__ == "__main__":
    unittest.main()
