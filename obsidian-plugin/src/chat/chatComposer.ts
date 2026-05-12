import { Notice, TAbstractFile, TFile, TFolder } from "obsidian";

import type {
  BackendCapabilities,
  MessageAttachment,
  SkillSummary,
  VaultDirectoryAttachment,
  VaultFileAttachment,
} from "../api/client";
import type { ChatCommonDeps } from "./chatTypes";
import type {
  ChatComposerController,
  ChatComposerSubmitPayload,
  ComposerImagePaste,
} from "./chatTypes";

type SuggestionKind = "slash" | "mention";

type ComposerSuggestion = {
  kind: SuggestionKind;
  label: string;
  description: string;
  replaceFrom: number;
  replaceTo: number;
  insertText: string;
};

type MentionSuggestionCandidate = TFile | TFolder;

const IMAGE_REF_RE = /\[Image\s+#(\d+)\]/g;
const SLASH_CONTEXT_RE = /(^|[^0-9A-Za-z_./\\:-])\/([^\s/]*)$/;
const QUOTED_MENTION_CONTEXT_RE = /(^|[^0-9A-Za-z_./\\:-])@"([^"]*)$/;
const REGULAR_MENTION_CONTEXT_RE = /(^|[^0-9A-Za-z_./\\:-])@([^\s"]*)$/;
const QUOTED_MENTION_RE = /(^|[^0-9A-Za-z_./\\:-])@"([^"]+)"(#L\d+(?:-\d+)?)?/g;
const REGULAR_MENTION_RE = /(^|[^0-9A-Za-z_./\\:-])@([^\s"]+)/g;
const MAX_IMAGES = 4;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

export function createChatComposer(
  deps: ChatCommonDeps,
): ChatComposerController {
  const { app, client, elements, state } = deps;

  let skills: SkillSummary[] = [];
  let nextImageId = 1;
  let pastedContents: Record<number, ComposerImagePaste> = {};
  let suggestions: ComposerSuggestion[] = [];
  let selectedSuggestionIndex = 0;
  let suggestionContextKey: string | null = null;
  let historyNavigationIndex: number | null = null;
  let historyDraft = "";
  let suppressNextHistoryReset = false;
  let suppressNextSelectionRefresh = false;
  let lastClipboardHintAt = 0;
  let backendCapabilities: BackendCapabilities | null = null;

  const cleanupFns: Array<() => void> = [];

  void client
    .listSkills()
    .then((result) => {
      skills = result;
      refreshSuggestions();
    })
    .catch(() => {
      skills = [];
    });

  void client
    .getCapabilities()
    .then((result) => {
      backendCapabilities = result;
    })
    .catch(() => {
      backendCapabilities = null;
    });

  const onInput = (): void => {
    if (suppressNextHistoryReset) {
      suppressNextHistoryReset = false;
    } else {
      resetHistoryNavigation();
    }
    autoResize();
    pruneDeletedImageRefs();
    refreshSuggestions();
  };

  const onSelectionChange = (): void => {
    if (suppressNextSelectionRefresh) {
      suppressNextSelectionRefresh = false;
      return;
    }
    refreshSuggestions();
  };

  const onKeyDown = (evt: KeyboardEvent): void => {
    if (suggestions.length > 0) {
      if (evt.key === "ArrowDown") {
        suppressNextSelectionRefresh = true;
        evt.preventDefault();
        evt.stopPropagation();
        selectedSuggestionIndex =
          (selectedSuggestionIndex + 1) % suggestions.length;
        renderSuggestions();
        return;
      }
      if (evt.key === "ArrowUp") {
        suppressNextSelectionRefresh = true;
        evt.preventDefault();
        evt.stopPropagation();
        selectedSuggestionIndex =
          (selectedSuggestionIndex - 1 + suggestions.length) % suggestions.length;
        renderSuggestions();
        return;
      }
      if (evt.key === "Tab" || evt.key === "Enter") {
        evt.preventDefault();
        evt.stopPropagation();
        applySuggestion(suggestions[selectedSuggestionIndex]!);
        return;
      }
      if (evt.key === "Escape") {
        suppressNextSelectionRefresh = true;
        evt.preventDefault();
        evt.stopPropagation();
        suggestions = [];
        selectedSuggestionIndex = 0;
        suggestionContextKey = null;
        renderSuggestions();
        return;
      }
    }
  };

  const onPaste = (evt: ClipboardEvent): void => {
    const files = extractImageFilesFromClipboard(evt);
    if (files.length === 0) {
      return;
    }
    evt.preventDefault();
    void ingestImageFiles(files);
  };

  const onDragOver = (evt: DragEvent): void => {
    if (!hasImageFiles(evt.dataTransfer?.files)) {
      return;
    }
    evt.preventDefault();
    elements.inputAreaEl.classList.add("drag-over");
  };

  const onDragLeave = (): void => {
    elements.inputAreaEl.classList.remove("drag-over");
  };

  const onDrop = (evt: DragEvent): void => {
    elements.inputAreaEl.classList.remove("drag-over");
    const files = toImageFiles(evt.dataTransfer?.files);
    if (files.length === 0) {
      return;
    }
    evt.preventDefault();
    void ingestImageFiles(files);
  };

  const onAttachmentClick = (): void => {
    elements.hiddenFileInput.click();
  };

  const onFileInput = (): void => {
    const files = toImageFiles(elements.hiddenFileInput.files);
    elements.hiddenFileInput.value = "";
    if (files.length === 0) {
      return;
    }
    void ingestImageFiles(files);
  };

  const onFocus = (): void => {
    void maybeShowClipboardHint();
  };

  elements.inputEl.addEventListener("input", onInput);
  elements.inputEl.addEventListener("keydown", onKeyDown);
  elements.inputEl.addEventListener("click", onSelectionChange);
  elements.inputEl.addEventListener("keyup", onSelectionChange);
  elements.inputEl.addEventListener("paste", onPaste);
  elements.inputAreaEl.addEventListener("dragover", onDragOver);
  elements.inputAreaEl.addEventListener("dragleave", onDragLeave);
  elements.inputAreaEl.addEventListener("drop", onDrop);
  elements.attachmentBtn.addEventListener("click", onAttachmentClick);
  elements.hiddenFileInput.addEventListener("change", onFileInput);
  window.addEventListener("focus", onFocus);

  cleanupFns.push(() => {
    elements.inputEl.removeEventListener("input", onInput);
    elements.inputEl.removeEventListener("keydown", onKeyDown);
    elements.inputEl.removeEventListener("click", onSelectionChange);
    elements.inputEl.removeEventListener("keyup", onSelectionChange);
    elements.inputEl.removeEventListener("paste", onPaste);
    elements.inputAreaEl.removeEventListener("dragover", onDragOver);
    elements.inputAreaEl.removeEventListener("dragleave", onDragLeave);
    elements.inputAreaEl.removeEventListener("drop", onDrop);
    elements.attachmentBtn.removeEventListener("click", onAttachmentClick);
    elements.hiddenFileInput.removeEventListener("change", onFileInput);
    window.removeEventListener("focus", onFocus);
  });

  function getSubmitPayload(): ChatComposerSubmitPayload | null {
    const rawText = elements.inputEl.value;
    const activeImages = getReferencedImages(rawText);
    const displayText = removeImageRefs(rawText);
    const displayAttachments = buildDisplayAttachments(rawText, activeImages);

    if (!displayText.trim() && displayAttachments.length === 0) {
      return null;
    }

    if (activeImages.length > 0 && backendCapabilities?.supports_vision === false) {
      new Notice("当前后端模型未开启视觉能力，图片已保留在输入框里，暂时不能发送。");
      return null;
    }

    return {
      request: {
        content: rawText,
        pasted_contents: activeImages.map(({ preview_url: _previewUrl, size_bytes: _size, ...rest }) => rest),
      },
      displayText,
      displayAttachments,
    };
  }

  function clear(): void {
    clearComposerState();
    elements.inputEl.value = "";
    autoResize();
    refreshSuggestions();
  }

  function destroy(): void {
    clearComposerState();
    cleanupFns.splice(0).forEach((cleanup) => cleanup());
  }

  function clearComposerState(): void {
    pastedContents = {};
    suggestions = [];
    selectedSuggestionIndex = 0;
    suggestionContextKey = null;
    resetHistoryNavigation();
    elements.composerPillsEl.empty();
    renderSuggestions();
  }

  async function maybeShowClipboardHint(): Promise<void> {
    if (
      typeof navigator === "undefined" ||
      !navigator.clipboard ||
      typeof navigator.clipboard.read !== "function"
    ) {
      return;
    }
    if (Date.now() - lastClipboardHintAt < 15_000) {
      return;
    }

    try {
      const items = await navigator.clipboard.read();
      const hasImage = items.some((item) =>
        item.types.some((type) => type.startsWith("image/")),
      );
      if (hasImage) {
        lastClipboardHintAt = Date.now();
        new Notice("剪贴板里有图片，可以直接粘贴到对话框。");
      }
    } catch {
      // Ignore permission / platform failures.
    }
  }

  async function ingestImageFiles(files: File[]): Promise<void> {
    const currentCount = Object.keys(pastedContents).length;
    if (currentCount + files.length > MAX_IMAGES) {
      new Notice(`每次最多附带 ${MAX_IMAGES} 张图片。`);
      return;
    }

    for (const file of files) {
      if (file.size > MAX_IMAGE_BYTES) {
        new Notice(`${file.name} 超过 10 MB，已跳过。`);
        continue;
      }

      const dataUrl = await readFileAsDataUrl(file);
      const [header, base64] = dataUrl.split(",", 2);
      if (!base64) {
        continue;
      }
      const mediaType = extractMediaType(header) || file.type || "image/png";
      const dimensions = await getImageDimensions(dataUrl);
      const id = nextImageId++;
      pastedContents[id] = {
        id,
        type: "image",
        data: base64,
        media_type: mediaType,
        filename: file.name || `Image ${id}`,
        width: dimensions?.width,
        height: dimensions?.height,
        preview_url: dataUrl,
        size_bytes: file.size,
      };
      insertImagePlaceholder(id);
    }

    renderImagePills();
    refreshSuggestions();
  }

  function buildDisplayAttachments(
    rawText: string,
    activeImages: ComposerImagePaste[],
  ): MessageAttachment[] {
    const fileAttachments = extractMentionDisplayAttachments(rawText);
    const imageAttachments: MessageAttachment[] = activeImages.map((image) => ({
      type: "image",
      filename: image.filename,
      media_type: image.media_type,
      width: image.width,
      height: image.height,
      preview_url: image.preview_url,
    }));
    return [...fileAttachments, ...imageAttachments];
  }

  function extractMentionDisplayAttachments(rawText: string): MessageAttachment[] {
    const mentions = extractAtMentions(rawText);
    const results: MessageAttachment[] = [];

    for (const mention of mentions) {
      const path = mention.path;
      const abstract = app.vault.getAbstractFileByPath(path);
      if (abstract instanceof TFolder) {
        const attachment: VaultDirectoryAttachment = {
          type: "vault_directory",
          path,
          entry_count: abstract.children.length,
        };
        results.push(attachment);
      } else if (abstract instanceof TFile) {
        const attachment: VaultFileAttachment = {
          type: "vault_file",
          path,
          line_start: mention.line_start,
          line_end: mention.line_end,
        };
        results.push(attachment);
      }
    }

    return results;
  }

  function getReferencedImages(rawText: string): ComposerImagePaste[] {
    const ids = Array.from(rawText.matchAll(IMAGE_REF_RE))
      .map((match) => Number(match[1]))
      .filter((value) => Number.isFinite(value));
    const ordered: ComposerImagePaste[] = [];
    const seen = new Set<number>();
    for (const id of ids) {
      if (seen.has(id) || !pastedContents[id]) {
        continue;
      }
      seen.add(id);
      ordered.push(pastedContents[id]!);
    }
    return ordered;
  }

  function pruneDeletedImageRefs(): void {
    const activeIds = new Set(
      Array.from(elements.inputEl.value.matchAll(IMAGE_REF_RE)).map((match) =>
        Number(match[1]),
      ),
    );
    for (const [key, item] of Object.entries(pastedContents)) {
      if (!activeIds.has(Number(key))) {
        delete pastedContents[Number(key)];
      }
    }
    renderImagePills();
  }

  function renderImagePills(): void {
    elements.composerPillsEl.empty();
    for (const image of Object.values(pastedContents)) {
      const pill = elements.composerPillsEl.createDiv({ cls: "chat-image-pill" });
      pill.createEl("img", {
        cls: "chat-image-pill-thumb",
        attr: {
          src: image.preview_url,
          alt: image.filename,
        },
      });
      const label = pill.createDiv({ cls: "chat-image-pill-label" });
      label.setText(image.filename);
      const removeBtn = pill.createEl("button", {
        cls: "chat-image-pill-remove",
        attr: { "aria-label": `Remove ${image.filename}` },
      });
      removeBtn.setText("×");
      removeBtn.addEventListener("click", () => {
        delete pastedContents[image.id];
        elements.inputEl.value = elements.inputEl.value
          .replace(new RegExp(`\\s*\\[Image\\s+#${image.id}\\]\\s*`, "g"), " ")
          .replace(/[ \t]{2,}/g, " ")
          .trim();
        autoResize();
        renderImagePills();
        refreshSuggestions();
      });
    }

    elements.composerPillsEl.classList.toggle(
      "has-items",
      Object.keys(pastedContents).length > 0,
    );
  }

  function refreshSuggestions(): void {
    const slashContext = getSlashContext();
    if (slashContext) {
      setSuggestions(
        buildSlashSuggestions(slashContext.query, slashContext.from, slashContext.to),
        `slash:${slashContext.from}:${slashContext.to}:${slashContext.query}`,
      );
      return;
    }

    const mentionContext = getMentionContext();
    if (mentionContext) {
      setSuggestions(
        buildMentionSuggestions(
          mentionContext.query,
          mentionContext.from,
          mentionContext.to,
        ),
        `mention:${mentionContext.from}:${mentionContext.to}:${mentionContext.query}`,
      );
      return;
    }

    setSuggestions([]);
  }

  function renderSuggestions(): void {
    elements.suggestionListEl.empty();
    if (suggestions.length === 0) {
      elements.suggestionListEl.classList.remove("is-open");
      return;
    }

    elements.suggestionListEl.classList.add("is-open");
    suggestions.forEach((suggestion, index) => {
      const item = elements.suggestionListEl.createDiv({
        cls: "chat-suggestion-item",
      });
      if (index === selectedSuggestionIndex) {
        item.classList.add("is-selected");
        window.setTimeout(() => {
          item.scrollIntoView({ block: "nearest" });
        }, 0);
      }

      const title = item.createDiv({ cls: "chat-suggestion-title" });
      title.setText(suggestion.label);
      const desc = item.createDiv({ cls: "chat-suggestion-desc" });
      desc.setText(suggestion.description);

      item.addEventListener("mousedown", (evt) => {
        evt.preventDefault();
        applySuggestion(suggestion);
      });
    });
  }

  function applySuggestion(suggestion: ComposerSuggestion): void {
    const value = elements.inputEl.value;
    const before = value.slice(0, suggestion.replaceFrom);
    const after = value.slice(suggestion.replaceTo);
    elements.inputEl.value = `${before}${suggestion.insertText}${after}`;
    const cursor = suggestion.replaceFrom + suggestion.insertText.length;
    elements.inputEl.setSelectionRange(cursor, cursor);
    elements.inputEl.focus();
    autoResize();
    suggestions = [];
    suggestionContextKey = null;
    renderSuggestions();
    pruneDeletedImageRefs();
  }

  function navigateHistory(direction: "up" | "down"): boolean {
    if (suggestions.length > 0) {
      return false;
    }

    const start = elements.inputEl.selectionStart ?? elements.inputEl.value.length;
    const end = elements.inputEl.selectionEnd ?? start;
    if (start !== end) {
      return false;
    }

    if (direction === "up" && !isCursorOnFirstLine(start)) {
      return false;
    }
    if (direction === "down" && !isCursorOnLastLine(end)) {
      return false;
    }

    const historyEntries = getMessageHistoryEntries();
    if (historyEntries.length === 0) {
      return false;
    }

    if (historyNavigationIndex == null) {
      if (direction === "down") {
        return false;
      }
      historyDraft = elements.inputEl.value;
      historyNavigationIndex = historyEntries.length - 1;
      setComposerText(historyEntries[historyNavigationIndex]!);
      return true;
    }

    if (direction === "up") {
      if (historyNavigationIndex === 0) {
        return true;
      }
      historyNavigationIndex -= 1;
      setComposerText(historyEntries[historyNavigationIndex]!);
      return true;
    }

    if (historyNavigationIndex >= historyEntries.length - 1) {
      historyNavigationIndex = null;
      setComposerText(historyDraft);
      return true;
    }

    historyNavigationIndex += 1;
    setComposerText(historyEntries[historyNavigationIndex]!);
    return true;
  }

  function setSuggestions(
    nextSuggestions: ComposerSuggestion[],
    contextKey: string | null = null,
  ): void {
    const currentSelection = suggestions[selectedSuggestionIndex];
    const shouldPreserveSelection =
      contextKey != null && contextKey === suggestionContextKey;

    suggestions = nextSuggestions;
    suggestionContextKey = contextKey;

    if (suggestions.length === 0) {
      selectedSuggestionIndex = 0;
      renderSuggestions();
      return;
    }

    if (shouldPreserveSelection && currentSelection) {
      const preservedIndex = suggestions.findIndex((suggestion) =>
        isSameSuggestion(suggestion, currentSelection),
      );
      if (preservedIndex >= 0) {
        selectedSuggestionIndex = preservedIndex;
        renderSuggestions();
        return;
      }
    }

    selectedSuggestionIndex = shouldPreserveSelection
      ? Math.min(selectedSuggestionIndex, suggestions.length - 1)
      : 0;
    renderSuggestions();
  }

  function buildSlashSuggestions(
    query: string,
    from: number,
    to: number,
  ): ComposerSuggestion[] {
    const normalizedQuery = query.trim().toLowerCase();
    const ranked = skills
      .map((skill) => ({
        skill,
        score: scoreSkill(skill, normalizedQuery),
      }))
      .filter((entry) => entry.score > 0 || normalizedQuery.length === 0)
      .sort((a, b) => b.score - a.score || a.skill.name.localeCompare(b.skill.name))
      .slice(0, 8);

    return ranked.map(({ skill }) => ({
      kind: "slash",
      label: `/${skill.name}`,
      description: skill.description,
      replaceFrom: from,
      replaceTo: to,
      insertText: `/${skill.name} `,
    }));
  }

  function buildMentionSuggestions(
    query: string,
    from: number,
    to: number,
  ): ComposerSuggestion[] {
    const normalizedQuery = query.trim().toLowerCase();
    const candidates = app.vault
      .getAllLoadedFiles()
      .filter(isMentionSuggestionCandidate);
    const ranked = candidates
      .map((candidate) => ({
        candidate,
        score: scoreMentionCandidate(candidate, normalizedQuery),
      }))
      .filter((entry) => entry.score > 0 || normalizedQuery.length === 0)
      .sort(
        (a, b) =>
          b.score - a.score ||
          a.candidate.path.localeCompare(b.candidate.path),
      )
      .slice(0, 8);

    return ranked.map(({ candidate }) => ({
      kind: "mention",
      label:
        candidate instanceof TFolder
          ? `@${candidate.path}/`
          : `@${candidate.path}`,
      description:
        candidate instanceof TFolder
          ? `${candidate.children.length} items`
          : candidate.basename,
      replaceFrom: from,
      replaceTo: to,
      insertText: `${formatMention(candidate.path)} `,
    }));
  }

  function getSlashContext():
    | { query: string; from: number; to: number }
    | null {
    const cursor = elements.inputEl.selectionStart ?? elements.inputEl.value.length;
    const before = elements.inputEl.value.slice(0, cursor);
    const match = before.match(SLASH_CONTEXT_RE);
    if (!match || match.index == null) {
      return null;
    }
    const slashIndex = match.index + match[1].length;
    let to = cursor;
    while (to < elements.inputEl.value.length && !/\s/.test(elements.inputEl.value[to]!)) {
      to += 1;
    }
    return {
      query: match[2] ?? "",
      from: slashIndex,
      to,
    };
  }

  function getMentionContext():
    | { query: string; from: number; to: number }
    | null {
    const cursor = elements.inputEl.selectionStart ?? elements.inputEl.value.length;
    const before = elements.inputEl.value.slice(0, cursor);
    const quoted = before.match(QUOTED_MENTION_CONTEXT_RE);
    if (quoted && quoted.index != null) {
      const start = quoted.index + quoted[1].length;
      let to = cursor;
      while (to < elements.inputEl.value.length && elements.inputEl.value[to] !== "\"") {
        to += 1;
      }
      if (elements.inputEl.value[to] === "\"") {
        to += 1;
      }
      return {
        query: quoted[2] ?? "",
        from: start,
        to,
      };
    }

    const regular = before.match(REGULAR_MENTION_CONTEXT_RE);
    if (!regular || regular.index == null) {
      return null;
    }
    const start = regular.index + regular[1].length;
    let to = cursor;
    while (to < elements.inputEl.value.length && !/\s/.test(elements.inputEl.value[to]!)) {
      to += 1;
    }
    return {
      query: regular[2] ?? "",
      from: start,
      to,
    };
  }

  function insertImagePlaceholder(id: number): void {
    const token = `[Image #${id}]`;
    insertTextAtCursor(`${needsLeadingSpace() ? " " : ""}${token} `);
    autoResize();
  }

  function insertTextAtCursor(text: string): void {
    const start = elements.inputEl.selectionStart ?? elements.inputEl.value.length;
    const end = elements.inputEl.selectionEnd ?? start;
    const value = elements.inputEl.value;
    elements.inputEl.value = `${value.slice(0, start)}${text}${value.slice(end)}`;
    const nextCursor = start + text.length;
    elements.inputEl.setSelectionRange(nextCursor, nextCursor);
    elements.inputEl.focus();
  }

  function setComposerText(text: string): void {
    suppressNextHistoryReset = true;
    elements.inputEl.value = text;
    const cursor = text.length;
    elements.inputEl.setSelectionRange(cursor, cursor);
    elements.inputEl.focus();
    autoResize();
    pruneDeletedImageRefs();
    refreshSuggestions();
  }

  function resetHistoryNavigation(): void {
    historyNavigationIndex = null;
    historyDraft = "";
  }

  function getMessageHistoryEntries(): string[] {
    return state.messages
      .filter((message) => message.role === "user" && Boolean(message.content.trim()))
      .map((message) => message.content);
  }

  function isCursorOnFirstLine(position: number): boolean {
    return !elements.inputEl.value.slice(0, position).includes("\n");
  }

  function isCursorOnLastLine(position: number): boolean {
    return !elements.inputEl.value.slice(position).includes("\n");
  }

  function needsLeadingSpace(): boolean {
    const start = elements.inputEl.selectionStart ?? elements.inputEl.value.length;
    const previous = elements.inputEl.value[start - 1];
    return Boolean(previous && !/\s/.test(previous));
  }

  function autoResize(): void {
    elements.inputEl.style.height = "auto";
    elements.inputEl.style.height = `${Math.min(elements.inputEl.scrollHeight, 120)}px`;
  }

  return {
    getSubmitPayload,
    navigateHistory,
    clear,
    destroy,
  };
}

function removeImageRefs(text: string): string {
  return text
    .replace(IMAGE_REF_RE, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function extractAtMentions(
  text: string,
): Array<{ path: string; line_start?: number; line_end?: number }> {
  const results: Array<{ path: string; line_start?: number; line_end?: number }> = [];
  const seen = new Set<string>();

  for (const match of text.matchAll(QUOTED_MENTION_RE)) {
    const path = `${match[2] ?? ""}${match[3] ?? ""}`;
    pushMention(results, seen, path);
  }
  for (const match of text.matchAll(REGULAR_MENTION_RE)) {
    const path = (match[2] ?? "").replace(/[.,;:!?]+$/, "");
    if (path.startsWith('"')) {
      continue;
    }
    pushMention(results, seen, path);
  }

  return results;
}

function pushMention(
  results: Array<{ path: string; line_start?: number; line_end?: number }>,
  seen: Set<string>,
  rawPath: string,
): void {
  if (!rawPath || seen.has(rawPath)) {
    return;
  }
  seen.add(rawPath);

  const rangeMatch = rawPath.match(/^(.*)#L(\d+)(?:-(\d+))?$/);
  if (!rangeMatch) {
    results.push({ path: rawPath });
    return;
  }

  const start = Number(rangeMatch[2]);
  const end = Number(rangeMatch[3] ?? rangeMatch[2]);
  results.push({
    path: rangeMatch[1]!,
    line_start: Math.min(start, end),
    line_end: Math.max(start, end),
  });
}

function scoreSkill(skill: SkillSummary, query: string): number {
  if (!query) {
    return 1;
  }
  const name = skill.name.toLowerCase();
  const description = skill.description.toLowerCase();
  if (name.startsWith(query)) return 5;
  if (name.includes(query)) return 4;
  if ((skill.aliases ?? []).some((alias) => alias.toLowerCase().startsWith(query))) {
    return 3.5;
  }
  if (description.includes(query)) return 2;
  return 0;
}

function isMentionSuggestionCandidate(
  file: TAbstractFile,
): file is MentionSuggestionCandidate {
  if (!(file instanceof TFile || file instanceof TFolder)) {
    return false;
  }
  return Boolean(file.path);
}

function scoreMentionCandidate(
  candidate: MentionSuggestionCandidate,
  query: string,
): number {
  if (!query) {
    return 1;
  }
  const path = candidate.path.toLowerCase();
  const base = candidate.name.toLowerCase();
  if (base.startsWith(query)) return 5;
  if (path.startsWith(query)) return 4.5;
  if (base.includes(query)) return 4;
  if (path.includes(query)) return 3;
  return 0;
}

function formatMention(path: string): string {
  return /\s/.test(path) ? `@"${path}"` : `@${path}`;
}

function isSameSuggestion(
  left: ComposerSuggestion,
  right: ComposerSuggestion,
): boolean {
  return (
    left.kind === right.kind &&
    left.label === right.label &&
    left.insertText === right.insertText &&
    left.replaceFrom === right.replaceFrom &&
    left.replaceTo === right.replaceTo
  );
}

function extractImageFilesFromClipboard(evt: ClipboardEvent): File[] {
  const items = Array.from(evt.clipboardData?.items ?? []);
  return items
    .filter((item) => item.type.startsWith("image/"))
    .map((item) => item.getAsFile())
    .filter((file): file is File => file != null);
}

function toImageFiles(fileList: FileList | null | undefined): File[] {
  return Array.from(fileList ?? []).filter((file) => file.type.startsWith("image/"));
}

function hasImageFiles(fileList: FileList | null | undefined): boolean {
  return toImageFiles(fileList).length > 0;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function extractMediaType(header: string): string | null {
  const match = header.match(/^data:([^;]+);base64$/);
  return match ? match[1]! : null;
}

function getImageDimensions(
  src: string,
): Promise<{ width: number; height: number } | null> {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.width, height: image.height });
    image.onerror = () => resolve(null);
    image.src = src;
  });
}
