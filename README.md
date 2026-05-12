# Crabby

<a href="#english">English</a> | <a href="#chinese">简体中文</a>

---

<h2 id="english">🇬🇧 English</h2>

**Crabby** is a local AI assistant built around an Obsidian Vault. It consists of three core components:

- **Python FastAPI Backend**: Handles LLM API calls, tool execution, MCP (Model Context Protocol) integration, session management, file attachments, cron jobs, and runtime configuration.
- **Obsidian TypeScript Plugin**: Provides the main chat UI, settings panel, backend lifecycle management, MCP configuration, and bridges Obsidian client capabilities to the backend.
- **Electron Desktop Pet**: A lightweight desktop companion that reuses the same backend session for seamless interactions outside Obsidian.

### Repository Layout

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

### Development

**Backend:**
```bash
cd server
uv sync --dev
uv run python main.py
uv run pytest
uv run ruff check .
```

**Obsidian Plugin:**
```bash
cd obsidian-plugin
npm ci
npm run test:config
npx tsc --noEmit
npm run build
```

**Desktop Pet:**
```bash
cd desktop-pet
npm ci
npm run typecheck
npm run test
npm run build
```

### Private Obsidian Release Package

For private or manual installation, the release artifact is a zip archive containing both the Obsidian plugin frontend and a pre-built backend binary.

*Current private target example: macOS Apple Silicon (`darwin arm64`), version `0.1.0`.*

#### 1. Clone
```bash
git clone <your-repo>
cd Crabby
```

#### 2. Build The Backend Runtime
Run this on the target platform (e.g., on an Apple Silicon Mac for `darwin arm64`):
```bash
cd server
uv sync --dev
uv run --with pyinstaller python ../scripts/build-backend-runtime.py --version 0.1.0
cd ..
```
*Expected backend binary: `dist/backend-runtime/0.1.0/darwin/crabby-backend`*

#### 3. Install Plugin Dependencies
```bash
cd obsidian-plugin
npm ci
cd ..
```

#### 4. Build The Manual Install Zip
```bash
python scripts/package-obsidian-release.py --platform darwin --arch arm64
```
*Output: `dist/obsidian-plugin/crabby-0.1.0-darwin-arm64.zip`*

The zip contains:
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
*`runtime/state.json` stores the backend executable path relative to the plugin directory, allowing the plugin folder to be moved with the vault across machines.*

### Manual Installation In Obsidian

1. Locate your target vault.
2. Unzip `crabby-0.1.0-darwin-arm64.zip` into `<YourVault>/.obsidian/plugins/`. Ensure the final structure looks like this:
   ```text
   <YourVault>/.obsidian/plugins/crabby/manifest.json
   <YourVault>/.obsidian/plugins/crabby/main.js
   <YourVault>/.obsidian/plugins/crabby/runtime/state.json
   ...
   ```
3. *(macOS/Linux only)* Ensure the backend binary is executable if your unzip tool didn't preserve permissions:
   ```bash
   chmod +x "<YourVault>/.obsidian/plugins/crabby/runtime/backend/0.1.0/darwin/crabby-backend"
   ```
4. Restart Obsidian.
5. Open `Settings -> Community plugins`.
6. Disable "Restricted mode" if necessary.
7. Enable **Crabby**.

The plugin will read `runtime/state.json`, resolve the relative backend path, and lazily boot up the bundled backend server.

### Notes
- Running `scripts/build-backend-runtime.py` on Windows creates a Windows backend executable (`.exe`); running it on macOS creates a macOS executable.
- The Obsidian frontend (`manifest.json` and `main.js`) is cross-platform, but the bundled backend binary is platform-specific.
- This private packaging workflow does not require a remote URL manifest or a temporary static server.

<br/>
<br/>

<h2 id="chinese">🇨🇳 简体中文</h2>

**Crabby** 是一个基于 Obsidian Vault 知识库构建的本地 AI 助手。项目主要由以下三部分组成：

- **Python FastAPI 后端**：负责提供 LLM 调用、工具执行、MCP (Model Context Protocol) 集成、会话管理、附件支持、定时任务（Cron）和运行时配置等核心功能。
- **Obsidian TypeScript 插件**：负责提供 Obsidian 内部的聊天 UI、设置页面、后端的生命周期管理、MCP 配置编辑器，并将部分 Obsidian 的客户端能力桥接给后端工具引用。
- **Electron 桌面宠物 (Desktop Pet)**：轻一点的桌面交互入口，与 Obsidian 插件复用同一个后端会话上下文。

### 代码仓库结构

```text
server/             后端服务 (Python)
obsidian-plugin/    Obsidian 插件源码及编译后的 main.js
desktop-pet/        Electron 桌搭应用
docs/               架构和设计文档
prompts/            默认角色/系统提示词模板
personas/           运行时人格扩展包
skills/             内置 AI 技能脚本
scripts/            用于构建和打包的辅助脚本
```

### 本地开发

**后端 (Backend)：**
```bash
cd server
uv sync --dev
uv run python main.py
uv run pytest
uv run ruff check .
```

**Obsidian 插件：**
```bash
cd obsidian-plugin
npm ci
npm run test:config
npx tsc --noEmit
npm run build
```

**桌面宠物 (Desktop Pet)：**
```bash
cd desktop-pet
npm ci
npm run typecheck
npm run test
npm run build
```

### 私有化 Obsidian 发布打包

针对私有库或手动安装，我们会将前端插件和预编译的后端可执行文件一并打包到一个 Zip 中。

*当前的默认打包目标示例：macOS Apple Silicon (`darwin arm64`)，版本 `0.1.0`。*

#### 1. 克隆代码
```bash
git clone <your-repo>
cd Crabby
```

#### 2. 构建后端 Runtime 二进制文件
需要在对应平台上运行，例如需要打包 M1 版本则需要在 Apple Silicon Mac 上运行：
```bash
cd server
uv sync --dev
uv run --with pyinstaller python ../scripts/build-backend-runtime.py --version 0.1.0
cd ..
```
*预期输出二进制位置：`dist/backend-runtime/0.1.0/darwin/crabby-backend`*

#### 3. 安装插件依赖
```bash
cd obsidian-plugin
npm ci
cd ..
```

#### 4. 构建用于离线安装的 Zip 包
```bash
python scripts/package-obsidian-release.py --platform darwin --arch arm64
```
*输出位置：`dist/obsidian-plugin/crabby-0.1.0-darwin-arm64.zip`*

ZIP 中的包结构大致如下：
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
*`runtime/state.json` 记录了后端二进制文件相对于插件目录的相对路径，确保在不同机器上直接拷贝 Vault 文件夹时插件依然能找到后端进程。*

### 如何在 Obsidian 中手动安装

1. 打开目标 Vault 文件夹。
2. 将 `crabby-0.1.0-darwin-arm64.zip` 解压缩到 `<你的Vault>/.obsidian/plugins/` 下，最终层级必须是：
   ```text
   <你的Vault>/.obsidian/plugins/crabby/manifest.json
   <你的Vault>/.obsidian/plugins/crabby/main.js
   <你的Vault>/.obsidian/plugins/crabby/runtime/state.json
   ...
   ```
3. *(对于 macOS/Linux)* 如果解压工具没有保留可执行权限，请手动赋予后端文件执行权限：
   ```bash
   chmod +x "<你的Vault>/.obsidian/plugins/crabby/runtime/backend/0.1.0/darwin/crabby-backend"
   ```
4. 重启 Obsidian。
5. 进入 `设置 -> 第三方插件 (Community plugins)`。
6. 如果开启了“安全模式(Restricted mode)”，需要将其关闭。
7. 在插件列表中启用 **Crabby**。

插件启动后会读取 `runtime/state.json`，解析后端的相对路径，并将包含在内的后端服务器自动拉起。

### 注意事项
- 在 Windows 上执行后端构建脚本 `build-backend-runtime.py` 会对应生成 Windows 可执行文件(`.exe`)，同理 macOS 会生成 macOS 系统文件。
- Obsidian 插件前端文件 (`manifest.json` 和 `main.js`) 虽然是跨平台的，但捆绑包中的后端文件具有严格的系统平台区分。
- 这种打包发布方案彻底省去了需要公开 manifest URL 加载或者临时启动静态资源服务器的需求。
