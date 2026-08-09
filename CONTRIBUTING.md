# Contributing

Thank you for helping make Codex customization safer and more approachable.

## Before opening a change

1. Search existing issues and discussions.
2. Keep pet generation, skin generation, and live activation concerns separated.
3. Do not add code that modifies the official Codex installation archive.
4. Do not commit copyrighted images unless their redistribution terms are clear.

## Development checks

```bash
python -m unittest discover -s tests -v
```

Before release, also validate the plugin and each skill using the validator scripts bundled with Codex's `plugin-creator` and `skill-creator` skills.

## Pull requests

- Keep changes focused and explain user-visible behavior.
- Include tests for deterministic scripts and schemas.
- Include before/after previews for visual changes without embedding private source images.
- Document new permissions, network calls, background processes, or local ports.
- Preserve a complete restore path for activation-related changes.

## Commit style

Use concise imperative subjects, for example:

- `Add skin package validator`
- `Document Windows recovery flow`
- `Fix pet atlas metadata validation`
