import type { SessionMessage, TranscriptEntry } from "./types";

function stringifyToolContent(content: unknown): string {
  if (typeof content === "string") {
    return content;
  }
  return JSON.stringify(content ?? "", null, 2);
}

function extractUserText(message: SessionMessage): string {
  if (typeof message.text === "string") {
    return message.text;
  }
  if (typeof message.content === "string") {
    return message.content;
  }
  if (!Array.isArray(message.content)) {
    return "";
  }
  return message.content
    .filter(
      (block): block is { type?: string; text?: string } =>
        typeof block === "object" && block !== null,
    )
    .filter((block) => block.type === "text" && typeof block.text === "string")
    .map((block) => block.text ?? "")
    .join("\n");
}

function isToolResultOnly(message: SessionMessage): boolean {
  if (!Array.isArray(message.content) || message.content.length === 0) {
    return false;
  }
  return message.content.every(
    (block) =>
      typeof block === "object" &&
      block !== null &&
      "type" in block &&
      (block as { type?: string }).type === "tool_result",
  );
}

export function restoreTranscriptFromSessionMessages(
  messages: SessionMessage[],
): TranscriptEntry[] {
  const restored: TranscriptEntry[] = [];
  const toolResults = new Map<string, string>();

  for (const message of messages) {
    if (message.role !== "user" || !Array.isArray(message.content)) {
      continue;
    }
    for (const block of message.content) {
      if (
        typeof block === "object" &&
        block !== null &&
        (block as { type?: string }).type === "tool_result"
      ) {
        const typedBlock = block as {
          tool_use_id?: string;
          content?: unknown;
        };
        if (typedBlock.tool_use_id) {
          toolResults.set(
            typedBlock.tool_use_id,
            stringifyToolContent(typedBlock.content),
          );
        }
      }
    }
  }

  let counter = 0;
  for (const message of messages) {
    if (message.role === "user" && !isToolResultOnly(message)) {
      const text = extractUserText(message);
      if (text || (message.attachments?.length ?? 0) > 0) {
        restored.push({
          id: `restored-${counter += 1}`,
          kind: "message",
          role: "user",
          text,
          attachments: message.attachments ?? [],
        });
      }
      continue;
    }

    if (message.role !== "assistant") {
      continue;
    }

    if (typeof message.content === "string" && message.content) {
      restored.push({
        id: `restored-${counter += 1}`,
        kind: "message",
        role: "assistant",
        text: message.content,
      });
      continue;
    }

    if (!Array.isArray(message.content)) {
      continue;
    }

    for (const block of message.content) {
      if (typeof block !== "object" || block === null) {
        continue;
      }
      const typedBlock = block as {
        id?: string;
        type?: string;
        text?: string;
        name?: string;
      };

      if (typedBlock.type === "text" && typedBlock.text) {
        restored.push({
          id: `restored-${counter += 1}`,
          kind: "message",
          role: "assistant",
          text: typedBlock.text,
        });
      }

      if (typedBlock.type === "tool_use" && typedBlock.name) {
        restored.push({
          id: `restored-${counter += 1}`,
          kind: "tool",
          name: typedBlock.name,
          output: toolResults.get(typedBlock.id ?? "") ?? "(no output)",
          status: "done",
        });
      }
    }
  }

  return restored;
}
