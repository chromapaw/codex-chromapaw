# macOS compatibility probe

ChromaPaw 0.4.1 can generate portable pet and skin assets with platform-neutral Python workflows. Live macOS skin activation is not implemented or claimed.

The probe exists to gather the exact evidence needed for a safe macOS runtime adapter. It reads an app bundle's `Info.plist`, locates and hashes its declared executable, records Electron packaging signals, and validates a selected ChromaPaw skin package. It does not launch Codex, inject CSS, open a debugging port, edit the app bundle, or create an activation state.

## Run on a real Mac

From the repository or installed plugin root:

```bash
python3 scripts/macos_compat.py --json discover
python3 scripts/macos_compat.py --json preflight /absolute/path/to/skin-package \
  --app /Applications/Codex.app
```

If the installed application is named `ChatGPT.app`, pass that path instead. `CHROMAPAW_MACOS_CODEX_APP` may point discovery at a nonstandard `.app` location.

The report always contains:

- `activationImplemented: false`
- `activationEnabled: false`
- `applicationFilesWillBeModified: false`

An exact probe adapter only means the bundle metadata is recognized. It never enables activation.

## Evidence required before implementation

1. A sanitized discovery and preflight report from an actual supported Mac.
2. Confirmation of the official app name, bundle identifier, version fields, executable, packaging layout, and code-signing behavior.
3. A reversible runtime design that does not patch the signed application bundle or `app.asar`.
4. Live verification on both the main window and transparent pet overlay.
5. Restore verification proving all temporary processes, ports, styles, and state are removed.
6. Exact-version failure tests and a disabled-by-default adapter entry.

Until all checks pass on a real Mac, ChromaPaw should generate and preview skins but must not claim they are active in Codex.
