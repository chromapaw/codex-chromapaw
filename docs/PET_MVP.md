# Desktop Pet MVP

ChromaPaw turns one local reference image plus a short behavior description into a reviewed Codex desktop v2 pet. It composes two layers instead of replacing the supported animation workflow:

- ChromaPaw handles request normalization, package validation, installation, backup, and restore.
- Codex's installed `hatch-pet` skill handles visual generation, deterministic atlas assembly, and visual QA.

## Dependency preflight

Before visual generation, ChromaPaw runs `scripts/check_dependencies.py --json`. It accepts a compatible `hatch-pet` directory from `--hatch-pet-dir`, `CHROMAPAW_HATCH_PET_DIR`, `$CODEX_HOME/skills/hatch-pet`, or `$CODEX_HOME/skills/.system/hatch-pet`, in that order. The check requires the skill manifest plus the preparation, extended-atlas assembly, and atlas-validation scripts.

If no compatible directory is found, pet generation stops before creating visual assets. ChromaPaw reports every checked path and does not silently download, copy, or invent the external workflow.

## User flow

1. Attach one image in Codex and invoke `$create-chromapaw-pet`.
2. Describe any special actions, such as “shoot the basketball” while working and “dance with the basketball” when ready.
3. Review the extended contact sheet, direction sheet, and motion previews.
4. Install the staged package after it passes both hatch QA and ChromaPaw validation.
5. If the same id is already installed, approve or reject an explicit backed-up replacement.

## Request file

`prepare_pet_request.py` writes `pet-request.json`. It records the resolved source-image path, display identity, style preset, five user-facing action intentions, a `hatchPetHandoff`, and the desktop v2 geometry target.

```bash
python scripts/prepare_pet_request.py \
  --image character.png \
  --name "Basket Buddy" \
  --working-action "Dribble and shoot the basketball" \
  --ready-action "Dance with the basketball" \
  --output-dir build/basket-buddy
```

The request file is local build metadata. Do not publish it unchanged when its absolute source path contains private information.

## Package contract

```text
basket-buddy/
  pet.json
  spritesheet.webp
```

The manifest follows [schemas/pet.schema.json](../schemas/pet.schema.json). The final atlas must be:

- PNG or WebP;
- `1536×2288`;
- 8 columns × 11 rows;
- `192×208` per cell;
- declared with `spriteVersionNumber: 2`.

The 8×9 `1536×1872` atlas produced during standard-row assembly is an intermediate artifact and is rejected as a new v2 package.

## Validation and installation

```bash
python scripts/validate_pet_package.py build/basket-buddy/package --json
python scripts/install_pet.py build/basket-buddy/package --json
```

The install destination is `$CODEX_HOME/pets/<id>` when `CODEX_HOME` is set, otherwise `~/.codex/pets/<id>`. This path model and the Python implementation are operating-system neutral. Windows has been exercised locally; a real Mac must still validate generation, installation, animation loading, replacement, and restore before macOS is marked verified.

The installer refuses an existing id by default. Explicit replacement moves the old directory to `pets/.chromapaw-backups/<id>-<UTC timestamp>` before the staged package is moved into place:

```bash
python scripts/install_pet.py build/basket-buddy/package --replace --json
```

Restore a managed backup with:

```bash
python scripts/restore_pet.py basket-buddy-<UTC timestamp> --replace --json
```

Restore also backs up the currently installed version, so a mistaken restore remains reversible.

## Boundaries

- Action descriptions shape the closest supported visual animation rows; they do not add Codex runtime states or change task execution.
- ChromaPaw validates structure, path safety, image type, version, and dimensions. A generated pet still needs every hatch-pet deterministic and visual gate.
- The workflow targets local desktop v2 packages; it does not claim a web-upload export format.
- Pet installation does not modify `WindowsApps`, signed application files, a macOS `.app` bundle, or the Codex renderer.
