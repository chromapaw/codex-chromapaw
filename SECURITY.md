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
- Verification refuses a changed executable, changed adapter file, changed adapter id, wrong browser product, non-loopback websocket, or different process identity.
- New sessions bind each owned PID to its executable path, executable hash, and Windows process creation FILETIME so PID reuse at the same path cannot authorize termination. Older active sessions remain recoverable through the prior exact-path and hash checks.
- Runtime mutations use an operating-system-owned advisory lock that is automatically released after an owner crash.
- Hot CSS refresh snapshots the currently owned style and treats CSS, monitor replacement, active state, and saved preference as one compensating transaction.
- Restore verifies process identity before terminating anything.

The executable hash is a per-session continuity check, not a claim that every allowed binary has been cryptographically published by OpenAI.

### Filesystem and configuration

- The runtime never writes `WindowsApps`, a signed executable, `app.asar`, or an application archive.
- The relaunch preference contains package, executable, adapter, version, and hash identities only; it excludes session tokens, CDP ports, task titles, and conversation content.
- Desktop and Start Menu integration is never implicit. It requires a separate acknowledgment, leaves the application-managed `.lnk` untouched, adds distinctly named ChromaPaw entries, and uses semantic ownership hashes so Windows tracking-data rewrites do not weaken verification.
- The launcher starts only on shortcut invocation. ChromaPaw does not install a login task, registry auto-run entry, or always-on process watcher.
- CSS is injected in memory and removed by a session-owned marker.
- A pre-activation `config.toml` backup is recorded when the file exists.
- Codex may change `SKY_CUA_NATIVE_PIPE_DIRECTORY` while launching. ChromaPaw restores that allowlisted volatile key only if every nonvolatile line matches the backup; unrelated user edits are preserved.
- Runtime state and backups remain local under `%CODEX_HOME%\chromapaw\runtime\windows` unless the operator selects an override.

### Private content

Reference images and generated assets stay in declared local output paths unless a separately disclosed image-generation workflow uploads them. Runtime screenshots may contain task names, source paths, or conversation text and require an explicit CLI acknowledgment. Do not publish captures without user permission.

## macOS probe boundary

The 0.4.1 macOS tool is compatibility discovery only. It may read `Info.plist`, hash the bundle's declared executable, inspect packaging signals, and validate a local skin package. It does not launch the app, open a debugging port, inject CSS, edit the application bundle, modify `app.asar`, or write activation state. The registry requires `activationImplemented: false` and rejects every adapter whose `activationEnabled` is not false.

Do not publish a raw compatibility report without reviewing absolute paths and local metadata. No macOS activation adapter may be enabled until a reversible design passes exact-version real-device testing and code-signing protections remain intact.

## Required invariants

ChromaPaw must:

- never weaken Windows package protections to activate a skin;
- never weaken macOS code-signing, Gatekeeper, or bundle protections;
- never expose CDP beyond loopback;
- disclose every local port and background process;
- refuse activation on unknown or unverified versions;
- keep package validation separate from activation consent;
- remove only a matching session-owned style marker;
- terminate only a verified runtime-owned process tree;
- preserve unrelated user configuration changes;
- and maintain deterministic stop/restore records.

See [docs/WINDOWS_RUNTIME_BETA.md](docs/WINDOWS_RUNTIME_BETA.md) for the operating sequence.
