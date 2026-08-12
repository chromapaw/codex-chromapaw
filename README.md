# ChromaPaw for Codex

Turn one uploaded image into an image-specific Codex skin or animated pet.

> Version 0.4.6 hardens one-image generation handoffs, pet selection, hosted shortcuts, and Windows runtime recovery. Package generation remains separate from installation and live skin activation; ChromaPaw does not claim an official OpenAI desktop skin API.

[中文说明](#中文说明) · [Skin Studio](docs/SKIN_STUDIO_MVP.md) · [Pet MVP](docs/PET_MVP.md) · [Windows Runtime Beta](docs/WINDOWS_RUNTIME_BETA.md) · [macOS probe](docs/MACOS_COMPATIBILITY.md) · [Release checklist](docs/RELEASE_CHECKLIST.md) · [Roadmap](ROADMAP.md) · [Architecture](docs/ARCHITECTURE.md)

## One-image workflow

1. Attach one image in a Codex task.
2. Ask for a **pet** or **skin**.
3. ChromaPaw analyzes only that image and the current request.
4. It creates a reviewable preview and a validated portable package.
5. ChromaPaw reports `generated-not-installed` or `generated-not-active` and shows the exact separate confirmation phrase only when that next step is supported on the current machine.
6. Pet installation also selects the installed desktop pet after confirmation and reports whether reopening Codex may be required. Windows skin activation still requires its later experimental-runtime acknowledgment after read-only preflight.

For skins, the analysis becomes a SHA-256-bound `theme-profile.json` containing the image's style, mood, identity cues, motifs, forbidden elements, four spatial depth descriptions, and safe-zone guidance. The four depth layers are composition slots, not a fixed beach template. A sky upload can use clouds and sunlight; comic art can use panels, halftone, and speed lines. Beach, waves, sand, or coral appear only when the upload or user request supports them. Prominent subjects that overlap the content safe zone are recomposed onto a side stage instead of being faded, blurred, or covered by a full-window wash.

## Current status

| Capability | Windows | macOS |
| --- | --- | --- |
| One-image skin package generation | Implemented | Platform-neutral implementation; real-Mac validation pending |
| One-image pet package generation | Implemented with `hatch-pet` | Platform-neutral implementation; real-Mac validation pending |
| Pet package validation/install/select/restore | Implemented; real-app visibility acceptance pending | Implementation present; real-Mac validation pending |
| Live skin activation | Experimental, exact-version adapters only | Not implemented |
| Skin relaunch after closing Codex | Explicit, reversible ChromaPaw Desktop and Start Menu shortcuts | Not implemented |
| Compatibility discovery | Implemented | Read-only probe and enhanced cloud harness implemented |

On the current Windows development machine, standalone Codex `26.707.9981.0` has an enabled experimental adapter. Recently discovered official AppX builds do not have an enabled adapter; the registry retains `26.803.5235.0` only as a historical disabled probe record. Unknown versions fail closed.

## Capabilities

### Skin Studio

- Classify an upload as a full environment, subject, texture, abstract cue, or logo.
- Bind the semantic theme profile to the original image hash and reject mismatches or motif/exclusion contradictions.
- Derive primary, secondary, muted, accent, on-accent, elevated, and input colors for both light and dark variants, with a minimum 4.5:1 text contrast gate.
- Override Codex and VS Code semantic UI tokens so the uploaded background cannot leave menus or navigation using unreadable host-theme colors.
- Use a safe full environment directly; otherwise expand or recompose it into image-specific scene artwork with the hero subject staged away from the reading/input zones.
- Preserve crisp scene fidelity with an 8% edge treatment and directional local reading surfaces instead of a full-window color wash.
- Extract accessible light and dark palettes and generate light, dark, and adaptive CSS.
- Render six visual-QA previews across 16:10, 16:9, and 4:3 window ratios.
- Record safe content zones, image-specific depth layers, attribution, semantic metadata, and structured QA.
- Isolate Codex's transparent pet overlay so the skin does not become a rectangle behind a pet.
- Export a portable schemaVersion 2 package independently from runtime compatibility.

### Animated pets

- Preserve the subject's silhouette, palette, face, clothing, and props.
- Map working, waiting, ready, and failed intent onto supported Codex animation rows.
- Build and visually validate an 8×11 desktop v2 atlas through a compatible installed `hatch-pet` workflow.
- Refuse silent replacement, back up an existing matching id, safely select the installed desktop pet through a config backup, and restore managed backups.

### Runtime compatibility

- `scripts/platform_capabilities.py --json` reports generation readiness, pet dependencies, and platform activation boundaries.
- Skin uploads require Codex's image-generation capability when the upload is not a full environment or a salient subject overlaps the reading/input safe zone; safe full-environment uploads can proceed directly to deterministic packaging.
- The Windows Runtime Beta validates an exact adapter, PE product metadata, signature policy, and a pinned executable identity before using a temporary loopback-only runtime without editing `WindowsApps`, `app.asar`, or signed application files.
- A successful Windows activation remembers only package/executable/adapter identities and hashes. It never stores the session token or debugging port as a relaunch preference.
- Reviewed CSS-only updates use separate fail-closed paths: `refresh-active-css` for a healthy active session and `refresh-preference` for an inactive saved skin. Identity changes require a new activation review.
- The optional Windows integration leaves `ChatGPT.lnk` untouched, hosts a verified content-addressed launcher/runtime copy outside the plugin cache, adds distinct `Codex ChromaPaw.lnk` entries to the Desktop and Start Menu, and removes only those managed entries while both semantic ownership hashes still match.
- `scripts/audit_pets.py` reports valid v2, legacy v1, and invalid installed pets without changing any files.
- The macOS probe reads bundle metadata and validates a package but cannot activate it. A separate enhanced GitHub Actions harness runs on Apple Silicon and Intel macOS runners, builds a real Skin Studio package, exercises pet installation/replacement/restore in a temporary Codex home, and captures simulated Codex renderer screenshots for the main window, right panel, and transparent pet overlay. It still does not test or claim activation in the signed, logged-in Codex app.

## Install

ChromaPaw requires a Codex build with plugin marketplace commands and Git on `PATH`.

```bash
codex plugin marketplace add chromapaw/codex-chromapaw --ref main
codex plugin add codex-chromapaw@chromapaw
```

Restart Codex and open a new task so the three skills are discovered. Attach an image and invoke `$create-chromapaw-skin` or `$create-chromapaw-pet`.

Animated pet generation additionally requires a compatible `hatch-pet` skill. ChromaPaw validates the full preparation, atlas assembly, direction, preview, and blind-QA script contract; it does not silently download or vendor this external dependency. A clean ChromaPaw install therefore cannot generate pets until a compatible `hatch-pet` is available through the user's Codex distribution or `CHROMAPAW_HATCH_PET_DIR`.

### Update

```bash
codex plugin marketplace upgrade chromapaw
codex plugin add codex-chromapaw@chromapaw
```

Restart Codex and use a new task after updating.

### Release checks

```bash
python -m pip install -r requirements-skin.txt -r requirements-dev.txt
python scripts/release_check.py
python scripts/audit_pets.py --json --allow-issues
```

See [the release checklist](docs/RELEASE_CHECKLIST.md) for real-image, clean-install, and exact-version platform gates.

### Uninstall

Restore any active Windows runtime session before uninstalling:

```bash
python scripts/windows_runtime.py --json status
python scripts/windows_runtime.py --json restore
python scripts/windows_shortcut.py --json restore
codex plugin remove codex-chromapaw@chromapaw
codex plugin marketplace remove chromapaw
```

## Plugin skills

- `$create-chromapaw-skin` — analyze one upload, create its semantic profile, generate when needed, then build and validate a layered skin.
- `$create-chromapaw-pet` — create, review, validate, and optionally install an animated Codex pet.
- `$manage-chromapaw` — inspect packages and use supported activation, compatibility, verification, and recovery paths.

## Skin quick start

In Codex, attach an image and say:

```text
Use $create-chromapaw-skin to turn this image into a complete layered theme.
Preserve the image's own subject, style, and motifs; keep the reading and input areas clear.
Do not introduce unrelated scene elements.
```

The skill analyzes the current upload and runs the profile, build, validation, and visual-QA steps. For a manual repository flow, create a profile first:

```bash
python scripts/prepare_theme_profile.py \
  --image scene.png \
  --source-kind full-environment \
  --theme-name "Open Blue Sky" \
  --visual-style "soft dimensional illustration" \
  --mood "fresh and airy" \
  --identity-cue "rounded white clouds" \
  --motif "blue sky" \
  --motif "soft sunlight" \
  --avoid-element "ocean" \
  --atmosphere "clear luminous air" \
  --distant "small layered cloud banks" \
  --midground "large soft clouds around the reading area" \
  --foreground "restrained corner wisps" \
  --safe-zone-guidance "keep the center and bottom low detail" \
  --output-dir run

python scripts/prepare_skin_request.py \
  --image scene.png \
  --theme-profile run/theme-profile.json \
  --mode adaptive \
  --output-dir run

python scripts/build_skin_package.py \
  --request run/skin-request.json \
  --output-dir package \
  --json

python scripts/validate_skin_package.py package --json
```

The builder requires Pillow, available in Codex's workspace runtime or installable from `requirements-skin.txt`.

## Platform checks

```bash
python scripts/platform_capabilities.py --json
```

Windows live activation is a separate explicit operation documented in [docs/WINDOWS_RUNTIME_BETA.md](docs/WINDOWS_RUNTIME_BETA.md). macOS users can collect a safe, non-activating report:

```bash
python3 scripts/macos_compat.py --json discover
python3 scripts/macos_compat.py --json preflight /absolute/path/to/package \
  --app /Applications/Codex.app
```

## Safety

- Package creation does not modify Codex application files.
- Skin activation never happens implicitly after generation.
- Unknown and disabled runtime versions fail closed.
- Reference images remain in declared local paths unless a separately disclosed generation service needs the image.
- Treat third-party characters, logos, and artwork as private-use references unless distribution rights are clear.

## Development

Use Python 3.10 or later. Skin builder tests require Pillow.

```bash
python -m py_compile scripts/*.py
python -m unittest discover -s tests -v
python scripts/check_dependencies.py --json
python scripts/platform_capabilities.py --json
python scripts/smoke_test_install.py --json
```

Plugin and skill structure must also pass the validators bundled with Codex's `plugin-creator` and `skill-creator` skills before release.

## License and trademark

Licensed under [Apache-2.0](LICENSE). ChromaPaw is an independent community project and is not affiliated with or endorsed by OpenAI. Codex and OpenAI product names belong to their respective owners.

## 中文说明

ChromaPaw 的目标是让用户在 Codex 中只上传一张图片，就可以生成：

- 带任务状态动画的自定义宠物；
- 根据当前图片内容动态生成的完整主题皮肤；
- 可预览、校验、备份和恢复的本地资源包。

皮肤不是固定的海滩模板。每次任务都会先分析当前图片，记录主题、画风、氛围、识别特征、应保留元素、禁止元素和四层空间构图，并通过原图 SHA-256 防止串图。如果上传的是蓝天白云，就围绕天空、云朵和阳光组织画面；如果上传的是卡通漫画，就围绕分镜、网点和速度线组织画面；只有海滩图片或用户明确要求时，才会使用海浪、沙滩、珊瑚等元素。

当前 Windows 已具备宠物与皮肤资源生成能力，并有受精确版本限制的实验性皮肤运行时。macOS 的生成和宠物安装代码采用跨平台路径设计，但仍需要真实 Mac 验证；macOS 皮肤实时应用尚未实现，目前只能进行只读兼容性探测。我们会明确区分“生成成功”和“已经应用到 Codex”，不会把预览当成激活结果。
