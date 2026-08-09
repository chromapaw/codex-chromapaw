# Skin package contract

A portable ChromaPaw skin is a directory with this minimum structure:

```text
my-skin/
├── skin.json
└── assets/
    ├── background.png
    ├── theme.css
    └── preview.png
```

`skin.json` must declare schema version 1, a lower-case kebab-case id, display name, mode, asset paths, and the three core colors.

```json
{
  "schemaVersion": 1,
  "id": "summer-beach",
  "displayName": "Summer Beach",
  "mode": "light",
  "assets": {
    "background": "assets/background.png",
    "stylesheet": "assets/theme.css",
    "preview": "assets/preview.png"
  },
  "theme": {
    "surface": "#F7FCF9",
    "ink": "#173F46",
    "accent": "#FF7F66",
    "panelOpacity": 0.82
  }
}
```

All paths must be relative, remain inside the package, and point to existing files. The repository root contains the authoritative JSON schema and dependency-free validator.

The stylesheet is package content, not permission to inject itself into Codex. A separate version-gated runtime owns activation and recovery.
