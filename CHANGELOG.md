# Changelog

## 0.4.5 — 2026-08-11

- Add a visible `Codex ChromaPaw.lnk` Desktop launcher alongside the Start Menu entry.
- Migrate existing version 0.4.4 Start Menu-only receipts to the dual-shortcut receipt without touching `ChatGPT.lnk`.
- Validate semantic ownership of both managed entries before restore and roll back a partial removal if Windows rejects either operation.
- Resolve the Windows known Desktop folder so redirected and OneDrive-backed desktops receive the launcher.
- Add cross-platform GitHub Actions and a reproducible repository release-check command.
- Add a read-only installed-pet audit that distinguishes valid v2, legacy v1, and invalid packages.
- Add deterministic coverage for landscape, portrait, ultrawide, transparent, dark, and light skin inputs.
- Document the real-image regression matrix, clean-install smoke test, and platform-claim gates required before publication.
- Let the isolated installation smoke test stage and install the current local worktree without cloning an older remote revision.

## 0.4.4 — 2026-08-10

- Keep the application-managed `ChatGPT.lnk` untouched and add a separate `Codex ChromaPaw.lnk` entry instead.
- Replace unstable whole-file `.lnk` hashes with semantic ownership hashes over target, arguments, working directory, icon, and description.
- Detect when Codex has already recreated its original shortcut and safely finalize legacy replacement receipts.
- Remove only the separately managed ChromaPaw shortcut during restore; never overwrite the original application entry.
- Add regression coverage for Windows tracking-data rewrites that change `.lnk` bytes without changing its behavior.

## 0.4.3 — 2026-08-10

- Remember the last successfully activated Windows skin without persisting session tokens, ports, or private page data.
- Add `windows_runtime.py resume` to recover a stale closed session, recheck executable/package/adapter continuity, and relaunch the selected skin.
- Add a quiet Windows launcher with local success/failure logging and a visible error dialog when fail-closed checks reject relaunch.
- Add an explicit, backup-backed Start Menu shortcut installer and deterministic restore command.
- Refuse shortcut replacement when the original target, installed shortcut ownership hash, or backup hash cannot be proven.
- Add Windows lifecycle and temporary `.lnk` integration regression tests.

## 0.4.2 — 2026-08-10

- Derive contrast-safe semantic UI colors independently for light and dark skin variants.
- Override Codex and VS Code menu, title bar, sidebar, editor, input, list, toolbar, and terminal color tokens instead of relying on the host theme's stale foreground colors.
- Raise or lower uploaded-image accent colors when necessary to maintain at least WCAG 4.5:1 text contrast.
- Add elevated-surface and input-surface roles so navigation and controls stay legible without flattening the artwork.
- Validate primary, secondary, muted, and accent text contrast in generated Skin Studio QA reports.
- Add regression tests for semantic token emission and light/dark accessibility gates.

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
