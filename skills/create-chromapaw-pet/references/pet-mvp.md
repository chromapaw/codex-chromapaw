# Pet MVP workflow

Use this contract for ChromaPaw `0.2.x` desktop pets.

## 1. Resolve paths

Locate the repository root by walking two directories upward from this skill directory. Use the active Python 3.10-or-later executable for ChromaPaw's dependency-free scripts. Before invoking any bundled `$hatch-pet` script, follow `$hatch-pet`'s runtime-dependency instructions and use the workspace Python it selects.

Keep three locations separate:

- request/run directory: working files and QA artifacts
- staged package directory: validated `pet.json` plus the final atlas
- live directory: `${CODEX_HOME:-$HOME/.codex}/pets/<id>`

Never generate directly over an existing live pet.

## 2. Normalize the request

Run the request builder with the attached image and the user's animation intent:

```text
python scripts/prepare_pet_request.py \
  --image <absolute-reference-path> \
  --name <display-name> \
  --style auto \
  --working-action "<what the pet does while a task is active>" \
  --waiting-action "<how the pet asks for input>" \
  --ready-action "<how the pet celebrates completion>" \
  --failed-action "<how the pet reacts to failure>" \
  --output-dir <absolute-run-directory>
```

Omit optional flags when defaults are appropriate. Read `pet-request.json`; do not reconstruct its handoff values from memory.

Example intent for a basketball mascot:

```text
working: dribble and shoot the basketball with focused body language
waiting: hold the basketball and look expectantly toward the user
ready: perform a compact celebration dance with the basketball
failed: hug the basketball and sit in a gently disappointed pose
```

## 3. Generate and review

Use the installed `$hatch-pet` workflow with:

- `sourceImage` as the visual reference
- `displayName` and `description` as package identity
- `style` as the hatch style preset
- `hatchPetHandoff.petNotes` as stable behavior guidance

Complete all of `$hatch-pet`'s standard rows, 16 look directions, deterministic checks, blind direction review, contact sheets, and motion previews. The final desktop atlas must be PNG or WebP, exactly `1536x2288`, with `192x208` cells in an `8x11` layout.

The intent labels are creative guidance for supported Codex animation rows. They do not add new app states or change when Codex considers a task active, waiting, complete, or failed.

## 4. Stage and validate

After every hatch gate passes, place only the approved desktop package in a staging directory:

```text
package/
  pet.json
  spritesheet.webp
```

`pet.json` must contain:

```json
{
  "id": "basket-buddy",
  "displayName": "Basket Buddy",
  "description": "A basketball-loving custom Codex pet.",
  "spriteVersionNumber": 2,
  "spritesheetPath": "spritesheet.webp"
}
```

Validate the staged package:

```text
python scripts/validate_pet_package.py <absolute-package-directory> --json
```

The ChromaPaw validator checks manifest safety, file containment, image format, v2 declaration, and exact atlas dimensions. A passing result does not waive hatch visual QA.

## 5. Install or replace

For a new id:

```text
python scripts/install_pet.py <absolute-package-directory> --json
```

If the id already exists, stop and show the destination. Only after explicit approval:

```text
python scripts/install_pet.py <absolute-package-directory> --replace --json
```

The replace path moves the previous directory into `pets/.chromapaw-backups/` before installing the staged package. Report both the destination and backup path.

Restore a named backup only after showing its manifest and current destination:

```text
python scripts/restore_pet.py <backup-directory-name> --replace --json
```

Do not modify `WindowsApps`, the signed Codex application bundle, or unrelated pet directories.
