# Crabby

Crabby 是一个围绕本地 Obsidian Vault 构建的 AI 助手。它把 Obsidian 聊天、Vault 搜索、LLM Profile、工具调用、MCP、Persona、Skill、会话分支、定时任务和桌面伴随入口组合成一个本地优先的个人助理系统。

它的默认使用场景很明确：一台本机、一个本地 Vault、用户自己掌控的配置和数据。

## 适合先了解什么

如果你第一次接触 Crabby，可以按这个顺序看：

1. 先读本文，了解项目是什么、怎么运行、怎么安装。
2. 再读 [docs/项目能力概览.md](docs/项目能力概览.md)，看完整产品能力。
3. 如果要维护代码，继续读 [docs/architecture.md](docs/architecture.md) 和 [AGENTS.md](AGENTS.md)。

## Crabby 能做什么

- **在 Obsidian 里聊天**：支持流式回复、工具状态、reasoning 展示、图片附件、上下文占用、当前回合 usage、session 累计 usage、历史恢复和 conversation 分支。
- **搜索和使用 Vault**：通过 `obsidian_search` 使用接近 Obsidian Search 的语义检索 `.md` 和 `.canvas` 文件，也可以用 `read`、`edit`、`grep`、`glob`、`task_query` 等工具处理本地内容。
- **管理多个 LLM Provider**：通过 LLM Profile 保存 provider、model、API key、base URL、vision、thinking/reasoning 等设置。
- **切换工作人格**：内置 secretary、archivist、researcher、philosopher、mentor 等 Persona，也支持 Auto / Manual / None 模式。
- **使用 Skill 行为指南**：用 `SKILL.md` 描述某类任务的处理方法，用户可通过 slash command 指定当前回合 Skill。
- **连接 MCP 工具生态**：支持 `stdio` 和 `sse` MCP server，插件设置页可编辑配置并触发 reload。
- **创建后台定时任务**：通过 Cron 工具让助手在未来时间点执行隔离 agent 回合，并把结果通知回源 session。
- **使用 Desktop Pet**：Electron 桌面伴随客户端复用同一个后端，提供轻量聊天、气泡和通知入口。
- **打包私有发布版**：把 Obsidian 插件和平台专属后端二进制打成一个手动安装 zip。

## 项目结构

```text
server/             Python FastAPI 后端
obsidian-plugin/    Obsidian 插件源码和构建后的 main.js
desktop-pet/        Electron Desktop Pet
docs/               产品、架构、路线图和设计文档
prompts/            默认 prompt fragments
personas/           Runtime Persona 定义
skills/             Runtime Skill 定义
scripts/            构建和发布辅助脚本
```

## 前置要求

- Obsidian Desktop。Crabby 是 desktop-only 插件，因为它需要管理本地后端进程。
- Python 3.11+ 和 [`uv`](https://docs.astral.sh/uv/)。
- Node.js 和 npm。
- 一个可用的 LLM Provider API key，或本地 Ollama-compatible 模型。
- 如果要打包发布，需要一台和目标系统/CPU 架构一致的构建机器。打包脚本不会跨平台编译后端二进制。

## 本地开发

后端：

```bash
cd server
uv sync --dev
uv run python main.py
uv run pytest
uv run ruff check .
```

Obsidian 插件：

```bash
cd obsidian-plugin
npm ci
npm run test:config
npm run test:chat-content
npm run test:chat-styles
npx tsc --noEmit
npm run build
```

Desktop Pet：

```bash
cd desktop-pet
npm ci
npm run typecheck
npm run test
npm run build
```

## 手动发布包

Crabby 当前支持私有手动安装包：一个 zip 里同时包含 Obsidian 插件前端和预构建的后端可执行文件。

插件前端本身跨平台，但后端二进制不跨平台。你需要按目标系统和 CPU 架构分别构建。

下面以 macOS Apple Silicon、版本 `0.1.0` 为例。

先在目标平台构建后端 runtime：

```bash
cd server
uv sync --dev
uv run --with pyinstaller python ../scripts/build-backend-runtime.py --version 0.1.0
cd ..
```

macOS 下预期输出：

```text
dist/backend-runtime/0.1.0/darwin/crabby-backend
```

再构建手动安装 zip：

```bash
cd obsidian-plugin
npm ci
npm run build
cd ..
python scripts/package-obsidian-release.py --platform darwin --arch arm64
```

预期输出：

```text
dist/obsidian-plugin/crabby-0.1.0-darwin-arm64.zip
```

包内结构：

```text
crabby/
  manifest.json
  main.js
  runtime/
    state.json
    backend/
      0.1.0/
        darwin/
          crabby-backend
```

`runtime/state.json` 会把后端可执行文件路径记录为相对 `runtime/` 的路径，所以插件目录可以跟随 Vault 移动。

## 在 Obsidian 中安装

1. 把 zip 解压到 `<YourVault>/.obsidian/plugins/`。
2. 确认最终路径是 `<YourVault>/.obsidian/plugins/crabby/manifest.json`。
3. macOS 或 Linux 下，如果解压工具没有保留执行权限，运行：

   ```bash
   chmod +x "<YourVault>/.obsidian/plugins/crabby/runtime/backend/0.1.0/darwin/crabby-backend"
   ```

4. 重启 Obsidian。
5. 打开 `Settings -> Community plugins`。
6. 如有需要，关闭 Restricted Mode。
7. 启用 **Crabby**。

启用后，插件会读取 `runtime/state.json`，在后台启动本地 backend，写入 host heartbeat，并在可能时复用健康的 managed backend。

## 首次运行

1. 打开 `Settings -> Crabby`。
2. 检查 backend runtime 状态。
3. 创建一个 LLM Profile，选择 provider 和 model，填入 API key 或本地 base URL。
4. 保存并激活 profile。
5. 点击 **Test Current Profile**。
6. 打开 Crabby chat view 开始使用。

插件托管的密钥和运行时设置在：

```text
<YourVault>/.obsidian/plugins/crabby/config/.env
```

这个文件只应保留在本地，不要提交真实 API key。

## 运行时数据

插件托管安装时，Crabby 会在插件目录下维护运行时文件：

```text
<YourVault>/.obsidian/plugins/crabby/
  config/.env
  config/mcp_servers.json
  config/prompts/
  config/personas/
  data/sessions/
  data/attachments/
  logs/
  runtime/state.json
  runtime/host-heartbeat.json
```

Cron jobs 存在 Vault 内：

```text
<YourVault>/.Crabby/data/cron_jobs.json
```

## 文档入口

- [docs/项目能力概览.md](docs/项目能力概览.md)：第一次了解项目时先读。
- [docs/architecture.md](docs/architecture.md)：当前架构和运行时流程。
- [docs/技术路线.md](docs/技术路线.md)：维护者技术路线。
- [docs/会话设计.md](docs/会话设计.md)：session、conversation、branch cache 和 fork 设计。
- [docs/llm-provider-matrix.md](docs/llm-provider-matrix.md)：内置 provider preset。
- [docs/execution-plan.md](docs/execution-plan.md)：发布路线图。
- [AGENTS.md](AGENTS.md)：维护者和 agent 接手说明。

## License

MIT License. See [LICENSE](LICENSE).

## 常见排障

- **打包时找不到后端二进制**：先运行 backend runtime 构建命令，或给 `scripts/package-obsidian-release.py` 传入 `--backend-binary <path>`。
- **启用插件后 backend 没启动**：查看已安装插件目录下 `logs/` 里的 `runtime-manager.log`、`backend-out.log` 和 `backend-error.log`。
- **macOS 阻止后端运行**：确认文件有执行权限；如果 zip 来自浏览器或聊天工具，还可以清理 quarantine：

  ```bash
  xattr -dr com.apple.quarantine "<YourVault>/.obsidian/plugins/crabby"
  ```

- **一台机器能用，另一台机器不能用**：请在目标 CPU 架构上重新构建后端 runtime，或为 `arm64` 和 `x64` 分别发布包。
- **聊天界面能打开，但模型调用失败**：检查 active LLM profile、API key、base URL、model name，以及 **Test Current Profile** 的结果。

## 安全边界

Crabby 不是云端多用户 SaaS。它是本地自动化助手，会把你配置给它的上下文发送给你选择的 LLM provider。

需要特别注意：

- 使用云端 LLM 时，用户输入、检索到的笔记片段和工具结果可能发送给 provider。
- `edit`、settings/profile、Cron 等工具具备写入能力。
- 启用 `bash` 后，模型具备非交互式 shell 能力。
- MCP server 的实际能力取决于你配置的外部 server。

请只在可信本地环境中启用写入、shell、MCP 和后台任务能力。
