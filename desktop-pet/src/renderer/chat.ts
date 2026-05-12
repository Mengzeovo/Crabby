import DOMPurify from "dompurify";
import { marked } from "marked";

import type {
  ConversationSnapshot,
  MessageAttachment,
  TranscriptEntry,
} from "../shared/types";

marked.setOptions({
  breaks: true,
  gfm: true,
});

const titleEl = document.getElementById("chatTitle") as HTMLHeadingElement;
const connectionBadge = document.getElementById("connectionBadge") as HTMLDivElement;
const transcriptEl = document.getElementById("transcript") as HTMLDivElement;
const contextMeter = document.getElementById("contextMeter") as HTMLDivElement;
const inputEl = document.getElementById("chatInput") as HTMLTextAreaElement;
const sendButton = document.getElementById("sendButton") as HTMLButtonElement;

let latestSnapshot: ConversationSnapshot | null = null;

function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { async: false }) as string);
}

function createAttachmentRow(attachments: MessageAttachment[]): HTMLDivElement {
  const row = document.createElement("div");
  row.className = "attachment-row";
  for (const attachment of attachments) {
    const chip = document.createElement("span");
    chip.className = "attachment-chip";
    chip.textContent = attachment.path ?? attachment.filename ?? attachment.type;
    row.appendChild(chip);
  }
  return row;
}

function renderMessageEntry(entry: Extract<TranscriptEntry, { kind: "message" }>): HTMLElement {
  const wrapper = document.createElement("article");
  wrapper.className = `entry message ${entry.role}`;

  const bubble = document.createElement("div");
  bubble.className = `bubble ${entry.role}`;

  if (entry.role === "assistant") {
    const markdown = document.createElement("div");
    markdown.className = "markdown-body";
    markdown.innerHTML = renderMarkdown(entry.text || "_..._");
    bubble.appendChild(markdown);
  } else {
    const plain = document.createElement("div");
    plain.className = "plain-text";
    plain.textContent = entry.text;
    bubble.appendChild(plain);
  }

  if (entry.attachments?.length) {
    bubble.appendChild(createAttachmentRow(entry.attachments));
  }

  wrapper.appendChild(bubble);
  return wrapper;
}

function renderToolEntry(entry: Extract<TranscriptEntry, { kind: "tool" }>): HTMLElement {
  const card = document.createElement("details");
  card.className = "entry tool-card";
  card.open = entry.status === "running";

  const summary = document.createElement("summary");
  const label = document.createElement("span");
  label.textContent = entry.name;
  const status = document.createElement("span");
  status.textContent = entry.status === "running" ? "Running" : "Done";
  summary.append(label, status);

  const output = document.createElement("pre");
  output.className = "tool-output";
  output.textContent = entry.output || (entry.status === "running" ? "Working..." : "(no output)");

  card.append(summary, output);
  return card;
}

function renderTranscript(snapshot: ConversationSnapshot): void {
  const shouldStick =
    transcriptEl.scrollHeight - transcriptEl.scrollTop - transcriptEl.clientHeight < 120;

  transcriptEl.innerHTML = "";

  if (snapshot.entries.length === 0) {
    const empty = document.createElement("article");
    empty.className = "entry message status";
    const bubble = document.createElement("div");
    bubble.className = "bubble status";
    bubble.textContent =
      "The desktop pet opens a full transcript here, including tool progress and auto-continued replies.";
    empty.appendChild(bubble);
    transcriptEl.appendChild(empty);
  }

  for (const entry of snapshot.entries) {
    const element =
      entry.kind === "tool" ? renderToolEntry(entry) : renderMessageEntry(entry);
    transcriptEl.appendChild(element);
  }

  if (shouldStick || snapshot.isStreaming) {
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
  }
}

function renderConnection(snapshot: ConversationSnapshot): void {
  connectionBadge.textContent = snapshot.isStreaming
    ? "Streaming"
    : snapshot.connectionState;
  connectionBadge.style.color =
    snapshot.connectionState === "error" ? "#cf4f34" : "#ff6f3d";
  connectionBadge.style.background =
    snapshot.connectionState === "error"
      ? "rgba(207, 79, 52, 0.15)"
      : "rgba(255, 111, 61, 0.14)";
}

function renderContext(snapshot: ConversationSnapshot): void {
  if (!snapshot.lastContext) {
    contextMeter.hidden = true;
    return;
  }
  contextMeter.hidden = false;
  const actualUsage = snapshot.lastContext.actual_usage;
  const actualText =
    actualUsage && actualUsage.call_count > 0
      ? ` | turn ${(actualUsage.total_tokens / 1000).toFixed(1)}k real`
      : "";
  contextMeter.textContent = `${(snapshot.lastContext.total_tokens / 1000).toFixed(1)}k / ${(
    snapshot.lastContext.context_limit / 1000
  ).toFixed(0)}k (${snapshot.lastContext.usage_percent}%)${actualText}`;
}

function renderSnapshot(snapshot: ConversationSnapshot): void {
  latestSnapshot = snapshot;
  titleEl.textContent = snapshot.title || "New chat";
  renderConnection(snapshot);
  renderTranscript(snapshot);
  renderContext(snapshot);
  inputEl.disabled = snapshot.isStreaming;
  sendButton.textContent = snapshot.isStreaming ? "Stop" : "Send";
}

function autoResize(): void {
  inputEl.style.height = "0px";
  inputEl.style.height = `${Math.min(180, inputEl.scrollHeight)}px`;
}

async function handleSubmit(): Promise<void> {
  if (latestSnapshot?.isStreaming) {
    await window.desktopPet.abortChat();
    return;
  }

  const content = inputEl.value.trim();
  if (!content) {
    return;
  }
  inputEl.value = "";
  autoResize();
  await window.desktopPet.sendChatMessage(content);
}

sendButton.addEventListener("click", () => {
  void handleSubmit();
});

inputEl.addEventListener("input", autoResize);
inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void handleSubmit();
  }
});

window.addEventListener("focus", () => {
  void window.desktopPet.markChatSeen();
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    void window.desktopPet.markChatSeen();
  }
});

window.desktopPet.subscribeConversationSnapshot(renderSnapshot);

void (async () => {
  renderSnapshot(await window.desktopPet.getConversationSnapshot());
  await window.desktopPet.markChatSeen();
  inputEl.focus();
  autoResize();
})();
