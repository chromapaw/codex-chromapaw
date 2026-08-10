# Semantic theme profile

Create this profile before scene expansion or skin packaging. It prevents an example theme, prior task, or implementation default from leaking unrelated objects into a new upload.

## Precedence

1. Follow the user's explicit theme and exclusions.
2. Preserve recognizable content and style from the current reference image.
3. Infer only the minimum details needed to create a complete environment.
4. Never treat example motifs as defaults.

The four depth fields describe spatial placement only. They do not mean sky, horizon, landscape, plants, beach, or any other fixed content. For a blue-sky upload they might describe haze, cloud banks, large clouds, and corner wisps. For comic art they might describe a halftone field, panels, graphic shapes, and edge speed lines.

## Required contract

Run `scripts/prepare_theme_profile.py` with:

- one `sourceKind`: `full-environment`, `subject`, `texture`, `abstract`, or `logo`;
- a theme name, visual style, and mood;
- one or more `identityCues` that make the upload recognizable;
- one or more `motifs` supported by the upload or user request;
- any `avoidElements`, including plausible but unwanted scene clichés;
- image-specific atmosphere, distant, midground, and foreground descriptions;
- central reading and bottom input safe-zone guidance.

Example for a blue-sky reference:

```text
python scripts/prepare_theme_profile.py \
  --image <absolute-reference-image> \
  --source-kind full-environment \
  --theme-name "Open Blue Sky" \
  --visual-style "soft dimensional illustration" \
  --mood "fresh, airy, and optimistic" \
  --identity-cue "clear blue gradient" \
  --identity-cue "rounded white cloud shapes" \
  --motif "blue sky" \
  --motif "white clouds" \
  --motif "soft sunlight" \
  --avoid-element "ocean" \
  --avoid-element "sand" \
  --avoid-element "coral" \
  --atmosphere "Luminous blue air with gentle high-altitude haze" \
  --distant "Small layered cloud banks and a faint bright horizon" \
  --midground "Large soft clouds framing the quiet reading surface" \
  --foreground "Restrained cloud wisps at the outer corners" \
  --safe-zone-guidance "Keep the center and bottom input region calm and low detail" \
  --output-dir <absolute-run-directory>
```

Read `theme-profile.json` after creation. Its `referenceSha256` must match the current upload. A value cannot appear in both `motifs` and `avoidElements`; the script rejects that contradiction.

## Scene expansion

Expand only when the upload is not already a complete environment. Build the image-generation prompt from the user request and the validated profile. Include the reference image for identity grounding. Do not add beach objects to a sky image, plants to a comic image, city elements to an abstract texture, or any other category that lacks support in the current inputs.

After expansion, review the result against every motif, forbidden element, depth description, and safe-zone instruction before passing it to the deterministic builder.
