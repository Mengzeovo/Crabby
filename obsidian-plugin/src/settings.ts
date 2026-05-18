import { App, Notice, PluginSettingTab, Setting } from "obsidian";

import { AgentClient, type MCPRuntimeStatus } from "./api/client";
import {
  deleteLlmProfileFromBackend,
  readEnvValue,
  resolveBackendEnvPath,
  saveLlmProfileToBackend,
} from "./config/backendConfig";
import {
  findModelPreset,
  getDefaultModelForProvider,
  getLlmProviderPreset,
  getReasoningEffortHint,
  LLM_PROVIDER_IDS,
  type LlmProviderCapabilities,
  type LlmProviderId,
  type LlmModelPreset,
} from "./config/llmProviders";
import {
  createMcpConfigFromExample,
  fetchMcpRuntimeStatus,
  formatMcpRuntimeStatus,
  loadMcpConfigLocally,
  reloadMcpConfigLocally,
  resolveBackendMcpConfigPath,
  saveMcpConfigLocally,
  validateMcpConfigText,
} from "./config/mcpConfig";
import type CrabbyPlugin from "./main";

export interface LlmProfile {
  id: string;
  name: string;
  provider: LlmProviderId;
  model: string;
  baseUrl: string;
  apiKey: string;
  supportsVision: boolean;
  thinkingMode: string;
  thinkingEffort: string;
  thinkingBudgetTokens: string;
  reasoningSplit: boolean;
}

export interface CrabbySettings {
  backendUrl: string;
  backendEnvPath: string;
  backendMcpConfigPath: string;
  runtimeManifestUrl: string;
  /** Legacy fallback only. */
  backendPath: string;
  llmProfiles: LlmProfile[];
  activeProfileId: string;
}

function applyKnownModelCapabilities(profile: LlmProfile): void {
  const modelPreset = findModelPreset(profile.provider, profile.model);
  if (!modelPreset) {
    return;
  }

  if (typeof modelPreset.supportsVision === "boolean") {
    profile.supportsVision = modelPreset.supportsVision;
  }
  if (modelPreset.supportsThinking === false) {
    profile.thinkingMode = "";
  }
}

function getEffectiveProfileCapabilities(
  profile: LlmProfile,
): {
  activePreset: ReturnType<typeof getLlmProviderPreset>;
  capabilities: LlmProviderCapabilities;
  modelPreset: LlmModelPreset | undefined;
} {
  const activePreset = getLlmProviderPreset(profile.provider);
  const modelPreset = findModelPreset(profile.provider, profile.model);
  const capabilities: LlmProviderCapabilities = {
    ...activePreset.capabilities,
  };

  if (modelPreset && typeof modelPreset.supportsVision === "boolean") {
    capabilities.vision = capabilities.vision && modelPreset.supportsVision;
  }
  if (modelPreset && typeof modelPreset.supportsThinking === "boolean") {
    capabilities.thinking = capabilities.thinking && modelPreset.supportsThinking;
  }

  return { activePreset, capabilities, modelPreset };
}

export const DEFAULT_SETTINGS: CrabbySettings = {
  backendUrl: "http://127.0.0.1:8000",
  backendEnvPath: "",
  backendMcpConfigPath: "",
  runtimeManifestUrl: "",
  backendPath: "",
  llmProfiles: [],
  activeProfileId: "",
};

function createCollapsibleSection(
  containerEl: HTMLElement,
  summaryText: string,
  open = false,
): HTMLDivElement {
  const detailsEl = containerEl.createEl("details");
  detailsEl.open = open;
  detailsEl.style.marginBottom = "10px";

  const summaryEl = detailsEl.createEl("summary", { text: summaryText });
  summaryEl.style.cursor = "pointer";
  summaryEl.style.fontWeight = "600";
  summaryEl.style.marginBottom = "8px";

  const contentEl = detailsEl.createDiv();
  contentEl.style.marginTop = "10px";
  return contentEl;
}

function formatReloadStatusLabel(status: MCPRuntimeStatus): string {
  if (status.last_reload_ok === undefined || status.last_reload_ok === null) {
    return "尚未执行";
  }
  return status.last_reload_ok ? "成功" : "失败";
}

function formatMcpRuntimeSummary(status: MCPRuntimeStatus): string {
  const totalTools = Object.values(status.tools_by_server).reduce(
    (sum, toolNames) => sum + toolNames.length,
    0,
  );
  const connectedServers =
    status.connected_servers.length > 0
      ? status.connected_servers.join("、")
      : "无";

  const lines = [
    `连接状态：${status.connected_servers.length > 0 ? `已连接 ${status.connected_servers.length} 个服务` : "当前没有已连接服务"}`,
    `服务列表：${connectedServers}`,
    `工具总数：${totalTools}`,
    `最近重载：${formatReloadStatusLabel(status)}${status.last_reload_at ? ` · ${status.last_reload_at}` : ""}`,
  ];

  if (status.vault_tools_enabled) {
    const vt = status.vault_tools_tools ?? [];
    lines.push(
      `Vault 工具集：${vt.length > 0 ? `已启用，已加载 ${vt.length} 个工具（${vt.join("、")}）` : "已启用，工具目录为空"}`,
    );
  } else {
    lines.push("Vault 工具集：未启用");
  }

  if (status.last_reload_error) {
    lines.push(`错误信息：${status.last_reload_error}`);
  }

  return lines.join("\n");
}

export class CrabbySettingTab extends PluginSettingTab {
  constructor(app: App, private plugin: CrabbyPlugin) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    containerEl.createEl("h2", { text: "Crabby 设置" });

    this.renderRuntimeSection(containerEl);
    this.renderMcpSection(containerEl);
    this.renderLlmSection(containerEl);
  }

  private renderRuntimeSection(containerEl: HTMLElement): void {
    containerEl.createEl("h3", { text: "后端运行时" });

    const manager = this.plugin.runtimeManager;
    if (!manager) {
      containerEl.createDiv().setText("后端运行时管理器不可用。");
      return;
    }

    let manifestUrlDraft = this.plugin.settings.runtimeManifestUrl;
    const statusEl = containerEl.createEl("pre");
    Object.assign(statusEl.style, {
      backgroundColor: "var(--background-secondary)",
      border: "1px solid var(--background-modifier-border)",
      borderRadius: "6px",
      padding: "10px 12px",
      whiteSpace: "pre-wrap",
      fontSize: "12px",
      lineHeight: "1.5",
    });

    let renderStatusRequestId = 0;
    const renderStatus = async () => {
      const requestId = ++renderStatusRequestId;
      const status = manager.getStatus();
      const setStatusText = (healthText: string) => {
        statusEl.setText(
          [
            `模式：${status.mode === "dev" ? "开发模式" : "生产模式"}`,
            `运行时已安装：${status.installed ? "是" : "否"}`,
            `后端进程：${status.running ? "运行中" : "未运行"}`,
            `连接状态：${healthText}`,
            `后端地址：${status.backendUrl}`,
            `PID: ${status.pid ?? "-"}`,
            `Prompt config: ${status.promptsDir}`,
            `Persona config: ${status.personasDir}`,
            `.env 文件：${status.envPath}`,
            `MCP 配置：${status.mcpConfigPath}`,
            `数据目录：${status.dataDir}`,
            `日志目录：${status.logsDir}`,
            `状态：${status.detail}`,
          ].join("\n"),
        );
      };

      setStatusText("正在检查...");
      const client = new AgentClient(status.backendUrl);
      try {
        const isHealthy = await client.health();
        if (requestId === renderStatusRequestId) {
          setStatusText(isHealthy ? "可访问（/health 正常）" : "不可访问");
        }
      } catch (error) {
        if (requestId === renderStatusRequestId) {
          const message = error instanceof Error ? error.message : String(error);
          setStatusText(`不可访问：${message}`);
        }
      }
    };

    new Setting(containerEl)
      .setName("运行时清单 URL")
      .setDesc("生产模式用于下载后端运行时。开发模式会优先使用 .dev-runtime.json。")
      .addText((text) => {
        text
          .setPlaceholder("https://example.com/life-assistant/runtime-manifest.json")
          .setValue(manifestUrlDraft)
          .onChange((value) => {
            manifestUrlDraft = value.trim();
          });
        text.inputEl.style.width = "420px";
      })
      .addButton((button) => {
        button.setButtonText("保存");
        button.onClick(async () => {
          this.plugin.settings.runtimeManifestUrl = manifestUrlDraft;
          await this.plugin.saveSettings();
          new Notice("运行时清单 URL 已保存。");
        });
      });

    new Setting(containerEl)
      .setName("安装后端运行时")
      .setDesc("下载并校验当前平台对应的后端运行时。")
      .addButton((button) => {
        button.setButtonText("安装");
        button.onClick(async () => {
          button.setDisabled(true);
          try {
            this.plugin.settings.runtimeManifestUrl = manifestUrlDraft;
            await this.plugin.saveSettings();
            await manager.installRuntime(manifestUrlDraft);
            new Notice("后端运行时已安装。");
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            new Notice(`运行时安装失败：${message}`);
          } finally {
            button.setDisabled(false);
            await renderStatus();
          }
        });
      });

    new Setting(containerEl)
      .setName("后端进程")
      .setDesc("控制由当前插件管理的本地后端进程。")
      .addButton((button) => {
        button.setButtonText("启动");
        button.onClick(async () => {
          button.setDisabled(true);
          try {
            await manager.start();
            await this.plugin.saveSettings();
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            new Notice(`后端启动失败：${message}`);
          } finally {
            button.setDisabled(false);
            await renderStatus();
          }
        });
      })
      .addButton((button) => {
        button.setButtonText("重启");
        button.onClick(async () => {
          button.setDisabled(true);
          try {
            await manager.restart();
            await this.plugin.saveSettings();
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            new Notice(`后端重启失败：${message}`);
          } finally {
            button.setDisabled(false);
            await renderStatus();
          }
        });
      })
      .addButton((button) => {
        button.setButtonText("停止");
        button.onClick(async () => {
          button.setDisabled(true);
          try {
            await manager.stop();
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            new Notice(`后端停止失败：${message}`);
          } finally {
            button.setDisabled(false);
            await renderStatus();
          }
        });
      })
      .addButton((button) => {
        button.setButtonText("刷新");
        button.onClick(() => {
          void renderStatus();
        });
      });

    void renderStatus();
  }

  private renderMcpSection(containerEl: HTMLElement): void {
    containerEl.createEl("h3", { text: "MCP 服务与工具" });

    let draftMcpConfigPath = this.plugin.settings.backendMcpConfigPath;
    const backendUrl = () =>
      this.plugin.settings.backendUrl || DEFAULT_SETTINGS.backendUrl;

    const settingsWithDraftPath = (): CrabbySettings => ({
      ...this.plugin.settings,
      backendMcpConfigPath: draftMcpConfigPath,
    });

    const pathHint = containerEl.createDiv({ cls: "mcp-config-hint" });
    Object.assign(pathHint.style, {
      fontSize: "12px",
      color: "var(--text-muted)",
      marginBottom: "10px",
      lineHeight: "1.5",
      whiteSpace: "pre-wrap",
      wordBreak: "break-word",
    });

    const runtimeSummaryEl = containerEl.createDiv({ cls: "mcp-runtime-summary" });
    Object.assign(runtimeSummaryEl.style, {
      backgroundColor: "var(--background-secondary)",
      border: "1px solid var(--background-modifier-border)",
      borderRadius: "8px",
      padding: "12px 14px",
      marginBottom: "10px",
      fontSize: "12px",
      lineHeight: "1.6",
      whiteSpace: "pre-wrap",
      color: "var(--text-normal)",
    });
    runtimeSummaryEl.setText("正在读取 MCP 运行状态...");

    const statusEl = containerEl.createDiv({ cls: "mcp-status-bar" });
    statusEl.style.fontSize = "12px";
    statusEl.style.color = "var(--text-muted)";
    statusEl.style.marginBottom = "10px";
    statusEl.style.minHeight = "18px";

    const runtimeDetailsEl = createCollapsibleSection(
      containerEl,
      "查看服务与工具详情",
    );
    const runtimeStatusEl = runtimeDetailsEl.createEl("pre", {
      cls: "mcp-runtime-status",
    });
    Object.assign(runtimeStatusEl.style, {
      backgroundColor: "var(--background-secondary)",
      border: "1px solid var(--background-modifier-border)",
      borderRadius: "6px",
      padding: "10px 12px",
      marginBottom: "0",
      fontSize: "12px",
      fontFamily: "var(--font-monospace)",
      whiteSpace: "pre-wrap",
      wordBreak: "break-word",
      lineHeight: "1.5",
      color: "var(--text-normal)",
    });
    runtimeStatusEl.setText("正在读取 MCP 运行状态...");

    const updatePathHint = () => {
      const resolution = resolveBackendMcpConfigPath(settingsWithDraftPath());
      if (!resolution.ok || !resolution.configPath) {
        pathHint.setText(resolution.message);
        return;
      }

      const sourceLabel = resolution.derivedFromBackendEnvPath
        ? "自动从插件配置目录推导"
        : "手动覆盖路径";
      const exampleText = resolution.examplePath
        ? `\n模板文件：${resolution.examplePath}`
        : "";
      pathHint.setText(
        `当前 MCP 配置文件：${resolution.configPath}\n路径来源：${sourceLabel}${exampleText}`,
      );
    };

    const persistDraftMcpPath = async (): Promise<void> => {
      this.plugin.settings.backendMcpConfigPath = draftMcpConfigPath;
      await this.plugin.saveSettings();
    };

    const setRuntimeStatus = async (): Promise<void> => {
      const loadingText = "正在读取 MCP 运行状态...";
      runtimeSummaryEl.setText(loadingText);
      runtimeStatusEl.setText(loadingText);
      try {
        const client = new AgentClient(backendUrl());
        const result = await fetchMcpRuntimeStatus(settingsWithDraftPath(), client);
        if (result.ok && result.status) {
          runtimeSummaryEl.setText(formatMcpRuntimeSummary(result.status));
          runtimeStatusEl.setText(formatMcpRuntimeStatus(result.status));
        } else {
          runtimeSummaryEl.setText(result.message);
          runtimeStatusEl.setText(result.message);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        const failureMessage = `读取 MCP 运行状态失败：${message}`;
        runtimeSummaryEl.setText(failureMessage);
        runtimeStatusEl.setText(failureMessage);
      }
    };

    new Setting(containerEl)
      .setName("刷新运行状态")
      .setDesc("重新读取后端当前已连接的 MCP 服务和工具。")
      .addButton((button) => {
        button.setButtonText("刷新");
        button.onClick(() => {
          void setRuntimeStatus();
        });
      });

    const advancedPathSectionEl = createCollapsibleSection(
      containerEl,
      "高级路径覆盖",
      Boolean(draftMcpConfigPath),
    );

    new Setting(advancedPathSectionEl)
      .setName("MCP 配置文件路径")
      .setDesc("一般不需要设置。仅在 mcp_servers.json 不在默认位置（<vault>/.crabby/config/server/data/）时手动填写。")
      .addText((text) => {
        text
          .setPlaceholder("D:\\path\\to\\Crabby\\server\\data\\mcp_servers.json")
          .setValue(draftMcpConfigPath)
          .onChange((value) => {
            draftMcpConfigPath = value.trim();
            updatePathHint();
          });
        text.inputEl.style.width = "320px";
      });

    const editorSectionEl = createCollapsibleSection(
      containerEl,
      "编辑 mcp_servers.json",
    );

    const editor = editorSectionEl.createEl("textarea", {
      cls: "mcp-config-editor",
    });
    Object.assign(editor.style, {
      width: "100%",
      minHeight: "280px",
      boxSizing: "border-box",
      padding: "10px 12px",
      marginBottom: "10px",
      borderRadius: "6px",
      border: "1px solid var(--background-modifier-border)",
      backgroundColor: "var(--background-primary)",
      color: "var(--text-normal)",
      fontFamily: "var(--font-monospace)",
      fontSize: "12px",
      lineHeight: "1.5",
      resize: "vertical",
    });
    editor.placeholder = '{\n  "mcpServers": {}\n}\n';

    const loadEditorFromDisk = () => {
      const result = loadMcpConfigLocally(settingsWithDraftPath());
      if (result.ok) {
        editor.value = result.text ?? "";
      }
      statusEl.setText(result.message);
      updatePathHint();
    };

    new Setting(editorSectionEl)
      .setName("从文件载入")
      .setDesc("把磁盘上的 mcp_servers.json 重新载入到编辑器。")
      .addButton((button) => {
        button.setButtonText("载入");
        button.onClick(() => {
          loadEditorFromDisk();
        });
      });

    new Setting(editorSectionEl)
      .setName("从模板创建")
      .setDesc("当真实配置文件不存在时，根据 mcp_servers.example.json 创建。")
      .addButton((button) => {
        button.setButtonText("创建");
        button.onClick(async () => {
          await persistDraftMcpPath();
          const result = createMcpConfigFromExample(this.plugin.settings);
          if (result.ok) {
            editor.value = result.text ?? "";
            statusEl.setText(result.message);
            new Notice("已根据模板创建 MCP 配置文件。");
            await setRuntimeStatus();
          } else {
            statusEl.setText(result.message);
            new Notice(`创建失败：${result.message}`);
          }
          updatePathHint();
        });
      });

    new Setting(editorSectionEl)
      .setName("本地校验")
      .setDesc("只校验 JSON 语法和 MCP 配置结构，不会写入后端。")
      .addButton((button) => {
        button.setButtonText("校验");
        button.onClick(() => {
          const result = validateMcpConfigText(editor.value);
          statusEl.setText(result.message);
          if (result.ok) {
            new Notice("MCP 配置校验通过。");
          } else {
            new Notice(`校验失败：${result.message}`);
          }
        });
      });

    new Setting(editorSectionEl)
      .setName("保存配置")
      .setDesc("把编辑器内容写入 mcp_servers.json（需要先在高级路径覆盖里配置路径，或配置好 .env）。")
      .addButton((button) => {
        button.setButtonText("保存");
        button.onClick(async () => {
          await persistDraftMcpPath();
          const result = saveMcpConfigLocally(this.plugin.settings, editor.value);
          statusEl.setText(result.message);
          if (result.ok) {
            new Notice("MCP 配置已保存。");
          } else {
            new Notice(`保存失败：${result.message}`);
          }
          updatePathHint();
        });
      })
      .addButton((button) => {
        button.setButtonText("保存并重载");
        button.setCta();
        button.onClick(async () => {
          await persistDraftMcpPath();

          const saveResult = saveMcpConfigLocally(this.plugin.settings, editor.value);
          if (!saveResult.ok) {
            statusEl.setText(saveResult.message);
            new Notice(`保存失败：${saveResult.message}`);
            updatePathHint();
            return;
          }

          statusEl.setText(`${saveResult.message} 正在重载后端...`);
          const client = new AgentClient(backendUrl());
          const reloadResult = await reloadMcpConfigLocally(
            this.plugin.settings,
            client,
          );
          statusEl.setText(reloadResult.message);
          if (reloadResult.ok) {
            new Notice("MCP 配置已保存，并完成后端重载。");
          } else {
            new Notice(`重载失败：${reloadResult.message}`);
          }
          await setRuntimeStatus();
          updatePathHint();
        });
      });

    updatePathHint();
    loadEditorFromDisk();
    void setRuntimeStatus();
  }

  private renderLlmSection(containerEl: HTMLElement): void {
    containerEl.createEl("h3", { text: "LLM 配置" });

    const resolution = resolveBackendEnvPath(this.plugin.settings);
    const configHint = containerEl.createDiv({ cls: "llm-config-hint" });
    configHint.style.fontSize = "12px";
    configHint.style.marginBottom = "10px";
    if (resolution.ok && resolution.envPath) {
      configHint.style.color = "var(--text-muted)";
      configHint.setText(`当前生效配置文件：${resolution.envPath}`);
    } else {
      configHint.style.color = "var(--text-accent)";
      configHint.style.fontWeight = "600";
      configHint.setText(resolution.message);
    }

    const statusEl = containerEl.createDiv({ cls: "llm-status-bar" });
    statusEl.style.fontSize = "12px";
    statusEl.style.color = "var(--text-muted)";
    statusEl.style.marginBottom = "10px";
    statusEl.style.minHeight = "18px";

    const profileListEl = containerEl.createDiv({ cls: "llm-profile-list" });
    profileListEl.style.marginBottom = "4px";

    const backendUrl = () =>
      this.plugin.settings.backendUrl || DEFAULT_SETTINGS.backendUrl;

    const refreshProfilesFromBackend = async (): Promise<void> => {
      statusEl.setText("正在从后端读取 LLM 配置...");
      try {
        const result = await this.plugin.syncLlmProfilesFromBackend({
          migrateLocalProfiles: true,
        });
        statusEl.setText(result.message);
        if (result.ok) {
          renderProfiles();
          updateStatusFromActiveProfile();
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        statusEl.setText(`读取后端 LLM 配置失败：${message}`);
      }
    };

    const updateStatusFromActiveProfile = () => {
      const activeProfile = this.plugin.settings.llmProfiles.find(
        (profile) => profile.id === this.plugin.settings.activeProfileId,
      );

      if (activeProfile) {
        statusEl.setText(
          `当前启用：${activeProfile.name}（${activeProfile.provider} / ${activeProfile.model}）`,
        );
      } else if (this.plugin.settings.llmProfiles.length > 0) {
        statusEl.setText("当前还没有选中的配置。");
      } else {
        statusEl.setText("当前还没有创建任何 LLM 配置。");
      }
    };

    const applyProfileToBackend = async (
      profile: LlmProfile,
    ): Promise<boolean> => {
      statusEl.setText(`正在应用 ${profile.name} ...`);
      const client = new AgentClient(backendUrl());

      try {
        const result = await saveLlmProfileToBackend(
          this.plugin.settings,
          profile,
          client,
          true,
        );
        statusEl.setText(result.message);
        if (result.ok) {
          await this.plugin.saveSettings();
          renderProfiles();
          new Notice(`已切换到 ${profile.name}。`);
          return true;
        } else {
          renderProfiles();
          new Notice(`切换失败：${result.message}`);
          return false;
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        statusEl.setText(`切换失败：${message}`);
        renderProfiles();
        new Notice(`切换失败：${message}`);
        return false;
      }
    };

    const saveProfile = async (profile: LlmProfile): Promise<void> => {
      const activate = profile.id === this.plugin.settings.activeProfileId;
      statusEl.setText(`正在保存 ${profile.name} 到后端...`);
      const client = new AgentClient(backendUrl());

      try {
        const result = await saveLlmProfileToBackend(
          this.plugin.settings,
          profile,
          client,
          activate,
        );
        statusEl.setText(result.message);
        if (result.ok) {
          await this.plugin.saveSettings();
          renderProfiles();
          updateStatusFromActiveProfile();
          new Notice(`已保存 ${profile.name}。`);
        } else {
          new Notice(`保存失败：${result.message}`);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        statusEl.setText(`保存失败：${message}`);
        new Notice(`保存失败：${message}`);
      }
    };

    const testCurrentProfile = async (): Promise<void> => {
      const activeProfile = this.plugin.settings.llmProfiles.find(
        (profile) => profile.id === this.plugin.settings.activeProfileId,
      );

      const envResolution = resolveBackendEnvPath(this.plugin.settings);
      if (!envResolution.ok || !envResolution.envPath) {
        statusEl.setText(envResolution.message);
        return;
      }

      const adminToken = readEnvValue(
        envResolution.envPath,
        "CRABBY_ADMIN_TOKEN",
      )?.trim();
      if (!adminToken) {
        statusEl.setText(
          `无法测试当前 Profile：${envResolution.envPath} 缺少 CRABBY_ADMIN_TOKEN。`,
        );
        return;
      }

      const profileLabel = activeProfile
        ? `${activeProfile.name}（${activeProfile.provider} / ${activeProfile.model}）`
        : "后端当前已生效配置";
      statusEl.setText(
        `正在测试当前 Profile：${profileLabel}...`,
      );

      const client = new AgentClient(backendUrl());
      const result = await client.testCurrentProfile(adminToken);
      if (!result.ok || !result.data) {
        const message =
          result.status === null
            ? "后端当前不可访问。"
            : result.detail || `HTTP ${result.status}`;
        statusEl.setText(`测试失败：${message}`);
        new Notice(`测试失败：${message}`);
        return;
      }

      statusEl.setText(result.data.message);
      new Notice(result.data.ok ? result.data.message : `测试未通过：${result.data.message}`);
    };

    const renderProfiles = () => {
      profileListEl.empty();

      if (this.plugin.settings.llmProfiles.length === 0) {
        const emptyState = profileListEl.createDiv();
        emptyState.setText("还没有配置。点击“添加配置”创建一个新的 LLM 配置。");
        emptyState.style.color = "var(--text-muted)";
        emptyState.style.fontStyle = "italic";
        emptyState.style.padding = "8px 0";
        return;
      }

      this.plugin.settings.llmProfiles.forEach((profile, index) => {
        applyKnownModelCapabilities(profile);
        const isActive = profile.id === this.plugin.settings.activeProfileId;

        const card = profileListEl.createDiv({ cls: "llm-profile-card" });
        Object.assign(card.style, {
          border: `1px solid ${isActive ? "var(--interactive-accent)" : "var(--background-modifier-border)"}`,
          borderRadius: "8px",
          padding: "12px 16px",
          marginBottom: "10px",
          backgroundColor: isActive
            ? "var(--background-secondary-alt)"
            : "var(--background-secondary)",
          transition: "border-color 0.15s, background-color 0.15s",
        });

        const headerRow = card.createDiv();
        Object.assign(headerRow.style, {
          display: "flex",
          alignItems: "center",
          gap: "8px",
          marginBottom: "10px",
          flexWrap: "wrap",
        });

        const activeBadge = headerRow.createSpan();
        activeBadge.style.fontSize = "16px";
        activeBadge.style.cursor = "pointer";
        activeBadge.title = isActive
          ? "这个配置当前已启用。"
          : "点击启用这个配置，并热重载后端。";
        activeBadge.setText(isActive ? "●" : "○");
        activeBadge.addEventListener("click", async () => {
          await applyProfileToBackend(profile);
        });

        const titleEl = headerRow.createEl("strong");
        const getProfileTitle = () => profile.name || `\u914d\u7f6e ${index + 1}`;
        titleEl.setText(getProfileTitle());
        titleEl.style.flex = "1";
        titleEl.style.fontSize = "14px";

        const providerColors: Record<string, string> = Object.fromEntries(
          LLM_PROVIDER_IDS.map((providerId) => [
            providerId,
            getLlmProviderPreset(providerId).badge,
          ]),
        );
        const providerBadge = headerRow.createSpan();
        Object.assign(providerBadge.style, {
          fontSize: "11px",
          padding: "2px 8px",
          borderRadius: "12px",
          backgroundColor: providerColors[profile.provider],
          color: "#fff",
          fontWeight: "600",
          letterSpacing: "0.03em",
        });
        const updateProviderBadge = () => {
          const provider = String(profile.provider || "");
          providerBadge.setText(provider.toUpperCase() || "UNKNOWN");
          providerBadge.style.backgroundColor =
            providerColors[provider] ?? "var(--text-muted)";
        };
        updateProviderBadge();

        const saveBtn = headerRow.createEl("button");
        saveBtn.setText("保存");
        saveBtn.title = isActive
          ? "保存这个配置，并立即应用到后端。"
          : "把这个配置保存到后端。";
        saveBtn.addEventListener("click", () => {
          void saveProfile(profile);
        });

        const deleteBtn = headerRow.createEl("button");
        deleteBtn.setText("删除");
        deleteBtn.title = "删除这个配置。";
        deleteBtn.addEventListener("click", async () => {
          statusEl.setText(`正在从后端删除 ${profile.name}...`);
          const client = new AgentClient(backendUrl());
          const result = await deleteLlmProfileFromBackend(
            this.plugin.settings,
            profile.id,
            client,
          );
          statusEl.setText(result.message);
          if (!result.ok) {
            new Notice(`删除失败：${result.message}`);
            return;
          }
          await this.plugin.saveSettings();
          renderProfiles();
          updateStatusFromActiveProfile();
          new Notice(`已删除 ${profile.name}。`);
        });

        {
          const { activePreset, capabilities } =
            getEffectiveProfileCapabilities(profile);

          const styleProfileRow = (row: HTMLDivElement) => {
            Object.assign(row.style, {
              display: "grid",
              gridTemplateColumns: "80px 1fr",
              alignItems: "center",
              gap: "8px",
              marginBottom: "6px",
            });
          };

          const styleProfileLabel = (labelEl: HTMLLabelElement) => {
            Object.assign(labelEl.style, {
              fontSize: "12px",
              color: "var(--text-muted)",
              textAlign: "right",
            });
          };

          const styleProfileControl = (control: HTMLElement) => {
            Object.assign(control.style, {
              width: "100%",
              boxSizing: "border-box",
              fontSize: "13px",
              padding: "4px 8px",
              borderRadius: "4px",
              border: "1px solid var(--background-modifier-border)",
              backgroundColor: "var(--background-primary)",
              color: "var(--text-normal)",
            });
          };

          const createTextRow = (
            parentEl: HTMLElement,
            label: string,
            value: string,
            placeholder: string,
            onInput: (value: string) => Promise<void>,
            type = "text",
          ): HTMLInputElement => {
            const row = parentEl.createDiv();
            styleProfileRow(row);

            const labelEl = row.createEl("label");
            labelEl.setText(label);
            styleProfileLabel(labelEl);

            const input = row.createEl("input");
            input.type = type;
            input.placeholder = placeholder;
            input.value = value;
            styleProfileControl(input);
            input.addEventListener("input", async () => {
              await onInput(input.value);
              updateStatusFromActiveProfile();
            });
            return input;
          };

          const createCheckboxRow = (
            parentEl: HTMLElement,
            label: string,
            checked: boolean,
            onChange: (checked: boolean) => Promise<void>,
          ) => {
            const row = parentEl.createDiv();
            styleProfileRow(row);

            const labelEl = row.createEl("label");
            labelEl.setText(label);
            styleProfileLabel(labelEl);

            const inputWrap = row.createDiv();
            const input = inputWrap.createEl("input");
            input.type = "checkbox";
            input.checked = checked;
            input.addEventListener("change", async () => {
              await onChange(input.checked);
              updateStatusFromActiveProfile();
            });
          };

          createTextRow(card, "Name", profile.name, "Daily driver", async (value) => {
            profile.name = value;
            await this.plugin.saveSettings();
            titleEl.setText(getProfileTitle());
          });

          const providerRow = card.createDiv();
          styleProfileRow(providerRow);
          const providerLabel = providerRow.createEl("label");
          providerLabel.setText("Provider");
          styleProfileLabel(providerLabel);
          const providerSelect = providerRow.createEl("select");
          styleProfileControl(providerSelect);
          LLM_PROVIDER_IDS.forEach((providerId) => {
            const option = providerSelect.createEl("option");
            option.value = providerId;
            option.setText(getLlmProviderPreset(providerId).label);
          });
          providerSelect.value = profile.provider;
          providerSelect.addEventListener("change", async () => {
            profile.provider = providerSelect.value as LlmProviderId;
            const nextPreset = getLlmProviderPreset(profile.provider);
            const defaultModel = getDefaultModelForProvider(profile.provider);
            profile.model = defaultModel || profile.model;
            profile.baseUrl = nextPreset.defaultBaseUrl;
            applyKnownModelCapabilities(profile);
            if (!nextPreset.capabilities.thinking) {
              profile.thinkingMode = "";
            }
            if (!nextPreset.capabilities.thinkingBudget) {
              profile.thinkingBudgetTokens = "1024";
            }
            if (!nextPreset.capabilities.reasoningEffort) {
              profile.thinkingEffort = "";
            }
            if (!nextPreset.capabilities.reasoningSplit) {
              profile.reasoningSplit = false;
            }
            await this.plugin.saveSettings();
            renderProfiles();
            updateStatusFromActiveProfile();
          });

          const modelList = card.createEl("datalist");
          modelList.id = `llm-models-${profile.id}`;
          activePreset.models.forEach((model) => {
            const option = modelList.createEl("option");
            option.value = model.id;
            option.label = model.label;
          });
          const modelInput = createTextRow(
            card,
            "Model",
            profile.model,
            "Select or type a model id",
            async (value) => {
              profile.model = value.trim();
              applyKnownModelCapabilities(profile);
              await this.plugin.saveSettings();
            },
          );
          modelInput.setAttribute("list", modelList.id);
          modelInput.addEventListener("change", () => {
            renderProfiles();
            updateStatusFromActiveProfile();
          });

          if (capabilities.baseUrl) {
            createTextRow(
              card,
              "Base URL",
              profile.baseUrl,
              activePreset.defaultBaseUrl,
              async (value) => {
                profile.baseUrl = value.trim();
                await this.plugin.saveSettings();
              },
            );
          }

          if (capabilities.apiKey) {
            createTextRow(
              card,
              "API Key",
              profile.apiKey,
              activePreset.apiKeyEnv || "LLM_API_KEY",
              async (value) => {
                profile.apiKey = value.trim();
                await this.plugin.saveSettings();
              },
              "password",
            );
          }

          const hasAdvancedFields =
            capabilities.vision ||
            capabilities.thinking ||
            capabilities.thinkingBudget ||
            capabilities.reasoningEffort ||
            capabilities.reasoningSplit;
          if (hasAdvancedFields) {
            const advancedEl = card.createEl("details");
            advancedEl.style.marginTop = "8px";
            const summaryEl = advancedEl.createEl("summary");
            summaryEl.setText("Advanced");
            summaryEl.style.cursor = "pointer";
            summaryEl.style.fontSize = "12px";
            summaryEl.style.color = "var(--text-muted)";
            const advancedBody = advancedEl.createDiv();
            advancedBody.style.marginTop = "8px";

            if (capabilities.vision) {
              createCheckboxRow(
                advancedBody,
                "Vision",
                Boolean(profile.supportsVision),
                async (checked) => {
                  profile.supportsVision = checked;
                  await this.plugin.saveSettings();
                },
              );
            }

            if (capabilities.thinking) {
              createCheckboxRow(
                advancedBody,
                "Thinking",
                profile.thinkingMode.trim().toLowerCase() === "enabled",
                async (checked) => {
                  profile.thinkingMode = checked ? "enabled" : "";
                  await this.plugin.saveSettings();
                },
              );
            }

            if (capabilities.thinkingBudget) {
              createTextRow(
                advancedBody,
                "Budget",
                profile.thinkingBudgetTokens,
                "1024",
                async (value) => {
                  profile.thinkingBudgetTokens = value.trim();
                  await this.plugin.saveSettings();
                },
              );
            }

            if (capabilities.reasoningEffort) {
              createTextRow(
                advancedBody,
                "Effort",
                profile.thinkingEffort,
                getReasoningEffortHint(profile.provider),
                async (value) => {
                  profile.thinkingEffort = value.trim();
                  await this.plugin.saveSettings();
                },
              );
            }

            if (capabilities.reasoningSplit) {
              createCheckboxRow(
                advancedBody,
                "Split",
                Boolean(profile.reasoningSplit),
                async (checked) => {
                  profile.reasoningSplit = checked;
                  await this.plugin.saveSettings();
                },
              );
            }
          }
        }
      });
    };

    renderProfiles();
    updateStatusFromActiveProfile();
    void refreshProfilesFromBackend();

    new Setting(containerEl)
      .setName("刷新后端 Profile")
      .setDesc("重新从后端读取当前 LLM Profile 列表。")
      .addButton((button) => {
        button.setButtonText("刷新");
        button.onClick(() => {
          void refreshProfilesFromBackend();
        });
      });

    new Setting(containerEl)
      .setName("测试当前 Profile")
      .setDesc("校验后端当前已生效的 provider、model、key，并在 DeepSeek / MiniMax 上做一次低 token 真实探测。")
      .addButton((button) => {
        button.setButtonText("测试");
        button.onClick(() => {
          void testCurrentProfile();
        });
      });

    new Setting(containerEl)
      .setName("添加配置")
      .setDesc("新增一个 LLM 配置预设。")
      .addButton((button) => {
        button.setButtonText(resolution.ok ? "添加" : "请先初始化后端");
        button.setDisabled(!resolution.ok);
        button.onClick(async () => {
          const newProfile: LlmProfile = {
            id: crypto.randomUUID(),
            name: "新配置",
            provider: "anthropic",
            model: "claude-sonnet-4-20250514",
            baseUrl: "",
            apiKey: "",
            supportsVision: false,
            thinkingMode: "",
            thinkingEffort: "",
            thinkingBudgetTokens: "1024",
            reasoningSplit: false,
          };

          const activate = this.plugin.settings.llmProfiles.length === 0;
          statusEl.setText(`正在创建 ${newProfile.name}...`);
          const client = new AgentClient(backendUrl());
          const result = await saveLlmProfileToBackend(
            this.plugin.settings,
            newProfile,
            client,
            activate,
          );
          statusEl.setText(result.message);
          if (!result.ok) {
            new Notice(`添加失败：${result.message}`);
            return;
          }
          await this.plugin.saveSettings();
          renderProfiles();
          updateStatusFromActiveProfile();
        });
      });
  }
}
