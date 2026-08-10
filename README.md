# ChromaPaw for Codex

Turn one image into a custom Codex skin or animated pet.

> Version 0.3.0 ships the one-image Skin Studio MVP and the installable desktop Pet Beta. Skin packages can be generated and fully validated now; live skin activation remains separate until a reversible Codex runtime is available.

[中文说明](#中文说明) · [Skin Studio](docs/SKIN_STUDIO_MVP.md) · [Pet MVP](docs/PET_MVP.md) · [Roadmap](ROADMAP.md) · [Architecture](docs/ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md)

## Vision

1. Upload one reference image in Codex.
2. Choose **Pet** or **Skin**.
3. Preview and review the generated result.
4. Validate it before installation or activation.
5. Switch or restore safely.

## Capabilities

### Skin Studio MVP

- Turn a full environment image directly into a skin, or expand a character/object reference into complete environmental artwork first.
- Extract accessible light and dark palettes automatically.
- Generate light, dark, and adaptive CSS with readable glass surfaces.
- Render six visual-QA previews: light/dark × 16:10/16:9/4:3.
- Record a normalized safe content zone, atmosphere/distant/midground/foreground depth layers, source attribution, and structured QA.
- Isolate Codex's transparent avatar overlay so a theme background cannot appear as a rectangle behind a pet.
- Export a portable schemaVersion 2 package without modifying a live Codex installation.

### Animated pets

- Preserve the subject's recognizable silhouette, palette, face, clothing, and props.
- Generate task-aware animation intent such as working, waiting, ready, and failed.
- Build and validate a Codex-compatible desktop v2 pet package through a compatible installed `hatch-pet` workflow.
- Produce contact sheets and motion previews before installation.
- Refuse silent replacement, back up an existing matching id, and restore managed backups.

## Current status

| Area | Status |
| --- | --- |
| Plugin manifest and Git marketplace | Available |
| One-image Skin Studio v2 package | Available |
| Automatic palette, CSS, six previews, and QA | Available |
| Legacy skin v1 validation | Compatible |
| One-image desktop Pet Beta | Available |
| Pet package validation/install/restore | Available |
| Live Codex skin activation | Planned for 0.4 |
| Reversible Windows runtime | Planned for 0.4 |
| macOS runtime | Planned |

## Install

ChromaPaw requires a Codex build with plugin marketplace commands and Git available on `PATH`.

```bash
codex plugin marketplace add chromapaw/codex-chromapaw --ref main
codex plugin add codex-chromapaw@chromapaw
```

Restart Codex and open a new task so the three ChromaPaw skills are discovered. Attach an image and invoke `$create-chromapaw-skin` or `$create-chromapaw-pet`.

Animated pet generation additionally requires a compatible `hatch-pet` skill. ChromaPaw checks this dependency before generation and does not silently download or vendor it.

### Update

```bash
codex plugin marketplace upgrade chromapaw
codex plugin add codex-chromapaw@chromapaw
```

Restart Codex and use a new task after updating.

### Uninstall

```bash
codex plugin remove codex-chromapaw@chromapaw
codex plugin marketplace remove chromapaw
```

## Plugin skills

- `$create-chromapaw-skin` — create and validate a layered Skin Studio v2 package from one image.
- `$create-chromapaw-pet` — create, review, validate, and optionally install an animated Codex pet.
- `$manage-chromapaw` — inspect packages and use supported preview, activation, or recovery paths.

## Skin quick start

In Codex, attach one image and ask:

```text
Use $create-chromapaw-skin to turn this into a fresh summer beach theme.
Keep the beach, waves, sand, and coral visible around readable glass panels,
and generate both light and dark previews.
```

The skill inspects the reference, creates expanded environmental artwork when necessary, builds the package, and reviews all six variants. It will not claim that the skin is active.

From a repository checkout, build from existing full-scene artwork with the Codex workspace Python runtime:

```bash
python scripts/prepare_skin_request.py --image scene.png --mode adaptive --output-dir run
python scripts/build_skin_package.py --request run/skin-request.json --output-dir package --json
python scripts/validate_skin_package.py package --json
```

The builder requires Pillow, available in Codex's workspace runtime or installable from `requirements-skin.txt`. See [docs/SKIN_STUDIO_MVP.md](docs/SKIN_STUDIO_MVP.md) for the v2 output contract and review gates.

## Pet quick start

```text
Use $create-chromapaw-pet to make this my Codex pet. While a task is running,
have it dribble and shoot a basketball. When the task finishes, have it dance
with the basketball.
```

The skill prepares the request, delegates complete 8×11 generation and visual QA to `hatch-pet`, stages the package, and installs only after validation. Runtime timing remains controlled by Codex; requested behavior is mapped onto the closest supported animation rows.

For an already generated package:

```bash
python scripts/validate_pet_package.py path/to/pet-package --json
python scripts/install_pet.py path/to/pet-package --json
```

Replacing an existing id is explicit and creates a backup:

```bash
python scripts/install_pet.py path/to/pet-package --replace --json
python scripts/restore_pet.py backup-directory-name --replace --json
```

## Repository layout

```text
.agents/plugins/        Git-backed marketplace metadata
.codex-plugin/          Plugin manifest
skills/                 Codex workflows
scripts/                Deterministic package tooling
schemas/                Portable package schemas
tests/                  Validation tests
docs/                   Architecture and design notes
```

## Safety principles

- Never modify `WindowsApps` or the official Codex application archive.
- Back up user configuration before any future activation or restore operation.
- Keep skin generation separate from live activation.
- Do not silently upload user images or retain assets outside declared output locations.
- Treat loopback debugging interfaces as a security-sensitive fallback, not a default assumption.

## Development

Run checks with Python 3.10 or later. Skin builder tests require Pillow.

```bash
python -m unittest discover -s tests -v
python scripts/check_dependencies.py --json
python scripts/validate_pet_package.py --help
python scripts/validate_skin_package.py --help
python scripts/smoke_test_install.py --json
```

Plugin and skill structure should also be checked with the validators bundled with Codex's `plugin-creator` and `skill-creator` skills before release.

## License and trademark

Licensed under [Apache-2.0](LICENSE). ChromaPaw is an independent community project and is not affiliated with or endorsed by OpenAI. Codex and OpenAI product names belong to their respective owners.

## 中文说明

ChromaPaw 是一个面向 Codex 的开源个性化插件，目标是让用户只上传一张图片，就能生成：

- 带任务状态动画的 Codex 自定义宠物；
- 包含背景、海浪、沙滩、珊瑚等环境元素和立体层次的完整主题皮肤；
- 可预览、校验、备份与恢复的本地资产包。

当前 `0.3.0` 已完成 Skin Studio MVP：如果上传的是完整场景图，可以直接生成皮肤；如果只是人物、物体或风格参考，技能会先扩展成完整环境图，再自动提取浅色/深色配色，生成 3 套 CSS、6 张常见窗口比例预览、阅读安全区和 QA 报告。生成的 CSS 已内置宠物透明浮层隔离，避免宠物背后出现整块主题背景。

桌面宠物 Beta 也已可用：它通过兼容的 `hatch-pet` 工作流完成 8×11 精灵图和视觉 QA，并在安装前执行严格校验。同名宠物不会被静默覆盖，替换前会备份，之后可恢复。

需要注意：`0.3.0` 可以完整生成和验证皮肤包，但还不会直接把皮肤注入正在运行的 Codex。可逆、带版本检查的 Windows 激活运行时属于下一阶段 `0.4`。
