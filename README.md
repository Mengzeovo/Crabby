# Life Assistant Agent

Life Assistant Agent 是一个围绕 Obsidian Vault 构建的本地 AI 助手。它由三部分组成：

- Python FastAPI 后端：负责 LLM 调用、工具执行、MCP 集成、会话、附件、定时任务和运行时配置。
- Obsidian TypeScript 插件：负责聊天 UI、设置页、后端生命周期管理、MCP 配置和 Obsidian 客户端工具桥接。
- Electron desktop pet：轻量桌面入口，复用同一个后端会话能力。

## Repository Layout

```text
server/             Python backend
obsidian-plugin/    Obsidian plugin source and built main.js
desktop-pet/        Electron desktop companion
docs/               Architecture and design notes
prompts/            Default prompt templates
personas/           Runtime persona assets
skills/             Runtime skill assets
scripts/            Build and release helper scripts
```

## Development

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
npx tsc --noEmit
npm run build
```

Desktop pet:

```bash
cd desktop-pet
npm ci
npm run typecheck
npm run test
npm run build
```

## Private Obsidian Release Package

For private/manual installation, the release artifact is a zip containing both the Obsidian plugin frontend and a prebuilt backend binary.

Current private target: macOS Apple Silicon (`darwin arm64`), version `0.1.0`.

### 1. Clone

```bash
git clone <your-repo>
cd LifeAssistantAgent
```

### 2. Build The Backend Runtime

Run this on the target platform. For the macOS Apple Silicon package, run it on an Apple Silicon Mac:

```bash
cd server
uv sync --dev
uv run --with pyinstaller python ../scripts/build-backend-runtime.py --version 0.1.0
cd ..
```

Expected backend binary:

```text
dist/backend-runtime/0.1.0/darwin/life-assistant-backend
```

### 3. Install Plugin Dependencies

```bash
cd obsidian-plugin
npm ci
cd ..
```

### 4. Build The Manual Install Zip

```bash
python scripts/package-obsidian-release.py --platform darwin --arch arm64
```

Output:

```text
dist/obsidian-plugin/life-assistant-agent-0.1.0-darwin-arm64.zip
```

The zip contains:

```text
life-assistant-agent/
  manifest.json
  main.js
  runtime/
    state.json
    backend/
      0.1.0/
        darwin/
          life-assistant-backend
```

`runtime/state.json` stores the backend executable path relative to the plugin runtime directory, so the plugin folder can move with the vault across machines.

## Manual Installation In Obsidian

1. Locate the target vault.
2. Unzip `life-assistant-agent-0.1.0-darwin-arm64.zip` into:

```text
<YourVault>/.obsidian/plugins/
```

The final structure must be:

```text
<YourVault>/.obsidian/plugins/life-assistant-agent/manifest.json
<YourVault>/.obsidian/plugins/life-assistant-agent/main.js
<YourVault>/.obsidian/plugins/life-assistant-agent/runtime/state.json
```

3. On macOS, ensure the backend binary is executable if the unzip tool did not preserve permissions:

```bash
chmod +x "<YourVault>/.obsidian/plugins/life-assistant-agent/runtime/backend/0.1.0/darwin/life-assistant-backend"
```

4. Restart Obsidian.
5. Open `Settings -> Community plugins`.
6. Disable Restricted mode if needed.
7. Enable `Life Assistant Agent`.

The plugin will read `runtime/state.json`, resolve the relative backend executable path, and start the bundled backend.

## Notes

- Running `scripts/build-backend-runtime.py` on Windows creates a Windows backend binary; running it on macOS creates a macOS backend binary.
- The Obsidian frontend (`manifest.json` and `main.js`) is cross-platform, but the bundled backend binary is platform-specific.
- The private package flow does not require a runtime manifest URL or a temporary static server.
