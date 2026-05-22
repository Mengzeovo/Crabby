import { statSync } from "node:fs";
import { resolve, sep } from "node:path";

import { Notice, TFile, normalizePath, type App } from "obsidian";

import type { AgentClient, ToolCallPayload } from "../api/client";
import type CrabbyPlugin from "../main";
import type { DiaryPromptController } from "./chatTypes";

interface DiaryPromptDeps {
  app: App;
  client: AgentClient;
  plugin: CrabbyPlugin;
  rootEl: HTMLDivElement;
  openPluginSettings: () => boolean;
}

interface PendingDiaryPrompt {
  sessionId: string;
  conversationId: string;
  summary: string;
  entryKey: string;
  writing: boolean;
}

export function createDiaryPrompt(
  deps: DiaryPromptDeps,
): DiaryPromptController {
  const { app, client, plugin, rootEl, openPluginSettings } = deps;
  let current: PendingDiaryPrompt | null = null;

  function hide(): void {
    current = null;
    rootEl.empty();
    rootEl.classList.remove("is-open", "is-writing", "is-missing-template");
  }

  function render(): void {
    const pending = current;
    rootEl.empty();
    rootEl.classList.remove("is-open", "is-writing", "is-missing-template");
    if (!pending) {
      return;
    }

    const templateExists = dailyTemplateExists(app, plugin);
    rootEl.classList.add("is-open");
    if (pending.writing) {
      rootEl.classList.add("is-writing");
    }
    if (!templateExists) {
      rootEl.classList.add("is-missing-template");
    }

    const panelEl = rootEl.createDiv({ cls: "chat-diary-prompt-panel" });
    const textEl = panelEl.createDiv({ cls: "chat-diary-prompt-text" });
    textEl.createDiv({
      cls: "chat-diary-prompt-title",
      text: "Loop 任务已完成",
    });
    textEl.createDiv({
      cls: "chat-diary-prompt-body",
      text: templateExists
        ? "要把这次循环任务的总结写入今日日记吗？"
        : "先配置日记模板后才能写入今日日记。",
    });
    textEl.createDiv({
      cls: "chat-diary-prompt-preview",
      text: truncatePreview(pending.summary),
    });

    const actionsEl = panelEl.createDiv({ cls: "chat-diary-prompt-actions" });
    if (templateExists) {
      const writeBtn = actionsEl.createEl("button", {
        cls: "chat-diary-prompt-btn is-primary",
        text: pending.writing ? "写入中..." : "写入今日日记",
      });
      writeBtn.disabled = pending.writing;
      writeBtn.addEventListener("click", () => {
        void writeCurrentPrompt();
      });

      const skipBtn = actionsEl.createEl("button", {
        cls: "chat-diary-prompt-btn",
        text: "跳过",
      });
      skipBtn.disabled = pending.writing;
      skipBtn.addEventListener("click", hide);
      return;
    }

    const settingsBtn = actionsEl.createEl("button", {
      cls: "chat-diary-prompt-btn is-primary",
      text: "去设置",
    });
    settingsBtn.addEventListener("click", () => {
      if (!openPluginSettings()) {
        new Notice("无法自动打开 Crabby 设置，请从 Obsidian 设置里打开插件设置。");
      }
    });

    const closeBtn = actionsEl.createEl("button", {
      cls: "chat-diary-prompt-btn",
      text: "关闭",
    });
    closeBtn.addEventListener("click", hide);
  }

  async function writeCurrentPrompt(): Promise<void> {
    const pending = current;
    if (!pending || pending.writing) {
      return;
    }
    pending.writing = true;
    render();

    try {
      const vaultSync = await plugin.ensureBackendVaultPathSynced(client);
      if (!vaultSync.ok) {
        throw new Error(vaultSync.message);
      }

      const result = await client.writeDiaryEntry({
        session_id: pending.sessionId,
        conversation_id: pending.conversationId,
        period: "daily",
        date: formatLocalDate(new Date()),
        summary: pending.summary,
        topics: ["loop"],
        domains: ["task"],
        memory_links: [],
        entry_key: pending.entryKey,
      });

      if (result.is_error || result.status === "error") {
        throw new Error(result.output || "日记写入失败。");
      }

      if (current === pending) {
        hide();
      }
      const deduplicated = Boolean(result.metadata?.deduplicated);
      new Notice(deduplicated ? "今日日记里已有这条 Loop 总结。" : "已写入今日日记。");
    } catch (error) {
      if (current === pending) {
        pending.writing = false;
        render();
      }
      const message = error instanceof Error ? error.message : String(error);
      new Notice(`写入今日日记失败：${message}`);
    }
  }

  return {
    showLoopStopResult(payload, sessionId, conversationId): void {
      if (payload.is_error || payload.status === "error") {
        return;
      }
      const summary = String(payload.output ?? "").trim();
      if (!summary || !sessionId || !conversationId) {
        return;
      }
      const rawJobId = getLoopJobId(payload);
      if (!rawJobId) {
        return;
      }
      const jobId = sanitizeEntryKeyPart(rawJobId);
      current = {
        sessionId,
        conversationId,
        summary,
        entryKey: `loop:${jobId}:completion`,
        writing: false,
      };
      render();
    },
    hide,
    destroy: hide,
  };
}

function dailyTemplateExists(app: App, plugin: CrabbyPlugin): boolean {
  const rawPath = plugin.settings.diary?.templatePaths?.daily?.trim();
  if (!rawPath) {
    return false;
  }
  const normalizedPath = normalizePath(rawPath);
  const file = app.vault.getAbstractFileByPath(normalizedPath);
  if (file instanceof TFile) {
    return true;
  }

  const vaultPath = plugin.getCurrentVaultPath().trim();
  if (!vaultPath) {
    return false;
  }

  const vaultRoot = resolve(vaultPath);
  const targetPath = resolve(vaultRoot, normalizedPath);
  if (!isWithinVault(targetPath, vaultRoot)) {
    return false;
  }

  try {
    return statSync(targetPath).isFile();
  } catch {
    return false;
  }
}

function sanitizeEntryKeyPart(value: string): string {
  const normalized = value.replace(/\r|\n/g, " ").replace(/-->/g, "--").trim();
  return (normalized || "unknown").slice(0, 150);
}

function getLoopJobId(payload: ToolCallPayload): string | null {
  const jobId = payload.metadata?.job_id;
  if (typeof jobId !== "string") {
    return null;
  }
  const trimmed = jobId.trim();
  return trimmed || null;
}

function isWithinVault(targetPath: string, vaultRoot: string): boolean {
  if (targetPath === vaultRoot) {
    return true;
  }
  const rootWithSeparator = vaultRoot.endsWith(sep) ? vaultRoot : `${vaultRoot}${sep}`;
  return targetPath.startsWith(rootWithSeparator);
}

function truncatePreview(value: string, limit = 260): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit).trim()}...`;
}

function formatLocalDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
