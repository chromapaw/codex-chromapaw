from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_dependencies import (
    HATCH_PET_REQUIRED_PYTHON_SCRIPTS,
    check_dependencies,
    inspect_hatch_pet,
)


def write_compatible_hatch_pet(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        "---\n"
        "name: hatch-pet\n"
        "description: Create and validate complete Codex v2 animated pets.\n"
        "---\n\n"
        "# Hatch Pet\n\n"
        "Call load_workspace_dependencies before scripts. Build imagegen-jobs.json, "
        "then package spriteVersionNumber: 2.\n",
        encoding="utf-8",
    )
    for relative in HATCH_PET_REQUIRED_PYTHON_SCRIPTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        from scripts.check_dependencies import HATCH_PET_SCRIPT_CONTRACTS

        flags = HATCH_PET_SCRIPT_CONTRACTS[relative]["flags"]
        path.write_text(
            "def main():\n"
            f"    flags = {flags!r}\n"
            "    return len(flags)\n",
            encoding="utf-8",
        )
    return root


class DependencyTests(unittest.TestCase):
    def test_missing_hatch_pet_is_reported_with_machine_readable_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)

            result = check_dependencies(home)
            dependency = result["dependencies"]["hatch-pet"]

            self.assertFalse(result["ok"])
            self.assertFalse(dependency["available"])
            self.assertIsNone(dependency["path"])
            self.assertFalse(dependency["validation"]["valid"])
            self.assertIn("visualQa", dependency["capabilities"])
            self.assertTrue(dependency["contract"]["requiredPythonScripts"])

    def test_complete_compatible_hatch_pet_layout_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            hatch_pet = write_compatible_hatch_pet(home / "skills" / "hatch-pet")

            result = check_dependencies(home)
            dependency = result["dependencies"]["hatch-pet"]

            self.assertTrue(result["ok"])
            self.assertEqual(dependency["path"], str(hatch_pet))
            self.assertTrue(dependency["validation"]["skillMetadata"]["valid"])
            self.assertTrue(dependency["validation"]["pythonScripts"]["valid"])
            self.assertTrue(
                all(item["available"] for item in dependency["capabilities"].values())
            )

    def test_missing_late_visual_qa_script_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hatch_pet = write_compatible_hatch_pet(Path(temporary) / "hatch-pet")
            relative = "scripts/render_animation_previews.py"
            (hatch_pet / relative).unlink()

            result = inspect_hatch_pet(hatch_pet)

            self.assertFalse(result["available"])
            self.assertIn(relative, result["missing"])
            self.assertFalse(result["capabilities"]["visualQa"]["available"])

    def test_empty_required_python_script_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hatch_pet = write_compatible_hatch_pet(Path(temporary) / "hatch-pet")
            relative = "scripts/validate_direction_blind_verdicts.py"
            (hatch_pet / relative).write_text(" \n", encoding="utf-8")

            result = inspect_hatch_pet(hatch_pet)

            self.assertFalse(result["available"])
            self.assertIn(
                "empty_python_script",
                {issue["code"] for issue in result["validation"]["issues"]},
            )
            self.assertFalse(result["capabilities"]["blindDirectionQa"]["available"])

    def test_compileable_stub_without_cli_contract_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hatch_pet = write_compatible_hatch_pet(Path(temporary) / "hatch-pet")
            relative = "scripts/render_animation_previews.py"
            (hatch_pet / relative).write_text(
                "def main():\n    return 0\n", encoding="utf-8"
            )

            result = inspect_hatch_pet(hatch_pet)

            self.assertFalse(result["available"])
            self.assertIn(
                "python_contract_flag_missing",
                {issue["code"] for issue in result["validation"]["issues"]},
            )

    def test_python_compile_error_fails_with_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hatch_pet = write_compatible_hatch_pet(Path(temporary) / "hatch-pet")
            relative = "scripts/measure_direction_continuity.py"
            (hatch_pet / relative).write_text("def broken(:\n", encoding="utf-8")

            result = inspect_hatch_pet(hatch_pet)
            issue = next(
                issue
                for issue in result["validation"]["issues"]
                if issue["code"] == "python_compile_error"
            )

            self.assertFalse(result["available"])
            self.assertEqual(issue["path"], relative)
            self.assertEqual(issue["line"], 1)
            self.assertFalse(result["capabilities"]["directionQa"]["available"])

    def test_wrong_frontmatter_name_fails_skill_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hatch_pet = write_compatible_hatch_pet(Path(temporary) / "hatch-pet")
            skill = hatch_pet / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "name: hatch-pet", "name: almost-hatch-pet"
                ),
                encoding="utf-8",
            )

            result = inspect_hatch_pet(hatch_pet)

            self.assertFalse(result["available"])
            self.assertFalse(result["validation"]["skillMetadata"]["valid"])
            self.assertFalse(result["capabilities"]["skillContract"]["available"])
            self.assertIn(
                "skill_name_mismatch",
                {issue["code"] for issue in result["validation"]["issues"]},
            )

    def test_missing_workflow_capability_marker_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hatch_pet = write_compatible_hatch_pet(Path(temporary) / "hatch-pet")
            skill = hatch_pet / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace("imagegen-jobs.json", "jobs.json"),
                encoding="utf-8",
            )

            result = inspect_hatch_pet(hatch_pet)

            self.assertFalse(result["available"])
            self.assertIn(
                "skill_capability_marker_missing",
                {issue["code"] for issue in result["validation"]["issues"]},
            )


if __name__ == "__main__":
    unittest.main()
