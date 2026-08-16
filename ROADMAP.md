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

## 0.4.1 — Semantic profiles and macOS probe ✅

- Bind every skin theme profile to the current upload's SHA-256.
- Derive scene motifs and exclusions dynamically from the upload and user request.
- Add non-beach semantic regression fixtures.
- Report generation, pet-dependency, and activation readiness separately.
- Discover macOS app bundles and collect read-only preflight evidence without implementing activation.

## 0.4.5 — Release-candidate hardening ✅

- Persist the last validated Windows skin through separate Desktop and Start Menu launchers.
- Host and verify the shortcut runtime outside the replaceable plugin cache.
- Keep the application-managed shortcut untouched and verify semantic ownership before removal.
- Add cross-platform CI and one-command release checks.
- Detect legacy and invalid installed pets without silently deleting or replacing them.
- Install and safely select pets with TOML validation, backups, and concurrency-safe rollback.
- Maintain deterministic input-shape coverage plus a real-image release regression matrix.
- Require a clean GitHub installation smoke test before the public tag is considered verified.

## 0.4.6 — Generation and runtime safety hardening ✅

- Make generation-to-install/application handoffs explicit and machine-readable.
- Validate pet selection as TOML with backup, locking, and concurrency-aware rollback.
- Bind Windows executables to verified PE identity and pin hosted shortcut runtime bundles.
- Make Windows status and CSS updates continuity-aware and compensating on failure.
- Validate schemas, external workflow contracts, and isolated installation in the release gate.

## 0.4.7 — Adaptive layout and open-source readiness (release candidate)

- Decide conversation width from subject role and display priority instead of subject position alone.
- Keep supporting scenery at the default Codex width and reserve space only for a side-staged showcase subject.
- Protect the current Codex header and system menu with image-derived, contrast-checked surfaces and controls.
- Make reviewed CSS monitor updates wait for the matching transactional state handoff.
- Add complete community, support, issue, ownership, dependency, security, and release automation surfaces.
- Pin GitHub Actions to reviewed commits and publish archives, checksums, and an SPDX SBOM from validated tags.

## 0.4.x — Runtime hardening

- Add adapters only after exact-version isolated live verification.
- Investigate an official packaged-app activation route without weakening AppX protections.
- Improve stale-session recovery and sanitized diagnostic export.
- Add reduced-motion controls for runtime skin effects.

## 0.5 — Cross-platform and ecosystem

- Run package generation, pet lifecycle, bundle probe, and simulated-renderer screenshot gates on Apple Silicon and Intel GitHub-hosted macOS runners.
- Real-Mac validation against an installed Codex app for skin generation and pet install/restore.
- Reversible exact-version macOS skin runtime investigation and implementation.
- Community skin and pet gallery format.
- Signed releases and reproducible packaging.
- Accessibility and localization passes.

## 1.0 — Stable release

- Documented compatibility and migration policy.
- Stable adapters on supported official Codex distribution channels.
- Release-quality recovery tooling and automated compatibility tests.
