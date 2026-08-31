## Summary

Describe the user-visible outcome and why the change is needed.

## Scope

- [ ] Skin generation or validation
- [ ] Pet generation, installation, or validation
- [ ] Windows experimental runtime
- [ ] macOS compatibility probe or harness
- [ ] Documentation, community, or release automation

## Verification

- [ ] `python scripts/release_check.py`
- [ ] `python scripts/check_dependencies.py --json`
- [ ] Relevant package validators and platform checks
- [ ] Sanitized before/after previews are attached when visual behavior changes
- [ ] Exact live-tested Codex versions and unsupported paths are documented

## Safety and privacy

- [ ] This change does not modify `WindowsApps`, signed executables, `.app` bundles, or `app.asar`
- [ ] New permissions, ports, background processes, network calls, and recovery behavior are disclosed
- [ ] No private images, task content, tokens, runtime state, or unlicensed assets are committed
- [ ] Activation, installation, replacement, and destructive actions remain separately confirmed

## Release note

Add a concise entry under the single `Unreleased` section in `CHANGELOG.md`, or explain why none is needed.
