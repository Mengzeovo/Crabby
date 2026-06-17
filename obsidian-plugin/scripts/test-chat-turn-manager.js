const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const esbuild = require("esbuild");

async function loadTurnManagerModule() {
  const outdir = await fs.mkdtemp(path.join(os.tmpdir(), "turn-manager-test-"));
  const outfile = path.join(outdir, "turn-manager.cjs");
  await esbuild.build({
    entryPoints: [path.join(__dirname, "../src/chat/chatTurnManager.ts")],
    bundle: true,
    format: "cjs",
    platform: "node",
    outfile,
    logLevel: "silent",
  });
  return require(outfile);
}

async function loadTurnRunnerModule() {
  const outdir = await fs.mkdtemp(path.join(os.tmpdir(), "turn-runner-test-"));
  const outfile = path.join(outdir, "turn-runner.cjs");
  await esbuild.build({
    entryPoints: [path.join(__dirname, "../src/chat/chatTurnRunner.ts")],
    bundle: true,
    format: "cjs",
    platform: "node",
    outfile,
    logLevel: "silent",
    plugins: [
      {
        name: "obsidian-stub",
        setup(build) {
          build.onResolve({ filter: /^obsidian$/ }, () => ({
            path: "obsidian-stub",
            namespace: "obsidian-stub",
          }));
          build.onLoad({ filter: /.*/, namespace: "obsidian-stub" }, () => ({
            contents: `
class Notice {
  static messages = [];
  constructor(message) {
    Notice.messages.push(String(message));
  }
}
module.exports = { MarkdownRenderer: { render() {} }, Notice };
`,
            loader: "js",
          }));
        },
      },
    ],
  });
  return require(outfile);
}

function nextTick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function waitFor(predicate) {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (predicate()) {
      return;
    }
    await nextTick();
  }
  assert.ok(predicate(), "condition was not met");
}

async function main() {
  const fetchCalls = [];
  const pendingFetchResolves = [];
  global.fetch = (url, init) => {
    fetchCalls.push({ url: String(url), init });
    return new Promise((resolve) => {
      pendingFetchResolves.push(() =>
        resolve({
          ok: true,
          json: async () => ({ ok: true, status: "cancelled" }),
          text: async () => "",
        }),
      );
    });
  };

  const sockets = [];
  class FakeWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 3;

    constructor(url) {
      this.url = url;
      this.readyState = FakeWebSocket.CONNECTING;
      this.listeners = new Map();
      this.sent = [];
      this.closed = false;
      sockets.push(this);
      setTimeout(() => {
        this.readyState = FakeWebSocket.OPEN;
        this.emit("open", {});
      }, 0);
    }

    addEventListener(type, handler) {
      const handlers = this.listeners.get(type) || [];
      handlers.push(handler);
      this.listeners.set(type, handlers);
    }

    removeEventListener(type, handler) {
      const handlers = this.listeners.get(type) || [];
      this.listeners.set(
        type,
        handlers.filter((candidate) => candidate !== handler),
      );
    }

    emit(type, event) {
      for (const handler of this.listeners.get(type) || []) {
        handler(event);
      }
    }

    send(message) {
      this.sent.push(String(message));
    }

    close() {
      this.closed = true;
      this.readyState = FakeWebSocket.CLOSED;
    }
  }
  global.WebSocket = FakeWebSocket;

  const { ChatTurnManager } = await loadTurnManagerModule();
  const manager = new ChatTurnManager("http://127.0.0.1:8000");

  manager.setCurrentConversation("session-1", "root");
  const firstEvents = [];
  let firstBuffer = "";
  const first = manager.startTurn({
    sessionId: "session-1",
    conversationId: "root",
    payload: { content: "first" },
    callbacks: {
      onForeground: () => {
        if (firstBuffer) {
          firstEvents.push(firstBuffer);
        }
      },
      onTextDelta: (text) => {
        firstBuffer += text;
        if (manager.isCurrent("session-1", "root")) {
          firstEvents.push(firstBuffer);
        }
      },
    },
  });
  assert.ok(first);

  await waitFor(() => sockets[0]?.sent.length === 1);
  assert.match(sockets[0].url, /\/sessions\/session-1\/conversations\/root\/ws$/);

  manager.setCurrentConversation("session-2", "root");
  assert.equal(sockets[0].closed, false);

  const second = manager.startTurn({
    sessionId: "session-2",
    conversationId: "root",
    payload: { content: "second" },
    callbacks: {},
  });
  assert.ok(second);

  await waitFor(() => sockets[1]?.sent.length === 1);
  assert.match(sockets[1].url, /\/sessions\/session-2\/conversations\/root\/ws$/);
  assert.equal(manager.getSessionStatus("session-1"), "running");
  assert.equal(manager.getSessionStatus("session-2"), "running");

  const blockedSameSession = manager.startTurn({
    sessionId: "session-2",
    conversationId: "branch",
    payload: { content: "blocked" },
    callbacks: {},
  });
  assert.equal(blockedSameSession, null);
  assert.equal(sockets.length, 2);

  manager.setCurrentConversation(null, null);
  sockets[0].emit("message", {
    data: JSON.stringify({ type: "text_delta", text: "hidden" }),
  });
  assert.deepEqual(firstEvents, []);

  manager.setCurrentConversation("session-1", "root");
  assert.deepEqual(firstEvents, ["hidden"]);

  const abortSecond = manager.abort("session-2", "root");
  await waitFor(() => fetchCalls.length === 1);
  assert.match(
    fetchCalls[0].url,
    /\/sessions\/session-2\/conversations\/root\/abort$/,
  );
  assert.equal(manager.getSessionStatus("session-2"), "running");
  assert.equal(sockets[0].closed, false);
  pendingFetchResolves.shift()();
  await abortSecond;
  await second.finished;
  assert.equal(manager.getSessionStatus("session-2"), "aborted");
  manager.setCurrentConversation("session-2", "root");
  assert.equal(manager.getStatus("session-2", "root"), "aborted");
  assert.equal(manager.consumeTerminalStatus("session-2", "root"), "aborted");
  assert.equal(manager.getStatus("session-2", "root"), null);

  sockets[0].emit("message", {
    data: JSON.stringify({
      type: "done",
      session_id: "session-1",
      conversation_id: "root",
    }),
  });
  await first.finished;
  assert.equal(manager.getSessionStatus("session-1"), "done");

  const { createChatTurnRunner } = await loadTurnRunnerModule();
  await testTurnRunnerReassertsCurrentConversation(createChatTurnRunner);
}

async function testTurnRunnerReassertsCurrentConversation(createChatTurnRunner) {
  const setCalls = [];
  let currentConversation = null;
  let startOptions = null;
  let hasRunningCheckedAfterSync = false;
  let composerCleared = false;
  const appendedMessages = [];

  const turnManager = {
    setCurrentConversation(sessionId, conversationId) {
      currentConversation = { sessionId, conversationId };
      setCalls.push(currentConversation);
    },
    isRunning() {
      return false;
    },
    isCurrent(sessionId, conversationId) {
      return (
        currentConversation?.sessionId === sessionId &&
        currentConversation?.conversationId === conversationId
      );
    },
    hasRunningSession(sessionId) {
      assert.equal(sessionId, "watcher-session");
      assert.deepEqual(currentConversation, {
        sessionId: "watcher-session",
        conversationId: "root",
      });
      hasRunningCheckedAfterSync = true;
      return false;
    },
    startTurn(options) {
      startOptions = options;
      return {
        sessionId: options.sessionId,
        conversationId: options.conversationId,
        status: "running",
        finished: Promise.resolve(),
        abort: async () => {},
        detach: () => {},
      };
    },
  };

  const runner = createChatTurnRunner({
    app: {},
    component: {},
    client: {
      sessionId: "watcher-session",
      conversationId: "root",
      createSession: async () => {
        throw new Error("existing Watcher session should be reused");
      },
      chat: async () => {
        throw new Error("streaming path should be used");
      },
    },
    plugin: {
      applyLlmProfile: async () => ({ ok: true, message: "" }),
      ensureBackendVaultPathSynced: async () => ({
        ok: true,
        changed: false,
        message: "ok",
      }),
    },
    composer: {
      getSubmitPayload: () => ({
        request: { content: "hello" },
        displayText: "hello",
        displayAttachments: [],
      }),
      navigateHistory: () => false,
      clear: () => {
        composerCleared = true;
      },
      destroy: () => {},
    },
    elements: createTurnRunnerElements(),
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
        mode: "auto",
        manual_persona_id: null,
        active_persona_id: null,
        source: "none",
        status: "unresolved",
      },
    },
    transcript: {
      appendMessage: (...args) => appendedMessages.push(args),
      renderAssistantMessage: () => {},
      updateLastUserMessageId: () => false,
      beginTool: () => {},
      completeTool: () => {},
      renderHistoricalTool: () => {},
      clearConversationUi: () => {},
      clearToolTracking: () => {},
      removeTransientUi: () => {},
      scrollToBottom: () => {},
      updateContextBar: () => {},
      setForkHandler: () => {},
    },
    sessions: {
      handleNewSession: () => {},
      toggleSessionPanel: () => {},
      toggleTreePanel: () => {},
      loadSessionList: async () => {},
      loadConversationTree: async () => {},
      switchToSession: async () => {},
      deleteSessionConfirm: async () => {},
      syncCurrentSessionTitle: async () => {},
    },
    persona: { setPersonaState: () => {} },
    diaryPrompt: {
      showLoopStopResult: () => {},
      hide: () => {},
      destroy: () => {},
    },
    turnManager,
  });

  await runner.handleSend();

  assert.deepEqual(setCalls, [
    { sessionId: "watcher-session", conversationId: "root" },
  ]);
  assert.equal(hasRunningCheckedAfterSync, true);
  assert.equal(startOptions.sessionId, "watcher-session");
  assert.equal(startOptions.conversationId, "root");
  assert.deepEqual(startOptions.payload, {
    content: "hello",
    persona_mode: "auto",
    manual_persona_id: null,
    session_id: "watcher-session",
    conversation_id: "root",
  });
  assert.equal(composerCleared, true);
  assert.deepEqual(appendedMessages[0], ["user", "hello", true, []]);
}

function createTurnRunnerElements() {
  const inputEl = { disabled: false };
  const attachmentBtn = { disabled: false };
  const sendBtn = {
    classList: new ClassListStub(),
    innerHTML: "",
    attributes: {},
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
  };
  return {
    messagesEl: {},
    minimapEl: {},
    diaryPromptEl: {},
    inputAreaEl: {},
    inputEl,
    sendBtn,
    attachmentBtn,
    hiddenFileInput: {},
    composerPillsEl: {},
    suggestionListEl: {},
    contextBarEl: {},
    sessionTitleEl: {},
    sessionPanelEl: {},
    sessionListEl: {},
    treePanelEl: {},
    treePanelTitleEl: {},
    treeListEl: {},
  };
}

class ClassListStub {
  constructor() {
    this.classes = new Set();
  }

  add(...classes) {
    classes.forEach((cls) => this.classes.add(cls));
  }

  remove(...classes) {
    classes.forEach((cls) => this.classes.delete(cls));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
