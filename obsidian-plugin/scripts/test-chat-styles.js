const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const esbuild = require("esbuild");

async function loadChatStylesModule() {
  const outdir = await fs.mkdtemp(path.join(os.tmpdir(), "chat-styles-test-"));
  const outfile = path.join(outdir, "chatStyles.cjs");
  await esbuild.build({
    entryPoints: [path.join(__dirname, "../src/chat/chatStyles.ts")],
    bundle: true,
    format: "cjs",
    platform: "node",
    outfile,
  });
  return require(outfile);
}

function createDocumentStub() {
  const nodesById = new Map();
  const appended = [];

  return {
    nodesById,
    appended,
    head: {
      appendChild(node) {
        appended.push(node);
        nodesById.set(node.id, node);
        node.parentNode = this;
        return node;
      },
    },
    getElementById(id) {
      return nodesById.get(id) ?? null;
    },
    createElement(tagName) {
      return {
        tagName: String(tagName).toUpperCase(),
        id: "",
        textContent: "",
        parentNode: null,
      };
    },
  };
}

async function main() {
  const { ensureChatStyles } = await loadChatStylesModule();

  const previousDocument = global.document;
  const documentStub = createDocumentStub();
  global.document = documentStub;

  try {
    ensureChatStyles();
    assert.equal(documentStub.appended.length, 1);
    assert.equal(documentStub.appended[0].id, "crabby-chat-styles");
    assert.match(documentStub.appended[0].textContent, /crabby-chat/);
    assert.match(documentStub.appended[0].textContent, /chat-assistant-name/);

    documentStub.appended[0].textContent = "stale css";
    ensureChatStyles();
    assert.equal(documentStub.appended.length, 1);
    assert.match(documentStub.appended[0].textContent, /chat-msg/);
    assert.notEqual(documentStub.appended[0].textContent, "stale css");
  } finally {
    global.document = previousDocument;
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
