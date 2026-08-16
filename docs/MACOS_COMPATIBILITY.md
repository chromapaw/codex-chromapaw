# macOS compatibility probe

ChromaPaw 0.4.7 has platform-neutral code paths for portable pet and contrast-safe, image-aware skin assets. Pet generation additionally requires a compatible external `hatch-pet` workflow, and both generation paths still require real-Mac acceptance testing. The separate persistent launchers are Windows-only; live macOS skin activation is not implemented or claimed.

## Enhanced cloud harness

`.github/workflows/macos-enhanced.yml` runs a second compatibility layer on GitHub-hosted Apple Silicon and Intel macOS virtual machines. It calls the production package and filesystem code rather than duplicating formats:

1. generate and validate one adaptive Skin Studio v2 package;
2. generate a deterministic 1536×2288 v2 pet fixture;
3. install, replace, restore, and revalidate that pet under a temporary `CODEX_HOME`;
4. inspect a deterministic Electron-shaped `.app` bundle through the read-only macOS probe;
5. load the generated CSS in a Codex-shaped Chromium renderer with a deliberately conflicting host palette;
6. verify right-panel primary and secondary text contrast in light and dark modes;
7. verify that the skin scene is suppressed in the transparent pet overlay while the `.codex-avatar-root` spritesheet remains present;
8. capture main-window and transparent-overlay PNG evidence plus a machine-readable report.

Run the renderer portion locally for development with:

```bash
npm ci
npx playwright install chromium
python3 scripts/macos_enhanced_test.py --output artifacts/macos-enhanced --force
```

The normal command fails outside macOS. `--allow-non-darwin` exists only for developer preflight and records `realMacOSHost: false`; it cannot satisfy the macOS acceptance gate.

The harness is stronger than operating-system-neutral unit tests, but it is not the signed, logged-in Codex application. It does not prove app-specific launch arguments, main-window selectors, transparent native-window behavior, login state, persistence after an actual Codex restart, or live skin activation.

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

1. A sanitized discovery and preflight report from an actual supported Mac with Codex installed, not only the deterministic CI fixture.
2. Confirmation of the official app name, bundle identifier, version fields, executable, packaging layout, and code-signing behavior.
3. A reversible runtime design that does not patch the signed application bundle or `app.asar`.
4. Live verification on both the main window and transparent pet overlay.
5. Restore verification proving all temporary processes, ports, styles, and state are removed.
6. Exact-version failure tests and a disabled-by-default adapter entry.

Until all checks pass on a real Mac, ChromaPaw should generate and preview skins but must not claim they are active in Codex.
