from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import release_check  # noqa: E402


class ReleaseCheckTests(unittest.TestCase):
    def test_repository_schema_contracts_are_valid(self) -> None:
        release_check.validate_schema_contracts()

    def test_schema_validation_rejects_invalid_registry(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "windows-runtime-adapters.schema.json").read_text(
                encoding="utf-8"
            )
        )
        invalid = json.loads(
            (ROOT / "runtime" / "windows-adapters.json").read_text(encoding="utf-8")
        )
        invalid["schemaVersion"] = 999

        with self.assertRaisesRegex(
            release_check.ReleaseCheckError,
            r"runtime/windows-adapters\.json violates .* at \$\.schemaVersion",
        ):
            release_check._validate_schema_value(
                schema,
                invalid,
                schema_name="schemas/windows-runtime-adapters.schema.json",
                instance_name="runtime/windows-adapters.json",
            )


if __name__ == "__main__":
    unittest.main()
