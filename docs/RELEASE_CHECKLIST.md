# Release checklist

Use this checklist for every public ChromaPaw release. Unit tests establish deterministic package safety; they do not replace real Codex installation and visual review.

## Automated gates

- Run `python scripts/release_check.py` on Python 3.10 and 3.12.
- Require GitHub Actions to pass on Windows, macOS, and Linux.
- Require the enhanced Apple Silicon and Intel macOS harness to publish nonblank main-window and transparent-overlay screenshots plus a passing JSON report.
- Validate the plugin with Codex's `plugin-creator` validator.
- Validate all three skills with Codex's `skill-creator` validator.
- Run `python scripts/audit_pets.py --json --allow-issues` and review every legacy or invalid package.
- Validate the candidate skin package and pet package with their dedicated validators.

## One-image regression matrix

Use redistributable or private local references; never commit private source images. For every candidate release, exercise at least one image in each applicable category:

| Category | Skin expectation | Pet expectation |
| --- | --- | --- |
| Full landscape/environment | Preserve the scene directly | Ask before inventing a subject |
| Portrait or character | Expand an environment from the subject | Preserve identity across all rows |
| Mascot or object | Expand scene-specific surroundings | Keep one compact readable silhouette |
| Logo or brand cue | Create motif-safe scenery without copying text | Create a mascot-safe interpretation |
| Comic or illustration | Preserve panels, ink, and style | Preserve line and color identity |
| Abstract or texture | Build an environment from its own motifs | Ask before inventing a pet |
| Transparent PNG | Flatten safely for skin; isolate pet transparency | Produce no rectangular background |
| Dark image | Keep menus, navigation, editor, and input text readable | Preserve dark details at pet size |
| Light image | Keep low-contrast host text from disappearing | Preserve outline readability |
| Right task/settings panel | Match the generated surface and primary/secondary text roles | No light-on-light or dark-on-dark panel content |
| Portrait, square, ultrawide | Pass all six preview ratios without critical cropping | Fit every used cell without clipping |
| Low-resolution image | Disclose likely quality limits | Ask for a clearer reference when identity is ambiguous |
| Text-heavy or screenshot | Keep text out of generated motifs unless requested | Reject UI/text as detached pet content |

For skins, visually inspect light and dark 16:10 plus 16:9 and 4:3 edge cases. With a pet enabled, also verify the notification card title, body, and controls against both light and dark image-derived surfaces while preserving the transparent pet sprite. For pets, require the complete hatch-pet contact sheet, motion previews, 16 direction semantics, blind direction result, continuity report, and v2 validation.

## Clean-environment installation

Before pushing, verify that the current worktree can be installed from a temporary local marketplace:

```bash
python scripts/smoke_test_install.py --source . --ref= --json
```

1. Push the candidate commit to GitHub.
2. Create a new isolated `CODEX_HOME` outside a temporary-directory root that Codex refuses for helper binaries.
3. Add the `chromapaw/codex-chromapaw` marketplace and install `codex-chromapaw@chromapaw`.
4. Confirm `codex plugin list` reports the plugin as installed and enabled.
5. Start a new Codex task and verify that natural-language pet and skin requests route to the expected skills.
6. Generate and validate one pet and one skin from fresh references.
7. On an enabled Windows adapter, activate the skin, close Codex, relaunch from both ChromaPaw shortcuts, and restore.
8. Confirm the ordinary application shortcut still opens the default appearance.

## Platform claims

- Claim Windows activation only for exact adapter versions that passed the live checklist in `CONTRIBUTING.md`.
- Do not infer official AppX support from a standalone-copy result.
- Keep macOS activation unsupported until an actual Mac passes the documented adapter acceptance process.
- Treat the enhanced cloud harness as simulated-renderer evidence, not as proof that the signed Codex application was activated.
- Keep package generation separate from activation claims on unsupported builds.

## Publication

- Ensure the worktree is clean and `CHANGELOG.md` matches the manifest's release version; local `+codex.<cachebuster>` build metadata does not create a separate public release.
- Tag `v<manifest-version>` only after the candidate commit passes CI.
- Publish release notes that name exact live-tested Codex versions and all known unsupported routes.
- Re-run the isolated GitHub installation smoke test against the published tag.
