---
name: mempalace-cli
description: >
  This skill should be used when the user wants to operate MemPalace via the command-line
  interface, including installing it, initializing a project palace, mining files or
  conversations, searching memories, checking status, or configuring the MCP server.
  Trigger whenever the user says things like "init my palace", "mine this directory",
  "search my memories", "set up mempalace", "connect mempalace to MCP", or any request
  involving mempalace CLI commands.
---

# MemPalace CLI Skill

MemPalace is a local-first AI memory system. It gives an LLM persistent memory by
mining files and conversations into a searchable vector palace (ChromaDB) plus an
optional SQLite knowledge graph — no cloud, no API key required.

Two main entry points:
- **CLI** (`mempalace <command>`) — human-operated setup, mining, and search
- **MCP server** (`python -m mempalace.mcp_server`) — real-time AI tool access

## Architecture Mental Model

```
Wings (projects / people)
  └── Rooms (topic areas)
        └── Drawers (verbatim text chunks stored in ChromaDB)

Knowledge Graph (SQLite) — structured entity-relationship triples with temporal validity
Palace Graph (derived) — navigation graph built from ChromaDB metadata, enables tunnel queries
```

Storage defaults:
- Palace: `~/.mempalace/palace/`
- Config: `~/.mempalace/config.json`
- Identity: `~/.mempalace/identity.txt`
- Knowledge graph: `~/.mempalace/knowledge_graph.sqlite3`

Override palace path via `--palace <path>` or env var `MEMPALACE_PALACE_PATH`.

---

## Workflow: Complete Setup (init → mine → MCP)

Use this sequence when setting up MemPalace for the first time.

### 1. Install

```bash
pip install mempalace
# Optional extras:
pip install "mempalace[llm]"        # LLM-powered init (needs openai package)
pip install "mempalace[chinese]"    # BGE-M3 / multilingual embeddings
pip install "mempalace[qwen]"       # Qwen3-Embedding-4B (best multilingual)
```

Verify: `python -m mempalace --help`

### 2. Initialize a project

```bash
mempalace init <project-dir>
```

Flags:
- `--llm`   — Force LLM-powered room detection (requires `mempalace[llm]` + configured API key)
- `--local` — Force local folder-structure detection (no LLM)
- `--yes`   — Non-interactive: auto-accept all detected entities

Auto-selects LLM mode when `~/.mempalace/config.json` contains a valid `llm.api_key`.

LLM config example (`~/.mempalace/config.json`):
```json
{
  "llm": {
    "api_key": "sk-xxx",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat"
  }
}
```

Env var overrides (highest priority):
```
MEMPALACE_LLM_API_KEY
MEMPALACE_LLM_BASE_URL
MEMPALACE_LLM_MODEL
```

`init` writes a `mempalace.yaml` routing file to the project directory — this tells the
miner which files go into which room.

### 3. Mine data

#### Mine project files (code, docs, notes)

```bash
mempalace mine <project-dir>
mempalace mine <project-dir> --wing my_project   # explicit wing name
mempalace mine <project-dir> --dry-run           # preview without filing
mempalace mine <project-dir> --no-gitignore      # ignore .gitignore
mempalace mine <project-dir> --include-ignored path1,path2  # force-include paths
mempalace mine <project-dir> --limit 100         # cap at N files
```

#### Mine conversation exports (Claude, ChatGPT, Slack)

```bash
mempalace mine <convo-dir> --mode convos
mempalace mine <convo-dir> --mode convos --extract general   # auto-classify memories
mempalace mine <convo-dir> --mode convos --wing personal
```

Supported conversation formats: Claude.ai JSON, ChatGPT JSON, Claude Code JSONL,
OpenAI Codex JSONL, Slack JSON, plain text with `>` markers.

#### Split mega-files first (if needed)

For large concatenated transcript files containing multiple sessions:
```bash
mempalace split <dir> --dry-run   # preview
mempalace split <dir>             # execute
mempalace split <dir> --output-dir /tmp/split --min-sessions 2
```

### 4. Connect MCP server

```bash
mempalace mcp          # prints the exact registration command
```

For Claude Code:
```bash
claude mcp add mempalace -- python -m mempalace.mcp_server
# With custom palace path:
claude mcp add mempalace -- python -m mempalace.mcp_server --palace /path/to/palace
```

---

## Workflow: Day-to-Day Operations

### Search

```bash
mempalace search "why did we switch to GraphQL"
mempalace search "pricing discussion" --wing my_app --room costs
mempalace search "auth bug" --results 10
```

### Wake-up context (L0 + L1, ~600-900 tokens)

```bash
mempalace wake-up
mempalace wake-up --wing my_app
```

Use this to inject the essential memory summary into the LLM's context at session start.

### Status

```bash
mempalace status
```

Shows total drawers, wing/room breakdown, and palace path.

### Compress (AAAK Dialect, ~30× reduction)

```bash
mempalace compress
mempalace compress --wing my_project
mempalace compress --dry-run
```

Note: AAAK compression is **lossy**. Benchmark scores are from raw (uncompressed) mode.
Only compress when context budget is critical.

### Repair (rebuild vector index)

```bash
mempalace repair
```

Use when ChromaDB segfaults or the palace appears corrupted. Reads drawers from SQLite
and re-files them into a fresh ChromaDB collection.

---

## Workflow: MCP Tool Usage (when MCP is connected)

When the MCP server is running, prefer MCP tools over CLI for real-time AI operations:

| MCP Tool | Purpose |
|---|---|
| `mempalace_status` | Palace stats (drawer count, wings, rooms) |
| `mempalace_list_wings` | List all wings |
| `mempalace_list_rooms(wing)` | Rooms in a wing |
| `mempalace_get_taxonomy` | Full wing→room→count tree |
| `mempalace_search(query, wing, room)` | Semantic search |
| `mempalace_check_duplicate(content)` | Before filing, avoid duplicates |
| `mempalace_add_drawer(wing, room, content)` | File verbatim memory |
| `mempalace_delete_drawer(id)` | Remove a drawer |
| `mempalace_kg_add` | Add knowledge graph triple |
| `mempalace_kg_query(entity)` | Query structured facts about an entity |
| `mempalace_kg_invalidate` | Mark a fact as no longer valid |
| `mempalace_kg_timeline` | View facts over time |
| `mempalace_traverse(room)` | Walk palace navigation graph |
| `mempalace_find_tunnels(wing1, wing2)` | Cross-wing topic bridges |
| `mempalace_diary_write` | Agent private notes |
| `mempalace_diary_read` | Read agent notes |

---

## Workflow: Auto-Save Hooks (Claude Code / Codex)

Hooks trigger automatic memory saves during long sessions.

```bash
# Hook: every 15 messages, block and save
echo '{"session_id":"abc","stop_hook_active":false,"transcript_path":"..."}' \
  | mempalace hook run --hook stop --harness claude-code

# Hook: before context compaction — save everything
echo '{"session_id":"abc","stop_hook_active":false,"transcript_path":"..."}' \
  | mempalace hook run --hook precompact --harness claude-code

# Hook: session start — initialize tracking state
echo '{"session_id":"abc"}' \
  | mempalace hook run --hook session-start --harness claude-code
```

Supported harnesses: `claude-code`, `codex`

Hook state is stored in `~/.mempalace/hook_state/`.

---

## Configuration Reference

See `references/config_reference.md` for the full config schema and all environment
variables.

---

## Common Errors and Fixes

| Symptom | Fix |
|---|---|
| `pip install mempalace` fails (build error) | Install build tools: `apt install build-essential` / `xcode-select --install` / MSVC Build Tools |
| `mempalace init` fails with LLM error | Check `llm.api_key` in config.json or run with `--local` |
| Palace not found on `mine` | Run `mempalace init <dir>` first |
| ChromaDB segfault on Apple Silicon | Set `ORT_DISABLE_COREML=1` (auto-set by mempalace) |
| Telemetry warnings from chromadb | Expected, suppressed by mempalace automatically |
| `mempalace search` returns nothing | Check `mempalace status` — palace may be empty |
| Corrupted palace | Run `mempalace repair` |
