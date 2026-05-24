import type { App, TFile } from "obsidian";

import { sha256 } from "./hash";
import type { SearchSourceRef } from "./searchEngine";

export interface ResolvedChunk {
  ok: boolean;
  verified: boolean;
  stale: boolean;
  text?: string;
  vault_rel_path: string;
  reason?: string;
}

export async function resolveSourceRef(
  app: App,
  ref: SearchSourceRef,
): Promise<ResolvedChunk> {
  const file = app.vault.getAbstractFileByPath(ref.vault_rel_path);
  if (!file || !(isTFile(file))) {
    return {
      ok: false,
      verified: false,
      stale: true,
      vault_rel_path: ref.vault_rel_path,
      reason: "file_not_found",
    };
  }
  let content: string;
  try {
    content = await app.vault.cachedRead(file);
  } catch (error) {
    return {
      ok: false,
      verified: false,
      stale: true,
      vault_rel_path: ref.vault_rel_path,
      reason: `read_failed:${error instanceof Error ? error.message : String(error)}`,
    };
  }
  const currentHash = await sha256(content);
  if (currentHash !== ref.content_sha256) {
    const span = sliceLines(content, ref.start_line, ref.end_line);
    return {
      ok: true,
      verified: false,
      stale: true,
      text: span,
      vault_rel_path: ref.vault_rel_path,
      reason: "content_drift",
    };
  }
  const span = sliceLines(content, ref.start_line, ref.end_line);
  return {
    ok: true,
    verified: true,
    stale: false,
    text: span,
    vault_rel_path: ref.vault_rel_path,
  };
}

function sliceLines(
  content: string,
  start?: number,
  end?: number,
): string {
  const lines = content.split(/\r?\n/);
  const from = Math.max(1, start ?? 1) - 1;
  const to = Math.min(lines.length, end ?? lines.length);
  return lines.slice(from, to).join("\n");
}

function isTFile(file: unknown): file is TFile {
  return (
    !!file &&
    typeof file === "object" &&
    "stat" in (file as Record<string, unknown>) &&
    "extension" in (file as Record<string, unknown>)
  );
}
