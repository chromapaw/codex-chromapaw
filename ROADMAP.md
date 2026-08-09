# Roadmap

## 0.1 — Foundation

- Valid Codex plugin manifest.
- Separate pet, skin, and management skills.
- Portable skin-package schema and validator.
- Safety, architecture, contribution, and security documentation.
- Dependency-free validation tests that can run on Windows, macOS, and Linux.

## 0.2 — Pet MVP

- One-image input workflow built on the supported Codex pet pipeline.
- User-defined animation intent for working, waiting, ready, and failed states.
- Contact-sheet and motion-preview review.
- Desktop v2 package plus a web-compatible export path where supported.

## 0.3 — Skin Studio MVP

- Scene expansion and layered composition from one source image.
- Palette extraction, safe content zones, readable surfaces, and preview rendering.
- Versioned `skin.json`, CSS, background, and attribution bundle.
- Built-in light/dark and common window-ratio variants.

## 0.4 — Reversible Windows Runtime

- Version-gated Codex renderer adapter.
- Backup, activate, verify, stop, and restore lifecycle.
- No modification of `WindowsApps` or official application archives.
- Security review of any local debugging transport before release.

## 0.5 — Cross-platform and ecosystem

- macOS runtime investigation.
- Community skin and pet gallery format.
- Signed releases and reproducible packaging.
- Accessibility, reduced-motion, and localization passes.

## 1.0 — Stable release

- Documented compatibility policy.
- Stable migration path for package schema updates.
- Release-quality installers, recovery tooling, and automated compatibility tests.
