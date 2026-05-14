import { App, Modal, Notice } from "obsidian";

import { createDefaultPersonaState } from "../api/client";
import type {
  ConversationInfo,
  ContextStats,
  MessageAttachment,
  SessionInfo,
  SessionMessage,
  ToolCallPayload,
} from "../api/client";
import {
  buildAssistantContent,
  parseAssistantContent,
} from "./chatAssistantContent";
import { ICON_TRASH } from "./chatIcons";
import type {
  ChatSessionsController,
  ForkMessageTarget,
  SessionDeps,
} from "./chatTypes";

function formatRelativeTime(timestamp: number): string {
  if (timestamp == null || Number.isNaN(timestamp)) {
    return "未知时间";
  }

  const milliseconds = timestamp > 1e10 ? timestamp : timestamp * 1000;
  if (milliseconds === 0) {
    return "早期会话";
  }

  const diff = Date.now() - milliseconds;
  if (diff < 0) {
    return "刚刚";
  }

  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) {
    return "刚刚";
  }
  if (minutes < 60) {
    return `${minutes} 分钟前`;
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} 小时前`;
  }

  const days = Math.floor(hours / 24);
  if (days < 7) {
    return `${days} 天前`;
  }

  const date = new Date(milliseconds);
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
}

function getReasoningText(block: Record<string, unknown>): string {
  const details = block.reasoning_details;
  if (Array.isArray(details)) {
    return details
      .map((detail) => {
        if (
          typeof detail === "object" &&
          detail !== null &&
          typeof (detail as { text?: unknown }).text === "string"
        ) {
          return (detail as { text: string }).text;
        }
        return "";
      })
      .join("");
  }

  return typeof block.thinking === "string" ? block.thinking : "";
}

type ConversationTreeNode = ConversationInfo & {
  children: ConversationTreeNode[];
};

class ForkConversationModal extends Modal {
  private readonly resolve: (value: string | null) => void;
  private resolved = false;
  private titleInput!: HTMLInputElement;

  constructor(
    app: App,
    private readonly sourcePreview: string,
    private readonly suggestedTitle: string,
    resolve: (value: string | null) => void,
  ) {
    super(app);
    this.resolve = resolve;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("fork-conversation-modal");

    contentEl.createEl("h2", { text: "确认分叉标题" });

    const previewSection = contentEl.createDiv({
      cls: "fork-conversation-preview",
    });
    previewSection.createEl("div", {
      cls: "fork-conversation-label",
      text: "来源消息",
    });
    previewSection.createEl("div", {
      cls: "fork-conversation-text",
      text: this.sourcePreview,
    });

    const titleSection = contentEl.createDiv({
      cls: "fork-conversation-title",
    });
    titleSection.createEl("div", {
      cls: "fork-conversation-label",
      text: "分支标题",
    });
    this.titleInput = titleSection.createEl("input", {
      cls: "fork-conversation-input",
      attr: { type: "text", value: this.suggestedTitle, spellcheck: "false" },
    });
    this.titleInput.addEventListener("keydown", (evt) => {
      if (evt.key === "Enter") {
        evt.preventDefault();
        this.submit();
      }
      if (evt.key === "Escape") {
        evt.preventDefault();
        this.close();
      }
    });

    const buttonRow = contentEl.createDiv({
      cls: "fork-conversation-actions",
    });
    const cancelBtn = buttonRow.createEl("button", {
      cls: "mod-muted",
      text: "取消",
    });
    cancelBtn.addEventListener("click", () => this.close());

    const confirmBtn = buttonRow.createEl("button", {
      cls: "mod-cta",
      text: "分叉",
    });
    confirmBtn.addEventListener("click", () => this.submit());

    window.requestAnimationFrame(() => {
      this.titleInput.focus();
      this.titleInput.select();
    });
  }

  onClose(): void {
    if (!this.resolved) {
      this.resolved = true;
      this.resolve(null);
    }
    this.contentEl.removeClass("fork-conversation-modal");
    this.contentEl.empty();
  }

  private submit(): void {
    if (this.resolved) {
      return;
    }
    this.resolved = true;
    this.resolve(this.titleInput.value.trim());
    this.close();
  }
}

function promptForkTitle(
  app: App,
  sourcePreview: string,
  suggestedTitle: string,
): Promise<string | null> {
  return new Promise((resolve) => {
    const modal = new ForkConversationModal(
      app,
      sourcePreview,
      suggestedTitle,
      resolve,
    );
    modal.open();
  });
}

function normalizePreview(content: string): string {
  const parsed = parseAssistantContent(content);
  const raw = parsed.visibleMarkdown || content;
  return raw.replace(/\s+/g, " ").trim();
}

function buildForkTitleSuggestion(content: string): string {
  const preview = normalizePreview(content);
  return preview.slice(0, 40) || "新分支";
}

function buildForkPreview(content: string): string {
  const preview = normalizePreview(content);
  return preview.slice(0, 160) || "（空消息）";
}

function buildConversationTree(
  conversations: ConversationInfo[],
): ConversationTreeNode[] {
  const nodes = new Map<string, ConversationTreeNode>();
  for (const conversation of conversations) {
    nodes.set(conversation.id, {
      ...conversation,
      children: [],
    });
  }

  const roots: ConversationTreeNode[] = [];
  for (const node of nodes.values()) {
    const parentId = node.parent_id ?? "";
    const parent = parentId ? nodes.get(parentId) : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const sortNodes = (items: ConversationTreeNode[]): void => {
    items.sort((left, right) => {
      if (left.created_at !== right.created_at) {
        return left.created_at - right.created_at;
      }
      return left.id.localeCompare(right.id);
    });
    for (const item of items) {
      if (item.children.length > 0) {
        sortNodes(item.children);
      }
    }
  };
  sortNodes(roots);

  return roots;
}

export function createChatSessions(
  deps: SessionDeps,
): ChatSessionsController {
  const { app, client, composer, elements, state, transcript, persona } = deps;

  transcript.setForkHandler((target) => {
    void handleForkMessage(target);
  });

  async function loadSessionList(): Promise<void> {
    elements.sessionListEl.empty();

    const loadingEl = elements.sessionListEl.createDiv({
      cls: "session-loading",
    });
    loadingEl.setText("加载中...");

    try {
      const sessions = await client.listSessions();
      elements.sessionListEl.empty();

      if (sessions.length === 0) {
        const emptyEl = elements.sessionListEl.createDiv({
          cls: "session-empty",
        });
        emptyEl.setText("暂无历史会话");
        return;
      }

      for (const session of sessions) {
        renderSessionCard(session);
      }
    } catch {
      elements.sessionListEl.empty();
      const errEl = elements.sessionListEl.createDiv({ cls: "session-error" });
      errEl.setText("加载失败，请检查后端连接");
    }
  }

  async function loadConversationTree(): Promise<void> {
    if (!state.treePanelOpen) {
      return;
    }

    elements.treeListEl.empty();
    const loadingEl = elements.treeListEl.createDiv({
      cls: "conversation-tree-loading",
    });
    loadingEl.setText("加载中...");

    const sessionId = client.sessionId;
    if (!sessionId) {
      elements.treeListEl.empty();
      const emptyEl = elements.treeListEl.createDiv({
        cls: "conversation-tree-empty",
      });
      emptyEl.setText("当前还没有可显示的会话树");
      elements.treePanelTitleEl.setText("会话树");
      return;
    }

    try {
      const [session, conversations] = await Promise.all([
        client.getSession(sessionId),
        client.listConversations(sessionId),
      ]);

      if (!state.treePanelOpen || client.sessionId !== sessionId) {
        return;
      }

      elements.treePanelTitleEl.setText(
        session.title ? `会话树 · ${session.title}` : "会话树",
      );
      elements.treeListEl.empty();

      if (conversations.length === 0) {
        const emptyEl = elements.treeListEl.createDiv({
          cls: "conversation-tree-empty",
        });
        emptyEl.setText("当前会话尚无分支");
        return;
      }

      const tree = buildConversationTree(conversations);
      renderTreeBranch(tree, elements.treeListEl, session.id);
    } catch (err) {
      if (!state.treePanelOpen) {
        return;
      }
      elements.treeListEl.empty();
      const message = err instanceof Error ? err.message : String(err);
      const errEl = elements.treeListEl.createDiv({
        cls: "conversation-tree-error",
      });
      errEl.setText(`会话树加载失败：${message}`);
    }
  }

  function openSessionPanel(): void {
    state.sessionPanelOpen = true;
    state.treePanelOpen = false;
    elements.sessionPanelEl.addClass("open");
    elements.treePanelEl.removeClass("open");
  }

  function closeSessionPanel(): void {
    state.sessionPanelOpen = false;
    elements.sessionPanelEl.removeClass("open");
  }

  function openTreePanel(): void {
    state.treePanelOpen = true;
    state.sessionPanelOpen = false;
    elements.treePanelEl.addClass("open");
    elements.sessionPanelEl.removeClass("open");
  }

  function closeTreePanel(): void {
    state.treePanelOpen = false;
    elements.treePanelEl.removeClass("open");
  }

  function toggleSessionPanel(): void {
    if (state.sessionPanelOpen) {
      closeSessionPanel();
      return;
    }

    openSessionPanel();
    void loadSessionList();
  }

  function toggleTreePanel(): void {
    if (state.treePanelOpen) {
      closeTreePanel();
      return;
    }

    openTreePanel();
    void loadConversationTree();
  }

  function handleNewSession(): void {
    closeSessionPanel();
    closeTreePanel();

    client.disconnect();
    transcript.clearConversationUi();
    composer.clear();
    persona.setPersonaState(createDefaultPersonaState());
    elements.sessionTitleEl.setText("新会话");
    elements.treePanelTitleEl.setText("会话树");
    elements.treeListEl.empty();

    transcript.appendMessage(
      "assistant",
      "你好！新会话已经开始了，有什么可以帮你的？",
    );
  }

  async function switchToSession(session: SessionInfo): Promise<void> {
    try {
      const conversationId = session.active_conversation_id;
      let rawMessages: SessionMessage[] = [];
      let contextStats: ContextStats | null = null;

      try {
        rawMessages = await client.getConversationMessages(
          session.id,
          conversationId,
        );
      } catch (msgErr) {
        console.warn("[ChatView] getConversationMessages failed:", msgErr);
      }

      try {
        contextStats = await client.getConversationContextStats(
          session.id,
          conversationId,
        );
      } catch (contextErr) {
        console.warn(
          "[ChatView] getConversationContextStats failed:",
          contextErr,
        );
      }

      client.setSession(session.id, conversationId);
      persona.setPersonaState(
        session.persona_state ?? createDefaultPersonaState(),
      );
      elements.sessionTitleEl.setText(session.title || "未命名会话");

      transcript.clearConversationUi();
      composer.clear();

      const toolResults = new Map<string, ToolCallPayload>();
      for (const msg of rawMessages) {
        if (msg.role === "user" && Array.isArray(msg.content)) {
          for (const block of msg.content as Array<any>) {
            if (block.type === "tool_result" && block.tool_use_id) {
              const output =
                typeof block.content === "string"
                  ? block.content
                  : JSON.stringify(block.content || "");
              const ui =
                block.ui && typeof block.ui === "object"
                  ? (block.ui as ToolCallPayload)
                  : {};
              toolResults.set(block.tool_use_id, {
                id: block.tool_use_id,
                tool_use_id: block.tool_use_id,
                output,
                ...ui,
              });
            }
          }
        }
      }

      for (const msg of rawMessages) {
        if (msg.role === "user") {
          renderHistoricalUserMessage(msg);
        } else if (msg.role === "assistant") {
          renderHistoricalAssistantMessage(msg, toolResults);
        }
      }

      if (contextStats) {
        transcript.updateContextBar(contextStats);
      }

      transcript.scrollToBottom(true);

      if (state.treePanelOpen) {
        await loadConversationTree();
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error("[ChatView] switchToSession failed:", err);
      new Notice(`切换会话失败: ${message}`);
    }
  }

  function renderHistoricalUserMessage(msg: SessionMessage): void {
    const attachments = Array.isArray(msg.attachments)
      ? (msg.attachments as MessageAttachment[])
      : [];

    if (typeof msg.text === "string") {
      transcript.appendMessage(
        "user",
        msg.text,
        false,
        attachments,
        msg.message_id,
      );
      return;
    }

    let hasText = false;
    if (typeof msg.content === "string") {
      transcript.appendMessage(
        "user",
        msg.content,
        false,
        attachments,
        msg.message_id,
      );
      hasText = true;
    } else if (Array.isArray(msg.content)) {
      const texts = (msg.content as Array<any>)
        .filter((block) => block.type === "text" && block.text)
        .map((block) => block.text)
        .join("\n");

      if (texts || attachments.length > 0) {
        transcript.appendMessage(
          "user",
          texts,
          false,
          attachments,
          msg.message_id,
        );
        hasText = true;
      }
    }

    if (!hasText && !Array.isArray(msg.content) && msg.content) {
      transcript.appendMessage(
        "user",
        JSON.stringify(msg.content),
        false,
        attachments,
        msg.message_id,
      );
    }
  }

  function renderHistoricalAssistantMessage(
    msg: SessionMessage,
    toolResults: Map<string, ToolCallPayload>,
  ): void {
    if (Array.isArray(msg.content)) {
      let reasoningText = "";
      let visibleText = "";
      let forkAttached = false;

      const flushAssistantContent = (): void => {
        const content = buildAssistantContent(reasoningText, visibleText);
        if (content.trim()) {
          transcript.appendMessage(
            "assistant",
            content,
            false,
            [],
            !forkAttached && msg.message_id ? msg.message_id : undefined,
          );
          forkAttached = true;
        }
        reasoningText = "";
        visibleText = "";
      };

      for (const block of msg.content as Array<any>) {
        if (block.type === "reasoning_details" || block.type === "thinking") {
          reasoningText += getReasoningText(block);
        } else if (block.type === "text" && block.text) {
          visibleText += `${visibleText ? "\n" : ""}${block.text}`;
        } else if (block.type === "tool_use" && block.name) {
          flushAssistantContent();
          transcript.renderHistoricalTool({
            id: block.id,
            tool_use_id: block.id,
            name: block.name,
            tool: block.name,
            output: "(no output)",
            ...(toolResults.get(block.id) || {}),
          });
        }
      }
      flushAssistantContent();
      return;
    }

    if (typeof msg.content === "string" && msg.content) {
      transcript.appendMessage(
        "assistant",
        msg.content,
        false,
        [],
        msg.message_id,
      );
    }
  }

  async function deleteSessionConfirm(sessionId: string): Promise<void> {
    try {
      await client.deleteSession(sessionId);
      new Notice("会话已删除");
      await loadSessionList();
      if (client.sessionId === null) {
        closeTreePanel();
        elements.treePanelTitleEl.setText("会话树");
        elements.treeListEl.empty();
      }
    } catch {
      new Notice("删除失败");
    }
  }

  async function syncCurrentSessionTitle(sessionId: string): Promise<void> {
    if (client.sessionId !== sessionId) {
      return;
    }

    try {
      const sessions = await client.listSessions();
      const current = sessions.find((item) => item.id === sessionId);
      if (!current) {
        return;
      }

      if (elements.sessionTitleEl.getText() === "新会话" && current.title) {
        elements.sessionTitleEl.setText(current.title);
      }
      if (state.treePanelOpen) {
        elements.treePanelTitleEl.setText(
          current.title ? `会话树 · ${current.title}` : "会话树",
        );
        void loadConversationTree();
      }
    } catch {
      // Ignore title sync failures.
    }
  }

  async function handleForkMessage(target: ForkMessageTarget): Promise<void> {
    if (state.isSending) {
      new Notice("当前正在回复，请先完成后再分叉");
      return;
    }

    const sessionId = client.sessionId;
    const conversationId = client.conversationId;
    if (!sessionId || !conversationId) {
      new Notice("当前没有可分叉的会话");
      return;
    }

    const suggestedTitle = buildForkTitleSuggestion(target.content);
    const preview = buildForkPreview(target.content);
    const title = await promptForkTitle(app, preview, suggestedTitle);
    if (title === null) {
      return;
    }

    try {
      const updatedSession = await client.forkConversation(
        sessionId,
        conversationId,
        target.messageId,
        title,
      );
      await switchToSession(updatedSession);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      new Notice(`分叉失败: ${message}`);
    }
  }

  function renderSessionCard(session: SessionInfo): void {
    const card = elements.sessionListEl.createDiv({ cls: "session-card" });
    const isActive = client.sessionId === session.id;
    if (isActive) {
      card.addClass("active");
    }

    const contentArea = card.createDiv({ cls: "session-card-content" });

    const titleEl = contentArea.createDiv({ cls: "session-card-title" });
    titleEl.setText(session.title || "未命名会话");

    const metaEl = contentArea.createDiv({ cls: "session-card-meta" });
    const turnLabel =
      session.turn_count > 0
        ? `${session.turn_count} 次对话`
        : `${session.message_count} 条消息`;
    metaEl.setText(`${turnLabel} · ${formatRelativeTime(session.created_at)}`);

    if (isActive) {
      const badge = contentArea.createEl("span", {
        cls: "session-card-badge",
      });
      badge.setText("当前");
    }

    contentArea.addEventListener("click", () => {
      closeSessionPanel();
      void switchToSession(session);
    });

    if (!isActive) {
      const deleteBtn = card.createEl("button", {
        cls: "session-card-delete",
        attr: { "aria-label": "删除会话" },
      });
      deleteBtn.innerHTML = ICON_TRASH;
      deleteBtn.addEventListener("click", (evt) => {
        evt.stopPropagation();
        void deleteSessionConfirm(session.id);
      });
    }
  }

  function renderTreeBranch(
    nodes: ConversationTreeNode[],
    container: HTMLElement,
    sessionId: string,
  ): void {
    for (const node of nodes) {
      const branchEl = container.createDiv({ cls: "conversation-tree-branch" });
      const button = branchEl.createEl("button", {
        cls: "conversation-tree-node",
        attr: {
          type: "button",
          "aria-pressed": node.active ? "true" : "false",
          title: node.active ? "当前分支" : "切换到该分支",
        },
      });
      if (node.active) {
        button.addClass("active");
      }

      const mainRow = button.createDiv({ cls: "conversation-tree-node-main" });
      const title = mainRow.createDiv({ cls: "conversation-tree-node-title" });
      title.setText(node.title || "未命名分支");

      const activeBadge = mainRow.createSpan({
        cls: "conversation-tree-node-badge",
      });
      activeBadge.setText(node.active ? "当前" : `v${node.revision}`);

      const meta = button.createDiv({ cls: "conversation-tree-node-meta" });
      meta.setText(
        [
          `${node.message_count} 条`,
          node.fork_message_id ? `fork ${node.fork_message_id.slice(0, 8)}` : "",
          node.parent_id ? `parent ${node.parent_id.slice(0, 8)}` : "root",
        ]
          .filter(Boolean)
          .join(" · "),
      );

      button.addEventListener("click", () => {
        if (node.active) {
          return;
        }
        if (state.isSending) {
          new Notice("当前正在回复，请先完成后再切换分支");
          return;
        }
        void activateConversation(sessionId, node.id);
      });

      if (node.children.length > 0) {
        const children = branchEl.createDiv({
          cls: "conversation-tree-children",
        });
        renderTreeBranch(node.children, children, sessionId);
      }
    }
  }

  async function activateConversation(
    sessionId: string,
    conversationId: string,
  ): Promise<void> {
    try {
      const updatedSession = await client.patchSession(sessionId, {
        active_conversation_id: conversationId,
      });
      await switchToSession(updatedSession);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      new Notice(`切换分支失败: ${message}`);
    }
  }

  return {
    handleNewSession,
    toggleSessionPanel,
    toggleTreePanel,
    loadSessionList,
    loadConversationTree,
    switchToSession,
    deleteSessionConfirm,
    syncCurrentSessionTitle,
  };
}
