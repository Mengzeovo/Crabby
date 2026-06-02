# Agent Handoff

Last rewritten: 2026-05-25

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
- `docs/记忆沉淀设计.md`: long-term memory facet model, directory layout,
  registry rules, write/search tool contract, diary relationship, and
  current implemented/pending status for local memory, Diary V1, MemPalace
  double-write, full-text search, and aggregation.
- `docs/会话上下文折叠与展开设计.md`: future design note for compressing
  tool-heavy session spans into reusable summaries and expanding them on
  demand.
- `docs/Vault搜索索引与语义召回设计.md`: future design note for adding a
  rebuildable Vault search index, MemPalace-backed semantic recall, stable
  source references back to Vault originals, result verification, and separate
  MemPalace wings for long-term memory versus ordinary Vault document search.
- `docs/MEMPALACE_INTEGRATION.md`: MemPalace MCP service reference; treat
  MemPalace as a downstream semantic index and knowledge-graph layer, not the
  canonical memory store.
- `docs/execution-plan.md`: release roadmap.
- `docs/release-notes-0.3.0.md`: Release 0.3.0 memory-focused feature summary,
  operational notes, and remaining memory roadmap items.
- `docs/growth-vision.md`: product vision and phased growth plan. Current
  growth-feedback direction is user-initiated: `/learn` is the preferred entry
  for learning/review feedback, ordinary chat only deposits durable learning
  signals, and cron-style reminders should stay low-interruption rather than
  automatically starting lessons or evaluations.
- `docs/claude-code-analysis.md`: design reference, not current implementation.
- `docs/agent-harness-重构-2026-05.md`: current agent harness refactor
  status, completed extraction work, future child-agent tool safety boundary
  plan for context-injection risk reduction, and remaining loop-consolidation
  notes.
- `docs/prompt-cache-现状与优化方向.md`: current prompt-cache limitations and
  future provider-cache optimization direction; no implementation yet.
- `prompts/`: repository default prompt fragments.
- `personas/`: checked-in runtime personas.
- `skills/`: checked-in runtime skills.
- `reference/`: reference material.
- `scripts/`: backend runtime build and release packaging helpers.
- `scripts/build-backend-runtime.py`: builds a PyInstaller backend runtime by
  running PyInstaller in the `server/` uv project with PyInstaller injected for
  that command. Generated PyInstaller `.spec` files are ignored by git.
- `scripts/package-obsidian-release.py`: builds a manual-install Obsidian
  plugin zip with `manifest.json`, `main.js`, relative production
  `runtime/state.json`, and a prebuilt backend binary. It resolves
  `npm.cmd` on Windows when running the plugin build.
- `README.md`: release-facing overview, dev commands, packaging, install,
  first-run setup, runtime data, and troubleshooting.
- `LICENSE`: MIT License for the repository.
- `.env`: local secrets and runtime settings. Do not commit real secrets.

## Backend Map

Important backend files and folders:

- `server/main.py`: FastAPI app entry, route assembly, MCP startup,
  loop/cron startup, background daemons, and the packaged
  `--crabby-vault-tools-runner` subprocess entry used by Vault tools.
- `server/vault_tools_entrypoint.py`: dependency-light shared subprocess
  entrypoint constants, imported by `main.py` before backend modules so the
  packaged Vault tools runner can dispatch without initializing the backend app.
- `server/config.py`: environment-backed settings.
- `server/diary_config.py`: Vault-root diary config loader/validator for
  `<vault>/.crabby/config/diary.json`, with Vault-relative root/template path
  normalization and defaults for daily, weekly, monthly, quarterly, and yearly
  templates.
- `server/runtime_config.py`: runtime config helpers for prompts, personas,
  and skills.
- `server/mcp_config.py`: MCP config loading and environment interpolation.
- `server/mcp_runtime.py`: MCP startup, status, and transactional reload. When
  Vault tools are enabled, it launches `vault_tools_runner.py` directly in dev
  mode and launches the bundled backend executable with
  `--crabby-vault-tools-runner` in PyInstaller mode so the runner does not
  start a second backend server.
- `server/host_watchdog.py`: host heartbeat watchdog for managed backends.
- `server/loop_daemon.py`: background scanner/queue/consumer for
  non-interactive Loop jobs and cron-compatible jobs. It waits for global
  session idleness before executing jobs in isolated sessions and pushes
  completion notifications back to source sessions.
- `server/loop_manager.py`: Loop job persistence under runtime data, including
  migration from legacy `cron_jobs.json` into the Loop job schema.
- `server/loop_models.py`: Loop job models, cron-compatible aliases, cron
  validation, and shared fire-time logic.
- `server/dream_daemon.py`: low-frequency background memory maintenance
  scheduler. It persists `<vault>/.crabby/data/dream_state.json`, schedules
  the first and subsequent dream attempts 7-14 days out, enforces a minimum
  7-day gap between dream starts, requires 30 minutes of real-user idle time
  plus global session idleness, and interrupts running dream work when the user
  starts chatting.
- `server/api/`: REST, WebSocket, attachments, sessions, client-tool bridge,
  and admin APIs.
- `server/api/rest.py`: REST chat, diary-write bridge, context stats, persona,
  skill, health/version, capability, and admin-facing routes with safe ID
  validation.
- `server/api/sessions.py`: session metadata and message-history APIs.
- `server/api/websocket.py`: streaming chat WebSocket, turn-id based abort API,
  active-turn cancellation registry, tool-loop warnings, safe conversation ID
  checks, and delegation of frontend loop-control messages. When a chat turn is
  aborted, it cancels the active backend task, persists partial text or a
  complete cancelled tool round (`assistant tool_use` plus completed/synthetic
  `tool_result` blocks), records accumulated usage when present, and writes a
  short assistant abort marker so the next turn keeps a valid provider message
  sequence.
- `server/api/loop_control.py`: WebSocket loop-control handler for
  `loop_submit`, `loop_next`, `loop_stop`, and `loop_pause`. It resolves the
  same Vault runtime data path as loop tools, updates Loop jobs, persists
  `active_loop_id` changes, and sends compact frontend events.
- `server/api/client_tools.py`: WebSocket bridge for Obsidian-hosted tools. It
  removes pending client-tool RPC futures when the owning chat turn is cancelled,
  so late plugin results are ignored instead of keeping the turn alive.
- `server/llm/`: LLM client, provider presets, output adapters, profile store,
  profile probe, prompt assembly, context metering, token accounting, session
  activity, and tool loop helpers.
- `server/llm/providers.py`: built-in provider presets, base URLs, key
  fallbacks, reasoning/output shapes, and streaming-tool support flags.
- `server/llm/output_adapters.py`: normalizes provider chunks/responses into
  text, reasoning, tool, and done events, and exposes shared reasoning-detail
  text extraction for non-streaming paths.
- `server/llm/profile_store.py`: persists backend-owned profiles in `.env`.
- `server/llm/profile_probe.py`: validates/tests active profiles.
- `server/llm/agent_runner.py`: shared non-streaming agent runner for REST,
  fallback WebSocket paths, cron, and other background turns.
- `server/llm/tools_schema.py`: shared helper for assembling per-round eager
  tool schemas plus the full system-prompt tool catalog. It applies skill
  `allowed_tools` filters when supplied and promotes deferred tools discovered
  through `tool_search` for the next LLM round.
- `server/llm/tool_executor.py`: validates, runs, and formats tool calls into
  compact LLM-visible receipts plus structured UI card payloads with full
  output, summaries, previews, detail refs, status, metadata, truncation/cache
  details, and elapsed time. When an active skill supplies an allowed-tool
  whitelist, the whitelist is carried on `Context.allowed_tool_names` and
  enforced before execution.
- `server/llm/token_usage.py`: normalizes provider usage, accumulates
  per-turn/session totals, and provides the shared helper that records a turn's
  accumulated usage onto the in-memory session before callers persist it.
- `server/personas/`: persona loader, registry, router, runtime selection, and
  API models.
- `server/tools/`: built-in tools such as `obsidian_search`,
  `crabby_settings`, `read`, `grep`, `glob`, `bash`, `edit`, `fetch`, `cron`,
  `task_query`, and memory tools.
- `server/tools/registry.py`: built-in/dynamic tool registry. It also exposes
  `sync_configurable_builtin_tools()` so admin settings reloads can add or
  remove the `bash` tool immediately when `BASH_ENABLED` changes.
- `server/tools/bash.py`: non-interactive cross-platform shell tool. On
  Windows it launches PowerShell without a profile, forces UTF-8 output,
  translates top-level `&&` / `||` chains for PowerShell 5.x compatibility, and
  kills the foreground process tree when the owning chat turn is cancelled.
- `server/tools/tool_result_read.py`: read-only detail expansion tool for
  previous tool-result cards in the current tool context session and
  conversation only. It reads persisted UI-only `ui.output` by `detail_ref` or
  `tool_use_id` with offset/limit/query controls, and can safely expand
  truncated tool cache files only when `cache_path` resolves inside the runtime
  `cache/tool-results/` directory.
- `server/tools/edit.py`: Vault-relative exact replacement/new-file tool that
  preserves dominant newline style, rejects paths outside the Vault, and returns
  user-readable change summaries plus structured `metadata.file_changes` entries
  for successful writes.
- `server/tools/base.py`: shared tool formatter and UI payload helper. LLM-visible
  tool errors now treat `metadata.error` as an error prefix, not just blocked /
  timeout / exit-code failures.
- `server/tools/crabby_settings.py`: self-management tool that talks to the
  Obsidian bridge and backend admin profile APIs.
- `server/tools/tool_search.py`: session-scoped deferred-tool discovery tool.
  It respects `Context.allowed_tool_names`, so restricted skills cannot discover
  deferred tools that their `allowed_tools` whitelist excludes.
- `server/tools/diary.py`: `diary_write` and `diary_read` tools for
  Vault-facing diary, weekly, monthly, quarterly, and yearly records. Paths and
  templates come from `diary.json`; writes create from the configured template
  or append timestamped blocks without rewriting existing user text, with an
  optional `entry_key` marker for idempotent generated entries.
- `server/tools/memory_search.py`: read-only long-term memory recall tool. It
  exposes `list_registry`, structured `search`, and `full_text` modes so Crabby
  can run a model-orchestrated flow: inspect registry topics/domains, choose
  facet and created/updated time filters, judge structured candidates, then
  fall back to local full-text snippets over file names/titles/body headings
  before using external search. ISO datetime filters are compared in local
  wall-clock time so timezone-aware inputs normalize against stored naive
  timestamps. Common filter validation rejects invalid `kind` values instead of
  treating unknown kinds as empty search results.
- `server/tools/memory_inventory.py`: maintenance inventory tool for all
  long-term memory states. It defaults to `state=all`, supports facet/time/name
  filters plus pagination, and returns compact metadata, link fields, Vault
  relative paths, and snippets for dream/maintenance candidate selection. It
  uses the same common facet filter validation as `memory_search`, including
  `kind` validation. It is hidden from the normal chat tool catalog and
  `tool_search`.
- `server/tools/memory_read.py`: memory-scoped reader that resolves a global
  memory `name` through `NAME_INDEX.md`, reads only files under
  `<vault>/.crabby/memory/`, and returns full frontmatter/body with truncation
  cache support for active, archived, and invalidated memories. It is also
  hidden from the normal chat tool catalog and `tool_search`.
- `server/memory/catalog.py`: shared scanner/filter helper for Vault-backed
  memory documents, used by `memory_search` and `memory_inventory`.
- `server/tools/loop_task.py`: interactive loop tools plus cron-compatible
  create/list/delete tools, all routed through LoopManager/runtime data.
- `server/memory/`: file-backed session manifest/conversation storage, legacy
  flat-session migration, active branch materialization/cache, ID validation,
  actual usage snapshots, pending notifications, per-conversation auto-save
  checkpoints, and auto-save support.
- `server/memory/auto_save.py`: cursor-based memory auto-save review daemon.
  It snapshots the active conversation window at enqueue time, rebases against
  the latest checkpoint before processing, restricts the background memory
  agent to `memory_search` / `memory_write`, rejects any non-memory tool use
  before execution, and advances per-conversation checkpoints only after
  successful review.
- `server/memory/dream.py`: maintenance dream runner. It plans with
  `memory_inventory` / `memory_read` only, then commits validated aggregation
  plans by writing a new active summary memory and archiving source memories;
  invalidation is reserved for replaced, expired, or conflicting facts. Plan
  validation rejects missing or memory-root-escaping source/invalidation targets,
  and commit checks cancellation before each write/archive action.
- `server/memory/maintenance.py`: internal memory lifecycle helpers used by
  dream and `memory_write` for frontmatter state transitions. It is not an
  LLM-visible tool.
- `server/memory/layout.py`: creates the Vault-backed long-term memory layout
  under `<vault>/.crabby/memory/`, seeds `MEMORY.md`, `REGISTRY.md`, the
  `user/`, `feedback/`, `project/`, and `reference/` type directories, keeps the
  legacy editable diary template at `<vault>/.crabby/templates/diary.md`, and
  seeds `<vault>/.crabby/templates/diary/{daily,weekly,monthly,quarterly,yearly}.md`
  without overwriting existing files. If the new daily template is missing and
  legacy `diary.md` already exists, daily is initialized from the legacy file.
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
uv run --with pyinstaller python ../scripts/build-backend-runtime.py --version 0.3.5
```

## Obsidian Plugin Map

Important plugin files and folders:

- `obsidian-plugin/src/main.ts`: plugin entry point. It passes the live
  `manifest.version` into the Vault search index so plugin version changes can
  invalidate stale persisted indexes without a duplicated version constant.
- `obsidian-plugin/src/settings.ts`: settings UI, backend-owned profile
  controls, active-profile test button, local backend program/MCP settings, and
  Diary root/template Vault-relative path autocomplete. It also exposes
  `.env`-backed `AUTO_SAVE_INTERVAL`, `BASH_ENABLED`, and
  `VAULT_TOOLS_ENABLED`; the Tools and Permissions section owns tool toggles
  plus runtime MCP/Vault tool status and detail viewing, while the MCP section
  is limited to service config path/editor actions. Vault user tools are
  managed in a separate modal for `<vault>/.crabby/tools/` directory creation,
  example creation, status, and reload. Diary template suggestions include
  Obsidian-loaded Markdown files
  plus adapter-listed hidden `.crabby/templates/diary/` files. The local
  backend status panel shows 开发版 / 正式版 as user-facing runtime labels,
  preferring the live `/health` backend version and falling back to the runtime
  state version while offline; internal runtime mode values remain `dev` /
  `production`.
- `obsidian-plugin/src/api/client.ts`: backend API client, WebSocket handling,
  turn-id generation for streaming chat, abort API calls before closing active
  chat WebSockets, transport/server error classification, admin reload/status
  calls, profile calls, active-profile test calls, and direct diary-write calls.
- `obsidian-plugin/src/chat/`: chat view, transcript, context/token usage bar,
  composer, assistant rendering, personas, profiles, sessions, current-session
  tree, fork actions, stylesheet injection, turn runner, stop-button handling
  that waits for backend abort acknowledgement before clearing sending state,
  local cross-session turn management that lets one session continue replying
  in the background while the visible session sends another turn,
  inline loop-to-diary prompts, and tool-block metadata rendering including
  file-change counts from `metadata.file_changes`. The context/token bar
  separates current context window estimates from provider-returned usage
  totals; usage labels are not a direct context-window bill, and
  reasoning/cache numbers are displayed as provider sub-breakdowns rather than
  extra additive totals.
- `obsidian-plugin/src/chat/ChatView.ts`: chat view shell. When no saved LLM
  profile exists, it shows a dismissing banner whose settings action opens the
  Obsidian settings modal and switches to the Crabby plugin tab.
- `obsidian-plugin/src/chat/chatDiaryPrompt.ts`: inline prompt rendered above
  the chat input after `loop_stop`, allowing the user to write the loop summary
  into today's diary only for non-error loop completions with a `job_id`. It
  checks both Obsidian's file cache and the Vault filesystem so default hidden
  `.crabby/templates/diary/daily.md` templates can enable the write action.
- `obsidian-plugin/src/chat/chatAssistantContent.ts`: assistant markdown and
  thought rendering helpers, including shared `Crabby` identity header.
- `obsidian-plugin/src/clientTools/`: WebSocket client-tool bridge.
- `obsidian-plugin/src/clientTools/obsidianClientTools.ts`: routes backend RPC
  requests to plugin-hosted tools.
- `obsidian-plugin/src/clientTools/searchInput.ts`: normalizes
  `obsidian_search` bridge input and intentionally strips internal
  `debug_score_details` from backend-visible tool requests.
- `obsidian-plugin/src/clientTools/crabbySettingsTool.ts`: plugin-hosted
  self-management tool for settings and backend-owned profiles.
- `obsidian-plugin/src/config/`: backend, profile sync, provider presets, and
  MCP config helpers.
- `obsidian-plugin/src/config/llmProviders.ts`: provider/model presets and UI
  capability metadata.
- `obsidian-plugin/src/runtime/`: backend runtime management, host heartbeat,
  managed-backend reuse/shutdown, runtime state path helpers, default config
  templates, and first-run creation of Vault-root memory/template directories.
- `obsidian-plugin/src/runtime/defaultConfigTemplates.ts`: seeds default prompt
  and persona templates. Persona seeding is based on discovered `PERSONA.md`
  files, so incidental files do not block first-run defaults.
- `obsidian-plugin/src/runtime/runtimeDataMigration.ts`: migrates legacy
  plugin-local `config/`, `data/`, and `logs/` into Vault-root `.crabby/`
  storage without overwriting existing target files.
- `obsidian-plugin/src/runtime/runtimeState.ts`: serializes production backend
  executable paths relative to the installed plugin runtime directory and
  resolves relative/legacy absolute paths at launch.
- `obsidian-plugin/src/search/`: Obsidian-search-compatible DSL parsing,
  `.md` / `.canvas` search implementation, and persisted Vault search index.
  Ranking is field-aware: filename, title, aliases, headings, tags/properties,
  path, tasks, body BM25-lite, query-term coverage, phrase hits, and a small
  recency boost contribute to the final score. Source references include stable
  content hashes and, for block matches with line metadata, block-wide line
  spans. Internal `debug_score_details` is available to tests/local diagnostics
  but is not accepted through the client bridge or shown in normal tool output.
  `SearchIndex` loads a matching on-disk index when possible, reconciles by
  mtime/size on warm start, and forces a full rebuild when the last full rebuild
  is older than 30 days.
- `obsidian-plugin/scripts/`: repo-local verification scripts.
- `obsidian-plugin/scripts/test-chat-tools.js`: verifies tool-result payload
  normalization and chat transcript tool-block rendering behavior.
- `obsidian-plugin/scripts/test-api-client-abort.js`: verifies streaming chat
  turn-id propagation to the abort API and confirms the client keeps the stream
  pending until abort acknowledgement before closing the WebSocket.
- `obsidian-plugin/scripts/test-backend-config.js`: platform-neutral config
  regression coverage for backend config, runtime state, search engine, and
  Obsidian vault resolution. It uses OS-specific Obsidian metadata locations
  and vault path literals so `npm run test:config` passes on Windows, macOS,
  and Linux.
- `obsidian-plugin/manifest.json`: plugin manifest.
- `obsidian-plugin/main.js`: built plugin bundle.

Plugin commands:

```bash
cd obsidian-plugin
npm ci
npm run test:config
npm run test:search-index
npm run test:chat-content
npm run test:api-client
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
11. Before each LLM round trip, the backend rebuilds the per-turn eager tool
    schema from the registry, active skill filters, and per-session
    `tool_search` discoveries so deferred tools discovered in the previous
    round can be called immediately. The same active skill allowlist is carried
    into tool execution context so `tool_search` results and direct tool
    execution cannot escape skill restrictions.
12. LLM responses are normalized into text, reasoning, tool calls, stop
    reasons, and usage.
13. Tool execution routes through built-in tools, connected MCP tools, and the
    Obsidian client-tool bridge. Tool results include compact model-visible
    receipts plus structured UI card payloads with full UI output, summaries,
    previews, detail refs, and `success`, `warning`, or `error` status.
14. Responses include streamed events or structured REST output plus context
    stats, per-turn usage, cumulative session usage when available, and
    assistant/user message IDs. WebSocket `tool_result` events and REST
    `tool_calls` carry the full tool UI card payload, while persisted
    `tool_result.content` stays compact for future model context.
15. When a chat turn completes with a successful `loop_stop` tool result, the
    Obsidian chat view can show an inline prompt directly above the input box
    to write the loop summary to today's diary through `/diary/write`. The
    prompt requires a non-error loop result with `metadata.job_id`; stale or
    missing loop jobs must not be treated as writable summaries. If the configured
    daily template file is missing, the prompt offers settings/close actions and
    does not show a write button.
16. Auto-save queues frozen conversation review windows, uses
    `auto_save_checkpoints` to continue from the last reviewed message for each
    conversation, and writes only strict long-term value through
    `memory_write`. Diary entries are user-facing records created through the
    diary skill or explicit inline user confirmation. Unresolved tool errors
    and max-iteration exhaustion do not advance the checkpoint.
17. Dream maintenance runs as a separate low-frequency daemon. It does not run
    immediately on first startup; it schedules attempts 7-14 days out, requires
    30 minutes of real-user idle time and global `session_activity` idleness,
    and cancels promptly when a new user chat starts. Dream uses maintenance
    memory tools only during planning and internal helpers for source-memory
    archiving, so ordinary chat is not blocked and does not see archived /
    invalidated memory bodies.
18. Cron-compatible Loop jobs run in isolated sessions through the shared
    non-streaming agent runner and push completion notifications back to source
    sessions.
19. WebSocket `error` events are reserved for transport/protocol failures.
    Backend-delivered business conditions should use `warning`/`done`.
20. The Obsidian plugin supports local frontend concurrency across different
    sessions by running each active chat turn through an isolated client /
    WebSocket. The visible conversation owns live DOM streaming; when a running
    session is hidden, the turn continues in the background; returning before
    completion resumes the accumulated foreground stream, and returning after
    completion reloads persisted history. A single session is still limited to
    one active conversation turn at a time.

## Session And Conversation Rules

- Session IDs and conversation IDs use ASCII letters, digits, underscores, and
  hyphens, up to 128 chars.
- Session storage uses `sessions/<session_id>/manifest.json` plus
  `sessions/<session_id>/conversations/<conversation_id>.json`.
- Session manifests may include `auto_save_checkpoints`, keyed by
  `conversation_id`, with the last reviewed message ID, revision, branch
  fingerprint, and review timestamp.
- Forked conversations inherit the parent auto-save checkpoint only when the
  checkpointed message is at or before the fork point; parent checkpoints after
  the fork point are not inherited.
- Legacy flat sessions are loaded and rewritten into the new layout.
- Active branch materialization excludes sibling branches.
- Branch cache is process-local memory with 30-minute inactivity TTL, 64 MiB
  budget, LRU eviction, serialized-byte accounting, and
  `sha256(conversation_id:revision|...)` branch fingerprints.
- Session history is not capped by `max_turns`; pruning/summarization is a
  future explicit feature.
- Persisted `tool_result` blocks may contain a UI-only `ui` payload, including
  full `ui.output`, for frontend restoration and `tool_result_read` detail
  expansion. `tool_result_read` is limited to the current session/conversation
  from the execution context and must not accept model-supplied session or
  conversation overrides. Model-message materialization strips UI-only fields
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
- The checked-in `diary` skill routes diary/journal/review requests to
  `diary_read` and `diary_write`, forbids `edit`/`bash` for diary writes, and
  treats weekly/monthly/quarterly/yearly records as explicit-request only.
- A skill with a non-empty `allowed_tools` list restricts the per-turn schema,
  `tool_search` discovery results, and execution-time tool calls to that
  whitelist. A skill with `allowed_tools=[]` imposes no restriction.

## Configuration Notes

- All runtime configuration, secrets, and user data live under the vault, never in
  the repository. The backend (whether in dev or production mode) reads its `.env`
  from `<vault>/.crabby/config/.env`. Runtime state lives under
  `<vault>/.crabby/`, with `config/`, `data/`, `logs/`, `memory/`, and
  `templates/` subdirectories.
- Long-term memory source files live under `<vault>/.crabby/memory/` as
  `MEMORY.md`, `REGISTRY.md`, and `user/`, `feedback/`, `project/`, and
  `reference/` type directories. Topic subdirectories are created by memory
  write code when a memory is actually written. Topic values may include
  Chinese / Unicode letters and digits plus non-edge hyphens, while memory
  `name` values remain ASCII kebab-case file slugs. `MEMORY.md` is a backend memory
  policy/reference file, not a full memory index or main prompt payload.
- The main chat prompt only carries a short memory hint. Relevant turns call
  `memory_search` on demand, while `auto_save` remains a separate background,
  checkpoint-driven task that does not block chat. The memory hint describes a
  model-orchestrated recall flow: fuzzy, semantic, cross-topic, or exploratory
  questions should prefer `mempalace_search` when available; exact facts,
  decisions, preferences, and other state-sensitive lookups should prefer
  `memory_search`, using `list_registry`, structured `search`, and `full_text`
  as needed, then escalating to external search only outside the memory tool if
  memory remains insufficient.
- MemPalace is an optional downstream semantic index and knowledge-graph
  layer. Vault Markdown under `<vault>/.crabby/memory/` remains the canonical
  source of truth, and current code does not double-write to MemPalace yet.
- Planned memory frontmatter follows the facet model in
  `docs/记忆沉淀设计.md`: `type`, `topic`, `domain`, `kind`, `state`,
  `valid_from`, and `valid_to`. Timestamps, links, and provenance are
  frontmatter metadata but not facet fields. The facet model does not include
  `scope`, `confidence`, or `description`.
- Memory lifecycle states are `active`, `archived`, and `invalidated`.
  `memory_search` is the ordinary recall tool and defaults to `active`;
  `memory_inventory` and `memory_read` are maintenance-oriented tools for
  inspecting archived/invalidated provenance without making those states part of
  default chat recall. They stay registered in the backend but are filtered out
  of normal chat tool catalogs and `tool_search`. There is no hard-delete memory
  tool in the current V1.
- Dream memory maintenance is enabled by default. It persists scheduler state at
  `<vault>/.crabby/data/dream_state.json`, draws each next run uniformly between
  7 and 14 days, enforces a minimum 7-day gap between dream starts, and only
  runs after 30 minutes without real user chat plus global session idleness.
  Relevant settings are `DREAM_ENABLED`, `DREAM_IDLE_SECONDS`,
  `DREAM_MIN_INTERVAL_SECONDS`, `DREAM_MAX_INTERVAL_SECONDS`,
  `DREAM_SCAN_INTERVAL_SECONDS`, `DREAM_MIN_GROUP_SIZE`, and
  `DREAM_MAX_ITERATIONS`.
- `memory_search` distinguishes fact validity from file recency:
  `valid_at` filters `valid_from`/`valid_to`, while `created_after`,
  `created_before`, `updated_after`, and `updated_before` filter memory
  document timestamps. Timezone-aware ISO datetimes are normalized to the
  local wall clock before comparison.
- Diary configuration lives at `<vault>/.crabby/config/diary.json`, with
  `rootPath` defaulting to `Journal` and `templatePaths.daily`, `weekly`,
  `monthly`, `quarterly`, and `yearly` pointing by default to
  `.crabby/templates/diary/{period}.md`. Diary entries themselves are
  user-facing Vault notes outside `.crabby/memory/`: daily entries use
  `Journal/daily/YYYY/MM/YYYY-MM-DD.md`, weekly entries use ISO week-year
  `Journal/weekly/YYYY/YYYY-Www.md`, and monthly/quarterly/yearly entries use
  their corresponding period folders. The legacy
  `<vault>/.crabby/templates/diary.md` file is kept for compatibility and can
  seed the new daily template if needed.
- `diary_write` is a Vault write and is blocked in restricted tool contexts,
  while `diary_read` remains read-only. Diary template rendering only replaces
  placeholders in the template text, so user content containing `{{...}}`
  remains literal. Diary is separate from memory auto-save and is not generated
  automatically in the current V1.
- Memory auto-save only accepts `memory_search` / `memory_write`; any
  non-memory tool call returned by the model is rejected before execution.
- `AUTO_SAVE_INTERVAL` controls memory auto-save cadence by conversation turn
  count; `0` disables triggering. The Obsidian settings UI writes this value to
  `<vault>/.crabby/config/.env` and uses `/admin/reload-settings` so ordinary
  cadence changes do not require restarting the backend.
- `BASH_ENABLED` controls whether the built-in `bash` tool is registered.
  Admin settings reload hot-syncs this tool without reconnecting MCP servers.
- `VAULT_TOOLS_ENABLED` controls the internal `vault-tools` MCP subprocess for
  user-defined tools under `<vault>/.crabby/tools/`. The Obsidian settings UI
  saves this value through `.env` and uses full admin reload so MCP state and
  status reflect the change.
- Tool errors should expose `metadata.error` so the LLM sees `[error]` instead
  of a success prefix. Loop tools, including `loop_stop`, must mark missing jobs
  as errors rather than successful textual results.
- The plugin and backend derive vault paths from the `VAULT_PATH` environment
  variable set by the plugin at startup. The backend falls back to the repo root
  when `VAULT_PATH` is absent (e.g., bare `uv run python main.py` outside of
  the plugin).
- Plugin install/runtime assets stay under
  `<vault>/.obsidian/plugins/crabby/`, so the plugin folder can be replaced
  without deleting sessions or provider configuration.
- `PROMPTS_DIR` controls prompt fragments.
- `PERSONAS_DIR` controls runtime personas.
- Active LLM secrets/base URL can use generic `LLM_API_KEY` and
  `LLM_BASE_URL`.
- Provider-specific fallbacks include `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `BAILIAN_CODING_PLAN_API_KEY`,
  `KIMI_API_KEY`, `MINIMAX_API_KEY`, and `ZAI_API_KEY`.
- Built-in provider IDs are `anthropic`, `openai`, `deepseek`,
  `qwen`, `kimi`, `minimax`, `zhipu`, and `custom_openai`.
- `kimi` targets Kimi Code: `https://api.kimi.com/coding/v1` and
  `kimi-for-coding`.
- Optional reasoning controls: `LLM_THINKING_MODE`,
  `LLM_THINKING_BUDGET_TOKENS`, `LLM_REASONING_EFFORT`,
  `LLM_REASONING_SPLIT`.
- Backend-owned profiles are stored in `.env` as `PROFILE_<id>_*`, with
  `ACTIVE_PROFILE_ID` selecting the active profile.
- The backend runtime dependency set includes `tzdata` so PyInstaller Windows
  builds bundle IANA timezone data for any future named-timezone use.
- Backend-owned profile IDs must be env-key safe: ASCII letters, digits, and
  underscores only, up to 64 chars.
- In the plugin settings UI, "添加配置" creates a local editable draft card;
  the profile is written to the backend `.env` only when the card's save/apply
  action calls the backend profile admin API. Draft profiles are preserved
  across settings refreshes but are ignored by startup migration, chat model
  selection, and send-time profile activation until saved.
- The plugin settings UI calls the managed backend install/start section
  "本地后端程序". The persisted setting key remains `runtimeManifestUrl`, but
  the user-facing field is "后端程序下载清单 URL" and the install action is
  "安装/更新本地后端程序".
- Managed backend cleanup uses `CRABBY_HOST_HEARTBEAT_FILE`,
  `CRABBY_HOST_HEARTBEAT_TIMEOUT_SECONDS`, `CRABBY_HOST_PID`, and
  `CRABBY_BACKEND_RELOADER_PARENT`.
- `PERSONA_ROUTER_THRESHOLD` defaults to `0.75`.

## Search Tool Rules

- Use `obsidian_search` first for Obsidian-native lookup in `.md` and
  `.canvas` files.
- Use `mempalace_search` first for fuzzy, semantic, cross-topic, or
  exploratory memory lookups when the MemPalace MCP tool is available; use
  `memory_search` first for exact facts, decisions, preferences, and current
  state.
- Use `memory_inventory` and `memory_read` only for maintenance-style review,
  dream preparation, or explicit full-state memory inspection; ordinary chat
  recall should stay on `memory_search` so archived/invalidated memories do not
  contaminate current answers. Normal chat contexts must not surface these two
  tools in the prompt or `tool_search` results.
- `obsidian_search` is hosted by the running plugin and reached through the
  `/client-tools/obsidian` bridge.
- It supports common Obsidian Search DSL semantics: terms, phrases, OR,
  negation, regex, file/path/content/tag/line/block/section/task operators,
  and property queries. Default result ordering uses field-aware relevance
  scoring with BM25-lite body normalization, query coverage, phrase boosts, and
  only a small recency tie-break boost.
- Use `crabby_settings` for plugin runtime/profile/settings state.
- Use `grep`, `glob`, and `read` for non-Obsidian files, raw text/code/logs, or
  when the bridge is disconnected.

## Cron Behavior

- Tools: `cron_create`, `cron_list`, `cron_delete`.
- Persistence: `<vault>/.crabby/data/cron_jobs.json` in
  plugin-managed production runs, or `DATA_DIR/cron_jobs.json` generally.
- Daemon scans once per second and consumes due jobs FIFO.
- Non-interactive loop/cron jobs only fire while their status is `active`;
  paused/done jobs are skipped by `should_fire`.
- Execution waits for idle session activity, up to 30 minutes.
- Each run uses a new isolated session and does not reuse source conversation
  context.
- Completion notifications are stored on the source session and pushed through
  WebSocket when possible.
- Supports standard 5-field cron and 6-field seconds-first cron.
- `cron_create` and `skills/loop/SKILL.md` must describe the 6-field
  seconds-first form in model-visible text so Crabby does not incorrectly claim
  cron is 5-field-only.

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
- Diary tool/config/skill change:
  `cd server && uv run pytest tests/test_diary_tool.py tests/test_diary_api.py tests/test_tool_executor.py tests/test_memory_layout.py tests/test_skills.py`,
  `cd server && uv run ruff check .`.
  Add `cd obsidian-plugin && npm run test:config && npx tsc --noEmit && npm run build`
  when the diary settings sync path or plugin runtime layout changes.
- Memory write/search/inventory/read, memory checkpoint, or memory provenance
  change:
  `cd server && uv run pytest tests/test_auto_save.py tests/test_memory.py tests/test_memory_tools.py tests/test_memory_dream.py tests/test_dream_daemon.py`,
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
- CI uses Node 24-compatible GitHub Actions majors:
  `actions/checkout@v6`, `actions/setup-python@v6`,
  `actions/setup-node@v6`, and `astral-sh/setup-uv@v8`.

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
  `ui` payloads share the same tool UI card shape with ID, name, full output,
  summary, input summary, output preview, optional detail ref, metadata, status,
  truncation/cache fields, and elapsed time when available.
- Successful `edit` tool writes include a concise text change summary in the
  model-visible tool result plus `metadata.file_changes` entries with path,
  operation, replacement count, replace-all flag, old/new previews, and character
  counts for UI restoration and non-git user visibility.
- Non-streaming agent-runner tool results persist that same full `ui` payload
  while `Session.get_messages()` strips it from model-bound messages.
- New tools should put durable structure in `metadata`, mark failures with
  `metadata.error` / `metadata.error_type`, and return raw details in
  `ToolResult.output`; the executor derives compact LLM receipts so raw tool
  output does not automatically bloat future model context.
- Auto-save review jobs use enqueue-time snapshots, not live active
  conversations at drain time. Empty/no-value batches still advance
  per-conversation checkpoints after successful review; unresolved tool errors
  block checkpoint advancement unless a later successful `memory_write`
  recovers the chunk.
- `diary_write` stores `session_id`, `conversation_id`, and
  `branch_fingerprint` from tool context in the appended source block and
  returns `metadata.file_changes` for UI restoration. When `entry_key` is
  supplied, it writes a hidden marker and skips later writes with the same key.
- The Obsidian chat footer owns an inline loop-to-diary prompt above the input
  area. Template-present prompts show write/skip only; missing-template prompts
  show settings/close only. Completing an older in-flight diary write must not
  hide a newer prompt.
- `memory_write` stores `session_id`, `conversation_id`, and
  `branch_fingerprint` from tool context into memory frontmatter.
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
