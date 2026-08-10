# Skin Studio v2 workflow

Use this contract for ChromaPaw Skin Studio v2 portable skins. The dependency-free validator still accepts legacy schemaVersion 1 packages.

## 1. Keep three locations separate

- reference/run directory: original image, optional generated environment, and `skin-request.json`
- package directory: shareable v2 assets, metadata, previews, and QA
- runtime state directory: used only by a separately authorized, supported runtime; Codex application files remain untouched

Skin Studio never generates directly into Codex application files.

## 2. Prepare the scene

A complete skin needs four visible depth layers:

1. atmosphere — sky, haze, light, clouds, particles, or distant color
2. distant — horizon, skyline, far landscape, or room boundary
3. midground — the main environment around the reading surface
4. foreground — restrained edge decoration that adds depth without covering controls

If the uploaded image is only a mascot, object, texture, or palette cue, first use the image-generation workflow to create a full desktop environment. Keep the central reading and bottom input zones low-detail.

## 3. Normalize the request

Use the workspace Python returned by Codex's workspace dependency loader. The builder requires Pillow from that runtime.

```text
python scripts/prepare_skin_request.py \
  --image <absolute-original-reference> \
  --artwork <absolute-approved-expanded-scene> \
  --name "Summer Beach" \
  --mode adaptive \
  --scene-brief "Fresh beach, waves, sand, coral, and dimensional foreground edges" \
  --author "User-provided reference" \
  --license "Unspecified" \
  --output-dir <absolute-run-directory>
```

Omit `--artwork` when the original is already a complete environment. Read the generated request before building.

## 4. Build and validate

```text
python scripts/build_skin_package.py \
  --request <absolute-run-directory>/skin-request.json \
  --output-dir <absolute-package-directory> \
  --json

python scripts/validate_skin_package.py <absolute-package-directory> --json
```

The v2 package structure is:

```text
my-skin/
├── skin.json
├── assets/
│   ├── background.png
│   ├── theme.css
│   ├── theme-light.css
│   ├── theme-dark.css
│   ├── preview.png
│   └── previews/
│       ├── preview-light-16x10.png
│       ├── preview-light-16x9.png
│       ├── preview-light-4x3.png
│       ├── preview-dark-16x10.png
│       ├── preview-dark-16x9.png
│       └── preview-dark-4x3.png
└── qa/
    └── skin-studio-report.json
```

`skin.json` declares schemaVersion 2, the active mode, all three stylesheets, all six previews, accessible light/dark palettes, a normalized safe content zone, four depth layers, source attribution, and the QA report path.

The preview dimensions are fixed for deterministic QA:

- 16:10 — 960×600
- 16:9 — 960×540
- 4:3 — 840×630

## 5. Review

Inspect both light and dark 16:10 previews, then check the narrow-height 16:9 and compact 4:3 previews. Reject the package when:

- the result looks like a flat color swap;
- the environment disappears behind opaque panels;
- important artwork sits under the reading or input area;
- either palette fails 4.5:1 text contrast;
- pet overlay isolation is absent from the CSS;
- any QA check or structural validation fails.

## 6. Activation boundary

The stylesheets are portable package content, not permission to inject into Codex. Finish and validate the package first. If the user separately requests activation, hand off to `$manage-chromapaw`, which must run the 0.4 Windows Runtime Beta preflight and safety workflow. Unknown or disabled versions remain preview-only.
