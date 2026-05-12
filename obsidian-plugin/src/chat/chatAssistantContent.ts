import { MarkdownRenderer, type App, type Component } from "obsidian";

const THINK_OPEN = "<think>";
const THINK_CLOSE = "</think>";
const THINKING_OPEN = "<thinking>";
const THINKING_CLOSE = "</thinking>";
const THINK_JSON_OPEN = "<think-json>";
const THINK_JSON_CLOSE = "</think-json>";
export const ASSISTANT_DISPLAY_NAME = "Crabby";

type ThoughtTag = {
  open: string;
  close: string;
  encoded?: boolean;
  allowNested?: boolean;
};

type ThoughtTagMatch = {
  tag: ThoughtTag;
  openIndex: number;
};

const THOUGHT_TAGS: ThoughtTag[] = [
  { open: THINK_JSON_OPEN, close: THINK_JSON_CLOSE, encoded: true },
  { open: THINK_OPEN, close: THINK_CLOSE, allowNested: true },
  { open: THINKING_OPEN, close: THINKING_CLOSE, allowNested: true },
];

type ParsedAssistantContent = {
  visibleMarkdown: string;
  thoughtText: string;
};

export type StreamingAssistantContentRenderer = {
  render: (visibleText: string, thoughtText: string) => void;
};

export function createAssistantIdentityHeader(
  container: HTMLElement,
): HTMLElement {
  const header = container.createDiv({ cls: "chat-assistant-header" });
  header.createSpan({
    cls: "chat-assistant-name",
    text: ASSISTANT_DISPLAY_NAME,
  });
  return header;
}

export function renderAssistantMessageContent(
  app: App,
  component: Component,
  container: HTMLElement,
  content: string,
): void {
  container.empty();

  const parsed = parseAssistantContent(content);
  if (parsed.thoughtText) {
    createThoughtBlock(container, parsed.thoughtText);
  }

  if (parsed.visibleMarkdown.trim()) {
    const markdownEl = container.createDiv({ cls: "chat-assistant-markdown" });
    void MarkdownRenderer.render(app, parsed.visibleMarkdown, markdownEl, "", component);
  }
}

export function createStreamingAssistantContentRenderer(
  container: HTMLElement,
): StreamingAssistantContentRenderer {
  container.empty();

  const shell = container.createDiv({ cls: "chat-assistant-shell" });
  createAssistantIdentityHeader(shell);
  const contentEl = shell.createDiv({ cls: "chat-assistant-content" });

  let thoughtBlock: ThoughtBlockRefs | null = null;
  let visibleEl: HTMLDivElement | null = null;

  return {
    render(visibleText: string, thoughtText: string): void {
      const thought = thoughtText.trim();
      if (thought) {
        if (!thoughtBlock) {
          thoughtBlock = createThoughtBlock(contentEl, thought, {
            streaming: true,
          });
        } else {
          thoughtBlock.updateThoughtText(thought);
        }
      }

      if (visibleText) {
        if (!visibleEl) {
          visibleEl = contentEl.createDiv({
            cls: "chat-assistant-markdown chat-assistant-streaming-text",
          });
        }
        visibleEl.setText(visibleText);
      } else if (visibleEl) {
        visibleEl.remove();
        visibleEl = null;
      }
    },
  };
}

export function buildAssistantContent(
  reasoningText: string,
  visibleText: string,
): string {
  const reasoning = reasoningText.trim();
  if (!reasoning) {
    return visibleText;
  }
  return `${THINK_JSON_OPEN}${encodeThoughtText(reasoning)}${THINK_JSON_CLOSE}\n\n${visibleText}`.trim();
}

export function parseAssistantContent(content: string): ParsedAssistantContent {
  if (!hasThoughtOpenTag(content)) {
    return {
      visibleMarkdown: content,
      thoughtText: "",
    };
  }

  const visibleParts: string[] = [];
  const thoughtParts: string[] = [];
  let cursor = 0;

  while (cursor < content.length) {
    const match = findNextThoughtTag(content, cursor);
    if (!match) {
      visibleParts.push(content.slice(cursor));
      break;
    }

    const { tag, openIndex } = match;
    const closeIndex = findThoughtCloseIndex(
      content,
      tag,
      openIndex,
    );
    if (closeIndex < 0) {
      return {
        visibleMarkdown: content,
        thoughtText: "",
      };
    }

    visibleParts.push(content.slice(cursor, openIndex));

    const rawThought = content.slice(openIndex + tag.open.length, closeIndex);
    const thought = parseThoughtText(rawThought, tag);
    if (thought) {
      thoughtParts.push(thought);
    }

    cursor = closeIndex + tag.close.length;
  }

  return {
    visibleMarkdown: cleanVisibleMarkdown(visibleParts.join("")),
    thoughtText: thoughtParts.join("\n\n"),
  };
}

function hasThoughtOpenTag(content: string): boolean {
  return THOUGHT_TAGS.some((tag) => content.includes(tag.open));
}

function findNextThoughtTag(
  content: string,
  cursor: number,
): ThoughtTagMatch | null {
  let nextMatch: ThoughtTagMatch | null = null;
  for (const tag of THOUGHT_TAGS) {
    const openIndex = content.indexOf(tag.open, cursor);
    if (openIndex >= 0 && (!nextMatch || openIndex < nextMatch.openIndex)) {
      nextMatch = { tag, openIndex };
    }
  }
  return nextMatch;
}

function findThoughtCloseIndex(
  content: string,
  tag: ThoughtTag,
  openIndex: number,
): number {
  const cursor = openIndex + tag.open.length;
  if (!tag.allowNested) {
    return content.indexOf(tag.close, cursor);
  }

  const legacyWrapperCloseIndex = findLegacyWrapperCloseIndex(
    content,
    tag,
    openIndex,
  );
  if (legacyWrapperCloseIndex >= 0) {
    return legacyWrapperCloseIndex;
  }

  let depth = 1;
  let searchFrom = cursor;
  while (searchFrom < content.length) {
    const nextOpenIndex = content.indexOf(tag.open, searchFrom);
    const nextCloseIndex = content.indexOf(tag.close, searchFrom);
    if (nextCloseIndex < 0) {
      return -1;
    }
    if (nextOpenIndex >= 0 && nextOpenIndex < nextCloseIndex) {
      depth += 1;
      searchFrom = nextOpenIndex + tag.open.length;
      continue;
    }

    depth -= 1;
    if (depth === 0) {
      return nextCloseIndex;
    }
    searchFrom = nextCloseIndex + tag.close.length;
  }

  return -1;
}

function findLegacyWrapperCloseIndex(
  content: string,
  tag: ThoughtTag,
  openIndex: number,
): number {
  if (openIndex !== 0) {
    return -1;
  }

  const closeWithFollowingMarkdown = `\n${tag.close}\n\n`;
  const closeWithFollowingMarkdownIndex = content.lastIndexOf(
    closeWithFollowingMarkdown,
  );
  if (closeWithFollowingMarkdownIndex >= 0) {
    return closeWithFollowingMarkdownIndex + 1;
  }

  const closeAtEnd = `\n${tag.close}`;
  if (content.endsWith(closeAtEnd)) {
    return content.length - tag.close.length;
  }

  return -1;
}

function parseThoughtText(rawThought: string, tag: ThoughtTag): string {
  const thoughtText = tag.encoded ? decodeThoughtText(rawThought) : rawThought;
  return (thoughtText ?? rawThought).trim();
}

function encodeThoughtText(thoughtText: string): string {
  return JSON.stringify(thoughtText).replace(/[<>&]/g, (char) => {
    if (char === "<") {
      return "\\u003c";
    }
    if (char === ">") {
      return "\\u003e";
    }
    return "\\u0026";
  });
}

function decodeThoughtText(encodedThoughtText: string): string | null {
  try {
    const decoded = JSON.parse(encodedThoughtText) as unknown;
    return typeof decoded === "string" ? decoded : null;
  } catch {
    return null;
  }
}

type ThoughtBlockRefs = {
  updateThoughtText: (thoughtText: string) => void;
};

function createThoughtBlock(
  container: HTMLElement,
  thoughtText: string,
  options: { streaming?: boolean } = {},
): ThoughtBlockRefs {
  const wrapper = container.createDiv({
    cls: options.streaming
      ? "chat-thought-block streaming"
      : "chat-thought-block",
  });
  const header = wrapper.createDiv({ cls: "chat-thought-header" });
  header.setAttribute("role", "button");
  header.setAttribute("tabindex", "0");
  header.setAttribute("aria-expanded", "false");

  const title = header.createSpan({ cls: "chat-thought-title" });
  title.setText("思维链");

  const preview = header.createSpan({ cls: "chat-thought-preview" });

  const chevron = header.createSpan({ cls: "chat-thought-chevron" });
  chevron.setText(">");

  const body = wrapper.createDiv({ cls: "chat-thought-body" });

  const updateThoughtText = (nextThoughtText: string): void => {
    const previewLine = getFirstNonEmptyLine(nextThoughtText);
    preview.classList.toggle("is-empty", !previewLine);
    preview.setText(
      previewLine
        ? previewLine.slice(0, 72) + (previewLine.length > 72 ? "..." : "")
        : "",
    );
    body.setText(nextThoughtText);
  };

  const toggle = (): void => {
    const expanded = !wrapper.classList.contains("expanded");
    wrapper.classList.toggle("expanded", expanded);
    header.setAttribute("aria-expanded", expanded ? "true" : "false");
    chevron.setText(expanded ? "v" : ">");
  };

  header.addEventListener("click", toggle);
  header.addEventListener("keydown", (evt: KeyboardEvent) => {
    if (evt.key === "Enter" || evt.key === " ") {
      evt.preventDefault();
      toggle();
    }
  });

  updateThoughtText(thoughtText);
  return { updateThoughtText };
}

function cleanVisibleMarkdown(content: string): string {
  return content
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function getFirstNonEmptyLine(content: string): string | undefined {
  return content
    .trim()
    .split("\n")
    .find((line) => line.trim());
}
