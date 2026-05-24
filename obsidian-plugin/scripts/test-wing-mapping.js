const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const esbuild = require("esbuild");

async function loadModule(relativePath, outputName) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "laa-wing-"));
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
  const stub = { normalizePath: (p) => p.replace(/\\+/g, "/") };
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
}

async function main() {
  installObsidianStub();
  const { buildWingMapper, DEFAULT_WING_CONFIG, loadWingConfig } = await loadModule(
    "search/wingMapping.ts",
    "wingMapping.cjs.js",
  );

  // Default config: top-level folder → vault:<folder>; root files → default_wing
  {
    const mapper = buildWingMapper(DEFAULT_WING_CONFIG);
    assert.equal(mapper.pathToWing("Projects/Crabby/Search.md"), "vault:Projects");
    assert.equal(mapper.pathToWing("Diary/2026-05-24.md"), "vault:Diary");
    assert.equal(mapper.pathToWing("Inbox.md"), "vault_default");
    assert.equal(
      mapper.pathToWing(".crabby/memory/x.md"),
      null,
      "exclude .crabby/**",
    );
    assert.equal(
      mapper.pathToWing(".obsidian/workspace.json"),
      null,
      "exclude .obsidian/**",
    );
    console.log("ok default mapping");
  }

  // Custom rules with capture
  {
    const mapper = buildWingMapper({
      rules: [
        { match: "Projects/*/**", wing: "vault:projects/{1}" },
        { match: "Reading/**", wing: "vault:reading" },
      ],
      default_wing: "vault_default",
      exclude: [".crabby/**"],
    });
    assert.equal(
      mapper.pathToWing("Projects/Crabby/Search.md"),
      "vault:projects/Crabby",
    );
    assert.equal(
      mapper.pathToWing("Projects/Other/sub/notes.md"),
      "vault:projects/Other",
    );
    assert.equal(mapper.pathToWing("Reading/2025/book.md"), "vault:reading");
    assert.equal(mapper.pathToWing("Diary/today.md"), "vault:Diary");
    assert.equal(mapper.pathToWing("root.md"), "vault_default");
    console.log("ok custom rules with captures");
  }

  // Exclude wins over rules
  {
    const mapper = buildWingMapper({
      rules: [{ match: ".crabby/**", wing: "vault:should-not-apply" }],
      default_wing: "vault_default",
      exclude: [".crabby/**"],
    });
    assert.equal(mapper.pathToWing(".crabby/memory/a.md"), null);
    console.log("ok exclude precedence");
  }

  // T-G: loadWingConfig — missing file, malformed JSON, partial config.
  function makeApp(initial = {}) {
    const files = new Map(Object.entries(initial));
    return {
      vault: {
        adapter: {
          async exists(p) {
            return files.has(p);
          },
          async read(p) {
            if (!files.has(p)) throw new Error("ENOENT " + p);
            return files.get(p);
          },
        },
      },
    };
  }

  // T-G-1: missing config file → defaults.
  {
    const app = makeApp();
    const cfg = await loadWingConfig(app);
    assert.deepEqual(cfg, DEFAULT_WING_CONFIG);
    console.log("ok loadWingConfig missing file → defaults");
  }

  // T-G-2: malformed JSON → warn + defaults (no throw).
  {
    const origWarn = console.warn;
    let warned = false;
    console.warn = () => {
      warned = true;
    };
    try {
      const app = makeApp({ ".crabby/config/search-wings.json": "{ not json" });
      const cfg = await loadWingConfig(app);
      assert.deepEqual(cfg, DEFAULT_WING_CONFIG);
      assert.ok(warned, "should warn on malformed JSON");
    } finally {
      console.warn = origWarn;
    }
    console.log("ok loadWingConfig malformed JSON → defaults + warn");
  }

  // T-G-3: partial config (only rules) → defaults filled for missing keys.
  {
    const partial = JSON.stringify({
      rules: [{ match: "Foo/**", wing: "vault:foo" }],
    });
    const app = makeApp({ ".crabby/config/search-wings.json": partial });
    const cfg = await loadWingConfig(app);
    assert.equal(cfg.rules.length, 1);
    assert.equal(cfg.rules[0].wing, "vault:foo");
    assert.equal(
      cfg.default_wing,
      DEFAULT_WING_CONFIG.default_wing,
      "missing default_wing filled from defaults",
    );
    assert.deepEqual(
      cfg.exclude,
      DEFAULT_WING_CONFIG.exclude,
      "missing exclude filled from defaults",
    );
    console.log("ok loadWingConfig partial config fills defaults");
  }

  console.log("\nAll wing-mapping tests passed.");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
