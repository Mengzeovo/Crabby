import type { SearchInput } from "../search/searchEngine";

export function normalizeSearchInput(input: unknown): SearchInput {
  if (!input || typeof input !== "object") {
    return { query: "" };
  }
  const record = input as Record<string, unknown>;
  return {
    query: String(record.query ?? ""),
    max_results:
      typeof record.max_results === "number" ? record.max_results : undefined,
    context_chars:
      typeof record.context_chars === "number" ? record.context_chars : undefined,
    sort:
      record.sort === "mtime_desc" ||
      record.sort === "mtime_asc" ||
      record.sort === "path"
        ? record.sort
        : "score",
  };
}
