# Roadmap

## 0.1 — Foundation ✅

- Valid Codex plugin manifest.
- Separate pet, skin, and management skills.
- Portable skin-package schema and validator.
- Safety, architecture, contribution, and security documentation.

## 0.2 — Desktop Pet MVP ✅

- One-image workflow built on the Codex `hatch-pet` pipeline.
- User-defined animation intent for working, waiting, ready, and failed states.
- Mandatory contact-sheet, direction, and motion-preview review.
- Strict desktop v2 validation, explicit replacement, managed backup, and restore.

## 0.2.1 — Installable Pet Beta ✅

- Git-backed marketplace installation.
- Explicit `hatch-pet` dependency preflight.
- Isolated `CODEX_HOME` marketplace smoke test.
- Streaming validation for large lossless WebP atlases.

## 0.3 — Skin Studio MVP ✅

- Scene expansion and four-layer composition from one source image.
- Automatic light/dark palette extraction and 4.5:1 text contrast gates.
- Safe zones, readable glass surfaces, and pet-overlay isolation CSS.
- Three stylesheets, six visual-QA previews, attribution, and schemaVersion 2 metadata.

## 0.4 — Reversible Windows Runtime Beta ✅

- Exact-version adapter registry and machine-readable schema.
- AppX registry and standalone executable discovery.
- Backup, activate, monitor, verify, stop, capture, and restore lifecycle.
- Random loopback-only CDP transport with full disclosure and shutdown verification.
- Executable, adapter, package, and session continuity checks.
- No writes to `WindowsApps`, `app.asar`, signed executables, or application archives.
- Safe reconciliation of a known volatile Codex config key.
- Unit fixtures and isolated live verification; unsupported versions fail closed.

## 0.4.x — Runtime hardening

- Add adapters only after exact-version isolated live verification.
- Investigate an official packaged-app activation route without weakening AppX protections.
- Improve stale-session recovery and sanitized diagnostic export.
- Add reduced-motion controls for runtime skin effects.

## 0.5 — Cross-platform and ecosystem

- macOS runtime investigation.
- Community skin and pet gallery format.
- Signed releases and reproducible packaging.
- Accessibility and localization passes.

## 1.0 — Stable release

- Documented compatibility and migration policy.
- Stable adapters on supported official Codex distribution channels.
- Release-quality recovery tooling and automated compatibility tests.
