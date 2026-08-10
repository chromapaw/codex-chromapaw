# Contributing

Thank you for helping make Codex customization safer and more approachable.

## Before opening a change

1. Search existing issues and discussions.
2. Keep pet generation, skin generation, and live activation concerns separated.
3. Do not add code that modifies `WindowsApps`, signed executables, or `app.asar`.
4. Do not commit copyrighted or private images without clear redistribution permission.
5. Document every new permission, network interface, background process, local port, or recovery behavior.

## Development checks

```bash
python -m py_compile scripts/*.py
python -m unittest discover -s tests -v
python scripts/check_dependencies.py --json
```

Before release, validate the plugin and all skills with the scripts bundled with Codex's `plugin-creator` and `skill-creator` skills. Run the isolated marketplace installation smoke test after pushing the candidate commit.

## Windows adapter acceptance

Keep a candidate adapter's `activationEnabled` value false until all checks pass on its exact four-part Codex version:

1. Discovery returns the correct absolute executable and version.
2. Preflight validates the skin and records executable/adapter/package hashes.
3. Activation uses an empty `--profile-dir` compatibility fixture and a random loopback port.
4. Main and avatar-overlay targets receive matching CSS/session markers, including a delayed target repaired by the monitor or deterministic fixture test.
5. A real screenshot confirms the theme renders and the avatar overlay remains transparent.
6. `verify` passes without repair.
7. `restore` removes the styles, stops the monitor and only the runtime-launched process tree, closes the port, and preserves the original Codex process.
8. The post-restore config hash matches its backup, or unrelated user changes are explicitly preserved without overwrite.
9. Unit tests cover unknown-version failure, disabled activation, adapter validation, CDP lifecycle, monitor repair, and config reconciliation.

Never enable an AppX adapter by bypassing protected-package execution. Record a failed launch as evidence and leave activation disabled.

## macOS adapter acceptance

The macOS registry remains probe-only until an implementation exists. Fixture tests can validate metadata parsing but do not count as live support. Before any macOS activation field or command is introduced:

1. Collect a sanitized discovery/preflight report from an actual Mac and exact official Codex build.
2. Document bundle identity, executable, Electron layout, code-signing behavior, launch model, and all temporary state.
3. Design a reversible path that does not patch the signed `.app` bundle or `app.asar`.
4. Verify the main window and transparent pet overlay on the real build.
5. Verify complete restoration and closure of any temporary process or port.
6. Keep the new adapter disabled until exact-version tests and manual visual evidence pass.

Do not infer macOS live support from portable Python code, a synthetic `.app` fixture, or successful package generation.

## Pull requests

- Keep changes focused and explain user-visible behavior.
- Include tests for deterministic scripts and schemas.
- Include sanitized before/after previews for visual changes; never embed private live captures.
- Preserve a complete restore path for activation-related changes.
- State which exact Codex versions were live-tested and which remain discovery-only.

## Commit style

Use concise imperative subjects, for example:

- `Add version-gated Windows runtime`
- `Document Windows recovery flow`
- `Fix pet atlas metadata validation`
