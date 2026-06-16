/**
 * Watcher modal: register a monitored external code directory for the current
 * session and choose an access level, plus manage the persistent Vault-dir <->
 * external-dir binding registry.
 */

import { App, Modal, Notice, Setting } from "obsidian";

import type { AgentClient, ProjectBinding, SessionInfo } from "../api/client";

const ACCESS_LEVEL_LABELS: Record<string, string> = {
  "read-only": "只读（可读监控项目，写入仅限 Vault）",
  "workspace-write": "可写（读写监控项目，bash 在项目目录执行）",
  "full-access": "完全访问（可写 + 放宽非破坏性命令告警）",
};

function accessLevelLabel(level: string): string {
  return ACCESS_LEVEL_LABELS[level] ?? level;
}

export interface ExternalProjectModalDeps {
  app: App;
  client: AgentClient;
  /** Ensure a session exists and return its id (creates one if needed). */
  ensureSessionId: () => Promise<string>;
  /** Called after the session's external project settings change. */
  onApplied: (session: SessionInfo) => void;
}

class ExternalProjectModal extends Modal {
  private pathValue = "";
  private levelValue = "workspace-write";
  private bindVaultDir = "";
  private levels: string[] = [
    "read-only",
    "workspace-write",
    "full-access",
  ];
  private sessionId: string | null = null;
  /**
   * 是否已完成首次状态加载（access-levels + 会话外部项目设置）。
   * 加载只在首次 render 时执行一次；之后的重渲染（点「使用」、存/删绑定）
   * 沿用内存中的 pathValue/levelValue/bindVaultDir，避免回拉会话把用户
   * 刚选好的路径覆盖成空字符串。
   */
  private initialized = false;

  constructor(private readonly deps: ExternalProjectModalDeps) {
    super(deps.app);
  }

  onOpen(): void {
    void this.render();
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private async render(): Promise<void> {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("external-project-modal");
    contentEl.createEl("h2", { text: "Watcher（项目监控）" });
    contentEl.createEl("p", {
      cls: "external-project-hint",
      text:
        "为当前会话注册一个被监控的外部代码目录，Crabby 即可访问 Vault 与该目录。" +
        "Vault 用于存放规划、理解与实现记录，外部目录是实际代码。",
    });

    // Load current session state + available access levels — first render only.
    // Subsequent re-renders reuse the in-memory values so clicking a binding's
    // 「使用」button (which calls render()) doesn't get its path wiped by a
    // fresh session fetch.
    if (!this.initialized) {
      try {
        this.sessionId = await this.deps.ensureSessionId();
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        contentEl.createEl("p", {
          cls: "external-project-error",
          text: `无法获取当前会话：${message}`,
        });
        return;
      }

      try {
        const [levelsInfo, session] = await Promise.all([
          this.deps.client.getAccessLevels(),
          this.sessionId
            ? this.deps.client.getSession(this.sessionId)
            : Promise.resolve(null),
        ]);
        if (levelsInfo.levels.length > 0) {
          this.levels = levelsInfo.levels;
          this.levelValue = levelsInfo.default || this.levelValue;
        }
        if (session) {
          this.pathValue = session.external_project_path ?? "";
          this.levelValue = session.external_access_level || this.levelValue;
        }
      } catch (err) {
        console.warn("[ChatView] load external project state failed:", err);
      }

      this.initialized = true;
    }

    this.renderCurrentState(contentEl);
    this.renderPathInput(contentEl);
    this.renderLevelSelect(contentEl);
    void this.renderBindings(contentEl);
    this.renderActions(contentEl);
  }

  private renderCurrentState(parent: HTMLElement): void {
    const current = parent.createDiv({ cls: "external-project-current" });
    if (this.pathValue) {
      current.createEl("div", {
        text: `当前监控项目：${this.pathValue}`,
      });
      current.createEl("div", {
        text: `访问等级：${accessLevelLabel(this.levelValue)}`,
      });
    } else {
      current.createEl("div", { text: "当前会话未注册监控项目（纯 Vault 对话）。" });
    }
  }

  private renderPathInput(parent: HTMLElement): void {
    new Setting(parent)
      .setName("监控项目目录")
      .setDesc("绝对路径，例如 D:\\code\\my-app。留空并应用可解除监控。")
      .addText((text) => {
        text.setPlaceholder("/绝对/路径/到/项目");
        text.setValue(this.pathValue);
        text.onChange((value) => {
          this.pathValue = value;
        });
        text.inputEl.style.width = "100%";
      });
  }

  private renderLevelSelect(parent: HTMLElement): void {
    new Setting(parent)
      .setName("访问等级")
      .setDesc("控制对监控项目的写入与 shell 能力；Vault 始终可读写。")
      .addDropdown((dropdown) => {
        for (const level of this.levels) {
          dropdown.addOption(level, accessLevelLabel(level));
        }
        dropdown.setValue(this.levelValue);
        dropdown.onChange((value) => {
          this.levelValue = value;
        });
      });
  }

  private async renderBindings(parent: HTMLElement): Promise<void> {
    const section = parent.createDiv({ cls: "external-project-bindings" });
    section.createEl("h3", { text: "已保存的监控绑定" });
    section.createEl("p", {
      cls: "external-project-hint",
      text:
        "绑定把 Vault 内的规划目录映射到监控的外部代码目录，便于快速复用。" +
        "点击某条绑定可填入上方路径。",
    });

    const listEl = section.createDiv({ cls: "external-project-binding-list" });
    listEl.setText("加载中...");

    let bindings: ProjectBinding[] = [];
    try {
      bindings = await this.deps.client.listProjectBindings();
    } catch (err) {
      listEl.empty();
      listEl.setText(
        `加载绑定失败：${err instanceof Error ? err.message : String(err)}`,
      );
      this.renderBindForm(section);
      return;
    }

    listEl.empty();
    if (bindings.length === 0) {
      listEl.createEl("div", {
        cls: "external-project-binding-empty",
        text: "暂无保存的绑定。",
      });
    }

    for (const binding of bindings) {
      const row = listEl.createDiv({ cls: "external-project-binding-row" });
      const info = row.createDiv({ cls: "external-project-binding-info" });
      info.createEl("div", {
        cls: "external-project-binding-external",
        text: binding.external_path,
      });
      info.createEl("div", {
        cls: "external-project-binding-vault",
        text: binding.vault_dir
          ? `↔ Vault: ${binding.vault_dir}`
          : "（未绑定 Vault 目录）",
      });

      const useBtn = row.createEl("button", { text: "使用" });
      useBtn.addEventListener("click", () => {
        this.pathValue = binding.external_path;
        this.bindVaultDir = binding.vault_dir;
        void this.render();
      });

      const removeBtn = row.createEl("button", {
        cls: "mod-warning",
        text: "删除",
      });
      removeBtn.addEventListener("click", () => {
        void this.handleRemoveBinding(binding);
      });
    }

    this.renderBindForm(section);
  }

  private renderBindForm(section: HTMLElement): void {
    new Setting(section)
      .setName("将当前路径绑定到 Vault 目录")
      .setDesc("可选。填写 Vault 内相对目录（如 Projects/MyApp）后点击保存绑定。")
      .addText((text) => {
        text.setPlaceholder("Vault 相对目录，可留空");
        text.setValue(this.bindVaultDir);
        text.onChange((value) => {
          this.bindVaultDir = value;
        });
      })
      .addButton((button) => {
        button.setButtonText("保存绑定");
        button.onClick(() => {
          void this.handleSaveBinding();
        });
      });
  }

  private async handleSaveBinding(): Promise<void> {
    const externalPath = this.pathValue.trim();
    if (!externalPath) {
      new Notice("请先填写监控项目目录再保存绑定。");
      return;
    }
    try {
      await this.deps.client.upsertProjectBinding({
        external_path: externalPath,
        vault_dir: this.bindVaultDir.trim(),
      });
      new Notice("绑定已保存。");
      void this.render();
    } catch (err) {
      new Notice(
        `保存绑定失败：${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  private async handleRemoveBinding(binding: ProjectBinding): Promise<void> {
    try {
      await this.deps.client.removeProjectBinding({
        vault_dir: binding.vault_dir,
        external_path: binding.external_path,
      });
      new Notice("绑定已删除。");
      void this.render();
    } catch (err) {
      new Notice(
        `删除绑定失败：${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  private renderActions(parent: HTMLElement): void {
    const actions = parent.createDiv({ cls: "external-project-actions" });

    const clearBtn = actions.createEl("button", {
      cls: "mod-muted",
      text: "解除监控",
    });
    clearBtn.addEventListener("click", () => {
      void this.applyClear();
    });

    const applyBtn = actions.createEl("button", {
      cls: "mod-cta",
      text: "应用到当前会话",
    });
    applyBtn.addEventListener("click", () => {
      void this.applySettings();
    });
  }

  private async applyClear(): Promise<void> {
    if (!this.sessionId) {
      new Notice("当前没有可用会话。");
      return;
    }
    try {
      const session = await this.deps.client.patchSession(this.sessionId, {
        clear_external_project: true,
      });
      new Notice("已解除监控项目，恢复纯 Vault 对话。");
      this.deps.onApplied(session);
      this.close();
    } catch (err) {
      new Notice(
        `操作失败：${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  private async applySettings(): Promise<void> {
    if (!this.sessionId) {
      new Notice("当前没有可用会话。");
      return;
    }
    const externalPath = this.pathValue.trim();

    // Empty path means "detach"; mirror the clear action for clarity.
    if (!externalPath) {
      await this.applyClear();
      return;
    }

    // Validate the path before patching so the user gets a clean error.
    try {
      const result = await this.deps.client.validateProjectPath(externalPath);
      if (!result.valid) {
        new Notice(result.error || "路径无效。");
        return;
      }
    } catch (err) {
      new Notice(
        `校验路径失败：${err instanceof Error ? err.message : String(err)}`,
      );
      return;
    }

    try {
      const session = await this.deps.client.patchSession(this.sessionId, {
        external_project_path: externalPath,
        external_access_level: this.levelValue,
      });
      new Notice("监控项目已应用到当前会话。");
      this.deps.onApplied(session);
      this.close();
    } catch (err) {
      new Notice(
        `操作失败：${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }
}

export function openExternalProjectModal(deps: ExternalProjectModalDeps): void {
  new ExternalProjectModal(deps).open();
}
