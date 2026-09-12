# ChromaPaw 0.4.8 candidate

Prepared on 2026-09-12. Public release is pending; this document records local validation, not a completed GitHub release.

## Changes

- Package the signed Store adapters, language readback, bounded CDP retries, official startup fallback, and durable next-launch skin/sidebar recovery implemented since 0.4.7.
- Update the plugin manifest, current-version documentation, roadmap and management skill together. Use one fresh `+codex.<timestamp>` suffix to avoid reusing a stale plugin cache.
- Compare installed files with the selected marketplace snapshot using SHA-256, including new recovery modules. Missing, unexpected or changed distributable files fail installation verification even when version strings match.
- Exclude local dependencies, Python caches, build output, logs and private artifacts from local marketplace staging.

## Local validation

- `python scripts/release_check.py`: passed; 192 tests, 191 passed and one symlink test skipped because symlink creation is unavailable on this Windows host.
- Codex plugin validator: passed.
- Codex skill validator: all three skills passed with `python -X utf8` on the Windows host.
- `python scripts/smoke_test_install.py --source . --ref= --json`: passed; isolated installation, exact version and file content verified, missing/compatible hatch-pet dependency behavior checked with the explicit test fixture.
- `git diff --check`: passed.

The installation fixture proves package and dependency discovery, not fresh pet generation or live skin activation.

## Compatibility at preparation time

Read-only discovery found official Store Codex `26.903.9818.0`. It has no reviewed adapter in this candidate and live skin activation remains disabled for that build. Historical acceptance records for `26.901.1978.0`, `26.901.2854.0` and `26.901.5003.0` do not establish compatibility with the new build. Existing reviewed runtime generations remain independently pinned across plugin updates.

## GitHub handoff

1. Review and include all new recovery modules, tests and management references when committing; they were previously untracked development files.
2. Push a candidate branch and open a PR targeting `main`.
3. Require Linux Python 3.10/3.12, Windows, macOS, Apple Silicon/Intel enhanced harness and CodeQL checks under the repository ruleset.
4. Run the isolated GitHub installation test against that exact candidate branch.
5. Complete [the release checklist](RELEASE_CHECKLIST.md), squash merge the approved PR, and create an annotated `v0.4.8` tag on a commit reachable from `main`.
6. Verify the Release workflow assets and re-run installation against `v0.4.8` before calling the public release complete.

For future maintenance, keep the Git checkout as the source of truth. Plugin-cache directories and local release snapshots are build/install outputs.
