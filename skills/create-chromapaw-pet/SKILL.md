---
name: create-chromapaw-pet
description: Create a Codex-compatible animated pet from a user-provided character, mascot, object, or reference image. Use when a user asks ChromaPaw to turn one image into a custom pet, preserve a character identity across task-state animations, define working or completion actions, validate a pet spritesheet, or install a finished local Codex pet.
---

# Create ChromaPaw Pet

Create a reviewed Codex pet from one visual reference while preserving the subject's recognizable identity.

Read [references/pet-mvp.md](references/pet-mvp.md) before preparing, validating, or installing a pet.

## Required workflow

1. Confirm the source image exists and inspect it before generation.
2. Resolve this skill's plugin root, run `scripts/check_dependencies.py --json`, and read the result. Stop before visual generation when `hatch-pet` is unavailable; report the checked paths and remediation message instead of guessing a package format.
3. Infer the pet name and style when possible. Ask only for missing decisions that materially change the result.
4. Translate the user's request into idle, working, waiting, ready, and failed intent. Preserve named props in every applicable state.
5. Run `scripts/prepare_pet_request.py` and read the generated `pet-request.json` before visual generation.
6. Load and follow the detected `$hatch-pet` skill as the authoritative v2 generation and visual-QA workflow. Pass it the exact reference, name, description, style preset, and `hatchPetHandoff.petNotes` values from the request. Do not invent a competing atlas contract or skip its required direction QA.
7. Keep the attached source image visible to every generation job that requires identity grounding.
8. Stage the approved `pet.json` and final extended spritesheet in a package directory outside the live Codex pets directory.
9. Run `scripts/validate_pet_package.py` on the staged directory. This structural validator supplements, but never replaces, `$hatch-pet` deterministic and visual QA.
10. Show the extended contact sheet, direction sheet, and motion previews before installation.
11. Run `scripts/post_generation_guidance.py pet <package> --platform auto --json`. Present its exact `generated-not-installed` status, destination, replacement state, selection behavior, possible restart requirement, and confirmation phrase. Always say that generation did **not** install or select the pet.
12. Stop and wait for the separate confirmation returned by the guidance script. For a new id, after the user replies `安装这个宠物`, run `scripts/install_pet.py <package> --select --json`. For an existing id, show the destination and install only after the user replies `同意替换安装宠物 <id>`, then run `scripts/install_pet.py <package> --replace --select --json`; the replace operation must create and report its pet backup, and selection must report any config backup. A request to create or generate a pet never counts as installation confirmation.
13. Report the selected avatar id and whether a restart may be required. If the pet is not immediately visible while Codex is open, tell the user to close and reopen Codex; never claim live visibility without verifying the real app.

## Defaults

- Infer a short friendly name when the user does not provide one.
- Preserve the reference style unless the user requests a transformation.
- Prefer readable whole-body poses over detached effects, text, scenery, or motion streaks.
- Treat a prop named in the user's request as part of the pet identity.
- Map working intent to the supported active-task animation family and completion intent to the closest supported celebration rows. Do not claim that custom art changes Codex's task scheduler or creates new runtime states.

## Safety

- Do not overwrite an existing pet with the same id without confirmation.
- Pet selection may edit only `[desktop].selected-avatar-id`; preserve all unrelated config, back up an existing config, and fail closed on duplicate or ambiguous keys.
- Do not claim that changing a pet changes task execution behavior.
- Do not package a partial or unvalidated atlas.
- If `hatch-pet` is unavailable, preserve the dependency check JSON, stop, and report its remediation message instead of fabricating a pet format.
- Keep generation artifacts and the source image inside user-approved local output paths.
