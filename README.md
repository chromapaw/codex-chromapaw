# ChromaPaw for Codex

Turn one image into a custom Codex skin or animated pet.

> Version 0.4.0 adds an experimental, reversible Windows skin runtime. Skin and pet generation are available; live skin activation is limited to exact, isolated-live-verified Codex versions and is not an official OpenAI skin API.

[中文说明](#中文说明) · [Windows Runtime Beta](docs/WINDOWS_RUNTIME_BETA.md) · [Skin Studio](docs/SKIN_STUDIO_MVP.md) · [Pet MVP](docs/PET_MVP.md) · [Roadmap](ROADMAP.md) · [Architecture](docs/ARCHITECTURE.md)

## Vision

1. Upload one reference image in Codex.
2. Choose **Pet** or **Skin**.
3. Preview and review the generated result.
4. Validate it before installation or activation.
5. Switch or restore safely.

## Current status

| Area | Status |
| --- | --- |
| Plugin manifest and Git marketplace | Available |
| One-image Skin Studio v2 package | Available |
| Automatic palette, CSS, six previews, and QA | Available |
| One-image desktop Pet Beta | Available |
| Pet validation, install, backup, and restore | Available |
| Reversible Windows skin runtime | Experimental Beta for exact verified versions |
| Official AppX `26.803.5235.0` | Discoverable; activation disabled |
| macOS runtime | Planned |

## Capabilities

### Skin Studio

- Turn full environment artwork directly into a skin, or expand a character/object reference into complete environmental artwork first.
- Extract accessible light and dark palettes and generate light, dark, and adaptive CSS.
- Render six visual-QA previews across three common window ratios.
- Record safe content zones, four depth layers, attribution, and structured QA.
- Isolate Codex's transparent avatar overlay so the skin does not become a rectangle behind a pet.
- Export a portable schemaVersion 2 package independently from runtime compatibility.

### Animated pets

- Preserve the subject's silhouette, palette, face, clothing, and props.
- Map task intent such as working, waiting, ready, and failed onto Codex-compatible animation rows.
- Build and visually validate an 8×11 desktop v2 atlas through a compatible installed `hatch-pet` workflow.
- Refuse silent replacement, back up an existing matching id, and restore managed backups.

### Windows Runtime Beta

- Discover local standalone and AppX Codex candidates.
- Fail closed on unknown or recognized-but-disabled versions.
- Validate the package, exact executable version, executable hash, adapter identity, and running processes before launch.
- Launch a supported Codex build with an ephemeral CDP endpoint bound only to `127.0.0.1`.
- Inject skin CSS into eligible `app://` pages without changing `WindowsApps`, `app.asar`, or signed application files.
- Keep delayed windows such as the pet overlay synchronized with a disclosed local monitor.
- Verify, stop, and restore the session, terminate only the runtime-launched process tree, and confirm that the debugging port closed.

The runtime uses an experimental Electron interface because Codex does not document a public desktop skin API. Read [docs/WINDOWS_RUNTIME_BETA.md](docs/WINDOWS_RUNTIME_BETA.md) before activation.

## Install

ChromaPaw requires a Codex build with plugin marketplace commands and Git on `PATH`.

```bash
codex plugin marketplace add chromapaw/codex-chromapaw --ref main
codex plugin add codex-chromapaw@chromapaw
```

Restart Codex and open a new task so the three ChromaPaw skills are discovered. Attach an image and invoke `$create-chromapaw-skin` or `$create-chromapaw-pet`.

Animated pet generation additionally requires a compatible `hatch-pet` skill. ChromaPaw checks this dependency and does not silently download or vendor it.

### Update

```bash
codex plugin marketplace upgrade chromapaw
codex plugin add codex-chromapaw@chromapaw
```

Restart Codex and use a new task after updating.

### Uninstall

Restore any active Windows runtime session before uninstalling:

```bash
python scripts/windows_runtime.py --json status
python scripts/windows_runtime.py --json restore
codex plugin remove codex-chromapaw@chromapaw
codex plugin marketplace remove chromapaw
```

## Plugin skills

- `$create-chromapaw-skin` — create and validate a layered Skin Studio v2 package from one image.
- `$create-chromapaw-pet` — create, review, validate, and optionally install an animated Codex pet.
- `$manage-chromapaw` — inspect packages and use supported activation, verification, and recovery paths.

## Skin quick start

```text
Use $create-chromapaw-skin to turn this into a fresh summer beach theme.
Keep the beach, waves, sand, and coral visible around readable glass panels,
and generate both light and dark previews.
```

From a repository checkout, build and validate a package:

```bash
python scripts/prepare_skin_request.py --image scene.png --mode adaptive --output-dir run
python scripts/build_skin_package.py --request run/skin-request.json --output-dir package --json
python scripts/validate_skin_package.py package --json
```

The builder requires Pillow, available in Codex's workspace runtime or installable from `requirements-skin.txt`.

## Pet quick start

```text
Use $create-chromapaw-pet to make this my Codex pet. While a task is running,
have it dribble and shoot a basketball. When the task finishes, have it dance
with the basketball.
```

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

## Windows runtime quick start

Run these commands from a trusted repository checkout. Do not activate until `preflight` reports an enabled exact-version adapter and the selected executable is closed.

```bash
python scripts/windows_runtime.py --json discover
python scripts/windows_runtime.py --json preflight path/to/skin-package --executable "C:\\path\\to\\ChatGPT.exe"
python scripts/windows_runtime.py --json activate path/to/skin-package --executable "C:\\path\\to\\ChatGPT.exe" --acknowledge-experimental-runtime
python scripts/windows_runtime.py --json verify
python scripts/windows_runtime.py --json restore
```

Activation launches a separate Codex process owned by the runtime. Restore stops that process so the unauthenticated loopback CDP endpoint cannot remain open. `--allow-parallel-profile` is for isolated compatibility testing only.

## Repository layout

```text
.agents/plugins/        Git-backed marketplace metadata
.codex-plugin/          Plugin manifest
skills/                 Codex workflows
scripts/                Deterministic package and runtime tooling
runtime/                Exact-version adapter registry
schemas/                Portable package and adapter schemas
tests/                  Unit and compatibility-fixture tests
docs/                   Architecture, security, and operating guides
```

## Safety principles

- Never modify `WindowsApps`, `app.asar`, or signed Codex application files.
- Keep image/package generation separate from live activation.
- Require explicit experimental-runtime acknowledgment for activation.
- Bind CDP to a random loopback port, disclose the monitor, and close both during restore.
- Preserve user configuration changes; only a known volatile Codex session key may be restored when every other config line is unchanged.
- Do not silently upload user images or retain assets outside declared output locations.

## Development

Use Python 3.10 or later. Skin builder tests require Pillow.

```bash
python -m unittest discover -s tests -v
python scripts/check_dependencies.py --json
python scripts/windows_runtime.py --json discover
python scripts/smoke_test_install.py --json
```

Plugin and skill structure must also pass the validators bundled with Codex's `plugin-creator` and `skill-creator` skills before release.

## License and trademark

Licensed under [Apache-2.0](LICENSE). ChromaPaw is an independent community project and is not affiliated with or endorsed by OpenAI. Codex and OpenAI product names belong to their respective owners.

## 中文说明

ChromaPaw 是一个面向 Codex 的开源个性化插件。目标是让用户只上传一张图片，就能生成：

- 带任务状态动画的 Codex 自定义宠物；
- 包含海滩、海浪、沙滩、珊瑚等环境元素和立体层次的完整主题皮肤；
- 可预览、校验、备份与恢复的本地资源包。

`0.4.0` 已完成皮肤包生成、宠物生成与实验性 Windows 皮肤运行时。运行时不会修改 `WindowsApps`、`app.asar` 或签名文件，而是启动一个受版本白名单约束的 Codex 进程，通过仅绑定本机随机端口的实验性接口注入皮肤，并在还原时关闭该进程、后台监控和端口。

需要注意：这不是 OpenAI 官方皮肤 API。只有经过隔离实测的精确 Codex 版本才允许激活；未知版本以及当前已识别但未通过启动验证的官方 AppX 版本都会安全拒绝。宠物包仍可正常生成、安装和恢复，皮肤包也可正常生成和预览，这两部分不依赖实验性运行时。
