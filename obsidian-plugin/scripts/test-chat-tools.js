const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const esbuild = require("esbuild");

async function loadBundledChatModule(entryFile, outfileName) {
  const outdir = await fs.mkdtemp(path.join(os.tmpdir(), "chat-tools-test-"));
  const outfile = path.join(outdir, outfileName);
  await esbuild.build({
    entryPoints: [path.join(__dirname, "../src/chat", entryFile)],
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
            contents:
              `
class Notice {
  static messages = [];
  constructor(message) {
    Notice.messages.push(String(message));
  }
}
class TFile {}
function normalizePath(value) {
  return String(value).replace(/\\\\/g, "/").replace(/\\/+/g, "/").replace(/^\\//, "");
}
module.exports = { MarkdownRenderer: { render() {} }, Notice, TFile, normalizePath, setTooltip() {} };
`,
            loader: "js",
          }));
        },
      },
    ],
  });
  return require(outfile);
}

async function loadChatTranscriptModule() {
  return loadBundledChatModule("chatTranscript.ts", "chatTranscript.cjs");
}

async function loadChatDiaryPromptModule() {
  return loadBundledChatModule("chatDiaryPrompt.ts", "chatDiaryPrompt.cjs");
}

async function main() {
  const {
    createChatTranscript,
    formatToolMeta,
    formatToolOutput,
    formatToolCardDetail,
    formatToolPreview,
    getToolPayloadId,
    getToolPayloadName,
    normalizeToolPayload,
    toolStatus,
    toolStatusIcon,
    toolStatusLabel,
  } = await loadChatTranscriptModule();

  const failingPayload = normalizeToolPayload({
    id: "toolu_1",
    tool_use_id: "toolu_1",
    name: "bash",
    output: "failure detail",
    status: "error",
    is_error: true,
    metadata: { exit_code: 7 },
    elapsed_ms: 12.4,
  });

  assert.equal(getToolPayloadId(failingPayload), "toolu_1");
  assert.equal(getToolPayloadName(failingPayload), "bash");
  assert.equal(toolStatus(failingPayload), "error");
  assert.equal(toolStatusIcon("error"), "x");
  assert.equal(toolStatusLabel("error"), "failed");
  assert.equal(formatToolMeta(failingPayload), "exit 7 · 12ms");
  assert.equal(formatToolOutput(failingPayload), "failure detail");

  const cardPayload = normalizeToolPayload({
    id: "toolu_card",
    name: "bash",
    output: "full output line one\nfull output line two",
    summary: "short summary",
    input_summary: "{\"command\":\"echo hi\"}",
    output_preview: "preview line",
    detail_ref: "tool-result://bash/toolu_card",
    detail_available: true,
  });
  assert.equal(formatToolPreview(cardPayload), "preview line");
  assert.match(formatToolCardDetail(cardPayload), /Input: \{"command":"echo hi"\}/);
  assert.match(formatToolCardDetail(cardPayload), /Summary: short summary/);
  assert.match(formatToolCardDetail(cardPayload), /full output line two/);
  assert.match(formatToolCardDetail(cardPayload), /tool-result:\/\/bash\/toolu_card/);

  const truncatedPayload = normalizeToolPayload({
    name: "read",
    output: "partial",
    is_truncated: true,
    cache_path: "cache/tool-results/read.txt",
  });
  assert.equal(toolStatus(truncatedPayload), "warning");
  assert.match(formatToolOutput(truncatedPayload), /result truncated/);
  assert.match(formatToolOutput(truncatedPayload), /cache\/tool-results\/read.txt/);

  const editPayload = normalizeToolPayload({
    name: "edit",
    output: "修改文件: note.md",
    metadata: {
      file_changes: [
        {
          path: "note.md",
          operation: "modified",
        },
      ],
    },
  });
  assert.equal(formatToolMeta(editPayload), "1 file modified");

  const createPayload = normalizeToolPayload({
    name: "edit",
    output: "创建文件: notes/new.md",
    metadata: {
      file_changes: [
        {
          path: "notes/new.md",
          operation: "created",
        },
      ],
    },
  });
  assert.equal(formatToolMeta(createPayload), "1 file created");

  const legacyPayload = normalizeToolPayload("grep", "old output");
  assert.equal(getToolPayloadName(legacyPayload), "grep");
  assert.equal(legacyPayload.output, "old output");
  assert.equal(toolStatus(legacyPayload), "success");

  const { transcript, messagesEl, contextBarEl } =
    createTranscriptHarness(createChatTranscript);
  transcript.beginTool("bash", "toolu_first");
  transcript.beginTool("bash", "toolu_second");
  transcript.completeTool({
    id: "toolu_first",
    tool_use_id: "toolu_first",
    name: "bash",
    output: "first failed",
    status: "error",
    is_error: true,
    metadata: { exit_code: 7 },
  });

  const toolBlocks = messagesEl.children.filter((child) =>
    child.classList.contains("chat-tool-block"),
  );
  assert.equal(toolBlocks.length, 2);
  assert.equal(toolBlocks[0].classList.contains("done"), true);
  assert.equal(toolBlocks[0].classList.contains("error"), true);
  assert.equal(toolBlocks[1].classList.contains("running"), true);
  assert.match(toolBlocks[0].querySelector(".chat-tool-terminal").textContent, /first failed/);

  transcript.completeTool({
    id: "toolu_second",
    tool_use_id: "toolu_second",
    name: "bash",
    output: "second ok",
    status: "success",
    metadata: { exit_code: 0 },
  });
  assert.equal(toolBlocks[1].classList.contains("done"), true);
  assert.equal(toolBlocks[1].classList.contains("success"), true);

  transcript.updateContextBar({
    total_tokens: 35540,
    system_tokens: 1608,
    schema_tokens: 1187,
    user_tokens: 39,
    assistant_tokens: 8440,
    tool_result_tokens: 24266,
    message_count: 26,
    user_message_count: 1,
    assistant_message_count: 4,
    tool_result_count: 3,
    context_limit: 200000,
    usage_percent: 17.77,
    actual_usage: {
      call_count: 4,
      prompt_tokens: 85415,
      completion_tokens: 2658,
      total_tokens: 88073,
      reasoning_tokens: 833,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 0,
      prompt_cache_hit_tokens: 6500,
      prompt_cache_miss_tokens: 78915,
      prompt_cached_tokens: 0,
    },
    cumulative_usage: {
      call_count: 13,
      prompt_tokens: 145287,
      completion_tokens: 9232,
      total_tokens: 154519,
      reasoning_tokens: 5221,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 0,
      prompt_cache_hit_tokens: 118144,
      prompt_cache_miss_tokens: 27143,
      prompt_cached_tokens: 0,
    },
  });
  assert.match(
    contextBarEl.attributes["aria-label"],
    /当前上下文窗口\n占用：35,540 \/ 200,000 tokens/,
  );
  assert.match(contextBarEl.attributes["aria-label"], /服务商用量（usage）/);
  assert.match(
    contextBarEl.attributes["aria-label"],
    /本轮：88,073 tokens，4 次模型调用。/,
  );
  assert.match(
    contextBarEl.attributes["aria-label"],
    /输出：2,658（含推理 833）。/,
  );
  assert.match(
    contextBarEl.attributes["aria-label"],
    /输入缓存：命中 6,500，未命中 78,915。/,
  );
  assert.match(
    contextBarEl.attributes["aria-label"],
    /会话累计：154,519 tokens，13 次模型调用。/,
  );
  assert.equal(
    contextBarEl.querySelector(".context-usage-label").textContent,
    "用量 154.5k",
  );
  assert.equal(
    contextBarEl.querySelector(".context-percent-label").textContent,
    "18%",
  );

  transcript.renderHistoricalTool({
    id: "toolu_history",
    name: "read",
    output: "historic partial",
    status: "warning",
    is_truncated: true,
    cache_path: "cache/tool-results/read.txt",
  });
  const historicalBlock = messagesEl.children[messagesEl.children.length - 1];
  assert.equal(historicalBlock.classList.contains("warning"), true);
  assert.match(
    historicalBlock.querySelector(".chat-tool-terminal").textContent,
    /historic partial/,
  );

  const { createDiaryPrompt } = await loadChatDiaryPromptModule();
  await testDiaryPrompt(createDiaryPrompt);
}

class ClassListStub {
  constructor(initial = "") {
    this.classes = new Set(initial.split(/\s+/).filter(Boolean));
  }

  add(...classes) {
    classes.forEach((cls) => this.classes.add(cls));
  }

  remove(...classes) {
    classes.forEach((cls) => this.classes.delete(cls));
  }

  toggle(cls, force) {
    const shouldAdd = force === undefined ? !this.classes.has(cls) : Boolean(force);
    if (shouldAdd) {
      this.classes.add(cls);
    } else {
      this.classes.delete(cls);
    }
    return shouldAdd;
  }

  contains(cls) {
    return this.classes.has(cls);
  }
}

class ElementStub {
  constructor(cls = "") {
    this.children = [];
    this.classList = new ClassListStub(cls);
    this.textContent = "";
    this.style = {
      setProperty(name, value) {
        this[name] = String(value);
      },
    };
    this.attributes = {};
    this.listeners = {};
    this.scrollTop = 0;
    this.scrollHeight = 100;
    this.clientHeight = 100;
  }

  createDiv(options = {}) {
    return this._createChild(options);
  }

  createSpan(options = {}) {
    return this._createChild(options);
  }

  createEl(_tag, options = {}) {
    return this._createChild({
      cls: options.cls,
      text: options.text,
    });
  }

  _createChild(options = {}) {
    const child = new ElementStub(options.cls || "");
    child.parent = this;
    if (options.text !== undefined) {
      child.setText(options.text);
    }
    this.children.push(child);
    return child;
  }

  empty() {
    this.children = [];
    this.textContent = "";
  }

  setText(text) {
    this.textContent = String(text);
  }

  addEventListener(type, handler) {
    this.listeners[type] = handler;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  removeAttribute(name) {
    delete this.attributes[name];
  }

  remove() {
    if (!this.parent) return;
    this.parent.children = this.parent.children.filter((child) => child !== this);
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    const selectors = selector.split(",").map((part) => part.trim());
    const results = [];
    const visit = (node) => {
      for (const child of node.children) {
        if (selectors.some((part) => matchesSelector(child, part))) {
          results.push(child);
        }
        visit(child);
      }
    };
    visit(this);
    return results;
  }
}

function matchesSelector(node, selector) {
  if (!selector.startsWith(".")) {
    return false;
  }
  const classes = selector.split(".").filter(Boolean);
  return classes.every((cls) => node.classList.contains(cls));
}

function createTranscriptHarness(createChatTranscript) {
  const messagesEl = new ElementStub();
  const elements = {
    messagesEl,
    minimapEl: new ElementStub(),
    inputAreaEl: new ElementStub(),
    inputEl: new ElementStub(),
    sendBtn: new ElementStub(),
    attachmentBtn: new ElementStub(),
    hiddenFileInput: new ElementStub(),
    composerPillsEl: new ElementStub(),
    suggestionListEl: new ElementStub(),
    contextBarEl: new ElementStub(),
    sessionTitleEl: new ElementStub(),
    sessionPanelEl: new ElementStub(),
    sessionListEl: new ElementStub(),
    treePanelEl: new ElementStub(),
    treePanelTitleEl: new ElementStub(),
    treeListEl: new ElementStub(),
  };
  const transcript = createChatTranscript({
    app: {},
    component: {},
    plugin: {},
    client: { getAttachmentUrl: (id) => `/attachments/${id}` },
    elements,
    state: {
      messages: [],
      userMsgRefs: [],
      toolBlocks: new Map(),
      toolIdToName: new Map(),
      isSending: false,
      isAborted: false,
      sessionPanelOpen: false,
      treePanelOpen: false,
      personaState: {
        mode: "none",
        manual_persona_id: null,
        active_persona_id: null,
        source: "none",
        status: "inactive",
      },
    },
  });
  return { transcript, messagesEl, contextBarEl: elements.contextBarEl };
}

async function testDiaryPrompt(createDiaryPrompt) {
  const vaultRoot = await fs.mkdtemp(path.join(os.tmpdir(), "chat-diary-test-"));
  const templateDir = path.join(vaultRoot, ".crabby", "templates", "diary");
  await fs.mkdir(templateDir, { recursive: true });
  await fs.writeFile(path.join(templateDir, "daily.md"), "template", "utf8");

  const rootEl = new ElementStub();
  let resolveFirstWrite;
  const firstWrite = new Promise((resolve) => {
    resolveFirstWrite = resolve;
  });
  let writeCalls = 0;
  const client = {
    writeDiaryEntry: () => {
      writeCalls += 1;
      return firstWrite;
    },
  };
  const plugin = {
    settings: {
      diary: {
        templatePaths: {
          daily: ".crabby/templates/diary/daily.md",
        },
      },
    },
    getCurrentVaultPath: () => vaultRoot,
    ensureBackendVaultPathSynced: async () => ({
      ok: true,
      changed: false,
      message: "ok",
    }),
  };
  const controller = createDiaryPrompt({
    app: { vault: { getAbstractFileByPath: () => null } },
    client,
    plugin,
    rootEl,
    openPluginSettings: () => true,
  });

  controller.showLoopStopResult(
    { name: "loop_stop", output: "missing job", metadata: {} },
    "session-1",
    "conversation-1",
  );
  assert.equal(rootEl.children.length, 0);
  assert.equal(rootEl.classList.contains("is-open"), false);

  controller.showLoopStopResult(
    { name: "loop_stop", output: "first summary", metadata: { job_id: "job-1" } },
    "session-1",
    "conversation-1",
  );
  assert.equal(rootEl.classList.contains("is-open"), true);
  assert.match(
    rootEl.querySelector(".chat-diary-prompt-preview").textContent,
    /first summary/,
  );

  const writeButton = rootEl.querySelector(".chat-diary-prompt-btn.is-primary");
  assert.ok(writeButton, "filesystem template fallback should show the write button");
  writeButton.listeners.click();

  controller.showLoopStopResult(
    { name: "loop_stop", output: "second summary", metadata: { job_id: "job-2" } },
    "session-1",
    "conversation-1",
  );
  resolveFirstWrite({ status: "success", is_error: false, output: "ok", metadata: {} });
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(writeCalls, 1);
  assert.equal(rootEl.classList.contains("is-open"), true);
  assert.match(
    rootEl.querySelector(".chat-diary-prompt-preview").textContent,
    /second summary/,
  );
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
