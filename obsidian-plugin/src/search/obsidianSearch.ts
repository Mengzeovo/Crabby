import type { App, CachedMetadata, TFile } from "obsidian";

import {
  SearchDocument,
  SearchInput,
  SearchResponse,
  SearchTaskPart,
  SearchTextPart,
  searchDocuments,
} from "./searchEngine";

const BLOCKED_DIRS = new Set([
  ".obsidian",
  ".LifeAssistantAgent",
  ".git",
  "node_modules",
  ".venv",
]);

export async function performObsidianSearch(
  app: App,
  input: SearchInput,
): Promise<SearchResponse> {
  const documents = await buildSearchDocuments(app);
  return searchDocuments(documents, input);
}

export async function buildSearchDocuments(app: App): Promise<SearchDocument[]> {
  const markdownFiles = app.vault.getMarkdownFiles();
  const canvasFiles = app.vault
    .getFiles()
    .filter((file) => getExt(file) === "canvas");
  const files = [...markdownFiles, ...canvasFiles].filter(
    (file) => !isBlockedPath(file.path),
  );

  const documents: SearchDocument[] = [];
  for (const file of files) {
    try {
      const content = await app.vault.cachedRead(file);
      if (getExt(file) === "canvas") {
        documents.push(buildCanvasDocument(file, content));
      } else {
        documents.push(
          buildMarkdownDocument(
            file,
            content,
            app.metadataCache.getFileCache(file),
          ),
        );
      }
    } catch (error) {
      console.warn("[Life Assistant] Failed to read searchable file", file.path, error);
    }
  }

  return documents;
}

function buildMarkdownDocument(
  file: TFile,
  content: string,
  cache: CachedMetadata | null,
): SearchDocument {
  const properties = { ...(cache?.frontmatter ?? {}) };
  const aliases = parseAliases(properties.aliases);
  const tags = collectTags(cache, properties);
  if (aliases.length > 0) {
    properties.aliases = aliases;
  }
  if (tags.length > 0) {
    properties.tags = tags;
  }

  return {
    path: file.path,
    name: file.name,
    ext: getExt(file),
    content,
    mtime: file.stat.mtime,
    ctime: file.stat.ctime,
    tags,
    aliases,
    properties,
    sections: buildSections(content, cache),
    blocks: buildBlocks(content, cache),
    tasks: buildTasks(content, cache),
  };
}

function buildCanvasDocument(file: TFile, content: string): SearchDocument {
  const extracted = extractCanvasText(content);
  return {
    path: file.path,
    name: file.name,
    ext: getExt(file),
    content: extracted.content,
    mtime: file.stat.mtime,
    ctime: file.stat.ctime,
    tags: [],
    aliases: [],
    properties: {
      type: "canvas",
    },
    sections: extracted.blocks,
    blocks: extracted.blocks,
    tasks: [],
  };
}

function extractCanvasText(content: string): {
  content: string;
  blocks: SearchTextPart[];
} {
  try {
    const parsed = JSON.parse(content) as {
      nodes?: Array<Record<string, unknown>>;
    };
    const blocks = (parsed.nodes ?? [])
      .map((node) => {
        const type = String(node.type ?? "");
        if (type === "text") {
          return String(node.text ?? "").trim();
        }
        if (type === "file") {
          return String(node.file ?? "").trim();
        }
        if (type === "link") {
          return String(node.url ?? "").trim();
        }
        if (type === "group") {
          return String(node.label ?? "").trim();
        }
        return "";
      })
      .filter(Boolean)
      .map((text) => ({ text }));
    return {
      content: blocks.map((block) => block.text).join("\n\n"),
      blocks,
    };
  } catch {
    return {
      content,
      blocks: content
        .split(/\n\s*\n/g)
        .map((text) => text.trim())
        .filter(Boolean)
        .map((text) => ({ text })),
    };
  }
}

function buildSections(
  content: string,
  cache: CachedMetadata | null,
): SearchTextPart[] {
  const headings = cache?.headings ?? [];
  if (!headings.length) {
    return [{ text: content, line: 1 }];
  }

  const lines = content.split(/\r?\n/);
  return headings.map((heading, index) => {
    const startLine = heading.position.start.line;
    const next = headings[index + 1];
    const endLine = next ? next.position.start.line : lines.length;
    return {
      text: lines.slice(startLine, endLine).join("\n"),
      line: startLine + 1,
    };
  });
}

function buildBlocks(
  content: string,
  cache: CachedMetadata | null,
): SearchTextPart[] {
  const sections = cache?.sections ?? [];
  const lines = content.split(/\r?\n/);
  if (!sections.length) {
    return content
      .split(/\n\s*\n/g)
      .map((text) => text.trim())
      .filter(Boolean)
      .map((text) => ({ text }));
  }

  return sections
    .filter((section) => section.type !== "yaml")
    .map((section) => {
      const startLine = section.position.start.line;
      const endLine = section.position.end.line + 1;
      return {
        text: lines.slice(startLine, endLine).join("\n"),
        line: startLine + 1,
      };
    })
    .filter((part) => part.text.trim().length > 0);
}

function buildTasks(
  content: string,
  cache: CachedMetadata | null,
): SearchTaskPart[] {
  const listItems = cache?.listItems ?? [];
  const lines = content.split(/\r?\n/);
  return listItems
    .filter((item) => item.task !== undefined)
    .map((item) => {
      const line = item.position.start.line;
      return {
        text: lines[line] ?? "",
        line: line + 1,
        status: item.task === " " ? "todo" : "done",
      };
    });
}

function collectTags(
  cache: CachedMetadata | null,
  properties: Record<string, unknown>,
): string[] {
  const tags = new Set<string>();
  for (const tag of cache?.tags ?? []) {
    if (tag.tag) {
      tags.add(tag.tag);
    }
  }
  for (const tag of parseTags(properties.tags)) {
    tags.add(tag.startsWith("#") ? tag : `#${tag}`);
  }
  return Array.from(tags).sort();
}

function parseAliases(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return [];
}

function parseTags(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return value
      .split(/[,\s]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function getExt(file: TFile): string {
  return file.extension || file.path.split(".").pop()?.toLowerCase() || "";
}

function isBlockedPath(path: string): boolean {
  return path
    .split("/")
    .some((part) => BLOCKED_DIRS.has(part));
}
