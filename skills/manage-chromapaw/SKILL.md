---
name: manage-chromapaw
description: Inspect, validate, preview, switch, remove, or restore ChromaPaw skin and pet customizations. Use when a user asks what ChromaPaw assets are installed, wants to verify a package, activate a supported skin, return to the official Codex appearance, recover from a broken customization, or understand runtime compatibility and safety.
---

# Manage ChromaPaw

Manage customization state without assuming that a live skin runtime is installed or compatible.

## Operation selection

- **Inspect:** list package metadata, paths, validation state, and runtime compatibility without changing anything.
- **Validate:** run `scripts/validate_skin_package.py` for skins or `scripts/validate_pet_package.py` for desktop v2 pets and report every failure.
- **Preview:** open or display the package preview without activating it.
- **Activate:** proceed only when a supported, version-gated runtime is present and the user explicitly requested activation.
- **Restore:** for pets, inspect a package under `pets/.chromapaw-backups/` and use `scripts/restore_pet.py`; for skins, use a verified backup created by the same runtime. Never reconstruct unknown user settings from guesses.
- **Remove:** delete only the selected ChromaPaw asset after confirming the resolved target path.

## Required safety model

Read [references/safety-model.md](references/safety-model.md) before any activate, restore, or remove operation.

Version `0.3.x` includes a validated desktop-pet install, backup, and restore path plus portable Skin Studio v2 generation and visual QA. It still does not include a production live-skin runtime. If skin activation is requested without a supported runtime, stop after validation and preview, then explain the missing component.
