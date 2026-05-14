# Agent Handoff

Last rewritten: 2026-05-14

This file is the fast entry point for agents and maintainers taking over the
Crabby repository. It should reflect the current repo, not old plans or memory
from external systems.

## Maintenance Rule

Every meaningful repository change must update this file from the current repo
state. Do not append stale notes. Re-scan structure, commands, runtime paths,
module responsibilities, workflow assumptions, and verification commands.

Meaningful changes include:

- Adding, removing, or moving modules.
- Changing backend, plugin, desktop-pet, MCP, prompt, persona, skill, cron,
  session, token accounting, provider, or test behavior.
- Changing install, build, launch, release, or verification commands.
- Adding runtime requirements or environment variables.

## Project Purpose

Crabby is a local-first AI assistant for Obsidian. It combines:

- A Python FastAPI backend for LLM calls, provider profiles, tool execution,
  MCP integration, runtime config, sessions, attachments, token/context
  accounting, cron jobs, and admin APIs.
- An Obsidian TypeScript plugin for chat UI, settings, backend lifecycle,
  LLM profile management, MCP config editing, session tree/fork UI, and
  client-hosted Obsidian tools.
- An Electron Desktop Pet client that talks to the same backend and provides a
  lightweight desktop companion surface.

Crabby is designed for one local machine, one local Vault, and personal
workflows. It is not a cloud multi-user SaaS.

## Top-Level Map

- `server/`: Python FastAPI backend.
- `obsidian-plugin/`: Obsidian plugin source and bundled `main.js`.
- `desktop-pet/`: Electron desktop companion app.
- `docs/`: product, architecture, technical route, session design, provider
  matrix, roadmap, and design reference docs.
- `docs/项目能力概览.md`: first-read product capability overview.
- `docs/architecture.md`: current architecture and runtime flow.
- `docs/技术路线.md`: technical direction and extension boundaries.
- `docs/会话设计.md`: session/conversation split, branch materialization, and
  active branch cache.
- `docs/llm-provider-matrix.md`: built-in provider presets and compatibility.
- `docs/execution-plan.md`: release roadmap.
- `docs/claude-code-analysis.md`: design reference, not current implementation.
- `prompts/`: repository default prompt fragments.
- `personas/`: checked-in runtime personas.
- `skills/`: checked-in runtime skills.
- `reference/`: reference material.
- `scripts/`: backend runtime build and release packaging helpers.
- `scripts/build-backend-runtime.py`: builds a PyInstaller backend runtime.
  Generated PyInstaller `.spec` files are ignored by git.
- `scripts/package-obsidian-release.py`: builds a manual-install Obsidian
  plugin zip with `manifest.json`, `main.js`, relative production
  `runtime/state.json`, and a prebuilt backend binary. It resolves
  `npm.cmd` on Windows when running the plugin build.
- `README.md`: release-facing overview, dev commands, packaging, install,
  first-run setup, runtime data, and troubleshooting.
- `LICENSE`: MIT License for the repository.
- `.env`: local secrets and runtime settings. Do not commit real secrets.
- `.env.example`: example environment configuration.

## Backend Map

Important backend files and folders:

- `server/main.py`: FastAPI app entry, route assembly, MCP startup, cron
  startup, and background daemons.
- `server/config.py`: environment-backed settings.
- `server/runtime_config.py`: runtime config helpers for prompts, personas,
  and skills.
- `server/mcp_config.py`: MCP config loading and environment interpolation.
- `server/mcp_runtime.py`: MCP startup, status, and transactional reload.
- `server/host_watchdog.py`: host heartbeat watchdog for managed backends.
- `server/cron_daemon.py`: background cron scanner/queue/consumer.
- `server/api/`: REST, WebSocket, attachments, sessions, client-tool bridge,
  and admin APIs.
- `server/api/rest.py`: REST chat, context stats, persona, skill, capability,
  and admin-facing routes with safe ID validation.
- `server/api/sessions.py`: session metadata and message-history APIs.
- `server/api/websocket.py`: streaming chat WebSocket, tool-loop warnings, and
  safe conversation ID checks.
- `server/api/client_tools.py`: WebSocket bridge for Obsidian-hosted tools.
- `server/llm/`: LLM client, provider presets, output adapters, profile store,
  profile probe, prompt assembly, context metering, token accounting, session
  activity, and tool loop helpers.
- `server/llm/providers.py`: built-in provider presets, base URLs, key
  fallbacks, reasoning/output shapes, and streaming-tool support flags.
- `server/llm/output_adapters.py`: normalizes provider chunks/responses into
  text, reasoning, tool, and done events.
- `server/llm/profile_store.py`: persists backend-owned profiles in `.env`.
- `server/llm/profile_probe.py`: validates/tests active profiles.
- `server/llm/agent_runner.py`: shared non-streaming agent runner for REST,
  fallback WebSocket paths, cron, and other background turns.
- `server/llm/tool_executor.py`: validates, runs, and formats tool calls,
  including standardized UI payloads with tool IDs, status, metadata,
  truncation/cache details, and elapsed time.
- `server/llm/token_usage.py`: normalizes provider usage and accumulates
  per-turn/session totals.
- `server/personas/`: persona loader, registry, router, runtime selection, and
  API models.
- `server/tools/`: built-in tools such as `obsidian_search`,
  `crabby_settings`, `read`, `grep`, `glob`, `bash`, `edit`, `fetch`, `cron`,
  and `task_query`.
- `server/tools/bash.py`: non-interactive cross-platform shell tool. On
  Windows it launches PowerShell without a profile, forces UTF-8 output, and
  translates top-level `&&` / `||` chains for PowerShell 5.x compatibility.
- `server/tools/edit.py`: Vault-relative exact replacement/new-file tool that
  preserves dominant newline style and rejects paths outside the Vault.
- `server/tools/crabby_settings.py`: self-management tool that talks to the
  Obsidian bridge and backend admin profile APIs.
- `server/tools/cron.py`: cron create/list/delete tool and
  backend runtime `data/cron_jobs.json` persistence.
- `server/memory/`: file-backed session manifest/conversation storage, legacy
  flat-session migration, active branch materialization/cache, ID validation,
  actual usage snapshots, pending notifications, and auto-save support.
- `server/tests/`: backend tests.
- `server/data/mcp_servers.example.json`: example MCP config.
- `server/data/mcp_servers.json`: local private MCP config when present.

Backend commands:

```bash
cd server
uv sync --dev
uv run python main.py
uv run pytest
uv run ruff check .
uv run --with pyinstaller python ../scripts/build-backend-runtime.py --version 0.1.0
```

## Obsidian Plugin Map

Important plugin files and folders:

- `obsidian-plugin/src/main.ts`: plugin entry point.
- `obsidian-plugin/src/settings.ts`: settings UI, backend-owned profile
  controls, active-profile test button, runtime/MCP settings.
- `obsidian-plugin/src/api/client.ts`: backend API client, WebSocket handling,
  transport/server error classification, admin reload/status calls, profile
  calls, and active-profile test calls.
- `obsidian-plugin/src/chat/`: chat view, transcript, context/token usage bar,
  composer, assistant rendering, personas, profiles, sessions, current-session
  tree, fork actions, stylesheet injection, and turn runner.
- `obsidian-plugin/src/chat/chatAssistantContent.ts`: assistant markdown and
  thought rendering helpers, including shared `Crabby` identity header.
- `obsidian-plugin/src/clientTools/`: WebSocket client-tool bridge.
- `obsidian-plugin/src/clientTools/obsidianClientTools.ts`: routes backend RPC
  requests to plugin-hosted tools.
- `obsidian-plugin/src/clientTools/crabbySettingsTool.ts`: plugin-hosted
  self-management tool for settings and backend-owned profiles.
- `obsidian-plugin/src/config/`: backend, profile sync, provider presets, and
  MCP config helpers.
- `obsidian-plugin/src/config/llmProviders.ts`: provider/model presets and UI
  capability metadata.
- `obsidian-plugin/src/runtime/`: backend runtime management, host heartbeat,
  managed-backend reuse/shutdown, runtime state path helpers, and default
  config templates.
- `obsidian-plugin/src/runtime/defaultConfigTemplates.ts`: seeds default prompt
  and persona templates. Persona seeding is based on discovered `PERSONA.md`
  files, so incidental files do not block first-run defaults.
- `obsidian-plugin/src/runtime/runtimeState.ts`: serializes production backend
  executable paths relative to the installed plugin runtime directory and
  resolves relative/legacy absolute paths at launch.
- `obsidian-plugin/src/search/`: Obsidian-search-compatible DSL parsing and
  `.md` / `.canvas` search implementation.
- `obsidian-plugin/scripts/`: repo-local verification scripts.
- `obsidian-plugin/scripts/test-chat-tools.js`: verifies tool-result payload
  normalization and chat transcript tool-block rendering behavior.
- `obsidian-plugin/manifest.json`: plugin manifest.
- `obsidian-plugin/main.js`: built plugin bundle.

Plugin commands:

```bash
cd obsidian-plugin
npm ci
npm run test:config
npm run test:chat-content
npm run test:chat-styles
npx tsc --noEmit
npm run build
npm run dev
```

`npm run test:config` is expected to pass on Windows and GitHub Actions
`ubuntu-latest`; keep path assertions platform-neutral.

Manual-install release packaging:

```bash
python scripts/package-obsidian-release.py --platform darwin --arch arm64
```

The packaging script expects the backend binary at
`dist/backend-runtime/<version>/<platform>/crabby-backend` unless
`--backend-binary` is supplied. `--arch` affects the zip filename; it does not
cross-compile the backend binary.

## Desktop Pet Map

Important files and folders:

- `desktop-pet/src/main/`: Electron main process, backend client, avatar,
  settings, and conversation manager.
- `desktop-pet/src/main/backendClient.ts`: backend REST/WebSocket client.
- `desktop-pet/src/main/conversationManager.ts`: transcript, streaming state,
  notifications, and auto-continue behavior.
- `desktop-pet/src/renderer/`: pet, chat, bubble, and settings views.
- `desktop-pet/src/shared/`: shared types, constants, avatar data, and history
  helpers.
- `desktop-pet/assets/`: runtime visual assets copied into `dist/assets/`.
- `desktop-pet/dist/`: build output.

Desktop Pet commands:

```bash
cd desktop-pet
npm ci
npm run typecheck
npm run test
npm run build
npm run start
```

## Runtime Flow

1. The Obsidian plugin registers UI immediately and starts the managed backend
   in the background.
2. Before spawning, the plugin reuses a reachable managed backend only after
   `/health`, authenticated `/admin/mcp/status`, and authenticated
   `/admin/profiles` pass.
3. The plugin writes a host heartbeat. The backend watchdog exits orphaned
   managed backends when heartbeat becomes stale.
4. User interaction from the plugin or Desktop Pet goes to the backend through
   REST/WebSocket with explicit `session_id` and `conversation_id`.
5. The backend validates IDs before disk access.
6. The backend owns LLM profiles in `.env`; plugin profile UI uses admin APIs.
7. Backend startup registers built-in tools, sessions, attachments, personas,
   skills, cron, and auto-save, then returns health before MCP finishes
   connecting.
8. MCP startup reload runs in the background. Admin reload can refresh MCP
   synchronously.
9. Prompt context is assembled from prompt fragments, runtime environment,
   persona/config state, session state, skills, and available tools.
10. The active session branch is materialized from `SessionStore` and branch
    cache before each model call.
11. LLM responses are normalized into text, reasoning, tool calls, stop
    reasons, and usage.
12. Tool execution routes through built-in tools, connected MCP tools, and the
    Obsidian client-tool bridge. Tool results include structured UI payloads
    with `success`, `warning`, or `error` status.
13. Responses include streamed events or structured REST output plus context
    stats, per-turn usage, cumulative session usage when available, and
    assistant/user message IDs. WebSocket `tool_result` events and REST
    `tool_calls` carry the full tool UI payload, not a shortened preview.
14. Cron jobs run in isolated sessions through the shared non-streaming agent
    runner and push completion notifications back to source sessions.
15. WebSocket `error` events are reserved for transport/protocol failures.
    Backend-delivered business conditions should use `warning`/`done`.

## Session And Conversation Rules

- Session IDs and conversation IDs use ASCII letters, digits, underscores, and
  hyphens, up to 128 chars.
- Session storage uses `sessions/<session_id>/manifest.json` plus
  `sessions/<session_id>/conversations/<conversation_id>.json`.
- Legacy flat sessions are loaded and rewritten into the new layout.
- Active branch materialization excludes sibling branches.
- Branch cache is process-local memory with 30-minute inactivity TTL, 64 MiB
  budget, LRU eviction, serialized-byte accounting, and
  `sha256(conversation_id:revision|...)` branch fingerprints.
- Session history is not capped by `max_turns`; pruning/summarization is a
  future explicit feature.
- Persisted `tool_result` blocks may contain a UI-only `ui` payload for
  frontend restoration. Model-message materialization strips UI-only fields
  before provider requests.

## Persona And Skill Rules

- Personas are discovered by recursively loading `PERSONA.md` from
  `personas/` or `PERSONAS_DIR`.
- Current checked-in personas are `secretary`, `archivist`, `researcher`,
  `philosopher`, and `mentor`.
- Default persona directories contain `PERSONA.md`, `METHODS.md`, and
  optional `sources/` reference material.
- Default persona prompts use consistent sections for role positioning,
  responsibility boundaries, tool habits, default workflow, minimum output
  commitments, output style, and methodology sources.
- `METHODS.md` is a short runtime methodology summary loaded with the active
  persona into the final system prompt. It is not included in Auto routing
  catalogs.
- `sources/*.md` files are long-form maintenance/reference material and are not
  loaded into runtime prompts by default.
- Persona boundaries should tell the assistant to declare scope and suggest
  switching personas; they should not imply that the current turn will
  automatically hand off to another persona.
- Persona modes are Auto, Manual, and None.
- Auto mode routes through an LLM classifier over loaded persona metadata/body
  and current/recent user context. High-confidence results lock one active
  persona for the session.
- Manual and None override auto routing.
- Skills are loaded from `skills/` or `SKILLS_DIR`; they are behavior guides,
  not executable tools.

## Configuration Notes

- General runtime configuration lives in `.env`.
- Plugin-managed runtime config lives under
  `<vault>/.obsidian/plugins/crabby/config/`.
- `PROMPTS_DIR` controls prompt fragments.
- `PERSONAS_DIR` controls runtime personas.
- Active LLM secrets/base URL can use generic `LLM_API_KEY` and
  `LLM_BASE_URL`.
- Provider-specific fallbacks include `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `BAILIAN_CODING_PLAN_API_KEY`,
  `KIMI_API_KEY`, `MINIMAX_API_KEY`, and `ZAI_API_KEY`.
- Built-in provider IDs are `anthropic`, `openai`, `ollama`, `deepseek`,
  `qwen`, `kimi`, `minimax`, `zhipu`, and `custom_openai`.
- `kimi` targets Kimi Code: `https://api.kimi.com/coding/v1` and
  `kimi-for-coding`.
- Optional reasoning controls: `LLM_THINKING_MODE`,
  `LLM_THINKING_BUDGET_TOKENS`, `LLM_REASONING_EFFORT`,
  `LLM_REASONING_SPLIT`.
- Backend-owned profiles are stored in `.env` as `PROFILE_<id>_*`, with
  `ACTIVE_PROFILE_ID` selecting the active profile.
- Managed backend cleanup uses `CRABBY_HOST_HEARTBEAT_FILE`,
  `CRABBY_HOST_HEARTBEAT_TIMEOUT_SECONDS`, `CRABBY_HOST_PID`, and
  `CRABBY_BACKEND_RELOADER_PARENT`.
- `PERSONA_ROUTER_THRESHOLD` defaults to `0.75`.

## Search Tool Rules

- Use `obsidian_search` first for Obsidian-native lookup in `.md` and
  `.canvas` files.
- `obsidian_search` is hosted by the running plugin and reached through the
  `/client-tools/obsidian` bridge.
- It supports common Obsidian Search DSL semantics: terms, phrases, OR,
  negation, regex, file/path/content/tag/line/block/section/task operators,
  and property queries.
- Use `crabby_settings` for plugin runtime/profile/settings state.
- Use `grep`, `glob`, and `read` for non-Obsidian files, raw text/code/logs, or
  when the bridge is disconnected.

## Cron Behavior

- Tools: `cron_create`, `cron_list`, `cron_delete`.
- Persistence: `<vault>/.obsidian/plugins/crabby/data/cron_jobs.json` in
  plugin-managed production runs, or `DATA_DIR/cron_jobs.json` generally.
- Daemon scans once per second and consumes due jobs FIFO.
- Execution waits for idle session activity, up to 30 minutes.
- Each run uses a new isolated session and does not reuse source conversation
  context.
- Completion notifications are stored on the source session and pushed through
  WebSocket when possible.
- Supports standard 5-field cron and 6-field seconds-first cron.

## Before Editing

1. Read this file first.
2. Run `git status --short`.
3. Preserve unrelated user changes.
4. Use source files under `server/`, `obsidian-plugin/src/`, and
   `desktop-pet/src/` as authority.
5. Treat docs as helpful but possibly stale unless they match current source.
6. After meaningful repo changes, rewrite this file from the new current state.

## Verification Baseline

Use the smallest relevant verification set:

- Backend-only change: `cd server && uv run pytest`; add
  `uv run ruff check .` when Python style/imports changed.
- Session-ID validation or session storage hardening:
  `cd server && uv run pytest tests/test_memory.py tests/test_sessions_api.py tests/test_chat_session_validation.py tests/test_websocket_notifications.py`,
  then full backend tests and ruff.
- Branch cache/session tree change: targeted tests for TTL, LRU,
  serialized-size accounting, global-budget eviction, warm hits, cold rebuilds,
  lineage, and sibling exclusion, then full backend tests.
- Bash tool change: `cd server && uv run pytest tests/test_bash.py`, then full
  backend tests and ruff.
- Tool-result payload or chat tool-block rendering change:
  `cd server && uv run pytest tests/test_bash.py tests/test_websocket_notifications.py tests/test_chat_session_validation.py tests/test_memory.py`,
  `cd server && uv run ruff check .`,
  `cd obsidian-plugin && npm run test:chat-tools`,
  `npm run test:chat-styles`, `npx tsc --noEmit`, and `npm run build`.
- Edit tool change: `cd server && uv run pytest tests/test_edit_tool.py`, then
  full backend tests and ruff.
- Token accounting change:
  `cd server && uv run pytest tests/test_token_usage.py tests/test_websocket_notifications.py`,
  plus relevant client checks when UI stats changed.
- Reasoning/thinking/provider preset change:
  `cd server && uv run pytest tests/test_token_usage.py tests/test_websocket_notifications.py`,
  `cd obsidian-plugin && npm run test:config`, and plugin build.
- Provider output adapter, backend-owned profile, or active-profile test
  change:
  `cd server && uv run pytest tests/test_token_usage.py tests/test_admin_api.py tests/test_websocket_notifications.py`,
  ruff, plugin `test:config`, `npx tsc --noEmit`, and build.
- Obsidian client-tool bridge or `crabby_settings` change:
  `cd server && uv run pytest tests/test_obsidian_search_tool.py tests/test_crabby_settings_tool.py`,
  ruff, plugin `test:config`, `npx tsc --noEmit`, and build.
- Managed backend lifecycle or host-watchdog change:
  `cd server && uv run pytest tests/test_host_watchdog.py tests/test_app_smoke.py`,
  ruff, plugin `test:config`, `npx tsc --noEmit`, and build.
- Persona/routing/template change:
  `cd server && uv run pytest tests/test_personas.py tests/test_prompts.py`,
  plugin `test:config`, and plugin build when templates/UI payloads changed.
- Cron or agent-runner change: full backend tests, including
  `tests/test_cron.py` and `tests/test_agent_runner.py`.
- Obsidian plugin change: plugin build; add `test:config` for config/runtime/search,
  `test:chat-content` for assistant thought rendering, `test:chat-tools` for
  tool-result transcript rendering, `test:chat-styles` for stylesheet/hot-reload,
  and `npx tsc --noEmit` when TypeScript types changed.
- Chat turn ID propagation or live fork UI change:
  backend tests `tests/test_chat_session_validation.py`,
  `tests/test_websocket_notifications.py`, `tests/test_user_turn.py`, ruff,
  plugin `test:chat-content`, `test:chat-styles`, `npx tsc --noEmit`, and build.
- Prompt assembly change: `cd server && uv run pytest tests/test_prompts.py`;
  broaden when tool use or shared runtime behavior changed.
- Desktop Pet change: `cd desktop-pet && npm run typecheck`, `npm run test`, or
  `npm run build` depending on touched surface.
- WebSocket warning/fallback change:
  `cd server && uv run pytest tests/test_websocket_notifications.py`,
  plugin `npx tsc --noEmit`, and plugin build.
- Cross-module behavior: run relevant backend and client checks together.

## Known Working Assumptions

- Python backend targets Python 3.11+ and uses `uv`.
- Backend framework is FastAPI with uvicorn.
- Obsidian plugin is TypeScript bundled by esbuild.
- Obsidian plugin development mode is activated by `.dev-runtime.json` in the
  installed plugin directory.
- Plugin dev/deploy helper scripts resolve target Vault from `VAULT_PATH`,
  then Obsidian local vault metadata, then `<home>/ObsidianVault`.
- Production runtime state stores `executablePath` relative to the installed
  plugin runtime directory when possible; legacy absolute paths still resolve.
- Plugin first-run config seeds default prompts/personas without overwriting
  user files.
- Managed backend reuse requires current admin profile APIs; older backends
  should not be adopted.
- Desktop Pet is Electron, TypeScript, esbuild, and Vitest.
- The Obsidian client-tool bridge exposes `obsidian_search` and
  `crabby_settings`.
- REST, WebSocket, Obsidian plugin, and Desktop Pet use explicit
  `session_id + conversation_id`.
- Backend chat REST responses and WebSocket `done` events carry both
  `message_id` and `user_message_id`.
- REST `tool_calls`, WebSocket `tool_result` events, and persisted tool-result
  `ui` payloads share the same tool UI shape with ID, name, output, metadata,
  status, truncation/cache fields, and elapsed time when available.
- `obsidian-plugin/src/chat/chatStyles.ts` upserts the shared style tag on
  reload.
- The backend system prompt dynamically injects runtime platform label,
  `sys.platform`, and shell used by `bash`.
- REST chat, WebSocket chat, and cron turns share
  `server/llm/agent_runner.py`'s `DEFAULT_MAX_AGENT_ITERATIONS`, currently 200.
- WebSocket client fallback to REST is only for transport failures, not
  backend-delivered stream errors.
- Thinking/reasoning controls are opt-in and provider-specific.
- Historical DeepSeek sessions reconstruct thought blocks from saved reasoning
  data when thinking mode is enabled and the model supports `reasoning_content`.
