const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const esbuild = require("esbuild");

async function loadModule(relativePath, outputName) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "laa-source-resolver-"));
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

function installObsidianStub() {
  const Module = require("module");
  class TFileStub {
    constructor(props) {
      Object.assign(this, props);
    }
  }
  const stub = {
    TFile: TFileStub,
    normalizePath: (p) => p.replace(/\\+/g, "/"),
  };
  Module._cache.obsidian = {
    id: "obsidian",
    filename: "obsidian",
    loaded: true,
    exports: stub,
  };
  const orig = Module._resolveFilename;
  Module._resolveFilename = function (request, ...rest) {
    if (request === "obsidian") return "obsidian";
    return orig.call(this, request, ...rest);
  };
  return stub;
}

async function sha256Web(text) {
  const data = new TextEncoder().encode(text);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function makeApp(files) {
  return {
    vault: {
      getAbstractFileByPath: (p) => files.get(p) ?? null,
      cachedRead: async (file) => {
        if (file._throw) throw new Error(file._throw);
        return file._content;
      },
    },
  };
}

function fakeTFile(p, content) {
  return {
    path: p,
    name: p.split("/").pop(),
    extension: p.split(".").pop(),
    stat: { mtime: 1, ctime: 1, size: content.length },
    _content: content,
  };
}

async function main() {
  installObsidianStub();
  const { resolveSourceRef } = await loadModule(
    "search/sourceResolver.ts",
    "sourceResolver.cjs.js",
  );

  // T-F-1: happy path — content matches stored hash → verified, not stale.
  {
    const content = "line one\nline two\nline three";
    const hash = await sha256Web(content);
    const file = fakeTFile("Notes/a.md", content);
    const files = new Map([[file.path, file]]);
    const app = makeApp(files);
    const result = await resolveSourceRef(app, {
      vault_rel_path: "Notes/a.md",
      chunk_id: "vault:" + hash + ":file:1",
      chunk_kind: "file",
      start_line: 1,
      end_line: 3,
      content_sha256: hash,
    });
    assert.equal(result.ok, true);
    assert.equal(result.verified, true);
    assert.equal(result.stale, false);
    assert.equal(result.text, content);
    console.log("ok resolveSourceRef happy path");
  }

  // T-F-2: content drift — file exists but hash differs → ok but unverified
  // and stale; still returns current span text for display.
  {
    const content = "rewritten one\nrewritten two";
    const file = fakeTFile("Notes/a.md", content);
    const files = new Map([[file.path, file]]);
    const app = makeApp(files);
    const result = await resolveSourceRef(app, {
      vault_rel_path: "Notes/a.md",
      chunk_id: "vault:stale-hash:file:1",
      chunk_kind: "file",
      start_line: 1,
      end_line: 2,
      content_sha256: "stale-hash",
    });
    assert.equal(result.ok, true);
    assert.equal(result.verified, false);
    assert.equal(result.stale, true);
    assert.equal(result.reason, "content_drift");
    assert.ok(result.text && result.text.length > 0, "drifted resolve returns current text");
    console.log("ok resolveSourceRef drift path");
  }

  // T-F-3: file not found → stale, not ok.
  {
    const files = new Map();
    const app = makeApp(files);
    const result = await resolveSourceRef(app, {
      vault_rel_path: "Notes/missing.md",
      chunk_id: "vault:x:file:1",
      chunk_kind: "file",
      content_sha256: "x",
    });
    assert.equal(result.ok, false);
    assert.equal(result.verified, false);
    assert.equal(result.stale, true);
    assert.equal(result.reason, "file_not_found");
    console.log("ok resolveSourceRef missing file");
  }

  console.log("\nAll source-resolver tests passed.");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
