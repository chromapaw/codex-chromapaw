# ChromaPaw for Codex

Turn one image into a custom Codex skin or animated pet.

> Early-stage open-source project. Pet generation is designed around Codex's supported custom-pet workflow. Rich background skins are packaged separately and will only be activated through a reversible local runtime.

[中文说明](#中文说明) · [Roadmap](ROADMAP.md) · [Architecture](docs/ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md)

## Vision

ChromaPaw aims to make Codex customization approachable to everyone:

1. Upload one reference image in Codex.
2. Choose **Pet** or **Skin**.
3. Preview the generated result.
4. Validate it before installation.
5. Switch or restore safely.

## Planned capabilities

### Animated pets

- Preserve the subject's recognizable silhouette, palette, face, clothing, and props.
- Generate task-aware animation states such as working, waiting, ready, and failed.
- Build and validate a Codex-compatible local pet package.
- Produce contact sheets and motion previews before installation.

### Layered skins

- Expand a single image into a complete visual environment instead of applying a flat color.
- Generate background, atmosphere, foreground decorations, safe content zones, and readable glass surfaces.
- Export a portable skin package with metadata, CSS, preview, and source attribution.
- Keep activation separate from generation so unsupported Codex versions fail safely.

## Current status

Version `0.1.0` establishes the plugin manifest, three focused skills, the skin-package contract, validation scripts, documentation, and automated tests. A production skin runtime is intentionally not included yet.

| Area | Status |
| --- | --- |
| Plugin manifest and skill routing | Available |
| Pet creation workflow | Initial workflow |
| Skin package generation contract | Initial workflow |
| Package validator | Available |
| Live Codex skin activation | Planned |
| Windows runtime | Planned |
| macOS runtime | Planned |

## Plugin skills

- `$create-chromapaw-pet` — create and validate an animated Codex pet from an image.
- `$create-chromapaw-skin` — create a layered, portable skin package from an image.
- `$manage-chromapaw` — inspect packages and use safe preview, activation, or recovery paths.

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

当前 `0.1.0` 是项目基础版本：已经建立插件结构、三项核心技能、皮肤包规范、验证脚本与自动化测试。完整皮肤运行时将在后续版本中实现。
