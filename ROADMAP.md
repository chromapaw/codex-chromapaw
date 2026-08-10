# Roadmap

## 0.1 — Foundation ✅

- Valid Codex plugin manifest.
- Separate pet, skin, and management skills.
- Portable skin-package schema and validator.
- Safety, architecture, contribution, and security documentation.
- Dependency-free validation tests that run on Windows, macOS, and Linux.

## 0.2 — Desktop Pet MVP ✅

- One-image input workflow built on the Codex `hatch-pet` pipeline.
- User-defined animation intent for working, waiting, ready, and failed states.
- Mandatory contact-sheet, direction, and motion-preview review before installation.
- Strict desktop v2 package validation for the 1536×2288 extended atlas.
- Safe installation, explicit replacement, managed backup, and restore commands.

## 0.2.1 — Installable Pet Beta ✅

- Git-backed `chromapaw` marketplace with install, update, and removal commands.
- Dependency preflight for the external `hatch-pet` visual workflow.
- Isolated `CODEX_HOME` marketplace-install smoke test.
- Streaming validation for large lossless WebP pet atlases.
- Versioned GitHub release and clean-install verification.

## 0.3 — Skin Studio MVP ✅

- Scene expansion workflow and four-layer composition from one source image.
- Deterministic request preparation and package builder.
- Automatic light/dark palette extraction with 4.5:1 text contrast gates.
- Safe content zones, readable glass surfaces, and pet-overlay isolation CSS.
- Versioned schemaVersion 2 manifest, three stylesheets, background, and attribution bundle.
- Six built-in visual-QA previews covering light/dark and 16:10/16:9/4:3 windows.
- Legacy schemaVersion 1 validation compatibility.

## 0.4 — Reversible Windows Runtime

- Version-gated Codex renderer adapter.
- Backup, activate, verify, stop, and restore lifecycle.
- No modification of `WindowsApps` or official application archives.
- Security review of any local debugging transport before release.
- Compatibility tests that fail closed on unknown Codex versions.

## 0.5 — Cross-platform and ecosystem

- macOS runtime investigation.
- Community skin and pet gallery format.
- Signed releases and reproducible packaging.
- Accessibility, reduced-motion, and localization passes.

## 1.0 — Stable release

- Documented compatibility policy.
- Stable migration path for package schema updates.
- Release-quality installers, recovery tooling, and automated compatibility tests.
