import type { App, EventRef, TAbstractFile, TFile } from "obsidian";
import { TFile as ObsidianTFile, normalizePath } from "obsidian";

import {
  buildDocumentForFile,
  getSearchableFiles,
  isBlockedPath,
} from "./searchDocumentBuilder";
import { sha256 } from "./hash";
import type { SearchDocument } from "./searchEngine";

export const SEARCH_INDEX_SCHEMA_VERSION = 1;
const INDEX_DIR = ".crabby/data/search-index";
const MANIFEST_FILE = `${INDEX_DIR}/manifest.json`;
const DOCUMENTS_FILE = `${INDEX_DIR}/documents.jsonl`;
const FLUSH_DEBOUNCE_MS = 5000;
const FLUSH_QUEUE_LIMIT = 50;
// Cap drift accumulated by the cheap mtime+size reconcile path: if the last
// full rebuild is older than this, force a full rebuild on startup so any
// content that changed without mtime/size moving still gets re-hashed.
const FULL_REBUILD_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;

interface IndexedDocument extends SearchDocument {
  contentSha256: string;
  indexedAt: number;
  size: number;
}

interface SearchIndexManifest {
  schema_version: number;
  built_with_plugin_version: string;
  document_count: number;
  last_full_rebuild_at: number;
}

export interface SearchIndexOptions {
  pluginVersion: string;
}

type PendingEvent =
  | { kind: "create"; file: TFile }
  | { kind: "modify"; file: TFile }
  | { kind: "delete"; path: string }
  | { kind: "rename"; file: TFile; oldPath: string }
  | { kind: "rename-deleted"; oldPath: string };

export class SearchIndex {
  private readonly documents = new Map<string, IndexedDocument>();
  private dirty = new Set<string>();
  private ready = false;
  private rebuilding = false;
  private flushTimer: number | null = null;
  private vaultEventRefs: EventRef[] = [];
  private pendingFlush: Promise<void> = Promise.resolve();
  private lastFullRebuildAt = 0;
  private readonly pendingEvents: PendingEvent[] = [];
  private readonly inflight = new Map<string, Promise<void>>();

  constructor(
    private readonly app: App,
    private readonly options: SearchIndexOptions,
  ) {}

  isReady(): boolean {
    return this.ready;
  }

  getDocuments(): SearchDocument[] {
    return Array.from(this.documents.values()).map(toSearchDocument);
  }

  async initialize(): Promise<void> {
    try {
      await this.ensureIndexDir();
      const loaded = await this.loadFromDisk();
      if (loaded && !this.isRebuildOverdue()) {
        await this.reconcileWithVault();
      } else {
        await this.fullRebuild();
      }
      // Drain repeatedly: events can arrive between drain and the `ready=true`
      // assignment because awaits inside `applyEvent` yield to the event loop.
      // We loop until the queue is empty AND `ready` is true; any event that
      // sneaks in during the final drain will be observed by the next
      // iteration. Once `ready=true` is set and the queue is empty, subsequent
      // dispatch() calls take the immediate-apply path.
      do {
        await this.drainPendingEvents();
        if (this.pendingEvents.length === 0) {
          this.ready = true;
        }
      } while (this.pendingEvents.length > 0);
    } catch (error) {
      console.warn("[Crabby] SearchIndex initialize failed; will fall back to live scan", error);
      this.ready = false;
    }
  }

  attachVaultEvents(): void {
    if (this.vaultEventRefs.length > 0) {
      return;
    }
    const { vault } = this.app;
    const onCreate = (file: TAbstractFile) => {
      if (file instanceof ObsidianTFile) {
        this.dispatch({ kind: "create", file });
      }
    };
    const onModify = (file: TAbstractFile) => {
      if (file instanceof ObsidianTFile) {
        this.dispatch({ kind: "modify", file });
      }
    };
    const onDelete = (file: TAbstractFile) => {
      this.dispatch({ kind: "delete", path: file.path });
    };
    const onRename = (file: TAbstractFile, oldPath: string) => {
      if (file instanceof ObsidianTFile) {
        this.dispatch({ kind: "rename", file, oldPath });
      } else {
        this.dispatch({ kind: "rename-deleted", oldPath });
      }
    };

    this.vaultEventRefs = [
      vault.on("create", onCreate),
      vault.on("modify", onModify),
      vault.on("delete", onDelete),
      vault.on("rename", onRename),
    ];
  }

  async shutdown(): Promise<void> {
    for (const ref of this.vaultEventRefs) {
      this.app.vault.offref(ref);
    }
    this.vaultEventRefs = [];
    // Stop accepting new immediate-apply work; pending events that were
    // already dispatched still need to finish writing into `documents`/`dirty`
    // before we flush, otherwise their updates get dropped on plugin unload.
    this.ready = false;
    if (this.flushTimer !== null) {
      window.clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    while (this.inflight.size > 0) {
      await Promise.allSettled(Array.from(this.inflight.values()));
    }
    await this.pendingFlush;
    const maxAttempts = 5;
    let attempts = 0;
    let delay = 50;
    while (this.dirty.size > 0 && attempts < maxAttempts) {
      attempts++;
      const before = this.dirty.size;
      try {
        await this.flushNow();
      } catch {
        /* flushNow swallows internally; loop checks dirty.size */
      }
      if (this.dirty.size === 0) {
        break;
      }
      if (attempts >= maxAttempts) {
        console.warn(
          "[Crabby] SearchIndex shutdown could not flush dirty paths after retries",
          { remaining: this.dirty.size, before, attempts },
        );
        break;
      }
      await sleep(delay);
      delay = Math.min(delay * 2, 1000);
    }
  }

  async rebuildAll(): Promise<void> {
    await this.fullRebuild();
  }

  private dispatch(event: PendingEvent): void {
    if (!this.ready || this.rebuilding) {
      this.pendingEvents.push(event);
      return;
    }
    void this.applyEventSerialized(event);
  }

  /**
   * Chain applyEvent calls for the same path so that two rapid events on the
   * same file cannot race their cachedRead/document.set sequence (older event
   * landing after newer event). Different paths still run concurrently.
   */
  private applyEventSerialized(event: PendingEvent): Promise<void> {
    const key = eventKey(event);
    const previous = this.inflight.get(key) ?? Promise.resolve();
    const next = previous
      .catch(() => {
        /* swallow prior failure so this event still runs */
      })
      .then(() => this.applyEvent(event));
    const tracked = next.finally(() => {
      // Only clear the slot if it still points at this promise; another newer
      // event for the same key may have replaced it.
      if (this.inflight.get(key) === tracked) {
        this.inflight.delete(key);
      }
    });
    this.inflight.set(key, tracked);
    return tracked;
  }

  private async applyEvent(event: PendingEvent): Promise<void> {
    switch (event.kind) {
      case "create":
        await this.handleCreate(event.file);
        return;
      case "modify":
        await this.handleModify(event.file);
        return;
      case "delete":
        await this.handleDelete(event.path);
        return;
      case "rename":
        await this.handleRename(event.file, event.oldPath);
        return;
      case "rename-deleted":
        await this.handleDelete(event.oldPath);
        return;
    }
  }

  private async drainPendingEvents(): Promise<void> {
    while (this.pendingEvents.length > 0) {
      const event = this.pendingEvents.shift()!;
      await this.applyEventSerialized(event);
    }
  }

  private async loadFromDisk(): Promise<boolean> {
    const adapter = this.app.vault.adapter;
    const manifestPath = normalizePath(MANIFEST_FILE);
    const docsPath = normalizePath(DOCUMENTS_FILE);
    if (!(await adapter.exists(manifestPath)) || !(await adapter.exists(docsPath))) {
      return false;
    }
    let manifest: SearchIndexManifest;
    try {
      manifest = JSON.parse(await adapter.read(manifestPath)) as SearchIndexManifest;
    } catch (error) {
      console.warn("[Crabby] SearchIndex manifest unreadable; rebuilding", error);
      return false;
    }
    if (
      manifest.schema_version !== SEARCH_INDEX_SCHEMA_VERSION ||
      manifest.built_with_plugin_version !== this.options.pluginVersion
    ) {
      return false;
    }
    this.lastFullRebuildAt = manifest.last_full_rebuild_at;
    try {
      const raw = await adapter.read(docsPath);
      this.documents.clear();
      for (const line of raw.split(/\r?\n/)) {
        if (!line.trim()) continue;
        const doc = JSON.parse(line) as IndexedDocument;
        this.documents.set(doc.path, doc);
      }
      return true;
    } catch (error) {
      console.warn("[Crabby] SearchIndex documents unreadable; rebuilding", error);
      this.documents.clear();
      return false;
    }
  }

  private isRebuildOverdue(): boolean {
    if (!this.lastFullRebuildAt) return true;
    return Date.now() - this.lastFullRebuildAt > FULL_REBUILD_MAX_AGE_MS;
  }

  private async reconcileWithVault(): Promise<void> {
    const files = getSearchableFiles(this.app);
    const seen = new Set<string>();
    let changed = false;
    for (const file of files) {
      seen.add(file.path);
      const existing = this.documents.get(file.path);
      if (
        !existing ||
        existing.mtime !== file.stat.mtime ||
        existing.size !== file.stat.size
      ) {
        const updated = await this.rebuildFile(file);
        if (updated) {
          changed = true;
        }
      }
    }
    for (const path of Array.from(this.documents.keys())) {
      if (!seen.has(path)) {
        this.documents.delete(path);
        this.dirty.add(path);
        changed = true;
      }
    }
    if (changed) {
      await this.flushNow();
    }
  }

  private async fullRebuild(): Promise<void> {
    this.rebuilding = true;
    try {
      this.documents.clear();
      this.dirty.clear();
      for (const file of getSearchableFiles(this.app)) {
        await this.rebuildFile(file);
      }
      this.lastFullRebuildAt = Date.now();
    } finally {
      this.rebuilding = false;
    }
    await this.flushNow();
  }

  private async rebuildFile(file: TFile): Promise<boolean> {
    const document = await buildDocumentForFile(this.app, file);
    if (!document) {
      return false;
    }
    const contentSha256 =
      document.content_sha256 ?? (await sha256(document.content));
    const indexed: IndexedDocument = {
      ...document,
      contentSha256,
      indexedAt: Date.now(),
      size: file.stat.size,
    };
    this.documents.set(file.path, indexed);
    this.dirty.add(file.path);
    this.scheduleFlush();
    return true;
  }

  private async handleCreate(file: TFile): Promise<void> {
    if (isBlockedPath(file.path) || !isSearchable(file)) return;
    await this.rebuildFile(file);
  }

  private async handleModify(file: TFile): Promise<void> {
    if (isBlockedPath(file.path) || !isSearchable(file)) return;
    await this.rebuildFile(file);
  }

  private async handleDelete(path: string): Promise<void> {
    if (!this.documents.has(path)) return;
    this.documents.delete(path);
    this.dirty.add(path);
    this.scheduleFlush();
  }

  private async handleRename(file: TFile, oldPath: string): Promise<void> {
    const previous = this.documents.get(oldPath);
    if (previous) {
      this.documents.delete(oldPath);
      this.dirty.add(oldPath);
    }
    if (isBlockedPath(file.path) || !isSearchable(file)) {
      this.scheduleFlush();
      return;
    }
    if (
      previous &&
      previous.mtime === file.stat.mtime &&
      previous.size === file.stat.size
    ) {
      const renamed: IndexedDocument = {
        ...previous,
        path: file.path,
        name: file.name,
        indexedAt: Date.now(),
      };
      this.documents.set(file.path, renamed);
      this.dirty.add(file.path);
      this.scheduleFlush();
      return;
    }
    await this.rebuildFile(file);
  }

  private scheduleFlush(): void {
    if (this.rebuilding) {
      return;
    }
    if (this.dirty.size >= FLUSH_QUEUE_LIMIT) {
      void this.flushNow();
      return;
    }
    if (this.flushTimer !== null) {
      return;
    }
    this.flushTimer = window.setTimeout(() => {
      this.flushTimer = null;
      void this.flushNow();
    }, FLUSH_DEBOUNCE_MS);
  }

  private async flushNow(): Promise<void> {
    if (this.flushTimer !== null) {
      window.clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    const previous = this.pendingFlush;
    const next = previous.then(() => this.doFlush()).catch((error) => {
      console.warn("[Crabby] SearchIndex flush failed", error);
    });
    this.pendingFlush = next;
    await next;
  }

  private async doFlush(): Promise<void> {
    if (this.dirty.size === 0) {
      return;
    }
    const flushing = this.dirty;
    this.dirty = new Set<string>();
    try {
      await this.ensureIndexDir();
      const adapter = this.app.vault.adapter;
      const docsPath = normalizePath(DOCUMENTS_FILE);
      const tempPath = normalizePath(`${DOCUMENTS_FILE}.tmp`);
      const lines: string[] = [];
      for (const doc of this.documents.values()) {
        lines.push(JSON.stringify(doc));
      }
      await adapter.write(tempPath, lines.join("\n"));
      if (await adapter.exists(docsPath)) {
        await adapter.remove(docsPath);
      }
      await adapter.rename(tempPath, docsPath);
      await this.writeManifest();
    } catch (error) {
      for (const path of flushing) {
        this.dirty.add(path);
      }
      this.scheduleFlush();
      throw error;
    }
  }

  private async writeManifest(): Promise<void> {
    const adapter = this.app.vault.adapter;
    const manifest: SearchIndexManifest = {
      schema_version: SEARCH_INDEX_SCHEMA_VERSION,
      built_with_plugin_version: this.options.pluginVersion,
      document_count: this.documents.size,
      last_full_rebuild_at: this.lastFullRebuildAt || Date.now(),
    };
    await adapter.write(
      normalizePath(MANIFEST_FILE),
      JSON.stringify(manifest, null, 2),
    );
  }

  private async ensureIndexDir(): Promise<void> {
    const adapter = this.app.vault.adapter;
    const dir = normalizePath(INDEX_DIR);
    if (!(await adapter.exists(dir))) {
      await adapter.mkdir(dir);
    }
  }
}

function toSearchDocument(doc: IndexedDocument): SearchDocument {
  const {
    indexedAt: _at,
    size: _size,
    contentSha256,
    ...rest
  } = doc;
  return { ...rest, content_sha256: contentSha256 };
}

function isSearchable(file: TFile): boolean {
  const ext = (file.extension || "").toLowerCase();
  return ext === "md" || ext === "canvas";
}

function eventKey(event: PendingEvent): string {
  switch (event.kind) {
    case "create":
    case "modify":
      return event.file.path;
    case "delete":
      return event.path;
    case "rename":
      // Serialize against both old and new path so a rename can't race a
      // create/modify on either side.
      return `${event.oldPath} ${event.file.path}`;
    case "rename-deleted":
      return event.oldPath;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
