---
name: create-chromapaw-skin
description: Turn a user-provided image into a layered ChromaPaw skin package for Codex. Use when a user asks for a complete visual theme with scenery, background elements, dimensional depth, readable panels, generated theme assets, a skin preview, or a portable skin package rather than only changing flat interface colors.
---

# Create ChromaPaw Skin

Create a portable, validated visual package. Keep package generation independent from live Codex activation.

## Workflow

1. Inspect the reference image and determine whether it is a scene, character, object, texture, or palette cue.
2. Confirm light, dark, or adaptive mode only when the user's request does not make it clear.
3. Design depth in four layers: atmosphere, distant environment, middle environment, and foreground decoration. Keep the central reading and input zones quiet.
4. Use the available image-generation skill for new raster art or image edits. Do not simulate visual generation with CSS gradients when the user asked for environmental artwork.
5. Derive accessible surface, ink, accent, and panel-opacity values from the approved artwork.
6. Create `skin.json`, the background, stylesheet, and PNG preview using the contract in [references/skin-package.md](references/skin-package.md).
7. Run the repository's `scripts/validate_skin_package.py` against the package directory.
8. Present the preview and validation result. Do not activate the package unless a supported runtime exists and the user separately approves activation.

## Quality gates

- Preserve recognizable cues from the input without copying unlicensed logos or text.
- Make scenery visible around the interface instead of hiding it under opaque surfaces.
- Maintain readable text and code blocks at common window sizes.
- Keep generated assets inside the package and record known source attribution.
- Reject a package with missing assets, unsafe relative paths, invalid colors, or no PNG preview.
