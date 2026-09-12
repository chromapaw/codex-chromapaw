# Reversible Windows Runtime Beta

ChromaPaw 0.4 can apply a validated Skin Studio v2 package to selected Windows Codex builds without modifying the application archive. Version 0.4.8 adds durable reviewed next-launch requests, signed Store startup recovery, project-sidebar repair, and renderer language verification while retaining pinned runtime generations. This is an experimental compatibility layer, not an official OpenAI desktop skin API.

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

An adapter marked disabled is diagnostic history only and cannot activate. The registry retains official AppX `26.803.5235.0` as a historical disabled probe record because Windows denied direct protected-package execution. Exact AppX `26.901.1978.0` and `26.901.2854.0` are enabled after isolated activation, locale, main-window, avatar-overlay, repair, verification, and cleanup checks passed through Windows' packaged-app activation manager. AppX activation must return a new process: an existing PID is rejected before CSS injection or runtime ownership. ChromaPaw does not bypass package protection, and every other unknown AppX version fails closed.

Runtime CSS compatibility also covers the newer application-menu top bar, which no longer uses `.app-header-tint`. A narrowly scoped shell/menubar selector gives its text an opaque image-derived contrast surface without styling the transparent avatar overlay. Existing packages receive this compatibility layer during compilation; their images and manifests are not rewritten. Adopting this changed compiled CSS requires a reviewed runtime update or fresh activation.

## Lifecycle

The signed Store build `26.901.5003.0` was additionally verified on 2026-09-06 with the Kyoto Rooftop Cats HD package: Chinese main-window UI, both saved projects visible, readable application menus, transparent avatar window, CSS repair and cleanup. Its exact executable SHA-256 is pinned in the registry. A Store update that removes an older executable still requires fresh reviewed activation, which can be persisted for the next ChromaPaw click; copying the old preference hashes cannot establish compatibility.

The production monitor lifecycle also passed in an isolated profile: activation, verified CSS/locale, automatic repair after removing session-owned CSS, and restore with the debug port closed. These are historical checks for the named executable hashes, not evidence for a later Store update. Verification retries only timed-out CSS/locale reads (at most three attempts); it does not retry script/identity errors or convert missing styles into a passing result.

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
3. Selects a random available port, mirrors `[desktop].localeOverride` through Electron's supported `--lang` switch, and launches Codex with CDP bound to `127.0.0.1`. Exact reviewed AppX adapters use Windows [`IApplicationActivationManager`](https://learn.microsoft.com/windows/win32/api/shobjidl_core/nf-shobjidl_core-iapplicationactivationmanager-activateapplication); standalone adapters use direct process creation.
4. Verifies the CDP browser and websocket identities against the adapter.
5. Injects one session-owned `<style>` element into eligible `app://` targets.
6. Starts a hidden Python monitor that checks once per second and styles newly created eligible windows.

No app archive, signed application file, or `WindowsApps` file is written.

After the monitor starts successfully, activation also writes `preferred-skin.json`. This preference contains package, executable, adapter, version, and hash identities only. It never contains the runtime session token, CDP port, task titles, or conversation content.

### Resume after closing Codex

#### Durable reviewed activation on the next click

When activation is requested from inside the Codex process that must close, do not rely on a child waiting process surviving the application's shutdown. After explicit experimental-runtime consent and installation of the reviewed hosted generation, `scripts/windows_pending_activation.py` can persist `pending-skin-activation.json` in the runtime directory. Run this entry from that immutable hosted generation with its verified `CHROMAPAW_HOSTED_GENERATION` and `CHROMAPAW_HOSTED_BUNDLE_HASH` environment values, the exact package/executable, and `--acknowledge-experimental-runtime`.

This records an intent, not a successful activation: it leaves `preferred-skin.json` unchanged. It pins package, CSS, executable, version, adapter, hosted-generation identities and the previous preference hash. The next Desktop or Start Menu **Codex ChromaPaw** click prioritizes this reviewed request over an obsolete preference and revalidates all identities before doing anything to a running application. Close Codex completely before clicking; if it remains running, the existing explicit restart confirmation still applies. A cancelled or failed activation retains the intent. Only successful runtime verification consumes it and records `pending-skin-activation-result.json`. No scheduled task, login entry, or waiting background process is installed.

A project-sidebar repair requested while Codex is open uses the same durable handoff principle. The reviewed request pins the signed official application, its bundled app-server CLI, the current hosted runtime generation, and the existing database project ids/roots. The launcher refuses to write while any `ChatGPT.exe` process is present. On the next click after all Codex variants have closed, it creates the normal sidebar-profile backup, rebuilds only the global sidebar cache through the verified project records, verifies both projects, consumes the request, and then continues startup. It does not copy authentication data, Chromium profiles, or conversation text.

Closing Codex ends the in-memory style and its loopback transport. Resume revalidates the saved preference, recovers the stale ended session record, and starts a fresh runtime. If Windows has already recycled a recorded PID, recovery treats the replacement as unrelated: it never terminates or attaches to that process, archives only the old ChromaPaw state, and continues with a fresh reviewed session:

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

For standalone Codex, installation first confirms that the original `ChatGPT.lnk` still targets the selected executable. For an exact reviewed AppX adapter, Windows may expose only a StartApps identity and no filesystem shortcut; that application-owned entry is treated as unmanaged whether it is absent or appears later. ChromaPaw then creates its own `Codex ChromaPaw.lnk` on the user's Desktop and in the Start Menu. The receipt hashes stable semantic fields—target, arguments, working directory, icon, and description—because Windows may rewrite binary tracking data after a click. It does not configure Windows startup or a background watcher. Clicking either ChromaPaw entry launches Codex on demand; clicking the original application entry opens the default appearance.

The shortcut target is a stable bootstrap below the ChromaPaw runtime data directory, not a versioned plugin-cache path. Installation atomically copies the launcher, its complete Python import closure, and the adapter registry into a content-addressed generation and records all hashes in the receipt. Plugin cache cleanup therefore does not break the installed shortcut. A reviewed skin remains pinned to its original immutable generation across upgrades. If skin recovery fails, the launcher tries the previously hash-verified ordinary executable. If a Store update removed that executable, it verifies the current registered `OpenAI.Codex_2p2nqsd0c76g0` Store package, publisher, manifest target, and valid OpenAI executable signature before ordinary activation through its stable AppX identity. This fallback carries only the configured locale: no CDP port, monitor, skin injection, process termination, or preference identity replacement. Successful fallback is logged as plain startup, never skin activation. A later reviewed activation is still required for a new skin-compatible version.

To repair an already-managed launcher after a Store update, without adopting a new skin runtime or replacing the saved preference, explicitly authorize:

```powershell
python scripts/windows_shortcut.py --json repair-launcher --acknowledge-repairs-windows-launcher
```

This verifies existing shortcut ownership, updates the stable bootstrap and its recovery code transactionally, and leaves both `.lnk` files and the original skin pin unchanged. Recovery is embedded in the trusted bootstrap, so even an older pinned skin launcher can recover from a deleted version directory. If no verified official installation or hash-matching saved executable can be opened, a final actionable error is still shown; ChromaPaw does not hide a total launch failure.

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
- Language synchronization is verified after launch. The legacy standalone `26.707.9981.0` build cannot initialize its renderer in a configured non-English locale and therefore fails the new language gate; use the exact enabled AppX `26.901.1978.0` adapter for synchronized UI language. Changing the Codex language setting while a process is open requires closing it and reopening through `Codex ChromaPaw`.
