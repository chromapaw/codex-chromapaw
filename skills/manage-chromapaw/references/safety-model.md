# Runtime safety model

Apply these rules to every state-changing operation:

1. Resolve and display the exact target package, Codex version, and destination.
2. Verify that every source and destination path stays inside its declared root.
3. Back up user configuration before activation and record the backup path.
4. Never modify `WindowsApps`, signed application files, or an official application archive.
5. Refuse unknown Codex versions unless an adapter explicitly declares compatibility.
6. Bind any required local transport to loopback only, disclose it, and close it when the runtime stops.
7. Verify the target application identity before applying UI content.
8. After activation, test background, stylesheet, native controls, and restore behavior.
9. If verification fails, stop the runtime and restore the verified backup.
10. Never delete a recursively computed path before confirming its resolved absolute location.

Package validation alone does not authorize activation. Treat activation as a separate, explicit user decision.
