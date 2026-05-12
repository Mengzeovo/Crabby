# Agent Handoff

Last rewritten: 2026-05-12

This file is the fast entry point for agents and maintainers who need the repo
without relying on MemPalace or any external memory system.

## Required Maintenance Rule

Every time the repository changes in a meaningful way, rewrite this file from
the current repo state. Do not only append notes. Re-scan the structure,
commands, module responsibilities, and workflow assumptions, then replace stale
content.

Meaningful updates include:

- Adding, removing, or moving modules.
- Changing backend, plugin, desktop-pet, MCP, prompt, config, cron, reasoning,
  token accounting, or test behavior.
- Changing install, build, launch, or verification commands.
- Adding new runtime requirements or environment variables.

## Repository Purpose

LifeAssistantAgent is a local AI assistant built around an Obsidian vault. It
combines:

- A Python FastAPI backend for LLM calls, tool execution, MCP integration,
  runtime config, sessions, attachments, token/context accounting, cron jobs,
  and admin reloads.
- An Obsidian TypeScript plugin for chat UI, settings, backend lifecycle and
  config management, MCP config editing, and client-hosted Obsidian tools.
- An Electron desktop pet client that talks to the backend and provides a
  lightweight desktop UI.

## Top-Level Map

- `server/`: Python backend.
- `obsidian-plugin/`: Obsidian plugin source and bundled output.
- `desktop-pet/`: Electron desktop companion app.
- `docs/`: Architecture, `技术路线.md`, execution plan, `会话设计.md`,
  LLM provider matrix, and Claude Code analysis notes.
- `docs/会话设计.md`: Session/conversation split, manifest/index, hot branch
  cache, and branch fingerprint design notes.
- `prompts/`: Repository default prompt templates. Plugin-managed runs seed
  the same default prompt text into the installed plugin directory under
  `config/prompts/`, then pass that path to the backend as `PROMPTS_DIR`.
- `personas/`: Runtime persona assets and methodology source notes.
- `skills/`: Local skill assets.
- `reference/`: Reference material.
- `scripts/`: Repo-level helper scripts, including backend runtime building and release packaging.
- `scripts/package-obsidian-release.py`: Builds/stages a manual-install
  Obsidian plugin zip containing `manifest.json`, `main.js`, relative
  production runtime `state.json`, and a prebuilt backend binary.
- `README.md`: User-facing quick start plus private release packaging flow.
- `.env`: Local secrets and runtime settings. Do not commit real secrets.
- `.env.example`: Example environment configuration.

## Backend Map

Important backend files and folders:

- `server/main.py`: FastAPI app entry point, route assembly, MCP startup,
  cron startup, and background daemons.
- `server/config.py`: Environment-backed application settings.
- `server/runtime_config.py`: Runtime configuration helpers for personas and
  skills.
- `server/mcp_config.py`: MCP server config loading and environment variable
  interpolation.
- `server/mcp_runtime.py`: MCP runtime startup, status, and reload behavior.
- `server/host_watchdog.py`: Host heartbeat watchdog for managed backends.
- `server/cron_daemon.py`: Background cron scanner/queue/consumer.
- `server/api/`: REST, WebSocket, attachments, sessions, client-tool bridge,
  and admin APIs.
- `server/api/rest.py`: REST chat, session, context-stats, persona, skill,
  capability, and admin-facing routes with session-ID validation.
- `server/api/sessions.py`: Session metadata and message-history APIs with
  safe session-ID checks.
- `server/api/websocket.py`: Streaming chat WebSocket, tool-loop warnings,
  and safe conversation-ID checks.
- `server/api/client_tools.py`: WebSocket bridge for client-hosted Obsidian
  tools such as `obsidian_search` and `life_assistant_settings`.
- `server/llm/`: LLM client, provider presets, output adapters, profile store,
  profile probe, prompt assembly, context metering, token accounting, session
  activity, and tool execution helpers.
- `server/llm/providers.py`: Built-in provider presets, base URLs, key
  fallbacks, reasoning/output shape declarations, and streaming-tool support
  flags.
- `server/llm/output_adapters.py`: Normalizes provider chunks and responses
  into backend text, reasoning, tool, and done events.
- `server/llm/profile_probe.py`: Validates the active profile and runs live
  probes for supported providers.
- `server/llm/profile_store.py`: Persists backend-owned LLM profiles in
  `.env`, applies the active profile, and exposes profile state to admin APIs.
- `server/llm/agent_runner.py`: Shared non-streaming tool loop for background
  cron turns and other non-streaming agent runs. REST, WebSocket, and cron
  turns share the same iteration ceiling.
- `server/llm/token_usage.py`: Normalizes provider usage payloads and
  accumulates per-turn and per-session usage.
- `server/personas/`: Persona loader, registry, router, runtime selection,
  and API-facing models.
- `server/tools/`: Built-in tools such as `obsidian_search`,
  `life_assistant_settings`, `read`, `grep`, `glob`, `bash`, `edit`, `fetch`,
  `cron`, and `task_query`.
- `server/tools/bash.py`: Non-interactive cross-platform shell tool. On
  Windows it launches PowerShell without a profile and translates top-level
  `&&` / `||` chains for PowerShell 5.x compatibility.
- `server/tools/edit.py`: Vault-relative exact string replacement that
  preserves the target file's newline style and rejects paths outside the
  vault.
- `server/tools/life_assistant_settings.py`: Self-management tool that talks
  to the Obsidian bridge and uses backend admin profile APIs instead of local
  mirror mutation.
- `server/tools/cron.py`: Cron task create/list/delete tool and
  `.LifeAssistantAgent/data/cron_jobs.json` persistence.
- `server/memory/`: File-backed session manifest/conversation storage, legacy
  flat-session migration, active branch materialization/cache, unsafe session
  ID validation, unbounded active-branch message history, actual usage
  snapshots, pending notifications, and auto-save support.
- `server/tests/`: Backend tests.
- `server/data/mcp_servers.example.json`: Example MCP server config.
- `server/data/mcp_servers.json`: Local private MCP config when present.

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

- `obsidian-plugin/src/main.ts`: Plugin entry point.
- `obsidian-plugin/src/settings.ts`: Settings UI and plugin configuration,
  including backend-owned profile controls and the active-profile test button.
- `obsidian-plugin/src/api/client.ts`: Backend API client, WebSocket handling,
  transport/server error classification, admin reload/status calls, profile
  calls, and active-profile test calls.
- `obsidian-plugin/src/chat/`: Chat view, transcript, context/token usage bar,
  composer, assistant rendering, personas, profiles, sessions, current-session
  conversation tree, fork actions, stylesheet injection, and turn runner with
  WebSocket-to-REST fallback control.
- `obsidian-plugin/src/chat/chatAssistantContent.ts`: Assistant markdown and
  thought rendering helpers, including the shared `Crabby` identity header used
  by completed and streaming replies.
- `obsidian-plugin/scripts/`: Small repo-local verification scripts such as
  `test-chat-styles.js`.
- `obsidian-plugin/src/clientTools/`: WebSocket client tool bridge from
  Obsidian to the backend.
- `obsidian-plugin/src/clientTools/obsidianClientTools.ts`: Routes backend RPC
  requests to plugin-hosted tools.
- `obsidian-plugin/src/clientTools/lifeAssistantSettingsTool.ts`: Plugin-hosted
  self-management tool for settings and backend-owned profiles.
- `obsidian-plugin/src/config/`: Backend, profile sync, and MCP config
  helpers.
- `obsidian-plugin/src/config/llmProviders.ts`: Provider/model presets and UI
  capability metadata.
- `obsidian-plugin/src/runtime/`: Backend runtime management, host heartbeat
  writing, managed-backend reuse/shutdown, runtime state path helpers, and
  default config templates.
- `obsidian-plugin/src/runtime/runtimeState.ts`: Serializes production backend
  executable paths relative to the installed plugin runtime directory and
  resolves relative/legacy absolute runtime state paths at launch.
- `obsidian-plugin/src/search/`: Obsidian-search-compatible DSL parsing and
  `.md` / `.canvas` search implementation.
- `obsidian-plugin/manifest.json`: Plugin manifest.
- `obsidian-plugin/main.js`: Built plugin bundle.

Plugin commands:

```bash
cd obsidian-plugin
npm run build
npm run test:config
npm run test:chat-content
npm run test:chat-styles
npm run dev
```

Manual-install release packaging:

```bash
python scripts/package-obsidian-release.py --platform darwin --arch arm64
```

The packaging script expects the backend binary at
`dist/backend-runtime/<version>/<platform>/life-assistant-backend` unless
`--backend-binary` is supplied.

## Desktop Pet Map

Important desktop-pet files and folders:

- `desktop-pet/src/main/`: Electron main process, backend client, avatar,
  settings, and conversation manager.
- `desktop-pet/src/renderer/`: Pet, chat, bubble, and settings renderer views.
- `desktop-pet/src/shared/`: Shared types, constants, avatar data, and history
  helpers.
- `desktop-pet/assets/`: Runtime visual assets.
- `desktop-pet/dist/`: Build output.

Desktop pet commands:

```bash
cd desktop-pet
npm run build
npm run start
npm run typecheck
npm run test
```

## Current Architecture Flow

1. The Obsidian plugin registers UI immediately and starts the managed backend
   in the background instead of blocking plugin load on backend health. Before
   spawning, it reuses a reachable managed backend after checking `/health`,
   authenticated `/admin/mcp/status`, and authenticated `/admin/profiles`.
2. The plugin writes a host-heartbeat file while loaded. The backend watchdog
   exits orphaned managed backends when the heartbeat becomes stale; dev
   `uvicorn --reload` launches also mark the reload parent for cleanup.
3. User interaction from the plugin or desktop pet goes to the backend once it
   is reachable. Session and conversation IDs are validated before any disk
   write or lookup. Clients now pass explicit `session_id` plus
   `conversation_id`; new chat sessions are created through `/sessions` before
   WebSocket or REST chat turns. The Obsidian chat header has separate history
   and current-session tree entry points; the tree uses the active session's
   conversation graph, and branch switching / fork creation go through the
   existing conversation endpoints.
4. The backend owns LLM profile persistence in `.env` via `PROFILE_<id>_*`
   keys and `ACTIVE_PROFILE_ID`. The Obsidian plugin mirrors profiles for UI,
   but save/delete/activate operations go through authenticated admin APIs.
5. The chat profile selector rebuilds from mirrored `llmProfiles`, refreshes on
   settings changes, and activates profiles through the backend admin API.
6. The Obsidian plugin client-tool bridge serves both `obsidian_search` and
   `life_assistant_settings`. The settings tool works through the live plugin
   object, can reconnect the bridge after backend URL changes, updates active
   chat clients when settings move, and uses backend admin profile APIs instead
   of mutating local profile mirrors directly.
7. Backend startup registers built-in tools, sessions, attachments, personas,
   skills, cron, and auto-save, then returns health without waiting for MCP
   servers to connect.
8. MCP startup reload runs as a backend background task. MCP tools become
   available after that reload succeeds; admin reload can still refresh MCP
   synchronously.
9. The backend builds prompt context from runtime prompt fragments, dynamic
   environment state, persona/config state, session state, and available tools.
   In plugin-managed runs, those prompt fragments live in the installed
   Obsidian plugin directory under `config/prompts/`; the repository `prompts/`
   directory is the default template/fallback source.
   Auto persona routing uses an LLM classification pass over loaded persona
   metadata/body plus current/recent user context, then locks one active
   persona for the session when confidence is high enough.
10. The LLM client resolves the configured provider through
    `server/llm/providers.py`. Anthropic uses the native Messages API, while
    OpenAI-compatible providers and Ollama use OpenAI-compatible chat
    completions with provider-specific request-field whitelists.
11. Before each call, the backend materializes the active session branch from
    `SessionStore` and estimates context usage from that same branch snapshot;
    after each call, provider `usage` is preserved when available. When a turn
    triggers tool use, the returned usage is normalized through the active
    provider preset and accumulated into both turn and session totals.
12. Tool execution is routed through built-in tools, connected MCP tools, and
    the Obsidian plugin client-tool bridge.
13. Backend returns streamed or structured responses to the client UI,
    including context stats, per-turn usage, session-cumulative usage when the
    provider supplies it, and the assistant/user message IDs for the turn. The
    Obsidian plugin chat footer shows context occupancy, per-turn bill, and
    session bill separately. Assistant transcript entries render a `Crabby`
    identity header in both streamed and completed states, and the live
    transcript backfills the latest user bubble ID after the turn completes so
    fork actions appear immediately.
14. Provider reasoning is preserved when supported. DeepSeek reasoning is
    stored as `reasoning_details` for a unified UI shape, then converted back
    to `reasoning_content` when replaying assistant history to DeepSeek
    thinking-mode calls. Providers that do not support streaming tool calls
    fall back to non-streaming tool-loop calls in the WebSocket path.
15. Cron jobs are stored under the vault and scanned by `server/cron_daemon.py`;
    due jobs run in isolated sessions through the shared non-streaming agent
    runner.
16. Background cron completion notifications are stored on the source session
    and surfaced to clients through WebSocket notifications and the next
    assistant turn.
17. Admin/runtime APIs support config inspection, save, reload, MCP status,
    shutdown, backend-owned profile list/save/activate/delete, and current
    active-profile testing. `/admin/profile/test` and `/admin/profiles*` routes
    are authenticated with the admin token.
18. WebSocket `error` events are reserved for transport/protocol failures.
    Terminal business conditions should complete the turn with `warning`/`done`
    or another non-replayable signal so the same prompt is not executed twice.
    The Obsidian client only falls back to REST on transport failures, not on
    backend-delivered stream errors.

## Cron Behavior

- The model can use `cron_create`, `cron_list`, and `cron_delete` when those
  tools are registered.
- Cron jobs are persisted at `<vault>/.LifeAssistantAgent/data/cron_jobs.json`.
- The daemon scans once per second and consumes jobs FIFO.
- Cron execution waits until session activity is idle, with a 30-minute wait
  cap per queued job.
- Each cron execution uses a new isolated session ID and does not reuse the
  source conversation context.
- REST chat, WebSocket chat, and cron agent turns share
  `server/llm/agent_runner.py`'s `DEFAULT_MAX_AGENT_ITERATIONS`.
- Completion notifications are pushed back to the source session when
  available.
- Cron expressions support standard 5-field minute-level syntax and 6-field
  syntax with seconds first.

## Search Tool Rules

- Use `obsidian_search` first for Obsidian-native knowledge lookup in `.md`
  and `.canvas` files.
- `obsidian_search` is hosted by the running Obsidian plugin and reached
  through `/client-tools/obsidian`.
- `obsidian_search` supports common Obsidian Search DSL semantics: terms,
  phrases, OR, negation, regex, file/path/content/tag/line/block/section/task
  operators, and property queries.
- Use `life_assistant_settings` for the plugin's own config/runtime/profile
  state. It is the intended path for agent self-management and avoids exposing
  `.obsidian` as a general search surface.
- Use `grep`, `glob`, and `read` for non-Obsidian file types, raw text/code/log
  files, or when the Obsidian plugin bridge is disconnected.

## Persona System

- Runtime personas are discovered by recursively loading `PERSONA.md` files
  from `personas/` or `PERSONAS_DIR`.
- The current core personas are `secretary`, `archivist`, `researcher`,
  `philosopher`, and `mentor`.
- The runtime supports Auto, Manual, and None persona modes, with one active
  persona per turn.
- Auto mode routes only when the session has no active auto persona. A
  high-confidence result locks one active persona for the session; low
  confidence, null, or unknown-persona results clear the active persona and the
  current turn runs without a persona prompt.
- Manual mode and None mode override auto routing. The system prompt has one
  current-persona slot, so switching personas replaces the prior persona body
  instead of appending multiple persona prompts.

## Configuration Notes

- General runtime configuration lives in `.env`.
- `PERSONAS_DIR` can override the default repo `personas/` directory used by
  the backend persona registry.
- `PROMPTS_DIR` controls the prompt fragments loaded by the backend. The
  Obsidian plugin sets it to the installed plugin config folder's
  `prompts/` directory, for example
  `<vault>/.obsidian/plugins/life-assistant-agent/config/prompts/`.
- Active LLM secrets/base URL can use generic `LLM_API_KEY` and
  `LLM_BASE_URL`.
- Legacy and provider-specific key fallbacks remain supported:
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`,
  `DASHSCOPE_API_KEY`, `BAILIAN_CODING_PLAN_API_KEY`, `KIMI_API_KEY`,
  `MINIMAX_API_KEY`, and `ZAI_API_KEY`. `MOONSHOT_API_KEY` still appears in
  compat cleanup paths, but the built-in `kimi` preset now targets Kimi Code.
- The built-in `kimi` provider uses `https://api.kimi.com/coding/v1`,
  `kimi-for-coding`, and optional `KIMI_BASE_URL` / `KIMI_API_KEY`.
- Built-in LLM provider IDs are `anthropic`, `openai`, `ollama`, `deepseek`,
  `qwen`, `kimi`, `minimax`, `zhipu`, and `custom_openai`.
- LLM reasoning controls are optional environment settings:
  `LLM_THINKING_MODE`, `LLM_THINKING_BUDGET_TOKENS`, `LLM_REASONING_EFFORT`,
  and `LLM_REASONING_SPLIT`.
- Backend-owned LLM profiles are stored in `.env` as `PROFILE_<id>_*` keys,
  with `ACTIVE_PROFILE_ID` selecting the currently applied profile.
- Managed backend orphan cleanup uses
  `LIFE_ASSISTANT_HOST_HEARTBEAT_FILE`,
  `LIFE_ASSISTANT_HOST_HEARTBEAT_TIMEOUT_SECONDS`,
  `LIFE_ASSISTANT_HOST_PID`, and `LIFE_ASSISTANT_BACKEND_RELOADER_PARENT`.
- `PERSONA_ROUTER_THRESHOLD` controls the minimum confidence needed for auto
  persona lock-in; the default is `0.75`.
- The Obsidian LLM profile editor uses provider/model presets, still allows
  custom model IDs, and saves reasoning controls alongside provider, model,
  base URL, API key, and vision support through the backend admin profile APIs.
- Deleting an LLM profile removes the matching backend `.env`
  `PROFILE_<id>_*` snapshot. If the deleted profile was active, the backend
  activates the next saved profile or clears the active LLM env keys when none
  remain.
- The Obsidian settings UI can create/edit MCP config and trigger backend
  reload.
- Some generated or local-only folders exist, including `node_modules/`,
  `.venv/`, cache folders, logs, and build outputs. Do not treat them as source
  of truth.
- Token fields have separate meanings: `context.total_tokens` is current
  context-window occupancy; `context.actual_usage.total_tokens` is
  provider-returned per-turn usage; `context.cumulative_usage.total_tokens` is
  the session-persisted cumulative provider usage.
- Session IDs must use ASCII letters, digits, underscores, and hyphens, up to
  128 characters. Conversation IDs follow the same character rules. REST
  `/sessions`, `/chat`,
  `/sessions/{session_id}/conversations/{conversation_id}/context-stats`, and
  WebSocket `/sessions/{session_id}/conversations/{conversation_id}/ws` reject
  unsafe IDs before any disk write or lookup.

## Before Editing

When taking over this repo:

1. Read this file first.
2. Check `git status --short` before changing anything.
3. Preserve unrelated user changes.
4. Use source files under `server/`, `obsidian-plugin/src/`, and
   `desktop-pet/src/` as the authority.
5. Treat docs as helpful but possibly stale unless they match current source.
6. After meaningful repo changes, rewrite this file from the new current state.

## Verification Baseline

Use the smallest relevant verification set:

- Backend-only change: `cd server && uv run pytest`, plus
  `cd server && uv run ruff check .` when Python style/imports changed.
- Session-ID validation or session storage hardening:
  `cd server && uv run pytest tests/test_memory.py tests/test_sessions_api.py tests/test_chat_session_validation.py tests/test_websocket_notifications.py`,
  then `cd server && uv run pytest` and `cd server && uv run ruff check .`.
- Session/conversation branch-cache implementation:
  add or run targeted tests for TTL expiry, LRU eviction, serialized-size
  accounting, global-budget eviction, warm hits, and cold rebuilds, then run
  `cd server && uv run pytest`.
- Bash tool change: `cd server && uv run pytest tests/test_bash.py`, then
  `cd server && uv run pytest` and `cd server && uv run ruff check .`.
- Edit tool change: `cd server && uv run pytest tests/test_edit_tool.py`, then
  `cd server && uv run pytest` and `cd server && uv run ruff check .`.
- Token accounting change:
  `cd server && uv run pytest tests/test_token_usage.py tests/test_websocket_notifications.py`,
  plus relevant client build/type checks if UI stats changed.
- Reasoning/thinking or provider-preset config change:
  `cd server && uv run pytest tests/test_token_usage.py tests/test_websocket_notifications.py`,
  `cd obsidian-plugin && npm run test:config`, and
  `cd obsidian-plugin && npm run build`.
- Provider output adapter, backend-owned profile, or active-profile test change:
  `cd server && uv run pytest tests/test_token_usage.py tests/test_admin_api.py tests/test_websocket_notifications.py`,
  `cd server && uv run ruff check .`, `cd obsidian-plugin && npm run test:config`,
  `cd obsidian-plugin && npx tsc --noEmit`, and
  `cd obsidian-plugin && npm run build`.
- Obsidian client-tool bridge or `life_assistant_settings` tool change:
  `cd server && uv run pytest tests/test_obsidian_search_tool.py tests/test_life_assistant_settings_tool.py`,
  `cd server && uv run ruff check .`, `cd obsidian-plugin && npm run test:config`,
  `cd obsidian-plugin && npx tsc --noEmit`, and
  `cd obsidian-plugin && npm run build`.
- Managed backend lifecycle or host-watchdog change:
  `cd server && uv run pytest tests/test_host_watchdog.py tests/test_app_smoke.py`,
  `cd server && uv run ruff check .`, `cd obsidian-plugin && npm run test:config`,
  `cd obsidian-plugin && npx tsc --noEmit`, and
  `cd obsidian-plugin && npm run build`.
- Persona/routing/template change:
  `cd server && uv run pytest tests/test_personas.py tests/test_prompts.py`,
  `cd obsidian-plugin && npm run test:config`, and
  `cd obsidian-plugin && npm run build` when plugin templates or UI payloads changed.
- Cron or agent-runner change: `cd server && uv run pytest`, including
  `server/tests/test_cron.py` and `server/tests/test_agent_runner.py`.
- Obsidian plugin change: `cd obsidian-plugin && npm run build`, plus
  `npm run test:config` for config/runtime/search changes and
  `npm run test:chat-content` for assistant thought rendering changes.
  Use `npm run test:chat-styles` for stylesheet injection or hot-reload
  changes. Run `npx tsc --noEmit` when TypeScript types changed.
- Chat turn ID propagation or live fork UI change: `cd server && uv run pytest
  tests/test_chat_session_validation.py tests/test_websocket_notifications.py
  tests/test_user_turn.py`, `cd server && uv run ruff check .`, `cd
  obsidian-plugin && npm run test:chat-content`, `cd obsidian-plugin && npm
  run test:chat-styles`, `cd obsidian-plugin && npx tsc --noEmit`, and `cd
  obsidian-plugin && npm run build`.
- Prompt assembly change: `cd server && uv run pytest tests/test_prompts.py`,
  plus broader backend tests when prompt changes affect tool use or shared
  runtime behavior.
- Desktop pet change: `cd desktop-pet && npm run typecheck`, `npm run test`,
  or `npm run build` depending on the touched surface.
- WebSocket turn-terminal warning/fallback change:
  `cd server && uv run pytest tests/test_websocket_notifications.py`,
  `cd obsidian-plugin && npx tsc --noEmit`, and
  `cd obsidian-plugin && npm run build`.
- Cross-module behavior: run the relevant backend and client checks together.

## Known Working Assumptions

- Python backend targets Python 3.11+ and uses `uv`.
- Backend framework is FastAPI with uvicorn.
- Obsidian plugin is TypeScript bundled by esbuild.
- Obsidian plugin development mode is activated by `.dev-runtime.json` in the
  installed plugin directory.
- Obsidian plugin dev/deploy helper scripts resolve the target vault from
  `VAULT_PATH`, then Obsidian's local vault metadata, then a generic
  `<home>/ObsidianVault` fallback.
- Production backend runtime state stores `executablePath` relative to the
  installed plugin runtime directory when the executable lives under that
  directory. Launch resolution still accepts legacy absolute paths for existing
  installs.
- Managed backend reuse is verified through `/health`, authenticated
  `/admin/mcp/status`, and authenticated `/admin/profiles`; older backends that
  lack current admin profile APIs should not be adopted.
- Managed backend orphan cleanup is handled by a host heartbeat watchdog, so
  closing Obsidian without a clean plugin unload should still cause the backend
  to exit after the configured heartbeat timeout.
- Desktop pet is Electron, TypeScript, esbuild, and Vitest.
- LLM providers are configured through environment/runtime settings, with
  backend-owned profile APIs as the normal UI path for creating, saving,
  deleting, and activating profiles. The built-in `kimi` preset maps to Kimi
  Code, not Moonshot/Kimi Platform.
- The Obsidian client-tool bridge exposes both `obsidian_search` and
  `life_assistant_settings`; the latter is for agent self-management and
  requires the plugin bridge to be connected.
- Backend session history is no longer capped by `max_turns`; persisted active
  branches retain complete message history until an explicit pruning or
  summarization feature is added.
- Session storage now uses `sessions/<session_id>/manifest.json` plus
  `sessions/<session_id>/conversations/<conversation_id>.json`. Legacy flat
  `sessions/<session_id>.json` files are loaded and rewritten into the new
  layout on startup without needing a separate migration command.
- The session/conversation split and active-branch cache policy are documented
  in `docs/会话设计.md`. The backend has a process-local in-memory branch cache
  with a 30-minute inactivity TTL, 64 MiB process budget, LRU eviction,
  serialized-message-byte size accounting, no separate per-entry hard cap, and
  `sha256(conversation_id:revision|...)` branch fingerprints; active
  conversation switching now reuses that cache before falling back to disk
  materialization.
- REST, WebSocket, Obsidian plugin, and desktop pet now use the explicit
  `session_id` + `conversation_id` contract. The backend can read manifest
  conversation lineage and exclude sibling branches when materializing the
  active branch; the Obsidian plugin now exposes the current-session tree and
  fork flow in the chat UI, while the history list remains separate.
- Backend chat REST responses and WebSocket `done` events now carry both
  `message_id` and `user_message_id`; the Obsidian plugin backfills the latest
  rendered user bubble after a turn completes instead of generating temporary
  client IDs.
- `obsidian-plugin/src/chat/chatStyles.ts` now upserts the shared style tag on
  reload, so hot-reloading the plugin refreshes chat CSS instead of leaving an
  old `<style id="life-assistant-chat-styles">` node in place.
- The backend `bash` tool is non-interactive. On Windows it runs PowerShell
  without loading the profile, forces UTF-8 output, and accepts top-level
  `&&` / `||` command chains by translating them before execution.
- The backend system prompt dynamically injects the runtime platform label,
  `sys.platform`, and the shell used by the `bash` tool.
- The backend `edit` tool matches text after newline normalization so snippets
  copied from `read` can update LF or CRLF notes, but writeback preserves the
  target file's dominant newline style.
- REST chat, WebSocket chat, and cron agent turns share
  `server/llm/agent_runner.py`'s `DEFAULT_MAX_AGENT_ITERATIONS`, currently 200.
- WebSocket `error` events are reserved for transport/protocol failures that
  should abort the stream; terminal business conditions should complete the
  turn with `warning`/`done` or another non-replayable signal.
- The Obsidian client distinguishes WebSocket transport failures from backend
  stream errors. Only transport failures may fall back to REST; server-delivered
  stream errors stay terminal.
- The checked-in runtime persona set is exactly `secretary`, `archivist`,
  `researcher`, `philosopher`, and `mentor`.
- Auto persona routing no longer uses keyword prefiltering. The router sends
  all loaded persona metadata, routing hints, examples, body text, and source
  path to the configured LLM in stable `persona.id` order and expects strict
  JSON with `persona_id`, `confidence`, `reason`, and `summary`.
- Thinking/reasoning controls are opt-in and provider-specific. Unsupported
  models may still reject configured parameters, and leaving fields blank
  preserves previous behavior.
- Provider presets declare `reasoning_output_shape`: Anthropic uses
  `anthropic_blocks`, DeepSeek, Qwen, and Kimi use `reasoning_content`,
  MiniMax and `custom_openai` use `reasoning_details`, and first-pass built-in
  OpenAI-compatible providers without official reasoning output handling use
  `none`.
- DeepSeek thought display depends on `LLM_THINKING_MODE=enabled` and a model
  that returns `reasoning_content`. Historical sessions reconstruct thought
  blocks from saved reasoning data.
