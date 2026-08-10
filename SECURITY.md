# Security policy

## Reporting a vulnerability

Do not publish an exploit in a public issue. Contact the maintainers through the repository owner's private channel or GitHub Security Advisories when enabled.

Include the affected version, operating system, reproduction steps, impact, and suggested mitigation. Do not attach private source images, runtime state files, screenshots, or access tokens.

## Trust boundary

Pet and skin package generation is local and does not require live application access. Windows skin activation crosses an additional boundary: it launches an Electron process with Chrome DevTools Protocol (CDP). Codex does not document a public desktop skin API, so this runtime is experimental and version-gated.

## Windows runtime threat model

### Local debugging endpoint

- CDP is unauthenticated.
- ChromaPaw binds it only to `127.0.0.1` on a random ephemeral port.
- HTTP and websocket clients reject non-loopback hosts and mismatched ports.
- The active state discloses the port.
- Restore terminates the runtime-launched Codex process and confirms the endpoint is closed.

Another process running as the same user may be able to connect while the session is active. Do not leave an activated session running on an untrusted shared Windows account.

### Background monitor

Activation starts a hidden local Python monitor that checks eligible targets once per second. It has no external network role. It compiles only the already validated package, checks adapter/browser identity at startup, and injects only when an allowed `app://` target is new or unstyled. Its PID, executable, hash, and interval are recorded and disclosed.

### Application identity

- Unknown versions and disabled adapters fail closed.
- Preflight records the absolute executable path and SHA-256 hash.
- Active state records the adapter file path and SHA-256 hash.
- Verification refuses a changed executable, changed adapter file, changed adapter id, wrong browser product, non-loopback websocket, or different process executable.
- Restore verifies process identity before terminating anything.

The executable hash is a per-session continuity check, not a claim that every allowed binary has been cryptographically published by OpenAI.

### Filesystem and configuration

- The runtime never writes `WindowsApps`, a signed executable, `app.asar`, or an application archive.
- CSS is injected in memory and removed by a session-owned marker.
- A pre-activation `config.toml` backup is recorded when the file exists.
- Codex may change `SKY_CUA_NATIVE_PIPE_DIRECTORY` while launching. ChromaPaw restores that allowlisted volatile key only if every nonvolatile line matches the backup; unrelated user edits are preserved.
- Runtime state and backups remain local under `%CODEX_HOME%\chromapaw\runtime\windows` unless the operator selects an override.

### Private content

Reference images and generated assets stay in declared local output paths unless a separately disclosed image-generation workflow uploads them. Runtime screenshots may contain task names, source paths, or conversation text and require an explicit CLI acknowledgment. Do not publish captures without user permission.

## Required invariants

ChromaPaw must:

- never weaken Windows package protections to activate a skin;
- never expose CDP beyond loopback;
- disclose every local port and background process;
- refuse activation on unknown or unverified versions;
- keep package validation separate from activation consent;
- remove only a matching session-owned style marker;
- terminate only a verified runtime-owned process tree;
- preserve unrelated user configuration changes;
- and maintain deterministic stop/restore records.

See [docs/WINDOWS_RUNTIME_BETA.md](docs/WINDOWS_RUNTIME_BETA.md) for the operating sequence.
