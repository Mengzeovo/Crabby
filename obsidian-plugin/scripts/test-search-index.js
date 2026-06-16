const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const esbuild = require("esbuild");

async function loadModule(relativePath, outputName) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "laa-search-index-"));
  const outfile = path.join(tempDir, outputName);
  await esbuild.build({
    entryPoints: [path.join(__dirname, "..", "src", ...relativePath.split("/"))],
    outfile,
    bundle: true,
    platform: "node",
    format: "cjs",
    logLevel: "silent",
    external: ["obsidian"],
  });
  return require(outfile);
}

function makeFakeApp(initial) {
  const files = new Map();
  const adapterFiles = new Map();
  const listeners = { create: [], modify: [], delete: [], rename: [] };

  function setFile(file) {
    files.set(file.path, file);
  }
  for (const f of initial) setFile(f);

  const adapter = {
    async exists(p) {
      return adapterFiles.has(p);
    },
    async read(p) {
      if (!adapterFiles.has(p)) throw new Error("ENOENT " + p);
      return adapterFiles.get(p);
    },
    async write(p, data) {
      adapterFiles.set(p, data);
    },
    async remove(p) {
      adapterFiles.delete(p);
    },
    async rename(from, to) {
      if (!adapterFiles.has(from)) throw new Error("ENOENT " + from);
      adapterFiles.set(to, adapterFiles.get(from));
      adapterFiles.delete(from);
    },
    async mkdir() {},
    _files: adapterFiles,
  };

  const vault = {
    adapter,
    getMarkdownFiles: () =>
      Array.from(files.values()).filter((f) => f.extension === "md"),
    getFiles: () => Array.from(files.values()),
    cachedRead: async (file) => file._content,
    on(event, fn) {
      const ref = { event, fn };
      listeners[event].push(ref);
      return ref;
    },
    off(event, fn) {
      listeners[event] = listeners[event].filter((ref) => ref.fn !== fn);
    },
    offref(ref) {
      const arr = listeners[ref.event];
      if (!arr) return;
      listeners[ref.event] = arr.filter((r) => r !== ref);
    },
    _emit(event, ...args) {
      for (const ref of listeners[event]) ref.fn(...args);
    },
    _setFile: setFile,
    _deleteFile: (p) => files.delete(p),
    _files: files,
  };

  const metadataCache = {
    getFileCache: () => null,
  };

  const workspace = {
    onLayoutReady: (fn) => fn(),
  };

  const app = { vault, metadataCache, workspace };
  return { app, vault, adapter };
}

function makeFile(p, content, mtime = 1000) {
  return {
    path: p,
    name: p.split("/").pop(),
    extension: p.endsWith(".canvas") ? "canvas" : "md",
    stat: { mtime, ctime: mtime, size: content.length },
    _content: content,
  };
}

// Make TFile instanceof check pass for our fake files. The bundled module
// imports TFile from obsidian; since we externalize obsidian, esbuild will
// require("obsidian"). We provide a stub via Module._cache.
function installObsidianStub() {
  const Module = require("module");
  const stub = {
    TFile: class TFile {
      constructor(props) {
        Object.assign(this, props);
      }
    },
    normalizePath: (p) => p.replace(/\\+/g, "/"),
  };
  const fakePath = require.resolve.paths("obsidian")?.[0] || process.cwd();
  Module._cache[path.join(fakePath, "obsidian")] = {
    id: "obsidian",
    filename: "obsidian",
    loaded: true,
    exports: stub,
  };
  // Also register under the bare name resolution
  const orig = Module._resolveFilename;
  Module._resolveFilename = function (request, ...rest) {
    if (request === "obsidian") return "obsidian";
    return orig.call(this, request, ...rest);
  };
  Module._cache.obsidian = {
    id: "obsidian",
    filename: "obsidian",
    loaded: true,
    exports: stub,
  };
  return stub;
}

async function main() {
  installObsidianStub();
  // Polyfills for SearchIndex's browser-style globals
  global.window = {
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
  };

  const obsidianStub = require("obsidian");
  const { SearchIndex } = await loadModule("search/searchIndex.ts", "searchIndex.cjs.js");
  const { searchDocuments } = await loadModule(
    "search/searchEngine.ts",
    "searchEngine.cjs.js",
  );

  // Re-bind file class so instanceof checks succeed: rebuild the module's
  // TFile reference via direct construction. Since searchIndex bundle pulled
  // its own TFile from the stub registered above, we use the same class.
  const TFile = obsidianStub.TFile;

  function tfile(p, content, mtime = 1000) {
    return new TFile({
      path: p,
      name: p.split("/").pop(),
      extension: p.endsWith(".canvas") ? "canvas" : "md",
      stat: { mtime, ctime: mtime, size: content.length },
      _content: content,
    });
  }

  // Test 1: cold start full rebuild + persistence
  {
    const fileA = tfile("Notes/a.md", "alpha bravo charlie", 1000);
    const fileB = tfile("Notes/b.md", "delta echo foxtrot", 2000);
    const { app, adapter } = makeFakeApp([fileA, fileB]);
    const index = new SearchIndex(app, { pluginVersion: "test-1" });
    await index.initialize();
    assert.equal(index.isReady(), true, "index should be ready after cold start");
    const docs = index.getDocuments();
    assert.equal(docs.length, 2, "two docs indexed");
    assert.ok(adapter._files.has(".crabby/data/search-index/manifest.json"));
    assert.ok(adapter._files.has(".crabby/data/search-index/documents.jsonl"));
    const manifest = JSON.parse(
      adapter._files.get(".crabby/data/search-index/manifest.json"),
    );
    assert.equal(manifest.schema_version, 1);
    assert.equal(manifest.document_count, 2);

    // search via engine
    const r = searchDocuments(docs, { query: "bravo" });
    assert.equal(r.results.length, 1);
    assert.equal(r.results[0].path, "Notes/a.md");
    await index.shutdown();
    console.log("ok cold start + full rebuild");
  }

  // Test 2: warm start reuses persisted index
  {
    const fileA = tfile("Notes/a.md", "alpha bravo charlie", 1000);
    const { app, adapter } = makeFakeApp([fileA]);
    const recentRebuildAt = Date.now();
    // Pre-populate manifest + documents.jsonl as if a previous run wrote them.
    adapter._files.set(
      ".crabby/data/search-index/manifest.json",
      JSON.stringify({
        schema_version: 1,
        built_with_plugin_version: "test-2",
        document_count: 1,
        last_full_rebuild_at: recentRebuildAt,
      }),
    );
    adapter._files.set(
      ".crabby/data/search-index/documents.jsonl",
      JSON.stringify({
        path: "Notes/a.md",
        name: "a.md",
        ext: "md",
        title: "a",
        content: "alpha bravo charlie",
        mtime: 1000,
        ctime: 1000,
        tags: [],
        aliases: [],
        properties: {},
        headings: [],
        sections: [{ text: "alpha bravo charlie", line: 1 }],
        blocks: [{ text: "alpha bravo charlie" }],
        tasks: [],
        contentSha256: "stub",
        indexedAt: 1,
        size: fileA.stat.size,
      }),
    );

    const index = new SearchIndex(app, { pluginVersion: "test-2" });
    await index.initialize();
    const docs = index.getDocuments();
    assert.equal(docs.length, 1);
    assert.equal(
      docs[0].content_sha256,
      "stub",
      "recent warm start should reconcile without full rebuild",
    );
    console.log("ok warm start");
    await index.shutdown();
  }

  // Test 2b: stale warm index forces a full rebuild even when mtime/size match
  {
    const fileA = tfile("Notes/a.md", "alpha bravo charlie", 1000);
    const { app, adapter } = makeFakeApp([fileA]);
    const staleRebuildAt = Date.now() - 31 * 24 * 60 * 60 * 1000;
    adapter._files.set(
      ".crabby/data/search-index/manifest.json",
      JSON.stringify({
        schema_version: 1,
        built_with_plugin_version: "test-2b",
        document_count: 1,
        last_full_rebuild_at: staleRebuildAt,
      }),
    );
    adapter._files.set(
      ".crabby/data/search-index/documents.jsonl",
      JSON.stringify({
        path: "Notes/a.md",
        name: "a.md",
        ext: "md",
        title: "a",
        content: "alpha bravo charlie",
        mtime: 1000,
        ctime: 1000,
        tags: [],
        aliases: [],
        properties: {},
        headings: [],
        sections: [{ text: "alpha bravo charlie", line: 1 }],
        blocks: [{ text: "alpha bravo charlie" }],
        tasks: [],
        contentSha256: "stub",
        indexedAt: 1,
        size: fileA.stat.size,
      }),
    );

    const index = new SearchIndex(app, { pluginVersion: "test-2b" });
    await index.initialize();
    const docs = index.getDocuments();
    assert.equal(docs.length, 1);
    assert.notEqual(
      docs[0].content_sha256,
      "stub",
      "stale warm start must force a content-hash refresh",
    );
    const manifest = JSON.parse(
      adapter._files.get(".crabby/data/search-index/manifest.json"),
    );
    assert.ok(
      manifest.last_full_rebuild_at > staleRebuildAt,
      "stale warm start must write a new full rebuild timestamp",
    );
    console.log("ok stale warm start triggers full rebuild");
    await index.shutdown();
  }

  // Test 3: schema mismatch triggers full rebuild
  {
    const fileA = tfile("Notes/a.md", "alpha", 1000);
    const { app, adapter } = makeFakeApp([fileA]);
    adapter._files.set(
      ".crabby/data/search-index/manifest.json",
      JSON.stringify({
        schema_version: 999,
        built_with_plugin_version: "old",
        document_count: 0,
        last_full_rebuild_at: 0,
      }),
    );
    adapter._files.set(".crabby/data/search-index/documents.jsonl", "");
    const index = new SearchIndex(app, { pluginVersion: "test-3" });
    await index.initialize();
    assert.equal(index.getDocuments().length, 1);
    const m = JSON.parse(
      adapter._files.get(".crabby/data/search-index/manifest.json"),
    );
    assert.equal(m.schema_version, 1);
    assert.equal(m.built_with_plugin_version, "test-3");
    console.log("ok schema mismatch triggers rebuild");
    await index.shutdown();
  }

  // Test 4: missing index files auto rebuild (acceptance: delete dir → rebuilds)
  {
    const fileA = tfile("Notes/a.md", "alpha", 1000);
    const { app, adapter } = makeFakeApp([fileA]);
    const index = new SearchIndex(app, { pluginVersion: "test-4" });
    await index.initialize();
    assert.equal(index.getDocuments().length, 1);
    // simulate user deleting the data dir
    adapter._files.clear();
    const index2 = new SearchIndex(app, { pluginVersion: "test-4" });
    await index2.initialize();
    assert.equal(index2.getDocuments().length, 1, "rebuilt after dir deletion");
    console.log("ok auto-rebuild after dir deletion");
    await index2.shutdown();
  }

  // Test 5: incremental modify/delete/rename
  {
    const fileA = tfile("Notes/a.md", "alpha original", 1000);
    const fileB = tfile("Notes/b.md", "bravo gamma", 1000);
    const { app, vault } = makeFakeApp([fileA, fileB]);
    const index = new SearchIndex(app, { pluginVersion: "test-5" });
    await index.initialize();
    index.attachVaultEvents();

    // modify
    const fileAMod = tfile("Notes/a.md", "alpha rewritten", 2000);
    vault._setFile(fileAMod);
    vault._emit("modify", fileAMod);
    await new Promise((resolve) => setTimeout(resolve, 0));
    let docs = index.getDocuments();
    const a = docs.find((d) => d.path === "Notes/a.md");
    assert.ok(a.content.includes("rewritten"), "content updated after modify");

    // delete
    vault._deleteFile("Notes/b.md");
    vault._emit("delete", fileB);
    await new Promise((resolve) => setTimeout(resolve, 0));
    docs = index.getDocuments();
    assert.equal(docs.length, 1, "doc removed after delete");

    // rename (content unchanged)
    const fileARenamed = tfile("Notes/a-new.md", "alpha rewritten", 2000);
    vault._deleteFile("Notes/a.md");
    vault._setFile(fileARenamed);
    vault._emit("rename", fileARenamed, "Notes/a.md");
    await new Promise((resolve) => setTimeout(resolve, 0));
    docs = index.getDocuments();
    assert.equal(docs.length, 1);
    assert.equal(docs[0].path, "Notes/a-new.md", "rename updates path");

    console.log("ok incremental create/modify/delete/rename");
    await index.shutdown();
  }

  // Test 6: blocked dirs are skipped
  {
    const fileA = tfile("Notes/a.md", "alpha", 1000);
    const fileBlocked = tfile(".crabby/memory/x.md", "should not index", 1000);
    const { app } = makeFakeApp([fileA, fileBlocked]);
    const index = new SearchIndex(app, { pluginVersion: "test-6" });
    await index.initialize();
    const docs = index.getDocuments();
    assert.equal(docs.length, 1);
    assert.equal(docs[0].path, "Notes/a.md");
    console.log("ok blocked dirs skipped");
    await index.shutdown();
  }

  // Test 7: events fired during initialize() are queued and applied
  {
    const fileA = tfile("Notes/a.md", "alpha original", 1000);
    const { app, vault } = makeFakeApp([fileA]);
    const index = new SearchIndex(app, { pluginVersion: "test-7" });
    index.attachVaultEvents();
    // Fire a modify during initialize() — before rebuild has finished walking
    // the file list. We schedule the emit on the microtask queue so it
    // interleaves with the awaits inside initialize().
    const fileAMod = tfile("Notes/a.md", "alpha hot-edit", 2000);
    Promise.resolve().then(() => {
      vault._setFile(fileAMod);
      vault._emit("modify", fileAMod);
    });
    await index.initialize();
    const docs = index.getDocuments();
    const a = docs.find((d) => d.path === "Notes/a.md");
    assert.ok(a, "doc present");
    assert.ok(
      a.content.includes("hot-edit"),
      "modify during initialize should be replayed",
    );
    console.log("ok events queued during initialize");
    await index.shutdown();
  }

  // Test 8: last_full_rebuild_at survives incremental flushes
  {
    const fileA = tfile("Notes/a.md", "alpha", 1000);
    const { app, vault, adapter } = makeFakeApp([fileA]);
    const index = new SearchIndex(app, { pluginVersion: "test-8" });
    index.attachVaultEvents();
    await index.initialize();
    const m1 = JSON.parse(
      adapter._files.get(".crabby/data/search-index/manifest.json"),
    );
    const rebuiltAt = m1.last_full_rebuild_at;
    assert.ok(rebuiltAt > 0);
    // Wait so Date.now() advances, then trigger an incremental flush via modify.
    await new Promise((resolve) => setTimeout(resolve, 5));
    const fileAMod = tfile("Notes/a.md", "alpha v2", 2000);
    vault._setFile(fileAMod);
    vault._emit("modify", fileAMod);
    // Force flush
    await index.shutdown();
    const m2 = JSON.parse(
      adapter._files.get(".crabby/data/search-index/manifest.json"),
    );
    assert.equal(
      m2.last_full_rebuild_at,
      rebuiltAt,
      "incremental flush must not overwrite last_full_rebuild_at",
    );
    console.log("ok last_full_rebuild_at preserved across incremental flush");
  }

  // Test 9: failed flush re-queues dirty paths
  {
    const fileA = tfile("Notes/a.md", "alpha", 1000);
    const { app, adapter } = makeFakeApp([fileA]);
    const index = new SearchIndex(app, { pluginVersion: "test-9" });
    await index.initialize();
    // Make next write fail once
    let failures = 1;
    const origWrite = adapter.write.bind(adapter);
    adapter.write = async (p, data) => {
      if (failures > 0 && p.endsWith("documents.jsonl.tmp")) {
        failures--;
        throw new Error("disk full");
      }
      return origWrite(p, data);
    };
    // Trigger dirty + flush
    const fileB = tfile("Notes/b.md", "bravo", 1500);
    app.vault._setFile(fileB);
    // Use create handler directly via the public path: attach events now.
    index.attachVaultEvents();
    app.vault._emit("create", fileB);
    // Drain debounce + retry
    await new Promise((resolve) => setTimeout(resolve, 50));
    await index.shutdown();
    const docsRaw = adapter._files.get(
      ".crabby/data/search-index/documents.jsonl",
    );
    assert.ok(docsRaw && docsRaw.includes("Notes/b.md"), "b.md eventually flushed after failure");
    console.log("ok dirty re-queued on flush failure");
  }

  // Test 10: full rebuild flushes documents.jsonl only once for >50 files
  {
    const files = [];
    for (let i = 0; i < 75; i++) {
      files.push(tfile(`Notes/file-${i}.md`, `content ${i}`, 1000 + i));
    }
    const { app, adapter } = makeFakeApp(files);
    let docsWrites = 0;
    const origWrite = adapter.write.bind(adapter);
    adapter.write = async (p, data) => {
      if (p.endsWith("documents.jsonl.tmp")) docsWrites++;
      return origWrite(p, data);
    };
    const index = new SearchIndex(app, { pluginVersion: "test-10" });
    await index.initialize();
    assert.equal(
      docsWrites,
      1,
      `documents.jsonl.tmp written ${docsWrites} times during cold rebuild; expected 1`,
    );
    console.log("ok full rebuild flushes documents.jsonl exactly once");
    await index.shutdown();
  }

  // Test 11: rename into blocked dir removes from index
  {
    const fileA = tfile("Notes/a.md", "alpha", 1000);
    const { app, vault } = makeFakeApp([fileA]);
    const index = new SearchIndex(app, { pluginVersion: "test-11" });
    index.attachVaultEvents();
    await index.initialize();
    const moved = tfile(".crabby/memory/a.md", "alpha", 1000);
    vault._deleteFile("Notes/a.md");
    vault._setFile(moved);
    vault._emit("rename", moved, "Notes/a.md");
    await new Promise((resolve) => setTimeout(resolve, 5));
    const docs = index.getDocuments();
    assert.equal(docs.length, 0, "file moved into blocked dir must leave index");
    console.log("ok rename into blocked dir purges entry");
    await index.shutdown();
  }

  const { performObsidianSearch } = await loadModule(
    "search/obsidianSearch.ts",
    "obsidianSearch.cjs.js",
  );

  // Test T-A (Finding #1): live-scan fallback (no index) must still emit
  // source_ref with non-empty content_sha256.
  {
    const fileA = tfile("Notes/a.md", "alpha bravo", 1000);
    const { app } = makeFakeApp([fileA]);
    const response = await performObsidianSearch(
      app,
      { query: "alpha" },
      null, // explicit "index not ready"
    );
    assert.equal(response.results.length, 1, "live-scan still returns hits");
    const ref = response.results[0].source_ref;
    assert.ok(ref, "live-scan result must carry source_ref");
    assert.ok(
      typeof ref.content_sha256 === "string" && ref.content_sha256.length > 0,
      "content_sha256 must be populated on live-scan fallback",
    );
    assert.equal(ref.vault_rel_path, "Notes/a.md");
    console.log("ok live-scan fallback emits source_ref with content_sha256");
  }

  // Test T-B (Finding #2): events emitted during the final drain window of
  // initialize() (after drainPendingEvents returns but before ready flips)
  // must still be applied, not orphaned.
  {
    const fileA = tfile("Notes/a.md", "alpha v0", 1000);
    const { app, vault } = makeFakeApp([fileA]);
    const index = new SearchIndex(app, { pluginVersion: "test-T-B" });
    index.attachVaultEvents();

    // Stash original cachedRead. We'll intercept the FIRST read after
    // initialize starts and use that yield-point to emit a modify so it lands
    // between the drain and ready=true.
    const origCachedRead = vault.cachedRead;
    let injected = false;
    vault.cachedRead = async (file) => {
      // Yield once so initialize() has a chance to call drainPendingEvents
      // first; then inject a late event.
      const content = await origCachedRead(file);
      if (!injected) {
        injected = true;
        Promise.resolve().then(() => {
          const fileAMod = tfile("Notes/a.md", "alpha v-late", 2000);
          vault._setFile(fileAMod);
          vault._emit("modify", fileAMod);
        });
      }
      return content;
    };

    await index.initialize();
    // Give the late event time to land via dispatch (now ready=true).
    await new Promise((resolve) => setTimeout(resolve, 20));
    const docs = index.getDocuments();
    const a = docs.find((d) => d.path === "Notes/a.md");
    assert.ok(a, "doc must exist");
    assert.ok(
      a.content.includes("v-late"),
      `late event during initialize must be applied; got content=${JSON.stringify(a.content)}`,
    );
    console.log("ok late event during initialize drain is applied");
    await index.shutdown();
  }

  // Test T-C (Finding #3): two rapid modify events on the same path must
  // serialize so the last-emitted content wins, even if the first cachedRead
  // resolves later than the second.
  {
    const fileA = tfile("Notes/a.md", "v0", 1000);
    const { app, vault } = makeFakeApp([fileA]);
    const index = new SearchIndex(app, { pluginVersion: "test-T-C" });
    await index.initialize();
    index.attachVaultEvents();

    // Make cachedRead for the FIRST call to a.md sleep longer than the
    // second, simulating an OS read that races.
    const origCachedRead = vault.cachedRead;
    let firstReadForA = true;
    vault.cachedRead = async (file) => {
      if (file.path === "Notes/a.md" && firstReadForA) {
        firstReadForA = false;
        await new Promise((r) => setTimeout(r, 30));
      }
      return origCachedRead(file);
    };

    const v1 = tfile("Notes/a.md", "v1-old", 2000);
    vault._setFile(v1);
    vault._emit("modify", v1);
    // Second modify lands ~immediately after.
    await new Promise((r) => setTimeout(r, 1));
    const v2 = tfile("Notes/a.md", "v2-new", 3000);
    vault._setFile(v2);
    vault._emit("modify", v2);

    // Wait for both serialized applies to finish.
    await new Promise((r) => setTimeout(r, 80));
    const docs = index.getDocuments();
    const a = docs.find((d) => d.path === "Notes/a.md");
    assert.ok(a, "doc must exist");
    assert.equal(
      a.content,
      "v2-new",
      `last-emitted content must win; got ${JSON.stringify(a.content)}`,
    );
    console.log("ok concurrent modifies on same path serialize correctly");
    await index.shutdown();
  }

  // Test T-D (Finding #4): events in flight at shutdown time must finish
  // landing in the persisted index, and no writes happen after shutdown
  // resolves.
  {
    const fileA = tfile("Notes/a.md", "v0", 1000);
    const { app, vault, adapter } = makeFakeApp([fileA]);
    const index = new SearchIndex(app, { pluginVersion: "test-T-D" });
    await index.initialize();
    index.attachVaultEvents();

    // Make cachedRead async so the modify is still in flight when shutdown
    // is called.
    const origCachedRead = vault.cachedRead;
    vault.cachedRead = async (file) => {
      await new Promise((r) => setTimeout(r, 25));
      return origCachedRead(file);
    };

    const v1 = tfile("Notes/a.md", "v1-shutdown-race", 2000);
    vault._setFile(v1);
    vault._emit("modify", v1);

    // Shutdown immediately — must drain inflight before resolving.
    await index.shutdown();

    // Track post-shutdown writes.
    let postShutdownWrites = 0;
    const origWrite = adapter.write.bind(adapter);
    adapter.write = async (p, data) => {
      postShutdownWrites++;
      return origWrite(p, data);
    };
    // Give the event loop more cycles to surface any leaked writes.
    await new Promise((r) => setTimeout(r, 50));

    const raw = adapter._files.get(".crabby/data/search-index/documents.jsonl");
    assert.ok(raw, "documents.jsonl must exist after shutdown");
    assert.ok(
      raw.includes("v1-shutdown-race"),
      "modify in flight at shutdown must be persisted",
    );
    assert.equal(
      postShutdownWrites,
      0,
      `no writes should happen after shutdown resolved; got ${postShutdownWrites}`,
    );
    console.log("ok shutdown awaits in-flight applies and writes nothing after");
  }

  // Test T-E (Recommended #7): plugin version mismatch triggers full rebuild.
  {
    const fileA = tfile("Notes/a.md", "alpha", 1000);
    const { app, adapter } = makeFakeApp([fileA]);
    adapter._files.set(
      ".crabby/data/search-index/manifest.json",
      JSON.stringify({
        schema_version: 1,
        built_with_plugin_version: "0.2.9",
        document_count: 0,
        last_full_rebuild_at: 1,
      }),
    );
    adapter._files.set(".crabby/data/search-index/documents.jsonl", "");

    const index = new SearchIndex(app, { pluginVersion: "0.4.0" });
    await index.initialize();
    const docs = index.getDocuments();
    assert.equal(docs.length, 1, "version mismatch must trigger full rebuild");
    const m = JSON.parse(
      adapter._files.get(".crabby/data/search-index/manifest.json"),
    );
    assert.equal(
      m.built_with_plugin_version,
      "0.4.0",
      "manifest must record new plugin version after rebuild",
    );
    console.log("ok plugin version mismatch triggers rebuild");
    await index.shutdown();
  }

  console.log("\nAll search-index tests passed.");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
