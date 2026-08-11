from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_pets import audit_pets  # noqa: E402


def write_png_header(path: Path, width: int, height: int) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
    )


def write_pet(root: Path, version: int, height: int, *, valid_id: bool = True) -> None:
    root.mkdir(parents=True)
    manifest = {
        "displayName": root.name,
        "description": "Fixture pet for an audit test.",
        "spriteVersionNumber": version,
        "spritesheetPath": "spritesheet.png",
    }
    if valid_id:
        manifest["id"] = root.name
    (root / "pet.json").write_text(json.dumps(manifest), encoding="utf-8")
    write_png_header(root / "spritesheet.png", 1536, height)


class AuditPetsTests(unittest.TestCase):
    def test_reports_valid_legacy_and_invalid_without_modifying_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            pets = home / "pets"
            write_pet(pets / "valid-pet", 2, 2288)
            write_pet(pets / "legacy-pet", 1, 1872, valid_id=False)
            (pets / "broken-pet").mkdir()

            before = sorted(str(path.relative_to(home)) for path in home.rglob("*"))
            result = audit_pets(home)
            after = sorted(str(path.relative_to(home)) for path in home.rglob("*"))

            self.assertEqual(before, after)
            self.assertFalse(result["releaseReady"])
            self.assertEqual(result["validV2Count"], 1)
            self.assertEqual(result["issueCount"], 2)
            statuses = {entry["name"]: entry["status"] for entry in result["pets"]}
            self.assertEqual(statuses["valid-pet"], "valid-v2")
            self.assertEqual(statuses["legacy-pet"], "legacy-v1")
            self.assertEqual(statuses["broken-pet"], "invalid")


if __name__ == "__main__":
    unittest.main()
