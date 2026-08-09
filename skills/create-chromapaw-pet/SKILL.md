---
name: create-chromapaw-pet
description: Create a Codex-compatible animated pet from a user-provided character, mascot, object, or reference image. Use when a user asks ChromaPaw to turn one image into a custom pet, preserve a character identity across task-state animations, define working or completion actions, validate a pet spritesheet, or install a finished local Codex pet.
---

# Create ChromaPaw Pet

Create a reviewed Codex pet from one visual reference while preserving the subject's recognizable identity.

Read [references/pet-mvp.md](references/pet-mvp.md) before preparing, validating, or installing a pet.

## Required workflow

1. Confirm the source image exists and inspect it before generation.
2. Infer the pet name and style when possible. Ask only for missing decisions that materially change the result.
3. Translate the user's request into idle, working, waiting, ready, and failed intent. Preserve named props in every applicable state.
4. Run `scripts/prepare_pet_request.py` and read the generated `pet-request.json` before visual generation.
5. Load and follow the installed `$hatch-pet` skill as the authoritative v2 generation and visual-QA workflow. Pass it the exact reference, name, description, style preset, and `hatchPetHandoff.petNotes` values from the request. Do not invent a competing atlas contract or skip its required direction QA.
6. Keep the attached source image visible to every generation job that requires identity grounding.
7. Stage the approved `pet.json` and final extended spritesheet in a package directory outside the live Codex pets directory.
8. Run `scripts/validate_pet_package.py` on the staged directory. This structural validator supplements, but never replaces, `$hatch-pet` deterministic and visual QA.
9. Show the extended contact sheet, direction sheet, and motion previews before installation.
10. Install with `scripts/install_pet.py`. Do not pass `--replace` unless the user explicitly approves replacing the displayed existing id and has been told the backup location.

## Defaults

- Infer a short friendly name when the user does not provide one.
- Preserve the reference style unless the user requests a transformation.
- Prefer readable whole-body poses over detached effects, text, scenery, or motion streaks.
- Treat a prop named in the user's request as part of the pet identity.
- Map working intent to the supported active-task animation family and completion intent to the closest supported celebration rows. Do not claim that custom art changes Codex's task scheduler or creates new runtime states.

## Safety

- Do not overwrite an existing pet with the same id without confirmation.
- Do not claim that changing a pet changes task execution behavior.
- Do not package a partial or unvalidated atlas.
- If `hatch-pet` is unavailable, stop and report that dependency instead of fabricating a pet format.
- Keep generation artifacts and the source image inside user-approved local output paths.
