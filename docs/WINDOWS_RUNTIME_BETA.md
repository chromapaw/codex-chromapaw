# Reversible Windows Runtime Beta

ChromaPaw 0.4 can apply a validated Skin Studio v2 package to selected Windows Codex builds without modifying the application archive. Version 0.4.5 can also remember that validated selection and resume it through separate reversible Desktop and Start Menu launchers. This is an experimental compatibility layer, not an official OpenAI desktop skin API.

## Compatibility boundary

Activation is allowed only when all of these checks pass:

- Windows is the host platform.
- The resolved executable exists and its four-part Codex version can be derived from the containing directory.
- `runtime/windows-adapters.json` has one exact version/executable match with `activationEnabled: true`.
- The adapter registry uses an ephemeral loopback-only transport and discloses its background monitor.
- The Skin Studio package validates as schemaVersion 2 and contains the avatar-overlay isolation guard.
- The selected executable is closed before ordinary activation.

An adapter marked disabled is discoverable for diagnostics but cannot activate. The official AppX `26.803.5235.0` is currently disabled: package discovery succeeds, but Windows denies the direct protected-package launch required to supply isolated runtime arguments. ChromaPaw does not bypass that protection.

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

The ordinary application-managed ChatGPT shortcut cannot supply the required runtime arguments and may be recreated by Codex. ChromaPaw therefore leaves it untouched. After explicit user consent, add a separate reversible launcher named `Codex ChromaPaw`:

```powershell
python scripts/windows_shortcut.py --json install `
  --executable C:\path\to\ChatGPT.exe `
  --acknowledge-adds-windows-shortcuts
```

Installation first confirms that the original `ChatGPT.lnk` still targets the selected executable, then creates `Codex ChromaPaw.lnk` on the user's Desktop and in the Start Menu. The receipt hashes stable semantic fields—target, arguments, working directory, icon, and description—because Windows may rewrite binary tracking data after a click. It does not configure Windows startup or a background watcher. Clicking either ChromaPaw entry launches Codex on demand; clicking the original entry opens the default appearance.

Remove both ChromaPaw shortcuts independently of the active skin session:

```powershell
python scripts/windows_shortcut.py --json restore
```

Restore first verifies both managed semantic ownership hashes, then removes both entries. If either entry changed, it removes neither. It never overwrites or deletes the original application shortcut.

### Verify

```powershell
python scripts/windows_runtime.py --json verify
```

Verification rechecks process identity, executable and adapter continuity, monitor identity, endpoint identity, target scheme, CSS hash, and session ownership. `verify --repair` may reapply the same validated CSS to an unstyled target; it refuses a changed package.

If a reviewed local runtime update changes only the compiled CSS for the active package, hot-refresh it without closing Codex:

```powershell
python scripts/windows_runtime.py --json refresh-active-css --acknowledge-runtime-update
```

The refresh fails closed if the package manifest, executable, app version, adapter, or package identity changed. It replaces the session-owned style in both the main window and pet overlay, then restarts only ChromaPaw's hidden CSS monitor. Use a new reviewed activation for any identity change.

### Status

```powershell
python scripts/windows_runtime.py --json status
```

Status reports active/inactive/stale state, the runtime-owned Codex PID, monitor PID, and local port.

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
- Restore must stop the runtime-launched Codex process to guarantee that unauthenticated CDP is closed.
- Persistence requires launching from either installed ChromaPaw shortcut; the untouched executable and any other entry still open the default Codex appearance.
- A Codex update normally changes the four-part version and fails closed until a new adapter is tested.
- Skin packages remain portable even when a runtime adapter is unavailable; preview and validation still work.
