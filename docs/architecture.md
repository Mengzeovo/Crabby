# Crabby 架构导览

最后更新：2026-05-12

本文面向第一次读代码的维护者。它解释 Crabby 当前怎么运行、各模块负责什么、数据在哪里、请求如何流动，以及哪些边界是设计上刻意保留的。

如果只想了解产品能力，先读 [项目能力概览.md](项目能力概览.md)。

## 总览

Crabby 是本地优先的 Obsidian AI assistant，由三个运行面组成：

- **Obsidian 插件**：主用户界面、本地配置界面、后端生命周期管理器、Obsidian 搜索桥。
- **FastAPI 后端**：LLM 调用、工具循环、MCP、sessions、attachments、personas、skills、cron、admin APIs。
- **Electron Desktop Pet**：独立桌面入口，复用同一后端协议和 session 系统。

```text
Obsidian Plugin                 Desktop Pet
Chat / Settings / Client Tools  Pet / Bubble / Chat / Settings
        |                                  |
        | REST + WebSocket                 | REST + WebSocket
        v                                  v
Python FastAPI Backend
Routes / LLM Client / ToolRegistry / MCP / SessionStore / Cron
        |               |                  |
        v               v                  v
LLM Provider        Local Vault        MCP Servers
Anthropic/OpenAI    Notes/Canvas       stdio/sse
Ollama/etc.         plugin runtime data
```

## Repository Map

```text
server/             Python backend
obsidian-plugin/    Obsidian TypeScript plugin and built main.js
desktop-pet/        Electron desktop companion
docs/               Documentation
prompts/            Default prompt fragments
personas/           Checked-in runtime personas
skills/             Checked-in runtime skills
scripts/            Build and packaging helpers
reference/          Reference material
```

Generated and local-only directories such as `node_modules/`, `.venv/`, logs,
cache folders, runtime data, and build outputs are not source of truth.

## Runtime Modes

Crabby has two common runtime modes.

### Development Mode

The backend runs from the repo:

```bash
cd server
uv run python main.py
```

The Obsidian plugin is built from `obsidian-plugin/src/` into `obsidian-plugin/main.js`. Development installs can use `.dev-runtime.json` in the installed plugin directory to point the plugin at the repo backend.

### Plugin-Managed Production Mode

The release zip installs into:

```text
<vault>/.obsidian/plugins/crabby/
```

The plugin reads `runtime/state.json`, resolves the backend executable relative to `runtime/`, starts it in the background, writes a host heartbeat, and reuses an existing managed backend only after checking:

- `GET /health`
- authenticated `GET /admin/mcp/status`
- authenticated `GET /admin/profiles`

The backend watchdog exits orphaned managed backends when the host heartbeat becomes stale.

## Plugin-Managed Files

In a normal installed plugin, install/runtime assets live under the plugin
folder:

```text
<vault>/.obsidian/plugins/crabby/
  manifest.json
  main.js
  runtime/state.json
  runtime/host-heartbeat.json
  runtime/backend/
```

User-owned runtime data lives under the Vault root so the plugin folder can be
replaced during upgrades:

```text
<vault>/crabby/
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

On startup, the plugin migrates legacy `<vault>/.obsidian/plugins/crabby/config`,
`data`, and `logs` directories into `<vault>/crabby/` when possible. Existing
target files are kept, and conflicting legacy files are left in place.

The repository `prompts/` and `personas/` directories are defaults. In plugin-managed runs, the plugin seeds runtime copies into `<vault>/crabby/config/prompts/` and `<vault>/crabby/config/personas/`, then passes those paths to the backend through environment variables.

## Backend

Backend entry point: `server/main.py`.

Startup responsibilities:

1. Load environment-backed settings from `server/config.py`.
2. Create the FastAPI app.
3. Register REST, WebSocket, sessions, attachments, client-tool, and admin routes.
4. Create the built-in ToolRegistry.
5. Load prompt-adjacent runtime config, skills, and personas.
6. Create file-backed session and attachment stores.
7. Start background tasks for MCP reload, host watchdog, cron, and auto-save.
8. Return health without waiting for MCP servers to finish connecting.

Important backend areas:

- `server/api/`: route layer.
- `server/llm/`: provider clients, output adapters, prompt assembly, tool loop helpers, context metering, token usage, profile storage and probe.
- `server/tools/`: built-in tools.
- `server/mcp_runtime.py`: MCP connection, transactional reload, and status.
- `server/memory/`: file-backed session/conversation storage and active branch materialization/cache.
- `server/personas/`: persona loader, registry, router, and runtime selection.
- `server/cron_daemon.py`: scheduled agent turns.
- `server/host_watchdog.py`: managed backend orphan cleanup.

## API Surface

Public local application endpoints include:

- `GET /health`
- `POST /chat`
- `GET /sessions`
- `POST /sessions`
- `GET /sessions/{session_id}`
- `PATCH /sessions/{session_id}`
- `DELETE /sessions/{session_id}`
- `GET /sessions/{session_id}/conversations`
- `GET /sessions/{session_id}/conversations/{conversation_id}/messages`
- `GET /sessions/{session_id}/conversations/{conversation_id}/context-stats`
- `WS /sessions/{session_id}/conversations/{conversation_id}/ws`
- `GET /personas`
- `GET /skills`
- `GET /capabilities`
- `GET /attachments/{attachment_id}`
- `WS /client-tools/obsidian`

Admin endpoints require `X-Crabby-Admin-Token`:

- `POST /admin/reload`
- `POST /admin/reload-settings`
- `GET /admin/mcp/status`
- `GET /admin/profiles`
- `PUT /admin/profiles/{profile_id}`
- `POST /admin/profiles/{profile_id}/activate`
- `DELETE /admin/profiles/{profile_id}`
- `POST /admin/profile/test`
- `POST /admin/shutdown`

Session and conversation IDs accept ASCII letters, digits, underscores, and hyphens, up to 128 characters. Unsafe IDs are rejected before disk access.

## Chat Turn Flow

REST and WebSocket share the same conceptual flow:

```text
Client sends user turn
  -> validate session_id and conversation_id
  -> persist user message and attachments
  -> resolve active persona mode
  -> assemble prompt fragments, environment state, tools, skills, persona
  -> materialize active conversation branch
  -> call LLM provider
  -> normalize text/reasoning/tool output
  -> execute tool calls through ToolRegistry/MCP/client bridge
  -> append tool results to history
  -> continue until final assistant output or iteration ceiling
  -> persist assistant message, usage, context stats, message IDs
```

WebSocket sends streaming events such as:

- `assistant_prefix`
- `reasoning_delta`
- `text_delta`
- `tool_start`
- `tool_result`
- `warning`
- `done`
- `error`
- `sys_notify`

`error` is reserved for transport/protocol failures. Terminal business conditions should complete with `warning` and `done` so clients do not replay the same prompt through REST fallback.

## LLM Providers And Profiles

Provider logic lives in `server/llm/client.py`, `server/llm/providers.py`, and `server/llm/output_adapters.py`.

Built-in provider IDs:

- `anthropic`
- `openai`
- `ollama`
- `deepseek`
- `qwen`
- `kimi`
- `minimax`
- `zhipu`
- `custom_openai`

Anthropic uses the native Messages API. OpenAI, Ollama, and compatible providers use chat completions with provider-specific request field allowlists.

Profiles are backend-owned:

- Stored in `.env` as `PROFILE_<id>_*`.
- Selected by `ACTIVE_PROFILE_ID`.
- Activated profiles write the effective `LLM_*` and provider-specific values.
- The plugin mirrors profiles for UI, but save/delete/activate operations go through authenticated admin APIs.
- `/admin/profile/test` validates current profile state and can run low-token live probes for supported providers.

Provider reasoning output is normalized into a shared UI/history shape when supported. DeepSeek, Qwen, and Kimi use `reasoning_content`; Anthropic uses native reasoning blocks; MiniMax and `custom_openai` use `reasoning_details`; unsupported providers use no reasoning output.

## Prompt, Persona, And Skill

Prompt assembly lives in `server/llm/prompts.py`.

Inputs can include:

- Static prompt fragments from `PROMPTS_DIR` or repository defaults.
- Runtime platform label, `sys.platform`, shell label, and Vault path.
- Tool catalog.
- Available skills and current-turn skill instruction.
- Current persona body.
- Session/conversation state.

Personas are loaded by recursively finding `PERSONA.md` files in `personas/` or `PERSONAS_DIR`. The checked-in persona set is:

- `secretary`
- `archivist`
- `researcher`
- `philosopher`
- `mentor`

Persona modes:

- Auto: LLM router chooses from loaded persona metadata/body and locks a high-confidence result for the session.
- Manual: user-selected persona.
- None: no persona prompt.

Skills are loaded from `skills/` or `SKILLS_DIR`. They are behavior instructions, not executable tools. Slash commands can force a skill for a turn.

## Tools

Built-in tools are registered in `server/tools/registry.py`.

Current built-ins include:

- `obsidian_search`
- `crabby_settings`
- `read`
- `edit`
- `grep`
- `glob`
- `task_query`
- `fetch`
- `bash`
- `cron_create`
- `cron_list`
- `cron_delete`

Tool execution pipeline:

```text
LLM tool call
  -> registry lookup
  -> Pydantic input validation
  -> permission/context checks
  -> async execution
  -> LLM/UI result formatting
  -> append tool_result to conversation
```

`obsidian_search` and `crabby_settings` are hosted by the Obsidian plugin and reached through the `/client-tools/obsidian` WebSocket bridge. Raw file tools remain available for non-Obsidian files, logs, code, or bridge-disconnected fallback.

`bash` is non-interactive. On Windows it launches PowerShell without a profile, forces UTF-8 output, and translates top-level `&&` / `||` chains for PowerShell 5.x compatibility.

`edit` is Vault-relative, preserves the target file's newline style, and rejects paths outside the Vault.

## MCP

MCP config is loaded from `MCP_CONFIG_FILE`, defaulting to a local data path in development. `server/data/mcp_servers.example.json` is the checked-in example.

MCP behavior:

- Supports `stdio` and `sse`.
- Interpolates `${ENV_VAR}` from process env or `.env`.
- Reloads in the background at startup.
- Supports authenticated admin reload.
- Uses transactional replacement: the active MCP tool set changes only after configured servers connect and register successfully.

## Sessions And Branches

Session storage uses:

```text
sessions/<session_id>/manifest.json
sessions/<session_id>/conversations/<conversation_id>.json
```

Legacy flat `sessions/<session_id>.json` files are migrated on load.

Key rules:

- A session is a topic container.
- A conversation is a branch under a session.
- The active LLM context is the materialized lineage from root to active conversation.
- Sibling branches are excluded.
- Active branches are cached in process memory with 30-minute inactivity TTL, 64 MiB global budget, LRU eviction, serialized-message-byte accounting, and branch fingerprints based on `conversation_id:revision`.

See [会话设计.md](会话设计.md) for the full design.

## Attachments And Usage

Image attachments are stored outside session JSON under `data/attachments/`, with metadata referenced from messages. A turn can include up to 4 images, each up to 10 MB, and only when the active profile declares vision support.

Token fields have distinct meanings:

- `context.total_tokens`: estimated current context-window occupancy.
- `context.actual_usage.total_tokens`: provider-reported usage for the current turn.
- `context.cumulative_usage.total_tokens`: session-persisted cumulative provider usage.

Provider usage is normalized in `server/llm/token_usage.py`.

## Cron

Cron jobs are managed by built-in tools and `server/cron_daemon.py`.

Behavior:

- Persisted at `<vault>/crabby/data/cron_jobs.json`.
- Supports 5-field cron and 6-field seconds-first cron.
- Scans once per second.
- Queues due jobs FIFO.
- Waits for session activity to become idle, up to 30 minutes.
- Runs each job in a fresh isolated session.
- Uses the shared non-streaming agent runner.
- Writes completion notifications back to the source session and pushes WebSocket `sys_notify` when clients are connected.

REST chat, WebSocket chat, and cron agent turns share `DEFAULT_MAX_AGENT_ITERATIONS`, currently 200.

## Obsidian Plugin

Plugin entry point: `obsidian-plugin/src/main.ts`.

Important areas:

- `src/chat/`: chat view, transcript, composer, context bar, profiles, personas, sessions, current-session tree, fork actions, stylesheet injection, turn runner.
- `src/api/client.ts`: REST/WebSocket client, admin APIs, profile APIs, profile test, error classification.
- `src/runtime/`: backend runtime management, host heartbeat, managed backend reuse/shutdown, runtime state, default config templates.
- `src/clientTools/`: plugin-hosted tools.
- `src/search/`: Obsidian-compatible search DSL and `.md` / `.canvas` implementation.
- `src/config/`: provider presets, backend config, MCP config, profile sync.
- `src/settings.ts`: settings UI.

The plugin registers UI immediately and starts the backend in the background. It distinguishes WebSocket transport failures from backend-delivered stream errors; only transport failures may fall back to REST.

## Desktop Pet

Desktop Pet entry point: `desktop-pet/src/main/index.ts`.

Important areas:

- `src/main/backendClient.ts`: backend REST/WebSocket client.
- `src/main/conversationManager.ts`: transcript state, streaming state, notifications, auto-continue.
- `src/renderer/`: pet, chat, bubble, and settings UI.
- `src/shared/`: shared types, constants, avatar data, and history helpers.

Desktop Pet is intentionally a companion surface, not a separate backend or AI runtime.

## Security Boundaries

Current local safety boundaries:

- Backend binds locally by default.
- Admin endpoints require admin token.
- Session and conversation IDs are filename-safe.
- Vault-relative file tools reject path escape.
- `read` blocks common sensitive filename patterns such as `.env`, credentials, and secrets.
- `edit` is disabled in restricted tool contexts.
- `bash` can be disabled and is non-interactive.
- MCP secrets should be supplied through environment variables, not hard-coded JSON.
- The settings tool redacts API keys in inspection output.

Crabby still has powerful write-capable tools. Treat it as local automation: enable shell, file edits, settings writes, MCP servers, and cron jobs only in trusted contexts.

## Development Commands

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
npm run test:config
npm run test:chat-content
npm run test:chat-styles
npx tsc --noEmit
npm run build
```

Desktop Pet:

```bash
cd desktop-pet
npm run typecheck
npm run test
npm run build
```

Manual release:

```bash
cd server
uv run --with pyinstaller python ../scripts/build-backend-runtime.py --version 0.1.0
cd ..
python scripts/package-obsidian-release.py --platform darwin --arch arm64
```

## Architecture Principles

- The backend owns LLM runtime truth: profiles, provider calls, tools, sessions, usage, personas, skills, cron, and MCP.
- The Obsidian plugin owns Obsidian-native UI and client-hosted Vault actions.
- Runtime config should remain local, human-inspectable, and file-backed unless a heavier store becomes necessary.
- The active branch is the unit of LLM history; the session tree is for organization and navigation.
- Tool results for the model and tool state for the UI should stay conceptually separate.
- MCP tools are dynamic and appear only after successful runtime registration.
