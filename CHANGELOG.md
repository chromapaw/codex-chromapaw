# Changelog

## Unreleased

## 0.4.8 — 2026-09-12

- Verify installed plugin files against the selected marketplace snapshot by SHA-256, rejecting missing modules and stale same-version content; exclude local dependency, cache, and artifact directories from installation staging.
- Update management guidance for reviewed next-launch activation, official Store launcher recovery, and project-sidebar repair, keeping upgrades separate from live runtime activation.

- Add the signed Store Codex `26.901.5003.0` Windows adapter after isolated Kyoto skin, main/avatar transparency, Chinese locale, menu contrast, project-list visibility and process-cleanup checks. Bind it to its exact executable hash so an older saved version can be replaced through reviewed next-launch activation.
- Repair project-sidebar indexes through a durable, one-shot next-launch request: pin the current signed official Codex and app-server CLI plus existing project identities, refuse writes while any Codex window is open, back up the shared state/database during repair, and consume the request only after the project list verifies. This prevents an older compatibility launcher from erasing the index again during shutdown.
- Persist explicitly reviewed Windows skin activation as a hash-pinned next-launch request. The managed launcher prioritizes it over a removed Store version, revalidates every identity before activation, and consumes it only after live verification; cancelled or failed launches retain the request without relying on an in-app background handoff surviving shutdown.
- Support the exact signed Store build `26.901.2854.0` after isolated main/avatar, locale, visual contrast, repair, and cleanup verification. Protect the modern application menubar using its semantic shell relationship, including previously generated skin packages; reject AppX activation that returns a pre-existing process before acquiring runtime ownership.
- Repair the Codex desktop project-sidebar migration gap through the current signed build's own `project/import` protocol: detect legacy saved workspace roots, create a consistent state-database/global-state backup, import only matching thread ids, and verify the resulting projects without copying authentication data or conversation text.
- Recover ordinary Codex startup after Store updates remove a pinned version directory: verify the registered Store package family, publisher, manifest, and OpenAI executable signature before invoking its stable AppX identity, without CDP or skin injection. Embed this recovery in the stable bootstrap so old pinned runtimes can recover too, and add transactional `repair-launcher` without changing the saved skin pin or application-managed shortcuts.
- Isolate Windows PowerShell's inbox module path from inherited PowerShell 7 module paths during AppX and Authenticode checks.
- Mirror Codex's `[desktop].localeOverride` through Electron's supported `--lang` switch, verify the main renderer's effective language, and reject false-success activation when it still differs. Add an exact signed AppX `26.901.1978.0` adapter using Windows' packaged-app activation manager after isolated zh-CN, main/avatar CSS, monitor, identity, and restore checks passed; retain the older incompatible AppX record as disabled.
- Retry transient CDP WebSocket timeouts during first-run AppX initialization instead of treating a recoverable target delay as a terminal activation failure. Bound post-launch CSS/locale readback retries to three attempts; persistent timeouts, identity errors and contrast-independent style/locale mismatches still fail verification.
- Launch verified AppX fallback sessions through Windows' packaged-app activation manager, preserve the configured locale there too, and allow shortcut installation when packaged Codex exposes a StartApps identity but no filesystem `ChatGPT.lnk`.
- Recover an ended Windows skin session when its recorded monitor or Codex PID has been recycled, without terminating or attaching to the unrelated replacement process; archive only the stale ChromaPaw state before starting the reviewed skin again.
- Protect unframed landing and empty-state copy with compact image-derived reading carriers instead of increasing the full main-viewport wash, preserving scene depth while keeping uploaded dark or bright artwork readable.
- Measure main-window text contrast against actual rendered screenshot pixels in the macOS compatibility harness, and decode renderer subprocess output as UTF-8 on legacy-code-page Windows test hosts.
- Retry content-addressed Windows shortcut runtime publication across bounded transient antivirus or indexer directory locks while preserving immutable-generation verification and fail-closed errors.

## 0.4.7 — 2026-08-25

- Resolve the repository plugin from the selected marketplace snapshot instead of a nested `main` checkout, and make clean-install smoke tests fail when the installed version differs from the requested branch or tag.
- Install a pinned, tested Codex CLI in release validation, verify the resolved tag for both push and manual-dispatch releases, and keep the committed npm lockfile on the official npm registry for reproducible public CI.
- Decouple subject position from conversation width with image- and intent-aware `subjectDisplayPriority` plus automatic `contentLayout` resolution; ambient/supporting scenery keeps normal Codex width, while only a side-staged showcase subject reserves space.
- Record the resolved layout decision in package metadata and structured QA, and render previews with the same default-width or reserved-width policy used by runtime CSS.
- Prevent the Windows CSS monitor from rejecting a legitimate hot refresh when it starts before the new reviewed CSS hash has been transactionally committed; the monitor now pins the expected hash and waits for the matching state handoff without weakening ordinary startup checks.
- Give Codex's current Electron application header an image-derived glass surface with independently contrast-checked menu, navigation, and window-control colors, and render it in all Skin Studio previews.
- Preserve structured runtime results as UTF-8 when hidden Windows handoff processes inherit a legacy console encoding, preventing a successful restore from being misreported as a launcher failure.
- Pin every reviewed Windows skin preference to the exact content-addressed hosted runtime generation used by its shortcut, so later plugin or adapter updates cannot invalidate a previously approved relaunch.
- Keep the technical failure details in the local launcher log while opening the hash-verified ordinary Codex executable when skin recovery cannot start, instead of blocking users with adapter or CSS hash dialogs.
- Preserve the pinned generation during shortcut upgrades and retain prior immutable generations for reviewed-skin continuity.
- Decouple compiled skin identity from launcher-only runtime versions, preventing a code-only update from looking like a user skin edit.
- Add a complete GitHub community surface with conduct, support, issue, compatibility, pull-request, ownership, and dependency-update policies.
- Pin every third-party GitHub Action to a reviewed commit and add a tag-gated release workflow that validates, smoke-installs, archives, inventories, checksums, and publishes the plugin.
- Add repository health badges, an honest beta boundary, and a one-image workflow diagram to the project landing page.

## 0.4.6 — 2026-08-13

- Recompute the hosted shortcut runtime's canonical bundle identity at every launch, reject coherent file-plus-manifest tampering, linked or unlisted files, and bind the result to both the current pointer and content-addressed generation name.
- Replace crash-persistent runtime sentinel locks with OS-owned advisory locks, bind new process ownership to Windows creation time, deepen status continuity checks, and make active CSS refresh compensating across CSS, monitor, state, and saved preference writes.
- Validate pet-selection edits as TOML before and after writing, and fail closed on dotted or quoted equivalent declarations instead of risking duplicate tables or keys.
- Make failed pet selection rollback concurrency-safe by preserving an install that changed after placement instead of deleting another process's update.
- Verify JSON Schema contracts in the release gate and report skin generation as not ready when Pillow is unavailable.
- Make the hosted Windows shortcut bootstrap revalidate its generation manifest and every content hash at launch, and roll back shortcut and pointer writes when receipt persistence fails.
- Bound the enhanced macOS renderer subprocess so a stalled browser fails with a clear timeout instead of hanging CI indefinitely.
- Offer the Windows skin-application handoff only when discovery finds an enabled exact-version adapter; incompatible and undiscovered Windows builds now remain preview-only instead of receiving a misleading confirmation phrase.
- Add an explicit install-and-select pet flow that backs up `config.toml`, preserves unrelated settings, rejects ambiguous desktop selection keys, rolls back a new package when selection fails, and reports whether reopening Codex may be required.
- Split deterministic skin packaging from host image-generation availability in the machine-readable capability report and include safe-zone subject conflicts in the scene-generation requirement.
- Replace the four-file `hatch-pet` shape check with a machine-readable compatibility contract covering skill metadata and all preparation, assembly, direction, visual, blind-review, continuity, preview, and validation scripts; empty or invalid Python helpers now fail closed.
- Bind every Windows adapter to verified PE product metadata, Authenticode policy, and either an allowlisted executable hash or exact signed file version so a renamed executable in a version-shaped directory cannot pass preflight.
- Host the Windows shortcut launcher, runtime module closure, and adapter registry in a content-addressed stable runtime directory so plugin cache upgrades or removal no longer leave Desktop and Start Menu entries pointing at vanished files.
- Declare the repository-validator PyYAML dependency explicitly and validate skill/agent YAML in the release gate so malformed plugin metadata fails CI on a clean development environment.
- Replace the 66% full-window scene wash with an 8% edge treatment, crisp scene saturation/contrast, and directional local reading protection so uploaded subjects stay vivid and dimensional.
- Recompose complete-environment uploads when a face, character, logo, or hero object conflicts with Codex's reading/input safe zone; stage the subject left or right instead of blurring or fading it.
- Record subject placement, recomposition state, local-surface protection, and the bounded global wash in generated package metadata and QA.
- Add a deterministic post-generation handoff for skins and pets that reports `generated-not-active` or `generated-not-installed`, tells the user the exact next confirmation phrase, and never treats generation as activation or installation consent.
- Preserve Codex's pet sprite background while isolating the transparent avatar overlay from skin backgrounds.
- Derive an accessible pet notification surface, title, body, and control palette from every uploaded image instead of mixing host material backgrounds with skin text tokens.
- Bind Codex's right-side task and settings panel to image-derived surface and text roles so nested host-theme scopes cannot create light-on-light or dark-on-dark controls.
- Add an acknowledged `refresh-active-css` repair path that updates the same reviewed skin in place, rechecks immutable runtime identity, and restarts only the local CSS monitor without closing Codex.
- Add regression coverage preventing generated skin CSS from clearing `.codex-avatar-root` with a background shorthand.
- Add an Apple Silicon and Intel macOS enhanced compatibility harness that builds a real skin, exercises the pet filesystem lifecycle, probes an Electron-shaped app bundle, verifies right-panel and transparent-overlay rendering, and uploads screenshot evidence without claiming live Codex activation.
- Add palette-matched local reading surfaces so primary content remains readable over arbitrary bright or dark uploaded artwork without flattening the complete scene.

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
