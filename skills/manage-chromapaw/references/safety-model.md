# Runtime safety model

Apply these rules to every state-changing operation.

## Universal rules

1. Resolve and display the exact target package, Codex version, executable, destination, and operation.
2. Verify that every source and destination path stays inside its declared root.
3. Back up relevant user configuration before activation and record the backup path and hash.
4. Never modify `WindowsApps`, signed application files, `app.asar`, or an official application archive.
5. Never delete or move a recursively computed path before confirming its resolved absolute location.
6. Package validation alone does not authorize activation; activation is a separate explicit user decision.

## Windows skin runtime rules

1. State clearly that no documented official Codex desktop skin API is being used.
2. Refuse unknown versions and recognized adapters whose `activationEnabled` value is false.
3. Record the executable hash and adapter-file hash, then fail if either changes during the session.
4. Refuse ordinary activation while the selected executable is already running. An isolated parallel profile is for compatibility testing only.
5. Bind CDP to a random port on `127.0.0.1`, disclose that it is unauthenticated, and never accept a non-loopback endpoint or websocket.
6. Accept only adapter-declared target schemes and verify the browser identity before applying UI content.
7. Disclose the hidden once-per-second monitor. It may inject only the validated compiled CSS when a new or unstyled eligible target appears.
8. Require the stylesheet's avatar-overlay isolation guard so the skin cannot create a rectangular pet background.
9. Remove only a style marker owned by the active session; refuse a marker identity mismatch.
10. During restore, stop the monitor first, remove session-owned CSS, verify process identities, terminate only the runtime-launched process tree, and confirm that the port closed.
11. Restore only allowlisted volatile Codex session keys when all nonvolatile config lines are unchanged. Preserve unrelated user changes.
12. Treat screenshots as private by default because they may contain task names, source paths, or conversation text.
13. Persist only restart-safe package, executable, version, CSS, and adapter identities. Never copy session tokens, ports, target metadata, or page content into the relaunch preference.
14. Resume only after rechecking every persisted identity. Fail closed when the package, executable, app version, compiled CSS, adapter id, or adapter registry changed.
15. Treat Desktop and Start Menu integration as a separate explicitly acknowledged operation. Verify the existing target, leave the application-managed shortcut untouched, add distinctly named ChromaPaw entries, and install no login task, registry auto-run entry, or always-on watcher.
16. Hash stable shortcut semantics—target, arguments, working directory, icon, and description—because Windows may rewrite binary tracking metadata after use. Before removal, verify both separately managed entries; if either semantic hash differs from the receipt, remove neither.

## Failure behavior

- If launch or injection fails, terminate the process launched by the runtime, write a failure record, and leave no active state.
- If verification fails, report the failed target and use explicit repair only when the package and adapter hashes still match.
- If restore cannot prove process or style ownership, stop and report the exact mismatch instead of guessing.
- If resume cannot prove preference continuity, require a fresh preflight and activation instead of updating saved hashes automatically.
- If semantic ownership of either separate shortcut cannot be proven, leave both it and the original application entry unchanged and report the exact mismatch.
- If an official packaged executable cannot be launched through the verified path, keep that adapter disabled. Do not weaken Windows package protections.
