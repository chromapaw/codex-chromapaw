# Compatibility review — 2026-10-22

This is a dated maintenance snapshot, not an assertion that every future Codex build is compatible. GitHub Releases and the PR checks remain the source of truth for publication and CI status. The 0.4.9 changes are a maintenance candidate, not a published release.

## Verified boundaries

| Surface | Observation | Meaning |
| --- | --- | --- |
| Public ChromaPaw release | `v0.4.8`, published 2026-09-12 | Latest release at review time |
| Existing local installation | Updated from `0.4.8+codex.20260912064437` to the published `0.4.8+codex.20260912085858` snapshot | 106 distributable files matched; candidate code is not installed into the user's live profile |
| Stable Codex CLI | `0.163.0`, checked against the npm registry | Isolated installation passed on Windows |
| Previous CLI baseline | `0.144.2` | Isolated installation passed on Windows; retained in Linux CI |
| Bundled local CLI | `0.163.0-alpha.11` | v0.4.8 isolated installation passed; not a replacement for stable-CLI validation |
| Local hatch-pet | Contract version 1 passed | Dependency scripts/metadata are present; this is not fresh generation or visual-QA evidence |
| Current Windows Store app | `26.1016.6573.0`, PE `155.0.8059.80`, valid OpenAI signature | Discovery-only candidate; activation disabled |
| macOS | Existing portable tests and simulated-renderer harness | No new live-app activation claim |

The Store executable SHA-256 observed read-only is `602a21169fa011cf48997dbc07a0ffcdc11058caa5dc992e534876e8cb6f9a4e`. A matching signature/hash does not prove CSS, overlay isolation, launch ownership or restoration works. The candidate registry entry remains disabled until the full [Windows adapter acceptance](../CONTRIBUTING.md#windows-adapter-acceptance) sequence passes with explicit experimental-runtime consent.

No live application was relaunched, no CDP port was opened against the user's app, and no skin preference, managed shortcut or project/sidebar data was changed during this review. The plugin configuration was backed up locally before moving its marketplace pointer to the final immutable v0.4.8 snapshot. Private backup paths and user data are not part of the repository.

## Maintenance changes

- Test isolated installation on Linux, Windows and macOS with pinned Codex CLI `0.163.0`; retain `0.144.2` on Linux. These checks run with normal PR/push CI, not a new background schedule.
- Move the release install gate to `0.163.0`, preserving exact-tag and file-hash verification.
- Require structured plugin-list evidence for the exact plugin ID, version and boolean installed/enabled state. A different plugin or an available-but-not-installed entry cannot satisfy the check.
- Remove inherited `CHROMAPAW_HATCH_PET_DIR` only inside the isolated smoke-test environment, so a caller's external dependency does not contaminate missing-dependency verification.
- Explain why recognized Windows adapters are disabled. Keep the newly observed Store version discovery-only.

Existing dependency PRs remain separate: a newer dependency version alone does not justify merging it. No unrelated dependency PR was merged in this review.

## Validation

The pre-change release gate passed all 192 tests (191 passed, one Windows symlink-permission skip). The candidate gate passed 197 tests (196 passed, the same symlink-permission skip). Candidate installations passed with CLI `0.144.2`, `0.163.0` and the local `0.163.0-alpha.11`, each matching all 107 distributable files even when an invalid external hatch-pet override was inherited by the test process. Cross-platform PR results must also pass before release. The CLI smoke fixture checks installation and dependency discovery, not pet generation or desktop skin activation.

The previously used local plugin-creator validator is no longer installed on this host. Repository manifest/schema checks and real CLI installations passed instead; no separate plugin-creator validation result is claimed.

The current [official plugin packaging documentation](https://developers.openai.com/plugins/build/plugins) still supports `.codex-plugin/plugin.json` as a compatibility fallback. ChromaPaw retains that format because the actual stable and baseline CLI installations pass; this review does not migrate to a new manifest format or claim support for unrelated ChatGPT Work pet storage.
