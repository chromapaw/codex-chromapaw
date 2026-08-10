# Changelog

## 0.4.1 — 2026-08-10

- Add source-bound semantic theme profiles before skin scene expansion and packaging.
- Derive motifs, forbidden elements, and four depth descriptions from the current upload and user intent instead of a fixed beach example.
- Reject profile/reference SHA-256 mismatches and motif/exclusion contradictions.
- Preserve the semantic profile in Skin Studio v2 packages and structured QA.
- Add blue-sky and comic regression fixtures to prevent unrelated scene leakage.
- Add a machine-readable cross-platform capability report.
- Add a read-only macOS app-bundle discovery and package preflight probe; macOS skin activation remains disabled and unimplemented.

## 0.4.0 — 2026-08-10

- Add an experimental, reversible Windows skin runtime for exact enabled Codex versions.
- Add standalone and AppX discovery, version-gated preflight, executable hashing, and adapter-registry hashing.
- Add dependency-free loopback CDP injection, verification, removal, and private screenshot capture.
- Add a disclosed monitor that styles delayed eligible windows without modifying application files.
- Add deterministic stop/restore that terminates only verified runtime-owned processes and confirms the CDP port closed.
- Add safe restoration of an allowlisted volatile Codex config key while preserving unrelated user changes.
- Add the Windows adapter schema, threat model, operating guide, compatibility checklist, unit fixtures, and isolated live QA.
- Keep the discovered official AppX `26.803.5235.0` adapter disabled after protected-package launch was rejected by Windows.

## 0.3.0 — 2026-08-10

- Add the one-image Skin Studio request and deterministic package builder.
- Add automatic light and dark palette extraction with contrast QA.
- Add light, dark, and adaptive CSS plus pet-overlay background isolation.
- Add six real-artwork UI previews for 16:10, 16:9, and 4:3 windows.
- Add schemaVersion 2 safe-zone, depth-layer, attribution, variant, and QA metadata.
- Preserve validation compatibility for legacy schemaVersion 1 skin packages.

## 0.2.1 — 2026-08-10

- Add a Git-backed Codex marketplace for repository installation.
- Add explicit `hatch-pet` dependency preflight and remediation output.
- Add an isolated `CODEX_HOME` installation smoke test.
- Support large lossless WebP pet atlases without reading the whole image payload.
- Reject truncated RIFF/WebP containers deterministically.

## 0.2.0 — 2026-08-09

- Add the one-image desktop v2 pet workflow.
- Add pet package validation, safe installation, backup, and restore.
- Add portable layered-skin package validation.
