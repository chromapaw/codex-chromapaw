from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_dependencies import (
    HATCH_PET_REQUIRED_FILES,
    check_dependencies,
)


class DependencyTests(unittest.TestCase):
    def test_missing_hatch_pet_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)

            result = check_dependencies(home)

            self.assertFalse(result["ok"])
            self.assertFalse(result["dependencies"]["hatch-pet"]["available"])
            self.assertIsNone(result["dependencies"]["hatch-pet"]["path"])

    def test_compatible_hatch_pet_layout_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            hatch_pet = home / "skills" / "hatch-pet"
            for relative in HATCH_PET_REQUIRED_FILES:
                path = hatch_pet / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")

            result = check_dependencies(home)

            self.assertTrue(result["ok"])
            self.assertEqual(
                result["dependencies"]["hatch-pet"]["path"],
                str(hatch_pet),
            )


if __name__ == "__main__":
    unittest.main()
