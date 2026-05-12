/**
 * Chat sidebar view with session management and enhanced composer.
 */

import { ItemView, WorkspaceLeaf } from "obsidian";

import { AgentClient } from "../api/client";
import { createDefaultPersonaState } from "../api/client";
import { SETTINGS_UPDATED_EVENT } from "../config/settingsEvents";
import type CrabbyPlugin from "../main";
import { createChatComposer } from "./chatComposer";
import {
  ICON_ATTACH,
  ICON_HISTORY,
  ICON_PLUS,
  ICON_SEND,
  ICON_TREE,
} from "./chatIcons";
import { mountPersonaSelect } from "./chatPersonaSelect";
import { mountProfileSelect } from "./chatProfileSelect";
import { createChatSessions } from "./chatSessions";
import { ensureChatStyles } from "./chatStyles";
import { createChatTranscript } from "./chatTranscript";
import { createChatTurnRunner } from "./chatTurnRunner";
import type { ChatCleanup, ChatElements, ChatViewState } from "./chatTypes";

export const VIEW_TYPE_CHAT = "crabby-chat";

export class ChatView extends ItemView {
  private readonly client: AgentClient;
  private readonly state: ChatViewState = {
    messages: [],
    userMsgRefs: [],
    toolBlocks: new Map<string, HTMLDivElement>(),
    toolIdToName: new Map<string, string>(),
    isSending: false,
    isAborted: false,
    sessionPanelOpen: false,
    treePanelOpen: false,
    personaState: createDefaultPersonaState(),
  };

  private elements!: ChatElements;
  private cleanupFns: ChatCleanup[] = [];

  constructor(leaf: WorkspaceLeaf, private readonly plugin: CrabbyPlugin) {
    super(leaf);
    this.client = new AgentClient(this.plugin.settings.backendUrl);
  }

  getViewType(): string {
    return VIEW_TYPE_CHAT;
  }

  getDisplayText(): string {
    return "Crabby";
  }

  getIcon(): string {
    return "bot";
  }

  async onOpen(): Promise<void> {
    this.cleanupFns = [];
    this.state.messages = [];
    this.state.userMsgRefs = [];
    this.state.toolBlocks.clear();
    this.state.toolIdToName.clear();
    this.state.isSending = false;
    this.state.isAborted = false;
    this.state.sessionPanelOpen = false;
    this.state.treePanelOpen = false;
    this.state.personaState = createDefaultPersonaState();

    const container = this.contentEl;
    container.empty();
    container.addClass("crabby-chat");

    const headerArea = container.createDiv({ cls: "chat-header-area" });
    const headerLeftEl = headerArea.createDiv({
      cls: "chat-header-actions chat-header-actions-left",
    });
    const historyBtn = headerLeftEl.createEl("button", {
      cls: "chat-header-btn chat-history-btn",
      attr: { "aria-label": "历史会话" },
    });
    historyBtn.innerHTML = ICON_HISTORY;
    const treeBtn = headerLeftEl.createEl("button", {
      cls: "chat-header-btn chat-tree-btn",
      attr: { "aria-label": "会话树" },
    });
    treeBtn.innerHTML = ICON_TREE;

    const sessionTitleEl = headerArea.createDiv({ cls: "chat-header-title" });
    sessionTitleEl.setText("新会话");

    const headerRightEl = headerArea.createDiv({
      cls: "chat-header-actions chat-header-actions-right",
    });
    const newBtn = headerRightEl.createEl("button", {
      cls: "chat-header-btn chat-new-btn",
      attr: { "aria-label": "新建会话" },
    });
    newBtn.innerHTML = ICON_PLUS;

    const sessionPanelEl = container.createDiv({ cls: "session-panel" });
    const panelHeader = sessionPanelEl.createDiv({
      cls: "session-panel-header",
    });
    panelHeader.createEl("span", {
      text: "历史会话",
      cls: "session-panel-title",
    });
    const closeBtn = panelHeader.createEl("button", {
      cls: "session-panel-close",
      attr: { "aria-label": "关闭" },
    });
    closeBtn.setText("×");
    const sessionListEl = sessionPanelEl.createDiv({ cls: "session-list" });

    const treePanelEl = container.createDiv({ cls: "session-panel tree-panel" });
    const treePanelHeader = treePanelEl.createDiv({
      cls: "session-panel-header",
    });
    const treePanelTitleEl = treePanelHeader.createSpan({
      cls: "session-panel-title",
    });
    treePanelTitleEl.setText("会话树");
    const treeCloseBtn = treePanelHeader.createEl("button", {
      cls: "session-panel-close",
      attr: { "aria-label": "关闭会话树" },
    });
    treeCloseBtn.setText("×");
    const treeListEl = treePanelEl.createDiv({ cls: "conversation-tree-list" });

    const bodyArea = container.createDiv({ cls: "chat-body" });
    const minimapEl = bodyArea.createDiv({ cls: "chat-minimap" });
    minimapEl.createDiv({ cls: "chat-minimap-line" });
    const messagesEl = bodyArea.createDiv({ cls: "chat-messages" });

    const footerArea = container.createDiv({ cls: "chat-footer" });
    const inputArea = footerArea.createDiv({ cls: "chat-input-area" });
    const composerPillsEl = inputArea.createDiv({ cls: "chat-composer-pills" });
    const suggestionListEl = inputArea.createDiv({ cls: "chat-suggestion-list" });

    const inputRowEl = inputArea.createDiv({ cls: "chat-input-row" });
    const attachmentBtn = inputRowEl.createEl("button", {
      cls: "chat-attach-btn",
      attr: { "aria-label": "选择图片" },
    });
    attachmentBtn.innerHTML = ICON_ATTACH;
    const inputEl = inputRowEl.createEl("textarea", {
      cls: "chat-input",
      attr: {
        placeholder: "输入消息，支持 /skill、@文件 和粘贴图片...",
        rows: "1",
      },
    });
    const sendBtn = inputRowEl.createEl("button", {
      cls: "chat-send-btn",
      attr: { "aria-label": "发送" },
    });
    sendBtn.innerHTML = ICON_SEND;

    const hiddenFileInput = inputRowEl.createEl("input", {
      attr: { type: "file", accept: "image/*", multiple: "true" },
    });
    hiddenFileInput.addClass("chat-hidden-file-input");

    const bottomArea = footerArea.createDiv({ cls: "chat-model-area" });
    const contextBarEl = bottomArea.createDiv({ cls: "chat-context-bar" });

    this.elements = {
      messagesEl,
      minimapEl,
      inputAreaEl: inputArea,
      inputEl,
      sendBtn,
      attachmentBtn,
      hiddenFileInput,
      composerPillsEl,
      suggestionListEl,
      contextBarEl,
      sessionTitleEl,
      sessionPanelEl,
      sessionListEl,
      treePanelEl,
      treePanelTitleEl,
      treeListEl,
    };

    ensureChatStyles();

    const composer = createChatComposer({
      app: this.app,
      component: this,
      client: this.client,
      plugin: this.plugin,
      elements: this.elements,
      state: this.state,
    });
    this.cleanupFns.push(() => composer.destroy());

    const transcript = createChatTranscript({
      app: this.app,
      component: this,
      client: this.client,
      plugin: this.plugin,
      elements: this.elements,
      state: this.state,
    });
    const persona = mountPersonaSelect(bottomArea, this.client, this.state);
    this.cleanupFns.push(() => persona.destroy());
    const sessions = createChatSessions({
      app: this.app,
      component: this,
      client: this.client,
      plugin: this.plugin,
      elements: this.elements,
      state: this.state,
      composer,
      transcript,
      persona,
    });
    const turnRunner = createChatTurnRunner({
      app: this.app,
      component: this,
      client: this.client,
      plugin: this.plugin,
      elements: this.elements,
      state: this.state,
      composer,
      transcript,
      sessions,
      persona,
    });

    this.cleanupFns.push(
      mountProfileSelect(bottomArea, this.plugin, this.client),
    );

    this.client.onSysNotify = (event) => {
      turnRunner.handleSysNotify(event);
    };
    this.cleanupFns.push(() => {
      this.client.onSysNotify = undefined;
    });

    const settingsUpdatedListener = () => {
      this.client.setBaseUrl(this.plugin.settings.backendUrl);
    };
    document.addEventListener(SETTINGS_UPDATED_EVENT, settingsUpdatedListener);
    this.cleanupFns.push(() => {
      document.removeEventListener(
        SETTINGS_UPDATED_EVENT,
        settingsUpdatedListener,
      );
    });

    historyBtn.addEventListener("click", () => {
      sessions.toggleSessionPanel();
    });
    treeBtn.addEventListener("click", () => {
      sessions.toggleTreePanel();
    });
    closeBtn.addEventListener("click", () => {
      sessions.toggleSessionPanel();
    });
    treeCloseBtn.addEventListener("click", () => {
      sessions.toggleTreePanel();
    });
    newBtn.addEventListener("click", () => {
      sessions.handleNewSession();
    });

    sendBtn.addEventListener("click", () => {
      if (this.state.isSending) {
        turnRunner.handleStop();
      } else {
        void turnRunner.handleSend();
      }
    });

    inputEl.addEventListener("keydown", (evt: KeyboardEvent) => {
      if (evt.defaultPrevented) {
        return;
      }
      if (
        !evt.shiftKey &&
        !evt.altKey &&
        !evt.ctrlKey &&
        !evt.metaKey &&
        (evt.key === "ArrowUp" || evt.key === "ArrowDown") &&
        composer.navigateHistory(evt.key === "ArrowUp" ? "up" : "down")
      ) {
        evt.preventDefault();
        return;
      }
      if (evt.key === "Enter" && !evt.shiftKey) {
        evt.preventDefault();
        void turnRunner.handleSend();
      }
    });

    transcript.appendMessage(
      "assistant",
      "你好！我是你的 Crabby，有什么可以帮你的？",
    );
  }

  async onClose(): Promise<void> {
    for (const cleanup of this.cleanupFns.splice(0).reverse()) {
      try {
        cleanup();
      } catch {
        // Best-effort cleanup only.
      }
    }

    this.client.disconnect();
    this.contentEl.empty();
  }
}
