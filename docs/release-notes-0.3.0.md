# Release 0.3.0 - Memory Foundation

Release 0.3.0 is the memory-focused release. It turns Crabby's long-term
memory from a mostly planned subsystem into a local-first, Vault-backed runtime
capability with recall, write, review, and maintenance paths.

## Highlights

- Vault Markdown under `<vault>/.crabby/memory/` is the canonical long-term
  memory store. MemPalace remains an optional downstream semantic index, not the
  source of truth.
- Memory documents use a stable facet model: `type`, `topic`, `domain`, `kind`,
  `state`, `valid_from`, and `valid_to`, with provenance fields for
  `session_id`, `conversation_id`, and `branch_fingerprint`.
- `memory_write` creates and updates memory files, maintains `REGISTRY.md` and
  `NAME_INDEX.md`, records provenance, detects same type/topic conflicts, and
  can invalidate superseded memories.
- `memory_search` supports registry inspection, structured facet search,
  local full-text fallback, active-state defaults, and created/updated time
  filters.
- `memory_inventory` and `memory_read` provide maintenance-only inspection
  over active, archived, and invalidated memories without exposing those states
  to ordinary chat recall.
- Auto-save now reviews frozen conversation windows by checkpoint, uses only
  `memory_search` and `memory_write`, and advances checkpoints only after a
  successful review.
- Dream maintenance runs as a low-frequency daemon that waits for real-user
  idle time, plans with maintenance read tools, writes conservative summary
  memories, archives merged sources, and interrupts when the user starts
  chatting.
- Diary V1 is kept separate from memory: diary entries are user-facing Vault
  notes, written only through diary-specific paths and explicit user intent.

## Operational Notes

- Dream maintenance is enabled by default and persists state at
  `<vault>/.crabby/data/dream_state.json`.
- The first dream run is scheduled 7-14 days after startup; subsequent runs use
  the same random window and require at least 30 minutes of real-user idle time.
- Ordinary chat sees only the normal memory recall surface. Archived and
  invalidated memory bodies remain available to maintenance flows, not default
  recall.
- Release packaging now uses version `0.3.0` for backend runtime folders,
  Obsidian plugin metadata, and Desktop Pet metadata.

## Still Pending

- MemPalace double-write and rebuild-from-Vault tooling.
- User-facing memory management UI.
- Cross-device synchronization guidance for MemPalace-derived indexes.
- Higher-level learning workflows such as `/learn`, learning profiles, and
  mistake-log aggregation.
