import { Notice } from "obsidian";

import {
  shouldFallbackToRest,
  type SystemNotificationEvent,
  type ToolCallPayload,
} from "../api/client";
import {
  buildAssistantContent,
  createStreamingAssistantContentRenderer,
  type StreamingAssistantContentRenderer,
} from "./chatAssistantContent";
import { ICON_SEND, ICON_STOP } from "./chatIcons";
import type {
  ChatComposerSubmitPayload,
  ChatTurnRunnerController,
  TurnRunnerDeps,
} from "./chatTypes";

const AUTO_TRIGGER_MESSAGE =
  "（系统通知：上次投递到后台的任务刚刚完成，请直接根据新注入的 <task_notification> 上下文继续回复我。）";

export function createChatTurnRunner(
  deps: TurnRunnerDeps,
): ChatTurnRunnerController {
  const {
    client,
    composer,
    elements,
    state,
    transcript,
    sessions,
    persona,
    plugin,
    diaryPrompt,
  } = deps;

  function setSendingUi(isSending: boolean): void {
    elements.inputEl.disabled = isSending;
    elements.attachmentBtn.disabled = isSending;
    if (isSending) {
      elements.sendBtn.classList.add("is-stop");
      elements.sendBtn.innerHTML = ICON_STOP;
      elements.sendBtn.setAttribute("aria-label", "停止");
      return;
    }

    elements.sendBtn.classList.remove("is-stop");
    elements.sendBtn.innerHTML = ICON_SEND;
    elements.sendBtn.setAttribute("aria-label", "发送");
  }

  async function handleSendRest(
    payload: ChatComposerSubmitPayload,
    backfillUserMessageId: boolean,
  ): Promise<void> {
    const typingEl = elements.messagesEl.createDiv({ cls: "chat-msg assistant" });
    typingEl.setText("思考中...");
    transcript.scrollToBottom();

    try {
      const resp = await client.chat(payload.request);
      typingEl.remove();
      resp.warnings?.forEach((warning) => transcript.appendMessage("status", warning));
      persona.setPersonaState(resp.persona_state);
      if (backfillUserMessageId) {
        transcript.updateLastUserMessageId(resp.user_message_id ?? undefined);
      }
      resp.tool_calls?.forEach((toolCall) => {
        transcript.renderHistoricalTool(toolCall);
      });
      const loopStopResult = findLoopStopResult(resp.tool_calls ?? []);
      transcript.appendMessage(
        "assistant",
        resp.reply,
        true,
        [],
        resp.message_id ?? undefined,
      );
      if (resp.context) {
        transcript.updateContextBar(resp.context);
      }
      await sessions.syncCurrentSessionTitle(resp.session_id);
      if (loopStopResult) {
        diaryPrompt.showLoopStopResult(
          loopStopResult,
          resp.session_id,
          resp.conversation_id,
        );
      }
    } catch (err) {
      typingEl.remove();
      const errMsg = err instanceof Error ? err.message : String(err);
      transcript.appendMessage(
        "assistant",
        `❌ 连接出错: ${errMsg}\n\n请检查后端是否可访问，或查看后端日志。`,
      );
    }
  }

  async function handleSend(overrideText?: string): Promise<void> {
    const payload = overrideText
      ? {
          request: {
            content: overrideText,
            persona_mode: state.personaState.mode,
            manual_persona_id: state.personaState.manual_persona_id,
          },
          displayText: overrideText,
          displayAttachments: [],
        }
      : (() => {
          const nextPayload = composer.getSubmitPayload();
          if (!nextPayload) {
            return null;
          }
          nextPayload.request.persona_mode = state.personaState.mode;
          nextPayload.request.manual_persona_id =
            state.personaState.manual_persona_id;
          return nextPayload;
        })();
    if (!payload || state.isSending) {
      return;
    }
    diaryPrompt.hide();
    const backfillUserMessageId = !overrideText;

    const profileApply = await plugin.applyLlmProfile();
    if (!profileApply.ok) {
      transcript.appendMessage(
        "assistant",
        `❌ ${profileApply.message}\n\n请在设置中配置 LLM 后再试。`,
      );
      return;
    }

    const vaultSync = await plugin.ensureBackendVaultPathSynced(client);
    if (!vaultSync.ok) {
      transcript.appendMessage(
        "status",
        `Warning: failed to sync the current vault path before sending. ${vaultSync.message}`,
        false,
      );
    }

    state.isSending = true;
    state.isAborted = false;
    setSendingUi(true);

    if (!overrideText) {
      composer.clear();
    }

    if (overrideText) {
      transcript.appendMessage(
        "status",
        "[系统代理自动触发：检查系统通知]",
      );
    } else {
      transcript.appendMessage(
        "user",
        payload.displayText,
        true,
        payload.displayAttachments,
      );
    }

    let msgEl: HTMLDivElement | null = null;
    let accumulated = "";
    let reasoningAccumulated = "";
    let fullAccumulated = "";
    let streamingRenderer: StreamingAssistantContentRenderer | null = null;
    let streamingRenderFrame: number | null = null;
    let loopStopResult: ToolCallPayload | null = null;

    const buildCurrentAssistantContent = (): string =>
      buildAssistantContent(reasoningAccumulated, accumulated);

    const renderStreamingMessageNow = (): void => {
      const content = buildCurrentAssistantContent();
      fullAccumulated = content;
      if (!content && !msgEl) {
        return;
      }

      if (!msgEl) {
        msgEl = elements.messagesEl.createDiv({
          cls: "chat-msg assistant streaming",
        });
      }

      const reasoning = reasoningAccumulated.trim();
      if (!streamingRenderer) {
        streamingRenderer = createStreamingAssistantContentRenderer(msgEl);
      }
      streamingRenderer.render(accumulated, reasoning);
      transcript.scrollToBottom(false);
    };

    const renderStreamingMessage = (): void => {
      fullAccumulated = buildCurrentAssistantContent();
      if (streamingRenderFrame !== null) {
        return;
      }
      streamingRenderFrame = requestAnimationFrame(() => {
        streamingRenderFrame = null;
        renderStreamingMessageNow();
      });
    };

    const flushStreamingMessage = (): void => {
      if (streamingRenderFrame !== null) {
        cancelAnimationFrame(streamingRenderFrame);
        streamingRenderFrame = null;
      }
      renderStreamingMessageNow();
    };

    const cancelStreamingMessageRender = (): void => {
      if (streamingRenderFrame !== null) {
        cancelAnimationFrame(streamingRenderFrame);
        streamingRenderFrame = null;
      }
    };

    try {
      await client.streamChat(payload.request, {
        onAssistantPrefix: (prefix: string) => {
          accumulated += prefix;
          renderStreamingMessage();
        },

        onReasoningDelta: (delta: string) => {
          reasoningAccumulated += delta;
          renderStreamingMessage();
        },

        onTextDelta: (delta: string) => {
          accumulated += delta;
          renderStreamingMessage();
        },

        onToolStart: (name: string, id: string) => {
          if (msgEl || buildCurrentAssistantContent().trim()) {
            flushStreamingMessage();
          }
          const assistantContent = buildCurrentAssistantContent();
          if (msgEl && assistantContent.trim()) {
            const keepThoughtExpanded = isThoughtBlockExpanded(msgEl);
            msgEl.empty();
            msgEl.classList.remove("streaming");
            transcript.renderAssistantMessage(msgEl, assistantContent);
            restoreThoughtBlockExpanded(msgEl, keepThoughtExpanded);
          } else if (msgEl) {
            msgEl.remove();
          }

          accumulated = "";
          reasoningAccumulated = "";
          fullAccumulated = "";
          streamingRenderer = null;
          msgEl = null;
          transcript.beginTool(name, id);
        },

        onToolResult: (payload: ToolCallPayload) => {
          transcript.completeTool(payload);
          if (isLoopStopResult(payload)) {
            loopStopResult = payload;
          }
        },

        onWarning: (message: string) => {
          transcript.appendMessage("status", message, false);
        },

        onDone: async (
          sessionId,
          conversationId,
          assistantMessageId,
          userMessageId,
          context,
          personaState,
        ) => {
          if (state.isAborted) {
            return;
          }

          if (backfillUserMessageId) {
            transcript.updateLastUserMessageId(userMessageId);
          }
          if (msgEl || buildCurrentAssistantContent().trim()) {
            flushStreamingMessage();
          }
          if (msgEl) {
            msgEl.classList.remove("streaming");
            const assistantContent = buildCurrentAssistantContent();
            if (assistantContent.trim()) {
              const keepThoughtExpanded = isThoughtBlockExpanded(msgEl);
              msgEl.empty();
              transcript.renderAssistantMessage(
                msgEl,
                assistantContent,
                assistantMessageId,
              );
              restoreThoughtBlockExpanded(msgEl, keepThoughtExpanded);
              streamingRenderer = null;
            } else if (!msgEl.childNodes.length) {
              msgEl.remove();
            }
          }

          state.messages.push({
            role: "assistant",
            content: fullAccumulated,
            messageId: assistantMessageId,
          });

          if (context) {
            transcript.updateContextBar(context);
          }
          if (personaState) {
            persona.setPersonaState(personaState);
          }

          if (loopStopResult) {
            diaryPrompt.showLoopStopResult(
              loopStopResult,
              sessionId,
              conversationId,
            );
            loopStopResult = null;
          }
          await sessions.syncCurrentSessionTitle(sessionId);
        },

        onError: (payload: { message: string; code: string }) => {
          const message = payload.message;
          if (state.isAborted) {
            return;
          }

          if (msgEl || buildCurrentAssistantContent().trim()) {
            flushStreamingMessage();
          }
          if (msgEl && !buildCurrentAssistantContent()) {
            msgEl.remove();
          }

          transcript.appendMessage(
            "assistant",
            `❌ 出错: ${message}\n\n请检查后端是否可访问，或查看后端日志。`,
          );
        },
      });
    } catch (err) {
      if (!state.isAborted) {
        if (msgEl || buildCurrentAssistantContent().trim()) {
          flushStreamingMessage();
        }
        const currentMsgEl = msgEl as HTMLDivElement | null;
        if (currentMsgEl) {
          const assistantContent = buildCurrentAssistantContent();
          if (assistantContent.trim()) {
            const keepThoughtExpanded = isThoughtBlockExpanded(currentMsgEl);
            currentMsgEl.classList.remove("streaming");
            currentMsgEl.empty();
            transcript.renderAssistantMessage(currentMsgEl, assistantContent);
            restoreThoughtBlockExpanded(currentMsgEl, keepThoughtExpanded);
            streamingRenderer = null;
          } else {
            currentMsgEl.remove();
          }
        }
        transcript.removeTransientUi();
        transcript.clearToolTracking();
        if (shouldFallbackToRest(err)) {
          await handleSendRest(payload, backfillUserMessageId);
        }
      }
    } finally {
      if (state.isAborted) {
        if (msgEl || buildCurrentAssistantContent().trim()) {
          flushStreamingMessage();
        }
        const currentMsgEl = msgEl as HTMLDivElement | null;
        if (currentMsgEl) {
          currentMsgEl.classList.remove("streaming");
          if (buildCurrentAssistantContent()) {
            const hint = document.createElement("span");
            hint.className = "abort-hint";
            hint.textContent = " [已中止]";
            currentMsgEl.appendChild(hint);
          } else {
            currentMsgEl.remove();
          }
        }

        if (fullAccumulated) {
          state.messages.push({
            role: "assistant",
            content: fullAccumulated,
          });
        }

        transcript.removeTransientUi();
        transcript.clearToolTracking();
      }

      cancelStreamingMessageRender();
      state.isAborted = false;
      state.isSending = false;
      setSendingUi(false);
    }
  }

  function handleStop(): void {
    state.isAborted = true;
    void client.abort();
  }

  function handleSysNotify(event: SystemNotificationEvent): void {
    transcript.appendMessage("status", event.message);
    new Notice("后台任务有新的完成通知。");

    if (event.autoTrigger && !state.isSending) {
      void handleSend(AUTO_TRIGGER_MESSAGE);
    }
  }

  return {
    handleSend,
    handleStop,
    handleSysNotify,
  };
}

function isThoughtBlockExpanded(container: HTMLElement): boolean {
  return Boolean(container.querySelector(".chat-thought-block.expanded"));
}

function restoreThoughtBlockExpanded(
  container: HTMLElement,
  expanded: boolean,
): void {
  if (!expanded) {
    return;
  }

  const block = container.querySelector(".chat-thought-block") as HTMLElement | null;
  const header = container.querySelector(".chat-thought-header") as HTMLElement | null;
  const chevron = container.querySelector(
    ".chat-thought-chevron",
  ) as HTMLElement | null;
  block?.classList.add("expanded");
  header?.setAttribute("aria-expanded", "true");
  if (chevron) {
    chevron.setText("v");
  }
}

function findLoopStopResult(payloads: ToolCallPayload[]): ToolCallPayload | null {
  for (let index = payloads.length - 1; index >= 0; index -= 1) {
    const payload = payloads[index];
    if (isLoopStopResult(payload)) {
      return payload;
    }
  }
  return null;
}

function isLoopStopResult(payload: ToolCallPayload): boolean {
  const name = payload.name || payload.tool || "";
  const jobId = payload.metadata?.job_id;
  return (
    name === "loop_stop" &&
    !payload.is_error &&
    payload.status !== "error" &&
    typeof jobId === "string" &&
    jobId.trim().length > 0
  );
}
