# Crabby

[English](#english) | [简体中文](#简体中文)

## English

Crabby is a local-first AI assistant for Obsidian. It combines an Obsidian chat plugin, a Python FastAPI backend, and an optional Electron desktop companion so one local vault can use LLM profiles, vault search, tools, MCP servers, personas, skills, session branches, attachments, and scheduled agent tasks.

It is designed for one machine, one local vault, and user-controlled configuration. It is not a cloud multi-user service.

### What It Includes

- **Obsidian plugin**: chat UI, settings, profile management, MCP config editing, session tree/fork UI, attachments, usage display, and Obsidian-hosted tools.
- **FastAPI backend**: provider calls, streaming, tool execution, MCP integration, prompt/persona/skill loading, sessions, token accounting, cron jobs, and admin APIs.
- **Desktop Pet**: an Electron companion surface that talks to the same backend for lightweight chat and notifications.

### Repository Layout

```text
server/             Python FastAPI backend
obsidian-plugin/    Obsidian plugin source and bundled main.js
desktop-pet/        Electron desktop companion
docs/               Product, architecture, session, provider, and roadmap docs
prompts/            Default prompt fragments
personas/           Runtime personas
skills/             Runtime skills
scripts/            Runtime build and release packaging helpers
```

### Requirements

- Obsidian Desktop
- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- Node.js and npm
- An LLM provider API key, or a local Ollama-compatible model
- For release packaging, a build machine matching the target OS/CPU architecture

### Development

Backend:

```bash
cd server
uv sync --dev
uv run python main.py
uv run pytest
uv run ruff check .
```

Obsidian plugin:

```bash
cd obsidian-plugin
npm ci
npm run test:config
npm run test:chat-content
npm run test:chat-styles
npx tsc --noEmit
npm run build
```

Desktop Pet:

```bash
cd desktop-pet
npm ci
npm run typecheck
npm run test
npm run build
```

### Manual Obsidian Release

The manual install package is a zip containing the Obsidian plugin files and a platform-specific backend binary. The plugin frontend is cross-platform; the bundled backend binary is not.

Build the backend runtime on the target platform:

```bash
cd server
uv sync --dev
uv run --with pyinstaller python ../scripts/build-backend-runtime.py --version 0.3.0
cd ..
```

Build the zip, for example for macOS Apple Silicon:

```bash
cd obsidian-plugin
npm ci
npm run build
cd ..
python scripts/package-obsidian-release.py --platform darwin --arch arm64
```

Expected output:

```text
dist/obsidian-plugin/crabby-0.3.0-darwin-arm64.zip
```

Install by extracting the zip to:

```text
<YourVault>/.obsidian/plugins/crabby/
```

User configuration, sessions, attachments, cron jobs, caches, and logs are stored
outside the plugin install directory at `<YourVault>/crabby/`, so the plugin
folder can be replaced during upgrades without deleting user data.

Then restart Obsidian, open `Settings -> Community plugins`, disable Restricted Mode if needed, and enable **Crabby**. On macOS or Linux, make the backend executable if your unzip tool did not preserve permissions:

```bash
chmod +x "<YourVault>/.obsidian/plugins/crabby/runtime/backend/0.3.0/darwin/crabby-backend"
```

### First Run

1. Open `Settings -> Crabby`.
2. Check the backend runtime status.
3. Create and activate an LLM profile.
4. Click **Test Current Profile**.
5. Open the Crabby chat view.

Plugin install files live under:

```text
<YourVault>/.obsidian/plugins/crabby/
  manifest.json
  main.js
  runtime/state.json
  runtime/host-heartbeat.json
  runtime/backend/
```

Plugin-managed user data lives under:

```text
<YourVault>/crabby/
  config/.env
  config/mcp_servers.json
  config/prompts/
  config/personas/
  data/sessions/
  data/attachments/
  data/cron_jobs.json
  data/cache/tool-results/
  logs/
```

Do not commit real API keys or private MCP configuration.

### Documentation

- [docs/项目能力概览.md](docs/项目能力概览.md): product capability overview
- [docs/architecture.md](docs/architecture.md): architecture and runtime flow
- [docs/技术路线.md](docs/技术路线.md): technical direction
- [docs/会话设计.md](docs/会话设计.md): session and branch design
- [docs/llm-provider-matrix.md](docs/llm-provider-matrix.md): provider presets
- [docs/execution-plan.md](docs/execution-plan.md): roadmap
- [docs/release-notes-0.3.0.md](docs/release-notes-0.3.0.md): Release 0.3.0 memory feature summary
- [AGENTS.md](AGENTS.md): maintainer and agent handoff

### Safety Notes

Crabby runs locally, but cloud LLM providers may receive user input, retrieved note snippets, and tool results. Tools such as `edit`, settings/profile management, `cron`, `bash`, and MCP servers can read or write local data depending on configuration. Enable write, shell, MCP, and background task capabilities only in a trusted local environment.

### License

MIT License. See [LICENSE](LICENSE).

## 简体中文

Crabby 是一个面向 Obsidian 的本地优先 AI 助手。它把 Obsidian 聊天插件、Python FastAPI 后端和可选的 Electron 桌面伴随入口组合起来，让一个本地 Vault 可以使用 LLM Profile、Vault 搜索、工具调用、MCP、Persona、Skill、会话分支、附件和后台定时 agent 任务。

它默认服务于一台本机、一个本地 Vault、用户自己掌控的配置和数据。Crabby 不是云端多用户服务。

### 包含什么

- **Obsidian 插件**：聊天 UI、设置页、Profile 管理、MCP 配置编辑、会话树/分支 UI、附件、usage 展示和 Obsidian 侧工具。
- **FastAPI 后端**：Provider 调用、流式输出、工具执行、MCP 集成、Prompt/Persona/Skill 加载、会话、Token 统计、Cron 任务和管理 API。
- **Desktop Pet**：复用同一后端的 Electron 桌面入口，用于轻量聊天和通知。

### 项目结构

```text
server/             Python FastAPI 后端
obsidian-plugin/    Obsidian 插件源码和构建后的 main.js
desktop-pet/        Electron 桌面伴随客户端
docs/               产品、架构、会话、Provider 和路线图文档
prompts/            默认 prompt fragments
personas/           Runtime Persona
skills/             Runtime Skill
scripts/            Runtime 构建和发布打包脚本
```

### 前置要求

- Obsidian Desktop
- Python 3.11+ 和 [`uv`](https://docs.astral.sh/uv/)
- Node.js 和 npm
- 一个 LLM Provider API key，或本地 Ollama-compatible 模型
- 如需打包发布，需要一台与目标系统/CPU 架构一致的构建机器

### 本地开发

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

### 手动 Obsidian 发布包

手动安装包是一个 zip，里面包含 Obsidian 插件文件和平台专属后端二进制。插件前端跨平台，但打包进去的后端二进制不跨平台。

先在目标平台构建后端 runtime：

```bash
cd server
uv sync --dev
uv run --with pyinstaller python ../scripts/build-backend-runtime.py --version 0.3.0
cd ..
```

再构建 zip，下面以 macOS Apple Silicon 为例：

```bash
cd obsidian-plugin
npm ci
npm run build
cd ..
python scripts/package-obsidian-release.py --platform darwin --arch arm64
```

预期输出：

```text
dist/obsidian-plugin/crabby-0.3.0-darwin-arm64.zip
```

安装时把 zip 解压到：

```text
<YourVault>/.obsidian/plugins/crabby/
```

然后重启 Obsidian，打开 `Settings -> Community plugins`，必要时关闭 Restricted Mode，并启用 **Crabby**。macOS 或 Linux 下，如果解压工具没有保留执行权限，运行：

```bash
chmod +x "<YourVault>/.obsidian/plugins/crabby/runtime/backend/0.3.0/darwin/crabby-backend"
```

### 首次运行

1. 打开 `Settings -> Crabby`。
2. 检查 **本地后端程序** 状态。手动安装包已内置后端程序时，通常不需要填写 **后端程序下载清单 URL** 或点击安装。
3. 创建并激活一个 LLM Profile。
4. 点击 **Test Current Profile**。
5. 打开 Crabby chat view。

插件托管的本地后端程序文件位于：

```text
<YourVault>/.obsidian/plugins/crabby/
  manifest.json
  main.js
  runtime/state.json
  runtime/host-heartbeat.json
  runtime/backend/
```

插件托管的用户数据位于：

```text
<YourVault>/crabby/
  config/.env
  config/mcp_servers.json
  config/prompts/
  config/personas/
  data/sessions/
  data/attachments/
  data/cron_jobs.json
  data/cache/tool-results/
  logs/
```

不要提交真实 API key 或私有 MCP 配置。

### 文档入口

- [docs/项目能力概览.md](docs/项目能力概览.md)：产品能力概览
- [docs/architecture.md](docs/architecture.md)：架构和运行时流程
- [docs/技术路线.md](docs/技术路线.md)：技术方向
- [docs/会话设计.md](docs/会话设计.md)：会话和分支设计
- [docs/llm-provider-matrix.md](docs/llm-provider-matrix.md)：Provider 预设
- [docs/execution-plan.md](docs/execution-plan.md)：路线图
- [AGENTS.md](AGENTS.md)：维护者和 agent 接手说明

### 安全边界

Crabby 在本地运行，但使用云端 LLM 时，用户输入、检索到的笔记片段和工具结果可能发送给 Provider。`edit`、settings/profile、`cron`、`bash` 和 MCP server 等能力可能读取或写入本地数据。请只在可信本地环境中启用写入、shell、MCP 和后台任务能力。

### License

MIT License. See [LICENSE](LICENSE).
