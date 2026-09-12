# Windows update and recovery

Use this reference for a removed Store executable, a reviewed next-launch request, or a project-sidebar migration issue. Read [safety-model.md](safety-model.md) before a mutation. Existing explicit authorization for the same disclosed operation remains valid; a plugin-version upgrade alone does not authorize changing the active skin or project data.

## Inspect before choosing a recovery

Run `scripts/windows_runtime.py --json discover` and `scripts/windows_runtime.py --json status` from the selected plugin root. Inspect the shortcut receipt with `scripts/windows_shortcut.py --json status`. Resolve the actual runtime data directory and hosted generation from these results and their recorded state; do not guess a removed executable, generation hash, or process id.

- A healthy active session needs no restart merely because the plugin was updated. Its monitor and saved preference can remain pinned to their reviewed generation.
- A Store update that removed the executable can still permit ordinary startup through the verified signed official AppX identity. That fallback does not apply a skin.
- A changed executable, adapter registry, package, or compiled CSS requires the corresponding reviewed activation/update path. Do not copy new hashes into an old preference.

## Repair an existing managed launcher

For an authorized launcher repair, run:

```bash
python scripts/windows_shortcut.py --json repair-launcher --acknowledge-repairs-windows-launcher
```

Require semantic shortcut ownership and transactional verification to pass. This updates the stable bootstrap recovery code while retaining the `.lnk` entries and previous skin pin. If ownership or the current official signature cannot be established, report the failure and retain the existing state.

## Review now, activate on the next launch

Use this when the user has accepted the experimental runtime behavior but wants to keep their current Codex window open. Preflight the exact new executable and package, including its version, signature/hash, locale, adapter and monitor/loopback-port disclosure.

The pending helper requires a verified, installed immutable hosted generation. Resolve and verify that generation using the shortcut receipt and hosted manifest before running its `scripts/windows_pending_activation.py`; set `CHROMAPAW_HOSTED_GENERATION` and `CHROMAPAW_HOSTED_BUNDLE_HASH` only from that verified identity. Use the exact package, executable, runtime data directory and hosted adapter path, and pass `--acknowledge-experimental-runtime`. Follow the hosted-generation workflow in [Windows Runtime Beta](../../../docs/WINDOWS_RUNTIME_BETA.md#durable-reviewed-activation-on-the-next-click).

Require `pending-next-launch` and an unchanged previous preference. Tell the user to close Codex and open either managed **Codex ChromaPaw** shortcut. This creates no waiting child process or scheduled task. A cancelled or failed launch retains the request; report activation complete only after verification succeeds and the pending result records `active-verified`.

If a conflicting pending request or owned active runtime prevents preparation, inspect that state and report it. Do not delete a pending request or stop a live session as an incidental plugin update.

## Project-sidebar repair

Inspect without changing state:

```bash
python scripts/windows_profile_repair.py --json status
```

Read the command's current `--help` before passing a non-default Codex home. Describe the saved workspace roots and migration/index status without exposing thread contents. Missing projects require a separate repair request; do not infer this from a visual theme problem.

For an authorized repair, prefer `prepare-next-launch` from the verified hosted generation with `--data-dir` and `--acknowledge-repairs-project-sidebar` when Codex is open. It pins the current official executable, bundled app-server CLI and existing project identities. The next managed launch applies it only after Codex has closed, backs up the database/global state, verifies the resulting project index, and consumes the request only on success. Follow the runtime documentation for the exact hosted environment.

Use direct `repair --acknowledge-repairs-project-sidebar` only after all Codex variants have closed. Report backup locations and verification results. Do not copy authentication data or conversation text. Prefer the durable request over the legacy waiting-process handoff, which may end when Codex closes.
