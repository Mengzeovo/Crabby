import type { ActualTokenUsage, MessageAttachment } from "../api/client";
import { setTooltip } from "obsidian";
import {
  createAssistantIdentityHeader,
  renderAssistantMessageContent,
} from "./chatAssistantContent";
import { ICON_FORK, getToolIcon } from "./chatIcons";
import type {
  ChatRole,
  ChatTranscriptController,
  ContextStats,
  ForkMessageHandler,
  TranscriptDeps,
} from "./chatTypes";

function getFirstNonEmptyLine(output: string): string | undefined {
  return output
    .trim()
    .split("\n")
    .find((line) => line.trim());
}

function formatCompactTokens(tokens: number): string {
  const trimDecimal = (value: string) => value.replace(/\.0$/, "");
  const absTokens = Math.abs(tokens);
  if (absTokens >= 1_000_000) {
    const digits = absTokens >= 10_000_000 ? 0 : 1;
    return `${trimDecimal((tokens / 1_000_000).toFixed(digits))}m`;
  }
  if (absTokens >= 1_000) {
    return `${trimDecimal((tokens / 1_000).toFixed(1))}k`;
  }
  return `${Math.round(tokens)}`;
}

function formatWholeTokens(tokens: number): string {
  return Math.round(tokens).toLocaleString("en-US");
}

function formatUsagePercent(percent: number): string {
  const precision = percent >= 10 ? 0 : 1;
  return `${percent.toFixed(precision).replace(/\.0$/, "")}%`;
}

function usageValue(
  usage: ActualTokenUsage,
  key: keyof ActualTokenUsage,
): number {
  const value = usage[key];
  return typeof value === "number" ? value : 0;
}

function cacheHitTokens(
  usage: ActualTokenUsage | null | undefined,
): number {
  if (!usage) {
    return 0;
  }
  return (
    usageValue(usage, "prompt_cache_hit_tokens") +
    usageValue(usage, "prompt_cached_tokens") +
    usageValue(usage, "cache_read_input_tokens")
  );
}

function hasUsage(
  usage: ActualTokenUsage | null | undefined,
): usage is ActualTokenUsage {
  return (
    !!usage &&
    (usage.call_count > 0 ||
      usage.prompt_tokens > 0 ||
      usage.completion_tokens > 0 ||
      usage.total_tokens > 0 ||
      usage.reasoning_tokens > 0 ||
      cacheHitTokens(usage) > 0 ||
      usageValue(usage, "prompt_cache_miss_tokens") > 0 ||
      usageValue(usage, "cache_creation_input_tokens") > 0)
  );
}

function buildBillLabel(
  actualUsage: ActualTokenUsage | null | undefined,
  cumulativeUsage: ActualTokenUsage | null | undefined,
): string {
  const sessionUsage = hasUsage(cumulativeUsage) ? cumulativeUsage : actualUsage;

  return hasUsage(sessionUsage)
    ? formatCompactTokens(sessionUsage.total_tokens)
    : "暂无";
}

function buildUsageLines(label: string, usage: ActualTokenUsage): string[] {
  const lines = [
    `${label}：${formatWholeTokens(usage.total_tokens)} tokens，${formatWholeTokens(usage.call_count)} 次模型调用。`,
    `${label}明细：输入 ${formatWholeTokens(usage.prompt_tokens)}，输出 ${formatWholeTokens(usage.completion_tokens)}，推理 ${formatWholeTokens(usage.reasoning_tokens)}。`,
  ];

  const cacheParts: string[] = [];
  const promptCacheHit = usageValue(usage, "prompt_cache_hit_tokens");
  const promptCacheMiss = usageValue(usage, "prompt_cache_miss_tokens");
  const promptCached = usageValue(usage, "prompt_cached_tokens");
  const cacheCreation = usageValue(usage, "cache_creation_input_tokens");
  const cacheRead = usageValue(usage, "cache_read_input_tokens");

  if (promptCacheHit > 0) {
    cacheParts.push(`缓存命中 ${formatWholeTokens(promptCacheHit)}`);
  }
  if (promptCacheMiss > 0) {
    cacheParts.push(`未命中 ${formatWholeTokens(promptCacheMiss)}`);
  }
  if (promptCached > 0) {
    cacheParts.push(`缓存命中 ${formatWholeTokens(promptCached)}`);
  }
  if (cacheRead > 0) {
    cacheParts.push(`读缓存 ${formatWholeTokens(cacheRead)}`);
  }
  if (cacheCreation > 0) {
    cacheParts.push(`建缓存 ${formatWholeTokens(cacheCreation)}`);
  }
  if (cacheParts.length > 0) {
    lines.push(`${label}缓存：${cacheParts.join("，")}。`);
  }

  return lines;
}

function buildContextBarTitle(ctx: ContextStats, percentLabel: string): string {
  const lines = [
    `上下文占用：${formatWholeTokens(ctx.total_tokens)} / ${formatWholeTokens(ctx.context_limit)} tokens（${percentLabel}）。`,
    `上下文明细：系统 ${formatWholeTokens(ctx.system_tokens)}，工具定义 ${formatWholeTokens(ctx.schema_tokens)}，用户 ${formatWholeTokens(ctx.user_tokens)}，助手 ${formatWholeTokens(ctx.assistant_tokens)}，工具结果 ${formatWholeTokens(ctx.tool_result_tokens)}。`,
    `消息数：${formatWholeTokens(ctx.message_count)}。`,
  ];

  const actualUsage = ctx.actual_usage;
  const cumulativeUsage = ctx.cumulative_usage;
  if (hasUsage(actualUsage)) {
    lines.push(...buildUsageLines("本轮账单", actualUsage));
  } else {
    lines.push("本轮账单：当前模型没有返回 usage 数据。");
  }
  if (hasUsage(cumulativeUsage)) {
    lines.push(...buildUsageLines("会话账单", cumulativeUsage));
  }
  lines.push(
    "账单来自服务商 usage，可能包含不进入上下文窗口的输出、推理和缓存相关 token。",
  );

  return lines.join("\n");
}

export function createChatTranscript(
  deps: TranscriptDeps,
): ChatTranscriptController {
  const { app, client, component, elements, state } = deps;
  let forkHandler: ForkMessageHandler | null = null;

  function repositionDots(): void {
    const dots = Array.from(
      elements.minimapEl.querySelectorAll(".chat-minimap-dot"),
    ) as HTMLDivElement[];
    const count = dots.length;
    if (count === 0) {
      return;
    }

    const dotSize = 10;
    const topPadding = 64;
    const bottomPadding = 24;
    const maxSpacing = 40;
    const minSpacing = 12;

    const available =
      elements.minimapEl.clientHeight - topPadding - bottomPadding;
    const spacing =
      count === 1
        ? 0
        : Math.max(
            minSpacing,
            Math.min(maxSpacing, (available - dotSize) / (count - 1)),
          );

    const totalUsed = dotSize + (count - 1) * spacing;
    const startY = topPadding + Math.max(0, (available - totalUsed) / 2);

    dots.forEach((dot, index) => {
      dot.style.top = `${startY + index * spacing}px`;
    });
  }

  function scrollToBottom(force = false): void {
    if (force) {
      requestAnimationFrame(() => {
        elements.messagesEl.scrollTop = elements.messagesEl.scrollHeight;
      });
      return;
    }

    const { scrollTop, scrollHeight, clientHeight } = elements.messagesEl;
    if (scrollHeight - scrollTop - clientHeight < 150) {
      elements.messagesEl.scrollTop = scrollHeight;
    }
  }

  function renderCompletedToolBlock(
    wrapper: HTMLDivElement,
    name: string,
    output: string,
  ): void {
    wrapper.classList.remove("running");
    wrapper.classList.add("done");

    const header = wrapper.querySelector(".chat-tool-header") as HTMLElement;
    if (header) {
      header.empty();

      const iconEl = header.createSpan({ cls: "chat-tool-icon" });
      iconEl.setText("✅");

      const nameEl = header.createSpan({ cls: "chat-tool-name" });
      nameEl.setText(name);

      const firstLine = getFirstNonEmptyLine(output);
      if (firstLine) {
        const preview = header.createSpan({ cls: "chat-tool-preview" });
        preview.setText(
          firstLine.slice(0, 72) + (firstLine.length > 72 ? "…" : ""),
        );
      }

      const chevron = header.createSpan({
        cls: "chat-tool-chevron",
        text: "▾",
      });

      header.addEventListener("click", () => {
        wrapper.classList.toggle("expanded", !wrapper.classList.contains("expanded"));
        chevron.setText(wrapper.classList.contains("expanded") ? "▴" : "▾");
      });
    }

    const terminal = wrapper.querySelector(".chat-tool-terminal") as HTMLElement;
    if (terminal) {
      terminal.empty();
      terminal.setText(output || "(no output)");
    }
  }

  function appendMessage(
    role: ChatRole,
    content: string,
    forceScroll = true,
    attachments: MessageAttachment[] = [],
    messageId?: string | null,
  ): void {
    state.messages.push({ role, content, attachments, messageId });
    const msgEl = elements.messagesEl.createDiv({ cls: `chat-msg ${role}` });
    if (messageId) {
      msgEl.dataset.messageId = messageId;
    }

    if (role === "user") {
      const dot = elements.minimapEl.createDiv({ cls: "chat-minimap-dot" });
      dot.setAttribute("title", content.slice(0, 30));
      dot.addEventListener("click", () => {
        msgEl.scrollIntoView({ behavior: "smooth", block: "start" });
      });

      state.userMsgRefs.push({ dot, msgEl });
      repositionDots();

      const bubble = msgEl.createDiv({ cls: "chat-msg-bubble" });
      renderUserAttachments(bubble, attachments);
      if (content) {
        const textEl = bubble.createDiv({ cls: "chat-msg-text" });
        textEl.setText(content);
      }
    } else if (role === "assistant" && content) {
      renderAssistantMessage(msgEl, content, messageId);
    } else if (content) {
      msgEl.setText(content);
    }

    scrollToBottom(forceScroll);
  }

  function renderAssistantMessage(
    targetEl: HTMLElement,
    content: string,
    messageId?: string | null,
  ): void {
    targetEl.empty();
    if (messageId) {
      targetEl.dataset.messageId = messageId;
    }

    const shell = targetEl.createDiv({ cls: "chat-assistant-shell" });
    const header = createAssistantIdentityHeader(shell);
    if (messageId && forkHandler) {
      renderForkAction(header, messageId, content, "assistant");
    }

    const contentEl = shell.createDiv({ cls: "chat-assistant-content" });
    renderAssistantMessageContent(app, component, contentEl, content);
  }

  function updateLastUserMessageId(messageId?: string | null): boolean {
    if (!messageId) {
      return false;
    }

    let messageIndex = -1;
    for (let index = state.messages.length - 1; index >= 0; index -= 1) {
      if (state.messages[index].role === "user") {
        messageIndex = index;
        break;
      }
    }
    if (messageIndex < 0) {
      return false;
    }

    state.messages[messageIndex].messageId = messageId;

    const userRef = state.userMsgRefs[state.userMsgRefs.length - 1];
    if (!userRef) {
      return false;
    }

    userRef.msgEl.dataset.messageId = messageId;
    return true;
  }

  function renderForkAction(
    container: HTMLElement,
    messageId: string,
    content: string,
    role: ChatRole,
  ): void {
    for (const child of Array.from(container.children)) {
      if (child.classList.contains("chat-msg-action-row")) {
        child.remove();
      }
    }

    const actions = container.createDiv({ cls: "chat-msg-action-row" });
    const button = actions.createEl("button", {
      cls: "chat-msg-fork-btn",
      attr: {
        type: "button",
        "aria-label": "从此消息分叉",
        title: "从此消息分叉",
      },
    });
    button.innerHTML = ICON_FORK;
    setTooltip(button, "从此消息分叉", {
      placement: "top",
      delay: 120,
    });
    button.addEventListener("click", (evt) => {
      evt.preventDefault();
      evt.stopPropagation();
      void forkHandler?.({ messageId, content, role });
    });

    if (
      !container.classList.contains("chat-assistant-header") &&
      container.firstElementChild !== actions
    ) {
      container.insertBefore(actions, container.firstChild);
    }
  }

  function renderUserAttachments(
    bubble: HTMLDivElement,
    attachments: MessageAttachment[],
  ): void {
    if (attachments.length === 0) {
      return;
    }

    const imageAttachments = attachments.filter(
      (attachment) => attachment.type === "image",
    );
    if (imageAttachments.length > 0) {
      const imageGrid = bubble.createDiv({ cls: "chat-msg-images" });
      for (const attachment of imageAttachments) {
        const src =
          attachment.preview_url ??
          (attachment.attachment_id
            ? client.getAttachmentUrl(attachment.attachment_id)
            : "");
        if (!src) {
          continue;
        }
        imageGrid.createEl("img", {
          cls: "chat-msg-image",
          attr: {
            src,
            alt: attachment.filename ?? "image",
            loading: "lazy",
          },
        });
      }
    }

    const nonImageAttachments = attachments.filter(
      (attachment) => attachment.type !== "image",
    );
    if (nonImageAttachments.length === 0) {
      return;
    }

    const chipRow = bubble.createDiv({ cls: "chat-msg-attachment-row" });
    for (const attachment of nonImageAttachments) {
      const chip = chipRow.createDiv({ cls: "chat-msg-attachment" });
      const label =
        attachment.type === "vault_directory"
          ? `@${attachment.path}/`
          : `@${attachment.path}`;
      chip.setText(label);
    }
  }

  function beginTool(name: string, id: string): void {
    const wrapper = elements.messagesEl.createDiv({
      cls: "chat-tool-block running",
    });

    const header = wrapper.createDiv({ cls: "chat-tool-header" });
    const iconEl = header.createSpan({ cls: "chat-tool-icon" });
    iconEl.setText(getToolIcon(name));

    const nameEl = header.createSpan({ cls: "chat-tool-name" });
    nameEl.setText(name);
    header.createDiv({ cls: "chat-tool-spinner" });

    const termEl = wrapper.createDiv({ cls: "chat-tool-terminal" });
    termEl.createSpan({ cls: "chat-tool-cursor", text: "█" });

    if (id) {
      state.toolBlocks.set(id, wrapper);
      state.toolIdToName.set(id, name);
    }
    state.toolBlocks.set(name, wrapper);

    scrollToBottom(false);
  }

  function completeTool(name: string, output: string): void {
    let wrapper: HTMLDivElement | undefined;

    if (state.toolBlocks.has(name)) {
      wrapper = state.toolBlocks.get(name);
      state.toolBlocks.delete(name);

      for (const [id, mappedName] of state.toolIdToName) {
        if (mappedName === name) {
          state.toolBlocks.delete(id);
          state.toolIdToName.delete(id);
          break;
        }
      }
    }

    if (!wrapper) {
      for (const [id, mappedName] of state.toolIdToName) {
        if (mappedName === name) {
          wrapper = state.toolBlocks.get(id);
          state.toolBlocks.delete(id);
          state.toolIdToName.delete(id);
          state.toolBlocks.delete(name);
          break;
        }
      }
    }

    if (!wrapper) {
      const blocks = elements.messagesEl.querySelectorAll(
        ".chat-tool-block.running",
      );
      if (blocks.length) {
        wrapper = blocks[blocks.length - 1] as HTMLDivElement;
      }
    }

    if (wrapper) {
      renderCompletedToolBlock(wrapper, name, output);
    } else {
      const fallback = elements.messagesEl.createDiv({ cls: "chat-msg status" });
      fallback.setText(`✅ ${name} 完成`);
    }

    scrollToBottom(false);
  }

  function renderHistoricalTool(name: string, output: string): void {
    const wrapper = elements.messagesEl.createDiv({
      cls: "chat-tool-block done",
    });
    wrapper.createDiv({ cls: "chat-tool-header" });
    wrapper.createDiv({ cls: "chat-tool-terminal" });
    renderCompletedToolBlock(wrapper, name, output);
    scrollToBottom(false);
  }

  function clearToolTracking(): void {
    state.toolBlocks.clear();
    state.toolIdToName.clear();
  }

  function removeTransientUi(): void {
    elements.messagesEl
      .querySelectorAll(".chat-msg.status, .chat-tool-block.running")
      .forEach((el) => el.remove());
  }

  function clearConversationUi(): void {
    state.messages = [];
    state.userMsgRefs = [];
    clearToolTracking();

    elements.messagesEl.empty();
    resetContextBar();
    elements.minimapEl
      .querySelectorAll(".chat-minimap-dot")
      .forEach((dot) => dot.remove());
  }

  function resetContextBar(): void {
    const title = "上下文统计会在下一次模型响应完成后更新。";
    elements.contextBarEl.style.display = "flex";
    elements.contextBarEl.removeAttribute("title");
    elements.contextBarEl.setAttribute("aria-label", title);
    setTooltip(elements.contextBarEl, title, {
      placement: "top",
      delay: 120,
      classes: ["life-context-tooltip"],
    });
    elements.contextBarEl.empty();

    elements.contextBarEl.createSpan({
      cls: "context-meter-label",
      text: "上下文",
    });

    const ring = elements.contextBarEl.createDiv({
      cls: "context-ring",
      attr: { "aria-hidden": "true" },
    });
    ring.style.setProperty("--context-progress", "0%");
    ring.style.setProperty("--context-color", "var(--text-muted)");

    const label = elements.contextBarEl.createSpan({
      cls: "context-percent-label",
    });
    label.style.color = "var(--text-muted)";
    label.setText("0%");

    elements.contextBarEl.createSpan({
      cls: "context-separator",
      text: "·",
    });
    elements.contextBarEl.createSpan({
      cls: "context-bill-label",
      text: "会话 暂无",
    });
  }

  function updateContextBar(ctx: ContextStats): void {
    elements.contextBarEl.style.display = "flex";
    const pct = ctx.usage_percent;
    const pctLabel = formatUsagePercent(pct);
    const boundedPct = Math.max(0, Math.min(pct, 100));
    const actualUsage = ctx.actual_usage;
    const cumulativeUsage = ctx.cumulative_usage;
    const billLabel = buildBillLabel(actualUsage, cumulativeUsage);

    let color = "var(--text-success)";
    if (pct > 80) {
      color = "var(--text-error)";
    } else if (pct > 50) {
      color = "var(--text-warning, #e0a030)";
    }

    const title = buildContextBarTitle(ctx, pctLabel);
    elements.contextBarEl.removeAttribute("title");
    elements.contextBarEl.setAttribute("aria-label", title);
    setTooltip(elements.contextBarEl, title, {
      placement: "top",
      delay: 120,
      classes: ["life-context-tooltip"],
    });
    elements.contextBarEl.empty();

    elements.contextBarEl.createSpan({
      cls: "context-meter-label",
      text: "上下文",
    });

    const ring = elements.contextBarEl.createDiv({
      cls: "context-ring",
      attr: { "aria-hidden": "true" },
    });
    ring.style.setProperty("--context-progress", `${boundedPct}%`);
    ring.style.setProperty("--context-color", color);

    const label = elements.contextBarEl.createSpan({
      cls: "context-percent-label",
    });
    label.style.color = color;
    label.setText(pctLabel);

    elements.contextBarEl.createSpan({
      cls: "context-separator",
      text: "·",
    });
    elements.contextBarEl.createSpan({
      cls: "context-bill-label",
      text: `会话 ${billLabel}`,
    });
  }

  function setForkHandler(handler: ForkMessageHandler | null): void {
    forkHandler = handler;
  }

  resetContextBar();

  return {
    appendMessage,
    renderAssistantMessage,
    beginTool,
    completeTool,
    renderHistoricalTool,
    clearConversationUi,
    clearToolTracking,
    removeTransientUi,
    scrollToBottom,
    updateContextBar,
    updateLastUserMessageId,
    setForkHandler,
  };
}
