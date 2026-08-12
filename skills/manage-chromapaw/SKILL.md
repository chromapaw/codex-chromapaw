---
name: manage-chromapaw
description: Inspect, validate, preview, activate, resume, verify, stop, remove, or restore ChromaPaw skin and pet customizations. Use when a user asks what ChromaPaw assets are installed, wants to activate or persist a supported Windows skin, return to the official Codex appearance, recover from a broken customization, or understand runtime compatibility and safety.
---

# Manage ChromaPaw

Manage customization state while treating package creation, pet installation, and experimental skin activation as separate operations.

## Required safety model

Read [references/safety-model.md](references/safety-model.md) completely before any activate, resume, shortcut install, stop, restore, replace, or remove operation. Tell the user whenever this safety model causes an operation to pause or fail closed.

## Choose the operation

- **Inspect:** list package metadata, resolved paths, validation state, and runtime compatibility without changing state.
- **Validate:** run `scripts/validate_skin_package.py` for skins or `scripts/validate_pet_package.py` for desktop v2 pets and report every failure.
- **Preview:** display package previews without activating the skin.
- **Activate skin:** use the Windows Runtime Beta only after the exact-version gates and explicit acknowledgment below pass.
- **Resume skin:** relaunch the last successfully activated Windows skin only after all saved package, executable, version, CSS, and adapter identities still match.
- **Install persistent entries:** after separate consent, confirm the original Start Menu target and add distinctly named, semantic-ownership-hashed ChromaPaw Desktop and Start Menu launchers without modifying the original entry.
- **Probe macOS:** use `scripts/macos_compat.py` only to collect read-only app metadata and package compatibility. There is no macOS activation command yet.
- **Install or restore pet:** use `scripts/install_pet.py` or `scripts/restore_pet.py`; replacement must remain explicit and backup-backed.
- **Stop or restore skin:** use the active runtime state. Never reconstruct session identifiers, ports, process ids, or backup paths from guesses.
- **Remove:** delete only the selected ChromaPaw asset after confirming its resolved path remains inside the declared root.

## Windows Runtime Beta workflow

The runtime is Windows-only and experimental. It is not an official OpenAI skin API. It must not patch `WindowsApps`, `app.asar`, signed application files, or Codex UI source files.

### 1. Discover and preflight

From the plugin root, run:

```bash
python scripts/windows_runtime.py --json discover
python scripts/windows_runtime.py --json preflight <skin-package> --executable <ChatGPT.exe>
```

Show the user the selected absolute executable path, Codex version, adapter id, `activationEnabled`, executable hash, any running PIDs, skin package id, and the disclosed transport/monitor behavior.

Stop when:

- the version is unknown;
- the adapter is recognized but activation is disabled;
- package validation fails;
- the pet-overlay isolation guard is missing;
- the executable is inside an unsupported installation route;
- or the user has not explicitly requested live activation.

### 2. Prepare activation

Ask the user to close every window belonging to the selected executable. Do not terminate their existing Codex process automatically.

Explain that activation will:

- create a backup and state record under the ChromaPaw runtime data directory;
- launch a Codex process owned by ChromaPaw;
- open an unauthenticated random CDP port bound only to `127.0.0.1`;
- run a hidden local Python monitor once per second so delayed Codex windows receive the skin;
- and stop that launched Codex process during restore so the port closes.

Only proceed after the user explicitly accepts this experimental behavior. The CLI independently enforces `--acknowledge-experimental-runtime`.

### 3. Activate and verify

```bash
python scripts/windows_runtime.py --json activate <skin-package> --executable <ChatGPT.exe> --acknowledge-experimental-runtime
python scripts/windows_runtime.py --json verify
```

Require `verify` to report:

- the recorded executable and monitor processes still match;
- the endpoint is loopback and the adapter/browser identity passes;
- every eligible `app://` target has the expected CSS hash and session marker;
- and both main and avatar-overlay targets match when both exist.

The monitor should repair a delayed unstyled target automatically. Use `verify --repair` only as an explicit diagnostic; if the package hash changed, restore and activate again.

For a reviewed CSS-only runtime repair while the same skin session is active, require explicit acknowledgement and hot-refresh without closing Codex:

```bash
python scripts/windows_runtime.py --json refresh-active-css --acknowledge-runtime-update
```

Use this only when immutable package, executable, app-version, and adapter continuity must remain unchanged. If the command reports an identity change, stop and require a new reviewed activation. The command restarts only ChromaPaw's local CSS monitor.

A successful activation writes `preferred-skin.json` with restart-safe identities and hashes. It must not persist the session token, CDP port, target ids, titles, or conversation content.

Never use `--allow-parallel-profile` for ordinary activation. It exists only for an isolated compatibility fixture with a separate `--profile-dir`.

### 4. Resume and optional persistent shortcut

After the user closes the runtime-launched Codex, resume the last successfully activated skin with:

```bash
python scripts/windows_runtime.py --json resume --acknowledge-experimental-runtime
```

Resume must recover only a stale ended session and then re-run the exact package, executable, CSS, app-version, adapter-id, and adapter-file hash gates. Refuse resume when an ordinary instance of the selected executable is already running or any continuity check changed.

The normal application-managed ChatGPT shortcut does not include the experimental runtime arguments and may be recreated by Codex. Never replace it. Installing separate `Codex ChromaPaw.lnk` Desktop and Start Menu entries is a state-changing operation. Display both managed shortcut paths plus the original path, the target executable, launcher, and absence of login/background auto-start behavior. Proceed only after the user explicitly agrees to add the shortcuts:

```bash
python scripts/windows_shortcut.py --json install --executable <ChatGPT.exe> --acknowledge-adds-windows-shortcuts
```

Require the installer to verify the original target and both new entries' targets, arguments, working directories, icons, descriptions, and semantic ownership hashes. Windows may rewrite `.lnk` binary tracking data after a click, so whole-file hashes are informational only. To remove both ChromaPaw entries:

```bash
python scripts/windows_shortcut.py --json restore
```

Never overwrite the original application shortcut. Remove the separate ChromaPaw entries only when both semantic receipt ownership hashes still match.

### 5. Inspect and capture

```bash
python scripts/windows_runtime.py --json status
```

Screenshots may expose task names, source paths, or conversation content. Capture only after explicit acknowledgment:

```bash
python scripts/windows_runtime.py --json capture --output <private-output.png> --acknowledge-screenshot-may-contain-private-content
```

Do not publish a live capture without separate user permission.

### 6. Stop or restore

```bash
python scripts/windows_runtime.py --json restore
```

`stop` and `restore` both remove session-owned CSS, stop the disclosed monitor, terminate only the runtime-launched Codex process tree after verifying its executable identity, and confirm that the CDP port closed. `restore` is the default user-facing recovery operation.

Report whether the original Codex config hash was restored. The runtime may restore only allowlisted volatile app-session keys when every other configuration line is unchanged; it must preserve unrelated user changes.

After restore, the user may launch Codex normally without the debugging arguments. Restoring the active runtime does not remove the optional ChromaPaw shortcut; remove it separately when the user no longer wants that additional launcher.

## Current compatibility

Version `0.4.5` enables Windows activation and resume only for exact entries marked `activationEnabled: true` in `runtime/windows-adapters.json`. The locally discovered official AppX `26.803.5235.0` remains disabled because protected package execution rejected the required isolated runtime launch. The separate persistent shortcuts are Windows-only. On macOS, `scripts/macos_compat.py` is probe-only and cannot activate a skin. Discovery does not imply activation support.
