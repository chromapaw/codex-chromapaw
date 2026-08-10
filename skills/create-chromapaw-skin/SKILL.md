---
name: create-chromapaw-skin
description: Turn one user-provided image into a complete ChromaPaw Skin Studio package for Codex. Use when a user asks for a layered theme with scenery, environmental depth, background elements, readable glass panels, automatic palette extraction, light or dark previews, safe content zones, generated CSS, visual QA, or a portable skin package instead of only changing flat interface colors.
---

# Create ChromaPaw Skin

Create a reviewed Skin Studio v2 package from one visual reference. Package generation is supported; live Codex activation remains a separate, version-gated runtime concern.

Read [references/theme-profile.md](references/theme-profile.md) and [references/skin-package.md](references/skin-package.md) before preparing, building, or validating a skin.

## Required workflow

1. Confirm the attached reference exists and inspect it before generation.
2. Classify it as a complete environment or only a character, object, texture, abstract composition, or logo cue.
3. Treat the user's explicit request as authoritative, then derive style, mood, identity cues, motifs, forbidden elements, and four spatial depth descriptions from the current upload. Never copy motifs from examples or a previous run. The four layers are layout slots, not prescribed objects: blue-sky art may use clouds and sunlight; comic art may use panels and halftone; neither should acquire beach scenery unless requested or visibly present.
4. Resolve the plugin root and run `scripts/prepare_theme_profile.py` with the original image and that visual analysis. Read the generated `theme-profile.json`. Stop if a motif also appears in `avoidElements`, or if the recorded image SHA-256 does not represent the current upload.
5. Infer light, dark, or adaptive mode from the request. Ask only when the choice materially changes the desired result. Protect the normalized central reading safe zone and keep faces, logos, high-frequency texture, and bright highlights away from it.
6. When `sourceKind` is not `full-environment`, use the available image-generation skill to expand it into approved scene artwork. Build the prompt only from the current source image, user request, and theme profile. Preserve the attached image as the identity and style reference. Do not substitute CSS gradients for requested scenery. When it is already a complete environment, use the original artwork without unnecessary regeneration.
7. Use the Codex workspace Python runtime with Pillow. Run `scripts/prepare_skin_request.py` with `--theme-profile`, the original image, and, when generated, the approved expanded artwork.
8. Read the generated `skin-request.json`; verify that `themeProfile` still describes the upload and do not reconstruct its metadata or image paths from memory.
9. Run `scripts/build_skin_package.py`. It must produce the background, automatic light and dark palettes, adaptive and fixed CSS, six common-ratio previews, semantic profile, safe-zone metadata, attribution, and structured QA report.
10. Run `scripts/validate_skin_package.py <package> --json`. Do not present a failed package as complete.
11. Visually inspect both light and dark 16:10 previews plus the 16:9 and 4:3 edge cases. Confirm that the image-specific environment remains visible, text panels are readable, foreground decoration does not cover the input area, forbidden or unrelated motifs were not introduced, and no preview is merely a flat color.
12. Present the primary preview, package path, detected theme profile, extracted palette, six-variant QA result, and validation output. Do not activate as an implicit part of creation. If the user separately requested activation, complete validation first and then follow `$manage-chromapaw` and its required safety model.

## Quality gates

- The result must read as a complete environment, not a recolored blank interface.
- The environment must follow the current upload and user intent; no scene category or motif is a global default.
- The source image or expanded artwork must remain visually recognizable.
- Light and dark surface-to-ink contrast must be at least 4.5:1.
- All six light/dark × 16:10/16:9/4:3 previews must exist at their contract dimensions.
- Generated CSS must isolate Codex's transparent pet overlay so a skin background cannot appear as a rectangle behind a pet.
- Paths must be package-relative, assets must remain inside the package, and attribution must not expose local source paths.

## Safety

- Keep the request/run directory separate from the portable package directory.
- Do not modify `WindowsApps`, signed Codex files, `app.asar`, or a live Codex installation.
- Do not claim that portable CSS is activated unless the separate runtime verification passed in the current operation.
- Treat unlicensed logos, characters, and images as private-use references unless the user provides distribution rights.
