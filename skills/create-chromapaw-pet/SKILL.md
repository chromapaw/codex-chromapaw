---
name: create-chromapaw-pet
description: Create a Codex-compatible animated pet from a user-provided character, mascot, object, or reference image. Use when a user asks ChromaPaw to turn one image into a custom pet, preserve a character identity across task-state animations, define working or completion actions, validate a pet spritesheet, or install a finished local Codex pet.
---

# Create ChromaPaw Pet

Create a reviewed Codex pet from one visual reference while preserving the subject's recognizable identity.

## Workflow

1. Confirm the source image exists and inspect it before generation.
2. Collect only missing decisions that materially affect the result: pet name, visual style, and special task-state actions.
3. Translate the user's behavior request into distinct working, waiting, ready, failed, and idle intent. Preserve signature props across all states.
4. Use the installed `hatch-pet` skill as the authoritative generation, atlas, direction, QA, and packaging workflow. Do not invent a competing spritesheet contract.
5. Keep the source image attached wherever the selected image-generation route supports references.
6. Show the final contact sheet and motion previews before installation when the workflow produces them.
7. Install only a package that passes deterministic and visual validation.

## Defaults

- Infer a short friendly name when the user does not provide one.
- Preserve the reference style unless the user requests a transformation.
- Prefer readable whole-body poses over detached effects, text, scenery, or motion streaks.
- Treat a prop named in the user's request as part of the pet identity.

## Safety

- Do not overwrite an existing pet with the same id without confirmation.
- Do not claim that changing a pet changes task execution behavior.
- Do not package a partial or unvalidated atlas.
- If `hatch-pet` is unavailable, stop and report that dependency instead of fabricating a pet format.
