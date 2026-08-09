# Security policy

## Reporting a vulnerability

Please do not publish an exploit in a public issue. Contact the ChromaPaw maintainers through the repository owner's private contact channel or GitHub Security Advisories when enabled.

Include the affected version, operating system, reproduction steps, impact, and any suggested mitigation. Avoid attaching private source images or access tokens.

## Security boundaries

ChromaPaw must:

- never modify `WindowsApps` or a signed Codex application archive;
- never expose a debugging interface beyond the loopback device;
- clearly disclose any local port, watcher, or background process;
- verify the target application identity before applying a live skin;
- back up configuration before a reversible activation;
- refuse activation when the Codex version is unsupported;
- avoid collecting or uploading user images without an explicit workflow step.

The `0.2.x` line includes local desktop-pet package installation and managed backups, but no live skin runtime. Any future skin runtime will require a dedicated threat model and security review before release.
