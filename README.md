# ChromaPaw for Codex

Turn one image into a custom Codex skin or animated pet.

> Version 0.2 ships the desktop Pet MVP. Visual generation and QA use Codex's installed `hatch-pet` workflow; rich background skins remain portable packages until a reversible runtime is available.

[中文说明](#中文说明) · [Pet MVP](docs/PET_MVP.md) · [Roadmap](ROADMAP.md) · [Architecture](docs/ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md)

## Vision

ChromaPaw aims to make Codex customization approachable to everyone:

1. Upload one reference image in Codex.
2. Choose **Pet** or **Skin**.
3. Preview the generated result.
4. Validate it before installation.
5. Switch or restore safely.

## Capabilities

### Animated pets

- Preserve the subject's recognizable silhouette, palette, face, clothing, and props.
- Generate task-aware animation states such as working, waiting, ready, and failed.
- Build and validate a Codex-compatible desktop v2 pet package.
- Produce contact sheets and motion previews before installation.
- Refuse silent replacement, back up an existing matching id, and restore managed backups.

### Layered skins

- Expand a single image into a complete visual environment instead of applying a flat color.
- Generate background, atmosphere, foreground decorations, safe content zones, and readable glass surfaces.
- Export a portable skin package with metadata, CSS, preview, and source attribution.
- Keep activation separate from generation so unsupported Codex versions fail safely.

## Current status

Version `0.2.0` adds the one-image desktop Pet MVP: normalized animation intent, the supported full v2 hatch workflow, a strict package validator, and reversible local installation. A production skin runtime is intentionally not included yet.

| Area | Status |
| --- | --- |
| Plugin manifest and skill routing | Available |
| One-image desktop Pet MVP | Available |
| Pet package validation/install/restore | Available |
| Skin package generation contract | Initial workflow |
| Skin package validator | Available |
| Live Codex skin activation | Planned |
| Windows runtime | Planned |
| macOS runtime | Planned |

## Plugin skills

- `$create-chromapaw-pet` — create and validate an animated Codex pet from an image.
- `$create-chromapaw-skin` — create a layered, portable skin package from an image.
- `$manage-chromapaw` — inspect packages and use safe preview, activation, or recovery paths.

## Pet quick start

In Codex, attach one character image and ask:

```text
Use $create-chromapaw-pet to make this my Codex pet. While a task is running,
have it dribble and shoot a basketball. When the task finishes, have it dance
with the basketball.
```

The skill prepares the request, delegates the complete 8×11 animation workflow to `hatch-pet`, presents QA media, stages the package, and installs only after validation. Exact runtime state timing remains controlled by Codex; the requested actions are mapped onto the closest supported animation rows.

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

See [docs/PET_MVP.md](docs/PET_MVP.md) for the package contract and limitations.

## Repository layout

```text
.codex-plugin/          Plugin manifest
skills/                 Codex workflows
scripts/                Deterministic package tooling
schemas/                Portable package schemas
tests/                  Validation tests
docs/                   Architecture and design notes
```

## Safety principles

- Never modify `WindowsApps` or the official Codex application archive.
- Back up user configuration before any activation or restore operation.
- Keep rich-skin activation reversible and version-gated.
- Do not silently upload user images or retain generated assets outside declared output locations.
- Treat loopback debugging interfaces as a security-sensitive fallback, not a default assumption.

## Development

Run the repository checks with Python 3.10 or later:

```bash
python -m unittest discover -s tests -v
python scripts/validate_pet_package.py --help
python scripts/validate_skin_package.py --help
```

Plugin and skill structure should also be checked with the validators bundled with Codex's `plugin-creator` and `skill-creator` skills before release.

## License and trademark

Licensed under [Apache-2.0](LICENSE). ChromaPaw is an independent community project and is not affiliated with or endorsed by OpenAI. Codex and OpenAI product names belong to their respective owners.

## 中文说明

ChromaPaw 是一个面向 Codex 的开源个性化工坊，目标是让用户只上传一张图片，就能生成：

- 带任务状态动画的 Codex 自定义宠物；
- 包含背景、环境元素、前景装饰和半透明面板的完整主题皮肤；
- 可以预览、验证、切换和恢复的本地资产包。

当前 `0.2.0` 已实现桌面宠物 MVP：上传一张参考图后，可以整理工作中、等待、完成和失败等动作意图，调用完整的 Codex v2 宠物生成与 QA 流程，并在安装前校验 `8×11` 精灵图。安装同名宠物时必须明确确认，旧版本会先备份，之后可以恢复。

例如，你可以直接说：“任务进行时让它拍篮球，任务完成后让它用篮球跳舞。”ChromaPaw 会把这些要求映射到 Codex 支持的动画行；任务状态本身仍由 Codex 控制。

完整主题皮肤的生成规范已经存在，但实时应用皮肤的可逆运行时仍将在后续版本中实现。
