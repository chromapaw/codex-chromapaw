# GitHub maintainer setup

Repository files are versioned, but GitHub rules and security switches are not. Apply and re-audit this checklist after ownership, plan, or default-branch changes.

## Repository features and metadata

- Visibility: public.
- Default branch: `main`.
- Enable Issues and Discussions.
- Disable the Wiki unless it has maintained content; keep canonical documentation in the repository.
- Enable automatic deletion of merged branches.
- Prefer squash merges and use the pull-request title as the commit title.
- Keep the description and topics aligned with the current README support claims.
- Add a homepage only after a maintained documentation or showcase page exists.

## Default-branch ruleset

Create an active ruleset targeting the default branch with these protections:

- block branch deletion and non-fast-forward updates;
- require a pull request before merging;
- require all conversations to be resolved;
- require the six current CI contexts: four `CI` matrix jobs plus the Apple Silicon and Intel enhanced harness jobs;
- require the branch to be up to date before merging;
- do not allow force pushes;
- grant a narrowly scoped maintainer bypass only for repository recovery.

While there is only one maintainer, use zero required external approvals so the repository is not deadlocked. Increase this to one approval and require CODEOWNER review after a second active maintainer joins.

## Security

- Enable Dependency Graph and Dependabot alerts.
- Enable Dependabot security updates.
- Enable Secret Scanning and Push Protection. Enable validity checks and non-provider patterns when the repository's GitHub plan exposes them, and record an unavailable toggle rather than claiming it is active.
- Enable CodeQL default setup for Python and JavaScript/TypeScript; workflow YAML remains covered by the repository release gate and pinned-Action policy.
- Enable private vulnerability reporting so `SECURITY.md` and the issue-template contact link resolve to a confidential channel.
- Require organization two-factor authentication after confirming every member has enrolled.

Never enable a runtime adapter merely to make a compatibility report green. Adapter acceptance remains governed by `CONTRIBUTING.md`.

## Labels

Keep GitHub's default issue labels and add:

- `dependencies`
- `python`
- `javascript`
- `github-actions`
- `security`
- `windows`
- `macos`
- `compatibility`

The first four are referenced by `.github/dependabot.yml`.

## Release

1. Merge a clean candidate whose public manifest version has a matching dated section in `CHANGELOG.md`.
2. Wait for all required checks on `main`.
3. Create and push an annotated `v<version>` tag; sign it when a maintainer signing identity is available.
4. Let the Release workflow validate the tag, smoke-install the plugin, build deterministic archives, generate an SPDX SBOM and SHA-256 checksums, and publish the GitHub release.
5. Verify a clean GitHub marketplace installation from the published tag.

Do not create a release manually when the automated workflow is failing.

## Quarterly audit

Review repository community health, rulesets, security settings, Actions permissions, pinned Action commits, inactive maintainers, open vulnerability alerts, release signatures, and the support matrix at least once per quarter and before a stable release.
