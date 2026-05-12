const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const esbuild = require("esbuild");

async function loadChatAssistantContentModule() {
  const outdir = await fs.mkdtemp(path.join(os.tmpdir(), "chat-content-test-"));
  const outfile = path.join(outdir, "chatAssistantContent.cjs");
  await esbuild.build({
    entryPoints: [path.join(__dirname, "../src/chat/chatAssistantContent.ts")],
    bundle: true,
    format: "cjs",
    platform: "node",
    outfile,
    plugins: [
      {
        name: "obsidian-stub",
        setup(build) {
          build.onResolve({ filter: /^obsidian$/ }, () => ({
            path: "obsidian-stub",
            namespace: "obsidian-stub",
          }));
          build.onLoad({ filter: /.*/, namespace: "obsidian-stub" }, () => ({
            contents: "module.exports = { MarkdownRenderer: { render() {} } };",
            loader: "js",
          }));
        },
      },
    ],
  });
  return require(outfile);
}

function createElementStub(cls) {
  return {
    cls,
    children: [],
    createSpan(options) {
      const span = { ...options };
      this.children.push(span);
      return span;
    },
  };
}

async function main() {
  const {
    ASSISTANT_DISPLAY_NAME,
    buildAssistantContent,
    createAssistantIdentityHeader,
    parseAssistantContent,
  } = await loadChatAssistantContentModule();

  assert.equal(ASSISTANT_DISPLAY_NAME, "Crabby");
  const container = {
    children: [],
    createDiv(options) {
      const div = createElementStub(options.cls);
      this.children.push(div);
      return div;
    },
  };
  const header = createAssistantIdentityHeader(container);
  assert.equal(header.cls, "chat-assistant-header");
  assert.deepEqual(header.children[0], {
    cls: "chat-assistant-name",
    text: "Crabby",
  });

  const visibleMarkdown = "final answer";
  const reasoningWithThinkExample =
    "The model may mention `<think>...</think>` as literal text.\nKeep reasoning.";
  const encodedContent = buildAssistantContent(
    reasoningWithThinkExample,
    visibleMarkdown,
  );
  assert.deepEqual(parseAssistantContent(encodedContent), {
    thoughtText: reasoningWithThinkExample,
    visibleMarkdown,
  });

  const legacyContent = `<think>\n${reasoningWithThinkExample}\n</think>\n\n${visibleMarkdown}`;
  assert.deepEqual(parseAssistantContent(legacyContent), {
    thoughtText: reasoningWithThinkExample,
    visibleMarkdown,
  });

  const legacyReasoningWithLiteralTags =
    "This explains literal `<think>` and `</think>` markers; it is not closing the thought block.";
  const legacyContentWithLiteralTags = `<think>\n${legacyReasoningWithLiteralTags}\n</think>\n\n${visibleMarkdown}`;
  assert.deepEqual(parseAssistantContent(legacyContentWithLiteralTags), {
    thoughtText: legacyReasoningWithLiteralTags,
    visibleMarkdown,
  });

  const legacyThinkingContent =
    "<thinking>\nMention <thinking>inner</thinking> and keep going\n</thinking>\n\nanswer";
  assert.deepEqual(parseAssistantContent(legacyThinkingContent), {
    thoughtText: "Mention <thinking>inner</thinking> and keep going",
    visibleMarkdown: "answer",
  });

  assert.deepEqual(parseAssistantContent("plain answer"), {
    thoughtText: "",
    visibleMarkdown: "plain answer",
  });
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
