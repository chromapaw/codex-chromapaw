# Reversible Windows Runtime Beta

ChromaPaw 0.4 can apply a validated Skin Studio v2 package to selected Windows Codex builds without modifying the application archive. Version 0.4.6 remembers that validated selection through separate reversible Desktop and Start Menu launchers and strengthens hosted-runtime integrity and recovery. This is an experimental compatibility layer, not an official OpenAI desktop skin API.

Every activation candidate must match both its exact Codex application version and the adapter's executable-identity policy. ChromaPaw probes PE product metadata and Authenticode status and requires an enabled adapter to pin either an allowlisted SHA-256 or an exact signed file version plus signer. A renamed executable placed in a version-shaped directory fails closed.

Shortcut installation copies the launcher, its complete dependency-free runtime module closure, and the reviewed adapter registry into a content-addressed generation under the ChromaPaw runtime data directory. Both shortcuts point only to a stable bootstrap there, so a plugin cache refresh does not invalidate them. The selected skin preference pins the exact reviewed generation; later plugin or adapter upgrades may update `current.json` for future activations but cannot silently move an existing skin to new runtime code. Earlier generations remain available for continuity and rollback. Removing the shortcuts retains this managed runtime directory so an in-flight launcher or monitor is not broken.

## Compatibility boundary

Activation is allowed only when all of these checks pass:

- Windows is the host platform.
- The resolved executable exists, its four-part Codex version can be derived from the containing directory, and its PE product metadata, signature policy, and pinned hash or signed file version match the adapter.
- `runtime/windows-adapters.json` has one exact version/executable match with `activationEnabled: true`.
- The adapter registry uses an ephemeral loopback-only transport and discloses its background monitor.
- The Skin Studio package validates as schemaVersion 2 and contains the avatar-overlay isolation guard.
- The selected executable is closed before ordinary activation.

An adapter marked disabled is diagnostic history only and cannot activate. Recently discovered official AppX builds do not have an enabled adapter; the registry retains official AppX `26.803.5235.0` as a historical disabled probe record because Windows denied the direct protected-package launch required to supply isolated runtime arguments. ChromaPaw does not bypass that protection, and every newer unknown AppX version fails closed.

## Lifecycle

### Discover

```powershell
python scripts/windows_runtime.py --json discover
```

Discovery checks explicit overrides, local standalone copies, accessible package folders, and the Windows AppX package registry. It does not modify any application.

### Preflight

```powershell
python scripts/windows_runtime.py --json preflight C:\skins\my-skin --executable C:\path\to\ChatGPT.exe
```

Review the exact path, version, adapter id, executable hash, running PIDs, package/hash, and transport disclosure. Preflight is read-only.

### Activate

Close the selected Codex executable first, then run:

```powershell
python scripts/windows_runtime.py --json activate C:\skins\my-skin --executable C:\path\to\ChatGPT.exe --acknowledge-experimental-runtime
```

Activation:

1. Creates a session directory and backs up `config.toml` when present.
2. Records the executable, adapter registry, package manifest, and compiled CSS hashes.
3. Selects a random available port and launches Codex with CDP bound to `127.0.0.1`.
4. Verifies the CDP browser and websocket identities against the adapter.
5. Injects one session-owned `<style>` element into eligible `app://` targets.
6. Starts a hidden Python monitor that checks once per second and styles newly created eligible windows.

No app archive, signed application file, or `WindowsApps` file is written.

After the monitor starts successfully, activation also writes `preferred-skin.json`. This preference contains package, executable, adapter, version, and hash identities only. It never contains the runtime session token, CDP port, task titles, or conversation content.

### Resume after closing Codex

Closing Codex ends the in-memory style and its loopback transport. Resume revalidates the saved preference, recovers the stale ended session record, and starts a fresh runtime:

```powershell
python scripts/windows_runtime.py --json resume --acknowledge-experimental-runtime
```

Resume fails closed if the package, compiled CSS, executable, app version, adapter identity, or adapter registry changed. If an ordinary unstyled instance of the same executable is already running, close it before resume.

When the runtime is inactive and a reviewed plugin update changes only the compiled CSS identity, refresh the saved preference before resuming:

```powershell
python scripts/windows_runtime.py --json refresh-preference --acknowledge-runtime-update
```

This command refuses a healthy active session and refuses any package manifest, executable, app-version, adapter-id, or adapter-registry change. Use a new reviewed activation for those identity changes.

The ordinary application-managed ChatGPT shortcut cannot supply the required runtime arguments and may be recreated by Codex. ChromaPaw therefore leaves it untouched. After explicit user consent, add a separate reversible launcher named `Codex ChromaPaw`:

```powershell
python scripts/windows_shortcut.py --json install `
  --executable C:\path\to\ChatGPT.exe `
  --acknowledge-adds-windows-shortcuts
```

Installation first confirms that the original `ChatGPT.lnk` still targets the selected executable, then creates `Codex ChromaPaw.lnk` on the user's Desktop and in the Start Menu. The receipt hashes stable semantic fields—target, arguments, working directory, icon, and description—because Windows may rewrite binary tracking data after a click. It does not configure Windows startup or a background watcher. Clicking either ChromaPaw entry launches Codex on demand; clicking the original entry opens the default appearance.

The shortcut target is a stable bootstrap below the ChromaPaw runtime data directory, not a versioned plugin-cache path. Installation atomically copies the launcher, its complete Python import closure, and the adapter registry into a content-addressed generation and records all hashes in the receipt. Plugin cache cleanup therefore does not break the installed shortcut. A reviewed skin remains pinned to its original immutable generation across upgrades. If skin recovery nevertheless fails, the launcher records the technical error locally and opens only the previously hash-verified ordinary Codex executable; low-level adapter and CSS identity errors are not shown as blocking dialogs. A later explicit skin activation can adopt the newest reviewed generation.

Maintainers may move an existing reviewed skin to a newly installed generation with `--upgrade-reviewed-runtime`. The migration is accepted only when a fresh preflight proves that the package manifest, compiled CSS, executable, application version, adapter identity, and adapter registry are unchanged; any mismatch rolls back the shortcut update and keeps the previous pin.

Remove both ChromaPaw shortcuts independently of the active skin session:

```powershell
python scripts/windows_shortcut.py --json restore
```

Restore first verifies both managed semantic ownership hashes, then removes both entries. If either entry changed, it removes neither. It never overwrites or deletes the original application shortcut. Hosted content-addressed runtime files are retained after removal because deleting them could break an in-flight launcher or monitor; a later installation can safely reuse or atomically supersede them.

### Verify

```powershell
python scripts/windows_runtime.py --json verify
```

Verification rechecks process identity, executable and adapter continuity, monitor identity, endpoint identity, target scheme, CSS hash, and session ownership. `verify --repair` may reapply the same validated CSS to an unstyled target; it refuses a changed package.

If a reviewed local runtime update changes only the compiled CSS for an active package, hot-refresh it without closing Codex:

```powershell
python scripts/windows_runtime.py --json refresh-active-css --acknowledge-runtime-update
```

The refresh fails closed if the package manifest, executable, app version, adapter, or package identity changed. Before mutation it reads and hashes the currently owned style from every eligible target. It replaces the session-owned style in both the main window and pet overlay, then restarts only ChromaPaw's hidden CSS monitor. CSS, monitor identity, active state, and saved preference are committed as one compensating transaction; a failed monitor restart or state write restores the previous CSS and monitor. Use a new reviewed activation for any identity change.

### Status

```powershell
python scripts/windows_runtime.py --json status
```

Status reports active/inactive/stale state, the runtime-owned Codex and monitor process identities, local port, adapter and package continuity, browser identity, compiled CSS continuity, and style ownership.

### Private screenshot

```powershell
python scripts/windows_runtime.py --json capture --output C:\private\skin-check.png --acknowledge-screenshot-may-contain-private-content
```

Captures may contain task titles, filesystem paths, or conversation content. They are never required for ordinary restore and should not be published without permission.

### Restore

```powershell
python scripts/windows_runtime.py --json restore
```

Restore performs this order:

1. Verify and stop the disclosed monitor.
2. Remove only CSS whose hash and session marker match the active session.
3. Verify and terminate only the Codex process tree launched by this runtime.
4. Poll until the random CDP port is closed.
5. Compare the current Codex config with the backup. Restore only allowlisted volatile app-session keys if every other line is unchanged.
6. Write the final session record and remove `active.json`.

The `stop` command uses the same safety sequence but labels the final operation as stopped.

## State and recovery files

The default state root is:

```text
%CODEX_HOME%\chromapaw\runtime\windows
```

If `CODEX_HOME` is unset, ChromaPaw uses `%USERPROFILE%\.codex`. Each session records preflight metadata, a configuration backup when available, activation/failure state, monitor events, and the final restore result. The selected-skin preference, launcher log, and shortcut receipt also live under this root. Session secrets remain in local state but are recursively redacted from normal command output and are excluded from the relaunch preference.

## Isolated compatibility testing

Maintainers may use `--profile-dir <empty-directory> --allow-parallel-profile` to test a candidate executable without sharing the active Codex profile. This flag is not for normal user activation. A candidate adapter remains disabled until the full live checklist in [CONTRIBUTING.md](../CONTRIBUTING.md) passes.

## Known limitations

- No official skin API or selector stability guarantee exists.
- Only Windows and exact enabled adapter versions are supported.
- Runtime mutations use an operating-system-owned advisory lock, so a crash-released operation cannot leave an unremovable sentinel lock.
- New sessions bind process ownership to PID, executable path and hash, and Windows creation FILETIME; legacy sessions remain restorable through the older exact-path and hash gate.
- Restore must stop the runtime-launched Codex process to guarantee that unauthenticated CDP is closed.
- Persistence requires launching from either installed ChromaPaw shortcut; the untouched executable and any other entry still open the default Codex appearance.
- A Codex update normally changes the four-part version and fails closed until a new adapter is tested.
- Skin packages remain portable even when a runtime adapter is unavailable; preview and validation still work.
