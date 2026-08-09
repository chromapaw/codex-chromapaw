# Desktop Pet MVP

ChromaPaw `0.2.0` turns one local reference image plus a short behavior description into a reviewed Codex desktop v2 pet. It composes two layers instead of replacing the supported animation workflow:

- ChromaPaw handles request normalization, package validation, installation, backup, and restore.
- Codex's installed `hatch-pet` skill handles visual generation, deterministic atlas assembly, and visual QA.

## User flow

1. Attach one image in Codex and invoke `$create-chromapaw-pet`.
2. Describe any special actions, such as “拍篮球” while working and “用篮球跳舞” when ready.
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

- PNG or WebP
- `1536×2288`
- 8 columns × 11 rows
- `192×208` per cell
- declared with `spriteVersionNumber: 2`

The 8×9 `1536×1872` atlas produced during standard-row assembly is an intermediate artifact and is rejected as a new v2 package.

## Validation and installation

```bash
python scripts/validate_pet_package.py build/basket-buddy/package --json
python scripts/install_pet.py build/basket-buddy/package --json
```

The install destination is `$CODEX_HOME/pets/<id>` when `CODEX_HOME` is set, otherwise `~/.codex/pets/<id>`.

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

- The action descriptions shape the closest supported visual animation rows; they do not add Codex runtime states or change task execution.
- ChromaPaw's validator checks package structure, path safety, image type, version, and dimensions. A generated pet still needs every hatch-pet deterministic and visual gate.
- Version `0.2.0` targets local desktop v2 packages. It does not claim a web-upload export format.
- Pet installation does not modify `WindowsApps`, signed application files, or the Codex renderer.
